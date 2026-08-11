# zheng_drift/tools/__init__.py
"""ZhengDrift 乐器独有工具

- 公共工具在 common/tools/（所有乐器共用，如修正手指骨骼）；
- 本目录只放 ZhengDrift 独有的工具：弦 Shape Key 生成 / 线性分布记录器。
"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import IntProperty, FloatProperty  # type: ignore

from ...common import ui_utils
from ...common.tools import ToolDef

from . import string_tools
from . import export_to_unreal


# ── 工具参数区场景属性（幂等注册） ─────────────────────────

def register_tool_scene_props():
    if not hasattr(bpy.types.Scene, "zheng_string_index"):
        bpy.types.Scene.zheng_string_index = IntProperty(
            name="弦序号",
            description="弦的索引（0-20）",
            default=10,
            min=0,
            max=20,
        )
    if not hasattr(bpy.types.Scene, "zheng_string_amplitude"):
        bpy.types.Scene.zheng_string_amplitude = FloatProperty(
            name="振幅比例",
            description="弦振动的偏移比例（实际偏移 = 弦长 * 比例）",
            default=0.005,
            min=0.0001,
            max=0.1,
            precision=4,
            step=0.0001,
        )


def unregister_tool_scene_props():
    for name in ("zheng_string_amplitude", "zheng_string_index"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


def _active_suffix(context) -> str:
    return ui_utils.get_active_suffix(context.scene)


# ── 执行算子 ─────────────────────────────────────────────────

class ZHENG_OT_tool_create_string_shape_key(Operator):
    """为指定弦生成右手摇指 + 左手按弦的 Shape Key"""
    bl_idname = "music_doll.tool_zheng_create_string_shape_key"
    bl_label = "生成弦 Shape Key"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        try:
            string_tools.create_string_shape_key(
                int(scene.zheng_string_index),
                scene.zheng_string_amplitude,
                suffix=_active_suffix(context))
            self.report(
                {'INFO'}, f"String {scene.zheng_string_index} shape key created")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to create shape key: {str(e)}")
            return {'CANCELLED'}


class ZHENG_OT_tool_create_all_strings_shape_keys(Operator):
    """为所有 21 根弦生成 Shape Key"""
    bl_idname = "music_doll.tool_zheng_create_all_strings_shape_keys"
    bl_label = "生成所有弦 Shape Key"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        try:
            string_tools.create_all_strings_shape_keys(
                scene.zheng_string_amplitude, suffix=_active_suffix(context))
            self.report({'INFO'}, "All 21 strings shape keys created")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to create shape keys: {str(e)}")
            return {'CANCELLED'}


class ZHENG_OT_tool_linear_distribute_recorders(Operator):
    """在选中的两个端点记录器之间线性分布所有记录器"""
    bl_idname = "music_doll.tool_zheng_linear_distribute_recorders"
    bl_label = "线性分布记录器"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            string_tools.linear_distribute_recorders()
            self.report({'INFO'}, "Recorder linear distribution completed")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Linear distribution failed: {str(e)}")
            return {'CANCELLED'}


# ── 工具参数区绘制 ───────────────────────────────────────────

def _draw_string_shape_key(layout, scene):
    """弦 Shape Key 工具的参数区（弦序号 + 振幅）"""
    split_row = layout.row()
    split_row.split(factor=0.6)
    col = split_row.column()
    col.prop(scene, "zheng_string_index", text="弦序号")
    col = split_row.column()
    col.prop(scene, "zheng_string_amplitude", text="振幅")
    layout.label(text="先选中弦（或用弦序号），再执行；需先 Setup 并定位弦记录器",
                 icon="INFO")


def _draw_linear_distribute(layout, scene):
    """线性分布工具的参数区：使用提示"""
    layout.label(text="提示：先选中两个端点记录器（如 s0head / s20head），再执行",
                 icon="INFO")
    layout.label(text="将把该序号范围内的所有记录器线性分布在两端点之间")


# 该乐器独有的工具列表（下拉 = 公共工具 + 本列表）
INSTRUMENT_TOOLS: list[ToolDef] = [
    ToolDef(
        id="zheng_string_shape_key",
        label="生成弦 Shape Key",
        operator="music_doll.tool_zheng_create_string_shape_key",
        icon="SHAPEKEY_DATA",
        draw=_draw_string_shape_key,
    ),
    ToolDef(
        id="zheng_all_strings_shape_keys",
        label="生成所有弦 Shape Key",
        operator="music_doll.tool_zheng_create_all_strings_shape_keys",
        icon="SHAPEKEY_DATA",
        draw=_draw_string_shape_key,
    ),
    ToolDef(
        id="zheng_linear_distribute_recorders",
        label="线性分布记录器",
        operator="music_doll.tool_zheng_linear_distribute_recorders",
        icon="ARROW_LEFTRIGHT",
        draw=_draw_linear_distribute,
    ),
]


# ── 注册/注销 ────────────────────────────────────────────────

def register():
    register_tool_scene_props()
    export_to_unreal.register()
    bpy.utils.register_class(ZHENG_OT_tool_create_string_shape_key)
    bpy.utils.register_class(ZHENG_OT_tool_create_all_strings_shape_keys)
    bpy.utils.register_class(ZHENG_OT_tool_linear_distribute_recorders)


def unregister():
    bpy.utils.unregister_class(ZHENG_OT_tool_linear_distribute_recorders)
    bpy.utils.unregister_class(ZHENG_OT_tool_create_all_strings_shape_keys)
    bpy.utils.unregister_class(ZHENG_OT_tool_create_string_shape_key)
    export_to_unreal.unregister()
    unregister_tool_scene_props()
