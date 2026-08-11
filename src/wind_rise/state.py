# wind_rise/state.py
"""WindRise 乐器模块 —— 按 MIDI 音高的状态存取（Save/Load Note State）"""

import json

import bpy  # type: ignore
from mathutils import Quaternion  # type: ignore

from ..common import state_io
from .enums import (
    iter_hand_controllers,
    midi_to_name,
)

_STATE_KEY = "wind_rise_state_data"


# ── 骨骼 JSON 整体读写 ─────────────────────────────────────────

def _get_wind_data(skeleton) -> dict:
    return state_io.get_state_data(skeleton, _STATE_KEY) or {}


def _set_wind_data(skeleton, data: dict) -> None:
    state_io.set_state_data(skeleton, _STATE_KEY, data)


# ── config 块读写（Shape Key 列表、乐器设置）──────────────────

def get_force_shape_keys(skeleton) -> list[str]:
    data = _get_wind_data(skeleton)
    return data.get("config", {}).get("force_shape_keys", [])


def set_force_shape_keys(skeleton, names: list[str]) -> None:
    data = _get_wind_data(skeleton)
    config = data.setdefault("config", {})
    config["force_shape_keys"] = names
    _set_wind_data(skeleton, data)


def get_instrument_shape_keys(skeleton) -> list[str]:
    data = _get_wind_data(skeleton)
    return data.get("config", {}).get("instrument_shape_keys", [])


def set_instrument_shape_keys(skeleton, names: list[str]) -> None:
    data = _get_wind_data(skeleton)
    config = data.setdefault("config", {})
    config["instrument_shape_keys"] = names
    _set_wind_data(skeleton, data)


# ── note_info 单条读写 ─────────────────────────────────────────

def _get_note_entry(skeleton, note_number: int) -> dict | None:
    data = _get_wind_data(skeleton)
    for item in data.get("note_info", []):
        if item and item.get("note") == note_number:
            return item
    return None


def _set_note_entry(skeleton, note_number: int, entry: dict) -> None:
    data = _get_wind_data(skeleton)
    note_info = data.setdefault("note_info", [])
    for i, item in enumerate(note_info):
        if item and item.get("note") == note_number:
            note_info[i] = entry
            _set_wind_data(skeleton, data)
            return
    note_info.append(entry)
    _set_wind_data(skeleton, data)


# ── Shape Key 辅助 ────────────────────────────────────────────

def _collect_nonzero_shape_keys(mesh_obj, sk_names: list[str]) -> list[dict]:
    result = []
    if not mesh_obj or not mesh_obj.data.shape_keys:
        return result
    for idx, name in enumerate(sk_names):
        kb = mesh_obj.data.shape_keys.key_blocks.get(name)
        if kb and abs(kb.value) > 0.000001:
            result.append(
                {"shape_key_index": idx, "value": round(kb.value, 6)})
    return result


def _apply_shape_keys(mesh_obj, sk_values: list[dict], sk_names: list[str]) -> None:
    """先全部归零，再按记录值设置。"""
    if not mesh_obj or not mesh_obj.data.shape_keys:
        return
    key_blocks = mesh_obj.data.shape_keys.key_blocks
    for kb in key_blocks:
        kb.value = 0.0
    for entry in sk_values:
        idx = entry.get("shape_key_index")
        val = entry.get("value", 0.0)
        if sk_names and 0 <= idx < len(sk_names):
            kb = key_blocks.get(sk_names[idx])
            if kb:
                kb.value = val
        elif 0 <= idx < len(key_blocks):
            key_blocks[idx].value = val


# ── Save / Load ───────────────────────────────────────────────

def save_note_state(note_number: int, suffix: str,
                    skeleton, lip_mesh, instrument_mesh) -> None:
    """把当前控件位置/旋转与 Shape Key 保存到骨骼 JSON 的指定音高条目。"""
    if skeleton is None:
        raise ValueError("请先选择目标骨骼")

    controllers = {}
    for short in iter_hand_controllers():
        full_name = performer_utils_resolve(short, suffix)
        obj = bpy.data.objects.get(full_name)
        if obj is None:
            continue
        true_loc = state_io.get_true_transform_value(obj, "location")
        true_rot = state_io.get_true_transform_value(obj, "rotation")
        controllers[short] = {
            "location": [true_loc.x, true_loc.y, true_loc.z],
            "rotation": [true_rot.w, true_rot.x, true_rot.y, true_rot.z],
        }

    force_sk_names = get_force_shape_keys(skeleton)
    inst_sk_names = get_instrument_shape_keys(skeleton)

    entry = {
        "note": note_number,
        "name": midi_to_name(note_number),
        "controllers": controllers,
        "character_shape_keys": _collect_nonzero_shape_keys(lip_mesh, force_sk_names),
        "instrument_shape_keys": (
            _collect_nonzero_shape_keys(instrument_mesh, inst_sk_names)
            if instrument_mesh else []
        ),
    }
    _set_note_entry(skeleton, note_number, entry)


def load_note_state(note_number: int, suffix: str,
                    skeleton, lip_mesh, instrument_mesh) -> None:
    """从骨骼 JSON 指定音高条目恢复控件位置/旋转与 Shape Key。"""
    if skeleton is None:
        raise ValueError("请先选择目标骨骼")

    entry = _get_note_entry(skeleton, note_number)
    if entry is None:
        raise ValueError(f"音高 {midi_to_name(note_number)} 无已保存数据，请先保存")

    # 控制器
    controllers = entry.get("controllers", {})
    for short in iter_hand_controllers():
        ctrl_data = controllers.get(short)
        if ctrl_data is None:
            continue
        full_name = performer_utils_resolve(short, suffix)
        obj = bpy.data.objects.get(full_name)
        if obj is None:
            continue
        loc = ctrl_data.get("location")
        rot = ctrl_data.get("rotation")
        if loc and len(loc) == 3:
            obj.lock_location[:] = [False, False, False]
            obj.location = (loc[0], loc[1], loc[2])
        if rot and len(rot) == 4:
            obj.lock_rotation[:] = [False, False, False]
            if obj.rotation_mode == "QUATERNION":
                obj.rotation_quaternion = Quaternion(
                    (rot[0], rot[1], rot[2], rot[3]))
            else:
                obj.rotation_euler = Quaternion(
                    (rot[0], rot[1], rot[2], rot[3])).to_euler(obj.rotation_mode)

    # Shape Key
    force_sk_names = get_force_shape_keys(skeleton)
    inst_sk_names = get_instrument_shape_keys(skeleton)
    _apply_shape_keys(lip_mesh, entry.get("character_shape_keys") or [],
                      force_sk_names)
    if instrument_mesh:
        _apply_shape_keys(instrument_mesh,
                          entry.get("instrument_shape_keys") or [],
                          inst_sk_names)


# 延迟 import 避免循环（仅在函数内使用）
def performer_utils_resolve(short: str, suffix: str) -> str:
    from ..common import performer_utils
    return performer_utils.resolve(short, suffix)
