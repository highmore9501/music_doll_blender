# wind_rise/io.py
"""WindRise 乐器模块 —— .wind 文件导入/导出"""

import json
import os

from ..common import io_utils
from ..common import state_io
from .enums import midi_to_name
from .state import (
    _get_wind_data,
    _set_wind_data,
    get_force_shape_keys,
    get_instrument_shape_keys,
    set_force_shape_keys,
    set_instrument_shape_keys,
)

_STATE_KEY = "wind_rise_state_data"


def _normalize_wind_path(path: str) -> str:
    if not path:
        raise ValueError("请先设置人物信息路径")
    if not path.endswith(".wind"):
        path = os.path.splitext(path)[0] + ".wind"
    return path


def export_wind(file_path: str, skeleton, min_note: int, max_note: int,
                for_unreal: bool = False) -> str:
    """从骨骼 JSON 全量读出，写入 .wind 文件。

    for_unreal=True 时坐标转换为 Unreal 空间，is_unreal 字段随之置 True。
    """
    _pos = io_utils.to_unreal_position if for_unreal else (lambda p: p)
    _rot = io_utils.to_unreal_rotation if for_unreal else (lambda r: r)

    if skeleton is None:
        raise ValueError("请先选择目标骨骼")

    file_path = _normalize_wind_path(file_path)

    data = _get_wind_data(skeleton)
    config = data.get("config", {})

    # 保证 note_info 覆盖完整音域（无记录的填空条目）
    saved = {item["note"]: item for item in data.get("note_info", []) if item}
    note_info = []
    for note_num in range(min_note, max_note + 1):
        if note_num in saved:
            entry = dict(saved[note_num])
            entry["character_shape_keys"] = entry.get(
                "character_shape_keys") or []
            entry["instrument_shape_keys"] = entry.get(
                "instrument_shape_keys") or []
            if for_unreal:
                raw_ctrls = entry.get("controllers", {})
                entry["controllers"] = {
                    k: {
                        "location": _pos(v.get("location", [0, 0, 0])),
                        "rotation": _rot(v.get("rotation", [1, 0, 0, 0])),
                    }
                    for k, v in raw_ctrls.items()
                }
            note_info.append(entry)
        else:
            note_info.append({
                "note": note_num,
                "name": midi_to_name(note_num),
                "controllers": {},
                "character_shape_keys": [],
                "instrument_shape_keys": [],
            })

    export_data = {"config": config,
                   "is_unreal": for_unreal, "note_info": note_info}
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    return file_path


def import_wind(file_path: str, skeleton) -> dict:
    """从 .wind 文件读入，全量写入骨骼 JSON，返回 config 供 UI 回填。"""
    if skeleton is None:
        raise ValueError("请先选择目标骨骼")
    if not file_path:
        raise ValueError("请先设置人物信息路径")
    if not file_path.endswith(".wind"):
        raise ValueError("请选择 .wind 文件")
    if not os.path.exists(file_path):
        raise ValueError(f"文件不存在：{file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        file_data = json.load(f)

    config = file_data.get("config", {})
    note_info = file_data.get("note_info", [])
    if not isinstance(note_info, list):
        raise ValueError(".wind 文件缺少有效的 note_info")

    # 保留骨骼上已有的 config 字段，仅覆盖文件中存在的键
    existing = _get_wind_data(skeleton)
    existing_config = existing.get("config", {})
    existing_config.update(config)

    write_data = {
        "config": existing_config,
        "note_info": [item for item in note_info if isinstance(item, dict)],
    }
    _set_wind_data(skeleton, write_data)

    return existing_config
