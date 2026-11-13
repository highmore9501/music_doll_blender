# common/animation_utils.py
"""动画通用工具 —— 公共模块（对应各乐器插件的 make_animation 里的通用部分）

提供所有乐器共用的：
- 集合对象递归收集；
- fcurve 批量写入（预解析 + 批量写 keyframe_points，性能优化）；
- 动作（action）的复用与回收：同名优先复用，清动画时把失去使用者的旧动作删除；
- shape key 归零 / 清除动画；
- driver 备份/恢复工具（可选，供需要手工搬运驱动的场景使用）；清动画默认保留 driver；
- 清动画（按演奏者后缀过滤，多演奏者隔离）。
"""

import math

import bpy  # type: ignore

from . import performer_utils


# ── 集合对象递归收集 ──────────────────────────────────────────

def collect_collection_objects(col, exclude_names, object_names) -> None:
    """递归收集集合内所有物体名称（排除列表中的除外）。"""
    for obj in col.objects:
        if obj.name in exclude_names:
            continue
        object_names.append(obj.name)

    for child_col in col.children:
        if child_col.name in exclude_names:
            continue
        collect_collection_objects(child_col, exclude_names, object_names)


# ── fcurve 批量写入（Blender 4.x / 5.x 兼容）──────────────────

def get_or_create_fcurve(datablock, data_path, index=0):
    """在 datablock 的动画 action 中查找或创建一条 fcurve（兼容 Blender 4.x 与 5.x）。

    Blender 5.0 起 Action 不再暴露 fcurves 集合，需使用
    Action.fcurve_ensure_for_datablock() 来确保 F-Curve 存在；
    旧版本（4.x）则直接使用 action.fcurves 查找或创建。
    前提：datablock.animation_data.action 已存在（由调用方先创建并赋值）。
    """
    anim_data = datablock.animation_data
    if anim_data is None or anim_data.action is None:
        return None
    action = anim_data.action

    ensure = getattr(action, 'fcurve_ensure_for_datablock', None)
    if ensure is not None:
        return ensure(datablock, data_path, index=index)

    for fcurve in action.fcurves:
        if fcurve.data_path == data_path and fcurve.array_index == index:
            return fcurve
    return action.fcurves.new(data_path, index=index)


def write_fcurve_points(fcurve, keyframes, clear_existing=True) -> None:
    """批量写入 fcurve 的关键帧点（比逐帧 frame_set + keyframe_insert 快得多）。

    :param fcurve: fcurve 对象
    :param keyframes: 可迭代的 (frame, value) 序列
    :param clear_existing: 是否先清空该 fcurve 上已有的关键帧点
    """
    if fcurve is None:
        return
    keyframes = list(keyframes)
    # 清空必须写在"没有数据就直接返回"之前：否则某条通道这次没有数据时，
    # 它上一次留下的关键帧会原样保留下来。
    if clear_existing:
        fcurve.keyframe_points.clear()
    if not keyframes:
        fcurve.update()
        return

    points = fcurve.keyframe_points
    points.add(count=len(keyframes))
    for point, (frame, value) in zip(points, keyframes):
        point.co = (float(frame), float(value))
        # VECTOR 手柄 + BEZIER 插值：接近原 keyframe_insert 的默认表现，且不会过冲
        point.interpolation = 'BEZIER'
        point.handle_left_type = 'VECTOR'
        point.handle_right_type = 'VECTOR'
    fcurve.update()


# ── 把 `.animation` 帧记录写成物体关键帧 ──────────────────────
#
# 各乐器产物的 `.animation` 都是同一个形状：
#
#     [{"frame": 0, "hand_infos": {"H_L": [x, y, z, w, i, j, k]}}]
#
# 一个控制器 7 个数：位置 3 个 + 四元数 4 个（四元数 w 在前）。只写位置（3 个）或
# 只写朝向（4 个）的条目也认。这里只负责把数值写进 fcurve，短名怎么换算成场景对象名
# 由调用方给——各乐器的手指、控制器命名与演奏者后缀规则不同。

def _animation_frame_number(raw_frame):
    """帧号 → 整数；不是有限数值、或落在负帧上时返回 None（那一条整条跳过）。"""
    try:
        frame = float(raw_frame)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(frame) or frame < 0:
        return None
    return int(round(frame))


def _continuous_quaternion(previous_quaternion, quaternion):
    """与上一帧点积为负就把四个数一起取反：同一段旋转插值走最短路径。"""
    if previous_quaternion is None:
        return quaternion
    dot_product = sum(
        previous * current
        for previous, current in zip(previous_quaternion, quaternion))
    if dot_product < 0:
        return [-component for component in quaternion]
    return quaternion


def apply_transform_animation(frame_records, object_name_of,
                              action_suffix="_anim"):
    """把一份 `.animation` 帧记录写成物体关键帧（位置 + 四元数）。

    位置与朝向分开收集：某个控制器只写了位置时，它的朝向不会被上一次的残值带跑。

    :param frame_records: `[{"frame": 0, "hand_infos": {短名: [数值...]}}]`
    :param object_name_of: 短名 → 场景对象名的函数（多演奏者时补后缀）
    :param action_suffix: 动作名 = 对象名 + 它；同名动作会被复用，重跑不会留多份
    :return: `{"objects": 写入的对象数, "missing": [找不到的对象名...]}`
    """
    channel_data = {}
    previous_quaternions = {}

    for frame_record in frame_records or []:
        if not isinstance(frame_record, dict):
            continue
        frame = _animation_frame_number(frame_record.get("frame"))
        if frame is None:
            continue

        for short_name, transform_data in (frame_record.get("hand_infos") or {}).items():
            if not isinstance(transform_data, (list, tuple)):
                print(f"警告: 控制器 {short_name} 的数据不是数值数组，跳过")
                continue
            if len(transform_data) not in (3, 4, 7):
                print(f"警告: 控制器 {short_name} 的数据维度 "
                      f"{len(transform_data)} 无法识别，跳过")
                continue

            object_name = object_name_of(short_name)
            entry = channel_data.setdefault(object_name, {
                "location_frames": [], "locations": [],
                "quaternion_frames": [], "quaternions": [],
            })

            if len(transform_data) in (3, 7):
                entry["location_frames"].append(frame)
                entry["locations"].append(
                    [float(component) for component in transform_data[:3]])

            if len(transform_data) in (4, 7):
                quaternion = _continuous_quaternion(
                    previous_quaternions.get(object_name),
                    [float(component) for component in transform_data[-4:]])
                previous_quaternions[object_name] = quaternion
                entry["quaternion_frames"].append(frame)
                entry["quaternions"].append(quaternion)

    written_count = 0
    missing_names = []
    for object_name, entry in channel_data.items():
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            missing_names.append(object_name)
            print(f"警告: 物体 {object_name} 不存在于场景中，跳过")
            continue

        if not obj.animation_data:
            obj.animation_data_create()
        get_or_create_action(obj, f"{object_name}{action_suffix}")

        if entry["locations"]:
            for axis_index in range(3):
                fcurve = get_or_create_fcurve(obj, "location", index=axis_index)
                write_fcurve_points(fcurve, zip(
                    entry["location_frames"],
                    [location[axis_index] for location in entry["locations"]]))

        if entry["quaternions"]:
            obj.rotation_mode = 'QUATERNION'
            for axis_index in range(4):
                fcurve = get_or_create_fcurve(
                    obj, "rotation_quaternion", index=axis_index)
                write_fcurve_points(fcurve, zip(
                    entry["quaternion_frames"],
                    [quaternion[axis_index] for quaternion in entry["quaternions"]]))

        written_count += 1

    return {"objects": written_count, "missing": missing_names}


# ── 动作（action）的复用与回收 ────────────────────────────────

def get_or_create_action(datablock, action_name):
    """取得 datablock 的动画动作：先用挂着的，其次复用同名的，最后才新建。

    同名动作直接复用，避免每重跑一次插帧就在文件里多留一份 xxx_anim.001。
    """
    anim_data = datablock.animation_data
    if anim_data is None:
        datablock.animation_data_create()
        anim_data = datablock.animation_data
    if anim_data is None:
        return None
    if anim_data.action is not None:
        return anim_data.action

    action = bpy.data.actions.get(action_name)
    if action is None:
        action = bpy.data.actions.new(action_name)
    anim_data.action = action
    return action


def discard_action_if_unused(action) -> bool:
    """把已经没有使用者的动作从文件里删掉（删掉了返回 True）。

    判断依据是"还有没有物体 / 形态键在用"，不能用 action.users：
    动作只要被保存下来的界面状态（大纲视图的记录等）引用过，users 就不会归零，
    Blender 自带的"清理未使用数据"因此永远删不到它。
    """
    if action is None:
        return False
    try:
        owners = bpy.data.user_map(subset=[action]).get(action, set())
        for owner in owners:
            if owner.bl_rna.identifier in ('Object', 'Key'):
                return False
        bpy.data.actions.remove(action)
    except (RuntimeError, ReferenceError, ValueError):
        return False
    return True


def clear_animation_and_discard(owner) -> None:
    """清除任意 ID（物体 / 形态键 / 节点树）上的动画数据，并删掉失去使用者的旧动作。"""
    if owner is None:
        return
    anim_data = getattr(owner, 'animation_data', None)
    if anim_data is None:
        return
    discarded_action = anim_data.action
    owner.animation_data_clear()
    discard_action_if_unused(discarded_action)


def clear_animation_preserve_drivers(owner) -> None:
    """清除任意 ID（物体 / 形态键）上的关键帧动画，但完全不碰它的驱动器。

    做法是把动作从 ID 上摘下来再回收，而不是 `animation_data_clear()`——
    后者会把 drivers 一起清空。驱动因此保持原对象、原表达式，不需要重建。
    """
    if owner is None:
        return
    anim_data = getattr(owner, 'animation_data', None)
    if anim_data is None:
        return

    discarded_action = anim_data.action
    anim_data.action = None

    # NLA 轨道也属于关键帧动画，一并清掉；drivers 不在这些轨道里
    for track in list(anim_data.nla_tracks):
        anim_data.nla_tracks.remove(track)

    discard_action_if_unused(discarded_action)


# ── shape key 工具 ────────────────────────────────────────────

def reset_shape_keys(obj, value: float = 0.0) -> None:
    """把对象所有 shape key 的值归零。"""
    if obj is None:
        return
    if hasattr(obj.data, "shape_keys") and obj.data.shape_keys:
        for shape_key_block in obj.data.shape_keys.key_blocks:
            shape_key_block.value = value


def clear_shape_key_animation(obj) -> None:
    """清除对象的 shape key 动画数据（连带删掉失去使用者的旧动作）。"""
    if obj is None:
        return
    if hasattr(obj.data, "shape_keys") and obj.data.shape_keys:
        clear_animation_and_discard(obj.data.shape_keys)


# ── driver 备份 / 恢复 ────────────────────────────────────────

def backup_driver(driver):
    """深度备份一个驱动器（包括所有变量和配置）。"""
    if not driver:
        return None

    backup = {
        'type': driver.type,
        'expression': driver.expression,
        'use_self': driver.use_self,
        'variables': []
    }

    for var in driver.variables:
        var_backup = {
            'name': var.name,
            'type': var.type,
            'targets': []
        }
        for target in var.targets:
            target_backup = {
                'id_type': target.id_type if hasattr(target, 'id_type') else None,
                'id': target.id if target.id else None,
                'data_path': target.data_path if target.data_path else '',
                'bone_target': target.bone_target if hasattr(target, 'bone_target') else '',
                'transform_type': target.transform_type if hasattr(target, 'transform_type') else '',
                'transform_space': target.transform_space if hasattr(target, 'transform_space') else '',
                'rotation_mode': target.rotation_mode if hasattr(target, 'rotation_mode') else ''
            }
            var_backup['targets'].append(target_backup)
        backup['variables'].append(var_backup)

    return backup


def restore_driver(new_driver, backup) -> None:
    """将备份的驱动器数据恢复到新驱动器。"""
    if not backup or not new_driver:
        return

    new_driver.type = backup['type']
    new_driver.expression = backup['expression']
    new_driver.use_self = backup['use_self']

    while len(new_driver.variables) > 0:
        new_driver.variables.remove(new_driver.variables[0])

    for var_backup in backup['variables']:
        new_var = new_driver.variables.new()
        new_var.name = var_backup['name']
        new_var.type = var_backup['type']

        for i, target_backup in enumerate(var_backup['targets']):
            if i >= len(new_var.targets):
                break
            target = new_var.targets[i]

            if target_backup['id']:
                target.id = target_backup['id']
            if target_backup['data_path']:
                target.data_path = target_backup['data_path']
            if target_backup['bone_target']:
                target.bone_target = target_backup['bone_target']
            if hasattr(target, 'transform_type') and target_backup['transform_type']:
                target.transform_type = target_backup['transform_type']
            if hasattr(target, 'transform_space') and target_backup['transform_space']:
                target.transform_space = target_backup['transform_space']
            if hasattr(target, 'rotation_mode') and target_backup['rotation_mode']:
                target.rotation_mode = target_backup['rotation_mode']


# ── 清动画（多演奏者：按后缀过滤）─────────────────────────────

def clear_all_keyframe(collection_names=None, exclude_names=None,
                       suffix="") -> None:
    """清除关键帧，但保留物体上的驱动器。

    生成动画前的清理只该动关键帧：物体动画数据里的 driver（ext 辅助控件、
    Middle_Hand 等）一律原样保留，不依赖调用方事先排除。

    :param collection_names: 要处理的集合名称（短名，自动按演奏者后缀解析）
    :param exclude_names: 要排除的物体名称或集合名称列表
    :param suffix: 演奏者后缀；非空时只处理该演奏者命名空间内的对象
    """
    if exclude_names is None:
        exclude_names = []
    if collection_names is None:
        collection_names = []

    object_names = []

    if collection_names:
        for collection_name in collection_names:
            collection = bpy.data.collections.get(
                performer_utils.resolve(collection_name, suffix))
            if collection:
                collect_collection_objects(
                    collection, exclude_names, object_names)
            else:
                print(f"Collection '{collection_name}' not found")
    else:
        for obj in bpy.data.objects:
            if suffix and not obj.name.endswith("_" + suffix):
                continue
            if obj.name not in exclude_names:
                object_names.append(obj.name)

    for obj_name in object_names:
        ob = bpy.data.objects.get(obj_name)
        if ob is None or ob.name in exclude_names:
            continue

        # 归零 shape key，并清除物体与 shape key 上的动画（用完的旧动作随即删掉）
        reset_shape_keys(ob, 0.0)
        clear_shape_key_animation(ob)
        clear_animation_preserve_drivers(ob)

    bpy.ops.object.select_all(action='DESELECT')


def clear_all_keyframe_preserve_drivers(collection_names=None,
                                        exclude_names=None, suffix="") -> None:
    """清除关键帧但保留驱动器。

    保留旧函数名供各乐器调用；实际清理与 `clear_all_keyframe` 相同，
    物体上的 driver 一律不碰。
    """
    clear_all_keyframe(collection_names, exclude_names, suffix)
