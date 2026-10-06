# wind_rise/tools/__init__.py
"""WindRise 专属工具列表

轴旋转 / 轴移动已提升为公共工具（common/tools/axis_transform.py），
不在本列表中重复声明。
"""

from ...common import i18n
from ...common.tools import ToolDef
from . import export_to_unreal

T = i18n.T


INSTRUMENT_TOOLS: list[ToolDef] = []


def register():
    export_to_unreal.register()


def unregister():
    export_to_unreal.unregister()
