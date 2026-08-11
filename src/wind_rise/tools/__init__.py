# wind_rise/tools/__init__.py
"""WindRise 专属工具列表"""

from ...common.tools import ToolDef
from . import axis_rotation_tool
from . import export_to_unreal


def _draw_axis_rot(layout, scene):
    axis_rotation_tool.draw_axis_rotation_panel(layout)


def _draw_axis_move(layout, scene):
    axis_rotation_tool.draw_axis_move_panel(layout)


INSTRUMENT_TOOLS: list[ToolDef] = [
    ToolDef(
        id="wind_rise_axis_rotation",
        label="轴旋转工具",
        operator="",
        icon="ORIENTATION_LOCAL",
        draw=_draw_axis_rot,
    ),
    ToolDef(
        id="wind_rise_axis_move",
        label="轴移动工具",
        operator="",
        icon="ORIENTATION_GLOBAL",
        draw=_draw_axis_move,
    ),
]


def register():
    axis_rotation_tool.register()
    export_to_unreal.register()


def unregister():
    export_to_unreal.unregister()
    axis_rotation_tool.unregister()
