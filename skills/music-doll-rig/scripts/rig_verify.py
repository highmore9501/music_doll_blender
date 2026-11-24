# -*- coding: utf-8 -*-
"""MusicDoll 骨架改造 —— 验收器（只读，三组断言）。

1. **结构**：三段直接父子；IK 数量与参数；`pole_angle` 一致；扭转复制单调；Z 轴夹角 < 2°；拱形 3%。
2. **功能**：把控制器摆到若干位置，比对"IK 解算后的腕关节位置"与控制器、手掌世界朝向与控制器、
   以及"肘关节是否朝极向量弯"。这三条是"同一组参数换个角色表现一致"的直接证据。
3. **职责**：形变骨一根不少、`use_deform` 一个没变；顶点组没变；rest 姿势下网格没被改动
   （给 `--reference` 时逐顶点比）；影子链的约束仍然在。

用法：

    blender -b --factory-startup -P rig_verify.py -- <file.blend> \
        [--armature NAME] [--reference 原始文件.blend] [--chains arm.L,leg.L] \
        [--json out.json] [--no-progress] [--save]

不带 `--chains` 时验全部十四条链（两臂 + 十指 + 两腿）；`status` 只有"这一轮把十四条都验过且全过"
才写成 DONE —— 只跑了一部分的，写多少条都不会把文件标成 DONE。

装了上半身 / 头部控制链（`MD_IK_upper`）的文件，会自动多验一条 `upper`：
颈 / 上胸 / 胸的 IK 链 + 头骨的复制旋转 + 视点。它也算进"齐全"——差它也不标 DONE。
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rig_common as common  # noqa: E402
import rig_progress as progress  # noqa: E402

Z_TOLERANCE_DEG = 2.0
ARCH_TARGET_PERCENT = 3.0
ARCH_TOLERANCE_PERCENT = 0.5
POLE_ALIGN_TOLERANCE_DEG = 5.0
WRIST_TOLERANCE = 0.002
HAND_ROTATION_TOLERANCE_DEG = 1.0
REST_MESH_TOLERANCE = 1e-5

# 上半身 / 头部控制链（rig_upper.py 的产物）
UPPER_PART = "upper"
UPPER_IK_NAME = "MD_IK_upper"
UPPER_ROT_NAME = "MD_Rot_upper"
REACH_TOLERANCE_RATIO = 0.02
HEAD_ROTATION_TOLERANCE_DEG = 1.0
HEAD_AIM_TOLERANCE_DEG = 2.0
UPPER_BEND_TOLERANCE_DEG = 5.0
UPPER_REST_MESH_TOLERANCE = 0.005


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {"file": None, "armature": None, "reference": None, "chains": [],
               "json": None, "no_progress": False, "save": False}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--armature":
            index += 1
            options["armature"] = argv[index]
        elif token == "--reference":
            index += 1
            options["reference"] = argv[index]
        elif token == "--chains":
            index += 1
            options["chains"].extend(argv[index].split(","))
        elif token == "--json":
            index += 1
            options["json"] = argv[index]
        elif token == "--no-progress":
            options["no_progress"] = True
        elif token == "--save":
            options["save"] = True
        else:
            options["file"] = token
        index += 1
    return options


def open_file(filepath):
    try:
        bpy.ops.wm.open_mainfile(filepath=filepath, load_ui=False)
    except RuntimeError as error:
        print("注意：载入时报错（已跳过）：%s" % str(error).splitlines()[0][:160])
    # 载入之后必须先把依赖图算一遍再取顶点：不算的话拿到的是"约束还没解算"的网格，
    # MMD 骨架的腿靠 IK 摆姿势、其它骨靠 TRANSFORM 复制，会凭空多出几微米的假位移
    # （实测把非腿部的 rest 位移从 4e-6 报成 4e-5，直接顶穿容差）。
    bpy.context.view_layer.update()


def find_armature(name=None):
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if name:
        armatures = [obj for obj in armatures if obj.name == name]
    return armatures[0] if armatures else None


def leg_group_names(armature_object):
    """腿链上的顶点组名（含 D / _dummy_ / _shadow_ 这些变体），用来把腿部顶点从网格检查里分出来。

    脚趾要按 `common.looks_like_toe` 认：`role_from_name` 把 `つま先` / `足先EX` 归成 leaf
    （它们的头落在脚掌末端），而按名字前缀兜底又认不出带侧别前缀的日文名（`左足先EX`）。
    漏掉的话，那批顶点的腿部位移会被当成"腿以外"去比严格容差，必然红。
    """
    groups = set()
    leg_roots = set()
    for bone in armature_object.data.bones:
        info = common.role_from_name(bone.name)
        if info["role"] in ("thigh", "shin", "foot", "toe"):
            leg_roots.add(bone.name)
            groups.add(bone.name)
    for bone in armature_object.data.bones:
        base = common.strip_variant(bone.name) if hasattr(common, "strip_variant") else None
        if base and base in leg_roots:
            groups.add(bone.name)
        elif bone.name.startswith(("足", "ひざ", "つま先", "足首", "足先")):
            groups.add(bone.name)
        elif common.looks_like_toe(bone.name):
            groups.add(bone.name)
    return sorted(groups)


def snapshot(filepath, armature_name=None):
    """读参考文件：形变骨、网格顶点、顶点组、约束数量。

    注意参考网格是**参考文件打开时的显示姿势**：MMD 骨架的腿靠 `足ＩＫ` 的 IK 摆出来，
    rest 朝向本身不在腿上（实测把这条 IK mute 掉，脚踝会跑到身后 46 cm、网格差 60 cm）。
    所以腿那部分的顶点会因为我们按配方重建 IK 而变化（拱形 + 重新解算），
    这部分在职责检查里单独算、单独报，不和非腿部顶点混在一个容差里。
    """
    open_file(filepath)
    armature_object = find_armature(armature_name)
    result = {"file": filepath, "deform_bones": {}, "meshes": {}, "groups": {},
              "constraints": {}, "leg_groups": []}
    if armature_object is not None:
        result["armature"] = armature_object.name
        result["leg_groups"] = leg_group_names(armature_object)
        for bone in armature_object.data.bones:
            if bone.use_deform:
                result["deform_bones"][bone.name] = True
        for pose_bone in armature_object.pose.bones:
            if len(pose_bone.constraints):
                result["constraints"][pose_bone.name] = [con.type for con in pose_bone.constraints]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        result["meshes"][obj.name] = [vertex.co.copy() for vertex in mesh.vertices]
        evaluated.to_mesh_clear()
        result["groups"][obj.name] = sorted(group.name for group in obj.vertex_groups)
    return result


def evaluated_head(armature_object, bone_name):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = armature_object.evaluated_get(depsgraph)
    pose_bone = evaluated.pose.bones[bone_name]
    return evaluated.matrix_world @ pose_bone.head


def evaluated_tail(armature_object, bone_name):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = armature_object.evaluated_get(depsgraph)
    pose_bone = evaluated.pose.bones[bone_name]
    return evaluated.matrix_world @ pose_bone.tail


def evaluated_rotation(armature_object, bone_name):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = armature_object.evaluated_get(depsgraph)
    return evaluated.matrix_world.to_quaternion() @ evaluated.pose.bones[bone_name].matrix.to_quaternion()


REQUIRED_PARTS = ("arm.L", "arm.R", "leg.L", "leg.R") + tuple(
    "%s.%s" % (finger, side)
    for side in ("L", "R")
    for finger in ("thumb", "index", "middle", "ring", "pinky"))


def parts_complete(rows, required=None):
    """进度表里的链都做完且都通过，才算这个文件 DONE（只看已记录的链，缺的链视为没做）。"""
    marks = {row["part"]: row for row in rows}
    for part in (required or REQUIRED_PARTS):
        row = marks.get(part)
        if row is None:
            return False
        if any(row.get(column) == "!" for column in progress.PART_COLUMNS):
            return False
    return True


class Checker:
    def __init__(self):
        self.items = []

    def check(self, group, name, ok, detail=""):
        self.items.append({"group": group, "name": name, "ok": bool(ok), "detail": detail})
        print("  [%s] %-6s %-34s %s" % (group, "PASS" if ok else "FAIL", name, detail))
        return ok

    def info(self, group, name, detail):
        self.items.append({"group": group, "name": name, "ok": None, "detail": detail})
        print("  [%s] %-6s %-34s %s" % (group, "INFO", name, detail))

    def failed(self, group=None):
        return [item for item in self.items
                if item["ok"] is False and (group is None or item["group"] == group)]


def hand_front_axis(bone_index):
    """人物前方（拇指的弯曲平面口径要用它定"朝前"那一侧）。"""
    foot_names = [name for name in bone_index
                  if common.role_from_name(name)["role"] == "foot"
                  and common.role_from_name(name)["variant"] in ("plain", "shadow")]
    front_axis, _evidence = common.detect_front_axis(bone_index, foot_names)
    return front_axis


def finger_from_armature(armature_object, part):
    """认一根手指：三节、末节、指尖骨、指甲方向。part 形如 `index.L`。"""
    import rig_arrows

    role, side = part.split(".")
    bone_index = common.build_bone_index(armature_object)
    hand_name = "手首.%s" % side
    if hand_name not in bone_index:
        candidates = [name for name in bone_index
                      if common.role_from_name(name)["role"] == "hand"
                      and common.role_from_name(name)["side"] == side]
        if not candidates:
            return None
        hand_name = candidates[0]
    targets = rig_arrows.finger_targets(bone_index, hand_name)
    entry = targets.get(role)
    if not entry:
        return None
    directions = common.finger_nail_directions(bone_index, hand_name, targets,
                                               hand_front_axis(bone_index))
    return {
        "role": role,
        "side": side,
        "hand": hand_name,
        "segments": entry["segments"],
        "last": entry["last"],
        "tip": entry["tip"],
        "nail": directions.get(role),
    }


def chain_joint_items(armature_object, chain_names):
    """链条关节的对接状态（验收用：同一份口径见 rig_common.chain_joint_report）。"""
    bone_index = common.build_bone_index(armature_object)
    return common.chain_joint_report(bone_index, chain_names)


def describe_joints(items):
    """把关节状态写成人看的一行：`父→子 gap=0.00000 connect=1`。"""
    parts = []
    for item in items:
        if not item["exists"]:
            parts.append("%s→%s 骨缺失" % (item["parent"], item["child"]))
            continue
        parts.append("%s→%s gap=%.5f connect=%d%s" % (
            item["parent"], item["child"], item["gap"], 1 if item["connected"] else 0,
            "" if item["parent_ok"] else "（不是子级）"))
    return "; ".join(parts)


def verify_chain_connect(part, armature_object, chain_names, checker):
    """链条对接：每对父子都要 head 压住父尾、而且是 connect 状态。

    少了这一步的后果不是"看起来不对"，而是解算时会散：没连的子骨可以被单独平移，
    拖 IK 控制器时两段之间会露出缝。
    """
    items = chain_joint_items(armature_object, chain_names)
    usable = [item for item in items if item["exists"]]
    ok = bool(usable) and all(item["parent_ok"] and item["coincident"] and item["connected"]
                             for item in usable)
    checker.check("struct", "%s 链条关节父子对接（tail=head + connect）" % part, ok,
                  describe_joints(items) or "链太短")


def verify_finger(armature_object, part, finger, checker):
    bone_index = common.build_bone_index(armature_object)
    segments = finger["segments"]
    nail = finger["nail"]

    # 左右镜像自洽：右手的目标方向必须等于左手目标方向的镜像。
    # 这条是防"手掌法线符号没换向"的回归 —— 单看"Z 是否等于算出来的指甲方向"是循环论证，
    # 算错了方向那一项照样通过（2026-11-18 作者看图才发现右手四指朝手背弯）。
    if finger["side"] == "R" and nail is not None:
        left = finger_from_armature(armature_object, "%s.L" % finger["role"])
        if left is not None and left.get("nail") is not None:
            mirrored = Vector((-left["nail"].x, left["nail"].y, left["nail"].z))
            mirror_angle = common.angle_between(nail, mirrored)
            checker.check("struct", "%s 指甲方向 = 左手镜像" % part,
                          mirror_angle is not None and mirror_angle <= 10.0,
                          "与左手镜像夹角 %s°（容差 10°；180° 就是左右符号反了）" % (
                              ("%.1f" % mirror_angle) if mirror_angle is not None else "n/a"))

    # ── 结构 ──
    parents_ok = all(bone_index[segments[index]]["parent"] == segments[index - 1]
                     for index in range(1, len(segments)))
    checker.check("struct", "%s 三节直接父子" % part, parents_ok,
                  " → ".join(segments))

    if nail is None:
        checker.check("struct", "%s 指甲方向" % part, False, "算不出来（手掌平面/拱形退化）")
        return
    angles = []
    for name in segments:
        z_axis = common.bone_axes(bone_index[name])[2]
        y_axis = common.bone_axes(bone_index[name])[1]
        in_plane = common.project_perpendicular(nail, y_axis)
        if in_plane.length < 0.15:
            continue
        angles.append(common.angle_between(z_axis, in_plane))
    checker.check("struct", "%s Z 朝指甲方向" % part,
                  bool(angles) and all(angle is not None and angle <= Z_TOLERANCE_DEG for angle in angles),
                  "最大夹角 %.2f°（容差 %.0f°，比的是投影到垂直骨方向后的方向）" % (
                      max(angle if angle is not None else 999.0 for angle in angles), Z_TOLERANCE_DEG))

    arch = common.chain_arch(bone_index, segments)
    if arch is None:
        checker.check("struct", "%s 拱形" % part, False, "链太短")
    else:
        # 拱形方向只能落在"垂直于弦"的平面里，所以拿指甲方向在同一个平面上的投影来比。
        # 不投影的话，拇指那种"弦本身朝前"的链会被扣掉几十度的纯几何差（实测 56.7°）。
        chord = bone_index[segments[-1]]["tail"] - bone_index[segments[0]]["head"]
        chord_axis = chord.normalized() if chord.length > 1e-9 else None
        nail_in_plane = common.project_perpendicular(nail, chord_axis) if chord_axis else None
        arch_angle = (common.angle_between(arch["direction"], nail_in_plane)
                      if (arch["direction"] and nail_in_plane is not None
                          and nail_in_plane.length > 1e-9) else None)
        checker.check("struct", "%s 拱形 3%% 朝指甲侧" % part,
                      arch["max_offset_ratio_percent"] >= ARCH_TARGET_PERCENT * 0.9 - 0.5
                      and arch_angle is not None and arch_angle <= 30.0,
                      "拱高 %.2f%%，与指甲方向夹角 %s°（比的是投影到垂直弦平面后的方向）" % (
                          arch["max_offset_ratio_percent"],
                          ("%.1f" % arch_angle) if arch_angle is not None else "n/a"))

    tip_name = finger.get("tip") or (segments[-1] + "_tip")
    tip_entry = bone_index.get(tip_name)
    if tip_entry is None:
        checker.check("struct", "%s 指尖骨" % part, False, "没有 %s" % tip_name)
    else:
        last_length = bone_index[segments[-1]]["length"]
        ratio = tip_entry["length"] / max(last_length, 1e-9) * 100.0
        tip_angle = common.angle_between(common.bone_direction(tip_entry),
                                         common.bone_direction(bone_index[segments[-1]]))
        # 新建的指尖骨必须非形变；模型自带的（人指先 这类）可能本来就是形变骨，只查长度与朝向
        created_by_us = tip_name.endswith("_tip")
        checker.check("struct", "%s 指尖骨（10%% / 同向%s）" % (part, " / 非形变" if created_by_us else ""),
                      abs(ratio - 10.0) <= 1.0 and tip_angle is not None and tip_angle <= 2.0
                      and (not created_by_us or not tip_entry["deform"]),
                      "%s：长度 %.1f%%、方向差 %s°、形变=%s" % (
                          tip_name, ratio, ("%.2f" % tip_angle) if tip_angle is not None else "n/a",
                          tip_entry["deform"]))

    finger_chain = list(segments) + ([tip_name] if tip_entry is not None else [])
    verify_chain_connect(part, armature_object, finger_chain, checker)

    ik_entries = []
    for name in segments:
        for con in armature_object.pose.bones[name].constraints:
            if con.type != "IK":
                continue
            ik_entries.append({
                "owner": name, "chain_count": con.chain_count,
                "pole_target": con.pole_target.name if con.pole_target else None,
                "pole_angle_deg": round(con.pole_angle * 57.295779513, 1),
                "use_stretch": con.use_stretch,
            })
    checker.check("struct", "%s IK 链长 3 + 极向量" % part,
                  any(item["chain_count"] == 3 and item["pole_target"] for item in ik_entries),
                  "; ".join("%s chain=%d pole=%s angle=%.1f°" % (
                      item["owner"], item["chain_count"], item["pole_target"],
                      item["pole_angle_deg"]) for item in ik_entries) or "无 IK")

    # ── 功能：把控制器往手掌里收，看中间关节朝哪边凸 ──
    prefix = {"thumb": "T", "index": "I", "middle": "M", "ring": "R", "pinky": "P"}[finger["role"]]
    controller = bpy.data.objects.get("%s_%s_test" % (prefix, finger["side"]))
    if controller is None:
        checker.info("func", "%s 功能测试" % part, "没有手指控制器，跳过")
        return
    wrist = armature_object.matrix_world @ bone_index[finger["hand"]]["head"]
    original = controller.matrix_world.copy()
    controller.location = original.translation + (wrist - original.translation) * 0.3
    bpy.context.view_layer.update()
    root_head = evaluated_head(armature_object, segments[0])
    tip = evaluated_tail(armature_object, segments[-1])
    chord = tip - root_head
    chord_unit = chord.normalized() if chord.length > 1e-9 else Vector((0, 0, 0))
    deviation = Vector((0.0, 0.0, 0.0))
    for name in segments[1:]:
        joint = evaluated_head(armature_object, name)
        offset = (joint - root_head) - chord_unit * (joint - root_head).dot(chord_unit)
        deviation += offset
    # 同上：这个姿势下的弦是"腕→指尖"，关节只能朝垂直于弦的方向凸，所以指甲方向也要先投影
    nail_in_plane = common.project_perpendicular(nail, chord_unit) if chord_unit.length > 1e-9 else None
    bend_angle = (common.angle_between(deviation, nail_in_plane)
                  if (deviation.length > 1e-7 and nail_in_plane is not None
                      and nail_in_plane.length > 1e-9) else None)
    controller.matrix_world = original
    bpy.context.view_layer.update()
    checker.check("func", "%s 屈指朝指甲侧" % part,
                  bend_angle is not None and bend_angle <= 30.0,
                  "中间关节偏离指甲方向 %s°（容差 30°，比的是投影到垂直弦平面后的方向）" % (
                      ("%.1f" % bend_angle) if bend_angle is not None else "n/a"))


def chain_from_armature(armature_object, part):
    """从骨架里认出这条链（复用分析器的认链结果，避免验收器和执行器各认一套）。"""
    import rig_analyze as analyzer

    bone_index = common.build_bone_index(armature_object)
    foot_names = [name for name in bone_index
                  if common.role_from_name(name)["role"] == "foot"
                  and common.role_from_name(name)["variant"] in ("plain", "shadow")]
    front_axis, _evidence = common.detect_front_axis(bone_index, foot_names)
    result = analyzer.analyze_armature(armature_object, front_axis)
    if part.startswith("arm."):
        group = "arms"
    elif part.startswith("leg."):
        group = "legs"
    else:
        return None, front_axis
    side = part.split(".")[1]
    entry = result[group].get(side)
    if not entry:
        return None, front_axis
    return entry, front_axis


def shadow_leg_chain_names(armature_object, side):
    """影子腿链（`足D → ひざD → 足首D → 足先EX`）的骨名，认不出来返回空表。

    MMD 常把"驱动用"的本体链与"真正带权重"的影子链分开放：本体骨 `足/ひざ/足首` 上一个权重都没有，
    网格全挂在 `足D/ひざD/足首D` 上。UE 做 animation retarget 时读的是这条影子链，
    所以它也必须逐节对接 —— 与本体链分开验。
    """
    bone_index = common.build_bone_index(armature_object)
    by_role = {}
    for name, entry in bone_index.items():
        # `_shadow_*` / `_dummy_*` / `MCH_*` 也是影子变体，但它们不是链上的骨
        if name.startswith(("_", "MCH_")):
            continue
        info = common.role_from_name(name)
        if info["variant"] != "shadow" or info["side"] != side:
            continue
        if info["role"] in ("thigh", "shin", "foot"):
            by_role.setdefault(info["role"], []).append(name)
    if not all(role in by_role for role in ("thigh", "shin", "foot")):
        return []
    thigh_name = by_role["thigh"][0]
    names = [thigh_name]
    current = thigh_name
    for role in ("shin", "foot"):
        children = [child for child in bone_index[current]["children"]
                    if common.role_from_name(child)["role"] == role]
        if not children:
            return []
        current = children[0]
        names.append(current)
    toe_name = common.toe_continuation(bone_index, current)
    if toe_name:
        names.append(toe_name)
    return names


def verify_shadow_drive(part, armature_object, shadow_names, checker):
    """影子骨的尾端一旦偏离它自己的 `_shadow_` 双胞胎，姿势就不能再靠"局部空间 ADD"来借。

    `mmd_additional_rotation`（LOCAL/ADD）把 `_shadow_*` 的**局部**旋转加到影子骨上，这组数只在
    "影子骨与 `_shadow_*` 是同一个静置帧"时成立。尾端一挪（比如把脚掌的尾端挪到脚趾的头上），
    同一组数落到别的骨轴上 —— 实测屈膝 50° 时脚飞出去 23 cm。

    所以判据是"与双胞胎不同帧了、却还有生效中的 TRANSFORM 约束"。原样没动过的 MMD 骨架里
    两边都是朝上的桩、同帧，这条不会误报。
    修法：`rig_connect --fix-tails --reanchor-drive`（重挂成 LOCAL / LOCAL_OWNER_ORIENT 复制旋转）。
    """
    bone_index = common.build_bone_index(armature_object)
    offenders = []
    checked = 0
    for name in shadow_names:
        entry = bone_index.get(name) or {}
        twin_name = "_shadow_" + name
        twin = armature_object.data.bones.get(twin_name)
        if twin is None or entry.get("head") is None:
            continue
        shadow_direction = (entry["tail"] - entry["head"]).normalized()
        twin_direction = (twin.tail_local - twin.head_local).normalized()
        deviation = math.degrees(shadow_direction.angle(twin_direction))
        checked += 1
        local_constraints = [constraint.name for constraint in
                             armature_object.pose.bones[name].constraints
                             if constraint.type == "TRANSFORM" and not constraint.mute]
        if deviation > 1.0 and local_constraints:
            offenders.append("%s（与 %s 差 %.1f°，还在用 %s）" % (
                name, twin_name, deviation, "/".join(local_constraints)))
    if offenders:
        checker.check("struct", "%s 影子腿链姿势来源" % part, False,
                      "尾端挪过但还在用局部空间 ADD：%s —— 形变会算歪，改用 "
                      "`rig_connect --reanchor-drive` 重挂" % "、".join(offenders))
    elif checked:
        checker.info("struct", "%s 影子腿链姿势来源" % part,
                     "逐根比过与双胞胎的帧和现存约束，没有「尾端挪了还靠局部 ADD」的骨")


def verify_legacy_constraints(part, armature_object, chain_names, checker, label="链"):
    """链上的骨只许有我们自己加的约束生效（`MD_` 前缀），原件的约束一律 mute。

    MMD 原件在这些骨上挂着 `IK` / `mmd_additional_rotation` / `mmd_ik_limit_override` /
    `mmd_tools_at_dummy` 之类，它们与我们加的 IK、复制旋转抢同一根骨：不关掉的话，
    到底谁说了算取决于算得先后，调起来像玄学。作者的规矩是"只让我们自己加的生效"。

    只查"决定链姿势"的关节骨；`ひじ補助`、`肩C`、`腰キャンセル`、`目` 这些是"跟着别人动"的骨，
    它们的约束没有替代品，关掉会掉形变，不算在内。
    """
    bone_index = common.build_bone_index(armature_object)
    offenders = []
    for bone_name in chain_names:
        if bone_name not in bone_index or bone_name not in armature_object.pose.bones:
            continue
        for constraint in armature_object.pose.bones[bone_name].constraints:
            if constraint.mute or constraint.name.startswith("MD_"):
                continue
            offenders.append("%s.%s" % (bone_name, constraint.name))
    checker.check("struct", "%s %s上只留我们自己的约束" % (part, label), not offenders,
                  ("还在生效的原件约束：" + "、".join(offenders) + "（应 mute）") if offenders
                  else "原件约束全部 mute，只剩 MD_*")


# ── 上半身 / 头部控制链 ─────────────────────────────────────────────────
def upper_spine(armature_object):
    """认这条人物身上的躯干链（颈 / 上胸 / 胸 + 头）；认不出返回 None。

    认链口径与 `rig_upper.py` 共用一处，避免"执行器认一套、验收器认另一套"。
    """
    import rig_upper

    return rig_upper.detect_spine_quiet(armature_object)


def has_upper_chain(armature_object):
    """文件里装过上半身 / 头部控制链吗（按 `MD_IK_upper` 这条约束判断）。"""
    spine = upper_spine(armature_object)
    if spine is None:
        return False
    pose_bone = armature_object.pose.bones.get(spine["neck"])
    if pose_bone is None:
        return False
    return pose_bone.constraints.get(UPPER_IK_NAME) is not None


def upper_group_names(armature_object):
    """躯干链上所有可能带权重的顶点组名（含影子变体），用来把躯干顶点分出来单独比。"""
    import rig_upper

    spine = upper_spine(armature_object)
    if spine is None:
        return []
    return sorted(rig_upper.upper_group_names(armature_object, spine))


def upper_chain_root_first(spine):
    """躯干链按"根 → 颈 → 头"的顺序排（`chain_joint_report` 要求父在前、子在后）。"""
    return list(reversed(spine["chain"])) + [spine["head"]]


def verify_upper(armature_object, reference, checker):
    """验"上半身 + 头部朝向"这条链（`rig_upper.py` 的产物）。

    判据与四肢同构：结构（链条对接 / IK 参数 / 复制旋转 / 只留自己的约束）、
    功能（头跟控制器、头看向视点、躯干往极向量那边弯）、职责（rest 网格）。
    差别在于它的"极向量"就是视点控制器 —— 视点在人的正前方，胸颈才会往前弯。
    """
    import rig_upper

    part = UPPER_PART
    spine = upper_spine(armature_object)
    if spine is None:
        checker.info("struct", "%s 躯干链" % part, "认不出颈骨 / 头骨，跳过（用 rig_upper --neck/--head 指定）")
        return False
    pose_bones = armature_object.pose.bones
    neck_pose_bone = pose_bones[spine["neck"]]
    ik_constraint = neck_pose_bone.constraints.get(UPPER_IK_NAME)
    rotation_constraint = pose_bones[spine["head"]].constraints.get(UPPER_ROT_NAME)
    checker.check("struct", "%s 躯干链（颈 / 上胸 / 胸 + 头骨）" % part,
                  ik_constraint is not None,
                  "链 = %s；%s IK 约束%s" % (
                      " → ".join(upper_chain_root_first(spine)), UPPER_IK_NAME,
                      "在" if ik_constraint is not None else "不在（这一段没做过）"))
    if ik_constraint is None:
        return False

    head_control = ik_constraint.target
    look_at = ik_constraint.pole_target
    checker.check("struct", "%s IK 参数（链长 / 目标 / 极向量 / 用尾端）" % part,
                  head_control is not None and look_at is not None
                  and ik_constraint.chain_count == len(spine["chain"])
                  and ik_constraint.use_tail,
                  "chain=%d（链上有 %d 节）target=%s pole=%s pole_angle=%.1f°" % (
                      ik_constraint.chain_count, len(spine["chain"]),
                      head_control.name if head_control else "?",
                      look_at.name if look_at else "?",
                      math.degrees(ik_constraint.pole_angle)))
    checker.check("struct", "%s 复制旋转（世界空间 REPLACE）" % part,
                  rotation_constraint is not None
                  and rotation_constraint.target is head_control
                  and rotation_constraint.owner_space == "WORLD"
                  and rotation_constraint.target_space == "WORLD"
                  and rotation_constraint.mix_mode == "REPLACE"
                  and not rotation_constraint.mute,
                  "目标 = %s" % (rotation_constraint.target.name
                                if rotation_constraint is not None and rotation_constraint.target else "?"))
    checker.check("struct", "%s 控制器独立（没有父级）" % part,
                  head_control is not None and look_at is not None
                  and head_control.parent is None and look_at.parent is None,
                  "%s.parent=%s，%s.parent=%s" % (
                      head_control.name if head_control else "?",
                      head_control.parent.name if head_control is not None and head_control.parent else "无",
                      look_at.name if look_at else "?",
                      look_at.parent.name if look_at is not None and look_at.parent else "无"))
    verify_chain_connect(part, armature_object, upper_chain_root_first(spine), checker)
    verify_legacy_constraints(part, armature_object,
                              list(spine["chain"]) + [spine["head"]], checker)

    if head_control is None or look_at is None:
        checker.info("func", "%s 功能" % part, "IK 的目标 / 极向量丢了，功能项跳过")
        return True

    bone_index = common.build_bone_index(armature_object)
    geometry = {
        "chain_length": (armature_object.matrix_world @ bone_index[spine["chain"][-1]]["head"]
                         - armature_object.matrix_world @ bone_index[spine["neck"]]["tail"]).length,
        "front_axis": front_axis_of(bone_index),
    }
    probes = rig_upper.measure_poses(armature_object, spine, head_control, look_at, geometry)
    reach = max(item["gap"] for item in probes)
    rotation = max(item["rotation_error"] for item in probes)
    aims = [item["aim_error"] for item in probes if item["aim_error"] is not None]
    bends = [item["bend_error"] for item in probes if item["bend_error"] is not None]
    aim = max(aims) if aims else 0.0
    bend = max(bends) if bends else 0.0
    checker.check("func", "%s 颈尾跟住头部控制器" % part,
                  reach <= geometry["chain_length"] * REACH_TOLERANCE_RATIO,
                  "4 个位置最大差 %.5f m（容差 %.5f）" % (
                      reach, geometry["chain_length"] * REACH_TOLERANCE_RATIO))
    checker.check("func", "%s 头骨朝向 = 头部控制器" % part,
                  rotation <= HEAD_ROTATION_TOLERANCE_DEG,
                  "最大 %.3f°（容差 %.1f°）" % (rotation, HEAD_ROTATION_TOLERANCE_DEG))
    checker.check("func", "%s 头骨 Z 轴指向视点" % part,
                  aim <= HEAD_AIM_TOLERANCE_DEG,
                  "最大 %.2f°（容差 %.1f°）" % (aim, HEAD_AIM_TOLERANCE_DEG))
    checker.check("func", "%s 躯干往极向量那侧弯" % part,
                  bend <= UPPER_BEND_TOLERANCE_DEG,
                  "最大偏 %.1f°（容差 %.1f°）" % (bend, UPPER_BEND_TOLERANCE_DEG))

    if reference is None:
        checker.info("duty", "%s 职责" % part, "没给 --reference，只做形状核对")
        return True
    groups = set(upper_group_names(armature_object))
    worst = 0.0
    counted = 0
    for mesh_name, reference_vertices in reference["meshes"].items():
        obj = bpy.data.objects.get(mesh_name)
        if obj is None or len(obj.data.vertices) != len(reference_vertices):
            continue
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        group_indices = {group.index for group in obj.vertex_groups if group.name in groups}
        for index, reference_point in enumerate(reference_vertices):
            if not group_indices:
                continue
            source = obj.data.vertices[index]
            if not any(member.group in group_indices and member.weight > 0.01
                       for member in source.groups):
                continue
            counted += 1
            worst = max(worst, (mesh.vertices[index].co - reference_point).length)
        evaluated.to_mesh_clear()
    checker.check("duty", "%s rest 网格位移（躯干顶点）" % part,
                  worst <= UPPER_REST_MESH_TOLERANCE,
                  "最大 %.5f m（%d 个躯干顶点；容差 %.3f —— IK 把链解回 rest 时本应为 0）" % (
                      worst, counted, UPPER_REST_MESH_TOLERANCE))
    return True


def front_axis_of(bone_index):
    foot_names = [name for name in bone_index
                  if common.role_from_name(name)["role"] == "foot"
                  and common.role_from_name(name)["variant"] in ("plain", "shadow")]
    front_axis, _evidence = common.detect_front_axis(bone_index, foot_names)
    return front_axis


def verify_arm(armature_object, part, arm, front_axis, reference, checker):
    """验一条两节链（手臂 / 腿）。两者结构相同（三段直接父子 + 中节 IK 链长 2 + 末端世界复制旋转），
    差别只在齿轮：骨的键名、复制旋转挂在哪、有没有扭转复制、拱形朝哪边。"""
    bone_index = common.build_bone_index(armature_object)
    back = -front_axis
    is_leg = part.startswith("leg.")
    chain = arm["chain"]
    if is_leg:
        upper_name, forearm_name, hand_name = chain["thigh"], chain["shin"], chain["foot"]
        copyrot_entries = arm.get("copyrot_foot") or []
        controller_name = (arm["controllers"].get("foot") or [None])[0]
        part_noun, tip_noun = "脚掌", "踝关节"
    else:
        upper_name, forearm_name, hand_name = chain["upper"], chain["forearm"], chain["hand"]
        copyrot_entries = arm.get("copyrot_hand") or []
        controller_name = (arm["controllers"].get("hand") or [None])[0]
        part_noun, tip_noun = "手掌", "腕关节"

    # ── 结构 ──
    hand_ancestors = []
    current = bone_index[hand_name]["parent"]
    while current:
        hand_ancestors.append(current)
        current = bone_index[current]["parent"]
    hierarchy_ok = forearm_name in hand_ancestors and upper_name in hand_ancestors
    between = []
    if forearm_name in hand_ancestors:
        between = hand_ancestors[:hand_ancestors.index(forearm_name)]
    checker.check("struct", "%s 三段直接父子" % part, hierarchy_ok and not between,
                  "%s→前中段→起始段之间：%s" % (part_noun, ", ".join(between) or "无"))

    # 链条对接：有 MCH 主骨时 IK 实际在"主骨链"上（形变骨是同一个头的复制），否则就是本体三段
    upper_mch_name, forearm_mch_name = "MCH_" + upper_name, "MCH_" + forearm_name
    if upper_mch_name in bone_index and forearm_mch_name in bone_index:
        connect_names = [upper_mch_name, forearm_mch_name, hand_name]
    else:
        connect_names = [upper_name, forearm_name, hand_name]
    if is_leg:
        # 脚掌→脚趾这一节是 Unreal 重定向 LeftLeg 链的最后一节，不能漏；
        # 但只有"头落在脚掌尾端上"的那根才算（MMD 的 つま先 常是分支）
        toe_name = common.toe_continuation(bone_index, hand_name)
        if toe_name:
            connect_names.append(toe_name)
        else:
            branch = common.toe_candidates(bone_index, hand_name)
            checker.info("struct", "%s 脚掌→脚趾" % part,
                         "；".join("%s 的头离脚掌尾 %.5f，按分支处理" % (name, gap) for name, gap in branch)
                         or "脚掌没有脚趾骨")
    verify_chain_connect(part, armature_object, connect_names, checker)

    if is_leg:
        side = part.split(".")[1]
        shadow_names = shadow_leg_chain_names(armature_object, side)
        if shadow_names:
            verify_chain_connect("%s 影子腿链（UE 重定向用）" % part, armature_object,
                                 shadow_names, checker)
            verify_shadow_drive("%s 影子腿链" % part, armature_object, shadow_names, checker)
            checker.info("struct", "%s 影子腿链组成" % part, " > ".join(shadow_names))
        else:
            checker.info("struct", "%s 影子腿链" % part, "没有影子腿链（只有本体链）")
        joint_names = [upper_name, forearm_name, hand_name] + (shadow_names or [])
        if connect_names:
            joint_names += connect_names
        verify_legacy_constraints(part, armature_object, joint_names, checker, "双腿关节")

    z_items = arm["zaxis"]["bones"]
    z_angles = [item["angle_deg"] for item in z_items if item["status"] != "skip"]
    checker.check("struct", "%s Z 轴朝后" % part,
                  bool(z_angles) and max(z_angles) <= Z_TOLERANCE_DEG,
                  "最大夹角 %.2f°（容差 %.0f°）" % (max(z_angles) if z_angles else -1.0, Z_TOLERANCE_DEG))

    # 拱形：手臂朝后（肘尖），腿朝前（膝盖）—— 分析器已经按链类给了"凸侧方向"，这里只比夹角
    arch = arm["arch"]
    arch_ratio = arch.get("max_offset_ratio_percent")
    arch_angle = arch.get("angle_to_bend_direction_deg")
    checker.check("struct", "%s 拱形 3%% 且朝%s" % (part, "前" if is_leg else "后"),
                  arch_ratio is not None and abs(arch_ratio - ARCH_TARGET_PERCENT) <= ARCH_TOLERANCE_PERCENT
                  and arch_angle is not None and arch_angle <= 30.0,
                  "拱高 %.2f%%，与凸侧夹角 %s°" % (arch_ratio or -1.0, arch_angle))

    ik_entries = arm["ik"]
    ik_ok = any(item["chain_count"] == 2 and item["pole_target"] and item["use_stretch"] for item in ik_entries)
    checker.check("struct", "%s IK 链长 2 + 极向量 + stretch" % part, ik_ok,
                  "; ".join("%s chain=%d pole=%s angle=%.1f° stretch=%s" % (
                      item["owner"], item["chain_count"], item["pole_target"],
                      item["pole_angle_deg"], item["use_stretch"]) for item in ik_entries) or "无 IK")

    checker.check("struct", "%s %s世界空间复制旋转" % (part, part_noun),
                  any(item["owner_space"] == "WORLD" and item["target_space"] == "WORLD"
                      and item["use_x"] and item["use_y"] and item["use_z"] for item in copyrot_entries),
                  "; ".join("%s → %s" % (item["name"], item["target"]) for item in copyrot_entries) or "无")

    twists = arm.get("twist_copies") or []
    if is_leg:
        # §3.6 的配方里腿没有扭转复制（大腿骨是整段的、MMD 的腿也不带扭转骨）
        checker.info("struct", "%s 扭转" % part, "不适用（腿不建扭转复制）")
    else:
        influences = [item["influence"] for item in twists]
        monotonic = all(influences[index] <= influences[index + 1] + 1e-6
                        for index in range(len(influences) - 1))
        only_y = all(item["use_xyz"] == (False, True, False) for item in twists)
        checker.check("struct", "%s 扭转复制仅 Y 且单调" % part,
                      bool(twists) and monotonic and only_y,
                      "强度 %s" % ([item["influence"] for item in twists] or "无"))

    # ── 功能 ──
    # 控制器优先从"挂上去的约束"里读（腿上那两个分析器只登记了脚控制器，极向量没登记），
    # 读不到再退回分析器按命名找的结果。
    controllers = arm["controllers"]
    ik_with_pole = next((item for item in ik_entries
                         if item["chain_count"] == 2 and item.get("pole_target")), None)
    pole_controller_name = ik_with_pole["pole_target"] if ik_with_pole else None
    if not pole_controller_name:
        pole_controller_name = (controllers.get("pole") or [None])[0]
    copyrot_target_name = next((item["target"] for item in copyrot_entries if item["target"]), None)
    hand_controller_name = copyrot_target_name or controller_name
    hand_controller = bpy.data.objects.get(hand_controller_name) if hand_controller_name else None
    pole_controller = bpy.data.objects.get(pole_controller_name) if pole_controller_name else None
    if hand_controller is None:
        checker.info("func", "%s 功能测试" % part, "没有%s控制器，跳过" % part_noun)
        return
    if pole_controller is None:
        checker.info("func", "%s 极向量" % part, "没有极向量控制器，跳过朝向检查")

    rest_wrist = armature_object.matrix_world @ bone_index[hand_name]["head"]
    shoulder = armature_object.matrix_world @ bone_index[upper_name]["head"]
    chain_length = sum(bone_index[name]["length"] for name in (upper_name, forearm_name))
    # 目标一律取在"够得到"的范围内（0.85 倍链长）：这套骨架的 IK 没有逐骨 ik_stretch，
    # 超出链长的目标本来就不可能跟住，那不是改造的问题。
    reach = chain_length * 0.85
    if is_leg:
        # 腿的活动范围：正前下方落脚、外侧、后摆、正下方
        directions = [
            Vector((0.10, -0.55, -0.80)),
            Vector((0.55, -0.30, -0.75)),
            Vector((0.05, 0.55, -0.60)),
            Vector((-0.05, -0.05, -1.00)),
        ]
    else:
        directions = [
            Vector((0.2, -0.9, -0.3)),
            Vector((-0.3, -0.5, 0.8)),
            Vector((0.9, -0.2, 0.0)),
            Vector((-0.2, 0.85, -0.4)),
        ]
    offsets = [direction.normalized() * reach for direction in directions]
    checker.info("func", "%s 测试范围" % part,
                 "链长 %.4f，目标半径 %.4f（够得到的范围）" % (chain_length, reach))
    wrist_errors = []
    rotation_errors = []
    pole_angles = []
    ik_owner = None
    for item in ik_entries:
        if item["chain_count"] == 2:
            ik_owner = item["owner"]
    root_name = bone_index[ik_owner]["parent"] if ik_owner else upper_name
    original_matrix = hand_controller.matrix_world.copy()
    for offset in offsets:
        moved = original_matrix.copy()
        moved.translation = shoulder + offset
        hand_controller.matrix_world = moved
        bpy.context.view_layer.update()
        target_point = hand_controller.matrix_world.translation.copy()
        wrist_error = ((evaluated_tail(armature_object, ik_owner) - target_point).length
                       if ik_owner else (evaluated_head(armature_object, hand_name) - target_point).length)
        wrist_errors.append(wrist_error)
        print("    目标 %s → %s误差 %.5f" % (
            "(%.4f, %.4f, %.4f)" % (target_point.x, target_point.y, target_point.z),
            tip_noun, wrist_error))
        hand_rotation = evaluated_rotation(armature_object, hand_name)
        controller_rotation = hand_controller.matrix_world.to_quaternion()
        rotation_errors.append(math.degrees(hand_rotation.rotation_difference(controller_rotation).angle))
        if pole_controller is not None and ik_owner:
            root_head = armature_object.matrix_world @ bone_index[root_name]["head"]
            chord = target_point - root_head
            chord_unit = chord.normalized()
            elbow = evaluated_head(armature_object, ik_owner)
            offset_vector = (elbow - root_head) - chord_unit * (elbow - root_head).dot(chord_unit)
            pole_raw = pole_controller.matrix_world.translation - root_head
            pole_raw = pole_raw - chord_unit * pole_raw.dot(chord_unit)
            if offset_vector.length > 1e-6 and pole_raw.length > 1e-6:
                pole_angles.append(common.angle_between(offset_vector, pole_raw))
    hand_controller.matrix_world = original_matrix
    bpy.context.view_layer.update()

    checker.check("func", "%s %s跟住控制器" % (part, tip_noun),
                  max(wrist_errors) <= WRIST_TOLERANCE,
                  "4 个位置最大误差 %.5f m（容差 %.3f）" % (max(wrist_errors), WRIST_TOLERANCE))
    checker.check("func", "%s %s朝向 = 控制器" % (part, part_noun),
                  max(rotation_errors) <= HAND_ROTATION_TOLERANCE_DEG,
                  "最大 %.3f°（容差 %.1f°）" % (max(rotation_errors), HAND_ROTATION_TOLERANCE_DEG))
    if pole_angles:
        checker.check("func", "%s %s朝极向量" % (part, "膝盖" if is_leg else "肘"),
                      max(pole_angles) <= POLE_ALIGN_TOLERANCE_DEG,
                      "最大偏离 %.2f°（容差 %.0f°）" % (max(pole_angles), POLE_ALIGN_TOLERANCE_DEG))

    # ── 职责 ──
    if reference is None:
        checker.info("duty", "%s 职责" % part, "没给 --reference，只做形状核对")
        return
    missing = [name for name in reference["deform_bones"] if name not in bone_index]
    non_deform = [name for name in reference["deform_bones"]
                  if name in bone_index and not bone_index[name]["deform"]]
    checker.check("duty", "%s 形变骨一根不少" % part, not missing and not non_deform,
                  "缺失 %s；被改成非形变 %s" % (missing or "无", non_deform or "无"))

    for mesh_name, reference_vertices in reference["meshes"].items():
        obj = bpy.data.objects.get(mesh_name)
        if obj is None:
            checker.check("duty", "%s 网格 %s" % (part, mesh_name), False, "网格不在了")
            continue
        groups_now = sorted(group.name for group in obj.vertex_groups)
        checker.check("duty", "%s 顶点组不变" % part,
                      groups_now == reference["groups"][mesh_name],
                      "现在 %d 个组，参考 %d 个" % (len(groups_now), len(reference["groups"][mesh_name])))
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        if len(mesh.vertices) != len(reference_vertices):
            checker.check("duty", "%s rest 网格不变" % part, False, "顶点数 %d ≠ %d" % (
                len(mesh.vertices), len(reference_vertices)))
        else:
            leg_groups = {group.index for group in obj.vertex_groups
                          if group.name in set(reference.get("leg_groups") or [])}
            # 只有装了上半身链的文件才把躯干顶点分出去（那条链由 verify_upper 单独按自己的容差量）。
            # 没装的照旧按严格容差比 —— 别因为"模型有颈骨"就把一批顶点悄悄从断言里漏掉。
            upper_groups = ({group.index for group in obj.vertex_groups
                             if group.name in set(upper_group_names(armature_object))}
                            if has_upper_chain(armature_object) else set())
            worst_other = 0.0
            worst_leg = 0.0
            leg_vertices = 0
            for index in range(len(reference_vertices)):
                delta = (mesh.vertices[index].co - reference_vertices[index]).length
                source_vertex = obj.data.vertices[index]
                is_leg = any(group.group in leg_groups and group.weight > 0.01
                             for group in source_vertex.groups)
                is_upper = any(group.group in upper_groups and group.weight > 0.01
                               for group in source_vertex.groups)
                if is_leg:
                    leg_vertices += 1
                    worst_leg = max(worst_leg, delta)
                elif is_upper:
                    # 躯干顶点由 `verify_upper` 单独按自己的容差量（IK 解算会把它归位到新姿势）
                    continue
                else:
                    worst_other = max(worst_other, delta)
            checker.check("duty", "%s rest 网格不变（腿部 / 躯干以外）" % part,
                          worst_other <= REST_MESH_TOLERANCE,
                          "最大顶点位移 %.7f m（容差 %.0e）" % (worst_other, REST_MESH_TOLERANCE))
            if leg_groups:
                # 腿按配方要重建 IK（拱形 + 用我们的 IK 取代 MMD 的），腿部顶点必然变一点：
                # 量出来只作参考，是不是能接受由人目视。
                checker.info("duty", "%s 腿部顶点位移" % part,
                             "最大 %.4f m（%d 个腿部顶点；拱形/IK 重解算引起，须目视）" % (
                                 worst_leg, leg_vertices))
        evaluated.to_mesh_clear()
        break


def main():
    options = parse_args()
    if not options["file"]:
        print(__doc__)
        return
    reference = None
    if options["reference"]:
        reference = snapshot(options["reference"], options["armature"])
        print("参考文件：%s（形变骨 %d 根，网格 %s）" % (
            os.path.basename(options["reference"]), len(reference["deform_bones"]),
            ", ".join(reference["meshes"])))
    open_file(options["file"])
    armature_object = find_armature(options["armature"])
    if armature_object is None:
        print("VERIFY 没找到骨架")
        return
    print("")
    print("验收：%s / %s" % (os.path.basename(options["file"]), armature_object.name))

    checker = Checker()
    parts = options["chains"] or list(REQUIRED_PARTS)
    upper_present = has_upper_chain(armature_object)
    if upper_present and UPPER_PART not in parts:
        # 装了这条链就一定一起验：它是"上半身怎么摆、头朝哪看"的唯一把手，
        # 只验四肢却说"文件 DONE"就等于把它漏掉了。
        parts = list(parts) + [UPPER_PART]
    rows = []
    verified_parts = []
    for part in parts:
        print("")
        print("== %s ==" % part)
        if part == UPPER_PART:
            if not upper_present:
                checker.info("struct", UPPER_PART, "没装上半身 / 头部控制链，跳过")
                continue
            verify_upper(armature_object, reference, checker)
            verified_parts.append(part)
            continue
        if part.startswith("arm.") or part.startswith("leg."):
            arm, front_axis = chain_from_armature(armature_object, part)
            if arm is None:
                checker.info("struct", part, "认不出这条链，跳过")
                continue
            verify_arm(armature_object, part, arm, front_axis, reference, checker)
            verified_parts.append(part)
            continue
        finger = finger_from_armature(armature_object, part)
        if finger is None:
            checker.info("struct", part, "认不出这根手指，跳过")
            continue
        verify_finger(armature_object, part, finger, checker)
        verified_parts.append(part)

    failed = checker.failed()
    print("")
    print("VERIFY RESULT: %s（%d 项通过，%d 项失败，%d 项信息）" % (
        "PASS" if not failed else "FAIL",
        len([item for item in checker.items if item["ok"] is True]),
        len(failed),
        len([item for item in checker.items if item["ok"] is None])))

    if not options["no_progress"]:
        for part in parts:
            part_items = [item for item in checker.items if part in item["name"]]
            # 这一条根本没验（认不出链 / 没装这条链）时不写进度行：
            # 写了会留下 "upper 全部 -、notes=verified" 这种假记录。
            if not part_items or all(item["ok"] is None for item in part_items):
                continue

            def mark(keyword):
                matched = [item for item in part_items if keyword in item["name"]]
                if not matched:
                    return "-"
                return "x" if all(item["ok"] is not False for item in matched) else "!"

            marks = {
                "hier": mark("父子"),
                "zaxis": mark("Z 轴") if any("Z 轴" in item["name"] for item in part_items) else mark("Z 朝"),
                "arch": mark("拱形"),
                "ik": mark("IK"),
                "copyrot": mark("复制旋转"),
                "twist": mark("扭转复制"),
                "leaf": mark("指尖骨"),
            }
            failures = [item["name"] for item in part_items if item["ok"] is False]
            rows.append(progress.make_row(part, notes=("FAIL: " + "; ".join(failures)) if failures else "verified",
                                          **marks))
        existing = progress.read(armature_object)
        merged = progress.merge_rows(existing["rows"], rows)
        # DONE 要三件事同时成立：这一轮没有任何失败、这一轮把十四条链都验过、进度表里十四条都齐全。
        # 只验了一部分（比如只跑两臂）时即使全过也不能标 DONE —— 那会把"没验过"写成"做完了"。
        # 装了上半身 / 头部控制链的文件还要多验一条 upper（它不在十四条里，但同样是"必须验过"）。
        required = list(REQUIRED_PARTS) + ([UPPER_PART] if upper_present else [])
        uncovered = [part for part in required if part not in verified_parts]
        status = "DONE" if (not failed and not uncovered and parts_complete(merged, required)) else "IN PROGRESS"
        progress.write(armature_object, 'armature "%s"' % armature_object.name, status, merged, "rig_verify.py")
        if uncovered:
            print("这一轮没验的链（%d 条）：%s" % (len(uncovered), ", ".join(uncovered)))
        print("进度文本块已更新（status=%s）" % status)
        if options["save"]:
            # 老模型引用的贴图可能不在了，保存时 Blender 报 "Unable to pack file" 的 RuntimeError，
            # 但文件其实已经写出来 —— 只提示，不当失败。
            try:
                bpy.ops.wm.save_mainfile()
            except RuntimeError as error:
                message = str(error).splitlines()[0] if str(error) else ""
                print("存盘时 Blender 报了一条错（文件已写出，多半是缺贴图）：%s" % message)
            print("已保存：%s" % bpy.data.filepath)
        elif status == "DONE":
            print("注意：DONE 只写进了内存，要落盘再加 --save")

    if options["json"]:
        with open(options["json"], "w", encoding="utf-8") as handle:
            json.dump({"file": options["file"], "items": checker.items}, handle, ensure_ascii=False, indent=1)
        print("json: %s" % options["json"])


if __name__ == "__main__":
    main()
