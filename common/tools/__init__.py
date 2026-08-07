# common/tools/__init__.py
"""公共工具框架 —— 所有乐器共用的工具注册与界面

- ToolDef: 一个工具的元信息（id / label / 执行算子 / 参数区绘制）；
- COMMON_TOOLS: 公共工具列表（所有乐器下拉菜单都显示）；
- 每个乐器的工具列表 = COMMON_TOOLS + 该乐器独有工具。
"""

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolDef:
    """工具定义

    :param id: 唯一 id（字符串），如 "fix_finger_bones"
    :param label: 下拉显示名，如 "修正手指骨骼"
    :param operator: 执行算子的 bl_idname，如 "music_doll.tool_fix_finger_bones"
    :param icon: 图标名（可选）
    :param draw: 可选参数区绘制函数 draw(layout, context, scene)（选中后显示）
    """
    id: str
    label: str
    operator: str
    icon: str = "TOOL_SETTINGS"
    draw: Callable = None


def find_tool(tools: list[ToolDef], tool_id: str) -> ToolDef | None:
    """按 id 在工具列表里查找工具定义。"""
    for t in tools:
        if t.id == tool_id:
            return t
    return None


# ── 公共工具注册表（所有乐器共用）─────────────────────────────
# 每个公共工具需提供自己的执行算子（bl_idname = "music_doll.tool_<id>"）。

COMMON_TOOLS: list[ToolDef] = [
    ToolDef(
        id="fix_finger_bones",
        label="修正手指骨骼",
        operator="music_doll.tool_fix_finger_bones",
        icon="BONE_DATA",
    ),
]
