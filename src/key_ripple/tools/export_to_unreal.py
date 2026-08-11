# key_ripple/tools/export_to_unreal.py
"""KeyRipple 独有工具 —— 导出 Unreal 格式 .avatar 文件"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import StringProperty  # type: ignore
from bpy_extras.io_utils import ExportHelper  # type: ignore


class KEYRIPPLE_OT_export_to_unreal(Operator, ExportHelper):
    """导出 .avatar（Unreal 引擎格式：坐标 ×100，Y 轴取反，旋转取共轭）"""
    bl_idname = "music_doll.key_ripple_export_to_unreal"
    bl_label = "导出到 Unreal"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".avatar"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.avatar", options={'HIDDEN'})
    }

    def execute(self, context):
        from ..ui import _get_active_skeleton, _get_active_suffix, _get_key_ripple
        from ..io import export_avatar

        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        props = context.scene.keyripple_props
        suffix = _get_active_suffix(context)
        key_ripple = _get_key_ripple(props, suffix=suffix, skeleton=skel)
        path = self.filepath

        try:
            export_avatar(path, key_ripple, skel, for_unreal=True)
            self.report({'INFO'}, f"已导出 Unreal 格式 → {path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"导出失败：{e}")
            return {'CANCELLED'}


def register():
    bpy.utils.register_class(KEYRIPPLE_OT_export_to_unreal)


def unregister():
    bpy.utils.unregister_class(KEYRIPPLE_OT_export_to_unreal)
