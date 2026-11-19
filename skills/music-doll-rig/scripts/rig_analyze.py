# -*- coding: utf-8 -*-
"""MusicDoll 骨架改造 —— 分析器（只读）。

对一套骨架做两件事：

1. **认链**：左右各认 手臂三段（上臂/前臂/手掌）、五指各三节、腿三段（大腿/小腿/脚掌），
   每条链都给证据（命名 / 父子 / 结构）与置信度，并区分**本体形变骨**、**MCH 主骨**、**D 影子链**；
2. **体检**：按规则逐条比对（层级、Z 朝向、拱形、IK、手掌复制旋转、扭转复制、指尖骨），
   每条给"已满足 / 不满足 / 不确定"与证据。

**本脚本绝不写 .blend**。认不出来的一律报"不确定 + 候选"，不猜。

用法：

    blender -b --factory-startup -P rig_analyze.py -- <file.blend> \
        [--armature 名字] [--front x,y,z] [--json out.json] [--summary]

`--summary` 只打一行结论（跑全量普查用），`--json` 落结构化结果（改造单草稿的来源）。
"""
import json
import os
import re
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rig_common as common  # noqa: E402

FINGER_KEYS = (
    ("thumb", ("親指", "thumb", "Thumb")),
    ("index", ("人指", "index", "Index")),
    ("middle", ("中指", "middle", "Middle")),
    ("ring", ("薬指", "ring", "Ring")),
    ("pinky", ("小指", "pinky", "Pinky", "LittleFinger", "little")),
)
FINGER_ORDER = ("thumb", "index", "middle", "ring", "pinky")
FINGER_CONTROLLER_PREFIX = {"thumb": "T", "index": "I", "middle": "M", "ring": "R", "pinky": "P"}

# 规则（v3.2）：手臂 Z 朝后、腿 Z 也朝后；拱形（凸侧）手臂朝后、腿朝前（膝盖）。
ARM_BEND = "back"
LEG_BEND = "front"
LEG_Z = "back"
Z_AXIS_TOLERANCE_DEG = 2.0
ARCH_TARGET_PERCENT = 3.0
ARCH_STRAIGHT_PERCENT = 0.5


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {"file": None, "armature": None, "json": None, "summary": False, "front": None}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--armature":
            index += 1
            options["armature"] = argv[index]
        elif token == "--json":
            index += 1
            options["json"] = argv[index]
        elif token == "--front":
            index += 1
            parts = [float(part) for part in argv[index].split(",")]
            options["front"] = Vector(parts).normalized()
        elif token == "--summary":
            options["summary"] = True
        else:
            options["file"] = token
        index += 1
    return options


def vector_to_tuple(vector):
    if vector is None:
        return None
    return [round(vector.x, 4), round(vector.y, 4), round(vector.z, 4)]


# ── 认链 ────────────────────────────────────────────────────────────────
def ancestors_of(bone_index, name):
    """从 name 往上数到根，返回 [(名字, 距 name 的层数)]。"""
    result = []
    current = bone_index[name]["parent"]
    depth = 1
    while current is not None:
        result.append((current, depth))
        current = bone_index[current]["parent"]
        depth += 1
    return result


def resolve_side(side, bone_index, hand_name, front_axis):
    """侧别：优先用名字；名字没有就用位置（左 = 上方向 × 前方向）。"""
    if side:
        return side, "name suffix"
    up = Vector((0.0, 0.0, 1.0))
    left = up.cross(front_axis)
    position = bone_index[hand_name]["head"]
    return ("L" if position.dot(left) >= 0 else "R"), "position (left = up x front)"


SKIP_VARIANTS = ("twist", "aux", "leaf", "ik", "segment")
BODY_NAME_MARKERS = (
    "lowerbody", "upperbody", "pelvis", "hip", "hips", "root", "spine", "center", "センター",
    "腰", "上半身", "下半身", "chest", "torso", "neck", "head", "頭", "首", "shoulder", "肩",
)


def walk_subtree(bone_index, root_name, limit=200):
    """从 root 起按层序（BFS）遍历子树，返回骨名列表（含 root 自己）。"""
    queue = [root_name]
    ordered = []
    while queue and len(ordered) < limit:
        current = queue.pop(0)
        ordered.append(current)
        entry = bone_index.get(current)
        if entry is None:
            continue
        queue.extend(entry["children"])
    return ordered


def find_role_in_subtree(bone_index, root_name, role):
    """在子树里找指定角色的骨（本体/影子优先），返回骨名或 None。"""
    if root_name is None:
        return None
    for name in walk_subtree(bone_index, root_name):
        info = common.role_from_name(name)
        if info["role"] == role and info["variant"] in ("plain", "shadow"):
            return name
    return None


def skipped_ok(info):
    """走链时能不能跳过这根骨：扭转/辅助/末端/IK/分段要跳过，但 MCH 主骨是链上的真骨，不能跳。"""
    if info["variant"] == "mechanism":
        return False
    return info["variant"] in SKIP_VARIANTS


def walk_up_segment(bone_index, start_name, steps=2):
    """从 start 往上取 steps 根"链上的骨"，跳过扭转/辅助/末端/IK 骨。

    返回 (骨名列表, 被跳过的骨名列表)。
    """
    segments = []
    skipped = []
    current = bone_index[start_name]["parent"]
    while current is not None and len(segments) < steps:
        info = common.role_from_name(current)
        if skipped_ok(info):
            skipped.append(current)
            current = bone_index[current]["parent"]
            continue
        segments.append(current)
        current = bone_index[current]["parent"]
    return segments, skipped


def looks_like_body_root(name):
    """这根骨看起来像躯干/根，而不是四肢的一段（用来防止把 LowerBody 当成大腿）。"""
    _tags, stem, _side = common.parse_bone_name(name)
    lowered = stem.lower()
    return any(marker in lowered or marker in stem for marker in BODY_NAME_MARKERS)


def prefer_named_ancestor(bone_index, start_name, current_name, role, max_levels=5):
    """结构回溯抓到的是真骨还是一根控制骨？

    控制器重的骨架（Skirk、桑多涅）会在链上夹 `c_traj` / `c_leg_fk` 这类骨，结构上它们确实是父级，
    但"三段"应该是 `arm.l / forearm.l / hand.l`。所以：当前骨名字对不上角色时，在祖先里就近找
    一根名字对得上的骨替换过来；找不到就保留结构结果。
    """
    if current_name is None:
        return None
    info = common.role_from_name(current_name)
    if info["role"] == role and info["variant"] in ("plain", "shadow", "mechanism"):
        return current_name
    for name, depth in ancestors_of(bone_index, start_name):
        if depth > max_levels:
            break
        candidate = common.role_from_name(name)
        if candidate["role"] == role and candidate["variant"] in ("plain", "shadow"):
            return name
    return current_name


def identify_arm(bone_index, hand_name, front_axis):
    """认一条手臂链：手掌 → 前臂 → 上臂。

    两套结果：
    - `deform`：本体形变骨（`腕` / `ひじ`），Z 对齐与网格跟随都看它；
    - `functional`：IK 链实际走的那三根 —— 有 MCH 主骨就用主骨（作者的做法是让 IK 挂主骨），
      没有主骨就是本体骨。

    MCH 主骨不一定叫 `MCH_ひじ`（东风谷早苗 叫 `MCH_手捩`），所以主骨按"是不是 mechanism 变体"取，
    不按名字角色取；本体骨则在主骨子树里按角色找。
    """
    _tags, _stem, side = common.parse_bone_name(hand_name)
    side, side_evidence = resolve_side(side, bone_index, hand_name, front_axis)

    ancestry = ancestors_of(bone_index, hand_name)
    mechanism_ancestors = []
    for name, _depth in ancestry:
        info = common.role_from_name(name)
        if info["variant"] == "mechanism" and info["role"] != "hand":
            mechanism_ancestors.append(name)

    uncertain = []
    if len(mechanism_ancestors) >= 2:
        functional_forearm = mechanism_ancestors[0]
        functional_upper = mechanism_ancestors[1]
        functional_evidence = "MCH chain (%s → %s)" % (functional_forearm, functional_upper)
    else:
        if mechanism_ancestors:
            seed = mechanism_ancestors[0]
        else:
            seed = hand_name
        segments, skipped = walk_up_segment(bone_index, seed, steps=2)
        functional_forearm = segments[0] if len(segments) > 0 else None
        functional_upper = segments[1] if len(segments) > 1 else None
        functional_evidence = "structural walk from hand (skipped: %s)" % (", ".join(skipped) or "nothing")

    deform_forearm = find_role_in_subtree(bone_index, functional_forearm, "forearm") or functional_forearm
    deform_upper = find_role_in_subtree(bone_index, functional_upper, "upper_arm") or functional_upper

    # 控制器骨纠偏：链上抓到 c_xxx 这类控制骨时，改认名字对得上的那根
    functional_forearm = prefer_named_ancestor(bone_index, hand_name, functional_forearm, "forearm")
    functional_upper = prefer_named_ancestor(bone_index, hand_name, functional_upper, "upper_arm")
    if deform_forearm and common.role_from_name(deform_forearm)["role"] != "forearm":
        deform_forearm = prefer_named_ancestor(bone_index, hand_name, deform_forearm, "forearm")
    if deform_upper and common.role_from_name(deform_upper)["role"] != "upper_arm":
        deform_upper = prefer_named_ancestor(bone_index, hand_name, deform_upper, "upper_arm")
    if deform_forearm is functional_forearm:
        info = common.role_from_name(functional_forearm or "")
        if info["role"] != "forearm":
            uncertain.append("forearm role unconfirmed on %s (name says %s)" % (
                functional_forearm, info["role"] or info["variant"]))

    between = {"upper_forearm": [], "forearm_hand": []}
    if functional_upper and functional_forearm:
        for name, _depth in ancestors_of(bone_index, functional_forearm):
            if name == functional_upper:
                break
            between["upper_forearm"].append(name)
    if functional_forearm:
        for name, _depth in ancestors_of(bone_index, hand_name):
            if name == functional_forearm:
                break
            between["forearm_hand"].append(name)

    if functional_forearm is None:
        uncertain.append("forearm not identified")
    if functional_upper is None:
        uncertain.append("upper arm not identified")
    # 控制器骨架（Skirk / Norinde 系）：形变骨之间可能根本不互为父子，三段是"控制骨"串起来的。
    # 已经做过 MCH 的文件不算问题（那时手掌本来就挂在 MCH 前臂下，本体前臂是它的子级）。
    hand_ancestry = [name for name, _depth in ancestors_of(bone_index, hand_name)]
    if not mechanism_ancestors:
        if deform_forearm and deform_forearm not in hand_ancestry:
            uncertain.append("deform forearm %s is not in the hand's parent chain (control-rig skeleton)" % deform_forearm)
        if deform_upper and deform_upper not in hand_ancestry:
            uncertain.append("deform upper arm %s is not in the hand's parent chain (control-rig skeleton)" % deform_upper)
        # 名字也对不上（Skirk 抓到 c_traj 这种根控制骨）：不要硬当成上臂用
        for label, bone_name in (("forearm", functional_forearm), ("upper arm", functional_upper)):
            if not bone_name:
                continue
            role = common.role_from_name(bone_name)["role"]
            expected = "forearm" if label == "forearm" else "upper_arm"
            if role != expected:
                uncertain.append("%s unresolved: picked %s (its name is not %s-like)" % (
                    label, bone_name, expected))

    return {
        "side": side,
        "side_evidence": side_evidence,
        "hand": hand_name,
        "deform": {"upper": deform_upper, "forearm": deform_forearm, "hand": hand_name},
        "mechanism": {"upper": functional_upper if mechanism_ancestors else None,
                      "forearm": functional_forearm if mechanism_ancestors else None},
        "functional": {"upper": functional_upper, "forearm": functional_forearm, "hand": hand_name},
        "between": between,
        "evidence": {
            "hand": "structural (>=4 similar finger chains)",
            "functional": functional_evidence,
            "deform": "role lookup in the functional bone's subtree",
        },
        "uncertain": uncertain,
    }


def identify_legs(bone_index):
    """认腿：先按名字找脚掌，再**结构上**往上取小腿、大腿。

    这样 `Leg/Knee/Ankle`、`Thigh/Shin/Foot`、`足/ひざ/足首`、`足D/ひざD/足首D` 都能走通；
    名字只用来复核（名称角色与结构位置不一致时记进 issues）。
    """
    foot_candidates = {"L": [], "R": []}
    for name in bone_index:
        info = common.role_from_name(name)
        if info["role"] != "foot" or info["confidence"] != "high":
            continue
        side = info["side"]
        if side in foot_candidates:
            foot_candidates[side].append((name, info["variant"]))

    preference = {"plain": 0, "shadow": 1, "mechanism": 2}
    legs = {}
    for side in ("L", "R"):
        candidates = sorted(foot_candidates[side], key=lambda item: preference.get(item[1], 3))
        foot = candidates[0][0] if candidates else None
        entry = {
            "side": side,
            "foot": foot,
            "foot_variant": candidates[0][1] if candidates else None,
            "foot_candidates": [item[0] for item in candidates],
            "shin": None, "thigh": None,
            "shin_variant": None, "thigh_variant": None,
            "issues": [],
        }
        if foot is None:
            entry["issues"].append("no foot bone")
            legs[side] = entry
            continue

        segments, skipped = walk_up_segment(bone_index, foot, steps=2)
        shin = segments[0] if len(segments) > 0 else None
        thigh = segments[1] if len(segments) > 1 else None
        # 控制器骨纠偏（Skirk 的链上夹着 c_leg_fk）：名字对得上就用名字那根
        shin = prefer_named_ancestor(bone_index, foot, shin, "shin")
        thigh = prefer_named_ancestor(bone_index, foot, thigh, "thigh")
        entry["walk_skipped"] = skipped

        if thigh and looks_like_body_root(thigh):
            entry["issues"].append("candidate thigh %s looks like a body root; thigh missing?" % thigh)
            thigh = None
        if shin and looks_like_body_root(shin):
            entry["issues"].append("candidate shin %s looks like a body root; shin missing?" % shin)
            shin = None
        # 控制器骨架：小腿/大腿可能不在脚掌的父子链上（foot 挂在 leg_fk 这种控制骨下面）
        foot_ancestry = [name for name, _depth in ancestors_of(bone_index, foot)]
        for label, candidate in (("shin", shin), ("thigh", thigh)):
            if candidate and candidate not in foot_ancestry:
                entry["issues"].append(
                    "%s %s is not in the foot's parent chain (control-rig skeleton)" % (label, candidate))

        # 名字复核：结构位置上的骨叫什么角色（名字认不出这个角色时不报，只报"名字说是别的角色"）
        for label, name in (("shin", shin), ("thigh", thigh)):
            if not name:
                continue
            info = common.role_from_name(name)
            if info["role"] is not None and info["role"] != label:
                entry["issues"].append("%s candidate %s has name role %s (%s)" % (
                    label, name, info["role"], info["variant"]))
            entry[label + "_variant"] = info["variant"]

        entry["shin"] = shin
        entry["thigh"] = thigh

        for lower, upper_role in (("shin", "thigh"), ("foot", "shin")):
            lower_name = entry[lower]
            upper_name = entry[upper_role]
            if lower_name and upper_name:
                ancestry = [name for name, _depth in ancestors_of(bone_index, lower_name)]
                between = []
                for name in ancestry:
                    if name == upper_name:
                        break
                    between.append(name)
                entry["%s_under_%s" % (lower, upper_role)] = upper_name in ancestry
                entry["between_%s_%s" % (upper_role, lower)] = between
            else:
                entry["%s_under_%s" % (lower, upper_role)] = None
                entry["between_%s_%s" % (upper_role, lower)] = []
        legs[side] = entry
    return legs


def finger_role_of(name):
    """手指归属：返回 thumb/index/middle/ring/pinky 或 None。"""
    _tags, stem, _side = common.parse_bone_name(name)
    for role, keywords in FINGER_KEYS:
        for keyword in keywords:
            if keyword in stem:
                return role
    return None


def identify_fingers(bone_index, hand_name):
    """认五指：结构找出五条链（从手掌往下逐层找第一根合法指骨），再按命名分配身份。"""
    chains = common.find_finger_roots(bone_index, hand_name)
    fingers = {}
    unidentified = []
    for root_name, depth, total_length in chains:
        role = finger_role_of(root_name)
        if role is None:
            unidentified.append((root_name, depth, total_length))
            continue
        fingers[role] = {"root": root_name, "chain_depth": depth, "total_length": round(total_length, 5)}
    if unidentified and len(fingers) < 5:
        missing = [role for role in FINGER_ORDER if role not in fingers]
        for role, item in zip(missing, unidentified):
            fingers[role] = {
                "root": item[0], "chain_depth": item[1], "total_length": round(item[2], 5),
                "confidence": "low", "note": "identity by elimination, not by name",
            }

    for role, entry in fingers.items():
        parsed = common.analyze_finger_chain(bone_index, entry["root"])
        entry["segments"] = parsed["segments"]
        entry["deform_segments"] = parsed["deform_segments"]
        entry["tip"] = parsed["tip"]
        entry["spine"] = parsed["spine"]
        entry["extra_base_bones"] = parsed["extra"]
        if parsed["note"]:
            entry["note"] = parsed["note"]
        entry.setdefault("confidence", "high")
    return fingers


# ── 体检 ────────────────────────────────────────────────────────────────
def z_axis_check(bone_index, bone_names, target_direction, label):
    """逐骨算 Z 轴与规则方向的夹角（都先投影到垂直于骨方向的平面）。"""
    results = []
    for name in bone_names:
        if name is None:
            continue
        entry = bone_index[name]
        _x_axis, y_axis, z_axis = common.bone_axes(entry)
        target_in_plane = common.project_perpendicular(target_direction, y_axis)
        if target_in_plane.length < 0.15:
            results.append({
                "bone": name,
                "status": "skip",
                "reason": "target projection degenerate (%.3f)" % target_in_plane.length,
            })
            continue
        angle = common.angle_between(z_axis, target_in_plane)
        results.append({
            "bone": name,
            "status": "ok" if angle is not None and angle <= Z_AXIS_TOLERANCE_DEG else "fail",
            "angle_deg": round(angle, 2) if angle is not None else None,
            "z_axis": vector_to_tuple(z_axis),
            "target": vector_to_tuple(target_in_plane.normalized()),
        })
    return {"label": label, "bones": results}


def arch_check(bone_index, chain_names, bend_direction):
    """拱形检查：方向对不对、拱高够不够（目标 3%）。"""
    arch = common.chain_arch(bone_index, chain_names)
    if arch is None:
        return {"status": "n/a", "reason": "chain shorter than 2 bones"}
    direction = arch["direction"]
    if direction is None:
        return {
            "status": "straight",
            "max_offset_ratio_percent": round(arch["max_offset_ratio_percent"], 3),
            "reason": "joints exactly on chord",
        }
    angle = common.angle_between(direction, bend_direction)
    ratio = arch["max_offset_ratio_percent"]
    if angle is None:
        status = "straight"
    elif angle <= 30.0:
        status = "ok" if ratio >= ARCH_TARGET_PERCENT * 0.9 else ("ok_thin" if ratio > ARCH_STRAIGHT_PERCENT else "straight")
    elif angle >= 150.0:
        status = "wrong_side"
    else:
        status = "oblique"
    return {
        "status": status,
        "angle_to_bend_direction_deg": round(angle, 2) if angle is not None else None,
        "max_offset_ratio_percent": round(ratio, 3),
        "target_percent": ARCH_TARGET_PERCENT,
        "direction": vector_to_tuple(direction),
        "bend_direction": vector_to_tuple(bend_direction),
        "joints": [
            {"bone": joint["bone"], "offset": round(joint["offset"], 5), "ratio_percent": round(joint["ratio_percent"], 3)}
            for joint in arch["joints"]
        ],
    }


def constraint_report(armature_object, bone_names):
    """把相关骨上的约束整理出来：IK / 复制旋转 / TRANSFORM。"""
    report = {}
    for name in bone_names:
        if name is None:
            continue
        pose_bone = armature_object.pose.bones.get(name)
        if pose_bone is None:
            continue
        items = []
        for con in pose_bone.constraints:
            item = {
                "name": con.name,
                "type": con.type,
                "target": con.target.name if getattr(con, "target", None) else None,
                "subtarget": getattr(con, "subtarget", None),
                "owner_space": getattr(con, "owner_space", None),
                "target_space": getattr(con, "target_space", None),
                "influence": round(con.influence, 4),
                "mute": con.mute,
            }
            if con.type == "IK":
                item.update({
                    "chain_count": con.chain_count,
                    "pole_target": con.pole_target.name if getattr(con, "pole_target", None) else None,
                    "pole_angle_deg": round(con.pole_angle * 57.295779513, 2),
                    "use_stretch": con.use_stretch,
                })
            if con.type == "COPY_ROTATION":
                item.update({"use_x": con.use_x, "use_y": con.use_y, "use_z": con.use_z, "mix_mode": con.mix_mode})
            items.append(item)
        if items:
            report[name] = items
    return report


def find_controllers(prefix, side):
    """找控制器物体：`H_L_xxx` / `F_R_xxx` 这种以 `前缀_侧_` 开头的 EMPTY。"""
    pattern = re.compile(r"^%s_%s([._]|$)" % (re.escape(prefix), side))
    found = []
    for obj in bpy.data.objects:
        if pattern.match(obj.name):
            found.append(obj.name)
    return found


def check_arm(armature_object, bone_index, arm, front_axis):
    """手臂链的七项检查（hier / zaxis / arch / ik / copyrot / twist / leaf）。"""
    back = -front_axis
    functional = arm["functional"]
    deform = arm["deform"]
    unit_bones = [name for name in (
        functional["upper"], functional["forearm"], functional["hand"],
        deform["upper"], deform["forearm"]) if name]
    unit_bones += arm["between"]["upper_forearm"] + arm["between"]["forearm_hand"]

    hierarchy = {
        "status": "ok" if not arm["between"]["upper_forearm"] and not arm["between"]["forearm_hand"] else "blocked",
        "between_upper_forearm": arm["between"]["upper_forearm"],
        "between_forearm_hand": arm["between"]["forearm_hand"],
    }

    constraints = constraint_report(armature_object, unit_bones)
    ik_entries = []
    for name, items in constraints.items():
        for item in items:
            if item["type"] == "IK":
                ik_entries.append(dict(item, owner=name))

    hand = functional["hand"]
    hand_copy_rotation = [
        item for item in constraints.get(hand, [])
        if item["type"] == "COPY_ROTATION" and item["owner_space"] == "WORLD" and item["target_space"] == "WORLD"
    ]
    twist_copies = []
    # 扭转骨不一定留在手臂单元里（芙宁娜 / 菲谢尔把它们挂到 MCH 主骨下），所以要整骨架扫
    for pose_bone in armature_object.pose.bones:
        if pose_bone.name == hand:
            continue
        for con in pose_bone.constraints:
            if con.type != "COPY_ROTATION":
                continue
            if con.subtarget != hand or con.owner_space != "LOCAL" or con.target_space != "LOCAL":
                continue
            twist_copies.append({
                "bone": pose_bone.name, "influence": round(con.influence, 4),
                "use_xyz": (con.use_x, con.use_y, con.use_z),
            })
    twist_copies.sort(key=lambda item: item["influence"])

    z_bones = []
    for name in (functional["upper"], functional["forearm"], deform["upper"], deform["forearm"], deform["hand"]):
        if name and name not in z_bones:
            z_bones.append(name)

    return {
        "chain": functional,
        "deform": deform,
        "mechanism": arm["mechanism"],
        "deform_chain": [name for name in (deform["upper"], deform["forearm"], deform["hand"]) if name],
        "hierarchy": hierarchy,
        "zaxis": z_axis_check(bone_index, z_bones, back, "arm Z should point BACK"),
        "arch": arch_check(bone_index, [name for name in (functional["upper"], functional["forearm"]) if name], back),
        "ik": ik_entries,
        "copyrot_hand": hand_copy_rotation,
        "twist_copies": twist_copies,
        "constraints": constraints,
        "controllers": {"hand": find_controllers("H", arm["side"]), "pole": find_controllers("HP", arm["side"])},
        "identification": arm,
    }


def check_leg(armature_object, bone_index, leg, front_axis):
    thigh, shin, foot = leg["thigh"], leg["shin"], leg["foot"]
    chain_names = [name for name in (thigh, shin, foot) if name]
    between_thigh_shin = leg.get("between_thigh_shin", [])
    between_shin_foot = leg.get("between_shin_foot", [])
    hierarchy = {
        "status": "ok" if not between_thigh_shin and not between_shin_foot else "blocked",
        "between_thigh_shin": between_thigh_shin,
        "between_shin_foot": between_shin_foot,
        "shin_under_thigh": leg.get("shin_under_thigh"),
        "foot_under_shin": leg.get("foot_under_shin"),
    }
    constraints = constraint_report(armature_object, chain_names + between_thigh_shin + between_shin_foot)
    ik_entries = []
    for name, items in constraints.items():
        for item in items:
            if item["type"] == "IK":
                ik_entries.append(dict(item, owner=name))
    foot_copy_rotation = [
        item for item in constraints.get(foot, [])
        if item["type"] == "COPY_ROTATION" and item["owner_space"] == "WORLD" and item["target_space"] == "WORLD"
    ]

    # 规则（v3.2）：腿的 Z 朝**正后方**，膝盖拱形朝**正前方** —— 两者方向相反是正常的，不是冲突。
    z_check = z_axis_check(bone_index, chain_names, -front_axis, "leg Z should point BACK")
    z_angles = [item["angle_deg"] for item in z_check["bones"] if item["status"] != "skip"]
    arch = arch_check(bone_index, [name for name in (thigh, shin) if name], front_axis)
    rule_conflict = None
    if z_angles and all(angle > 120.0 for angle in z_angles):
        rule_conflict = "bone Z points FRONT (rule wants BACK)"

    return {
        "chain": {"thigh": thigh, "shin": shin, "foot": foot},
        "variants": {role: leg.get(role + "_variant") for role in ("thigh", "shin", "foot")},
        "candidates": {role: leg.get(role + "_candidates", []) for role in ("thigh", "shin", "foot")},
        "issues": leg.get("issues", []),
        "hierarchy": hierarchy,
        "zaxis": z_check,
        "arch": arch,
        "ik": ik_entries,
        "copyrot_foot": foot_copy_rotation,
        "constraints": constraints,
        "rule_conflict": rule_conflict,
        "controllers": {"foot": find_controllers("F", leg.get("side") or "L")},
        "identification": leg,
    }


def check_finger(armature_object, bone_index, finger, nail_direction, side):
    segments = finger["segments"]
    tip = finger["tip"]
    leaf = {
        "tip_bone": tip,
        "exists": tip is not None,
        "deform": bone_index[tip]["deform"] if tip else None,
        "length": round(bone_index[tip]["length"], 5) if tip else None,
        "ratio_to_last_segment_percent": (
            round(bone_index[tip]["length"] / bone_index[segments[-1]]["length"] * 100.0, 2)
            if tip and segments and bone_index[segments[-1]]["length"] > 1e-9 else None
        ),
    }
    constraints = constraint_report(armature_object, segments + ([tip] if tip else []))
    ik_entries = []
    for name, items in constraints.items():
        for item in items:
            if item["type"] == "IK":
                ik_entries.append(dict(item, owner=name))
    prefix = FINGER_CONTROLLER_PREFIX.get(finger.get("role"), "?")
    return {
        "segments": segments,
        "leaf": leaf,
        "zaxis": z_axis_check(bone_index, segments, nail_direction, "finger Z should point to NAIL side"),
        "arch": arch_check(bone_index, segments, nail_direction),
        "ik": ik_entries,
        "constraints": constraints,
        "controllers": find_controllers(prefix, side),
        "identification": finger,
    }


def binding_summary(armature_object):
    """这套骨架被哪些网格绑定（armature 修改器指向它）。用来判断"该改哪一套骨架"。"""
    bound = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" and modifier.object is armature_object:
                bound.append({"mesh": obj.name, "vertices": len(obj.data.vertices),
                              "groups": len(obj.vertex_groups)})
                break
    return bound


def analyze_armature(armature_object, front_override=None):
    bone_index = common.build_bone_index(armature_object)
    result = {
        "armature": armature_object.name,
        "data": armature_object.data.name,
        "bone_count": len(bone_index),
        "bound_meshes": binding_summary(armature_object),
        "uncertain": [],
        "arms": {},
        "fingers": {},
        "legs": {},
    }

    hands = common.find_hand_candidates(bone_index)
    result["hand_candidates"] = hands
    if not hands:
        # 认不出手掌时，把"最像"的候选和它的手指条数报出来，方便人一眼判断是不是模型本身残缺
        best_name = None
        best_count = -1
        for name in bone_index:
            info = common.role_from_name(name)
            if info["role"] != "hand":
                continue
            count = len(common.find_finger_roots(bone_index, name))
            if count > best_count:
                best_count = count
                best_name = name
        if best_name:
            result["uncertain"].append(
                "no hand candidate: best named hand is %s with only %d finger chain(s)" % (best_name, best_count))
        else:
            result["uncertain"].append("no hand candidate and no bone named like a hand")
        return result

    # 祖先骨也会"子树里有五指"（上臂、前臂都算），所以每一侧只保留最深的那几根
    def is_ancestor(ancestor_name, descendant_name):
        return ancestor_name in [name for name, _depth in ancestors_of(bone_index, descendant_name)]

    deepest = []
    for candidate in hands:
        if any(is_ancestor(candidate, other) for other in hands):
            continue
        deepest.append(candidate)
    if not deepest:
        deepest = hands

    scored = []
    for hand_name in deepest:
        chains = common.find_finger_chains(bone_index, hand_name)
        named = 0
        for item in common.find_finger_roots(bone_index, hand_name):
            if finger_role_of(item[0]):
                named += 1
        # 形变骨优先：Skirk 这类骨架有 hand_ref.r 这种"参照骨"，手指链长得一样，但真正驱动网格的是 hand.r
        deform_score = 1 if bone_index[hand_name]["deform"] else 0
        scored.append((deform_score, named, len(chains), hand_name))
    scored.sort(reverse=True)

    # 前方向既要给"名字没侧别的手掌"按位置补侧别，后面认腿和认手臂也要用，所以先算一次；
    # 注意 detect_front_axis 靠脚骨的方向，这里要先收集脚骨。
    foot_names = []
    for name in bone_index:
        info = common.role_from_name(name)
        if info["role"] == "foot" and info["variant"] in ("plain", "shadow") and info["confidence"] == "high":
            foot_names.append(name)
    if front_override is not None:
        front_axis, front_evidence = front_override, "override"
    else:
        front_axis, front_evidence = common.detect_front_axis(bone_index, foot_names)

    hands_by_side = {}
    ignored_hands = []
    for _deform_score, named_count, _chain_count, hand_name in scored:
        _tags, _stem, side = common.parse_bone_name(hand_name)
        if side is None:
            # 名字上没有侧别：先记下，只有当这一侧没有"名字带侧别"的手掌时才按位置补
            ignored_hands.append((hand_name, named_count))
            continue
        hands_by_side.setdefault(side, []).append(hand_name)

    # 名字没侧别的候选：有些是短发/裙摆/腿链被误判成手指（頭、下半身、ORG-LowerBody），
    # 也有些是模型真没给左右后缀的手掌。只补空缺的那一侧，不抢已有的手掌。
    for hand_name, named_count in ignored_hands:
        if named_count < 2 and common.role_from_name(hand_name)["role"] != "hand":
            continue
        if front_axis is None:
            # 没有可信的前方向就没法按位置分左右，宁可留着不认，也不猜
            continue
        side = resolve_side(None, bone_index, hand_name, front_axis)[0]
        if side in hands_by_side:
            continue
        hands_by_side.setdefault(side, []).append(hand_name)

    result["hands_by_side"] = hands_by_side
    result["hand_candidates_deepest"] = deepest
    result["hand_candidates_ignored"] = [name for name, _count in ignored_hands]
    if not hands_by_side:
        result["uncertain"].append(
            "no usable hand: candidates %s are all midline/unpaired (best named hand has %d finger chain(s))"
            % (", ".join(hands) or "none", max([count for _name, count in ignored_hands] or [0])))
        return result

    if front_axis is None:
        result["foot_bones"] = foot_names
        result["uncertain"].append("cannot determine front axis (no usable foot bone)")
        return result
    result["front_axis"] = vector_to_tuple(front_axis)
    result["front_evidence"] = front_evidence
    result["foot_bones"] = foot_names

    legs = identify_legs(bone_index)
    for side in ("L", "R"):
        leg = legs.get(side) or {}
        if leg.get("thigh") or leg.get("shin") or leg.get("foot"):
            leg["side"] = side
            entry = check_leg(armature_object, bone_index, leg, front_axis)
            for issue in leg.get("issues", []):
                result["uncertain"].append("leg.%s: %s" % (side, issue))
            result["legs"][side] = entry
        else:
            result["uncertain"].append("side %s: no leg bones identified" % side)

    for side, hand_list in hands_by_side.items():
        hand_name = hand_list[0]
        if len(hand_list) > 1:
            result.setdefault("hand_choice_notes", []).append(
                "side %s: %s picked out of %s" % (side, hand_name, hand_list))
        arm = identify_arm(bone_index, hand_name, front_axis)
        result["uncertain"].extend("%s: %s" % (side, item) for item in arm["uncertain"])
        arm_entry = check_arm(armature_object, bone_index, arm, front_axis)
        result["arms"][side] = arm_entry

        fingers = identify_fingers(bone_index, hand_name)
        palm_side = common.role_from_name(hand_name)["side"]
        nail_direction = common.palm_plane_normal(
            bone_index, hand_name,
            (fingers.get("index") or {}).get("root"),
            (fingers.get("pinky") or {}).get("root"),
            side=palm_side)
        arm_entry["nail_normal"] = vector_to_tuple(nail_direction) if nail_direction else None
        arm_entry["nail_normal_evidence"] = (
            "palm plane (index root / pinky root / wrist), sign flipped for the right hand; "
            "thumb uses the elbow-wrist-thumb-tip plane facing front")
        entries = {}
        for role, finger in fingers.items():
            segments = [name for name in finger.get("segments") or [] if name]
            entries[role] = {"segments": segments,
                             "last": segments[-1] if segments else None,
                             "root": finger.get("root")}
        nail_directions = common.finger_nail_directions(bone_index, hand_name, entries, front_axis)
        side_fingers = {}
        for role, finger in fingers.items():
            finger["role"] = role
            finger_direction = nail_directions.get(role)
            if finger_direction is None:
                side_fingers[role] = {"segments": finger["segments"], "leaf": {"tip_bone": finger["tip"]},
                                      "identification": finger}
                continue
            finger["nail_direction"] = vector_to_tuple(finger_direction)
            side_fingers[role] = check_finger(armature_object, bone_index, finger,
                                              finger_direction, side)
        result["fingers"][side] = side_fingers
    return result


# ── 报告 ────────────────────────────────────────────────────────────────
def chain_marks(checks):
    """把七项检查压成一行符号（x=已满足 !=不满足 ?=无法判定 -=不适用）。"""
    def mark(condition):
        return "x" if condition else "!"

    hierarchy_ok = checks.get("hierarchy", {}).get("status") == "ok"
    z_items = checks.get("zaxis", {}).get("bones", [])
    z_ok = all(item["status"] in ("ok", "skip") for item in z_items) if z_items else False
    arch_status = checks.get("arch", {}).get("status")
    arch_ok = arch_status in ("ok", "ok_thin", "straight")
    ik_ok = any(item.get("chain_count") == 2 for item in checks.get("ik", []))
    copyrot = checks.get("copyrot_hand") or checks.get("copyrot_foot") or []
    twist = checks.get("twist_copies") or []
    return {
        "hier": mark(hierarchy_ok),
        "zaxis": mark(z_ok),
        "arch": mark(arch_ok),
        "ik": mark(ik_ok),
        "copyrot": mark(bool(copyrot)),
        "twist": mark(bool(twist)),
    }


def format_z_items(z_check, indent="  "):
    lines = []
    for item in z_check["bones"]:
        if item["status"] == "skip":
            lines.append("%sZ 轴 %-18s 跳过（%s）" % (indent, item["bone"], item["reason"]))
        else:
            lines.append("%sZ 轴 %-18s 与规则方向夹角 %6.2f°  %s" % (
                indent, item["bone"], item["angle_deg"], "OK" if item["status"] == "ok" else "不满足"))
    return lines


def format_report(result):
    lines = []
    lines.append("骨架：%s（数据块 %s，%d 根骨）" % (result["armature"], result["data"], result["bone_count"]))
    bound = result.get("bound_meshes") or []
    lines.append("绑定的网格：%s" % (
        ", ".join("%s(%d 顶点)" % (item["mesh"], item["vertices"]) for item in bound) or "无（这套骨架没驱动网格）"))
    lines.append("前方向：%s（依据：%s）" % (result.get("front_axis"), result.get("front_evidence")))
    lines.append("手掌候选：%s" % (", ".join(result.get("hand_candidates") or []) or "无"))
    if result["uncertain"]:
        lines.append("不确定：")
        for item in result["uncertain"]:
            lines.append("  - %s" % item)

    for side in ("L", "R"):
        arm = result["arms"].get(side)
        if not arm:
            continue
        chain = arm["chain"]
        mechanism = arm.get("mechanism") or {}
        mechanism_text = ""
        if mechanism.get("upper") or mechanism.get("forearm"):
            mechanism_text = "  [主骨：%s / %s]" % (mechanism.get("upper"), mechanism.get("forearm"))
        lines.append("")
        lines.append("== 手臂 %s == 上臂=%s 前臂=%s 手掌=%s%s" % (
            side, chain["upper"], chain["forearm"], chain["hand"], mechanism_text))
        lines.append("  层级：%s；上臂↔前臂之间=%s；前臂↔手掌之间=%s" % (
            arm["hierarchy"]["status"],
            ", ".join(arm["hierarchy"]["between_upper_forearm"]) or "无",
            ", ".join(arm["hierarchy"]["between_forearm_hand"]) or "无"))
        lines.extend(format_z_items(arm["zaxis"]))
        arch = arm["arch"]
        if arch.get("status") == "n/a":
            lines.append("  拱形：不适用（%s）" % arch.get("reason"))
        else:
            lines.append("  拱形：%s  偏移 %+.2f%%（目标 3%%）  与规则凸侧夹角 %s°" % (
                arch["status"], arch["max_offset_ratio_percent"], arch.get("angle_to_bend_direction_deg")))
        lines.append("  IK：%s" % (
            "; ".join("%s chain=%d pole=%s angle=%.1f° stretch=%s" % (
                item["owner"], item["chain_count"], item["pole_target"], item["pole_angle_deg"], item["use_stretch"])
                for item in arm["ik"]) or "无"))
        lines.append("  手掌世界复制旋转：%s" % (
            "; ".join("%s -> %s" % (item["name"], item["target"]) for item in arm["copyrot_hand"]) or "无"))
        lines.append("  扭转复制：%s" % (
            "; ".join("%s=%.2f(use %s)" % (item["bone"], item["influence"], item["use_xyz"])
                      for item in arm["twist_copies"]) or "无"))
        lines.append("  控制器：%s" % (", ".join(arm["controllers"]["hand"]) or "无 H_ 控制器"))

        for role in FINGER_ORDER:
            finger = result["fingers"].get(side, {}).get(role)
            if not finger:
                lines.append("  手指 %-7s 未认出" % role)
                continue
            segments = finger["segments"]
            leaf = finger.get("leaf", {})
            z_items = finger.get("zaxis", {}).get("bones", [])
            z_ok = all(item["status"] in ("ok", "skip") for item in z_items) if z_items else None
            z_text = ",".join("%.0f°" % item["angle_deg"] for item in z_items if item["status"] != "skip")
            note = finger.get("identification", {}).get("note")
            lines.append("  手指 %-7s %s  指尖=%s(%s)  Z偏移: %s  %s%s" % (
                role, "→".join(segments), leaf.get("tip_bone"),
                ("%.1f%%" % leaf["ratio_to_last_segment_percent"]) if leaf.get("ratio_to_last_segment_percent") else "无",
                z_text or "-", "OK" if z_ok else ("不满足" if z_ok is False else "?"),
                ("  [" + note + "]") if note else ""))

        leg = result["legs"].get(side)
        if leg:
            chain = leg["chain"]
            lines.append("  腿 %s：大腿=%s 小腿=%s 脚掌=%s（变体 %s）" % (
                side, chain["thigh"], chain["shin"], chain["foot"],
                "/".join(str(leg["variants"][role]) for role in ("thigh", "shin", "foot"))))
            lines.extend(format_z_items(leg["zaxis"], "    "))
            arch = leg["arch"]
            if arch.get("status") != "n/a":
                lines.append("    拱形：%s 偏移 %+.2f%% 与规则凸侧夹角 %s°" % (
                    arch["status"], arch["max_offset_ratio_percent"], arch.get("angle_to_bend_direction_deg")))
            lines.append("    IK：%s" % (
                "; ".join("%s chain=%d pole=%s angle=%.1f°" % (
                    item["owner"], item["chain_count"], item["pole_target"], item["pole_angle_deg"])
                    for item in leg["ik"]) or "无"))
            lines.append("    控制器：%s" % (", ".join(leg["controllers"]["foot"]) or "无 F_ 控制器"))
            if leg.get("rule_conflict"):
                lines.append("    **规则冲突**：%s" % leg["rule_conflict"])
    return "\n".join(lines)


def summarize(result):
    """一行结论（跑全量普查时用）。"""
    def name_of(chain, key):
        return chain.get(key) or "-"

    parts = []
    for side in ("L", "R"):
        arm = result["arms"].get(side)
        if not arm:
            parts.append("arm.%s=?" % side)
            continue
        chain = arm["chain"]
        parts.append("arm.%s=%s/%s/%s" % (side, name_of(chain, "upper"), name_of(chain, "forearm"), name_of(chain, "hand")))
    for side in ("L", "R"):
        leg = result["legs"].get(side)
        if not leg:
            parts.append("leg.%s=?" % side)
            continue
        chain = leg["chain"]
        parts.append("leg.%s=%s/%s/%s" % (side, name_of(chain, "thigh"), name_of(chain, "shin"), name_of(chain, "foot")))

    finger_counts = "%d/%d" % (len(result["fingers"].get("L", {})), len(result["fingers"].get("R", {})))
    marks = ""
    arm = result["arms"].get("L")
    if arm:
        chain_marks_result = chain_marks(arm)
        marks = " ".join("%s=%s" % (key, value) for key, value in chain_marks_result.items())
    leg = result["legs"].get("L")
    leg_z = ""
    if leg:
        angles = [item.get("angle_deg") for item in leg["zaxis"]["bones"] if item["status"] != "skip"]
        leg_z = " legZ=%s" % (round(max(angles), 0) if angles else "-")
    return "%s | fingers=%s | %s%s | ?=%d" % ("  ".join(parts), finger_counts, marks, leg_z, len(result["uncertain"]))


def main():
    options = parse_args()
    if not options["file"]:
        print("usage: rig_analyze.py -- <file.blend> [--armature NAME] [--json out.json] [--summary]")
        return
    ok, open_warning = common.open_mainfile_tolerant(options["file"])
    if open_warning:
        print("注意：这个文件载入时报了错（多为状态键指针损坏，坏键已被 Blender 删除）：%s" % open_warning)
    if not ok:
        print("ANALYZE 打不开文件：%s" % options["file"])
        return

    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if options["armature"]:
        armatures = [obj for obj in armatures if obj.name == options["armature"]]
    if not armatures:
        print("ANALYZE 没找到骨架：%s" % options["file"])
        return
    if len(armatures) > 1 and not options["armature"] and not options["summary"]:
        print("注意：这个文件里有 %d 套骨架（%s），逐套分析；改造前要先定哪一套（--armature）。" % (
            len(armatures), ", ".join(obj.name for obj in armatures)))

    payload = {"file": options["file"], "blender": bpy.app.version_string, "armatures": []}
    for armature_object in armatures:
        result = analyze_armature(armature_object, options["front"])
        payload["armatures"].append(result)
        if options["summary"]:
            print("SUMMARY %-40s %-26s %s" % (
                os.path.basename(options["file"])[:40], armature_object.name[:26], summarize(result)))
        else:
            print("")
            print(format_report(result))

    if options["json"]:
        with open(options["json"], "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        print("\njson written: %s" % options["json"])


if __name__ == "__main__":
    main()
