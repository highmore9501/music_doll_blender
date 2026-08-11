# harp_glide/tools/__init__.py
"""HarpGlide 乐器专属工具列表"""

from ..tools.string_tools import (
    draw_create_string_shape_key,
    draw_create_all_strings_shape_keys,
    draw_linear_distribute,
)
from ...common.tools import ToolDef

INSTRUMENT_TOOLS: list[ToolDef] = [
    ToolDef(
        id="harp_create_string_shape_key",
        label="生成弦 Shape Key",
        operator="harp_glide.create_string_shape_key",
        icon="CURVE_DATA",
        draw=draw_create_string_shape_key,
    ),
    ToolDef(
        id="harp_create_all_strings_shape_keys",
        label="批量生成所有弦 Shape Key",
        operator="harp_glide.create_all_strings_shape_keys",
        icon="CURVE_DATA",
        draw=draw_create_all_strings_shape_keys,
    ),
    ToolDef(
        id="harp_linear_distribute",
        label="线性分布弦位置",
        operator="harp_glide.linear_distribute_recorders",
        icon="ARROW_LEFTRIGHT",
        draw=draw_linear_distribute,
    ),
]
