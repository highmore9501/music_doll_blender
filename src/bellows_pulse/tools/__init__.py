# bellows_pulse/tools/__init__.py
"""BellowsPulse 乐器独有工具

- 公共工具在 `common/tools/`（修正手指骨骼、骨骼/控制器映射、轴旋转/移动），
  所有乐器共用；
- 本目录放 BellowsPulse 独有的工具。现在只有「导出到 Unreal」（面板上是按钮，
  不进工具下拉）；键区记录器排列检查、按键 shape key 生成等之后再补。
"""

from ...common.tools import ToolDef

from . import export_to_unreal

#: 本乐器独有的工具列表（面板工具下拉 = COMMON_TOOLS + 本列表）
INSTRUMENT_TOOLS: list[ToolDef] = []


def register() -> None:
    """注册本乐器独有的工具算子。"""
    export_to_unreal.register()


def unregister() -> None:
    """注销本乐器独有的工具算子（与注册逆序）。"""
    export_to_unreal.unregister()
