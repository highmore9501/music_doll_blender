# fret_dance/animation.py
"""FretDance 乐器模块 —— 动画生成（迁移自 fret_dance_blender/make_animation.py）

通用动画工具（fcurve/shape key/driver）改调 common.animation_utils。
"""

import json

import bpy  # type: ignore

from ..common import performer_utils
from ..common import animation_utils


def clear_all_keyframe(collection_names=None, exclude_names=None, suffix=""):
    """清除关键帧（集合名自动按演奏者后缀解析）"""
    animation_utils.clear_all_keyframe(collection_names, exclude_names, suffix)


def get_or_create_fcurve(datablock, data_path, index=0):
    """在 datablock 的动画 action 中查找或创建一条 fcurve（Blender 4.x/5.x 兼容）"""
    return animation_utils.get_or_create_fcurve(datablock, data_path, index)


def write_fcurve_points(fcurve, keyframes, clear_existing=True):
    """批量写入 fcurve 的关键帧点"""
    animation_utils.write_fcurve_points(fcurve, keyframes, clear_existing)


def animate_hand(animation_file: str, suffix: str = ""):
    """根据手部动画数据批量写入控制器 transform 关键帧（位置 + 四元数旋转）"""
    with open(animation_file, "r") as f:
        handDicts = json.load(f)

    # 第一步：按控制器收集每一帧的数据（保持帧序），并做四元数符号一致性处理
    object_data = {}
    previous_quaternions = {}

    for hand_data in handDicts:
        frame = int(hand_data["frame"])
        fingerInfos = hand_data["fingerInfos"]

        for controller_name, value in fingerInfos.items():
            full_name = performer_utils.resolve(controller_name, suffix)
            if full_name not in bpy.data.objects:
                print(f"警告: 控制器 {full_name} 不存在于场景中")
                continue

            entry = object_data.setdefault(full_name, {"frames": []})
            entry.setdefault("locations", []).append(value["position"])
            quat = list(value["rotation"])

            if full_name in previous_quaternions:
                dot = sum(
                    a * b for a, b in zip(previous_quaternions[full_name], quat))
                if dot < 0:
                    quat = [-x for x in quat]
            previous_quaternions[full_name] = quat

            entry.setdefault("quats", []).append(quat)
            entry["frames"].append(frame)

    # 第二步：为每个控制器准备 fcurve
    for obj_name, entry in object_data.items():
        obj = bpy.data.objects[obj_name]

        if not obj.animation_data:
            obj.animation_data_create()
        if not obj.animation_data.action:
            obj.animation_data.action = bpy.data.actions.new(
                f"{obj_name}_anim")

        if "locations" in entry:
            entry["location_fcurves"] = [
                get_or_create_fcurve(obj, "location", index=i)
                for i in range(3)]
        if "quats" in entry:
            obj.rotation_mode = 'QUATERNION'
            entry["quat_fcurves"] = [
                get_or_create_fcurve(obj, "rotation_quaternion", index=i)
                for i in range(4)]

    # 第三步：批量写入所有控制器的关键帧
    for obj_name, entry in object_data.items():
        frames = entry["frames"]

        if "location_fcurves" in entry:
            for i, fcurve in enumerate(entry["location_fcurves"]):
                values = [loc[i] for loc in entry["locations"]]
                write_fcurve_points(fcurve, zip(frames, values))

        if "quat_fcurves" in entry:
            for i, fcurve in enumerate(entry["quat_fcurves"]):
                values = [quat[i] for quat in entry["quats"]]
                write_fcurve_points(fcurve, zip(frames, values))

    print(f"手部动画已成功从 {animation_file} 生成")


def clear_controller_root_animation(suffix: str = ""):
    """清除吉他偏移动画：清空 controller_root_offset 的偏移关键帧并复位为中性值。

    对齐 Unreal 的 MakeControllerRootAnimation：controller_root_offset 是
    controller_root 下的偏移节点，吉他所挂其上，偏移量归零即回到初始姿态。
    """
    obj_name = performer_utils.resolve("controller_root_offset", suffix)
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        print(f"警告: 控制器 {obj_name} 不存在于场景中")
        return
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    if obj.animation_data:
        obj.animation_data_clear()


def animate_controller_root(animation_file: str, suffix: str = ""):
    """根据吉他偏移数据批量写入 controller_root_offset 的位置 + 四元数旋转关键帧。

    对齐 Unreal 的 MakeControllerRootAnimation：JSON 数组每帧解析
    fingerInfos.controller_root 的 position（3 值）与 rotation（四元数 4 值），
    写入对象是 controller_root_offset_<后缀>（吉他所挂的偏移节点）。
    """
    obj_name = performer_utils.resolve("controller_root_offset", suffix)
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        print(f"警告: 控制器 {obj_name} 不存在于场景中")
        return

    with open(animation_file, "r") as f:
        rootDicts = json.load(f)

    # 第一步：按帧收集 controller_root 数据（保持帧序），并做四元数符号一致性处理
    frames = []
    locations = []
    quats = []
    previous_quaternion = None

    for item in rootDicts:
        frame = int(item["frame"])
        fingerInfos = item.get("fingerInfos") or {}
        root_data = fingerInfos.get("controller_root")
        if not root_data:
            continue

        frames.append(frame)
        locations.append(list(root_data.get("position", [0.0, 0.0, 0.0])))

        quat = list(root_data.get("rotation", [1.0, 0.0, 0.0, 0.0]))
        if previous_quaternion is not None:
            dot = sum(a * b for a, b in zip(previous_quaternion, quat))
            if dot < 0:
                quat = [-x for x in quat]
        previous_quaternion = quat
        quats.append(quat)

    if not frames:
        print(f"警告: {animation_file} 中没有 controller_root 数据")
        return

    # 第二步：准备 fcurve（位置 + 四元数旋转）
    if not obj.animation_data:
        obj.animation_data_create()
    if not obj.animation_data.action:
        obj.animation_data.action = bpy.data.actions.new(f"{obj_name}_anim")

    obj.rotation_mode = 'QUATERNION'
    location_fcurves = [
        get_or_create_fcurve(obj, "location", index=i) for i in range(3)]
    quat_fcurves = [
        get_or_create_fcurve(obj, "rotation_quaternion", index=i)
        for i in range(4)]

    # 第三步：批量写入所有关键帧
    for i, fcurve in enumerate(location_fcurves):
        values = [loc[i] for loc in locations]
        write_fcurve_points(fcurve, zip(frames, values))

    for i, fcurve in enumerate(quat_fcurves):
        values = [quat[i] for quat in quats]
        write_fcurve_points(fcurve, zip(frames, values))

    print(f"吉他偏移动画已成功从 {animation_file} 生成")


def _collect_string_objects(instrument=None, suffix=""):
    """收集带弦 shape key 的物体（弦动画作用域）。

    - instrument 不为空：乐器物体本身 + 其子级 + 所在集合（含子集合）里的物体；
    - 否则有 suffix：按对象名后缀过滤；
    - 否则：全场景扫描（兼容旧场景）。
    """
    def has_string_shape_keys(obj):
        if not obj or obj.type != 'MESH':
            return False
        if not obj.data.shape_keys:
            return False
        for key_block in obj.data.shape_keys.key_blocks:
            if "fret" in key_block.name and "s" in key_block.name:
                return True
        return False

    result = []
    seen = set()

    def consider(obj):
        if obj is None or id(obj) in seen:
            return
        seen.add(id(obj))
        if has_string_shape_keys(obj):
            result.append(obj)

    if instrument is not None:
        consider(instrument)
        for child in instrument.children_recursive:
            consider(child)
        for coll in instrument.users_collection:
            for obj in coll.objects:
                consider(obj)
            for sub in coll.children_recursive:
                for obj in sub.objects:
                    consider(obj)
    elif suffix:
        for obj in bpy.data.objects:
            if obj.name.endswith("_" + suffix):
                consider(obj)
    else:
        for obj in bpy.data.objects:
            consider(obj)
    return result


def animate_string(string_recorder: str, suffix: str = "", instrument=None):
    """根据弦动画数据批量写入 shape key 与 is_vib 属性关键帧"""
    string_objects = _collect_string_objects(instrument, suffix)

    print(f"Found {len(string_objects)} string objects")

    shape_key_map = {}
    for string_obj in string_objects:
        for key_block in string_obj.data.shape_keys.key_blocks:
            shape_key_map.setdefault(key_block.name, (string_obj, key_block))

    bpy.context.scene.frame_set(0)  # 从第0帧开始动画，否则会出现插值问题

    with open(string_recorder, "r") as f:
        stringDicts = json.load(f)

    steps = len(stringDicts)

    shape_data = {}
    is_vib_data = {}

    for i in range(steps):
        item = stringDicts[i]
        if item["frame"] is None:
            continue

        if i % 100 == 0:
            print(f"processing step {i}/{steps}")

        frame = int(item["frame"])
        stringIndex = item["stringIndex"]
        fret = item["fret"]
        influence = item["influence"]
        is_up_direction = item.get("isUpDirection", True)

        shape_key_name = f's{stringIndex}fret{fret}'
        direction_shape_key_name = f'{shape_key_name}up' if is_up_direction else f'{shape_key_name}down'

        target = shape_key_map.get(direction_shape_key_name)
        if target is None:
            target = shape_key_map.get(shape_key_name)
        if target is None:
            continue

        target_object, target_shape_key = target

        entry = shape_data.setdefault(
            (target_object.name, target_shape_key.name),
            {"shape_key": target_shape_key, "frames": [], "values": []})
        entry["frames"].append(frame)
        entry["values"].append(influence)

        if "is_vib" in target_object:
            vib_entry = is_vib_data.setdefault(
                target_object.name, {"frames": [], "values": []})
            vib_entry["frames"].append(frame)
            vib_entry["values"].append(influence)

    # 第二步：批量写入所有 shape key 的关键帧
    for (obj_name, shape_key_name), entry in shape_data.items():
        obj = bpy.data.objects[obj_name]
        shape_keys = obj.data.shape_keys

        if not shape_keys.animation_data:
            shape_keys.animation_data_create()
        if not shape_keys.animation_data.action:
            shape_keys.animation_data.action = bpy.data.actions.new(
                f"{obj_name}_string_shape_keys")

        shape_key = entry["shape_key"]
        shape_fcurve = get_or_create_fcurve(
            shape_keys, f'key_blocks["{shape_key.name}"].value')

        frames = entry["frames"]
        values = entry["values"]
        write_fcurve_points(shape_fcurve, zip(frames, values))

    # 第三步：批量写入所有 is_vib 属性的关键帧
    for obj_name, entry in is_vib_data.items():
        obj = bpy.data.objects[obj_name]

        if not obj.animation_data:
            obj.animation_data_create()
        if not obj.animation_data.action:
            obj.animation_data.action = bpy.data.actions.new(
                f"{obj_name}_is_vib")

        vib_fcurve = get_or_create_fcurve(obj, '["is_vib"]')

        frames = entry["frames"]
        values = entry["values"]
        write_fcurve_points(vib_fcurve, zip(frames, values))

    print(f"弦动画已成功从 {string_recorder} 生成")


def clear_string_animation(suffix: str = "", instrument=None):
    """查找场景中带有特定 shape key 的物体列表，并清理这些物体上所有 shape key 的关键帧。

    返回包含目标 shape key 的物体名称列表。
    """
    objects_with_shape_keys = set()

    index = 0
    while True:
        shape_key_names = [
            f"s{index}fret20",
            f"s{index}fret20up",
            f"s{index}fret20down"
        ]

        found = False

        for obj in _collect_string_objects(instrument, suffix):
            if obj.data and hasattr(obj.data, 'shape_keys') and obj.data.shape_keys:
                for shape_key_name in shape_key_names:
                    if shape_key_name in obj.data.shape_keys.key_blocks:
                        objects_with_shape_keys.add(obj.name)
                        found = True
                        break

        if not found:
            break

        index += 1

    for obj_name in objects_with_shape_keys:
        obj = bpy.data.objects.get(obj_name)
        if obj and obj.data and hasattr(obj.data, 'shape_keys') and obj.data.shape_keys:
            for shape_key_block in obj.data.shape_keys.key_blocks:
                shape_key_block.value = 0.0

            if obj.data.shape_keys.animation_data:
                obj.data.shape_keys.animation_data_clear()

        if obj and "is_vib" in obj:
            obj["is_vib"] = 0.0
            if obj.animation_data and obj.animation_data.action:
                fc = animation_utils.get_or_create_fcurve(obj, '["is_vib"]')
                if fc is not None:
                    fc.keyframe_points.clear()
                    fc.update()

    if not objects_with_shape_keys:
        raise RuntimeError("找不到带有弦动画的物体")

    return list(objects_with_shape_keys)
