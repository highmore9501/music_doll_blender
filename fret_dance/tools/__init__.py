# fret_dance/tools/__init__.py
"""FretDance 乐器独有工具

- 公共工具在 common/tools/（所有乐器共用，如修正手指骨骼）；
- 本目录只放 FretDance 独有的工具。
"""

import bpy  # type: ignore

from ...common.tools import ToolDef

from . import strings


def _draw_create_string(layout, scene):
    """生成弦工具的参数区（弦序号 / 振幅）"""
    layout.prop(scene, "fret_dance_string_number", text="弦序号")
    layout.prop(scene, "fret_dance_string_amplitude", text="振幅")


# 该乐器独有的工具列表（下拉 = 公共工具 + 本列表）
INSTRUMENT_TOOLS: list[ToolDef] = [
    ToolDef(
        id="fret_dance_create_string",
        label="生成弦（shape key）",
        operator="music_doll.tool_fret_dance_create_string",
        icon="MOD_SIMPLEDEFORM",
        draw=_draw_create_string,
    ),
]


def register():
    strings.register()


def unregister():
    strings.unregister()
