# -*- coding: utf-8 -*-
"""MusicDoll 骨架改造 —— 执行器（按改造单改骨架，写 .blend）。

改造单是 JSON（`rig_apply.py --dump-order` 可以把分析结果导成一份草稿再改），核心字段：

    {
      "armature": "沙中净水1_arm",
      "front": [0.0, -1.0, 0.0],
      "chains": [
        {
          "part": "arm.L",                      # 进度表里的行名
          "kind": "arm",                        # arm / leg / finger
          "upper": "腕.L", "forearm": "ひじ.L", "hand": "手首.L",
          "between_upper_forearm": ["腕捩.L"],  # 三段之间夹着的骨（要挂到主骨下）
          "between_forearm_hand": ["手捩.L"],
          "create_mch": true,                   # 是否造 MCH 主骨（§3.4）
          "arch_percent": 3.0,                  # 拱高（按弦长百分比）
          "convex": "back",                     # 拱形凸向：back / front
          "pole_angle_deg": 0.0,
          "controllers": {"hand": null, "pole": null, "create_test": false},
          "twist_copy": {"min": 0.2, "max": 1.0},
          "mmd_twist_action": "mute"            # mute / remove / keep
        }
      ]
    }

执行顺序（每一步都受 --dry-run 影响，dry-run 只算不写）：

    造主骨 → 改父子 → 造拱形 → 对齐辅助骨尾端 → 改 roll → 加约束 → 整理集合 → 写回进度

顺序和方案 §5.2 略有不同，原因是几何依赖：拱形会移动肘关节，尾端必须**在拱形之后**对齐；
roll 也必须在拱形之后（拱形改了骨方向，roll 跟着转）。这两条已写进 SKILL 的规则章。

用法：

    blender -b --factory-startup -P rig_apply.py -- <file.blend> \
        --auto-order --only arm.L [--dry-run] [--out out.blend] [--front x,y,z] \
        [--pole-angle 0] [--arch-percent 3] [--no-arch] [--test-controllers] \
        [--dump-order order.json] [--order order.json] [--save] [--status "IN PROGRESS"]
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
import rig_arrows  # noqa: E402

POLE_ANGLE_DEFAULT = {"arm": 90.0, "leg": -90.0, "finger": 90.0}
COLLECTION_NAME = "MCHBones"
FINGER_ORDER = ("thumb", "index", "middle", "ring", "pinky")
LEAF_RATIO = 0.10

# 约束命名（作者 2026-11-17 定）：`MD_<类型>_<链名>`，MD = MusicDoll。
# 接手的人/agent 看到 MD_ 开头就知道是这套改造加的；链名与进度表的行名一致（arm.L / leg.L / index.L）。
CONSTRAINT_PREFIX = "MD_"
CONSTRAINT_IK = "IK"
CONSTRAINT_ROT = "Rot"
CONSTRAINT_TWIST = "Twist"


def constraint_name(kind, part):
    return "%s%s_%s" % (CONSTRAINT_PREFIX, kind, part)


# ── 参数 ────────────────────────────────────────────────────────────────
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {
        "file": None, "armature": None, "order": None, "out": None, "save": False,
        "auto_order": False, "only": [], "dry_run": False, "front": None,
        "pole_angle": None, "arch_percent": None, "no_arch": False,
        "test_controllers": False, "place_poles": False, "dump_order": None, "status": "IN PROGRESS",
        "skip_constraints": False, "twist_action": None,
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--armature":
            index += 1
            options["armature"] = argv[index]
        elif token == "--order":
            index += 1
            options["order"] = argv[index]
        elif token == "--out":
            index += 1
            options["out"] = argv[index]
        elif token == "--front":
            index += 1
            parts = [float(part) for part in argv[index].split(",")]
            options["front"] = Vector(parts).normalized()
        elif token == "--only":
            index += 1
            options["only"].extend(argv[index].split(","))
        elif token == "--pole-angle":
            index += 1
            options["pole_angle"] = float(argv[index])
        elif token == "--arch-percent":
            index += 1
            options["arch_percent"] = float(argv[index])
        elif token == "--dump-order":
            index += 1
            options["dump_order"] = argv[index]
        elif token == "--status":
            index += 1
            options["status"] = argv[index]
        elif token == "--twist-action":
            index += 1
            options["twist_action"] = argv[index]
        elif token == "--auto-order":
            options["auto_order"] = True
        elif token == "--dry-run":
            options["dry_run"] = True
        elif token == "--save":
            options["save"] = True
        elif token == "--no-arch":
            options["no_arch"] = True
        elif token == "--test-controllers":
            options["test_controllers"] = True
        elif token == "--place-poles":
            options["place_poles"] = True
        elif token == "--skip-constraints":
            options["skip_constraints"] = True
        else:
            options["file"] = token
        index += 1
    return options


# ── 小工具 ──────────────────────────────────────────────────────────────
def same_point(first, second, tolerance=1e-4):
    return (first - second).length <= tolerance


def edit_bone_z_axis(edit_bone):
    return (edit_bone.matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()


def edit_bone_direction(edit_bone):
    direction = edit_bone.tail - edit_bone.head
    if direction.length < 1e-9:
        return Vector((0.0, 0.0, 0.0))
    return direction.normalized()


def convex_vector(chain, front_axis):
    """拱形凸向的单位向量：手臂朝后、腿朝前（膝盖）。"""
    convex = chain.get("convex", "back")
    if convex == "back":
        return -front_axis
    return front_axis


def z_axis_vector(chain, front_axis):
    """Z 轴目标方向：手臂、腿都朝正后方（腿的拱形朝前与它是相反的两件事）。"""
    target = chain.get("z_target", "back")
    if target == "front":
        return front_axis
    return -front_axis


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


def pose_is_rest(armature_object, tolerance=1e-4):
    """检查当前姿势是不是 rest（改造只对 rest 姿势成立：骨矩阵一改，已有姿势会被一起带歪）。"""
    offenders = []
    for pose_bone in armature_object.pose.bones:
        basis = pose_bone.matrix_basis
        if (basis.translation.length > tolerance
                or abs(basis.to_quaternion().angle) > tolerance
                or (Vector(basis.to_scale()) - Vector((1.0, 1.0, 1.0))).length > tolerance):
            offenders.append(pose_bone.name)
    return offenders


# ── 改造步骤 ────────────────────────────────────────────────────────────
def create_mch_bones(edit_bones, chain, dry_run, report):
    """造主骨：每段复制一份加 `MCH_` 前缀，形变骨挂到它下面（附录 A 的机制）。"""
    created = []
    for segment_key in ("upper", "forearm"):
        segment_name = chain.get(segment_key)
        if not segment_name or segment_name not in edit_bones:
            continue
        segment_bone = edit_bones[segment_name]
        mch_name = "MCH_" + segment_name
        if mch_name in edit_bones:
            report("mch", "%s 已存在，沿用" % mch_name)
            created.append(edit_bones[mch_name])
            continue
        report("mch", "造 %s（head=%s tail=%s，非形变）" % (
            mch_name, _fmt(segment_bone.head), _fmt(segment_bone.tail)))
        if dry_run:
            created.append(None)
            continue
        mch_bone = edit_bones.new(mch_name)
        mch_bone.head = segment_bone.head.copy()
        mch_bone.tail = segment_bone.tail.copy()
        mch_bone.roll = segment_bone.roll
        mch_bone.parent = segment_bone.parent
        mch_bone.use_deform = False
        mch_bone.use_connect = False
        segment_bone.parent = mch_bone
        segment_bone.use_connect = False
        created.append(mch_bone)
    return created


def reparent_under_mch(edit_bones, chain, dry_run, report):
    """改父子：三段直接父子、夹在中间的骨挂到对应主骨下。"""
    upper_name = chain.get("upper")
    forearm_name = chain.get("forearm")
    hand_name = chain.get("hand")
    upper_mch = edit_bones.get("MCH_" + upper_name) if upper_name else None
    forearm_mch = edit_bones.get("MCH_" + forearm_name) if forearm_name else None

    for name in chain.get("between_upper_forearm", []):
        if name not in edit_bones:
            report("hier", "跳过 %s（骨不存在）" % name)
            continue
        report("hier", "%s 的父级改成 %s" % (name, upper_mch.name if upper_mch else upper_name))
        if not dry_run and upper_mch:
            edit_bones[name].parent = upper_mch

    for name in chain.get("between_forearm_hand", []):
        if name not in edit_bones:
            report("hier", "跳过 %s（骨不存在）" % name)
            continue
        report("hier", "%s 的父级改成 %s" % (name, forearm_mch.name if forearm_mch else forearm_name))
        if not dry_run and forearm_mch:
            edit_bones[name].parent = forearm_mch

    if hand_name and hand_name in edit_bones and forearm_mch:
        hand_bone = edit_bones[hand_name]
        connected = same_point(hand_bone.head, forearm_mch.tail)
        report("hier", "%s 的父级改成 %s（connect=%s）" % (
            hand_name, forearm_mch.name, "1" if connected else "0"))
        if not dry_run:
            hand_bone.parent = forearm_mch
            hand_bone.use_connect = connected

    if upper_mch and forearm_mch and not dry_run:
        if same_point(forearm_mch.head, upper_mch.tail):
            forearm_mch.parent = upper_mch
            forearm_mch.use_connect = True
            report("hier", "%s 与 %s 按肢体顺序 connect" % (forearm_mch.name, upper_mch.name))


def find_twist_bones(edit_bones, chain):
    """找这条链上的扭转骨，并判断它属于哪一段（用"头在哪一段的轴线上"来分）。

    返回 (上臂段的扭转骨, 前臂段的扭转骨)，都按到肩的距离排序。
    """
    upper_name = chain.get("upper")
    forearm_name = chain.get("forearm")
    hand_name = chain.get("hand")
    if not (upper_name and forearm_name and hand_name):
        return [], []
    segments = {
        "upper": (edit_bones[upper_name].head.copy(), edit_bones[forearm_name].head.copy()),
        "forearm": (edit_bones[forearm_name].head.copy(), edit_bones[hand_name].head.copy()),
    }
    chain_names = {upper_name, forearm_name, hand_name}
    chain_names.update(chain.get("between_upper_forearm", []))
    chain_names.update(chain.get("between_forearm_hand", []))

    assigned = {"upper": [], "forearm": []}
    for edit_bone in edit_bones:
        if edit_bone.name in chain_names:
            continue
        info = common.role_from_name(edit_bone.name)
        if info["variant"] != "twist":
            continue
        best_segment = None
        best_distance = 1e9
        for segment_key, (start, end) in segments.items():
            axis = end - start
            axis_length = axis.length
            if axis_length < 1e-9:
                continue
            axis_unit = axis / axis_length
            offset = edit_bone.head - start
            along = offset.dot(axis_unit)
            perpendicular = (offset - axis_unit * along).length
            if -0.1 * axis_length <= along <= 1.1 * axis_length and perpendicular < 0.25 * axis_length:
                if perpendicular < best_distance:
                    best_distance = perpendicular
                    best_segment = segment_key
        if best_segment:
            distance = (edit_bone.head - segments["upper"][0]).length
            assigned[best_segment].append((distance, edit_bone.name))
    for segment_key in assigned:
        assigned[segment_key] = [name for _distance, name in sorted(assigned[segment_key])]
    return assigned["upper"], assigned["forearm"]


def align_aux_tails(edit_bones, chain, dry_run, report):
    """对齐辅助 / 扭转骨的尾端：上臂段的对到肘，前臂段的对到腕。

    目的（方案 §3.6）：扭转骨的 Y 轴必须沿肢体方向，局部的 Y 复制旋转才是"沿手臂扭"。
    """
    upper_name = chain.get("upper")
    forearm_name = chain.get("forearm")
    hand_name = chain.get("hand")
    if not (upper_name and forearm_name and hand_name):
        return
    elbow = edit_bones[forearm_name].head.copy()
    wrist = edit_bones[hand_name].head.copy()

    upper_twists, forearm_twists = find_twist_bones(edit_bones, chain)
    targets = []
    for name in chain.get("between_upper_forearm", []) + upper_twists:
        targets.append((name, elbow, "肘"))
    for name in chain.get("between_forearm_hand", []) + forearm_twists:
        targets.append((name, wrist, "腕"))

    for name, target, label in targets:
        if name not in edit_bones:
            continue
        edit_bone = edit_bones[name]
        if same_point(edit_bone.tail, target, 1e-5):
            report("tail", "%s 的尾端已经对齐%s" % (name, label))
            continue
        report("tail", "%s 的尾端 %s → %s（对齐%s）" % (
            name, _fmt(edit_bone.tail), _fmt(target), label))
        if not dry_run:
            edit_bone.tail = target.copy()


def chain_connect_names(edit_bones, chain):
    """这条链上真正要对接的那串骨（有 MCH 主骨时是主骨链 + 手掌）。

    形变骨与它自己的 MCH 主骨是"同一个头复制出来"的两根（head 对 head），不是关节的延续，
    所以不能把形变骨连到主骨上 —— 那会把它的头拽到主骨的尾上去。
    """
    upper_name = chain.get("upper")
    forearm_name = chain.get("forearm")
    hand_name = chain.get("hand")
    upper_mch = edit_bones.get("MCH_" + upper_name) if upper_name else None
    forearm_mch = edit_bones.get("MCH_" + forearm_name) if forearm_name else None
    if upper_mch is not None and forearm_mch is not None:
        return [name for name in (upper_mch.name, forearm_mch.name, hand_name) if name]
    return [name for name in (upper_name, forearm_name, hand_name) if name]


def append_toe_joint(edit_bones, connect_names, chain, dry_run, report):
    """腿：把脚掌后面那一节脚趾骨也接进链里。

    Unreal 做 animation retarget 时，`足D→ひざD→足首D→足先EX` 是一条 LeftLeg 链，链上任何一节
    不连续，重定向出来的腿就是错的。而在 Blender 里，脚掌与脚趾之间看不出这层关系，最容易漏。

    MMD 的腿常同时有 `つま先`（脚掌中段长出去的分支）与 `足先EX`（沿腿延伸的那一节）。
    只把"沿腿延伸"的那一根接进来：`足先EX` / `toe` 型的一律算链的下一节，**它的头不在脚掌尾端时
    把脚掌的尾端挪过去**（作者 2026-11-24 定：该迁就的是脚掌的尾端，不是脚趾的头）；
    `つま先` 型是分支，既不连、也不掰脚掌的尾。
    """
    if chain.get("kind") != "leg" or not connect_names:
        return connect_names
    foot_name = connect_names[-1]
    foot_bone = edit_bones.get(foot_name)
    if foot_bone is None:
        return connect_names

    candidates = []
    for edit_bone in edit_bones:
        if edit_bone.parent != foot_bone:
            continue
        if common.role_from_name(edit_bone.name)["variant"] in ("shadow", "mechanism"):
            continue
        if not common.looks_like_toe(edit_bone.name):
            continue
        candidates.append((edit_bone.name, (foot_bone.tail - edit_bone.head).length))
    if not candidates:
        return connect_names

    chain_candidates = [item for item in candidates if common.is_chain_toe(item[0])]
    pool = chain_candidates or candidates
    pool.sort(key=lambda item: item[1])
    toe_name, toe_gap = pool[0]

    if chain_candidates:
        if toe_gap > common.CHAIN_JOINT_TOLERANCE:
            report("connect", "脚掌 %s 的尾端 %s → 脚趾 %s 的头 %s（原来差 %.5f；重定向的 LeftLeg 链要连续）" % (
                foot_name, _fmt(foot_bone.tail), toe_name, _fmt(edit_bones[toe_name].head), toe_gap))
            if not dry_run:
                foot_bone.tail = edit_bones[toe_name].head.copy()
        else:
            report("connect", "脚掌 %s → 脚趾 %s 直接接进链里（重定向的 LeftLeg 链要连续）" % (
                foot_name, toe_name))
        return connect_names + [toe_name]

    if toe_gap > common.CHAIN_JOINT_TOLERANCE:
        report("connect", "脚掌 %s 上只有分支脚趾骨 %s（头离脚掌尾 %.5f）—— 不连、也不掰尾端" % (
            foot_name, toe_name, toe_gap))
        return connect_names
    report("connect", "脚掌 %s → 脚趾 %s 接进链里（重定向的 LeftLeg 链要连续）" % (foot_name, toe_name))
    return connect_names + [toe_name]


def enforce_chain_connect(edit_bones, chain_names, dry_run, report, fix_tails=True,
                          planned_reparent=False):
    """链条对接：后一根的 head 落在前一根的 tail 上，并且 `use_connect = True`。

    不重合时改**前一根的 tail**（后一根的 head 才是关节位置，动它等于把整段肢体挪走）。
    这一步必须排在拱形之后：拱形会把中间关节顶出去（本例 9 mm），先连后拱形的话关节又错开。

    `planned_reparent`：dry-run 里主骨还没造出来，链上的父级还是"改之前"的样子。
    这时不该报"不是子级、不连"（真实执行会连上），只说这一轮的对接规划留给真实执行。
    """
    counts = {"already": 0, "new": 0, "moved_tail": 0, "skipped": 0}
    for parent_name, child_name in common.chain_joints(chain_names):
        parent_bone = edit_bones.get(parent_name)
        child_bone = edit_bones.get(child_name)
        if parent_bone is None or child_bone is None:
            report("connect", "跳过 %s → %s（这一轮没有这根骨，多半是还没建出来）" % (
                parent_name, child_name))
            counts["skipped"] += 1
            continue
        if child_bone.parent != parent_bone:
            if planned_reparent:
                report("connect", "%s → %s 的父级这一轮会改（dry-run 造不出主骨），对接交给真实执行" % (
                    parent_name, child_name))
                counts["skipped"] += 1
                continue
            report("connect", "%s 不是 %s 的子级（父级是 %s），不连" % (
                child_name, parent_name, child_bone.parent.name if child_bone.parent else "-"))
            counts["skipped"] += 1
            continue
        gap = (parent_bone.tail - child_bone.head).length
        if gap > common.CHAIN_JOINT_TOLERANCE:
            if not fix_tails:
                report("connect", "%s 的尾端离 %s 的头 %.5f，没动（--keep-tails）" % (
                    parent_name, child_name, gap))
                counts["skipped"] += 1
                continue
            report("connect", "%s 的尾端 %s → %s（对齐 %s 的头，原来差 %.5f）" % (
                parent_name, _fmt(parent_bone.tail), _fmt(child_bone.head), child_name, gap))
            if not dry_run:
                parent_bone.tail = child_bone.head.copy()
            counts["moved_tail"] += 1
        if child_bone.use_connect:
            counts["already"] += 1
            continue
        report("connect", "%s 连到 %s（connect=1）" % (child_name, parent_name))
        if not dry_run:
            child_bone.use_connect = True
        counts["new"] += 1
    if counts["new"] or counts["moved_tail"]:
        report("connect", "这条链接好了 %d 处（原本已连 %d 处，跳过 %d 处）" % (
            counts["new"], counts["already"], counts["skipped"]))
    elif counts["skipped"]:
        report("connect", "没有改动（%d 处跳过）" % counts["skipped"])
    else:
        report("connect", "这条链的 %d 处关节本来就对得上且已连" % counts["already"])
    return counts


def shape_arch(edit_bones, chain, front_axis, percent, dry_run, report):
    """拱形：把中间关节沿凸侧顶出去（按弦长的百分比），两端不动。"""
    upper_name = chain.get("upper")
    forearm_name = chain.get("forearm")
    hand_name = chain.get("hand")
    if not (upper_name and forearm_name and hand_name):
        return None
    shoulder = edit_bones[upper_name].head.copy()
    wrist = edit_bones[hand_name].head.copy()
    elbow = edit_bones[forearm_name].head.copy()

    chord = wrist - shoulder
    chord_length = chord.length
    if chord_length < 1e-9:
        report("arch", "弦长为 0，跳过")
        return None
    chord_unit = chord / chord_length
    direction = convex_vector(chain, front_axis)
    in_plane = direction - chord_unit * direction.dot(chord_unit)
    if in_plane.length < 0.15:
        report("arch", "凸侧在这个平面上投影退化（%.3f），跳过" % in_plane.length)
        return None
    in_plane.normalize()

    offset = (elbow - shoulder) - chord_unit * (elbow - shoulder).dot(chord_unit)
    current_ratio = offset.length / chord_length * 100.0
    desired = in_plane * (percent / 100.0 * chord_length)
    delta = desired - offset
    new_elbow = elbow + delta

    report("arch", "拱高 %+.2f%% → %.2f%%（目标 %.1f%%），中间关节移动 %.4f" % (
        current_ratio, percent, percent, delta.length))
    if dry_run or delta.length < 1e-6:
        return {"delta": delta, "current_ratio": current_ratio}

    elbow_owners = [(edit_bones[upper_name], "tail"), (edit_bones[forearm_name], "head")]
    if ("MCH_" + upper_name) in edit_bones:
        elbow_owners.append((edit_bones["MCH_" + upper_name], "tail"))
    if ("MCH_" + forearm_name) in edit_bones:
        elbow_owners.append((edit_bones["MCH_" + forearm_name], "head"))
    for edit_bone, side in elbow_owners:
        if side == "tail":
            edit_bone.tail = new_elbow.copy()
        else:
            edit_bone.head = new_elbow.copy()
    return {"delta": delta, "current_ratio": current_ratio}


def shape_chain_arch(edit_bones, segment_names, convex_direction, percent, dry_run, report, label):
    """多节链的拱形：每个中间关节沿凸侧顶出去，按抛物线分布（两端 0、中间最大 = percent% 弦长）。

    两节链（上臂+前臂）只有一个中间关节，抛物线在 t=0.5 处正好取满；
    三节手指链有两个中间关节（t≈1/3、2/3），各取 4·t·(1−t)≈0.89 倍，形状才是一条平滑的拱。
    """
    if len(segment_names) < 2:
        return None
    heads = [edit_bones[name].head.copy() for name in segment_names]
    last_tail = edit_bones[segment_names[-1]].tail.copy()
    start = heads[0]
    chord = last_tail - start
    chord_length = chord.length
    if chord_length < 1e-9:
        report("arch", "%s 弦长为 0，跳过" % label)
        return None
    chord_unit = chord / chord_length
    in_plane = convex_direction - chord_unit * convex_direction.dot(chord_unit)
    if in_plane.length < 0.15:
        report("arch", "%s 凸侧在垂直弦的平面上投影退化（%.3f），跳过" % (label, in_plane.length))
        return None
    in_plane.normalize()
    max_offset = percent / 100.0 * chord_length

    moved = 0
    for joint_index in range(1, len(segment_names)):
        joint = heads[joint_index]
        along = (joint - start).dot(chord_unit)
        position = along / chord_length
        profile = 4.0 * position * (1.0 - position)
        current = (joint - start) - chord_unit * along
        desired = in_plane * (max_offset * profile)
        delta = desired - current
        if delta.length < 1e-7:
            continue
        report("arch", "%s 的 %s 沿凸侧移动 %.5f（拱高 %.2f%%，位置 %.2f）" % (
            label, segment_names[joint_index], delta.length, profile * percent, position))
        if not dry_run:
            new_position = joint + delta
            edit_bones[segment_names[joint_index]].head = new_position.copy()
            edit_bones[segment_names[joint_index - 1]].tail = new_position.copy()
        moved += 1
    if not moved:
        report("arch", "%s 已经在目标拱形上" % label)
    return moved


def ensure_leaf_bone(edit_bones, segments, chain, dry_run, report):
    """指尖骨（§3.2，作者 2026-11-17 补充）：已有的把尾巴改成"与前一根同向、长度 10%"；
    没有的补一根同样规格的非形变骨。"""
    last_name = segments[-1]
    last_bone = edit_bones[last_name]
    direction = edit_bone_direction(last_bone)
    target_length = max(last_bone.length * LEAF_RATIO, 1e-5)
    tip_name = chain.get("tip")
    if tip_name and tip_name in edit_bones:
        leaf = edit_bones[tip_name]
        current_angle = common.angle_between(edit_bone_direction(leaf), direction)
        needs_fix = (abs(leaf.length - target_length) > target_length * 0.05
                     or (current_angle is not None and current_angle > 1.0))
        report("leaf", "已有指尖骨 %s：长度 %.5f（末节的 %.1f%% → 10%%），方向差 %s°%s" % (
            tip_name, leaf.length, leaf.length / max(last_bone.length, 1e-9) * 100.0,
            ("%.1f" % current_angle) if current_angle is not None else "n/a",
            "，改" if needs_fix else "，不用动"))
        if needs_fix and not dry_run:
            leaf.tail = leaf.head + direction * target_length
            leaf.roll = last_bone.roll
        return tip_name
    new_name = last_name + "_tip"
    if new_name in edit_bones:
        report("leaf", "已有指尖骨 %s" % new_name)
        return new_name
    report("leaf", "补指尖骨 %s（长度 %.6f = 末节的 10%%，非形变）" % (new_name, target_length))
    if dry_run:
        return new_name
    leaf = edit_bones.new(new_name)
    leaf.head = last_bone.tail.copy()
    leaf.tail = last_bone.tail + direction * target_length
    leaf.roll = last_bone.roll
    leaf.parent = last_bone
    leaf.use_connect = True
    leaf.use_deform = False
    return new_name


def apply_finger(armature_object, chain, front_axis, options, report):
    """一根手指：指尖骨 → 拱形 → 对齐 Z（指甲法线）→ IK 链长 3 + 极向量。"""
    part = chain.get("part", "finger")
    segments = [name for name in (chain.get("segments") or []) if name]
    bone_index = common.build_bone_index(armature_object)
    if len(segments) < 3:
        report("chain", "%s 认出的节数不足 3（%s），跳过" % (part, segments))
        return progress.make_row(part, hier="!", notes="segments=%d" % len(segments))
    for name in segments:
        if name not in bone_index:
            report("chain", "%s 的 %s 不存在，跳过" % (part, name))
            return progress.make_row(part, hier="!", notes="%s missing" % name)

    direction = chain.get("nail_direction")
    arrow = rig_arrows.arrow_direction(armature_object, chain.get("role"), chain.get("side"))
    if arrow is not None:
        direction = arrow
        report("nail", "%s 用箭头 %s 的方向 (%.3f, %.3f, %.3f)" % (
            part, rig_arrows.arrow_name(chain.get("role"), chain.get("side")),
            arrow.x, arrow.y, arrow.z))
    else:
        # 改造单里的指甲方向是"改骨架之前"算的；手臂那条链的拱形会把肘挪几毫米，
        # 拇指的弯曲平面（肘-腕-拇指末端）跟着变，照旧值对不齐（实测差 2.9°）。
        # 所以这里按当前几何重算一次，值偏了就换掉并报出来；有人转过箭头时仍以箭头为准。
        live_direction = live_nail_direction(armature_object, chain, front_axis)
        if live_direction is not None:
            if direction is None:
                direction = live_direction
                report("nail", "%s 指甲方向按当前几何算出" % part)
            else:
                drift = common.angle_between(Vector(direction), live_direction)
                if drift is not None and drift > 0.5:
                    report("nail", "%s 指甲方向按当前几何重算（改造单里的值偏了 %.1f°）" % (part, drift))
                    direction = live_direction
    if direction is None:
        report("nail", "%s 没有指甲方向，跳过" % part)
        return progress.make_row(part, zaxis="?", notes="no nail direction")
    direction = Vector(direction).normalized()

    edit_bones = enter_edit(armature_object)
    arch_percent = chain.get("arch_percent", 3.0)
    if options["no_arch"]:
        report("arch", "%s 按 --no-arch 跳过拱形" % part)
    else:
        shape_chain_arch(edit_bones, segments, direction, arch_percent,
                         options["dry_run"], report, part)
    # 指尖骨放在拱形之后：拱形会改末节方向，先做的话指尖骨的朝向又对不上了
    tip_name = ensure_leaf_bone(edit_bones, segments, chain, options["dry_run"], report)
    finger_chain = list(segments)
    if tip_name and tip_name in edit_bones:
        finger_chain.append(tip_name)
    enforce_chain_connect(edit_bones, finger_chain, options["dry_run"], report)
    align_roll_to(edit_bones, segments, direction, options["dry_run"], report)
    enter_object(armature_object)

    # 手指这一串关节上也不许有原件的约束在抢（MMD 的手指常挂 mmd_ik_limit_override）
    mute_legacy_constraints(armature_object, finger_chain, options["dry_run"], report)

    if options["skip_constraints"]:
        report("ik", "%s 按 --skip-constraints 跳过约束" % part)
        return progress.make_row(part, hier="x", zaxis="x", arch="x", ik="?", leaf="x",
                                 notes="constraints skipped")

    add_finger_constraints(armature_object, chain, direction, segments, options["dry_run"], report)
    notes = "leaf=%s" % (tip_name or "-")
    return progress.make_row(part, hier="x", zaxis="x", arch="x", ik="x", leaf="x", notes=notes)


def add_finger_constraints(armature_object, chain, nail_direction, segments, dry_run, report):
    """手指约束：末节上挂 IK（链长 3），极向量放在指甲侧。"""
    owner = segments[-1]
    role = chain.get("role", "index")
    side = chain.get("side", "L")
    target_object = ensure_finger_controller(armature_object, chain, role, side, "target",
                                             nail_direction, segments, dry_run, report)
    pole_object = ensure_finger_controller(armature_object, chain, role, side, "pole",
                                           nail_direction, segments, dry_run, report)
    if target_object is None or pole_object is None:
        report("ik", "%s 没有控制器，IK 跳过" % chain.get("part"))
        return
    pole_angle = chain.get("pole_angle_deg")
    if pole_angle is None:
        pole_angle = POLE_ANGLE_DEFAULT["finger"]
    report("ik", "%s 加 IK：chain=3 target=%s pole=%s pole_angle=%.1f° stretch=on" % (
        owner, target_object.name, pole_object.name, pole_angle))
    if dry_run:
        return
    pose_bone = armature_object.pose.bones[owner]
    for existing in [con for con in pose_bone.constraints
                     if con.type == "IK" and con.name.startswith(CONSTRAINT_PREFIX)]:
        pose_bone.constraints.remove(existing)
    constraint = pose_bone.constraints.new("IK")
    constraint.name = constraint_name(CONSTRAINT_IK, chain.get("part"))
    constraint.target = target_object
    constraint.chain_count = 3
    constraint.use_tail = True
    constraint.use_stretch = True
    constraint.pole_target = pole_object
    constraint.pole_angle = math.radians(pole_angle)
    constraint.iterations = 500


FINGER_CONTROLLER_PREFIX = {"thumb": "T", "index": "I", "middle": "M", "ring": "R", "pinky": "P"}


def live_nail_direction(armature_object, chain, front_axis):
    """按骨架**当前**几何算这条手指链的指甲方向（四指取手掌平面法线、拇指取弯曲平面朝前）。"""
    hand_name = chain.get("hand")
    role = chain.get("role")
    if not (hand_name and role and front_axis is not None):
        return None
    bone_index = common.build_bone_index(armature_object)
    if hand_name not in bone_index:
        return None
    targets = rig_arrows.finger_targets(bone_index, hand_name)
    if role not in targets:
        return None
    directions = common.finger_nail_directions(bone_index, hand_name, targets, front_axis)
    return directions.get(role)


def ensure_finger_controller(armature_object, chain, role, side, kind, nail_direction, segments,
                             dry_run, report):
    """手指控制器：优先找 `<前缀>_<侧>_*`（目标是控制器本身、极向量是 `*_pole_*`），
    没有就按需造测试用的空物体。"""
    prefix = FINGER_CONTROLLER_PREFIX.get(role, "I")
    if kind == "target":
        existing = _find_controller(prefix, side, pole=False)
        name = "%s_%s_test" % (prefix, side)
    else:
        existing = _find_controller(prefix, side, pole=True)
        name = "%s_%s_pole_test" % (prefix, side)
    if existing is not None:
        report("controller", "%s %s 控制器 = %s" % (role, kind, existing.name))
        return existing
    if not (chain.get("controllers") or {}).get("create_test"):
        return None
    bone = armature_object.data.bones[segments[-1]]
    if kind == "target":
        location = armature_object.matrix_world @ bone.tail_local
    else:
        # 极向量要摆在"链根到指尖这条弦的指甲侧、并且垂直离开弦"，这样 pole_angle 90° 才对每根手指
        # 都算出同一个弯曲平面。摆得贴着末节（离弦太近、方向顺着手轴）时，各指的仰角不一样，
        # 同一个角度会让食指/无名指/小指斜着弯（实测偏 32~43°）。
        root_head = armature_object.data.bones[segments[0]].head_local
        chord = bone.tail_local - root_head
        chord_length = chord.length
        chord_unit = chord.normalized() if chord_length > 1e-9 else Vector((0.0, 0.0, 1.0))
        nail_perp = Vector(nail_direction) - chord_unit * Vector(nail_direction).dot(chord_unit)
        if nail_perp.length < 1e-6:
            nail_perp = Vector((0.0, 0.0, 1.0))
        nail_perp.normalize()
        pole_point = root_head + chord_unit * (chord_length * 0.55) + nail_perp * (chord_length * 0.8)
        location = armature_object.matrix_world @ pole_point
    report("controller", "造测试控制器 %s（%s）" % (name, kind))
    if dry_run:
        return PlannedController(name)
    existing_object = bpy.data.objects.get(name)
    if existing_object is not None:
        return existing_object
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "SPHERE"
    empty.empty_display_size = 0.008
    empty.show_in_front = True
    empty.location = location
    bpy.context.scene.collection.objects.link(empty)
    return empty


def _find_controller(prefix, side, pole):
    import re

    pattern = re.compile(r"^%s_%s(_pole_|_)(?!.*_test$)" % (re.escape(prefix), side))
    for obj in bpy.data.objects:
        if obj.type != "EMPTY":
            continue
        if not pattern.match(obj.name):
            continue
        if pole != ("_pole_" in obj.name):
            continue
        return obj
    return None


def align_roll_to(edit_bones, names, target_vector, dry_run, report):
    """把指定骨的 Z 轴转到目标方向（投影到垂直于骨方向的平面上）。"""
    for name in names:
        if not name or name not in edit_bones:
            continue
        edit_bone = edit_bones[name]
        y_axis = edit_bone_direction(edit_bone)
        in_plane = target_vector - y_axis * target_vector.dot(y_axis)
        if in_plane.length < 0.15:
            report("roll", "%s 的骨方向几乎平行于目标方向（%.3f），跳过" % (name, in_plane.length))
            continue
        in_plane.normalize()
        before = common.angle_between(edit_bone_z_axis(edit_bone), in_plane)
        report("roll", "%s 的 Z 与目标夹角 %.2f° → 对齐" % (name, before if before is not None else -1.0))
        if not dry_run:
            edit_bone.align_roll(in_plane)


def move_to_collection(armature_object, names, collection_name, report):
    """把机制骨放进单独的骨骼集合（照 Jeht 的 MCHBones 做法）。"""
    data = armature_object.data
    collection = data.collections.get(collection_name)
    if collection is None:
        collection = data.collections.new(collection_name)
        report("collection", "新建骨骼集合 %s" % collection_name)
    for name in names:
        bone = data.bones.get(name)
        if bone is None:
            continue
        for existing in list(bone.collections):
            if existing.name != collection_name:
                existing.unassign(bone)
        collection.assign(bone)
        report("collection", "%s 归入 %s" % (name, collection_name))


# ── 约束 ────────────────────────────────────────────────────────────────
class PlannedController:
    """dry-run 时代表"将会被造出来的控制器"，只为让日志能打印名字。"""

    def __init__(self, name):
        self.name = name


def ensure_controller(armature_object, chain, kind, dry_run, report):
    """找控制器；没有就按需造一个测试用的空物体（只在实验副本里用）。

    控制器命名是 `前缀_侧_角色`：手臂 `H_` / 极向量 `HP_`，腿 `F_` / `FP_`，手指 `T/I/M/R/P_`。
    """
    controller_name = (chain.get("controllers") or {}).get(kind)
    if controller_name:
        existing = bpy.data.objects.get(controller_name)
        if existing is not None:
            report("controller", "%s 控制器 = %s" % (kind, controller_name))
            return existing
        report("controller", "%s 控制器 %s 不存在" % (kind, controller_name))
        return None
    if not (chain.get("controllers") or {}).get("create_test"):
        return None

    forearm_name = chain.get("forearm")
    hand_name = chain.get("hand")
    side = chain.get("side", "L")
    prefixes = chain.get("controller_prefix") or {"hand": "H", "pole": "HP"}
    if kind == "hand":
        bone_head = armature_object.data.bones[hand_name].head_local
        location = armature_object.matrix_world @ bone_head
        name = "%s_%s_test" % (prefixes["hand"], side)
    else:
        bone_head = armature_object.data.bones[forearm_name].head_local
        location = armature_object.matrix_world @ bone_head
        name = "%s_%s_test" % (prefixes["pole"], side)
    existing = bpy.data.objects.get(name)
    if existing is not None:
        report("controller", "沿用测试控制器 %s" % name)
        return existing
    report("controller", "造测试控制器 %s（位置 %s）" % (name, _fmt(location)))
    if dry_run:
        return PlannedController(name)
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "ARROWS"
    empty.empty_display_size = 0.05
    empty.show_in_front = True
    bpy.context.scene.collection.objects.link(empty)
    if kind == "hand":
        # 手掌那条世界空间复制旋转会把骨骼转到控制器的朝向：控制器必须拿着手掌的 rest 朝向，
        # 否则一加约束手掌就被拧到单位旋转，rest 姿势下网格就变形了。
        hand_bone = armature_object.data.bones[hand_name]
        empty.matrix_world = armature_object.matrix_world @ hand_bone.matrix_local
    else:
        empty.location = location
    return empty


def add_constraints(armature_object, chain, front_axis, options, dry_run, report):
    """按 §3.6 加约束：IK、手掌世界复制旋转、扭转复制。"""
    upper_name = chain.get("upper")
    forearm_name = chain.get("forearm")
    hand_name = chain.get("hand")
    ik_owner = "MCH_" + forearm_name if ("MCH_" + forearm_name) in armature_object.data.bones else forearm_name
    hand_controller = ensure_controller(armature_object, chain, "hand", dry_run, report)
    pole_controller = ensure_controller(armature_object, chain, "pole", dry_run, report)

    if hand_controller is None or pole_controller is None:
        report("ik", "没有控制器，IK / 复制旋转都跳过（控制器要在演奏者生成之后才有）")
        return

    pole_angle = chain.get("pole_angle_deg")
    if pole_angle is None:
        pole_angle = POLE_ANGLE_DEFAULT.get(chain.get("kind", "arm"), 0.0)
    report("ik", "%s 加 IK：chain=2 target=%s pole=%s pole_angle=%.1f° stretch=on" % (
        ik_owner, hand_controller.name, pole_controller.name, pole_angle))
    if not dry_run:
        pose_bone = armature_object.pose.bones[ik_owner]
        for existing in [con for con in pose_bone.constraints
                         if con.type == "IK" and con.name.startswith(CONSTRAINT_PREFIX)]:
            pose_bone.constraints.remove(existing)
        constraint = pose_bone.constraints.new("IK")
        constraint.name = constraint_name(CONSTRAINT_IK, chain.get("part"))
        constraint.target = hand_controller
        constraint.chain_count = 2
        constraint.use_tail = True
        constraint.use_stretch = True
        constraint.pole_target = pole_controller
        constraint.pole_angle = math.radians(pole_angle)
        constraint.iterations = 500

    report("copyrot", "%s 加世界空间复制旋转 ← %s" % (hand_name, hand_controller.name))
    if not dry_run:
        pose_bone = armature_object.pose.bones[hand_name]
        for existing in [con for con in pose_bone.constraints
                         if con.type == "COPY_ROTATION" and con.name.startswith(CONSTRAINT_PREFIX)]:
            pose_bone.constraints.remove(existing)
        constraint = pose_bone.constraints.new("COPY_ROTATION")
        constraint.name = constraint_name(CONSTRAINT_ROT, chain.get("part"))
        constraint.target = hand_controller
        constraint.owner_space = "WORLD"
        constraint.target_space = "WORLD"
        constraint.use_x = True
        constraint.use_y = True
        constraint.use_z = True
        constraint.influence = 1.0

    # 扭转复制：从肩到腕按位置排序，强度线性递增（末端 = 手掌 = 1.0，不建约束）
    twist_settings = chain.get("twist_copy") or {}
    if not twist_settings.get("enabled", True):
        return
    minimum = float(twist_settings.get("min", 0.2))
    maximum = float(twist_settings.get("max", 1.0))
    sequence = twist_ladder(armature_object, chain)
    count = len(sequence)
    for rank, name in enumerate(sequence):
        influence = round(minimum + (maximum - minimum) * rank / max(count, 1), 3)
        report("twist", "%s 加局部 Y 复制旋转 ← %s，强度 %.3f" % (name, hand_name, influence))
        if dry_run:
            continue
        pose_bone = armature_object.pose.bones[name]
        for existing in [con for con in pose_bone.constraints
                         if con.type == "COPY_ROTATION" and con.subtarget == hand_name
                         and con.name.startswith(CONSTRAINT_PREFIX)]:
            pose_bone.constraints.remove(existing)
        constraint = pose_bone.constraints.new("COPY_ROTATION")
        constraint.name = constraint_name(CONSTRAINT_TWIST, chain.get("part"))
        constraint.target = armature_object
        constraint.subtarget = hand_name
        constraint.owner_space = "LOCAL"
        constraint.target_space = "LOCAL"
        constraint.use_x = False
        constraint.use_y = True
        constraint.use_z = False
        constraint.influence = influence


def twist_ladder(armature_object, chain):
    """扭转链的顺序：上臂骨 + 上臂段扭转骨 + 前臂骨 + 前臂段扭转骨，按到肩的距离排。

    手掌是复制源，不参与（它的强度就是 1.0）。
    """
    bone_index = common.build_bone_index(armature_object)
    upper_name = chain.get("upper")
    forearm_name = chain.get("forearm")
    hand_name = chain.get("hand")
    if not (upper_name and forearm_name and hand_name):
        return []
    shoulder = bone_index[upper_name]["head"]
    wrist = bone_index[hand_name]["head"]
    axis = wrist - shoulder
    axis_length = axis.length
    if axis_length < 1e-9:
        return []
    axis_unit = axis / axis_length

    def find_twist_names():
        segments = {
            "upper": (bone_index[upper_name]["head"], bone_index[forearm_name]["head"]),
            "forearm": (bone_index[forearm_name]["head"], bone_index[hand_name]["head"]),
        }
        chain_names = {upper_name, forearm_name, hand_name}
        chain_names.update(chain.get("between_upper_forearm", []))
        chain_names.update(chain.get("between_forearm_hand", []))
        found = []
        for name, entry in bone_index.items():
            if name in chain_names:
                continue
            if common.role_from_name(name)["variant"] != "twist":
                continue
            for start, end in segments.values():
                segment_axis = end - start
                if segment_axis.length < 1e-9:
                    continue
                segment_unit = segment_axis / segment_axis.length
                offset = entry["head"] - start
                along = offset.dot(segment_unit)
                perpendicular = (offset - segment_unit * along).length
                if (-0.1 * segment_axis.length <= along <= 1.1 * segment_axis.length
                        and perpendicular < 0.25 * segment_axis.length):
                    found.append(name)
                    break
        return found

    candidates = [upper_name, forearm_name]
    candidates.extend(chain.get("between_upper_forearm", []))
    candidates.extend(chain.get("between_forearm_hand", []))
    candidates.extend(find_twist_names())
    unique = []
    for name in candidates:
        if name and name in bone_index and name not in unique and name != hand_name:
            unique.append(name)
    unique.sort(key=lambda name: (bone_index[name]["head"] - shoulder).dot(axis_unit))
    return unique


def handle_mmd_ik(armature_object, chain, action, dry_run, report):
    """禁用模型自带的 IK（MMD 的 `ひざ` IK、目标 `足ＩＫ` 那种）：默认直接 mute，不删。

    只动这条链上的骨；我们自己的约束（`MD_` 开头）不碰。作者 2026-11-17 定：这类 IK 直接禁用，
    腿按 §3.6 重建（极向量 + `pole_angle`）。
    """
    if action in (None, "keep"):
        return
    names = [chain.get(key) for key in ("upper", "forearm", "hand")]
    names += chain.get("between_upper_forearm", []) + chain.get("between_forearm_hand", [])
    for name in [item for item in names if item]:
        pose_bone = armature_object.pose.bones.get(name)
        if pose_bone is None:
            continue
        for constraint in list(pose_bone.constraints):
            if constraint.type != "IK":
                continue
            if (constraint.name or "").startswith(CONSTRAINT_PREFIX):
                continue
            if action == "remove":
                report("mmd-ik", "删除 %s 上的 %s（目标 %s）" % (
                    name, constraint.name, constraint.target.name if constraint.target else None))
                if not dry_run:
                    pose_bone.constraints.remove(constraint)
            else:
                report("mmd-ik", "禁用 %s 上的 %s（目标 %s）" % (
                    name, constraint.name, constraint.target.name if constraint.target else None))
                if not dry_run:
                    constraint.mute = True


def mute_legacy_constraints(armature_object, chain_bone_names, dry_run, report):
    """链上"决定姿势"的骨，原件带的约束一律 mute，只留我们自己的 `MD_`。

    MMD 原件在这些骨上挂着 `IK`、`mmd_additional_rotation`、`mmd_ik_limit_override`、
    `mmd_tools_at_dummy` 等；它们和我们加的 IK / 复制旋转抢同一根骨，谁说了算取决于算的先后，
    调起来像玄学。规矩是：改造过的链上只让自己加的约束生效，其余全部静音（保留可回溯，不删）。

    只管"关节骨"（上臂/前臂/手掌/大腿/小腿/脚掌/手指各节及其影子变体）。像 `ひじ補助`、`肩C`、
    `腰キャンセル`、`目` 这类"跟着别人动"的辅助骨，它们的约束没有替代品，关掉会掉形变，不在范围内。
    """
    muted = []
    expanded = []
    for bone_name in chain_bone_names:
        if bone_name not in expanded:
            expanded.append(bone_name)
        for prefix in ("_shadow_", "_dummy_"):
            twin = prefix + bone_name
            if twin not in expanded and twin in armature_object.pose.bones:
                expanded.append(twin)
    for bone_name in expanded:
        pose_bone = armature_object.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        for constraint in pose_bone.constraints:
            if constraint.name.startswith(CONSTRAINT_PREFIX) or constraint.mute:
                continue
            muted.append("%s.%s" % (bone_name, constraint.name))
            if not dry_run:
                constraint.mute = True
    if muted:
        report("mute", "%d 条原件约束静音（只留 %s*）：%s" % (
            len(muted), CONSTRAINT_PREFIX, ", ".join(muted)))
    else:
        report("mute", "链上没有需要静音的原件约束")
    return muted


def handle_mmd_twist(armature_object, bone_names, action, dry_run, report):
    """处理 MMD 自带的扭转机制（`mmd_additional_rotation`），只动这条链上的扭转骨。

    MMD 的扭转骨靠这条 TRANSFORM 约束从影子骨取旋转，轴的约定是按老骨朝向定的；
    我们把这些骨的尾端对齐到肢体末端、改成"手掌 Y 复制旋转"之后，这条约束会重复施加扭转。
    所以默认 mute（保留可回溯），要彻底删就用 --twist-action remove。
    """
    if action in (None, "keep"):
        return
    for name in bone_names:
        pose_bone = armature_object.pose.bones.get(name)
        if pose_bone is None:
            continue
        for constraint in list(pose_bone.constraints):
            if constraint.type != "TRANSFORM":
                continue
            if "mmd_additional_rotation" not in (constraint.name or ""):
                continue
            if action == "remove":
                report("mmd-twist", "删除 %s 上的 %s" % (name, constraint.name))
                if not dry_run:
                    pose_bone.constraints.remove(constraint)
            else:
                report("mmd-twist", "mute %s 上的 %s" % (name, constraint.name))
                if not dry_run:
                    constraint.mute = True


# ── 改造单 ──────────────────────────────────────────────────────────────
def build_order_from_analysis(armature_object, front_axis, parts):
    """用分析器认链，生成改造单草稿（几何全部由执行器从骨架现算）。"""
    import rig_analyze as analyzer

    result = analyzer.analyze_armature(armature_object, front_axis)
    order = {
        "armature": armature_object.name,
        "front": [round(front_axis[0], 6), round(front_axis[1], 6), round(front_axis[2], 6)],
        "chains": [],
    }
    for side in ("L", "R"):
        part = "arm.%s" % side
        if parts and part not in parts:
            continue
        arm = result["arms"].get(side)
        if not arm:
            continue
        chain = arm["chain"]
        hierarchy = arm["hierarchy"]
        between_upper = hierarchy["between_upper_forearm"]
        between_forearm = hierarchy["between_forearm_hand"]
        order["chains"].append({
            "part": part,
            "kind": "arm",
            "side": side,
            "upper": chain["upper"],
            "forearm": chain["forearm"],
            "hand": chain["hand"],
            "between_upper_forearm": between_upper,
            "between_forearm_hand": between_forearm,
            "create_mch": bool(between_upper or between_forearm),
            "arch_percent": 3.0,
            "convex": "back",
            "pole_angle_deg": POLE_ANGLE_DEFAULT["arm"],
            "controllers": {
                "hand": (arm["controllers"]["hand"] or [None])[0],
                "pole": (arm["controllers"]["pole"] or [None])[0],
                "create_test": False,
            },
            "twist_copy": {"enabled": True, "min": 0.2, "max": 1.0},
            "mmd_twist_action": "mute",
            "mmd_ik_action": "mute",
            "z_target": "back",
        })

    # 腿：字段名沿用 upper/forearm/hand（= 大腿/小腿/脚掌），几何全部由执行器现算。
    # 腿的拱形朝前（膝盖）、Z 朝后 —— 这两件事方向相反，别合并。
    for side in ("L", "R"):
        part = "leg.%s" % side
        if parts and part not in parts:
            continue
        leg = result["legs"].get(side)
        if not leg:
            continue
        chain = leg["chain"]
        if not (chain.get("thigh") and chain.get("shin") and chain.get("foot")):
            continue
        hierarchy = leg["hierarchy"]
        between_thigh = hierarchy.get("between_thigh_shin", [])
        between_shin = hierarchy.get("between_shin_foot", [])
        order["chains"].append({
            "part": part,
            "kind": "leg",
            "side": side,
            "upper": chain["thigh"],
            "forearm": chain["shin"],
            "hand": chain["foot"],
            "between_upper_forearm": between_thigh,
            "between_forearm_hand": between_shin,
            "create_mch": bool(between_thigh or between_shin),
            "arch_percent": 3.0,
            "convex": "front",
            "z_target": "back",
            "pole_angle_deg": POLE_ANGLE_DEFAULT["leg"],
            "controllers": {
                "hand": (leg["controllers"]["foot"] or [None])[0],
                "pole": None,
                "create_test": False,
            },
            "controller_prefix": {"hand": "F", "pole": "FP"},
            "twist_copy": {"enabled": False},
            "mmd_twist_action": "keep",
            "mmd_ik_action": "mute",
        })

    # 手指：每侧五指各一条链，Z 目标 = 作者口径的指甲方向（四指取手掌平面法线、拇指取自己的拱形凸侧）；
    # 如果这个文件里有复核用的箭头，apply 时以箭头为准（箭头优先）。
    bone_index = common.build_bone_index(armature_object)
    for side in ("L", "R"):
        hand_names = (result.get("hands_by_side") or {}).get(side) or []
        if not hand_names:
            continue
        hand_name = hand_names[0]
        targets = rig_arrows.finger_targets(bone_index, hand_name)
        if len(targets) < 4:
            continue
        nail_directions = common.finger_nail_directions(bone_index, hand_name, targets, front_axis)
        for role in FINGER_ORDER:
            part = "%s.%s" % (role, side)
            if parts and part not in parts:
                continue
            entry = targets.get(role)
            if not entry:
                continue
            direction = nail_directions.get(role)
            order["chains"].append({
                "part": part,
                "kind": "finger",
                "role": role,
                "side": side,
                "hand": hand_name,
                "segments": entry["segments"],
                "tip": entry["tip"],
                "arch_percent": 3.0,
                "pole_angle_deg": POLE_ANGLE_DEFAULT["finger"],
                "nail_direction": [round(value, 6) for value in direction] if direction else None,
                "controllers": {"create_test": False},
            })
    return order, result


def apply_chain(armature_object, chain, front_axis, options, report):
    """跑一条链的全部步骤。返回进度表的一行。"""
    if chain.get("kind") == "finger":
        return apply_finger(armature_object, chain, front_axis, options, report)
    part = chain.get("part", "chain")
    bone_index = common.build_bone_index(armature_object)
    for key in ("upper", "forearm", "hand"):
        name = chain.get(key)
        if not name or name not in bone_index:
            report("chain", "%s 的 %s 骨不存在（%s），整条链跳过" % (part, key, name))
            return progress.make_row(part, hier="!", notes="%s missing" % key)

    if chain.get("create_mch"):
        report("chain", "%s：三段之间夹着 %s，按 §3.4 造主骨" % (
            part, ", ".join(chain.get("between_upper_forearm", []) + chain.get("between_forearm_hand", []))))
    else:
        report("chain", "%s：三段直接父子，不造主骨" % part)

    edit_bones = enter_edit(armature_object)
    if chain.get("create_mch"):
        create_mch_bones(edit_bones, chain, options["dry_run"], report)
        reparent_under_mch(edit_bones, chain, options["dry_run"], report)
    elif not options["dry_run"]:
        reparent_under_mch(edit_bones, chain, options["dry_run"], report)

    arch_percent = chain.get("arch_percent", 3.0)
    if options["no_arch"]:
        report("arch", "按 --no-arch 跳过拱形")
    else:
        shape_arch(edit_bones, chain, front_axis, arch_percent, options["dry_run"], report)

    align_aux_tails(edit_bones, chain, options["dry_run"], report)
    chain_names = chain_connect_names(edit_bones, chain)
    chain_names = append_toe_joint(edit_bones, chain_names, chain, options["dry_run"], report)
    enforce_chain_connect(edit_bones, chain_names, options["dry_run"], report,
                          planned_reparent=bool(chain.get("create_mch")) and options["dry_run"])
    upper_twists, forearm_twists = find_twist_bones(edit_bones, chain)
    twist_names = (chain.get("between_upper_forearm", []) + chain.get("between_forearm_hand", [])
                   + upper_twists + forearm_twists)

    roll_names = []
    for name in (chain.get("upper"), chain.get("forearm"), chain.get("hand")):
        if name and name not in roll_names:
            roll_names.append(name)
    for name in ("MCH_" + chain["upper"], "MCH_" + chain["forearm"]):
        if name in edit_bones and name not in roll_names:
            roll_names.append(name)
    align_roll_to(edit_bones, roll_names, z_axis_vector(chain, front_axis), options["dry_run"], report)
    enter_object(armature_object)

    # 链上只留我们自己的约束：原件挂在关节骨上的 IK / 附加旋转 / 角度限制 / 影子拷贝全部静音
    joint_names = [name for name in (chain.get("upper"), chain.get("forearm"), chain.get("hand"))
                   if name]
    joint_names += [name for name in chain_names if name not in joint_names]
    for name in list(joint_names):
        if name.startswith("MCH_"):
            joint_names.append(name[4:])
    mute_legacy_constraints(armature_object, joint_names, options["dry_run"], report)

    if chain.get("create_mch") and not options["dry_run"]:
        move_to_collection(armature_object, ["MCH_" + chain["upper"], "MCH_" + chain["forearm"]],
                           COLLECTION_NAME, report)

    handle_mmd_twist(armature_object, twist_names, chain.get("mmd_twist_action"), options["dry_run"], report)
    handle_mmd_ik(armature_object, chain, chain.get("mmd_ik_action", "mute"), options["dry_run"], report)

    if options["skip_constraints"]:
        report("ik", "按 --skip-constraints 跳过约束")
        return progress.make_row(part, hier="x", zaxis="x", arch="x", ik="?", copyrot="?", twist="?",
                                 notes="constraints skipped")
    add_constraints(armature_object, chain, front_axis, options, options["dry_run"], report)

    notes = []
    if chain.get("create_mch"):
        notes.append("MCH_%s + MCH_%s" % (chain["upper"], chain["forearm"]))
    if not options["dry_run"]:
        notes.append("arch %.1f%%" % chain.get("arch_percent", 3.0))
    return progress.make_row(part, hier="x", zaxis="x", arch="x", ik="x", copyrot="x", twist="x",
                             notes=", ".join(notes))


# ── 主流程 ──────────────────────────────────────────────────────────────
def _fmt(vector):
    return "(%.4f, %.4f, %.4f)" % (vector[0], vector[1], vector[2])


def save_file(filepath, copy=True):
    """存盘。有些老模型引用了不存在的贴图，保存时会报 "Unable to pack file" 的 RuntimeError，
    但文件其实已经写出来了 —— 这种只提示，不当失败。"""
    try:
        bpy.ops.wm.save_as_mainfile(filepath=filepath, copy=copy)
    except RuntimeError as error:
        message = str(error).splitlines()[0] if str(error) else ""
        if os.path.exists(filepath):
            print("存盘时 Blender 报了一条错（文件已写出，多半是缺贴图）：%s" % message)
        else:
            raise


POLE_SWEEP_BEND_DEGREES = 60.0
POLE_SWEEP_STEP_DEGREES = 5


def evaluated_bone_head(armature_object, bone_name):
    """当前姿势下（约束解算之后）某根骨的头在世界空间的位置。"""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = armature_object.evaluated_get(depsgraph)
    return evaluated.matrix_world @ evaluated.pose.bones[bone_name].head


def resweep_pole_angle(armature_object, constraint, root_name, mid_name, end_name,
                       convex_world):
    """极向量挪走之后重标 `pole_angle`，返回 (角度, 中间关节朝极向量的偏离)。

    判据与 `rig_verify` 一致：中间关节相对"根→目标"这根弦的垂直偏移，与极向量相对同一根弦的
    垂直偏移之间的夹角最小者胜。

    **必须先把链摆弯**：链几乎笔直时（腿的 rest 就是这样），任何 `pole_angle` 解出来的关节位置
    都只差几毫米，扫描等于在给噪声排名 —— 实测把一条腿标成 0°、另一条标成 180°。
    所以这里绕弯曲平面法线把弦转 60° 当探针姿势，扫完再把控制器还原。
    """
    bones = armature_object.data.bones
    controller = constraint.target
    if controller is None or constraint.pole_target is None:
        return None, None
    if not all(name in bones for name in (root_name, mid_name, end_name)):
        return None, None

    root_local = bones[root_name].head_local.copy()
    chord = bones[end_name].head_local - root_local
    if chord.length < 1e-6:
        return None, None
    chord_unit = chord.normalized()
    convex_local = armature_object.matrix_world.inverted().to_3x3() @ Vector(convex_world)
    convex_perp = convex_local - chord_unit * convex_local.dot(chord_unit)
    if convex_perp.length < 1e-6:
        return None, None
    convex_perp.normalize()
    bend_axis = chord_unit.cross(convex_perp).normalized()
    bent_unit = Matrix.Rotation(math.radians(POLE_SWEEP_BEND_DEGREES), 4, bend_axis) @ chord_unit
    chain_length = bones[root_name].length + bones[mid_name].length
    probe_world = armature_object.matrix_world @ (root_local + bent_unit * (chain_length * 0.75))

    saved_matrix = controller.matrix_world.copy()
    probe_matrix = saved_matrix.copy()
    probe_matrix.translation = probe_world
    controller.matrix_world = probe_matrix
    bpy.context.view_layer.update()

    root_world = armature_object.matrix_world @ root_local
    chord_world = probe_world - root_world
    chord_world_unit = chord_world.normalized() if chord_world.length > 1e-9 else chord_unit
    pole_point = constraint.pole_target.matrix_world.translation.copy()
    pole_offset = (pole_point - root_world) - chord_world_unit * (pole_point - root_world).dot(chord_world_unit)

    original_angle = constraint.pole_angle
    best_angle, best_error = None, None
    for degrees in range(-180, 181, POLE_SWEEP_STEP_DEGREES):
        constraint.pole_angle = math.radians(degrees)
        bpy.context.view_layer.update()
        joint = evaluated_bone_head(armature_object, mid_name)
        joint_offset = (joint - root_world) - chord_world_unit * (joint - root_world).dot(chord_world_unit)
        if joint_offset.length < 1e-6 or pole_offset.length < 1e-6:
            continue
        error = math.degrees(joint_offset.angle(pole_offset))
        if best_error is None or error < best_error:
            best_angle, best_error = degrees, error

    controller.matrix_world = saved_matrix
    constraint.pole_angle = math.radians(best_angle) if best_angle is not None else original_angle
    bpy.context.view_layer.update()
    return best_angle, best_error


def arrange_controllers(armature_object, chains, front_axis, dry_run, report, place_poles=False):
    """控制器的从属与摆位（作者 2026-11-18 定，三条硬规矩）。

    1. 手指的目标控制器、极向量控制器，一律挂到同侧手腕控制器下面：
       动画师只动手腕，整只手连着手指一起走，手指之间的相对关系一根都不变。
    2. 肘的极向量控制器（`HP_*`）往人身后挪一段距离 —— 那是它真正工作的位置。
    3. 膝的极向量控制器（`FP_*`）往人身前挪一段距离。

    挪极向量只沿弯曲平面走（肘朝后、膝朝前都在矢状面里），弯曲平面不变，
    所以 `pole_angle` 不用重标定。
    """
    bones = armature_object.data.bones
    pose_bones = armature_object.pose.bones
    front = Vector(front_axis).normalized()

    # 每条链的"手腕控制器"与"肘/膝极向量控制器"先把对象找出来
    hand_by_side = {}
    pole_by_part = {}
    for chain in chains:
        controllers = chain.get("controllers") or {}
        side = chain.get("side")
        kind = chain.get("kind")
        hand_object = None
        if controllers.get("hand"):
            hand_object = bpy.data.objects.get(controllers["hand"])
        if hand_object is None and side:
            hand_object = bpy.data.objects.get("%s_%s_test" % (
                (chain.get("controller_prefix") or {}).get("hand", "H"), side))
        if hand_object is not None and side:
            hand_by_side[side] = hand_object

        pole_object = None
        if controllers.get("pole"):
            pole_object = bpy.data.objects.get(controllers["pole"])
        if pole_object is None and side:
            pole_object = bpy.data.objects.get("%s_%s_test" % (
                (chain.get("controller_prefix") or {}).get("pole", "HP" if kind == "arm" else "FP"), side))
        if pole_object is not None:
            pole_by_part[chain.get("part")] = (kind, side, pole_object)

    # 一 · 手指控制器挂到手腕下面
    for chain in chains:
        if chain.get("kind") != "finger":
            continue
        side = chain.get("side")
        hand_object = hand_by_side.get(side)
        if hand_object is None:
            continue
        segments = chain.get("segments") or []
        if not segments:
            continue
        owner_bone = segments[-1]
        if owner_bone not in pose_bones:
            continue
        for constraint in pose_bones[owner_bone].constraints:
            if constraint.type != "IK":
                continue
            for role, target in (("目标", getattr(constraint, "target", None)),
                                 ("极向量", getattr(constraint, "pole_target", None))):
                if target is None or target is hand_object:
                    continue
                if target.parent is hand_object:
                    continue
                report("controller", "%s.%s 的%s控制器 %s 挂到 %s 下" % (
                    chain.get("part"), owner_bone, role, target.name, hand_object.name))
                if dry_run:
                    continue
                # 新建的空物体在 depsgraph 更新之前 matrix_world 还是单位阵，
                # 不先 update 一次就把世界变换读错了（表现是控制器被搬到原点）。
                bpy.context.view_layer.update()
                world = target.matrix_world.copy()
                target.parent = hand_object
                # 挂父级只能"无逆"：parent inverse 写成手腕世界矩阵的逆时，
                # 这两项会互相抵消，location 里存下的就是世界值 —— Blender 里看不出来，
                # 导出到引擎按"父级 × 本地"再乘一遍手腕朝向，手指目标就飞了。
                target.matrix_parent_inverse.identity()
                target.matrix_world = world
                bpy.context.view_layer.update()

    # 二 · 极向量控制器挪到合适的位置
    for part, (kind, side, pole_object) in (sorted(pole_by_part.items()) if place_poles else []):
        if kind not in ("arm", "leg"):
            continue
        chain = next((item for item in chains if item.get("part") == part), None)
        if chain is None:
            continue
        upper_name = chain.get("upper")
        if upper_name not in bones:
            continue
        limb_length = (bones[upper_name].tail_local - bones[upper_name].head_local).length
        distance = limb_length * 0.6
        if kind == "leg":
            # 腿的极向量要放到"脚怎么抬都追不上"的地方：实测 200 mm 时脚往前抬过 400 mm，
            # 极向量就被甩到弦的后面，膝盖跟着翻到身后去了（膝盖朝哪边由极向量相对弦的方位决定）。
            distance = max(distance, 0.50)
        distance = max(distance, 0.01)
        direction = -front if kind == "arm" else front
        offset = (armature_object.matrix_world.to_3x3() @ direction).normalized() * distance
        report("controller", "%s 极向量 %s 沿%s挪 %.0f mm" % (
            part, pole_object.name, "身后" if kind == "arm" else "身前", distance * 1000.0))
        if dry_run:
            continue
        # 极向量本来压在关节上（退化），一挪开 IK 才真的按它掰，这时要重新标 pole_angle。
        ik_owner = "MCH_" + chain.get("forearm", "") if ("MCH_" + chain.get("forearm", "")) in pose_bones else chain.get("forearm")
        mid_bone = chain.get("forearm")
        if ik_owner in pose_bones and mid_bone in pose_bones:
            pole_object.location = pole_object.location + offset
            bpy.context.view_layer.update()
            constraint = next((con for con in pose_bones[ik_owner].constraints
                               if con.type == "IK" and con.name.startswith(CONSTRAINT_PREFIX)), None)
            if constraint is not None:
                best_angle, best_error = resweep_pole_angle(
                    armature_object, constraint, chain.get("upper"), mid_bone, chain.get("hand"),
                    direction)
                report("controller", "%s 极向量挪开后重标 pole_angle = %s°（探针姿势下中间关节朝极向量偏 %s°）" % (
                    part, best_angle if best_angle is not None else "保持原值",
                    ("%.1f" % best_error) if best_error is not None else "n/a"))
            continue
        pole_object.location = pole_object.location + offset


def main():
    options = parse_args()
    if not options["file"]:
        print(__doc__)
        return
    ok, open_warning = common.open_mainfile_tolerant(options["file"])
    if open_warning:
        print("注意：载入时报错（多为状态键指针损坏，已跳过）：%s" % open_warning)
    if not ok:
        print("APPLY 打不开文件：%s" % options["file"])
        return

    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if options["armature"]:
        armatures = [obj for obj in armatures if obj.name == options["armature"]]
    if not armatures:
        print("APPLY 没找到骨架")
        return
    if len(armatures) > 1:
        print("APPLY 文件里有 %d 套骨架，用 --armature 指定：%s" % (
            len(armatures), ", ".join(obj.name for obj in armatures)))
        return
    armature_object = armatures[0]

    offenders = pose_is_rest(armature_object)
    if offenders:
        print("APPLY 骨架不是 rest 姿势（%d 根骨有变换：%s），改造会带歪网格，先清姿势" % (
            len(offenders), ", ".join(offenders[:6])))

    if options["order"]:
        with open(options["order"], "r", encoding="utf-8") as handle:
            order = json.load(handle)
    else:
        front_axis = options["front"]
        if front_axis is None:
            foot_names = [name for name in common.build_bone_index(armature_object)
                          if common.role_from_name(name)["role"] == "foot"
                          and common.role_from_name(name)["variant"] in ("plain", "shadow")]
            front_axis, evidence = common.detect_front_axis(common.build_bone_index(armature_object), foot_names)
            print("前方向：%s（%s）" % (_fmt(front_axis) if front_axis else None, evidence))
        order, _result = build_order_from_analysis(armature_object, front_axis, options["only"])
        order["front"] = [round(front_axis[0], 6), round(front_axis[1], 6), round(front_axis[2], 6)]

    if options["front"] is not None:
        order["front"] = [options["front"][0], options["front"][1], options["front"][2]]
    front_axis = Vector(order["front"]).normalized()

    if options["dump_order"]:
        with open(options["dump_order"], "w", encoding="utf-8") as handle:
            json.dump(order, handle, ensure_ascii=False, indent=1)
        print("改造单草稿：%s" % options["dump_order"])

    chains = order["chains"]
    if options["only"]:
        chains = [chain for chain in chains if chain.get("part") in options["only"]]
    if not chains:
        print("APPLY 没有要改的链（--only %s）" % options["only"])
        return

    for chain in chains:
        if options["pole_angle"] is not None:
            chain["pole_angle_deg"] = options["pole_angle"]
        if options["arch_percent"] is not None:
            chain["arch_percent"] = options["arch_percent"]
        if options["no_arch"]:
            chain["arch_percent"] = 0.0
        if options["test_controllers"]:
            chain.setdefault("controllers", {})["create_test"] = True
        if options["twist_action"]:
            chain["mmd_twist_action"] = options["twist_action"]

    print("")
    print("改造单：%s / %s，%d 条链%s" % (
        os.path.basename(options["file"]), armature_object.name, len(chains),
        "（dry-run，只算不写）" if options["dry_run"] else ""))
    for chain in chains:
        if chain.get("kind") == "finger":
            print("  - %s: %s  [手指，链长 3 + 指尖骨]" % (
                chain.get("part"), " → ".join(chain.get("segments") or [])))
            continue
        print("  - %s: %s → %s → %s%s" % (
            chain.get("part"), chain.get("upper"), chain.get("forearm"), chain.get("hand"),
            "  [造主骨]" if chain.get("create_mch") else ""))

    report_lines = []

    def report(step, message):
        report_lines.append((step, message))
        print("  [%-11s] %s" % (step, message))

    rows = []
    for chain in chains:
        print("")
        print("== %s ==" % chain.get("part"))
        rows.append(apply_chain(armature_object, chain, front_axis, options, report))

    print("")
    print("== 控制器 ==")
    arrange_controllers(armature_object, chains, front_axis, options["dry_run"], report,
                        place_poles=options["place_poles"])

    if options["dry_run"]:
        print("")
        print("dry-run 结束：没有写任何东西")
        return

    existing = progress.read(armature_object)
    merged_rows = progress.merge_rows(existing["rows"], rows)
    target_label = 'armature "%s"' % armature_object.name
    progress.write(armature_object, target_label, options["status"], merged_rows, "rig_apply.py",
                   front=front_axis)
    print("")
    print("进度文本块已写回 %s" % progress.TEXT_BLOCK_NAME)

    if options["out"]:
        save_file(options["out"], copy=True)
        print("已另存：%s" % options["out"])
    elif options["save"]:
        save_file(bpy.data.filepath, copy=False)
        print("已保存：%s" % bpy.data.filepath)
    else:
        print("没有保存（要落盘加 --out <路径> 或 --save）")


if __name__ == "__main__":
    main()

