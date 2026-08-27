# key_ripple/tools/__init__.py
"""KeyRipple 乐器独有工具

- 公共工具在 common/tools/（所有乐器共用，如修正手指骨骼）；
- 本目录只放 KeyRipple 独有的工具。
"""

import bpy  # type: ignore

from ...common import i18n
from ...common.tools import ToolDef
from ...common.i18n import T

from . import make_shape_keys
from . import export_to_unreal


def _draw_make_shape_keys(layout, scene):
    """为钢琴键创建 shape keys 工具的参数区（无参数，仅说明）"""
    layout.label(text=T("为选中钢琴键创建 Basis + pressed shape keys"))


# 该乐器独有的工具列表（下拉 = 公共工具 + 本列表）
INSTRUMENT_TOOLS: list[ToolDef] = [
    ToolDef(
        id="key_ripple_make_shape_keys",
        label=T("为钢琴键创建 Shape Keys"),
        operator="music_doll.tool_key_ripple_make_shape_keys",
        icon="SHAPEKEY_DATA",
        draw=_draw_make_shape_keys,
    ),
]


def register():
    make_shape_keys.register()
    export_to_unreal.register()


def unregister():
    export_to_unreal.unregister()
    make_shape_keys.unregister()
