# wind_rise/animation.py
"""WindRise 乐器模块 —— 动画生成（迁移自 wind_rise_blender/make_animation.py）"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import bpy  # type: ignore

from ..common import animation_utils
from ..common import performer_utils
from ..common import object_utils


# ── 数据类型 ──────────────────────────────────────────────────

@dataclass
class HandKeyframe:
    frame: float
    hand_infos: Dict[str, List[float]]
    state: str


@dataclass
class ShapeKeyKeyframe:
    frame: float
    shape_key_name: str
    value: float


@dataclass
class ActivityCurveFrame:
    frame: float
    value: float


@dataclass
class WindRiseAnimationData:
    left_hand: List[HandKeyframe] = field(default_factory=list)
    right_hand: List[HandKeyframe] = field(default_factory=list)
    character_sk: List[ShapeKeyKeyframe] = field(default_factory=list)
    instrument_sk: List[ShapeKeyKeyframe] = field(default_factory=list)
    activity_curve: List[ActivityCurveFrame] = field(default_factory=list)


# ── 文件加载 ──────────────────────────────────────────────────

def load_wind_rise_file(file_path: str) -> WindRiseAnimationData:
    with open(file_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    result = WindRiseAnimationData()

    left_path = manifest.get("left_hand_animation_file", "")
    right_path = manifest.get("right_hand_animation_file", "")
    char_sk_path = manifest.get("character_sk_animation_file", "")
    inst_sk_path = manifest.get("instrument_sk_animation_file", "")
    activity_path = manifest.get("activity_curve_file", "")

    if os.path.exists(left_path):
        result.left_hand = _load_hand_animation(left_path)
        print(f"左手动画: {len(result.left_hand)} 帧")
    else:
        print(f"警告: 左手动画文件不存在: {left_path}")

    if os.path.exists(right_path):
        result.right_hand = _load_hand_animation(right_path)
        print(f"右手动画: {len(result.right_hand)} 帧")
    else:
        print(f"警告: 右手动画文件不存在: {right_path}")

    if os.path.exists(char_sk_path):
        result.character_sk = _load_shape_key_animation(char_sk_path)
        print(f"角色 Shape Key 动画: {len(result.character_sk)} 关键帧")
    else:
        print(f"警告: 角色 Shape Key 动画文件不存在: {char_sk_path}")

    if os.path.exists(inst_sk_path):
        result.instrument_sk = _load_shape_key_animation(inst_sk_path)
        print(f"乐器 Shape Key 动画: {len(result.instrument_sk)} 关键帧")
    else:
        print(f"警告: 乐器 Shape Key 动画文件不存在: {inst_sk_path}")

    if os.path.exists(activity_path):
        result.activity_curve = _load_activity_curve(activity_path)
        print(f"活动曲线: {len(result.activity_curve)} 帧")
    else:
        print(f"警告: 活动曲线文件不存在: {activity_path}")

    return result


def _load_hand_animation(file_path: str) -> List[HandKeyframe]:
    with open(file_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [HandKeyframe(
        frame=float(e.get("frame", 0)),
        hand_infos=e.get("hand_infos", {}),
        state=e.get("state", ""),
    ) for e in raw]


def _load_shape_key_animation(file_path: str) -> List[ShapeKeyKeyframe]:
    with open(file_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [ShapeKeyKeyframe(
        frame=float(e.get("frame", 0)),
        shape_key_name=e.get("shape_key_name", ""),
        value=float(e.get("value", 0.0)),
    ) for e in raw]


def _load_activity_curve(file_path: str) -> List[ActivityCurveFrame]:
    with open(file_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [ActivityCurveFrame(
        frame=float(e.get("frame", 0)),
        value=float(e.get("value", 0.0)),
    ) for e in raw]


# ── 动画写入 ──────────────────────────────────────────────────

def _ensure_quaternion_consistency(
    obj_name: str,
    quat: List[float],
    prev_quats: Dict[str, List[float]],
) -> List[float]:
    if obj_name in prev_quats:
        prev = prev_quats[obj_name]
        dot = sum(a * b for a, b in zip(prev, quat))
        if dot < 0:
            quat = [-x for x in quat]
    prev_quats[obj_name] = quat
    return quat


def apply_hand_animation(frames: List[HandKeyframe], suffix: str) -> None:
    """把手部动画帧批量写入 Blender 控件（对象名按 suffix 解析）。"""
    if not frames:
        return

    prev_quats: Dict[str, List[float]] = {}
    object_data: Dict[str, dict] = {}

    for frame_data in frames:
        frame = int(frame_data.frame)
        if frame < 0:
            continue
        for short_name, transform in frame_data.hand_infos.items():
            full_name = performer_utils.resolve(short_name, suffix)
            obj = bpy.data.objects.get(full_name)
            if obj is None:
                continue
            data_len = len(transform)
            entry = object_data.setdefault(full_name, {"frames": []})

            if data_len == 7:
                entry.setdefault("locations", []).append(transform[:3])
                quat = _ensure_quaternion_consistency(
                    full_name, transform[3:], prev_quats)
                entry.setdefault("quats", []).append(quat)
                entry["frames"].append(frame)
            elif data_len == 3:
                entry.setdefault("locations", []).append(transform[:3])
                entry["frames"].append(frame)
            elif data_len == 4:
                quat = _ensure_quaternion_consistency(
                    full_name, transform, prev_quats)
                entry.setdefault("quats", []).append(quat)
                entry["frames"].append(frame)

    for full_name, entry in object_data.items():
        obj = bpy.data.objects[full_name]
        if not obj.animation_data:
            obj.animation_data_create()
        if not obj.animation_data.action:
            obj.animation_data.action = bpy.data.actions.new(
                f"{full_name}_anim")

        if "locations" in entry:
            entry["location_fcurves"] = [
                animation_utils.get_or_create_fcurve(obj, "location", i)
                for i in range(3)]
        if "quats" in entry:
            obj.rotation_mode = "QUATERNION"
            entry["quat_fcurves"] = [
                animation_utils.get_or_create_fcurve(
                    obj, "rotation_quaternion", i)
                for i in range(4)]

    applied = 0
    for full_name, entry in object_data.items():
        frames_list = entry["frames"]
        if "location_fcurves" in entry:
            for i, fc in enumerate(entry["location_fcurves"]):
                animation_utils.write_fcurve_points(
                    fc, zip(frames_list, [loc[i] for loc in entry["locations"]]))
        if "quat_fcurves" in entry:
            for i, fc in enumerate(entry["quat_fcurves"]):
                animation_utils.write_fcurve_points(
                    fc, zip(frames_list, [q[i] for q in entry["quats"]]))
        applied += len(frames_list)

    print(f"手部动画写入完成，共处理 {applied} 个关键帧")


def apply_shape_key_animation(
    frames: List[ShapeKeyKeyframe],
    mesh_obj: Optional[bpy.types.Object],
) -> None:
    if not frames or mesh_obj is None:
        return
    if not hasattr(mesh_obj.data, "shape_keys") or mesh_obj.data.shape_keys is None:
        print(f"警告: 物体 '{mesh_obj.name}' 没有 Shape Key")
        return

    key_blocks = mesh_obj.data.shape_keys.key_blocks
    shape_data: Dict[str, dict] = {}
    for kf in frames:
        frame = int(kf.frame)
        if frame < 0:
            continue
        sk = key_blocks.get(kf.shape_key_name)
        if sk is None:
            continue
        entry = shape_data.setdefault(
            kf.shape_key_name, {"shape_key": sk, "frames": [], "values": []})
        entry["frames"].append(frame)
        entry["values"].append(kf.value)

    shape_keys = mesh_obj.data.shape_keys
    if not shape_keys.animation_data:
        shape_keys.animation_data_create()
    if not shape_keys.animation_data.action:
        shape_keys.animation_data.action = bpy.data.actions.new(
            f"{mesh_obj.name}_shape_keys")

    for sk_name, entry in shape_data.items():
        fc = animation_utils.get_or_create_fcurve(
            shape_keys, f'key_blocks["{sk_name}"].value')
        animation_utils.write_fcurve_points(
            fc, zip(entry["frames"], entry["values"]))

    print(
        f"Shape Key 动画写入完成 ('{mesh_obj.name}'): {sum(len(e['frames']) for e in shape_data.values())} 关键帧")


def apply_activity_curve(frames: List[ActivityCurveFrame], suffix: str) -> None:
    """把活动曲线写入 controller_root 的自定义属性 activity_curve（fcurve 关键帧）。"""
    if not frames:
        return

    # 主写入：controller_root 的自定义属性 fcurve
    cr_name = performer_utils.resolve("controller_root", suffix)
    cr_obj = bpy.data.objects.get(cr_name)
    if cr_obj is not None:
        if not cr_obj.animation_data:
            cr_obj.animation_data_create()
        if not cr_obj.animation_data.action:
            cr_obj.animation_data.action = bpy.data.actions.new(
                f"{cr_name}_anim")
        # 确保自定义属性存在
        if "activity_curve" not in cr_obj:
            cr_obj["activity_curve"] = 0.0
        fc = animation_utils.get_or_create_fcurve(
            cr_obj, '["activity_curve"]')
        animation_utils.write_fcurve_points(
            fc, [(int(f.frame), f.value) for f in frames])
        print(f"活动曲线写入 {cr_name}[\"activity_curve\"]: {len(frames)} 帧")

    # 备份：ActivityCurve_<suffix> Empty 上存 JSON 副本（供调试）
    curve_obj_name = performer_utils.resolve("ActivityCurve", suffix)
    curve_obj = bpy.data.objects.get(curve_obj_name)
    if curve_obj is None:
        curve_obj = bpy.data.objects.new(curve_obj_name, None)
        curve_obj.empty_display_size = 0.01
        addons_name = performer_utils.resolve("addons", suffix)
        col = bpy.data.collections.get(addons_name)
        if col:
            col.objects.link(curve_obj)
        else:
            bpy.context.scene.collection.objects.link(curve_obj)
    curve_obj["wind_rise_activity_curve"] = json.dumps(
        [{"frame": f.frame, "value": f.value} for f in frames],
        ensure_ascii=False)


# ── 主入口 ────────────────────────────────────────────────────

def generate_animation_from_wind_rise(
    file_path: str,
    suffix: str,
    lip_mesh: Optional[bpy.types.Object],
    instrument_mesh: Optional[bpy.types.Object],
) -> None:
    """从 .wind_rise 文件生成完整动画。"""
    print(f"\n{'='*60}")
    print(f"开始从 .wind_rise 生成动画: {file_path}")
    print(f"{'='*60}")

    anim_data = load_wind_rise_file(file_path)

    print("\n清除现有动画（保留 ext driver）...")
    animation_utils.clear_all_keyframe_preserve_drivers(
        collection_names=["Controllers"], suffix=suffix)

    print("\n写入左手动画...")
    apply_hand_animation(anim_data.left_hand, suffix)

    print("\n写入右手动画...")
    apply_hand_animation(anim_data.right_hand, suffix)

    lip_name = lip_mesh.name if lip_mesh else "未选择"
    print(f"\n写入角色 Shape Key 动画 (人物Mesh: {lip_name})...")
    apply_shape_key_animation(anim_data.character_sk, lip_mesh)

    inst_name = instrument_mesh.name if instrument_mesh else "未选择"
    print(f"\n写入乐器 Shape Key 动画 (乐器Mesh: {inst_name})...")
    apply_shape_key_animation(anim_data.instrument_sk, instrument_mesh)

    print("\n写入活动曲线...")
    apply_activity_curve(anim_data.activity_curve, suffix)

    print("\n动画生成完成")
