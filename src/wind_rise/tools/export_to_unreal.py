# wind_rise/tools/export_to_unreal.py
"""WindRise 独有工具 —— 导出 Unreal 格式 .wind 文件"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import StringProperty  # type: ignore
from bpy_extras.io_utils import ExportHelper  # type: ignore

from ...common import i18n
T = i18n.T
bl_label_set = i18n.bl_label_set


class WR_OT_export_to_unreal(Operator, ExportHelper):
    """导出 .wind（Unreal 引擎格式：坐标 ×100，Y 轴取反，旋转取共轭）"""
    bl_idname = "music_doll.wind_rise_export_to_unreal"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".wind"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.wind", options={'HIDDEN'})
    }

    def execute(self, context):
        from ..ui import _skeleton
        from ..io import export_wind

        skel = _skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        props = context.scene.md_wr_props
        try:
            instrument_type = (
                props.custom_instrument_type
                if props.instrument_type == "custom"
                else props.instrument_type
            )
            export_wind(
                self.filepath,
                skel,
                props.min_note,
                props.max_note,
                for_unreal=True,
                instrument_type=instrument_type,
            )
            self.report({'INFO'}, f"已导出 Unreal 格式 → {self.filepath}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"导出失败：{e}")
            return {'CANCELLED'}


def register():
    bl_label_set(WR_OT_export_to_unreal, "导出到 Unreal")
    bpy.utils.register_class(WR_OT_export_to_unreal)


def unregister():
    bpy.utils.unregister_class(WR_OT_export_to_unreal)
