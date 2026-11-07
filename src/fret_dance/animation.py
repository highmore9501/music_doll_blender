# fret_dance/animation.py
"""FretDance 乐器模块 —— 动画生成（迁移自 fret_dance_blender/make_animation.py）

通用动画工具（fcurve/shape key/driver）改调 common.animation_utils。
"""

import json
import os

import bpy  # type: ignore

from ..common import performer_utils
from ..common import animation_utils


def clear_all_keyframe(collection_names=None, exclude_names=None, suffix=""):
    """清除关键帧（集合名自动按演奏者后缀解析）"""
    animation_utils.clear_all_keyframe(collection_names, exclude_names, suffix)


def clear_all_keyframe_preserve_drivers(collection_names=None, exclude_names=None,
                                        suffix=""):
    """清除关键帧但保留驱动器（只摘 action / NLA，不碰 driver）

    生成动画前的清理一律走这里：不管物体属不属于控件体系，只要它挂着 driver，
    都原样保留（例如 ext 辅助控件的位置驱动）。
    """
    animation_utils.clear_all_keyframe_preserve_drivers(
        collection_names, exclude_names, suffix)


def get_or_create_fcurve(datablock, data_path, index=0):
    """在 datablock 的动画 action 中查找或创建一条 fcurve（Blender 4.x/5.x 兼容）"""
    return animation_utils.get_or_create_fcurve(datablock, data_path, index)


def get_or_create_action(datablock, action_name):
    """取得 datablock 的动画动作（同名优先复用，避免每次插帧多留一份动作）"""
    return animation_utils.get_or_create_action(datablock, action_name)


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
        get_or_create_action(obj, f"{obj_name}_anim")

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
    animation_utils.clear_animation_preserve_drivers(obj)


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
    get_or_create_action(obj, f"{obj_name}_anim")

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


# ── 弦与摇把的 shape key 动画 ─────────────────────────────────
#
# 弦振动与摇把形变在同一个物体上 —— MusicDoll 的「目标乐器」属性所指的那个物体。
# 两份数据各自带帧号，先各自读成逐通道的关键帧，再合成一张通道表，最后一次性
# 写进这个物体：一个物体的 shape key 只能挂一条动作，分两次写会把先写的那份顶掉。

#: 摇把形变的两个通道名，与 Rust 端输出字段同名
VIBRATO_SHAPE_KEY_NAMES = ("vibrato_up", "vibrato_down")


def _resolve_instrument(suffix: str = "", instrument=None):
    """目标乐器：优先显式传入，其次按演奏者后缀从登记信息解析。"""
    if instrument is not None:
        return instrument
    if suffix:
        performer = performer_utils.get_performer(suffix)
        if performer is not None:
            return performer.target_instrument
    return None


def _string_shape_key_candidates(string_index: int, fret: int, is_up_direction: bool):
    """一个拨弦事件可能对应的两个 shape key 名：带方向后缀的、不带方向的。

    弦的 shape key 建出来时带 up / down 后缀；更早的场景里只有不带方向的那一个，
    所以按顺序试，谁在乐器上就用谁。
    """
    base_name = f"s{string_index}fret{fret}"
    direction_suffix = "up" if is_up_direction else "down"
    return (f"{base_name}{direction_suffix}", base_name)


def _append_channel_value(channels: dict, shape_key_name: str, frame, value) -> None:
    """把一个关键帧追加到对应通道（没有该通道就先建一条）。"""
    entry = channels.setdefault(shape_key_name, {"frames": [], "values": []})
    entry["frames"].append(frame)
    entry["values"].append(value)


def _read_string_channels(instrument, string_recorder: str):
    """读弦振动数据，按目标乐器上真实存在的 shape key 归成逐通道的关键帧。

    返回 `(通道表, is_vib 帧表, is_vib 值表, 没有对应 shape key 的事件数)`。
    """
    with open(string_recorder, "r", encoding="utf-8") as file:
        string_records = json.load(file)

    key_blocks = instrument.data.shape_keys.key_blocks
    channels = {}
    is_vib_frames = []
    is_vib_values = []
    unmatched_events = 0

    for record in string_records:
        frame = record.get("frame")
        if frame is None:
            continue

        string_index = int(record.get("stringIndex", 0))
        fret = int(record.get("fret", 0))
        influence = float(record.get("influence", 0.0))
        is_up_direction = bool(record.get("isUpDirection", True))

        shape_key_name = None
        for candidate_name in _string_shape_key_candidates(
                string_index, fret, is_up_direction):
            if candidate_name in key_blocks:
                shape_key_name = candidate_name
                break
        if shape_key_name is None:
            unmatched_events += 1
            continue

        _append_channel_value(channels, shape_key_name, int(frame), influence)
        # 弦在不在振动这个自定义属性跟着弦的那一路走（不在 shape key 上）
        is_vib_frames.append(int(frame))
        is_vib_values.append(influence)

    return channels, is_vib_frames, is_vib_values, unmatched_events


def _merge_vibrato_channels(instrument, channels: dict,
                            vibrato_shape_key_file: str) -> int:
    """读摇把 shape key 数据，并进同一张通道表；返回并入的帧数。"""
    if not vibrato_shape_key_file:
        return 0
    if not os.path.exists(vibrato_shape_key_file):
        print(f"警告: 摇把 shape key 文件不存在，跳过: {vibrato_shape_key_file}")
        return 0

    with open(vibrato_shape_key_file, "r", encoding="utf-8") as file:
        vibrato_records = json.load(file)

    key_blocks = instrument.data.shape_keys.key_blocks
    available_names = [
        name for name in VIBRATO_SHAPE_KEY_NAMES if name in key_blocks]
    if not available_names:
        print(f"警告: 目标乐器 {instrument.name} 上没有 vibrato_up / "
              f"vibrato_down，跳过摇把形变")
        return 0

    merged_frames = 0
    for record in vibrato_records:
        frame = record.get("frame")
        if frame is None:
            continue
        for shape_key_name in available_names:
            _append_channel_value(
                channels, shape_key_name, float(frame),
                float(record.get(shape_key_name, 0.0)))
        merged_frames += 1

    return merged_frames


def _write_shape_key_channels(instrument, channels: dict) -> int:
    """把合并后的通道表一次写进目标乐器的 shape key 动作（所有通道共用一条动作）。"""
    if not channels:
        return 0

    shape_keys = instrument.data.shape_keys
    if not shape_keys.animation_data:
        shape_keys.animation_data_create()
    get_or_create_action(shape_keys, f"{instrument.name}_string_shape_keys")

    written_keyframes = 0
    for shape_key_name in sorted(channels):
        entry = channels[shape_key_name]
        shape_fcurve = get_or_create_fcurve(
            shape_keys, f'key_blocks["{shape_key_name}"].value')
        if shape_fcurve is None:
            continue
        write_fcurve_points(shape_fcurve, zip(entry["frames"], entry["values"]))
        written_keyframes += len(entry["frames"])
        print(
            f"  • {instrument.name} / {shape_key_name}: "
            f"{len(entry['frames'])} 个关键帧")

    return written_keyframes


def _write_is_vib_animation(instrument, frames, values) -> None:
    """把「弦在不在振动」写到物体自己的属性动画上（乐器上没有这个属性就跳过）。"""
    if not frames or "is_vib" not in instrument:
        return

    if not instrument.animation_data:
        instrument.animation_data_create()
    get_or_create_action(instrument, f"{instrument.name}_is_vib")

    vib_fcurve = get_or_create_fcurve(instrument, '["is_vib"]')
    write_fcurve_points(vib_fcurve, zip(frames, values))


def animate_string(string_recorder: str, vibrato_shape_key_file: str = "",
                   suffix: str = "", instrument=None) -> dict:
    """把弦振动与摇把形变合成一份，一次写入目标乐器的 shape key 动画。

    目标乐器取 MusicDoll 的「目标乐器」属性（场景 md_target_instrument，或演奏者
    登记的 target_instrument）：弦与摇把的 shape key 都位于这个物体上，不再按
    shape key 名字满场景找物体。

    返回统计字典：`{"shape_keys": 通道数, "keyframes": 关键帧总数,
    "vibrato_frames": 摇把帧数, "unmatched_events": 没对上 shape key 的弦事件数}`。
    """
    target_instrument = _resolve_instrument(suffix, instrument)
    if target_instrument is None:
        raise RuntimeError(
            "未找到目标乐器：请先在「角色操作」面板指定目标乐器")
    if not getattr(target_instrument.data, "shape_keys", None):
        raise RuntimeError(f"目标乐器 {target_instrument.name} 上没有 shape key")

    clear_string_animation(instrument=target_instrument)

    # 第一步：弦振动 → 逐通道关键帧
    channels, is_vib_frames, is_vib_values, unmatched_events = (
        _read_string_channels(target_instrument, string_recorder))
    # 第二步：摇把 → 并进同一张通道表
    vibrato_frames = _merge_vibrato_channels(
        target_instrument, channels, vibrato_shape_key_file)
    # 第三步：一次写入（弦与摇把共用同一条动作）
    written_keyframes = _write_shape_key_channels(target_instrument, channels)
    _write_is_vib_animation(target_instrument, is_vib_frames, is_vib_values)

    print("\n=== 弦与摇把动画写入统计 ===")
    print(f"目标乐器: {target_instrument.name}")
    print(f"通道: {len(channels)} 个；关键帧: {written_keyframes} 个"
          f"（摇把 {vibrato_frames} 帧）")
    if unmatched_events:
        print(f"没对上 shape key 的弦事件: {unmatched_events} 条")

    if not written_keyframes:
        print("警告: 没有写入任何 shape key 关键帧，弦动画未生成！")
        print("可能原因: ① 弦振动文件为空；"
              "② 乐器上还没有弦 / 摇把的 shape key；"
              "③ shape key 名字与文件里的不一致（当前后缀: "
              + (suffix or "（空）") + "）。")
    else:
        print(f"弦与摇把动画已成功从 {string_recorder} 生成")

    return {
        "shape_keys": len(channels),
        "keyframes": written_keyframes,
        "vibrato_frames": vibrato_frames,
        "unmatched_events": unmatched_events,
    }


def clear_string_animation(instrument=None, suffix: str = "") -> list:
    """清除目标乐器上弦与摇把的 shape key 动画（保留 shape key 本身与驱动器）。

    返回被清理的物体名（找不到目标乐器时为空列表）。
    """
    target_instrument = _resolve_instrument(suffix, instrument)
    if target_instrument is None:
        return []

    shape_keys = getattr(target_instrument.data, "shape_keys", None)
    if not shape_keys:
        return []

    for shape_key_block in shape_keys.key_blocks:
        shape_key_block.value = 0.0
    animation_utils.clear_animation_and_discard(shape_keys)

    if "is_vib" in target_instrument:
        target_instrument["is_vib"] = 0.0
        if target_instrument.animation_data and target_instrument.animation_data.action:
            vib_fcurve = animation_utils.get_or_create_fcurve(
                target_instrument, '["is_vib"]')
            if vib_fcurve is not None:
                vib_fcurve.keyframe_points.clear()
                vib_fcurve.update()

    return [target_instrument.name]
