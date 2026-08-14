# string_flow/tools/__init__.py
"""StringFlow 乐器独有工具

- 公共工具在 common/tools/（所有乐器共用，如修正手指骨骼）；
- 本目录只放 StringFlow 独有的工具：琴弦生成（一键创建琴弦 / 生成ShapeKey）
  + 导出到 Unreal（ExportHelper，注册后由面板「导入/导出」区直接调用）。
"""

import bpy  # type: ignore
from bpy.types import Operator  # type: ignore
from bpy.props import IntProperty, FloatProperty, BoolProperty  # type: ignore

from ...common import ui_utils
from ...common.tools import ToolDef

from . import make_violin_string
from . import export_to_unreal


# ── 工具参数区场景属性（幂等注册） ─────────────────────────

def register_tool_scene_props():
    if not hasattr(bpy.types.Scene, "string_flow_string_index"):
        bpy.types.Scene.string_flow_string_index = IntProperty(
            name="弦号",
            description="要生成/处理的弦编号（0-10）",
            default=0,
            min=0,
            max=10,
        )
    if not hasattr(bpy.types.Scene, "string_flow_offset_ratio"):
        bpy.types.Scene.string_flow_offset_ratio = FloatProperty(
            name="偏移比例",
            description="琴弦 shape key 的偏移比例（原版 UI 引用但属性缺失，此处补齐）",
            default=0.005,
            min=0.0,
            max=1.0,
            precision=4,
        )
    if not hasattr(bpy.types.Scene, "string_flow_reverse_frets"):
        bpy.types.Scene.string_flow_reverse_frets = BoolProperty(
            name="反序遍历品格",
            description="是否反序遍历品格（正序：fret1→fret20；反序：fret20→fret1）",
            default=False,
        )


def unregister_tool_scene_props():
    for name in ("string_flow_reverse_frets", "string_flow_offset_ratio",
                 "string_flow_string_index"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


def _active_suffix(context) -> str:
    return ui_utils.get_active_suffix(context.scene)


# ── 执行算子 ─────────────────────────────────────────────────

class STRINGFLOW_OT_tool_create_violin_string(Operator):
    """一键创建琴弦：选两个端点对象 → 创建弦 + 自动细分 + 全部 shape keys"""
    bl_idname = "music_doll.tool_string_flow_create_violin_string"
    bl_label = "一键创建琴弦"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        try:
            make_violin_string.make_violin_string_shape_keys(
                offset_ratio=scene.string_flow_offset_ratio,
                number=int(scene.string_flow_string_index),
                reverse_frets=scene.string_flow_reverse_frets,
                suffix=_active_suffix(context))
            self.report(
                {'INFO'}, f"琴弦 {int(scene.string_flow_string_index)} 已全部完成！"
                          f"自动生成了所有shape keys")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"创建失败: {str(e)}")
            return {'CANCELLED'}


class STRINGFLOW_OT_tool_generate_shape_keys(Operator):
    """为已细分好的琴弦生成 shape keys"""
    bl_idname = "music_doll.tool_string_flow_generate_shape_keys"
    bl_label = "生成ShapeKey"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        try:
            make_violin_string.generate_shape_keys_for_string(
                reverse_frets=scene.string_flow_reverse_frets,
                suffix=_active_suffix(context))
            self.report({'INFO'}, "ShapeKey生成完成")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"生成失败: {str(e)}")
            return {'CANCELLED'}


# ── 工具参数区绘制 ───────────────────────────────────────────

def _draw_violin_string(layout, scene):
    """一键创建琴弦工具的参数区（弦号 + 偏移比例 + 反序）"""
    col = layout.column(align=True)
    col.prop(scene, "string_flow_string_index", text="弦号")
    col.prop(scene, "string_flow_offset_ratio", text="偏移比例")
    col.prop(scene, "string_flow_reverse_frets", text="反序")
    layout.label(text="提示：先选中两个端点对象（start / end），再执行", icon="INFO")


def _draw_generate_shape_keys(layout, scene):
    """生成ShapeKey 工具的参数区（反序）"""
    col = layout.column(align=True)
    col.prop(scene, "string_flow_reverse_frets", text="反序")
    layout.label(text="提示：先选中已细分好的琴弦对象，再执行", icon="INFO")


# 该乐器独有的工具列表（下拉 = 公共工具 + 本列表）
INSTRUMENT_TOOLS: list[ToolDef] = [
    ToolDef(
        id="string_flow_create_violin_string",
        label="一键创建琴弦",
        operator="music_doll.tool_string_flow_create_violin_string",
        icon="PLAY",
        draw=_draw_violin_string,
    ),
    ToolDef(
        id="string_flow_generate_shape_keys",
        label="生成ShapeKey",
        operator="music_doll.tool_string_flow_generate_shape_keys",
        icon="SHAPEKEY_DATA",
        draw=_draw_generate_shape_keys,
    ),
]


# ── 注册/注销 ────────────────────────────────────────────────

def register():
    register_tool_scene_props()
    export_to_unreal.register()
    bpy.utils.register_class(STRINGFLOW_OT_tool_create_violin_string)
    bpy.utils.register_class(STRINGFLOW_OT_tool_generate_shape_keys)


def unregister():
    bpy.utils.unregister_class(STRINGFLOW_OT_tool_generate_shape_keys)
    bpy.utils.unregister_class(STRINGFLOW_OT_tool_create_violin_string)
    export_to_unreal.unregister()
    unregister_tool_scene_props()
