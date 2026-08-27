# harp_glide/tools/export_to_unreal.py
"""HarpGlide 独有工具 —— 导出 Unreal 格式 .harpist 文件"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import StringProperty  # type: ignore
from bpy_extras.io_utils import ExportHelper  # type: ignore

from ...common import i18n
T = i18n.T
bl_label_set = i18n.bl_label_set


class HG_OT_export_to_unreal(Operator, ExportHelper):
    """导出 .harpist（Unreal 引擎格式：坐标 ×100，Y 轴取反，旋转取共轭）"""
    bl_idname = "harp_glide.export_to_unreal"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".harpist"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.harpist", options={'HIDDEN'})
    }

    def execute(self, context):
        from ..ui import _skeleton, _suffix
        from ..io import export_harpist

        skel = _skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        try:
            export_harpist(self.filepath, _suffix(context), skel,
                           context.scene.md_hg_props, for_unreal=True)
            self.report({'INFO'}, f"已导出 Unreal 格式 → {self.filepath}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"导出失败：{e}")
            return {'CANCELLED'}


def register():
    bl_label_set(HG_OT_export_to_unreal, "导出到 Unreal")
    bpy.utils.register_class(HG_OT_export_to_unreal)


def unregister():
    bpy.utils.unregister_class(HG_OT_export_to_unreal)
