# fret_dance/tools/export_to_unreal.py
"""FretDance 独有工具 —— 导出 Unreal 格式人物信息

弹出文件浏览器让用户选择路径，调用 export_controller_info(for_unreal=True)。
"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import StringProperty  # type: ignore
from bpy_extras.io_utils import ExportHelper  # type: ignore

from ...common import i18n
T = i18n.T
bl_label_set = i18n.bl_label_set


class FRET_DANCE_OT_export_to_unreal(Operator, ExportHelper):
    """导出人物信息（Unreal 引擎格式：坐标 ×100，Y 轴取反，旋转取共轭）"""
    bl_idname = "music_doll.fret_dance_export_to_unreal"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.json", options={'HIDDEN'})
    }

    def execute(self, context):
        from ..ui import _build_base_state, _get_active_skeleton

        skeleton = _get_active_skeleton(context)
        if skeleton is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}

        base_state = _build_base_state(context)
        path = self.filepath
        if not path.endswith(".json"):
            path += ".json"

        try:
            base_state.export_controller_info(path, skeleton, for_unreal=True)
            self.report({'INFO'}, T("已导出 Unreal 格式 → %s") % path)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, T("导出失败：%s") % e)
            return {'CANCELLED'}


def register():
    bl_label_set(FRET_DANCE_OT_export_to_unreal, "导出到 Unreal")
    bpy.utils.register_class(FRET_DANCE_OT_export_to_unreal)


def unregister():
    bpy.utils.unregister_class(FRET_DANCE_OT_export_to_unreal)
