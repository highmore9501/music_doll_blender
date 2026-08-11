# harp_glide/state.py
"""HarpGlide 乐器模块 —— 状态传输

所有状态存骨骼自定义属性 `harp_glide_state_data`（JSON）。
踏板位置需要 harp_pivot 坐标系转换（保留原逻辑）。

JSON 结构：
{
  "config": {...},
  "pedal_positions": {
    "pedal_D_state0": {"location": [...], "rotation": [w,x,y,z]},
    ...
  },
  "harp_pivot_states": {
    "near": {"location": [...], "rotation": [...]},
    "mid":  {...},
    "far":  {...}
  },
  "hand_poses": {
    "left":  {"far": {"H_L": {...}, "HP_L": {...}, "T_L": {...}, ...}, ...},
    "right": {"far": {"H_R": {...}, ...}, ...}
  },
  "head_poses": {
    "far": {"Head": {"location": [...], "rotation": [...]}},
    ...
  },
  "foot_rest": {
    "F_L": {"location": [...], "rotation": [...]},
    "F_R": {...}
  }
}
"""

import bpy         # type: ignore
import mathutils   # type: ignore

from ..common import performer_utils as _pu
from ..common import state_io

from .config import STATE_KEY
from .enums import HandPoseState, PedalNote, PedalState, HarpPivotState, LEFT_FOOT_NOTES


# ── 内部读写辅助 ─────────────────────────────────────────────

def _get(skeleton) -> dict:
    return state_io.get_state_data(skeleton, STATE_KEY, {})


def _set(skeleton, data: dict) -> None:
    state_io.set_state_data(skeleton, STATE_KEY, data)


def _read_ctrl(suffix: str, short: str) -> dict:
    obj = bpy.data.objects.get(_pu.resolve(short, suffix))
    if obj is None:
        return {"location": [0.0, 0.0, 0.0], "rotation": [1.0, 0.0, 0.0, 0.0]}
    quat = (obj.rotation_quaternion
            if obj.rotation_mode == "QUATERNION"
            else obj.rotation_euler.to_quaternion())
    return {
        "location": list(obj.location),
        "rotation": [quat.w, quat.x, quat.y, quat.z],
    }


def _write_ctrl(suffix: str, short: str, entry: dict) -> None:
    obj = bpy.data.objects.get(_pu.resolve(short, suffix))
    if obj is None:
        return
    loc = entry.get("location", [0.0, 0.0, 0.0])
    rot = entry.get("rotation", [1.0, 0.0, 0.0, 0.0])
    obj.lock_location[:] = [False, False, False]
    obj.location = (loc[0], loc[1], loc[2])
    obj.lock_rotation[:] = [False, False, False]
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (rot[0], rot[1], rot[2], rot[3])


# ── 手部姿势 ─────────────────────────────────────────────────

def save_hand_pose(suffix: str, hand: str, pose_state: HandPoseState,
                   skeleton) -> None:
    """控件 → 骨骼 JSON hand_poses.<hand>.<state>"""
    state_key = pose_state.value
    data = _get(skeleton)
    data.setdefault("hand_poses", {}).setdefault(hand, {})[state_key] = {}
    target = data["hand_poses"][hand][state_key]

    shorts = (["H_L", "HP_L", "T_L", "I_L", "M_L", "R_L", "P_L"]
              if hand == "left"
              else ["H_R", "HP_R", "T_R", "I_R", "M_R", "R_R", "P_R"])
    for s in shorts:
        target[s] = _read_ctrl(suffix, s)
    _set(skeleton, data)
    print(f"✓ 手部姿势已保存：{hand} {state_key}")


def load_hand_pose(suffix: str, hand: str, pose_state: HandPoseState,
                   skeleton) -> None:
    """骨骼 JSON → 控件"""
    state_key = pose_state.value
    data = _get(skeleton)
    target = data.get("hand_poses", {}).get(hand, {}).get(state_key, {})
    if not target:
        print(f"  ✗ 未找到姿势数据：hand_poses.{hand}.{state_key}")
        return
    for short, entry in target.items():
        _write_ctrl(suffix, short, entry)
    print(f"✓ 手部姿势已加载：{hand} {state_key}")


# ── 头部姿势 ─────────────────────────────────────────────────

def save_head_pose(suffix: str, pose_state: HandPoseState, skeleton) -> None:
    state_key = pose_state.value
    data = _get(skeleton)
    data.setdefault("head_poses", {})[state_key] = {
        "Head": _read_ctrl(suffix, "Head")
    }
    _set(skeleton, data)
    print(f"✓ 头部姿势已保存：{state_key}")


def load_head_pose(suffix: str, pose_state: HandPoseState, skeleton) -> None:
    state_key = pose_state.value
    data = _get(skeleton)
    entry = data.get("head_poses", {}).get(state_key, {}).get("Head")
    if entry is None:
        print(f"  ✗ 未找到头部姿势：head_poses.{state_key}")
        return
    _write_ctrl(suffix, "Head", entry)
    print(f"✓ 头部姿势已加载：{state_key}")


# ── 踏板状态（含 harp_pivot 坐标系转换） ─────────────────────

def save_pedal_state(suffix: str, note: PedalNote, pedal_state: PedalState,
                     skeleton) -> None:
    """F_L/F_R 世界坐标 → harp_pivot 局部坐标 → 骨骼 JSON"""
    ctrl_short = "F_L" if note.value in LEFT_FOOT_NOTES else "F_R"
    key = f"pedal_{note.value}_{pedal_state.value}"

    ctrl_obj = bpy.data.objects.get(_pu.resolve(ctrl_short, suffix))
    pivot_obj = bpy.data.objects.get(_pu.resolve("harp_pivot", suffix))
    if not ctrl_obj:
        print(f"  ✗ 控件不存在：{ctrl_short}")
        return
    if not pivot_obj:
        print(f"  ✗ harp_pivot 不存在，无法转换坐标系")
        return

    world_mat = ctrl_obj.matrix_world.copy()
    local_mat = pivot_obj.matrix_world.inverted() @ world_mat
    loc = list(local_mat.translation)
    quat = local_mat.to_quaternion()

    data = _get(skeleton)
    data.setdefault("pedal_positions", {})[key] = {
        "location": loc,
        "rotation": [quat.w, quat.x, quat.y, quat.z],
    }
    _set(skeleton, data)
    print(f"✓ 踏板位置已保存（局部坐标）：{key}")


def load_pedal_state(suffix: str, note: PedalNote, pedal_state: PedalState,
                     skeleton) -> None:
    """骨骼 JSON（harp_pivot 局部坐标）→ F_L/F_R 世界坐标"""
    ctrl_short = "F_L" if note.value in LEFT_FOOT_NOTES else "F_R"
    key = f"pedal_{note.value}_{pedal_state.value}"

    data = _get(skeleton)
    entry = data.get("pedal_positions", {}).get(key)
    if not entry:
        print(f"  ✗ 未找到踏板数据：{key}")
        return

    ctrl_obj = bpy.data.objects.get(_pu.resolve(ctrl_short, suffix))
    pivot_obj = bpy.data.objects.get(_pu.resolve("harp_pivot", suffix))
    if not ctrl_obj or not pivot_obj:
        print(f"  ✗ 控件或 harp_pivot 不存在，跳过")
        return

    loc = entry["location"]
    rot = entry["rotation"]
    quat = mathutils.Quaternion((rot[0], rot[1], rot[2], rot[3]))
    local_mat = mathutils.Matrix.LocRotScale(
        mathutils.Vector(loc), quat, None)
    world_mat = pivot_obj.matrix_world @ local_mat

    ctrl_obj.lock_location[:] = [False, False, False]
    ctrl_obj.location = world_mat.translation
    ctrl_obj.lock_rotation[:] = [False, False, False]
    ctrl_obj.rotation_mode = "QUATERNION"
    ctrl_obj.rotation_quaternion = world_mat.to_quaternion()
    print(f"✓ 踏板位置已加载：{key} → {ctrl_short}")


# ── 竖琴倾斜状态 ─────────────────────────────────────────────

def save_harp_tilt(suffix: str, tilt_state: HarpPivotState, skeleton) -> None:
    key = tilt_state.value
    data = _get(skeleton)
    data.setdefault("harp_pivot_states", {})[
        key] = _read_ctrl(suffix, "harp_pivot")
    _set(skeleton, data)
    print(f"✓ 竖琴倾斜状态已保存：{key}")


def load_harp_tilt(suffix: str, tilt_state: HarpPivotState, skeleton) -> None:
    key = tilt_state.value
    data = _get(skeleton)
    entry = data.get("harp_pivot_states", {}).get(key)
    if not entry:
        print(f"  ✗ 未找到倾斜数据：{key}")
        return
    _write_ctrl(suffix, "harp_pivot", entry)
    print(f"✓ 竖琴倾斜状态已加载：{key}")


# ── 脚部休息位置 ─────────────────────────────────────────────

def save_foot_rest(suffix: str, skeleton) -> None:
    data = _get(skeleton)
    data["foot_rest"] = {
        "F_L": _read_ctrl(suffix, "F_L"),
        "F_R": _read_ctrl(suffix, "F_R"),
    }
    _set(skeleton, data)
    print("✓ 脚部休息位置已保存")


def load_foot_rest(suffix: str, skeleton) -> None:
    data = _get(skeleton)
    foot = data.get("foot_rest", {})
    for short in ("F_L", "F_R"):
        entry = foot.get(short)
        if entry:
            _write_ctrl(suffix, short, entry)
    print("✓ 脚部休息位置已加载")
