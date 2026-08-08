# common/animation_utils.py
"""动画通用工具 —— 公共模块（对应各乐器插件的 make_animation 里的通用部分）

提供所有乐器共用的：
- 集合对象递归收集；
- fcurve 批量写入（预解析 + 批量写 keyframe_points，性能优化）；
- shape key 归零 / 清除动画；
- driver 备份/恢复（清动画时保留驱动）；
- 清动画（按演奏者后缀过滤，多演奏者隔离）。
"""

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
    if not keyframes:
        return
    if clear_existing:
        fcurve.keyframe_points.clear()

    points = fcurve.keyframe_points
    points.add(count=len(keyframes))
    for point, (frame, value) in zip(points, keyframes):
        point.co = (float(frame), float(value))
        # VECTOR 手柄 + BEZIER 插值：接近原 keyframe_insert 的默认表现，且不会过冲
        point.interpolation = 'BEZIER'
        point.handle_left_type = 'VECTOR'
        point.handle_right_type = 'VECTOR'
    fcurve.update()


# ── shape key 工具 ────────────────────────────────────────────

def reset_shape_keys(obj, value: float = 0.0) -> None:
    """把对象所有 shape key 的值归零。"""
    if obj is None:
        return
    if hasattr(obj.data, "shape_keys") and obj.data.shape_keys:
        for shape_key_block in obj.data.shape_keys.key_blocks:
            shape_key_block.value = value


def clear_shape_key_animation(obj) -> None:
    """清除对象的 shape key 动画数据。"""
    if obj is None:
        return
    if hasattr(obj.data, "shape_keys") and obj.data.shape_keys:
        if obj.data.shape_keys.animation_data:
            obj.data.shape_keys.animation_data_clear()


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
    """清除关键帧。

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

        # 清除对象变换关键帧
        if ob.animation_data and ob.animation_data.action:
            ob.animation_data.action.animation_data_clear()

        # 归零 shape key 并清除动画
        reset_shape_keys(ob, 0.0)
        clear_shape_key_animation(ob)

        # 彻底清除动画数据
        if ob.animation_data:
            ob.animation_data_clear()
        clear_shape_key_animation(ob)

    bpy.ops.object.select_all(action='DESELECT')


def clear_all_keyframe_preserve_drivers(collection_names=None,
                                        exclude_names=None, suffix="") -> None:
    """清除关键帧但保留驱动器（备份 → 清空 → 恢复）。

    用于需要保留目标物体（如 Tar 开头物体）上驱动器的场景。
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

        driver_backups = []
        shape_key_driver_backups = []

        # 阶段 1: 备份驱动器
        if ob.animation_data and ob.animation_data.drivers:
            for fcurve in ob.animation_data.drivers:
                driver_backups.append({
                    'data_path': fcurve.data_path,
                    'array_index': fcurve.array_index,
                    'driver': backup_driver(fcurve.driver)
                })

        if hasattr(ob.data, "shape_keys") and ob.data.shape_keys:
            if ob.data.shape_keys.animation_data and ob.data.shape_keys.animation_data.drivers:
                for fcurve in ob.data.shape_keys.animation_data.drivers:
                    shape_key_driver_backups.append({
                        'data_path': fcurve.data_path,
                        'array_index': fcurve.array_index,
                        'driver': backup_driver(fcurve.driver)
                    })

        # 阶段 2: 清空所有动画数据
        ob.animation_data_clear()
        if hasattr(ob.data, "shape_keys") and ob.data.shape_keys:
            ob.data.shape_keys.animation_data_clear()
            for shape_key_block in ob.data.shape_keys.key_blocks:
                shape_key_block.value = 0.0

        # 阶段 3: 恢复备份的驱动器
        if driver_backups:
            if not ob.animation_data:
                ob.animation_data_create()
            for driver_backup in driver_backups:
                fcurve = ob.driver_add(
                    driver_backup['data_path'], driver_backup['array_index'])
                restore_driver(fcurve.driver, driver_backup['driver'])

        if shape_key_driver_backups and hasattr(ob.data, "shape_keys") and ob.data.shape_keys:
            if not ob.data.shape_keys.animation_data:
                ob.data.shape_keys.animation_data_create()
            for driver_backup in shape_key_driver_backups:
                fcurve = ob.data.shape_keys.driver_add(
                    driver_backup['data_path'], driver_backup['array_index'])
                restore_driver(fcurve.driver, driver_backup['driver'])

    bpy.ops.object.select_all(action='DESELECT')
