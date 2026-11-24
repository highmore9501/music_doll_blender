# -*- coding: utf-8 -*-
"""MusicDoll 骨架改造 —— 上半身 / 头部朝向控制链（腰→胸→颈 IK + 头部朝向）。

改造完四肢之后，人物还缺一个"上半身怎么摆、头朝哪看"的把手。这一站补上它，
形状照作者成品（`米娅-星彩_古筝.blend`，古筝演奏者）的那一套：

    头部控制器 `Head_Control_test`  ──IK──▶ 颈骨（链长 3：颈 / 上胸 / 胸）
            │                              ▲
            │ Track_To（本地 Z 轴指向视点）  │ 极向量 = 视点控制器
            ▼                              │
    视点控制器 `Look_At_test` ────────────┘
            │
            └──▶ 头骨的「世界空间复制旋转」（头跟着控制器转，不跟颈的余数）

三条要点（与四肢的规矩一致，理由见 SKILL）：

1. **两个控制器都是独立的、没有父级**：本阶段只管把链搭好、把控件摆对；后面的乐器阶段
   会换成模块自己的 `Head_Control_<后缀>` / `Look_At_<后缀>`（它们挂在
   `Middle_Hand` 这类"双手中点"对象下面，那是乐器模块的事）。
2. **极向量就是视点控制器**：视点在人的正前方，胸/颈自然往前往下弯；换成一个朝向别的
   方向的极向量，人会歪着弯。这一点和"膝的极向量要放在身前"是同一个道理。
3. **`pole_angle` 必须现场标定**：它相对骨自己的坐标系量，不同骨架的 roll 不一样。
   这里的做法是"把头部控制器摆在链条末端不动，扫一遍角度，取**rest 关节位移最小**的那一档" ——
   rest 本身就是 IK 的一个解，只有极向量平面与骨自身的弯曲平面重合时，解算才不会把 rest 掰歪。
   （实测错 90° 时 rest 关节直接被掰走 26 cm。）

用法：

    blender -b --factory-startup -P rig_upper.py -- <file.blend> [--armature NAME] \
        [--neck 首] [--head 頭] [--head-control Head_Control_test] [--look-at Look_At_test] \
        [--chain-count 3] [--look-distance 1.0] [--pole-angle 90] [--no-calibrate] \
        [--no-connect] [--no-track] [--dry-run] [--out 副本.blend] [--save] [--json 报告.json]

`--dry-run` 只打印认出来的链与现有约束状态，不写任何东西。
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rig_common as common  # noqa: E402
import rig_progress as progress  # noqa: E402
import rig_roles  # noqa: E402

CONSTRAINT_PREFIX = "MD_"
CONSTRAINT_IK = "MD_IK_upper"
CONSTRAINT_ROT = "MD_Rot_upper"
TRACK_CONSTRAINT = "Track_Look_At"
PART_NAME = "upper"

DEFAULT_HEAD_CONTROL = "Head_Control_test"
DEFAULT_LOOK_AT = "Look_At_test"

# 标定刷新率：粗扫 5°、细扫 1°。角度是相对骨坐标系量的，精度到 1° 就够
# （实测 90° 与 95° 之间 rest 关节只差 1.5 mm，而错 90° 会差 26 cm）。
COARSE_STEP_DEG = 5.0
FINE_STEP_DEG = 1.0

# rest 网格位移容差（躯干以外）：与 rig_verify 的严格口径同量级，只要不是真被掰弯就过得去。
REST_MESH_TOLERANCE = 1e-4
REACH_TOLERANCE_RATIO = 0.02
ROTATION_TOLERANCE_DEG = 1.0
AIM_TOLERANCE_DEG = 2.0
BEND_TOLERANCE_DEG = 5.0


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {
        "file": None, "armature": None, "neck": None, "head": None,
        "head_control": DEFAULT_HEAD_CONTROL, "look_at": DEFAULT_LOOK_AT,
        "chain_count": 3, "look_distance": 1.0, "pole_angle": None,
        "dry_run": False, "save": False, "out": None, "json": None,
        "no_calibrate": False, "no_connect": False, "no_track": False,
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--armature":
            index += 1
            options["armature"] = argv[index]
        elif token == "--neck":
            index += 1
            options["neck"] = argv[index]
        elif token == "--head":
            index += 1
            options["head"] = argv[index]
        elif token == "--head-control":
            index += 1
            options["head_control"] = argv[index]
        elif token == "--look-at":
            index += 1
            options["look_at"] = argv[index]
        elif token == "--chain-count":
            index += 1
            options["chain_count"] = int(argv[index])
        elif token == "--look-distance":
            index += 1
            options["look_distance"] = float(argv[index])
        elif token == "--pole-angle":
            index += 1
            options["pole_angle"] = float(argv[index])
        elif token == "--json":
            index += 1
            options["json"] = argv[index]
        elif token == "--out":
            index += 1
            options["out"] = argv[index]
        elif token == "--dry-run":
            options["dry_run"] = True
        elif token == "--save":
            options["save"] = True
        elif token == "--no-calibrate":
            options["no_calibrate"] = True
        elif token == "--no-connect":
            options["no_connect"] = True
        elif token == "--no-track":
            options["no_track"] = True
        else:
            options["file"] = token
        index += 1
    return options


# ── 小工具 ──────────────────────────────────────────────────────────────
def _fmt(vector):
    return "(%.4f, %.4f, %.4f)" % (vector[0], vector[1], vector[2])


def set_active(armature_object):
    if armature_object.mode != "OBJECT":
        return
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    armature_object.hide_viewport = False
    armature_object.hide_set(False)
    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)


def enter_edit(armature_object):
    set_active(armature_object)
    if armature_object.mode != "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    return armature_object.data.edit_bones


def enter_object(armature_object):
    if armature_object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def world_head(armature_object, bone_name):
    return armature_object.matrix_world @ armature_object.pose.bones[bone_name].head


def world_tail(armature_object, bone_name):
    return armature_object.matrix_world @ armature_object.pose.bones[bone_name].tail


def pose_axes(armature_object, bone_name):
    """当前姿势下这根骨的世界空间 (X, Y, Z) 单位轴。"""
    rotation = armature_object.pose.bones[bone_name].matrix.to_3x3()
    rotation = armature_object.matrix_world.to_3x3() @ rotation
    return (
        rotation.col[0].normalized(),
        rotation.col[1].normalized(),
        rotation.col[2].normalized(),
    )


# ── 认链 ────────────────────────────────────────────────────────────────
def pick_bone(bones, wanted_role, preferred_parent=None):
    """按角色挑一根骨：名字精确命中的优先、有父级要求的次之、形变骨优先。"""
    candidates = []
    for bone in bones:
        role, confidence = rig_roles.spine_role_from_name(bone.name)
        if role != wanted_role:
            continue
        candidates.append((bone, confidence))
    if not candidates:
        return None, "没找到"
    if preferred_parent is not None:
        # 注意：bpy 每次访问都给出新的 Python 包装对象，不能用 `is` 比父子关系，要比名字。
        nested = [item for item in candidates
                  if item[0].parent is not None and item[0].parent.name == preferred_parent.name]
        if not nested:
            return None, "找到了但不在 %s 下面" % preferred_parent.name
        candidates = nested
    # 高置信（名字精确）优先，其次形变骨
    candidates.sort(key=lambda item: (item[1] != "high", not item[0].use_deform))
    return candidates[0][0], candidates[0][1]


def detect_spine(armature_object, options, report):
    """认颈骨 / 头骨 / 上胸与胸（IK 链），返回 dict；认不出时返回 None。"""
    bones = armature_object.data.bones
    if options["neck"]:
        neck_bone = bones.get(options["neck"])
        if neck_bone is None:
            report("detect", "指定的颈骨 %s 不存在" % options["neck"])
            return None
        report("detect", "颈骨 = %s（命令行指定）" % neck_bone.name)
    else:
        neck_bone, evidence = pick_bone(bones, "neck")
        if neck_bone is None:
            report("detect", "认不出颈骨（%s），用 --neck 指定" % evidence)
            return None
        report("detect", "颈骨 = %s（名字判据 %s）" % (neck_bone.name, evidence))

    if options["head"]:
        head_bone = bones.get(options["head"])
        if head_bone is None:
            report("detect", "指定的头骨 %s 不存在" % options["head"])
            return None
        report("detect", "头骨 = %s（命令行指定）" % head_bone.name)
    else:
        head_bone, evidence = pick_bone(bones, "head", preferred_parent=neck_bone)
        if head_bone is None:
            report("detect", "认不出头骨（%s），用 --head 指定" % evidence)
            return None
        report("detect", "头骨 = %s（名字判据 %s）" % (head_bone.name, evidence))

    chain_names = [neck_bone.name]
    cursor = neck_bone.parent
    while cursor is not None and len(chain_names) < options["chain_count"]:
        role, _confidence = rig_roles.spine_role_from_name(cursor.name)
        if role not in ("chest", "spine"):
            report("detect", "往上走到 %s（%s）就停：它不是躯干骨，再往上会把腰/腿一起转" % (
                cursor.name, role or "未分类"))
            break
        chain_names.append(cursor.name)
        cursor = cursor.parent
    if len(chain_names) < options["chain_count"]:
        report("detect", "躯干只找到 %d 节（链长 %d），按 %d 节做 IK" % (
            len(chain_names), options["chain_count"], len(chain_names)))
    report("detect", "IK 链（颈 → 根）= %s" % " → ".join(chain_names))

    return {
        "neck": neck_bone.name,
        "head": head_bone.name,
        "chain": chain_names,
    }


def spine_geometry(armature_object, spine, options):
    """算这条链的几何量：链长、头骨的世界朝向、视点位置。"""
    bones = armature_object.data.bones
    chain_root = armature_object.matrix_world @ bones[spine["chain"][-1]].head_local
    chain_end = armature_object.matrix_world @ bones[spine["neck"]].tail_local
    head_matrix = armature_object.matrix_world @ bones[spine["head"]].matrix_local
    head_length = (bones[spine["head"]].tail_local - bones[spine["head"]].head_local).length
    bone_index = common.build_bone_index(armature_object)
    foot_names = [name for name in bone_index
                  if common.role_from_name(name)["role"] == "foot"]
    front_axis, front_evidence = common.detect_front_axis(bone_index, foot_names)
    return {
        "chain_root": chain_root,
        "chain_end": chain_end,
        "chain_length": (chain_end - chain_root).length,
        "head_matrix": head_matrix,
        "head_length": head_length,
        "front_axis": front_axis,
        "front_evidence": front_evidence,
    }


# ── 控制器 ──────────────────────────────────────────────────────────────
def ensure_controller(name, dry_run, report):
    """取同名控制器；没有就造一个空物体。本阶段的控制器一律独立（没有父级）。"""
    existing = bpy.data.objects.get(name)
    if existing is not None:
        report("controller", "沿用控制器 %s" % name)
        if dry_run:
            return existing
        if existing.parent is not None:
            # 用户 2026-11-25 定：本阶段 Head_Control / Look_At 都是独立控件，
            # 换不换父级交给后面的乐器阶段。这里只把世界位置保住。
            bpy.context.view_layer.update()
            world = existing.matrix_world.copy()
            existing.parent = None
            existing.matrix_world = world
            report("controller", "%s 原来是 %s 的子级，本阶段先摘成独立控件" % (
                name, existing.parent.name if existing.parent else "?"))
        return existing
    report("controller", "造控制器 %s" % name)
    if dry_run:
        return None
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "SPHERE"
    empty.show_in_front = True
    empty.rotation_mode = "QUATERNION"
    bpy.context.scene.collection.objects.link(empty)
    return empty


def place_controllers(head_control, look_at, geometry, options, dry_run, report):
    """摆控件：头部控制器 = 颈的尾端（= 头骨的头，也是转头的轴心）；视点 = 正前方一段。"""
    if dry_run:
        report("controller", "会把 %s 摆到 %s、%s 摆到正前方 %.3f m" % (
            options["head_control"], _fmt(geometry["chain_end"]),
            options["look_at"], geometry["chain_length"] * options["look_distance"]))
        return None, None

    head_control.rotation_mode = "QUATERNION"
    head_control.matrix_world = geometry["head_matrix"]
    head_control.empty_display_size = max(geometry["chain_length"] * 0.06, 1e-4)

    head_forward = geometry["head_matrix"].to_3x3().col[2].normalized()
    look_point = geometry["chain_end"] + head_forward * (
        geometry["chain_length"] * options["look_distance"])
    look_at.rotation_mode = "QUATERNION"
    look_at.matrix_world = Matrix.Translation(look_point)
    look_at.empty_display_size = max(geometry["chain_length"] * 0.06, 1e-4)
    bpy.context.view_layer.update()

    report("controller", "%s（头部控制器）= %s，朝向取头骨 rest 朝向" % (
        head_control.name, _fmt(head_control.matrix_world.translation)))
    report("controller", "%s（视点 / 极向量）= %s（从头往正前方 %.0f%% 链长）" % (
        look_at.name, _fmt(look_at.matrix_world.translation),
        100.0 * options["look_distance"]))
    return head_control, look_at


def ensure_track(head_control, look_at, options, dry_run, report):
    """头部控制器朝向 = 看视点（本地 Z 轴指向视点、本地 Y 轴尽量朝上）。"""
    if options["no_track"]:
        report("track", "按 --no-track 不加 Track_To")
        return None
    existing = None
    for constraint in head_control.constraints:
        if constraint.type == "TRACK_TO":
            existing = constraint
            break
    if existing is not None and existing.name != TRACK_CONSTRAINT:
        report("track", "%s 上已有 Track_To（%s），沿用不重建" % (head_control.name, existing.name))
        return existing
    report("track", "%s 的 Track_To：本地 Z 轴指向 %s、上方向取本地 Y" % (
        head_control.name, look_at.name))
    if dry_run:
        return None
    if existing is None:
        existing = head_control.constraints.new("TRACK_TO")
        existing.name = TRACK_CONSTRAINT
    existing.target = look_at
    existing.subtarget = ""
    existing.track_axis = "TRACK_Z"
    existing.up_axis = "UP_Y"
    existing.use_target_z = False
    existing.owner_space = "WORLD"
    existing.target_space = "WORLD"
    existing.mute = False
    existing.influence = 1.0
    return existing


# ── 连关节 ──────────────────────────────────────────────────────────────
def connect_chain(armature_object, spine, options, dry_run, report):
    """链上每对父子：后一根的头压在前一根的尾上，并且 use_connect = 1。

    不连的后果和四肢一样：拖 IK 控制器时，没连的子骨能被单独平移，链条从中间断开。
    这里只连"已经对得上"的关节；对不上时**不掰尾端** —— 躯干骨的尾端一挪，权重与
    影子驱动都要跟着重算（腿那一节踩过这个坑），交给 `rig_connect.py --fix-tails` 显式处理。
    """
    if options["no_connect"]:
        report("connect", "按 --no-connect 不连关节")
        return []
    bones = armature_object.data.bones
    pairs = [(spine["chain"][index], spine["chain"][index - 1])
             for index in range(1, len(spine["chain"]))]
    pairs.append((spine["neck"], spine["head"]))
    report("connect", "要连的关节：%s" % "、".join(
        "%s→%s" % (parent, child) for parent, child in pairs))
    loose = []
    if dry_run:
        for parent, child in pairs:
            gap = (bones[parent].tail_local - bones[child].head_local).length
            report("connect", "%s→%s gap=%.5f%s" % (
                parent, child, gap, "" if gap <= common.CHAIN_JOINT_TOLERANCE else "（对不上）"))
        return loose
    edit_bones = enter_edit(armature_object)
    try:
        for parent, child in pairs:
            parent_bone = edit_bones.get(parent)
            child_bone = edit_bones.get(child)
            if parent_bone is None or child_bone is None:
                continue
            gap = (parent_bone.tail - child_bone.head).length
            if gap > common.CHAIN_JOINT_TOLERANCE:
                loose.append("%s→%s gap=%.4f" % (parent, child, gap))
                report("connect", "%s→%s 差 %.4f，不硬掰（要掰跑 rig_connect.py --fix-tails）" % (
                    parent, child, gap))
                continue
            if not child_bone.use_connect:
                child_bone.use_connect = True
                report("connect", "%s→%s gap≈0，接上（use_connect=1）" % (parent, child))
            else:
                report("connect", "%s→%s 已经是连着的" % (parent, child))
    finally:
        enter_object(armature_object)
    return loose


# ── 约束 ────────────────────────────────────────────────────────────────
def strip_our_constraints(armature_object, spine):
    """重跑前先摘掉我们加的约束，让这次量到的"改前"是干净状态。"""
    names = set(spine["chain"]) | {spine["head"]}
    removed = []
    for name in names:
        pose_bone = armature_object.pose.bones.get(name)
        if pose_bone is None:
            continue
        for constraint in list(pose_bone.constraints):
            if constraint.name.startswith(CONSTRAINT_PREFIX):
                removed.append("%s.%s" % (name, constraint.name))
                pose_bone.constraints.remove(constraint)
    return removed


def mute_legacy_constraints(armature_object, spine, dry_run, report):
    """链上的骨只留我们自己的约束生效；原件的 `mmd_*` / IK 一律静音（不删）。

    与四肢那条规矩唯一的差别：**不顺手静音影子双胞胎**（`_shadow_上半身` 之类）。
    四肢的影子骨是链上的成员（网格就挂在它们身上），而躯干的影子骨是"姿势来源"，
    静音它们会把别人驱动的东西弄掉。
    """
    muted = []
    skins = []
    for bone_name in list(spine["chain"]) + [spine["head"]]:
        pose_bone = armature_object.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        for constraint in pose_bone.constraints:
            if constraint.name.startswith(CONSTRAINT_PREFIX) or constraint.mute:
                continue
            if constraint.name == TRACK_CONSTRAINT:
                continue
            muted.append("%s.%s" % (bone_name, constraint.name))
            if not dry_run:
                constraint.mute = True
        for prefix in ("_shadow_", "_dummy_"):
            if (prefix + bone_name) in armature_object.data.bones:
                skins.append(prefix + bone_name)
    if muted:
        report("mute", "%d 条原件约束静音（只留 %s*）：%s" % (
            len(muted), CONSTRAINT_PREFIX, ", ".join(muted)))
    else:
        report("mute", "链上没有需要静音的原件约束")
    if skins:
        report("mute", "注意：这些骨还有影子双胞胎 %s —— 网格若挂在它们身上，躯干形变不归本阶段的链管" % (
            ", ".join(skins)))
    return muted


def calibrate_pole_angle(armature_object, spine, ik_constraint, geometry):
    """标 `pole_angle`：头部控制器不动，扫一遍角度，取 rest 关节位移最小的那一档。

    rest 姿势本身就是 IK 的一个解（目标就压在链的末端），所以"哪一档角度能把 rest 原样解回来"
    就是"极向量平面与骨自身的弯曲平面重合"的那一档。实测错 90° 时 rest 关节被掰走 26 cm。
    """
    bones = armature_object.data.bones
    rest_joints = [armature_object.matrix_world @ bones[name].head_local
                   for name in spine["chain"]]
    rest_joints.append(armature_object.matrix_world @ bones[spine["neck"]].tail_local)

    def error_of(angle_deg):
        ik_constraint.pole_angle = math.radians(angle_deg)
        bpy.context.view_layer.update()
        live = [world_head(armature_object, name) for name in spine["chain"]]
        live.append(world_tail(armature_object, spine["neck"]))
        return max((current - rest).length for current, rest in zip(live, rest_joints))

    coarse = []
    angle = 0.0
    while angle <= 180.0 + 1e-6:
        coarse.append((angle, error_of(angle)))
        angle += COARSE_STEP_DEG
    best_angle, best_error = min(coarse, key=lambda item: item[1])
    fine = []
    angle = best_angle - COARSE_STEP_DEG
    while angle <= best_angle + COARSE_STEP_DEG + 1e-6:
        fine.append((angle, error_of(angle)))
        angle += FINE_STEP_DEG
    best_angle, best_error = min(fine, key=lambda item: item[1])
    ik_constraint.pole_angle = math.radians(best_angle)
    bpy.context.view_layer.update()
    return best_angle, best_error, coarse


def add_constraints(armature_object, spine, head_control, look_at, options, dry_run, report):
    """颈上挂 IK（链长 = 躯干链长度、极向量 = 视点），头上挂世界空间复制旋转。"""
    pose_bones = armature_object.pose.bones
    neck_bone = pose_bones[spine["neck"]]
    head_bone = pose_bones[spine["head"]]
    head_control_label = head_control.name if head_control is not None else "头部控制器"
    look_at_label = look_at.name if look_at is not None else "视点控制器"

    default_angle = options["pole_angle"]
    if default_angle is None:
        default_angle = 90.0
    report("ik", "%s 加 IK：chain=%d target=%s pole=%s pole_angle=%.0f°（待标定）" % (
        spine["neck"], len(spine["chain"]), head_control_label, look_at_label, default_angle))
    if dry_run:
        report("copyrot", "%s 加世界空间复制旋转 ← %s" % (spine["head"], head_control_label))
        return None, None

    ik_constraint = neck_bone.constraints.new("IK")
    ik_constraint.name = CONSTRAINT_IK
    ik_constraint.target = head_control
    ik_constraint.chain_count = len(spine["chain"])
    ik_constraint.use_tail = True
    ik_constraint.use_stretch = True
    ik_constraint.pole_target = look_at
    ik_constraint.pole_angle = math.radians(default_angle)
    bpy.context.view_layer.update()

    if options["pole_angle"] is not None or options["no_calibrate"]:
        angle, error = default_angle, None
        report("ik", "按指定的 %.0f° 用，不标定" % angle)
    else:
        angle, error, coarse = calibrate_pole_angle(
            armature_object, spine, ik_constraint, None)
        span = "、".join("%.0f°=%.4f" % (item[0], item[1]) for item in coarse[::6])
        report("ik", "标定 pole_angle = %.0f°（rest 关节最大位移 %.6f；粗扫 %s）" % (
            angle, error, span))

    rotation_constraint = head_bone.constraints.new("COPY_ROTATION")
    rotation_constraint.name = CONSTRAINT_ROT
    rotation_constraint.target = head_control
    rotation_constraint.subtarget = ""
    rotation_constraint.owner_space = "WORLD"
    rotation_constraint.target_space = "WORLD"
    rotation_constraint.mix_mode = "REPLACE"
    rotation_constraint.use_x = True
    rotation_constraint.use_y = True
    rotation_constraint.use_z = True
    rotation_constraint.mute = False
    rotation_constraint.influence = 1.0
    report("copyrot", "%s 加世界空间复制旋转 ← %s" % (spine["head"], head_control.name))
    bpy.context.view_layer.update()
    return ik_constraint, rotation_constraint


# ── 自检 ────────────────────────────────────────────────────────────────
def mesh_points(depsgraph):
    """场景里所有网格的世界空间顶点（评估后的，含形变）。"""
    result = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        result[obj.name] = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        evaluated.to_mesh_clear()
    return result


def upper_group_names(armature_object, spine):
    """躯干链上所有可能带权重的顶点组名（含影子变体）。"""
    names = set(spine["chain"]) | {spine["head"], spine["neck"]}
    for name in list(names):
        for prefix in ("_shadow_", "_dummy_"):
            if (prefix + name) in armature_object.data.bones:
                names.add(prefix + name)
    return names


def rest_mesh_report(before, after, armature_object, spine, report):
    """rest 姿势下网格动了多少：躯干顶点单独算（IK 解算会把它按极向量平面归位）。"""
    groups = upper_group_names(armature_object, spine)
    worst_all = 0.0
    worst_upper = 0.0
    upper_vertices = 0
    for object_name, before_points in before.items():
        after_points = after.get(object_name)
        if after_points is None or len(after_points) != len(before_points):
            report("check", "%s 顶点数变了（%d → %s），跳过位移比较" % (
                object_name, len(before_points),
                len(after_points) if after_points is not None else "?"))
            continue
        obj = bpy.data.objects[object_name]
        group_indices = {group.index for group in obj.vertex_groups if group.name in groups}
        for index, (old_point, new_point) in enumerate(zip(before_points, after_points)):
            delta = (new_point - old_point).length
            worst_all = max(worst_all, delta)
            if group_indices:
                source = obj.data.vertices[index]
                if any(member.group in group_indices and member.weight > 0.01
                       for member in source.groups):
                    upper_vertices += 1
                    worst_upper = max(worst_upper, delta)
    return {
        "max_all": worst_all,
        "max_upper": worst_upper,
        "upper_vertices": upper_vertices,
    }


def measure_poses(armature_object, spine, head_control, look_at, geometry):
    """把头部控制器摆到几个位置，量"跟得住 / 头朝向 / 头看着视点 / 往极向量那侧弯"。

    量完把控制器复位。验收器（`rig_verify.py`）直接调这个函数，避免两处各写一套口径。
    """
    front = geometry["front_axis"] if geometry["front_axis"] is not None else Vector((0.0, -1.0, 0.0))
    front = front.normalized()
    up = Vector((0.0, 0.0, 1.0))
    side = front.cross(up)
    if side.length < 1e-6:
        side = Vector((1.0, 0.0, 0.0))
    side.normalize()
    scale = geometry["chain_length"]
    offsets = (
        ("rest", Vector((0.0, 0.0, 0.0))),
        ("前伸 15%", front * scale * 0.15),
        ("侧移 15%", side * scale * 0.15),
        ("低头 12%", -up * scale * 0.12),
    )

    base_matrix = head_control.matrix_world.copy()
    base_location = base_matrix.translation.copy()
    results = []
    for tag, offset in offsets:
        head_control.matrix_world = Matrix.Translation(base_location + offset) @ \
            base_matrix.to_quaternion().to_matrix().to_4x4()
        bpy.context.view_layer.update()
        neck_tail = world_tail(armature_object, spine["neck"])
        target = head_control.matrix_world.translation
        head_rotation = (armature_object.matrix_world.to_quaternion()
                         @ armature_object.pose.bones[spine["head"]].matrix.to_quaternion())
        control_rotation = head_control.matrix_world.to_quaternion()
        head_z = pose_axes(armature_object, spine["head"])[2]
        aim = look_at.matrix_world.translation - world_head(armature_object, spine["head"])
        results.append({
            "tag": tag,
            "gap": (neck_tail - target).length,
            "rotation_error": math.degrees(head_rotation.rotation_difference(control_rotation).angle),
            "aim_error": common.angle_between(head_z, aim),
            "bend_error": bend_toward_pole(armature_object, spine, look_at),
        })
    head_control.matrix_world = base_matrix
    bpy.context.view_layer.update()
    return results


def probe_poses(armature_object, spine, head_control, look_at, geometry, report):
    """跑 `measure_poses` 并把每一档打印出来。"""
    results = measure_poses(armature_object, spine, head_control, look_at, geometry)
    for item in results:
        report("check", "%-8s 颈尾离控件 %.5f m，头朝向差 %.2f°，头看向视点差 %.2f°，弯曲朝极向量偏 %.1f°" % (
            item["tag"], item["gap"], item["rotation_error"],
            item["aim_error"] if item["aim_error"] is not None else -1.0,
            item["bend_error"] if item["bend_error"] is not None else -1.0))
    return results


def bend_toward_pole(armature_object, spine, look_at):
    """中间关节相对"链根→末端"这条弦的垂直偏移，与极向量相对同一根弦的垂直偏移的夹角。

    两个解都能让末端落到目标上，只有朝向分得清"往哪边弯"（和手臂肘那条判据一样）。
    """
    chord_start = world_head(armature_object, spine["chain"][-1])
    chord_end = head_control_point(armature_object, spine)
    chord = chord_end - chord_start
    if chord.length < 1e-6:
        return None
    chord_unit = chord.normalized()
    pole_offset = look_at.matrix_world.translation - chord_start
    pole_perp = pole_offset - chord_unit * pole_offset.dot(chord_unit)
    best = None
    for name in spine["chain"][1:]:
        joint = world_head(armature_object, name) - chord_start
        joint_perp = joint - chord_unit * joint.dot(chord_unit)
        if joint_perp.length < 1e-6 or pole_perp.length < 1e-6:
            continue
        angle = common.angle_between(joint_perp, pole_perp)
        if angle is None:
            continue
        best = angle if best is None else max(best, angle)
    return best


def head_control_point(armature_object, spine):
    """链末端的当前位置（= 颈骨的尾端）。"""
    return world_tail(armature_object, spine["neck"])


def detect_spine_quiet(armature_object, chain_count=3):
    """认链但不打印（验收器用）；认不出返回 None。"""
    options = {"neck": None, "head": None, "chain_count": chain_count}
    return detect_spine(armature_object, options, lambda *_args: None)


# ── 进度 ────────────────────────────────────────────────────────────────
def write_progress(armature_object, spine, checks, options, report):
    def mark(prefix):
        matched = [item for item in checks if item["name"].startswith(prefix)]
        if not matched:
            return "-"
        return "x" if all(item["ok"] for item in matched) else "!"

    failures = [item["name"] for item in checks if not item["ok"]]
    row = progress.make_row(
        PART_NAME,
        hier=mark("链条关节"),
        zaxis=mark("头骨 Z 轴"),
        arch="-",
        ik=mark("IK"),
        copyrot=mark("复制旋转"),
        twist="-",
        leaf="-",
        notes=("FAIL: " + "; ".join(failures)) if failures else "verified",
    )
    existing = progress.read(armature_object)
    merged = progress.merge_rows(existing["rows"], [row])
    # 这一站刚加完，等于"还没经过完整验收"：把 DONE 退回 IN PROGRESS，
    # 等 rig_verify 把 upper 一起验过再标 DONE（否则"DONE"就成了"加完就算完"）。
    progress.write(armature_object, 'armature "%s"' % armature_object.name, "IN PROGRESS",
                   merged, "rig_upper.py",
                   note="%s：%s；视点=极向量；pole_angle 见 IK 约束" % (
                       options["head_control"], " → ".join(spine["chain"])))
    report("progress", "进度文本块已写回（status=IN PROGRESS，等 rig_verify 验过再标 DONE）")


# ── 主流程 ──────────────────────────────────────────────────────────────
def report_current_state(armature_object, spine, options, report):
    """dry-run 时先把现状摊开：链上每根骨挂着的约束、两个控制器在哪、同名族还有谁。

    接手一个半成品时靠这一屏判断"这条链做过没有、做到哪一步"，比重跑一遍安全。
    """
    for bone_name in list(spine["chain"]) + [spine["head"]]:
        pose_bone = armature_object.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        connect = armature_object.data.bones[bone_name].use_connect
        if not pose_bone.constraints:
            report("state", "%s（connect=%d）没有约束" % (bone_name, 1 if connect else 0))
            continue
        described = []
        for constraint in pose_bone.constraints:
            target = getattr(constraint, "target", None)
            described.append("%s[%s]%s%s" % (
                constraint.name, constraint.type,
                "→%s" % target.name if target is not None else "",
                "（静音）" if constraint.mute else ""))
        report("state", "%s（connect=%d）：%s" % (bone_name, 1 if connect else 0, "；".join(described)))

    for option_key in ("head_control", "look_at"):
        name = options[option_key]
        obj = bpy.data.objects.get(name)
        if obj is None:
            report("state", "%s 不存在（这一轮会造）" % name)
            continue
        report("state", "%s 在 %s，父级 = %s，约束 %d 条" % (
            name, _fmt(obj.matrix_world.translation),
            obj.parent.name if obj.parent else "无", len(obj.constraints)))

    families = ("Head_Control", "Look_At")
    leftovers = []
    for obj in bpy.data.objects:
        if obj.type != "EMPTY":
            continue
        if obj.name in (options["head_control"], options["look_at"]):
            continue
        if any(obj.name.startswith(family) for family in families):
            leftovers.append(obj.name)
    if leftovers:
        report("state", "同名族里还有别的对象：%s（多半是乐器阶段建的，本阶段不动；"
                        "后面的阶段会把 test 控件换成它们）" % "、".join(sorted(leftovers)))


def main():
    options = parse_args()
    if not options["file"]:
        print(__doc__)
        return
    ok, open_warning = common.open_mainfile_tolerant(options["file"])
    if open_warning:
        print("注意：载入时报错（多为状态键指针损坏，已跳过）：%s" % open_warning)
    if not ok:
        print("UPPER 打不开文件：%s" % options["file"])
        sys.exit(1)

    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if options["armature"]:
        armatures = [obj for obj in armatures if obj.name == options["armature"]]
    if not armatures:
        print("UPPER 没找到骨架")
        sys.exit(1)
    if len(armatures) > 1:
        print("UPPER 文件里有 %d 套骨架，用 --armature 指定：%s" % (
            len(armatures), ", ".join(obj.name for obj in armatures)))
        sys.exit(1)
    armature_object = armatures[0]
    bpy.context.view_layer.update()

    def report(step, message):
        print("  [%-10s] %s" % (step, message))

    print("")
    print("上半身 / 头部控制链：%s / %s%s" % (
        os.path.basename(options["file"]), armature_object.name,
        "（dry-run，只算不写）" if options["dry_run"] else ""))

    offenders = [pose_bone.name for pose_bone in armature_object.pose.bones
                 if (pose_bone.matrix_basis.translation.length > 1e-4
                     or abs(pose_bone.matrix_basis.to_quaternion().angle) > 1e-4)]
    if offenders:
        report("warn", "骨架不是 rest 姿势（%d 根骨有变换），标定与位移测量会不准：%s" % (
            len(offenders), ", ".join(offenders[:6])))

    spine = detect_spine(armature_object, options, report)
    if spine is None:
        print("UPPER 认不出躯干链，停下来")
        sys.exit(1)
    geometry = spine_geometry(armature_object, spine, options)
    report("geometry", "链长 %.4f，头骨长 %.4f，前方向 %s（%s）" % (
        geometry["chain_length"], geometry["head_length"],
        _fmt(geometry["front_axis"]) if geometry["front_axis"] is not None else "未识别",
        geometry["front_evidence"]))

    if options["dry_run"]:
        # 先摊现状（含我们上次加的那两条约束），再摘掉重算 —— 顺序反了就会看到"链上没约束"。
        report_current_state(armature_object, spine, options, report)
        print("")
    removed = strip_our_constraints(armature_object, spine)
    if removed:
        report("reset", "重跑：先摘掉上次加的 %d 条约束（%s）" % (len(removed), ", ".join(removed)))
    bpy.context.view_layer.update()
    before_mesh = mesh_points(bpy.context.evaluated_depsgraph_get())

    head_control = ensure_controller(options["head_control"], options["dry_run"], report)
    look_at = ensure_controller(options["look_at"], options["dry_run"], report)
    if options["dry_run"]:
        place_controllers(None, None, geometry, options, True, report)
        if options["no_track"]:
            report("track", "按 --no-track 不加 Track_To")
        else:
            report("track", "会在 %s 上加 Track_To：本地 Z 轴指向 %s、上方向取本地 Y" % (
                options["head_control"], options["look_at"]))
        connect_chain(armature_object, spine, options, True, report)
        mute_legacy_constraints(armature_object, spine, True, report)
        add_constraints(armature_object, spine, None, None, options, True, report)
        print("")
        print("dry-run 结束：没有写任何东西")
        return

    head_control, look_at = place_controllers(
        head_control, look_at, geometry, options, False, report)
    ensure_track(head_control, look_at, options, False, report)

    loose_joints = connect_chain(armature_object, spine, options, False, report)
    mute_legacy_constraints(armature_object, spine, False, report)
    ik_constraint, rotation_constraint = add_constraints(
        armature_object, spine, head_control, look_at, options, False, report)

    checks = []

    # ── 自检 ──
    after_mesh = mesh_points(bpy.context.evaluated_depsgraph_get())
    displacement = rest_mesh_report(before_mesh, after_mesh, armature_object, spine, report)
    report("check", "rest 网格：整网格最大位移 %.6f m，躯干顶点最大位移 %.6f m（%d 个顶点）" % (
        displacement["max_all"], displacement["max_upper"], displacement["upper_vertices"]))
    checks.append({
        "group": "duty", "name": "rest 网格位移（躯干以外）",
        "ok": displacement["max_all"] <= REST_MESH_TOLERANCE,
        "detail": "最大 %.7f m（容差 %.0e）" % (displacement["max_all"], REST_MESH_TOLERANCE),
    })

    probes = probe_poses(armature_object, spine, head_control, look_at, geometry, report)
    reach = max(item["gap"] for item in probes)
    rotation = max(item["rotation_error"] for item in probes)
    aims = [item["aim_error"] for item in probes if item["aim_error"] is not None]
    bends = [item["bend_error"] for item in probes if item["bend_error"] is not None]
    aim = max(aims) if aims else 0.0
    bend = max(bends) if bends else 0.0
    checks.append({
        "group": "func", "name": "颈尾跟住头部控制器",
        "ok": reach <= geometry["chain_length"] * REACH_TOLERANCE_RATIO,
        "detail": "最大差 %.5f m（容差 %.5f）" % (reach, geometry["chain_length"] * REACH_TOLERANCE_RATIO),
    })
    checks.append({
        "group": "func", "name": "头骨朝向 = 头部控制器",
        "ok": rotation <= ROTATION_TOLERANCE_DEG,
        "detail": "最大 %.3f°（容差 %.1f°）" % (rotation, ROTATION_TOLERANCE_DEG),
    })
    checks.append({
        "group": "func", "name": "头骨 Z 轴指向视点",
        "ok": aim <= AIM_TOLERANCE_DEG,
        "detail": "最大 %.2f°（容差 %.1f°）" % (aim, AIM_TOLERANCE_DEG),
    })
    checks.append({
        "group": "func", "name": "躯干往极向量那侧弯",
        "ok": bend <= BEND_TOLERANCE_DEG,
        "detail": "最大偏 %.1f°（容差 %.1f°）" % (bend, BEND_TOLERANCE_DEG),
    })
    checks.append({
        "group": "struct", "name": "链条关节对接（tail=head + connect）",
        "ok": not loose_joints,
        "detail": "、".join(loose_joints) if loose_joints else "%d 对关节全部相接" % len(spine["chain"]),
    })
    ik_ok = (ik_constraint is not None
             and ik_constraint.chain_count == len(spine["chain"])
             and ik_constraint.target is head_control
             and ik_constraint.pole_target is look_at)
    checks.append({
        "group": "struct", "name": "IK 参数（链长 / 目标 / 极向量）", "ok": ik_ok,
        "detail": "chain=%d target=%s pole=%s pole_angle=%.1f°" % (
            ik_constraint.chain_count if ik_constraint else -1,
            ik_constraint.target.name if ik_constraint and ik_constraint.target else "?",
            ik_constraint.pole_target.name if ik_constraint and ik_constraint.pole_target else "?",
            math.degrees(ik_constraint.pole_angle) if ik_constraint else 0.0),
    })
    copyrot_ok = (rotation_constraint is not None
                  and rotation_constraint.target is head_control
                  and rotation_constraint.owner_space == "WORLD"
                  and rotation_constraint.target_space == "WORLD"
                  and rotation_constraint.mix_mode == "REPLACE")
    checks.append({
        "group": "struct", "name": "复制旋转（世界空间 REPLACE）", "ok": copyrot_ok,
        "detail": "目标 %s" % (rotation_constraint.target.name if rotation_constraint else "?"),
    })
    checks.append({
        "group": "struct", "name": "控制器独立（没有父级）",
        "ok": head_control.parent is None and look_at.parent is None,
        "detail": "%s.parent=%s，%s.parent=%s" % (
            head_control.name, head_control.parent.name if head_control.parent else "无",
            look_at.name, look_at.parent.name if look_at.parent else "无"),
    })

    failed = [item for item in checks if not item["ok"]]
    print("")
    for item in checks:
        print("  [%-6s] %-10s %-30s %s" % (
            item["group"], "PASS" if item["ok"] else "FAIL", item["name"], item["detail"]))
    print("")
    print("UPPER RESULT: %s（%d 项通过，%d 项失败）" % (
        "PASS" if not failed else "FAIL",
        len([item for item in checks if item["ok"]]), len(failed)))

    write_progress(armature_object, spine, checks, options, report)

    if options["json"]:
        with open(options["json"], "w", encoding="utf-8") as handle:
            json.dump({
                "file": options["file"],
                "armature": armature_object.name,
                "spine": spine,
                "geometry": {
                    "chain_length": geometry["chain_length"],
                    "head_length": geometry["head_length"],
                    "head_control": [round(value, 6) for value in head_control.matrix_world.translation],
                    "look_at": [round(value, 6) for value in look_at.matrix_world.translation],
                },
                "pole_angle_deg": round(math.degrees(ik_constraint.pole_angle), 2) if ik_constraint else None,
                "displacement": displacement,
                "probes": probes,
                "checks": checks,
            }, handle, ensure_ascii=False, indent=1)
        print("json: %s" % options["json"])

    if options["out"]:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(options["out"]), copy=True)
        print("已另存：%s" % options["out"])
    elif options["save"]:
        try:
            bpy.ops.wm.save_mainfile()
        except RuntimeError as error:
            message = str(error).splitlines()[0] if str(error) else ""
            print("存盘时 Blender 报了一条错（文件已写出，多半是缺贴图）：%s" % message)
        print("已保存：%s" % bpy.data.filepath)
    else:
        print("没有保存（要落盘加 --out <路径> 或 --save）")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
