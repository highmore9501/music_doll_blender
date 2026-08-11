# harp_glide/animation.py
"""HarpGlide 乐器模块 —— 动画生成（迁移自 harp_blender_addon/tools/animation_generator.py）

fcurve 工具改调 common.animation_utils，不在模块内重复定义。
所有控件查找通过 performer_utils.resolve 加演奏者后缀。
"""

import json
import os

import bpy  # type: ignore

from ..common import performer_utils
from ..common import animation_utils


# Rust 端控制器键 → Blender 短名前缀（加 _L / _R 后缀）
_HAND_CTRL_MAP = {
    "h":      "H",
    "thumb":  "T",
    "index":  "I",
    "middle": "M",
    "ring":   "R",
    "pinky":  "P",
    "hp":     "HP",
}


# ── 内部辅助 ─────────────────────────────────────────────────

def _resolve(short: str, suffix: str) -> str:
    return performer_utils.resolve(short, suffix)


def _get_obj(short: str, suffix: str):
    return bpy.data.objects.get(_resolve(short, suffix))


def _clear(obj) -> None:
    if obj and obj.animation_data:
        obj.animation_data_clear()


def _ensure_action(obj) -> None:
    if not obj.animation_data:
        obj.animation_data_create()
    if not obj.animation_data.action:
        obj.animation_data.action = bpy.data.actions.new(f"{obj.name}_anim")


def _write_loc_rot(obj, loc_frames, locations, quat_frames, quats) -> None:
    """批量写入 location + rotation_quaternion"""
    _ensure_action(obj)
    if locations:
        for i in range(3):
            fc = animation_utils.get_or_create_fcurve(obj, "location", i)
            animation_utils.write_fcurve_points(
                fc, zip(loc_frames, [l[i] for l in locations]))
    if quats:
        obj.rotation_mode = "QUATERNION"
        for i in range(4):
            fc = animation_utils.get_or_create_fcurve(
                obj, "rotation_quaternion", i)
            animation_utils.write_fcurve_points(
                fc, zip(quat_frames, [q[i] for q in quats]))


def _collect_loc_rot(keyframes, pos_getter, rot_getter):
    """从关键帧列表提取 loc/rot 数组（含四元数符号一致性处理）"""
    loc_frames, locations = [], []
    quat_frames, quats = [], []
    prev_quat = None
    for kf in keyframes:
        frame = int(kf["frame"])
        pos = pos_getter(kf)
        rot = rot_getter(kf)
        if pos and len(pos) == 3:
            loc_frames.append(frame)
            locations.append(list(pos))
        if rot and len(rot) == 4:
            quat = list(rot)
            if prev_quat is not None and sum(a*b for a, b in zip(prev_quat, quat)) < 0:
                quat = [-x for x in quat]
            prev_quat = quat
            quat_frames.append(frame)
            quats.append(quat)
    return loc_frames, locations, quat_frames, quats


# ── 竖琴支点动画 ─────────────────────────────────────────────

def generate_harp_animation(harp_path: str, suffix: str = "") -> None:
    print("\n=== 生成竖琴动画 ===")
    obj = _get_obj("harp_pivot", suffix)
    if not obj:
        print("  ⚠ 场景中未找到 harp_pivot，跳过")
        return
    _clear(obj)
    with open(harp_path, "r", encoding="utf-8") as f:
        kfs = json.load(f)
    lf, locs, qf, quats = _collect_loc_rot(
        kfs,
        pos_getter=lambda k: k.get("location"),
        rot_getter=lambda k: k.get("rotation"))
    _write_loc_rot(obj, lf, locs, qf, quats)
    print(f"  ✓ 竖琴动画：{len(kfs)} 帧")


# ── 演奏者动画（head + 双脚 + 双手 + Mid_Hand） ────────────────

def generate_performance_animation(perf_path: str, suffix: str = "") -> None:
    print("\n=== 生成表演者动画 ===")
    with open(perf_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # head
    head_obj = _get_obj("Head", suffix)
    if head_obj and "head" in data:
        _clear(head_obj)
        lf, locs, qf, quats = _collect_loc_rot(
            data["head"],
            lambda k: k.get("location"),
            lambda k: k.get("rotation"))
        _write_loc_rot(head_obj, lf, locs, qf, quats)
        print(f"  ✓ 头部：{len(data['head'])} 帧")

    # 双脚
    for foot_key, short, label in (
            ("left_foot",  "F_L", "左脚"),
            ("right_foot", "F_R", "右脚")):
        foot_obj = _get_obj(short, suffix)
        if foot_obj and foot_key in data:
            _clear(foot_obj)
            lf, locs, qf, quats = _collect_loc_rot(
                data[foot_key],
                lambda k: k.get("foot_position"),
                lambda k: k.get("foot_rotation"))
            _write_loc_rot(foot_obj, lf, locs, qf, quats)
            print(f"  ✓ {label}：{len(data[foot_key])} 帧")

    # 双手
    for hand_key, side, label in (
            ("left_hand",  "L", "左手"),
            ("right_hand", "R", "右手")):
        if hand_key in data:
            _generate_hand_animation(data[hand_key], side, label, suffix)

    # Mid_Hand
    mid_obj = _get_obj("Mid_Hand", suffix)
    if mid_obj and "mid_hand" in data:
        _clear(mid_obj)
        lf, locs, qf, quats = _collect_loc_rot(
            data["mid_hand"],
            lambda k: k.get("transform", {}).get("position"),
            lambda k: k.get("transform", {}).get("rotation"))
        _write_loc_rot(mid_obj, lf, locs, qf, quats)
        print(f"  ✓ Mid_Hand：{len(data['mid_hand'])} 帧")


def _generate_hand_animation(hand_kfs: list, side: str, label: str,
                             suffix: str) -> None:
    """单手控制器批量写关键帧"""
    # 先清动画
    for blender_base in _HAND_CTRL_MAP.values():
        obj = _get_obj(f"{blender_base}_{side}", suffix)
        if obj:
            _clear(obj)

    obj_data: dict = {}
    prev_quats: dict = {}

    for kf in hand_kfs:
        ctrl_key = kf.get("controller_name", "")
        blender_base = _HAND_CTRL_MAP.get(ctrl_key)
        if not blender_base:
            continue
        full = _resolve(f"{blender_base}_{side}", suffix)
        obj = bpy.data.objects.get(full)
        if not obj:
            continue

        frame = int(kf["frame"])
        tf = kf.get("transform", {})
        entry = obj_data.setdefault(full, {
            "obj": obj,
            "loc_frames": [], "locations": [],
            "quat_frames": [], "quats": []})

        pos = tf.get("position")
        if pos:
            entry["loc_frames"].append(frame)
            entry["locations"].append(list(pos))

        rot = tf.get("rotation")
        if rot:
            quat = list(rot)
            if full in prev_quats and sum(a*b for a, b in zip(prev_quats[full], quat)) < 0:
                quat = [-x for x in quat]
            prev_quats[full] = quat
            entry["quat_frames"].append(frame)
            entry["quats"].append(quat)

    for entry in obj_data.values():
        _write_loc_rot(entry["obj"],
                       entry["loc_frames"], entry["locations"],
                       entry["quat_frames"], entry["quats"])
    print(f"  ✓ {label}：处理 {len(hand_kfs)} 条关键帧记录")


# ── Shape Key 动画（无后缀：按 shape key 名查找 mesh） ──────────

def _find_obj_with_shape_key(name: str):
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data.shape_keys:
            if name in obj.data.shape_keys.key_blocks:
                return obj
    return None


def _clear_shape_key_animation(obj, prefix: str) -> None:
    if not (obj and obj.data.shape_keys and obj.data.shape_keys.animation_data):
        return
    action = obj.data.shape_keys.animation_data.action
    if action is None:
        return
    to_remove = [fc for fc in action.fcurves
                 if fc.data_path.startswith(f'key_blocks["{ prefix}')]
    for fc in to_remove:
        action.fcurves.remove(fc)


def generate_pedal_shape_animation(pedal_path: str) -> None:
    print("\n=== 生成踏板 Shape Key 动画 ===")
    pedal_obj = _find_obj_with_shape_key("pedal_A_state0")
    if not pedal_obj:
        print("  ⚠ 未找到含 pedal_A_state0 的物体，跳过")
        return

    _clear_shape_key_animation(pedal_obj, "pedal_")
    with open(pedal_path, "r", encoding="utf-8") as f:
        events = json.load(f)

    key_blocks = pedal_obj.data.shape_keys.key_blocks
    shape_data: dict = {}
    for ev in events:
        sk_name = ev.get("pedal_state", "")
        if not key_blocks.get(sk_name):
            continue
        frame = int(ev["data"]["frame"])
        value = ev["data"]["value"]
        shape_data.setdefault(sk_name, {"frames": [], "values": []})
        shape_data[sk_name]["frames"].append(frame)
        shape_data[sk_name]["values"].append(value)

    sk_data = pedal_obj.data.shape_keys
    if not sk_data.animation_data:
        sk_data.animation_data_create()
    if not sk_data.animation_data.action:
        sk_data.animation_data.action = bpy.data.actions.new(
            f"{pedal_obj.name}_pedal_sk")

    for sk_name, ed in shape_data.items():
        fc = animation_utils.get_or_create_fcurve(
            sk_data, f'key_blocks["{sk_name}"].value')
        animation_utils.write_fcurve_points(
            fc, zip(ed["frames"], ed["values"]))
    print(f"  ✓ 踏板 Shape Key：{len(events)} 个事件")


def generate_string_shape_animation(string_path: str) -> None:
    print("\n=== 生成弦振动 Shape Key 动画 ===")
    string_obj = _find_obj_with_shape_key("string0_inner")
    if not string_obj:
        print("  ⚠ 未找到含 string0_inner 的物体，跳过")
        return

    _clear_shape_key_animation(string_obj, "string")
    with open(string_path, "r", encoding="utf-8") as f:
        events = json.load(f)

    key_blocks = string_obj.data.shape_keys.key_blocks
    shape_data: dict = {}
    for ev in events:
        direction = "outer" if ev.get("is_thumb") else "inner"
        sk_name = f'string{ev["string_index"]}_{direction}'
        if not key_blocks.get(sk_name):
            continue
        shape_data.setdefault(sk_name, {"frames": [], "values": []})
        shape_data[sk_name]["frames"].append(int(ev["frame"]))
        shape_data[sk_name]["values"].append(ev["value"])

    sk_data = string_obj.data.shape_keys
    if not sk_data.animation_data:
        sk_data.animation_data_create()
    if not sk_data.animation_data.action:
        sk_data.animation_data.action = bpy.data.actions.new(
            f"{string_obj.name}_string_sk")

    for sk_name, ed in shape_data.items():
        fc = animation_utils.get_or_create_fcurve(
            sk_data, f'key_blocks["{sk_name}"].value')
        animation_utils.write_fcurve_points(
            fc, zip(ed["frames"], ed["values"]))
    print(f"  ✓ 弦振动 Shape Key：{len(events)} 个事件")


# ── 顶层入口 ─────────────────────────────────────────────────

def generate_all_animations(report_path: str, suffix: str = "") -> None:
    """读 .harpglide report，调用四个子动画生成函数"""
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    report_dir = os.path.dirname(report_path)

    def _abs(p: str) -> str:
        return p if os.path.isabs(p) else os.path.normpath(
            os.path.join(report_dir, p))

    harp_path = _abs(report.get("harp_animation", ""))
    perf_path = _abs(report.get("performance_animation", ""))
    pedal_path = _abs(report.get("pedal_shape_animation", ""))
    str_path = _abs(report.get("string_animation", ""))

    if harp_path and os.path.exists(harp_path):
        generate_harp_animation(harp_path, suffix)
    if perf_path and os.path.exists(perf_path):
        generate_performance_animation(perf_path, suffix)
    if pedal_path and os.path.exists(pedal_path):
        generate_pedal_shape_animation(pedal_path)
    if str_path and os.path.exists(str_path):
        generate_string_shape_animation(str_path)

    print("\n✓ 全部动画生成完成")
