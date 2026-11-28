# -*- coding: utf-8 -*-
"""上半身 / 头部控制链：把乐器模块自己的 `Head_Control` / `Look_At` 接到人物骨架上。

有些乐器模块（架子鼓、钢琴、古筝、竖琴）会在 setup 时建一套"看向哪里"的控件：

    Head_Control  —— 头往哪转（模块给它挂 Track_To，Z 轴指向 Look_At、Y 轴朝上）
    Look_At       —— 视点（多数模块让它挂在 `Middle_Hand` 下、跟着双手中点走）

但刚建出来时它们只是两个躺在世界的空/网格，人物的胸、颈、头**不认**它们。这一层负责把
人物接上去，形状按作者手工调好的那一版（头骨挂世界复制旋转、头上 Track_To 指向视点、颈上 IK 链长 = 躯干级数）：

    头骨（頭 / head） ──世界空间复制旋转──▶  Head_Control        ← 头的朝向直接等于它
                                                │
                                                ├── Track_To：Z 轴指向 Look_At、Y 轴朝上
                                                │
                                                └── IK 的目标（链长 = 颈到腰的级数）：
                                                    颈 → 上胸 → 胸       ← 上半身跟着这个点弯
                                                              ▲
                                                    极向量 = Look_At   （往视点那侧弯）

六条规矩（与作者成品一致）：

1. **`Head_Control` 摆在人物的头部骨骼位置**（= 颈骨的尾端 = 头骨的关节），不是原点，
   也不是"头心前面一点"——摆在关节上，rest 姿势才是这条 IK 链的精确解；
2. **`Look_At` 摆在人物正前方**（沿头骨自己的 Z 轴，也就是脸朝的方向），距离取链长的
   `look_distance` 倍；它本来挂在 `Middle_Hand` 下，所以双手一动视点跟着动，这是模块的设计；
3. **IK 挂在颈骨上**（= 头骨的父级），目标是 `Head_Control`、极向量是 `Look_At`；
4. **链长 = 颈骨往上数、到腰骨为止的级数**（米娅是 `首 → 上半身2 → 上半身` = 3）：
   腰以下挂着下半身（腿），包进来一动腰就带着腿转，所以**链头停在腰的上方那一节**；
5. **头骨挂世界空间复制旋转**（REPLACE），头的朝向直接等于控制器，不叠颈的余数；
6. **`Head_Control` 上要有一条 Track_To**：Z 轴指向 `Look_At`、Y 轴朝上（Y 是骨的径向轴，
   头部正常摆放时它就是世界向上），并把 `use_target_z` 关掉——否则头会绕视点方向乱滚。

规矩与 `music-doll-rig/scripts/rig_upper.py` 是同一套（同样的名字判据、同样的摆位、同样用
"rest 关节位移最小"标定 `pole_angle`）。这里自带一份，是为了让本 skill 不依赖 rig skill 也能跑；
两边改判据时要一起改。

本模块只碰三样东西：两根骨上的约束、链上这几根骨原有的约束（只静音不删）、以及链上关节的
`use_connect`（只在两节本来就重合时才接）。不动权重、不动 rest 朝向、不动动画。
"""

import math

import bpy
from mathutils import Matrix, Vector

CONSTRAINT_IK = "MD_IK_upper"
CONSTRAINT_ROT = "MD_Rot_upper"
TRACK_CONSTRAINT = "Track_Look_At"

# 名字判据：只给躯干这条串联链用（四肢那套"三段主骨"口径不适用）。
# 只认**主干精确命中**与英文关键词，不做包含匹配 —— `腰キャンセル`、`上半身2补助` 这类
# 派生骨必须落回"未分类"，否则它们会被当成链的一节。
SPINE_ROLE_STEMS = {
    "neck": ("首", "頸", "颈", "首根元"),
    "head": ("頭", "头", "頭部"),
    "chest": ("上半身", "上半身2", "上半身3", "胸", "胸部", "胴"),
    "spine": ("背骨", "腹", "腹部", "下腹"),
    "waist": ("腰", "下半身", "骨盤", "胴体"),
}
SPINE_ROLE_KEYWORDS = {
    "neck": ("neck",),
    "head": ("head", "skull"),
    "chest": ("chest", "upperchest", "torso", "spine2", "spine3", "spine02", "spine03"),
    "spine": ("spine", "spine1", "spine01", "abdomen", "belly"),
    "waist": ("waist", "hips", "pelvis", "hip"),
}
NAME_PREFIXES = ("_shadow_", "_dummy_", "MCH_", "MCH-", "MCH.")
SIDE_SUFFIXES = (".L", ".R", ".l", ".r", "_L", "_R", "-L", "-R")

# 关节"本来就连在一起"的判据：骨架单位 1e-3（改过单位的模型 1 单位 = 1 cm，即 10 μm）。
CHAIN_JOINT_TOLERANCE = 1e-3

# 自检容差
REST_MESH_TOLERANCE = 1e-4
REACH_TOLERANCE_RATIO = 0.02
ROTATION_TOLERANCE_DEG = 1.0
AIM_TOLERANCE_DEG = 2.0
BEND_TOLERANCE_DEG = 5.0
PLACEMENT_TOLERANCE_RATIO = 0.02  # 头部控制器离颈尾允许的偏差（× 链长）

# pole_angle 标定：粗扫 5°、细扫 1°。角度相对骨自己的坐标系量，到 1° 就够。
COARSE_STEP_DEG = 5.0
FINE_STEP_DEG = 1.0

DEFAULT_POLE_ANGLE_DEG = 90.0


class HeadChainError(RuntimeError):
    pass


# ── 名字 → 角色 ─────────────────────────────────────────────────────────

def bone_stem(name):
    """去掉影子 / 主骨前缀与侧别后缀之后的主干名。"""
    working = name
    changed = True
    while changed:
        changed = False
        for prefix in NAME_PREFIXES:
            if working.startswith(prefix) and len(working) > len(prefix):
                working = working[len(prefix):]
                changed = True
                break
    for suffix in SIDE_SUFFIXES:
        if working.endswith(suffix) and len(working) > len(suffix):
            working = working[:-len(suffix)]
            break
    return working


def spine_role_from_name(name):
    """返回 (角色, 置信度)：neck / head / chest / spine / waist；认不出返回 (None, None)。"""
    stem = bone_stem(name)
    if not stem:
        return None, None
    for role, stems in SPINE_ROLE_STEMS.items():
        if stem in stems:
            return role, "high"
    bare_stem = stem.lower().replace("_", "").replace(".", "").replace(" ", "")
    without_digits = bare_stem.rstrip("0123456789")
    for role, keywords in SPINE_ROLE_KEYWORDS.items():
        if bare_stem in keywords:
            return role, "low"
        if without_digits and without_digits != bare_stem and without_digits in keywords:
            return role, "low"
    return None, None


def _pick_bone(bones, wanted_role, preferred_parent=None):
    """按角色挑一根骨：名字精确命中的优先、有父级要求的次之、形变骨优先。"""
    candidates = []
    for bone in bones:
        role, confidence = spine_role_from_name(bone.name)
        if role != wanted_role:
            continue
        candidates.append((bone, confidence))
    if not candidates:
        return None, "没找到"
    if preferred_parent is not None:
        # bpy 每次访问都给出新的包装对象，不能用 `is` 比父子关系，要比名字。
        nested = [item for item in candidates
                  if item[0].parent is not None
                  and item[0].parent.name == preferred_parent.name]
        if not nested:
            return None, "找到了但不在 %s 下面" % preferred_parent.name
        candidates = nested
    candidates.sort(key=lambda item: (item[1] != "high", not item[0].use_deform))
    return candidates[0][0], candidates[0][1]


def detect_spine(armature_object, spec, report):
    """认颈骨 / 头骨 / IK 链（颈 → 根）。认不出时抛 HeadChainError。"""
    bones = armature_object.data.bones
    neck_name = spec.get("neck_bone") or ""
    head_name = spec.get("head_bone") or ""

    if neck_name:
        neck_bone = bones.get(neck_name)
        if neck_bone is None:
            raise HeadChainError("指定的颈骨不存在：" + neck_name)
        report("颈骨 = %s（命令行指定）" % neck_bone.name)
    else:
        neck_bone, evidence = _pick_bone(bones, "neck")
        if neck_bone is None:
            raise HeadChainError(
                "认不出颈骨（%s），用 --neck-bone 或适配器的 neck_bone 指定" % evidence)
        report("颈骨 = %s（名字判据 %s）" % (neck_bone.name, evidence))

    if head_name:
        head_bone = bones.get(head_name)
        if head_bone is None:
            raise HeadChainError("指定的头骨不存在：" + head_name)
        report("头骨 = %s（命令行指定）" % head_bone.name)
    else:
        head_bone, evidence = _pick_bone(bones, "head", preferred_parent=neck_bone)
        if head_bone is None:
            raise HeadChainError(
                "认不出头骨（%s），用 --head-bone 或适配器的 head_bone 指定" % evidence)
        report("头骨 = %s（名字判据 %s）" % (head_bone.name, evidence))

    # 链：颈骨 + 往上数的胸/背，**停在腰之前**。腰下面挂着下半身（腿），包进来一动腰就带腿转。
    chain_names = [neck_bone.name]
    requested = int(spec.get("chain_count") or 0)
    cursor = neck_bone.parent
    while cursor is not None and (requested <= 0 or len(chain_names) < requested):
        role, _confidence = spine_role_from_name(cursor.name)
        if role not in ("chest", "spine"):
            if role == "waist":
                report("IK 链停在 %s（腰）之前：它下面挂着下半身（腿）" % cursor.name)
            else:
                report("IK 链停在 %s（%s）之前：它不是躯干骨，再往上会把不相干的东西一起转"
                       % (cursor.name, role or "未分类"))
            break
        chain_names.append(cursor.name)
        cursor = cursor.parent
    if requested > 0 and len(chain_names) < requested:
        report("躯干只找到 %d 节（要求 %d 节），按 %d 节做 IK"
               % (len(chain_names), requested, len(chain_names)))
    report("IK 链（颈 → 根）= %s" % " → ".join(chain_names))
    return {"neck": neck_bone.name, "head": head_bone.name, "chain": chain_names}


# ── 几何 ────────────────────────────────────────────────────────────────

def world_head(armature_object, bone_name):
    return armature_object.matrix_world @ armature_object.pose.bones[bone_name].head


def world_tail(armature_object, bone_name):
    return armature_object.matrix_world @ armature_object.pose.bones[bone_name].tail


def evaluated_world(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return obj.evaluated_get(depsgraph).matrix_world.copy()


def set_world_location_keep_rotation(obj, location):
    """只换世界位置，旋转与缩放保持对象自己的（控件的显示尺寸不该被这里改掉）。"""
    _translation, rotation, scale = obj.matrix_world.decompose()
    obj.matrix_world = Matrix.LocRotScale(location, rotation, scale)


def set_world_pose_keep_scale(obj, matrix):
    translation, rotation, _scale = matrix.decompose()
    obj.matrix_world = Matrix.LocRotScale(translation, rotation, obj.matrix_world.to_scale())


def spine_geometry(armature_object, spine, spec):
    """链长 / 头骨 rest 朝向外加视点该放多远。"""
    bones = armature_object.data.bones
    chain_root = armature_object.matrix_world @ bones[spine["chain"][-1]].head_local
    chain_end = armature_object.matrix_world @ bones[spine["neck"]].tail_local
    head_matrix = armature_object.matrix_world @ bones[spine["head"]].matrix_local
    head_forward = head_matrix.to_3x3().col[2].normalized()
    chain_length = (chain_end - chain_root).length
    look_distance = float(spec.get("look_distance") or 1.0)
    return {
        "chain_root": chain_root,
        "chain_end": chain_end,
        "chain_length": chain_length,
        "head_matrix": head_matrix,
        "head_forward": head_forward,
        "look_point": chain_end + head_forward * chain_length * look_distance,
        "look_distance": look_distance,
    }


# ── 摆控件 ──────────────────────────────────────────────────────────────

def place_controllers(head_control, look_at, geometry, report):
    """头部控制器 = 颈尾（头部骨骼位置）；视点 = 沿脸朝方向、链长若干倍的正前方。"""
    set_world_pose_keep_scale(head_control, geometry["head_matrix"])
    set_world_location_keep_rotation(look_at, geometry["look_point"])
    bpy.context.view_layer.update()

    head_error = (evaluated_world(head_control).translation
                  - geometry["chain_end"]).length
    look_error = (evaluated_world(look_at).translation
                  - geometry["look_point"]).length
    report("头部控制器 %s 摆到颈尾 %s（偏差 %.6f m）" % (
        head_control.name,
        "(%0.4f, %0.4f, %0.4f)" % tuple(geometry["chain_end"]), head_error))
    report("视点 %s 摆到正前方 %s（偏差 %.6f m，距颈尾 %.4f m = 链长 %.4f × %.2f）" % (
        look_at.name,
        "(%0.4f, %0.4f, %0.4f)" % tuple(geometry["look_point"]), look_error,
        (geometry["look_point"] - geometry["chain_end"]).length,
        geometry["chain_length"], geometry["look_distance"]))
    if head_error > 1e-4 or look_error > 1e-4:
        raise HeadChainError(
            "控件没能摆到目标位置（头部控制器偏差 %.6f m、视点偏差 %.6f m）。"
            "多半是它们的父级上有约束/驱动在拉（Look_At 通常挂在 Middle_Hand 下），"
            "或父级矩阵还没更新；先 view_layer.update() 再设一次。" % (head_error, look_error))


def ensure_track(head_control, look_at, report):
    """头部控制器的 Track_To：Z 轴指向视点、Y 轴朝上、不取目标 Z 轴。

    乐器模块在建控件时已经挂了一条（通常叫 `Track_Look_At`）；有就沿用，没有才补。
    目标一定要指向本文讨论的 `Look_At`，否则头会看着别的地方。
    """
    existing = None
    for constraint in head_control.constraints:
        if constraint.type == "TRACK_TO":
            existing = constraint
            break
    created = existing is None
    if created:
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
    report("Track_To：%s 的 Z 轴指向 %s、Y 轴朝上（%s）" % (
        head_control.name, look_at.name, "新建" if created else "沿用 " + existing.name))
    return existing


# ── 关节 / 原件约束 ─────────────────────────────────────────────────────

def _set_active(armature_object):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    armature_object.hide_set(False)
    armature_object.hide_viewport = False
    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)


def connect_chain(armature_object, spine, report):
    """链上每对父子：后一根的头压在前一根的尾上，并且 use_connect = 1。

    不连的话，子骨仍然能被单独平移 —— 拖头部控制器时链会从中间散开。只在两节**本来就重合**
    时接（差值在 CHAIN_JOINT_TOLERANCE 内）；对不上就只报告，不掰尾端 —— 躯干尾端一挪，
    权重和影子骨的驱动都要跟着重算，那是 rig 阶段（`rig_connect.py --fix-tails`）的活。
    """
    bones = armature_object.data.bones
    pairs = [(spine["chain"][index], spine["chain"][index - 1])
             for index in range(1, len(spine["chain"]))]
    pairs.append((spine["neck"], spine["head"]))
    loose = []
    to_connect = []
    for parent, child in pairs:
        parent_bone = bones.get(parent)
        child_bone = bones.get(child)
        if parent_bone is None or child_bone is None:
            continue
        gap = (parent_bone.tail_local - child_bone.head_local).length
        if gap > CHAIN_JOINT_TOLERANCE:
            loose.append("%s→%s gap=%.4f" % (parent, child, gap))
            report("关节 %s→%s 差 %.4f，不硬掰（要掰跑 rig skill 的 rig_connect.py）"
                   % (parent, child, gap))
            continue
        if child_bone.use_connect:
            continue
        to_connect.append(child)
    if not to_connect:
        report("链上关节：%d 对都已经是连着的%s" % (
            len(pairs), "" if not loose else "（%d 对没对上）" % len(loose)))
        return loose

    if armature_object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    _set_active(armature_object)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit_bones = armature_object.data.edit_bones
        for child_name in to_connect:
            edit_bone = edit_bones.get(child_name)
            if edit_bone is None:
                continue
            edit_bone.use_connect = True
            report("关节 %s 接上（use_connect=1，两节本来就重合）" % child_name)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    return loose


def mute_legacy_constraints(armature_object, spine, report):
    """链上这几根骨只留我们自己的约束生效，原件的 `mmd_*` / IK 一律静音（不删，留可回溯）。

    与四肢那条规矩的差别：**不顺手静音影子双胞胎**（`_shadow_上半身` 之类）。躯干的影子骨是
    别人的"姿势来源"，静音会把不相干的东西弄掉，只在报告里点名。
    """
    muted = []
    shadows = []
    for bone_name in list(spine["chain"]) + [spine["head"]]:
        pose_bone = armature_object.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        for constraint in pose_bone.constraints:
            if constraint.name.startswith("MD_") or constraint.mute:
                continue
            if constraint.name == TRACK_CONSTRAINT:
                continue
            constraint.mute = True
            muted.append("%s.%s" % (bone_name, constraint.name))
        for prefix in ("_shadow_", "_dummy_"):
            if (prefix + bone_name) in armature_object.data.bones:
                shadows.append(prefix + bone_name)
    if muted:
        report("链上 %d 条原件约束静音（只留 MD_*）：%s" % (len(muted), "、".join(muted)))
    if shadows:
        report("注意：这些骨还有影子双胞胎 %s —— 网格若挂在它们身上，躯干形变不归这条链管"
               % "、".join(shadows))
    return muted


def strip_our_constraints(armature_object, spine):
    """重跑前先摘掉上次加的约束，让这次量到的"改前"是干净状态。"""
    removed = []
    for bone_name in list(spine["chain"]) + [spine["head"]]:
        pose_bone = armature_object.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        for constraint in list(pose_bone.constraints):
            if constraint.name.startswith("MD_"):
                removed.append("%s.%s" % (bone_name, constraint.name))
                pose_bone.constraints.remove(constraint)
    return removed


# ── 约束 ────────────────────────────────────────────────────────────────

def existing_head_constraints(armature_object, head_control, head_bone_name):
    """链上已经指向这个头部控制器的 IK / 复制旋转（rig 阶段搭好的那条也算）。"""
    found = []
    for pose_bone in armature_object.pose.bones:
        for constraint in pose_bone.constraints:
            if constraint.type == "IK" and constraint.target is head_control:
                found.append((pose_bone, constraint))
            elif (constraint.type == "COPY_ROTATION"
                  and constraint.target is head_control
                  and pose_bone.name == head_bone_name):
                found.append((pose_bone, constraint))
    return found


def calibrate_pole_angle(armature_object, spine, ik_constraint, report):
    """标 `pole_angle`：目标就压在链的末端，扫一圈角度，取 rest 关节位移最小的那一档。

    rest 姿势本身就是 IK 的一个解；只有极向量平面与骨自身的弯曲平面重合时，解算才不把 rest 掰歪。
    （实测角度错 90° 时 rest 关节会被掰走几十厘米，所以这个判据很好用。）
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
    best_angle, _best_error = min(coarse, key=lambda item: item[1])
    fine = []
    angle = best_angle - COARSE_STEP_DEG
    while angle <= best_angle + COARSE_STEP_DEG + 1e-6:
        fine.append((angle, error_of(angle)))
        angle += FINE_STEP_DEG
    best_angle, best_error = min(fine, key=lambda item: item[1])
    ik_constraint.pole_angle = math.radians(best_angle)
    bpy.context.view_layer.update()
    report("标定 pole_angle = %.0f°（rest 关节最大位移 %.6f m；粗扫 %s）" % (
        best_angle, best_error,
        "、".join("%.0f°=%.4f" % (item[0], item[1]) for item in coarse[::6])))
    return best_angle, best_error, coarse


def ensure_constraints(armature_object, spine, head_control, look_at, spec, report):
    """颈上挂 IK（链长 = 躯干链、极向量 = 视点）、头上挂世界空间复制旋转。

    已经有指向同一个头部控制器的约束时沿用（rig 阶段搭好的那条），只把参数补齐；
    新建的那条才标定 `pole_angle`。
    """
    neck_pose_bone = armature_object.pose.bones[spine["neck"]]
    head_pose_bone = armature_object.pose.bones[spine["head"]]

    ik_constraint = None
    for constraint in neck_pose_bone.constraints:
        if constraint.type == "IK" and constraint.target is head_control:
            ik_constraint = constraint
            break
    ik_created = ik_constraint is None
    if ik_created:
        ik_constraint = neck_pose_bone.constraints.new("IK")
        ik_constraint.name = CONSTRAINT_IK
        ik_constraint.target = head_control
        report("%s 加 IK：链长 %d、目标 %s、极向量 %s"
               % (spine["neck"], len(spine["chain"]), head_control.name, look_at.name))
    else:
        report("%s 上已有指向 %s 的 IK（%s），沿用并把链长/极向量补齐"
               % (spine["neck"], head_control.name, ik_constraint.name))
        if not ik_constraint.name.startswith("MD_"):
            ik_constraint.name = CONSTRAINT_IK
    ik_constraint.target = head_control
    ik_constraint.subtarget = ""
    ik_constraint.pole_target = look_at
    ik_constraint.pole_subtarget = ""
    ik_constraint.chain_count = len(spine["chain"])
    ik_constraint.use_tail = True
    ik_constraint.use_stretch = True
    ik_constraint.mute = False
    ik_constraint.influence = 1.0
    bpy.context.view_layer.update()

    requested_angle = spec.get("pole_angle")
    if requested_angle is not None:
        ik_constraint.pole_angle = math.radians(float(requested_angle))
        report("按指定的 %.0f° 用%s" % (
            float(requested_angle), "，不标定" if ik_created else "（覆盖既有值）"))
    elif ik_created:
        calibrate_pole_angle(armature_object, spine, ik_constraint, report)
    else:
        report("pole_angle 沿用既有值 %.1f°" % math.degrees(ik_constraint.pole_angle))

    rotation_constraint = None
    for constraint in head_pose_bone.constraints:
        if constraint.type == "COPY_ROTATION" and constraint.target is head_control:
            rotation_constraint = constraint
            break
    rotation_created = rotation_constraint is None
    if rotation_created:
        rotation_constraint = head_pose_bone.constraints.new("COPY_ROTATION")
        rotation_constraint.name = CONSTRAINT_ROT
        report("%s 加世界空间复制旋转 ← %s" % (spine["head"], head_control.name))
    elif not rotation_constraint.name.startswith("MD_"):
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
    bpy.context.view_layer.update()

    return {
        "ik": ik_constraint,
        "ik_created": ik_created,
        "rotation": rotation_constraint,
        "rotation_created": rotation_created,
    }


# ── 自检 ────────────────────────────────────────────────────────────────

def pose_axes(armature_object, bone_name):
    rotation = armature_object.pose.bones[bone_name].matrix.to_3x3()
    rotation = armature_object.matrix_world.to_3x3() @ rotation
    return (rotation.col[0].normalized(), rotation.col[1].normalized(),
            rotation.col[2].normalized())


def rotation_difference_degrees(first, second):
    """两个四元数之间的夹角（度）。

    mathutils 的 `.angle` 在差四元数 w<0 时给的是 ~360°（同一个旋转的另一种写法），
    直接拿来比会把"完全一致"读成"差了 360°"。这里折回 0~180°。
    """
    angle = first.rotation_difference(second).angle
    if angle > math.pi:
        angle = 2.0 * math.pi - angle
    return math.degrees(angle)


def bend_toward_pole(armature_object, spine, look_at):
    """中间关节相对"链根→末端"这条弦的垂直偏移，与极向量相对同一根弦的垂直偏移的夹角。

    目标落在末端上这件事两个解都能做到，只有朝向分得清"往哪边弯"（和手臂肘那条判据一样）。
    """
    chord_start = world_head(armature_object, spine["chain"][-1])
    chord_end = world_tail(armature_object, spine["neck"])
    chord = chord_end - chord_start
    if chord.length < 1e-6:
        return None
    chord_unit = chord.normalized()
    pole_offset = evaluated_world(look_at).translation - chord_start
    pole_perp = pole_offset - chord_unit * pole_offset.dot(chord_unit)
    best = None
    for name in spine["chain"][1:]:
        joint = world_head(armature_object, name) - chord_start
        joint_perp = joint - chord_unit * joint.dot(chord_unit)
        if joint_perp.length < 1e-6 or pole_perp.length < 1e-6:
            continue
        angle = math.degrees(joint_perp.angle(pole_perp))
        best = angle if best is None else max(best, angle)
    return best


def measure_poses(armature_object, spine, head_control, look_at, geometry):
    """把头部控制器摆到几档位置，量"颈尾跟得住 / 头朝向 / 头看着视点 / 往极向量那侧弯"。

    量完复位。验收脚本直接调这个函数，避免两处各写一套口径。
    """
    front = geometry["head_forward"]
    up = Vector((0.0, 0.0, 1.0))
    side = front.cross(up)
    if side.length < 1e-6:
        side = Vector((1.0, 0.0, 0.0))
    side.normalize()
    scale = geometry["chain_length"]
    offsets = (
        ("rest", Vector((0.0, 0.0, 0.0))),
        ("前伸15%", front * scale * 0.15),
        ("侧移15%", side * scale * 0.15),
        ("低头12%", -up * scale * 0.12),
    )

    base_matrix = head_control.matrix_world.copy()
    base_location = base_matrix.translation.copy()
    base_rotation = base_matrix.to_quaternion()
    base_scale = base_matrix.to_scale()
    results = []
    for tag, offset in offsets:
        head_control.matrix_world = Matrix.LocRotScale(
            base_location + offset, base_rotation, base_scale)
        bpy.context.view_layer.update()
        neck_tail = world_tail(armature_object, spine["neck"])
        control_world = evaluated_world(head_control)
        head_rotation = (armature_object.matrix_world.to_quaternion()
                         @ armature_object.pose.bones[spine["head"]].matrix.to_quaternion())
        head_z = pose_axes(armature_object, spine["head"])[2]
        aim = evaluated_world(look_at).translation - world_head(
            armature_object, spine["head"])
        results.append({
            "tag": tag,
            "gap": (neck_tail - control_world.translation).length,
            "rotation_error": rotation_difference_degrees(
                head_rotation, control_world.to_quaternion()),
            "aim_error": math.degrees(head_z.angle(aim)) if aim.length > 1e-9 else None,
            "bend_error": bend_toward_pole(armature_object, spine, look_at),
        })
    head_control.matrix_world = base_matrix
    bpy.context.view_layer.update()
    return results


# ── 主流程 ──────────────────────────────────────────────────────────────

def build(armature_object, head_control, look_at, spec, report,
          place=True, connect=True, strip=True, calibrate=True,
          check_mesh=True, mesh_reader=None):
    """把人物接到这两个控件上（幂等：重跑会先摘掉自己上次加的约束再重来）。

    参数：
        place       —— 是否重摆控件。rig 阶段已经搭好链、只是把 test 控件换成实际控件时传 False
                       （位置来自 test 控件，不能按规则再摆一遍）；
        connect     —— 是否补 `use_connect`；
        strip       —— 是否先摘掉上次加的 MD_* 约束；沿用 rig 阶段那条链时传 False（保留它标定好的
                       `pole_angle`）；
        check_mesh  —— 是否量 rest 网格位移（需要 mesh_reader）；
        mesh_reader —— 返回 {网格名: 顶点列表} 的函数。位移基线取在"先摘掉旧的 MD_* 约束之后、
                       新约束挂上之前"——修理一份已经被旧链掰歪的文件时，基线才是真正的 rest，
                       否则会把"修好它的位移"当成"接链弄坏了网格"。
    """
    spine = detect_spine(armature_object, spec, report)
    geometry = spine_geometry(armature_object, spine, spec)
    report("链长 %.4f（链根 %s → 颈尾），前方向 %s" % (
        geometry["chain_length"], spine["chain"][-1],
        "(%0.3f, %0.3f, %0.3f)" % tuple(geometry["head_forward"])))

    if strip:
        removed = strip_our_constraints(armature_object, spine)
        if removed:
            report("重跑：先摘掉上次加的 %d 条约束（%s）" % (len(removed), "、".join(removed)))
        bpy.context.view_layer.update()
    mesh_snapshot = mesh_reader() if (check_mesh and mesh_reader is not None) else None

    if place:
        place_controllers(head_control, look_at, geometry, report)
    track = ensure_track(head_control, look_at, report)
    loose_joints = connect_chain(armature_object, spine, report) if connect else []
    muted = mute_legacy_constraints(armature_object, spine, report)
    constraints = ensure_constraints(armature_object, spine, head_control, look_at, spec, report)
    if not calibrate and constraints["ik_created"]:
        constraints["ik"].pole_angle = math.radians(DEFAULT_POLE_ANGLE_DEG)
        report("保底用 %.0f°（调用方要求不标定）" % DEFAULT_POLE_ANGLE_DEG)
    bpy.context.view_layer.update()

    probes = measure_poses(armature_object, spine, head_control, look_at, geometry)
    for item in probes:
        report("%-9s 颈尾离控件 %.5f m，头朝向差 %.2f°，头看向视点差 %s°，弯曲朝极向量偏 %s°" % (
            item["tag"], item["gap"], item["rotation_error"],
            "%.2f" % item["aim_error"] if item["aim_error"] is not None else "-",
            "%.1f" % item["bend_error"] if item["bend_error"] is not None else "-"))

    checks = []

    # 控件摆位：头部控制器压在颈尾上（= 头部骨骼位置），视点在人正前方
    placement_error = (evaluated_world(head_control).translation
                       - geometry["chain_end"]).length
    look_offset = evaluated_world(look_at).translation - geometry["chain_end"]
    look_forward_cos = (look_offset.normalized().dot(geometry["head_forward"])
                        if look_offset.length > 1e-9 else 0.0)
    checks.append({
        "name": "头部控制器在头部骨骼位置",
        "ok": placement_error <= geometry["chain_length"] * PLACEMENT_TOLERANCE_RATIO,
        "detail": "离颈尾 %.6f m（容差 %.4f）" % (
            placement_error, geometry["chain_length"] * PLACEMENT_TOLERANCE_RATIO),
    })
    checks.append({
        "name": "视点在人物正前方",
        "ok": look_forward_cos >= 0.99,
        "detail": "偏离头骨 Z 轴 %.2f°，距颈尾 %.4f m" % (
            math.degrees(math.acos(max(-1.0, min(1.0, look_forward_cos)))),
            look_offset.length),
    })

    reach = max(item["gap"] for item in probes)
    rotation = max(item["rotation_error"] for item in probes)
    aims = [item["aim_error"] for item in probes if item["aim_error"] is not None]
    bends = [item["bend_error"] for item in probes if item["bend_error"] is not None]
    aim = max(aims) if aims else 0.0
    bend = max(bends) if bends else 0.0
    reach_tolerance = geometry["chain_length"] * REACH_TOLERANCE_RATIO
    checks.append({"name": "颈尾跟住头部控制器", "ok": reach <= reach_tolerance,
                   "detail": "最大差 %.5f m（容差 %.5f）" % (reach, reach_tolerance)})
    checks.append({"name": "头骨朝向 = 头部控制器", "ok": rotation <= ROTATION_TOLERANCE_DEG,
                   "detail": "最大 %.3f°（容差 %.1f°）" % (rotation, ROTATION_TOLERANCE_DEG)})
    checks.append({"name": "头骨 Z 轴指向视点", "ok": aim <= AIM_TOLERANCE_DEG,
                   "detail": "最大 %.2f°（容差 %.1f°）" % (aim, AIM_TOLERANCE_DEG)})
    checks.append({"name": "躯干往极向量那侧弯", "ok": bend <= BEND_TOLERANCE_DEG,
                   "detail": "最大偏 %.1f°（容差 %.1f°）" % (bend, BEND_TOLERANCE_DEG)})
    checks.append({"name": "链条关节对接（tail=head + connect）", "ok": not loose_joints,
                   "detail": "、".join(loose_joints) if loose_joints
                   else "%d 对关节全部相接" % (len(spine["chain"]))})
    ik = constraints["ik"]
    checks.append({
        "name": "IK 参数（链长 / 目标 / 极向量）",
        "ok": (ik.chain_count == len(spine["chain"]) and ik.target is head_control
               and ik.pole_target is look_at),
        "detail": "chain=%d target=%s pole=%s pole_angle=%.1f°" % (
            ik.chain_count, ik.target.name if ik.target else "?",
            ik.pole_target.name if ik.pole_target else "?",
            math.degrees(ik.pole_angle)),
    })
    rotation_constraint = constraints["rotation"]
    checks.append({
        "name": "复制旋转（世界空间 REPLACE）",
        "ok": (rotation_constraint.target is head_control
               and rotation_constraint.owner_space == "WORLD"
               and rotation_constraint.target_space == "WORLD"
               and rotation_constraint.mix_mode == "REPLACE"),
        "detail": "目标 %s" % (rotation_constraint.target.name
                               if rotation_constraint.target else "?"),
    })
    checks.append({
        "name": "Track_To（Z→视点、Y 朝上）",
        "ok": (track is not None and track.target is look_at
               and track.track_axis == "TRACK_Z" and track.up_axis == "UP_Y"
               and not track.use_target_z),
        "detail": "target=%s track=%s up=%s use_target_z=%s" % (
            track.target.name if track and track.target else "?",
            track.track_axis if track else "?", track.up_axis if track else "?",
            track.use_target_z if track else "?"),
    })

    mesh_delta = None
    if mesh_snapshot is not None and mesh_reader is not None:
        after = mesh_reader()
        mesh_delta = 0.0
        for mesh_name, before_points in mesh_snapshot.items():
            after_points = after.get(mesh_name)
            if after_points is None or len(after_points) != len(before_points):
                mesh_delta = float("inf")
                break
            for before_point, after_point in zip(before_points, after_points):
                mesh_delta = max(mesh_delta, (after_point - before_point).length)
        checks.append({
            "name": "rest 网格位移", "ok": mesh_delta <= REST_MESH_TOLERANCE,
            "detail": "最大 %.7f m（容差 %.0e）" % (mesh_delta, REST_MESH_TOLERANCE),
        })

    return {
        "spine": spine,
        "geometry": {
            "chain_length": geometry["chain_length"],
            "head_forward": [round(value, 6) for value in geometry["head_forward"]],
            "chain_end": [round(value, 6) for value in geometry["chain_end"]],
        },
        "head_control": head_control.name,
        "look_at": look_at.name,
        "head_control_world": [round(value, 6) for value in
                               evaluated_world(head_control).translation],
        "look_at_world": [round(value, 6) for value in evaluated_world(look_at).translation],
        "pole_angle_deg": round(math.degrees(constraints["ik"].pole_angle), 2),
        "ik_created": constraints["ik_created"],
        "rotation_created": constraints["rotation_created"],
        "connected": [bone.name for bone in armature_object.data.bones
                      if bone.use_connect and bone.name in
                      (spine["chain"] + [spine["head"]])],
        "muted_legacy": muted,
        "loose_joints": loose_joints,
        "probes": probes,
        "rest_mesh_delta": mesh_delta,
        "checks": checks,
        "passed": all(item["ok"] for item in checks),
    }


def constraints_to_freeze(armature_object, head_control, head_bone_name):
    """动作等价验收期间要临时静音的约束：这条链会把躯干带弯，污染手臂/手指的逐骨对比。

    视点在多数乐器里挂在 `Middle_Hand`（跟随双手中点）下面，动一下手视点就动，躯干跟着弯；
    那时"test 控件 vs 实际控件"的全身世界矩阵对比必然对不上——但那是设计行为，不是装错了。
    所以采样期间临时把这条链静音，链本身由上面的功能探针单独验收。
    """
    frozen = []
    for pose_bone, constraint in existing_head_constraints(
            armature_object, head_control, head_bone_name):
        if constraint.type in ("IK", "COPY_ROTATION"):
            frozen.append((pose_bone, constraint))
    return frozen


def mute_all(frozen):
    states = []
    for _pose_bone, constraint in frozen:
        states.append((constraint, constraint.mute))
        constraint.mute = True
    return states


def restore_mutes(states):
    for constraint, muted in states:
        constraint.mute = muted
