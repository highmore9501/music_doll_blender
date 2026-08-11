# harp_glide/io.py
"""HarpGlide 乐器模块 —— 导入/导出 .harpist

.harpist 文件格式（Rust 端兼容，短名键）：
  STRING_RECORDERS         ← 从物理对象读写（s{n}head / s{n}end）
  PEDAL_POSITION_RECORDERS ← 骨骼 JSON pedal_positions
  HARP_PIVOT_RECORDERS     ← 骨骼 JSON harp_pivot_states
  LEFT_HAND_RECORDERS      ← 骨骼 JSON hand_poses.left（展平为 {ctrl}_{pose} 键）
  RIGHT_HAND_RECORDERS     ← 骨骼 JSON hand_poses.right
  HEAD_RECORDERS           ← 骨骼 JSON head_poses（展平为 Head_{pose} 键）
  FOOT_REST_RECORDERS      ← 骨骼 JSON foot_rest（F_rest_L / F_rest_R 键）
"""

import bpy  # type: ignore

from ..common import performer_utils as _pu
from ..common import io_utils
from ..common import state_io

from .config import STATE_KEY
from .enums import HandPoseState, PedalNote, PedalState


# ── 物理对象读写（弦位置） ─────────────────────────────────────

def _read_obj_transform(full_name: str) -> dict:
    obj = bpy.data.objects.get(full_name)
    if obj is None:
        return {"location": [0.0, 0.0, 0.0], "rotation": [1.0, 0.0, 0.0, 0.0]}
    quat = (obj.rotation_quaternion
            if obj.rotation_mode == "QUATERNION"
            else obj.rotation_euler.to_quaternion())
    return {
        "location": list(obj.location),
        "rotation": [quat.w, quat.x, quat.y, quat.z],
    }


def _write_obj_transform(full_name: str, entry: dict) -> None:
    obj = bpy.data.objects.get(full_name)
    if obj is None:
        return
    loc = entry.get("location", [0.0, 0.0, 0.0])
    rot = entry.get("rotation", [1.0, 0.0, 0.0, 0.0])
    obj.lock_location[:] = [False, False, False]
    obj.location = (loc[0], loc[1], loc[2])
    obj.lock_rotation[:] = [False, False, False]
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (rot[0], rot[1], rot[2], rot[3])


# ── 导出 ─────────────────────────────────────────────────────

def _te(entry: dict, _pos, _rot) -> dict:
    """对单条 {location, rotation} 条目应用坐标转换（原地返回新 dict）。"""
    out = {}
    if "location" in entry:
        out["location"] = _pos(entry["location"])
    if "rotation" in entry:
        out["rotation"] = _rot(entry["rotation"])
    for k, v in entry.items():
        if k not in ("location", "rotation"):
            out[k] = v
    return out


def export_harpist(file_path: str, suffix: str, skeleton, props,
                   for_unreal: bool = False) -> None:
    """骨骼 JSON + 物理对象 → .harpist 文件

    for_unreal=True 时坐标转换为 Unreal 空间，is_unreal 字段随之置 True。
    """
    _pos = io_utils.to_unreal_position if for_unreal else (lambda p: p)
    _rot = io_utils.to_unreal_rotation if for_unreal else (lambda r: r)

    file_path = io_utils.ensure_extension(file_path, ".harpist")
    data = state_io.get_state_data(skeleton, STATE_KEY, {})

    cfg = dict(data.get("config", {
        "string_count": 47,
        "left_far": 0, "left_near": 0,
        "left_mid_far": 0, "left_mid_near": 0,
        "right_far": 0, "right_near": 0,
    }))
    cfg["is_unreal"] = for_unreal  # Rust 端从 config 子对象读取
    string_count = int(cfg.get("string_count", 47))

    result = {"config": cfg}

    # STRING_RECORDERS：从物理对象读（短名键）
    string_rec = {}
    for n in range(string_count):
        for part in ("head", "end"):
            short = f"s{n}{part}"
            string_rec[short] = _te(_read_obj_transform(
                _pu.resolve(short, suffix)), _pos, _rot)
    result["STRING_RECORDERS"] = string_rec

    # PEDAL_POSITION_RECORDERS：骨骼 JSON → 直接映射
    pedal_src = data.get("pedal_positions", {})
    result["PEDAL_POSITION_RECORDERS"] = {
        k: _te(v, _pos, _rot) for k, v in pedal_src.items()
    }

    # HARP_PIVOT_RECORDERS：near/mid/far → harp_pivot_{state} 键
    pivot_src = data.get("harp_pivot_states", {})
    result["HARP_PIVOT_RECORDERS"] = {
        f"harp_pivot_{k}": _te(v, _pos, _rot) for k, v in pivot_src.items()
    }

    # LEFT/RIGHT_HAND_RECORDERS：{ctrl}_{pose} 展平
    result["LEFT_HAND_RECORDERS"] = {
        k: _te(v, _pos, _rot) for k, v in _flatten_hand_poses(data, "left").items()
    }
    result["RIGHT_HAND_RECORDERS"] = {
        k: _te(v, _pos, _rot) for k, v in _flatten_hand_poses(data, "right").items()
    }

    # HEAD_RECORDERS：Head_{pose}
    head_poses = data.get("head_poses", {})
    head_rec = {}
    for pose, ctrls in head_poses.items():
        for ctrl, entry in ctrls.items():
            head_rec[f"{ctrl}_{pose}"] = _te(entry, _pos, _rot)
    result["HEAD_RECORDERS"] = head_rec

    # FOOT_REST_RECORDERS：F_rest_L / F_rest_R
    foot = data.get("foot_rest", {})
    result["FOOT_REST_RECORDERS"] = {
        "F_rest_L": _te(foot.get("F_L", {"location": [0]*3, "rotation": [1, 0, 0, 0]}), _pos, _rot),
        "F_rest_R": _te(foot.get("F_R", {"location": [0]*3, "rotation": [1, 0, 0, 0]}), _pos, _rot),
    }

    io_utils.save_json(file_path, result)
    print(f"✓ .harpist 导出完成：{file_path}")


def _flatten_hand_poses(data: dict, hand: str) -> dict:
    """hand_poses.<hand>.<pose>.<ctrl> → {ctrl_pose: entry}"""
    out = {}
    poses = data.get("hand_poses", {}).get(hand, {})
    for pose, ctrls in poses.items():
        for ctrl, entry in ctrls.items():
            out[f"{ctrl}_{pose}"] = entry
    return out


# ── 导入 ─────────────────────────────────────────────────────

def import_harpist(file_path: str, suffix: str, skeleton, props) -> None:
    """从 .harpist 文件写回物理对象 + 骨骼 JSON"""
    raw = io_utils.load_json(file_path)
    if not raw:
        print(f"  ✗ 无法读取文件：{file_path}")
        return

    data = state_io.get_state_data(skeleton, STATE_KEY, {})

    # config
    if "config" in raw:
        data["config"] = raw["config"]

    # STRING_RECORDERS → 物理对象
    for short, entry in raw.get("STRING_RECORDERS", {}).items():
        _write_obj_transform(_pu.resolve(short, suffix), entry)

    # PEDAL_POSITION_RECORDERS → 骨骼 JSON
    data["pedal_positions"] = dict(raw.get("PEDAL_POSITION_RECORDERS", {}))

    # HARP_PIVOT_RECORDERS：harp_pivot_{state} → {state}
    pivot_data = {}
    for k, v in raw.get("HARP_PIVOT_RECORDERS", {}).items():
        if k.startswith("harp_pivot_"):
            state_name = k[len("harp_pivot_"):]
            pivot_data[state_name] = v
    data["harp_pivot_states"] = pivot_data

    # LEFT/RIGHT_HAND_RECORDERS → hand_poses
    data["hand_poses"] = {
        "left":  _unflatten_hand_poses(raw.get("LEFT_HAND_RECORDERS",  {})),
        "right": _unflatten_hand_poses(raw.get("RIGHT_HAND_RECORDERS", {})),
    }

    # HEAD_RECORDERS：Head_{pose} → head_poses
    head_poses = {}
    for k, v in raw.get("HEAD_RECORDERS", {}).items():
        # 格式：Head_far / Head_near / ...
        parts = k.split("_", 1)
        if len(parts) == 2:
            ctrl, pose = parts
            head_poses.setdefault(pose, {})[ctrl] = v
    data["head_poses"] = head_poses

    # FOOT_REST_RECORDERS：F_rest_L/R → foot_rest
    foot_raw = raw.get("FOOT_REST_RECORDERS", {})
    data["foot_rest"] = {
        "F_L": foot_raw.get("F_rest_L", {"location": [0]*3, "rotation": [1, 0, 0, 0]}),
        "F_R": foot_raw.get("F_rest_R", {"location": [0]*3, "rotation": [1, 0, 0, 0]}),
    }

    state_io.set_state_data(skeleton, STATE_KEY, data)
    print(f"✓ .harpist 导入完成：{file_path}")


def _unflatten_hand_poses(flat: dict) -> dict:
    """{ctrl_pose: entry} → {pose: {ctrl: entry}}"""
    poses = {}
    for k, v in flat.items():
        # 格式：H_L_far / T_L_near / ...  最后一个 _ 前为 ctrl，其后为 pose
        idx = k.rfind("_")
        if idx < 0:
            continue
        ctrl = k[:idx]
        pose = k[idx+1:]
        poses.setdefault(pose, {})[ctrl] = v
    return poses
