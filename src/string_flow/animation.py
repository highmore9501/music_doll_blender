# string_flow/animation.py
"""StringFlow 乐器模块 —— 动画生成（迁移自 string_flow_blender/make_animation.py）

- 通用 fcurve 工具改调 common.animation_utils（get_or_create_fcurve / write_fcurve_points）；
- 动画 JSON 里的控制器名是短名（Rust 端输出），用 resolve(short, suffix) 映射到带后缀对象；
- 左右手控制器列表按 one_hand_finger_number 动态生成（支持多指/外星人），不再硬编码 4 指；
- 弦动画 shape key 名 s{i}fret{k}（在弦数据内部，无需后缀）；
- 清除控制器动画逐对象 animation_data_clear（动画控制器列表内无 driver 对象，安全）。
"""

import json

import bpy  # type: ignore

from ..common import animation_utils
from ..common import performer_utils

get_or_create_fcurve = animation_utils.get_or_create_fcurve
write_fcurve_points = animation_utils.write_fcurve_points


# ── 左右手动画 ───────────────────────────────────────────────

def _hand_controller_shorts(config, side: str) -> list:
    """该侧全部动画控制器短名：H/HP/T + 全部手指 + pole（+ 右手弓/触弦点）"""
    letter = 'L' if side == 'left' else 'R'
    names = [f"H_{letter}", f"HP_{letter}", f"T_{letter}", f"T_{letter}_pole"]
    for n in range(1, config.one_hand_finger_number + 1):
        names.append(f"{n}_{letter}")
        names.append(f"{n}_{letter}_pole")
    if side == 'right':
        names.append("String_Touch_Point")
        names.append("Bow_Controller")
    return names


def _clear_controller_animation(config, side: str, suffix: str = "") -> None:
    """清除该侧全部控制器的动画数据（列表内无 driver 对象，animation_data_clear 安全）"""
    for short in _hand_controller_shorts(config, side):
        full = performer_utils.resolve(short, suffix)
        obj = bpy.data.objects.get(full)
        if obj is not None and obj.animation_data:
            obj.animation_data_clear()


def _animate_hand_from_file(animation_file_path: str, side: str,
                            config, suffix: str = "") -> None:
    """根据手部动画文件批量写入控制器 transform 关键帧（位置 + 四元数旋转）。

    Rust 端输出的每帧结构：{"frame": ..., "hand_infos": {"H_L": [x,y,z,w,i,j,k] 或 [x,y,z], ...}}
    - 3 元素 = 位置；4 元素 = 四元数 (w,x,y,z)；7 元素 = 位置 + 四元数。
    四元数做符号一致性处理（相邻帧点积 < 0 则取反），避免旋转跳变。
    """
    side_label = '左手' if side == 'left' else '右手'
    print(f"\n=== 生成{side_label}动画 ===")

    _clear_controller_animation(config, side, suffix)

    with open(animation_file_path, 'r', encoding='utf-8') as f:
        animation_data = json.load(f)

    # 第一步：按控制器收集每一帧的数据（保持帧序），并做四元数符号一致性处理
    object_data = {}
    previous_quaternions = {}

    for frame_data in animation_data:
        frame = int(frame_data["frame"])
        hand_infos = frame_data.get("hand_infos") or {}

        for short, values in hand_infos.items():
            full = performer_utils.resolve(short, suffix)
            if full not in bpy.data.objects:
                print(f"警告: 控制器 {full} 不存在于场景中")
                continue

            entry = object_data.setdefault(full, {"frames": []})
            data_len = len(values)

            if data_len == 3:
                entry.setdefault("locations", []).append(list(values[:3]))
                entry["frames"].append(frame)
            elif data_len == 4:
                quat = list(values)
                if full in previous_quaternions:
                    dot = sum(a * b for a, b in zip(
                        previous_quaternions[full], quat))
                    if dot < 0:
                        quat = [-x for x in quat]
                previous_quaternions[full] = quat
                entry.setdefault("quats", []).append(quat)
                entry["frames"].append(frame)
            elif data_len == 7:
                # 合并格式 [x, y, z, w, qx, qy, qz]：前 3 位置，后 4 四元数
                entry.setdefault("locations", []).append(list(values[:3]))
                quat = list(values[3:7])
                if full in previous_quaternions:
                    dot = sum(a * b for a, b in zip(
                        previous_quaternions[full], quat))
                    if dot < 0:
                        quat = [-x for x in quat]
                previous_quaternions[full] = quat
                entry.setdefault("quats", []).append(quat)
                entry["frames"].append(frame)
            else:
                print(f"警告: 控制器 {short} 的数据维度 {data_len} 无法识别")
                continue

    # 第二步：为每个控制器准备 fcurve（位置 3 通道 / 四元数 4 通道）
    for full, entry in object_data.items():
        obj = bpy.data.objects[full]

        if not obj.animation_data:
            obj.animation_data_create()
        if not obj.animation_data.action:
            obj.animation_data.action = bpy.data.actions.new(f"{full}_anim")

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
    for full, entry in object_data.items():
        frames = entry["frames"]

        if "location_fcurves" in entry:
            for i, fcurve in enumerate(entry["location_fcurves"]):
                values = [loc[i] for loc in entry["locations"]]
                write_fcurve_points(fcurve, zip(frames, values))

        if "quat_fcurves" in entry:
            for i, fcurve in enumerate(entry["quat_fcurves"]):
                values = [quat[i] for quat in entry["quats"]]
                write_fcurve_points(fcurve, zip(frames, values))

    print(f"{side_label}动画已成功从 {animation_file_path} 生成")


def make_left_hand_animation(animation_file_path: str, config, suffix: str = "") -> None:
    """根据左手动画文件生成左手控制器动画（含全部手指与 pole）"""
    _animate_hand_from_file(animation_file_path, "left", config, suffix)


def make_right_hand_animation(animation_file_path: str, config, suffix: str = "") -> None:
    """根据右手动画文件生成右手控制器动画（含弓/触弦点/全部手指与 pole）"""
    _animate_hand_from_file(animation_file_path, "right", config, suffix)


# ── 弦动画 ───────────────────────────────────────────────────

def clear_string_shape_key_animation(suffix: str = "") -> None:
    """清除四根弦上已有的 shape key 动画（只清除动画，保留 shape key）"""
    for i in range(4):
        obj = bpy.data.objects.get(performer_utils.resolve(f"string{i}", suffix))
        if obj and obj.data.shape_keys:
            # 首先归零所有 shape key 的值（保留 Basis）
            for shape_key_block in obj.data.shape_keys.key_blocks:
                if shape_key_block.name != "Basis":
                    shape_key_block.value = 0.0
            # 清除 shape key 动画数据
            if obj.data.shape_keys.animation_data:
                obj.data.shape_keys.animation_data_clear()
            # 清除 shape key 上的驱动（保留 Basis）
            for shape_key in obj.data.shape_keys.key_blocks:
                if shape_key.name != "Basis":
                    shape_key.driver_remove("value")


def apply_string_animation(string_animation_file: str, suffix: str = "") -> None:
    """应用弦动画到场景中的弦对象（批量写 shape key 关键帧）。

    Rust 端输出结构：{"strings": [{"shape_key_name": "s0fret5", "keyframes": [...]}]}
    shape_key_name 前缀 s0~s3 映射到 string0~3 对象（带后缀）；f0/f1 结尾的跳过。
    """
    # 清除现有动画
    clear_string_shape_key_animation(suffix)

    with open(string_animation_file, 'r', encoding='utf-8') as f:
        string_animation_data = json.load(f)

    # 第一步：预先解析 shape key 名称 -> (物体, shape key) 的映射，避免逐帧重复扫描
    shape_key_map = {}
    for string_data in string_animation_data["strings"]:
        shape_key_name = string_data["shape_key_name"]

        # 品格为 0 或 1 的跳过
        if shape_key_name.endswith("f0") or shape_key_name.endswith("f1"):
            continue

        # 确定目标弦对象
        target_object = None
        for i in range(4):
            if shape_key_name.startswith(f"s{i}"):
                target_object = bpy.data.objects.get(
                    performer_utils.resolve(f"string{i}", suffix))
                break
        if not target_object or not target_object.data.shape_keys:
            continue

        shape_key = target_object.data.shape_keys.key_blocks.get(shape_key_name)
        if not shape_key:
            print(f"未找到shape key: {shape_key_name}")
            continue

        shape_key_map.setdefault(shape_key_name, (target_object, shape_key))

    # 第二步：按 shape key 收集每一帧的数据
    shape_data = {}
    for string_data in string_animation_data["strings"]:
        shape_key_name = string_data["shape_key_name"]
        if shape_key_name not in shape_key_map:
            continue

        target_object, shape_key = shape_key_map[shape_key_name]
        entry = shape_data.setdefault(
            (target_object.name, shape_key_name),
            {"shape_key": shape_key, "frames": [], "values": []})

        for keyframe in string_data["keyframes"]:
            entry["frames"].append(int(keyframe["frame"]))
            entry["values"].append(keyframe["shape_key_value"])

    # 第三步：批量写入所有 shape key 的关键帧
    for (obj_name, shape_key_name), entry in shape_data.items():
        obj = bpy.data.objects[obj_name]
        shape_keys = obj.data.shape_keys

        if not shape_keys.animation_data:
            shape_keys.animation_data_create()
        if not shape_keys.animation_data.action:
            shape_keys.animation_data.action = bpy.data.actions.new(
                f"{obj_name}_string_shape_keys")

        shape_fcurve = get_or_create_fcurve(
            shape_keys, f'key_blocks["{shape_key_name}"].value')

        write_fcurve_points(shape_fcurve, zip(entry["frames"], entry["values"]))

    print(f"弦动画已成功从 {string_animation_file} 生成")
