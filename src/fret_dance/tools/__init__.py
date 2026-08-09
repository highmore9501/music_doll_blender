# fret_dance/tools/__init__.py
"""FretDance 乐器独有工具

- 公共工具在 common/tools/（所有乐器共用，如修正手指骨骼）；
- 本目录只放 FretDance 独有的工具。
"""

import bpy  # type: ignore

from ...common.tools import ToolDef

from . import strings


def _draw_create_string(layout, scene):
    """生成弦工具的参数区：操作提示 + 参数（弦序号 / 振幅）

    与 create_string_with_shape_keys() 的使用要求一致：
    先选中两个对象（起点 → 终点）定义弦的起止位置，再生成弦与 shape key。
    """
    col = layout.column(align=True)
    col.label(text="提示：请先选中两个对象（起点 → 终点）定义弦的位置",
              icon="INFO")
    col.label(text="① 物体模式：选中「起点」和「终点」两个对象（且仅这两个）")
    col.label(text="② 设置下方「弦序号」与「振幅」")
    col.label(text="③ 点击下方按钮，生成弦并创建 0~20 品 shape key")
    col.separator()
    col.prop(scene, "fret_dance_string_number", text="弦序号")
    col.prop(scene, "fret_dance_string_amplitude", text="振幅")


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
