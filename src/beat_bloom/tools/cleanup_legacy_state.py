# beat_bloom/tools/cleanup_legacy_state.py
"""BeatBloom 专用小工具：清理旧版残留 state 键（H_rotation_* / F_rotation_*）。"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore

from ...common import i18n
from ..state import cleanup_legacy_state as _cleanup_legacy_state

T = i18n.T
bl_label_set = i18n.bl_label_set


class BB_OT_cleanup_legacy_state(Operator):
    """删除骨骼中残留的旧版 Rotation 拆分键，保留新 H_L/H_R/F_L/F_R 结构。"""
    bl_idname = "music_doll.beat_bloom_cleanup_legacy_state"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        skel = context.object if context.object is not None and context.object.type == "ARMATURE" else None
        if skel is None:
            self.report({'ERROR'}, T("请先选中目标骨骼"))
            return {'CANCELLED'}

        removed = _cleanup_legacy_state(skel)
        if removed == 0:
            self.report({'INFO'}, T("骨骼中没有残留的旧 state 键"))
        else:
            self.report({'INFO'}, T("已清理 %d 个旧版残留 state 键") % removed)
        return {'FINISHED'}


def draw(layout, scene):
    col = layout.column(align=True)
    col.label(text=T("说明：清理旧版 H_rotation_* / F_rotation_* 残留键"), icon="INFO")
    col.label(text=T("只保留新格式：H_L / H_R / F_L / F_R"))
    col.label(text=T("这个操作不会修改当前的新状态结构"))


def register():
    bl_label_set(BB_OT_cleanup_legacy_state, "清理残留 state")
    bpy.utils.register_class(BB_OT_cleanup_legacy_state)


def unregister():
    if hasattr(bpy.types, BB_OT_cleanup_legacy_state.__name__):
        bpy.utils.unregister_class(BB_OT_cleanup_legacy_state)
