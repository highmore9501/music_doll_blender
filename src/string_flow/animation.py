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
    names = [f"H_{letter}", f"HP_{letter}", f"T_{letter}", f"TP_{letter}"]
    for n in range(1, config.one_hand_finger_number + 1):
        names.append(f"{n}_{letter}")
        names.append(f"pole_{n}_{letter}")
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

def clear_string_shape_key_animation(instrument) -> None:
    """清除目标乐器（四根弦已合并进该物体）上已有的 shape key 动画（只清除动画，保留 shape key）

    instrument: 目标乐器物体（MusicDoll 属性：场景 md_target_instrument /
    演奏者登记的 target_instrument）；弦 shape key 全部位于它上面。
    """
    if instrument is None:
        return
    if not hasattr(instrument.data, "shape_keys") or not instrument.data.shape_keys:
        return
    # 首先归零所有 shape key 的值（保留 Basis）
    for shape_key_block in instrument.data.shape_keys.key_blocks:
        if shape_key_block.name != "Basis":
            shape_key_block.value = 0.0
    # 清除 shape key 动画数据
    if instrument.data.shape_keys.animation_data:
        instrument.data.shape_keys.animation_data_clear()
    # 清除 shape key 上的驱动（保留 Basis）
    for shape_key in instrument.data.shape_keys.key_blocks:
        if shape_key.name != "Basis":
            shape_key.driver_remove("value")


def apply_string_animation(string_animation_file: str, suffix: str = "",
                           instrument=None) -> dict:
    """应用弦动画到目标乐器物体（四根弦已合并进该物体），批量写 shape key 关键帧。

    Rust 端输出结构：{"strings": [{"shape_key_name": "s0fret5", "keyframes": [...]}]}
    shape key 全部位于目标乐器上（MusicDoll 属性：场景 md_target_instrument /
    演奏者登记的 target_instrument），直接按名字在乐器上查找；f0/f1 结尾的跳过。

    instrument 为空时按 suffix 从演奏者登记信息解析（get_performer(suffix).target_instrument）。

    返回统计字典（供调用方判断是否真正写入了动画）：
    {"shape_keys": 实际写入的 shape key 数量, "keyframes": 写入的关键帧总数,
     "total_entries": 文件数据条目数,
     "skipped_f0f1": 跳过品格0/1 的条数, "skipped_no_instrument": 未找到目标乐器的条数,
     "skipped_no_shape_keys": 乐器上没有 shape key 数据的条数,
     "skipped_no_shape_key": 乐器上未找到对应 shape key 的条数}
    """
    # 目标乐器：优先显式传入，其次按后缀从演奏者登记信息解析
    if instrument is None:
        performer = performer_utils.get_performer(suffix)
        if performer is not None:
            instrument = performer.target_instrument

    instrument_name = instrument.name if instrument is not None else "（未找到目标乐器）"

    # 清除现有动画
    clear_string_shape_key_animation(instrument)

    with open(string_animation_file, 'r', encoding='utf-8') as f:
        string_animation_data = json.load(f)

    strings_data = string_animation_data.get("strings") or []
    total_entries = len(strings_data)

    # 跳过原因统计
    skipped_f0f1 = 0
    skipped_no_instrument = 0
    skipped_no_shape_keys = 0
    skipped_no_shape_key = 0

    # 目标乐器的 shape key 块（仅在乐器存在且有 shape key 数据时解析）
    key_blocks = None
    if instrument is not None and hasattr(instrument.data, "shape_keys") \
            and instrument.data.shape_keys:
        key_blocks = instrument.data.shape_keys.key_blocks

    # 第一步：预先解析 shape key 名称 -> shape key 的映射，避免逐帧重复扫描
    shape_key_map = {}
    for string_data in strings_data:
        shape_key_name = string_data["shape_key_name"]

        # 品格为 0 或 1 的跳过
        if shape_key_name.endswith("f0") or shape_key_name.endswith("f1"):
            skipped_f0f1 += 1
            continue

        if instrument is None:
            skipped_no_instrument += 1
            continue
        if key_blocks is None:
            skipped_no_shape_keys += 1
            continue

        shape_key = key_blocks.get(shape_key_name)
        if not shape_key:
            skipped_no_shape_key += 1
            print(f"未找到shape key: {shape_key_name}")
            continue

        shape_key_map.setdefault(shape_key_name, shape_key)

    # 第二步：按 shape key 收集每一帧的数据
    shape_data = {}
    for string_data in strings_data:
        shape_key_name = string_data["shape_key_name"]
        if shape_key_name not in shape_key_map:
            continue

        shape_key = shape_key_map[shape_key_name]
        entry = shape_data.setdefault(
            shape_key_name,
            {"shape_key": shape_key, "frames": [], "values": []})

        for keyframe in string_data["keyframes"]:
            entry["frames"].append(int(keyframe["frame"]))
            entry["values"].append(keyframe["shape_key_value"])

    # 第三步：批量写入所有 shape key 的关键帧
    for shape_key_name, entry in shape_data.items():
        shape_keys = instrument.data.shape_keys

        if not shape_keys.animation_data:
            shape_keys.animation_data_create()
        if not shape_keys.animation_data.action:
            shape_keys.animation_data.action = bpy.data.actions.new(
                f"{instrument_name}_string_shape_keys")

        shape_fcurve = get_or_create_fcurve(
            shape_keys, f'key_blocks["{shape_key_name}"].value')

        write_fcurve_points(shape_fcurve, zip(entry["frames"], entry["values"]))

    # 汇总统计与日志
    written_shape_keys = len(shape_data)
    written_keyframes = sum(len(entry["frames"]) for entry in shape_data.values())

    print("\n=== 弦动画写入统计 ===")
    print(f"目标乐器: {instrument_name}")
    print(f"数据条目: 共 {total_entries} 条"
          f"（跳过品格0/1: {skipped_f0f1}, 未找到目标乐器: {skipped_no_instrument}, "
          f"乐器无shape key: {skipped_no_shape_keys}, "
          f"未找到shape key: {skipped_no_shape_key}）")
    for shape_key_name, entry in sorted(shape_data.items()):
        print(f"  • {instrument_name} / {shape_key_name}: {len(entry['frames'])} 个关键帧")
    print(f"共写入 {written_shape_keys} 个 shape key, {written_keyframes} 个关键帧")

    if written_shape_keys == 0:
        print("警告: 没有写入任何 shape key 关键帧，弦动画未生成！")
        print("可能原因: ① string_animation_file 数据为空或全部为品格0/1；"
              "② 未找到目标乐器（请在「角色操作」面板设置目标乐器，或确认演奏者已登记乐器）；"
              "③ 目标乐器上没有 shape key（请先生成 shape key）；"
              "④ 目标乐器上的 shape key 名字与文件不一致（当前后缀: "
              + (suffix or "（空）") + "）。")
    else:
        print(f"弦动画已成功从 {string_animation_file} 生成")

    return {
        "shape_keys": written_shape_keys,
        "keyframes": written_keyframes,
        "total_entries": total_entries,
        "skipped_f0f1": skipped_f0f1,
        "skipped_no_instrument": skipped_no_instrument,
        "skipped_no_shape_keys": skipped_no_shape_keys,
        "skipped_no_shape_key": skipped_no_shape_key,
    }
