# zheng_drift/tools/export_to_unreal.py
"""ZhengDrift 独有工具 —— 导出 Unreal 格式 .zheng_master 文件"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import StringProperty  # type: ignore
from bpy_extras.io_utils import ExportHelper  # type: ignore


class ZHENG_OT_export_to_unreal(Operator, ExportHelper):
    """导出 .zheng_master（Unreal 引擎格式：坐标 ×100，Y 轴取反，旋转取共轭）"""
    bl_idname = "music_doll.zheng_drift_export_to_unreal"
    bl_label = "导出到 Unreal"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.json", options={'HIDDEN'})
    }

    def execute(self, context):
        from ..ui import _get_active_skeleton, _get_active_suffix, _get_zheng_config
        from ..io import export_recorder_info

        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        config = _get_zheng_config(
            context.scene.zhengdrift_props, suffix=_get_active_suffix(context))

        try:
            export_recorder_info(self.filepath, config, skel, for_unreal=True)
            self.report({'INFO'}, f"已导出 Unreal 格式 → {self.filepath}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"导出失败：{e}")
            return {'CANCELLED'}


def register():
    bpy.utils.register_class(ZHENG_OT_export_to_unreal)


def unregister():
    bpy.utils.unregister_class(ZHENG_OT_export_to_unreal)
