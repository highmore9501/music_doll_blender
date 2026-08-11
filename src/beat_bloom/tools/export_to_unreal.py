# beat_bloom/tools/export_to_unreal.py
"""BeatBloom 独有工具 —— 导出 Unreal 格式 .drummer 文件"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import StringProperty  # type: ignore
from bpy_extras.io_utils import ExportHelper  # type: ignore


class BB_OT_export_to_unreal(Operator, ExportHelper):
    """导出 .drummer（Unreal 引擎格式：坐标 ×100，Y 轴取反，旋转取共轭）"""
    bl_idname = "music_doll.beat_bloom_export_to_unreal"
    bl_label = "导出到 Unreal"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".drummer"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.drummer", options={'HIDDEN'})
    }

    def execute(self, context):
        from ..ui import _get_active_skeleton, _get_drumkit
        from ..io import export_drummer

        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        dk = _get_drumkit(context)
        if not dk:
            self.report({'ERROR'}, "请先加载 Drumkit 配置")
            return {'CANCELLED'}

        try:
            export_drummer(self.filepath, skel, dk, for_unreal=True)
            self.report({'INFO'}, f"已导出 Unreal 格式 → {self.filepath}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"导出失败：{e}")
            return {'CANCELLED'}


def register():
    bpy.utils.register_class(BB_OT_export_to_unreal)


def unregister():
    bpy.utils.unregister_class(BB_OT_export_to_unreal)
