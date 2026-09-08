# beat_bloom/tools/__init__.py
"""BeatBloom 乐器独有工具"""

from ...common import i18n
from ...common.tools import ToolDef
from . import export_to_unreal
from . import cleanup_legacy_state

T = i18n.T

INSTRUMENT_TOOLS: list[ToolDef] = [
    ToolDef(
        id="beat_bloom_cleanup_legacy_state",
        label=T("清理残留 state"),
        operator="music_doll.beat_bloom_cleanup_legacy_state",
        icon="TRASH",
        draw=cleanup_legacy_state.draw,
    ),
]


def register():
    export_to_unreal.register()
    cleanup_legacy_state.register()


def unregister():
    cleanup_legacy_state.unregister()
    export_to_unreal.unregister()
