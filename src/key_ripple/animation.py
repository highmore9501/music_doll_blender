# key_ripple/animation.py
"""KeyRipple 乐器模块 —— 动画生成（迁移自 key_ripple_blender/make_animation/make_animation.py）

通用动画工具（fcurve/shape key/driver/clear）改调 common.animation_utils。
"""

import json
import os
import re

import bpy  # type: ignore

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


def make_animation(animation_file_path: str, suffix: str = ""):
    """根据动画数据批量写入物体 transform 关键帧（位置 + 四元数旋转）。

    suffix: 演奏者后缀；JSON 里的短名会自动解析成 <短名>_<后缀>
    """
    try:
        with open(animation_file_path, 'r') as f:
            animation_data = json.load(f)
    except Exception as e:
        print(f"无法读取动画文件: {e}")
        return

    from ..common import performer_utils

    # 第一步：按物体收集每一帧的数据（保持帧序），并做四元数符号一致性处理
    object_data = {}
    previous_quaternions = {}

    for frame_data in animation_data:
        frame = int(frame_data.get("frame", 0))
        if frame < 0:
            continue
        hand_infos = frame_data.get("hand_infos", {})

        for short_name, transform_data in hand_infos.items():
            obj_name = performer_utils.resolve(short_name, suffix)
            if obj_name not in bpy.data.objects:
                print(f"警告: 物体 {obj_name} 不存在于场景中")
                continue

            data_len = len(transform_data)
            entry = object_data.setdefault(obj_name, {"frames": []})

            if data_len == 7:
                # 合并格式 [x, y, z, w, i, j, k] → 位置 + 四元数旋转
                entry.setdefault("locations", []).append(transform_data[:3])
                quat = list(transform_data[3:])

                if obj_name in previous_quaternions:
                    dot = sum(
                        a * b for a, b in zip(previous_quaternions[obj_name], quat))
                    if dot < 0:
                        quat = [-x for x in quat]
                previous_quaternions[obj_name] = quat

                entry.setdefault("quats", []).append(quat)
                entry["frames"].append(frame)

            elif data_len == 4:
                # 旧格式兼容：纯四元数旋转 (w, x, y, z)
                quat = list(transform_data)

                if obj_name in previous_quaternions:
                    dot = sum(
                        a * b for a, b in zip(previous_quaternions[obj_name], quat))
                    if dot < 0:
                        quat = [-x for x in quat]
                previous_quaternions[obj_name] = quat

                entry.setdefault("quats", []).append(quat)
                entry["frames"].append(frame)

            elif data_len == 3:
                # 位置数据 [x, y, z]
                entry.setdefault("locations", []).append(transform_data[:3])
                entry["frames"].append(frame)

            else:
                print(f"警告: 物体 {obj_name} 的数据维度 {data_len} 无法识别")
                continue

    # 第二步：为每个物体准备 fcurve
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

    # 第三步：批量写入所有物体的关键帧
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

    print(f"动画已成功从 {animation_file_path} 生成")


def extract_key_index(shape_key_name):
    """从shape key名称中提取键索引，例如: "key_21_pressed" -> "21" """
    numbers = re.findall(r'\d+', shape_key_name)
    if not numbers:
        return None
    return numbers[0]


def build_material_index_map(obj):
    """一次性建立 键索引 -> 材质 的映射，供批量生成动画时使用"""
    material_by_index = {}
    candidates = [slot.material for slot in obj.material_slots]
    candidates.extend(bpy.data.materials)

    for material in candidates:
        if not material:
            continue
        numbers = re.findall(r'\d+', material.name)
        if numbers and numbers[-1] not in material_by_index:
            material_by_index[numbers[-1]] = material
    return material_by_index


def _prepare_factor_fcurve(material):
    """定位材质中 Mix Shader 节点的 Factor 参数，清理其上遗留的 driver 与旧关键帧，并返回 fcurve"""
    if not material or not material.node_tree:
        print(
            f"警告: 材质 {material.name if material else 'None'} 没有节点树，无法设置 Factor")
        return None

    node_tree = material.node_tree

    factor_node = None
    if node_tree.animation_data and node_tree.animation_data.drivers:
        for driver in node_tree.animation_data.drivers:
            match = re.match(
                r'nodes\["(.+)"\]\.inputs\[(?:".+"|\d+)\]\.default_value$',
                driver.data_path)
            if not match:
                continue
            node = node_tree.nodes.get(match.group(1))
            if node is not None and "Factor" in node.inputs:
                factor_node = node
                break

    if factor_node is None:
        for node in node_tree.nodes:
            if node.type == 'MIX_SHADER' and "Factor" in node.inputs:
                factor_node = node
                break

    if factor_node is None:
        print(f"警告: 材质 {material.name} 上未找到 Mix Shader 节点的 Factor 参数")
        return None

    factor_index = list(factor_node.inputs).index(
        factor_node.inputs["Factor"])
    data_path = f'nodes["{factor_node.name}"].inputs[{factor_index}].default_value'
    name_data_path = f'nodes["{factor_node.name}"].inputs["Factor"].default_value'

    if node_tree.animation_data and node_tree.animation_data.drivers:
        for driver in list(node_tree.animation_data.drivers):
            if driver.data_path in (name_data_path, data_path):
                node_tree.animation_data.drivers.remove(driver)

    if not node_tree.animation_data:
        node_tree.animation_data_create()
    if not node_tree.animation_data.action:
        node_tree.animation_data.action = bpy.data.actions.new(
            f"{material.name}_factor")

    fcurve = get_or_create_fcurve(node_tree, data_path, index=0)
    if fcurve is None:
        print(f"警告: 材质 {material.name} 上无法获取 Factor 的 fcurve")
        return None

    fcurve.keyframe_points.clear()

    return fcurve


def generate_piano_key_animation(piano_key_animation_path: str,
                                 keyboard_obj_name: str = 'keyboard'):
    """根据预先计算好的钢琴键动画数据在Blender中执行插帧操作"""
    try:
        with open(piano_key_animation_path, 'r') as f:
            piano_key_animation_data = json.load(f)
    except Exception as e:
        print(f"无法读取钢琴键动画数据文件: {e}")
        return

    obj = bpy.data.objects.get(keyboard_obj_name)
    if obj is None:
        print(f"错误: 找不到键盘物体 {keyboard_obj_name}")
        return

    if not hasattr(obj.data, "shape_keys") or not obj.data.shape_keys:
        print(f"警告: 物体 {keyboard_obj_name} 没有shape keys")
        return

    shape_keys = obj.data.shape_keys
    key_blocks = shape_keys.key_blocks

    material_by_index = build_material_index_map(obj)

    if not shape_keys.animation_data:
        shape_keys.animation_data_create()
    if not shape_keys.animation_data.action:
        shape_keys.animation_data.action = bpy.data.actions.new(
            f"{keyboard_obj_name}_shape_keys")

    is_pressed_fcurve = None
    if "is_pressed" in obj:
        if not obj.animation_data:
            obj.animation_data_create()
        if not obj.animation_data.action:
            obj.animation_data.action = bpy.data.actions.new(
                f"{obj.name}_key_is_pressed")
        is_pressed_fcurve = get_or_create_fcurve(
            obj, '["is_pressed"]')

    key_infos = []
    for key_data in piano_key_animation_data:
        shape_key_name = key_data["shape_key_name"]
        keyframes = key_data["keyframes"]

        shape_key = key_blocks.get(shape_key_name)
        if shape_key is None:
            print(f"警告: 未找到shape key {shape_key_name}")
            continue

        shape_fcurve = get_or_create_fcurve(
            shape_keys, f'key_blocks["{shape_key_name}"].value')

        factor_fcurve = None
        key_index = extract_key_index(shape_key_name)
        if key_index is not None:
            material = material_by_index.get(key_index)
            if material is not None:
                factor_fcurve = _prepare_factor_fcurve(material)
            else:
                print(f"警告: 未找到与 shape key {shape_key_name} 对应的材质，无法驱动发光")
        else:
            print(f"警告: 无法从 shape key {shape_key_name} 中提取键索引，无法驱动发光")

        key_infos.append({
            "shape_key_fcurve": shape_fcurve,
            "factor_fcurve": factor_fcurve,
            "keyframes": keyframes,
        })

    for info in key_infos:
        frames = [float(kf["frame"]) for kf in info["keyframes"]]
        shape_values = [float(kf["shape_key_value"])
                        for kf in info["keyframes"]]

        write_fcurve_points(
            info["shape_key_fcurve"], zip(frames, shape_values))

        if info["factor_fcurve"] is not None:
            write_fcurve_points(
                info["factor_fcurve"], zip(frames, shape_values))

        if is_pressed_fcurve is not None:
            pressed_values = [
                float(kf.get("is_pressed_value", 0.0))
                for kf in info["keyframes"]]
            write_fcurve_points(
                is_pressed_fcurve, zip(frames, pressed_values))

    print(f"钢琴键动画已成功从 {piano_key_animation_path} 生成")


def make_animation_from_keyripple(keyripple_file_path: str,
                                  keyboard_obj_name: str = 'keyboard',
                                  suffix: str = ""):
    """从.keyripple文件生成动画"""
    try:
        with open(keyripple_file_path, 'r') as f:
            keyripple_data = json.load(f)
    except Exception as e:
        print(f"无法读取.keyripple文件: {e}")
        return

    animation_file_path = keyripple_data.get("animation_path")
    piano_key_animation_path = keyripple_data.get("key_animation_path")

    if not animation_file_path or not piano_key_animation_path:
        print("错误: .keyripple文件中缺少必要的路径信息")
        return

    if not os.path.exists(animation_file_path):
        print(f"错误: 动画文件不存在: {animation_file_path}")
        return

    if not os.path.exists(piano_key_animation_path):
        print(f"错误: 钢琴键动画文件不存在: {piano_key_animation_path}")
        return

    # 清除现有动画
    collection_name = ["addons", "keys"]
    clear_all_keyframe(collection_name, suffix=suffix)

    # 生成手部动画
    make_animation(animation_file_path, suffix=suffix)

    # 生成钢琴键动画
    generate_piano_key_animation(piano_key_animation_path, keyboard_obj_name)

    print(f"动画已成功从 {keyripple_file_path} 生成")
