# bellows_pulse/tools/export_to_unreal.py
"""BellowsPulse 独有工具 —— 导出 Unreal 格式的 `.accordion`

写的是同一份 `.accordion` 结构，只是把 `points` / `hands` / `pivots` 三段的位置与旋转
过一遍 `common/io_utils` 的坐标系转换（Y 轴取反、旋转反射共轭），并置 `is_unreal: true`。
目标路径由文件浏览器选（普通导出走角色操作面板的「人物信息路径」）。
"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import StringProperty  # type: ignore
from bpy_extras.io_utils import ExportHelper  # type: ignore

from ...common import i18n

T = i18n.T
bl_label_set = i18n.bl_label_set


class BELLOWS_PULSE_OT_export_to_unreal(Operator, ExportHelper):
    """导出 .accordion（Unreal 坐标系：位置 Y 取反、旋转反射共轭）"""
    bl_idname = "music_doll.bellows_pulse_export_to_unreal"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".accordion"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.accordion", options={'HIDDEN'}),
    }

    def execute(self, context):
        # 延迟导入：ui 在模块级把本工具模块拉进来，这里反向引用要放在函数里
        from ..ui import _get_active_skeleton, _get_config
        from ..io import export_accordion

        skeleton = _get_active_skeleton(context)
        if skeleton is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}

        try:
            result = export_accordion(
                self.filepath, _get_config(context, skeleton=skeleton),
                skeleton, for_unreal=True)
        except Exception as error:
            self.report({'ERROR'}, T("导出失败: %s") % str(error))
            return {'CANCELLED'}

        self.report({'INFO'}, T("已导出 Unreal 格式 → %s") % result["path"])
        return {'FINISHED'}


def register() -> None:
    bl_label_set(BELLOWS_PULSE_OT_export_to_unreal, "导出到 Unreal")
    bpy.utils.register_class(BELLOWS_PULSE_OT_export_to_unreal)


def unregister() -> None:
    bpy.utils.unregister_class(BELLOWS_PULSE_OT_export_to_unreal)
