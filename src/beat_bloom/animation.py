# beat_bloom/animation.py
"""BeatBloom 乐器模块 —— 动画生成（迁移自 beat_bloom_addon/make_animation.py）

通用动画工具（fcurve / shape key / 清帧）改调 common.animation_utils。
"""

import json

import bpy  # type: ignore

from ..common import performer_utils
from ..common import animation_utils


def clear_all_keyframe(collection_names=None, exclude_names=None, suffix=""):
    """清除关键帧（按演奏者后缀隔离）"""
    animation_utils.clear_all_keyframe(collection_names, exclude_names, suffix)


def make_animation_by_path(animation_path: str, suffix: str = "") -> None:
    """根据动画 JSON 批量写入控件 transform 关键帧（位置 + 四元数旋转）

    animation JSON 结构：
      {
        "left_hand_animation":  [{"frame": N, "position": [...], "rotation": [...], "pivot_position": [...]}, ...],
        "right_hand_animation": [...],
        "left_foot_animation":  [{"frame": N, "position": [...], "rotation": [...]},...],
        "right_foot_animation": [...],
        "head_control_animation": [{"frame": N, "head_control_position": [...]}, ...]  # optional
      }
    """
    with open(animation_path, "r") as f:
        animation_data = json.load(f)

    object_data = {}
    previous_quaternions = {}

    def _add(short, frame, position=None, rotation=None):
        obj_name = performer_utils.resolve(short, suffix)
        if obj_name not in bpy.data.objects:
            print(f"警告: 物体 {obj_name} 不存在于场景中")
            return
        entry = object_data.setdefault(obj_name, {"frames": []})
        if position is not None:
            entry.setdefault("locations", []).append(position[:3])
        if rotation is not None:
            quat = list(rotation)
            if obj_name in previous_quaternions:
                dot = sum(
                    a * b for a, b in zip(previous_quaternions[obj_name], quat))
                if dot < 0:
                    quat = [-x for x in quat]
            previous_quaternions[obj_name] = quat
            entry.setdefault("quats", []).append(quat)
        entry["frames"].append(frame)

    for d in animation_data.get("left_hand_animation", []):
        f = int(d["frame"])
        _add("H_L",  f, d.get("position"), d.get("rotation"))
        _add("HP_L", f, d.get("pivot_position"))

    for d in animation_data.get("right_hand_animation", []):
        f = int(d["frame"])
        _add("H_R",  f, d.get("position"), d.get("rotation"))
        _add("HP_R", f, d.get("pivot_position"))

    for d in animation_data.get("left_foot_animation", []):
        f = int(d["frame"])
        _add("F_L", f, d.get("position"), d.get("rotation"))

    for d in animation_data.get("right_foot_animation", []):
        f = int(d["frame"])
        _add("F_R", f, d.get("position"), d.get("rotation"))

    for d in animation_data.get("head_control_animation", []):
        f = int(d["frame"])
        _add("Head_Control", f, d.get("head_control_position"))

    # 准备 fcurve
    for obj_name, entry in object_data.items():
        obj = bpy.data.objects[obj_name]
        if not obj.animation_data:
            obj.animation_data_create()
        if not obj.animation_data.action:
            obj.animation_data.action = bpy.data.actions.new(
                f"{obj_name}_anim")

        if "locations" in entry:
            entry["loc_fcurves"] = [
                animation_utils.get_or_create_fcurve(obj, "location", i)
                for i in range(3)]
        if "quats" in entry:
            obj.rotation_mode = "QUATERNION"
            entry["quat_fcurves"] = [
                animation_utils.get_or_create_fcurve(
                    obj, "rotation_quaternion", i)
                for i in range(4)]

    # 批量写入关键帧
    for obj_name, entry in object_data.items():
        frames = entry["frames"]
        if "loc_fcurves" in entry:
            for i, fc in enumerate(entry["loc_fcurves"]):
                animation_utils.write_fcurve_points(
                    fc, zip(frames, [loc[i] for loc in entry["locations"]]))
        if "quat_fcurves" in entry:
            for i, fc in enumerate(entry["quat_fcurves"]):
                animation_utils.write_fcurve_points(
                    fc, zip(frames, [q[i] for q in entry["quats"]]))

    print(f"✓ 动画已生成 ← {animation_path}")


def make_shape_key_animation(shape_key_animation_path: str) -> None:
    """根据 shape key 动画 JSON 批量写入关键帧

    JSON 结构：[{"drum_kit": "<name>", "animation_data": [{"frame": N, "value": V}, ...]}, ...]
    Shape key 名称约定：<drum_kit>_beat
    """
    with open(shape_key_animation_path, "r") as f:
        sk_data = json.load(f)

    drum_kit_names = list({d["drum_kit"] for d in sk_data})

    # 在场景中搜索 shape key
    found = {}
    for obj in bpy.data.objects:
        if not hasattr(obj.data, "shape_keys") or obj.data.shape_keys is None:
            continue
        for name in drum_kit_names:
            sk_name = f"{name}_beat"
            if sk_name in obj.data.shape_keys.key_blocks:
                found[sk_name] = (obj, obj.data.shape_keys.key_blocks[sk_name])

    # 收集帧数据
    shape_entries = {}
    for item in sk_data:
        sk_name = f"{item['drum_kit']}_beat"
        if sk_name not in found:
            print(f"警告: 找不到 shape key {sk_name}")
            continue
        obj, key_block = found[sk_name]
        entry = shape_entries.setdefault(
            (obj.name, sk_name), {"shape_key": key_block, "frames": [], "values": []})
        for kf in item["animation_data"]:
            entry["frames"].append(int(kf["frame"]))
            entry["values"].append(kf["value"])

    # 批量写入
    for (obj_name, sk_name), entry in shape_entries.items():
        obj = bpy.data.objects[obj_name]
        shape_keys = obj.data.shape_keys
        if not shape_keys.animation_data:
            shape_keys.animation_data_create()
        if not shape_keys.animation_data.action:
            shape_keys.animation_data.action = bpy.data.actions.new(
                f"{obj_name}_sk")

        fc = animation_utils.get_or_create_fcurve(
            shape_keys, f'key_blocks["{sk_name}"].value')
        animation_utils.write_fcurve_points(
            fc, zip(entry["frames"], entry["values"]))

    print(f"✓ Shape Key 动画已生成 ← {shape_key_animation_path}")
