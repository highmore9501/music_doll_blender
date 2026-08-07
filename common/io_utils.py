# common/io_utils.py
"""JSON 通用读写 —— 公共模块（对应 Unreal MusicDollCommon 的 IO 工具）

提供所有乐器共用的 JSON 文件读写、扩展名处理与嵌套字典工具。
乐器模块在此基础上定义各自的文件格式（_unreal.json / .avatar 等）。
"""

import json
import os
from collections import defaultdict


def nested_dict():
    """递归嵌套的 defaultdict，用于构建分层导出结构。"""
    return defaultdict(nested_dict)


def ensure_extension(file_path: str, ext: str) -> str:
    """确保文件路径带有指定扩展名（ext 含点，如 '.json'）。"""
    if not file_path.endswith(ext):
        file_path = os.path.splitext(file_path)[0] + ext
    return file_path


def save_json(file_path: str, data: dict) -> None:
    """把 dict 写入 JSON 文件（UTF-8，缩进 4）。"""
    output = json.dumps(data, default=list, indent=4)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(output)


def load_json(file_path: str) -> dict:
    """从 JSON 文件读取 dict；文件不存在或解析失败返回 {}。"""
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def dump_dict_to_json_str(data: dict) -> str:
    """把 dict 序列化为 JSON 字符串（存自定义属性用）。"""
    return json.dumps(data, ensure_ascii=False)


def load_dict_from_json_str(raw: str | None) -> dict:
    """从 JSON 字符串解析 dict；空/解析失败返回 {}。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
