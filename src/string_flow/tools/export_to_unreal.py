# string_flow/tools/export_to_unreal.py
"""StringFlow 独有工具 —— 导出 Unreal 格式 .violinist 文件

复用同一导出方法 export_recorder_info(file_path, config, skeleton, for_unreal=True)：
- 坐标 Y 轴取反（common.io_utils.to_unreal_position）；
- 旋转取反射共轭 [w,-x,y,-z]（common.io_utils.to_unreal_rotation）；
- config.is_unreal 置 True（Rust 端据此翻转指板平面法线方向）。
参照 zheng_drift/tools/export_to_unreal.py 的实现模式。
"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import StringProperty  # type: ignore
from bpy_extras.io_utils import ExportHelper  # type: ignore

from ...common import i18n
T = i18n.T
bl_label_set = i18n.bl_label_set


class STRINGFLOW_OT_export_to_unreal(Operator, ExportHelper):
    """导出 .violinist（Unreal 引擎格式：坐标 Y 轴取反、旋转取反射共轭，is_unreal=true）"""
    bl_idname = "music_doll.string_flow_export_to_unreal"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".violinist"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.violinist", options={'HIDDEN'})
    }

    def execute(self, context):
        from ..ui import _get_active_skeleton, _get_active_suffix, _get_string_flow_config
        from ..io import export_recorder_info

        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}

        config = _get_string_flow_config(
            context.scene.stringflow_props,
            suffix=_get_active_suffix(context), skeleton=skel)

        try:
            export_recorder_info(self.filepath, config, skel, for_unreal=True)
            self.report({'INFO'}, T("已导出 Unreal 格式 → %s") % self.filepath)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, T("导出失败：%s") % str(e))
            return {'CANCELLED'}


def register():
    bl_label_set(STRINGFLOW_OT_export_to_unreal, "导出到 Unreal")
    bpy.utils.register_class(STRINGFLOW_OT_export_to_unreal)


def unregister():
    bpy.utils.unregister_class(STRINGFLOW_OT_export_to_unreal)
