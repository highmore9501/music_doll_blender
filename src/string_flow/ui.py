# string_flow/ui.py
"""StringFlow 乐器模块 —— 面板与算子（迁移自 string_flow_blender/__init__.py）

- 公共演奏者选择/骨骼/乐器/路径改调 common.ui_utils；
- 导入/导出用角色模块的「人物信息路径」（SCENE_INFO_PATH），不再用文件浏览器；
- 乐器面板只保留 string_flow_file_path（.string_flow 动画配置）这一个 FILE_PATH；
- 工具下拉 = 公共工具 + StringFlow 独有工具（琴弦生成）；
- 「导出到 Unreal」直接放在「导入/导出」区（ExportHelper）。
"""

import json
import os

import bpy  # type: ignore
from bpy.types import Panel, Operator, PropertyGroup  # type: ignore
from bpy.props import (  # type: ignore
    StringProperty,
    PointerProperty,
    EnumProperty,
    IntProperty,
)

from ..common import ui_utils
from ..common import performer_utils
from ..common.tools import COMMON_TOOLS

from .config import StringFlowConfig
from .enums import HandType, LeftHandPositionType, RightHandPositionType
from .state import save_hand_state, load_hand_state
from .io import export_recorder_info, import_recorder_info
from .animation import (
    make_left_hand_animation,
    make_right_hand_animation,
    apply_string_animation,
)
from .tools import INSTRUMENT_TOOLS

# 该乐器的工具列表 = 公共工具 + 乐器独有工具
TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS


# ── 演奏者/骨骼辅助（公共实现） ─────────────────────────────

def _get_active_suffix(context) -> str:
    return ui_utils.get_active_suffix(context.scene)


def _get_active_skeleton(context):
    """当前目标骨骼：优先公共场景指针，其次选中的 ARMATURE"""
    skel = ui_utils.get_target_skeleton(context)
    if skel:
        return skel
    for obj in context.selected_objects:
        if obj is not None and obj.type == "ARMATURE":
            return obj
    return None


def _get_active_instrument(context):
    """当前目标乐器：优先公共场景指针，其次当前演奏者登记的乐器"""
    inst = ui_utils.get_target_instrument(context)
    if inst:
        return inst
    suffix = _get_active_suffix(context)
    if suffix:
        p = performer_utils.get_performer(suffix)
        if p is not None and p.target_instrument is not None:
            return p.target_instrument
    return None


def _get_string_flow_config(props, suffix="", skeleton=None, instrument=None) -> StringFlowConfig:
    return StringFlowConfig(
        performer_suffix=suffix,
        target_skeleton=skeleton,
        target_instrument=instrument,
        one_hand_finger_number=props.one_hand_finger_number,
    )


def _left_position_from_props(props) -> LeftHandPositionType:
    return getattr(LeftHandPositionType, props.left_hand_position_type)


def _right_position_from_props(props) -> RightHandPositionType:
    return getattr(RightHandPositionType, props.right_hand_position_type)


def _resolve_anim_path(scene, kind: str) -> str:
    """从 .string_flow 配置解析指定类型的动画文件路径（绝对路径，原版直接使用）。

    kind: left_hand_animation_file / right_hand_animation_file / string_animation_file
    """
    file_path = scene.stringflow_props.string_flow_file_path
    if not file_path:
        return ""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
    except Exception as e:
        print(f"解析 .string_flow 配置失败：{e}")
        return ""
    return config_data.get(kind, "")


# ── 属性组 ────────────────────────────────────────────────────

class StringFlowProperties(PropertyGroup):
    """StringFlow 面板属性（初始化 + 左右手状态选择 + 动画配置路径）"""
    __annotations__ = {
        # 初始化参数
        "one_hand_finger_number": IntProperty(
            name="Finger Number",
            description="Number of fingers per hand（可调，外星人多指预留）",
            default=4,
            min=1,
            max=10,
        ),
        "string_number": IntProperty(
            name="String Number",
            description="Number of strings（小提琴固定 4 根）",
            default=4,
            min=4,
            max=4,
        ),

        # 左手状态
        "left_hand_position_type": EnumProperty(
            name="Left Hand Position Type",
            description="Position type for left hand",
            items=[
                ('NORMAL', "Normal", "Normal position"),
                ('INNER', "Inner", "Inner position"),
                ('OUTER', "Outer", "Outer position"),
            ],
            default='NORMAL',
        ),
        "left_hand_string_index": EnumProperty(
            name="Left Hand String",
            description="String index for left hand",
            items=[
                ('0', "String 0", "String 0"),
                ('3', "String 3", "String 3"),
            ],
            default='0',
        ),
        "left_hand_fret_index": EnumProperty(
            name="Left Hand Fret",
            description="Fret index for left hand",
            items=[
                ('1', "Fret 1", "Fret 1"),
                ('9', "Fret 9", "Fret 9"),
                ('12', "Fret 12", "Fret 12"),
            ],
            default='1',
        ),

        # 右手状态
        "right_hand_position_type": EnumProperty(
            name="Right Hand Position Type",
            description="Position type for right hand",
            items=[
                ('NEAR', "Near", "Near position"),
                ('FAR', "Far", "Far position"),
                ('PIZZICATO', "Pizzicato", "Pizzicato position"),
            ],
            default='NEAR',
        ),
        "right_hand_string_index": EnumProperty(
            name="Right Hand String",
            description="String index for right hand",
            items=[
                ('0', "String 0", "String 0"),
                ('1', "String 1", "String 1"),
                ('2', "String 2", "String 2"),
                ('3', "String 3", "String 3"),
            ],
            default='0',
        ),

        # .string_flow 动画配置路径（乐器面板唯一 FILE_PATH；
        # 乐器物体/人物信息路径由角色模块「角色操作」面板统一设置）
        "string_flow_file_path": StringProperty(
            name="String Flow File",
            description="Path to .string_flow file（Rust 生成的动画配置文件）",
            default="",
            subtype='FILE_PATH',
        ),
    }


# ── 算子 ──────────────────────────────────────────────────────

class STRINGFLOW_OT_check_status(Operator):
    bl_idname = "music_doll.string_flow_check_status"
    bl_label = "Check Objects Status"
    bl_description = "Check the status of all StringFlow objects"

    def execute(self, context):
        config = _get_string_flow_config(
            context.scene.stringflow_props, suffix=_get_active_suffix(context))
        config.check_all_objects()
        return {'FINISHED'}


class STRINGFLOW_OT_setup_objects(Operator):
    bl_idname = "music_doll.string_flow_setup_objects"
    bl_label = "Setup All Objects"
    bl_description = "Create all StringFlow controllers and position markers"

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        config = _get_string_flow_config(
            scene.stringflow_props, suffix=suffix,
            skeleton=_get_active_skeleton(context),
            instrument=_get_active_instrument(context))
        if not config.setup_all_objects():
            self.report(
                {'ERROR'}, "设置失败：未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）")
            return {'CANCELLED'}
        self.report({'INFO'}, "All objects have been setup")
        return {'FINISHED'}


class STRINGFLOW_OT_save_state(Operator):
    """保存左右手状态到骨骼（左手：H_L/HP_L/T_L + 全部手指；右手：H_R/HP_R/T_R
    + 全部手指 + 触弦点 + 弓）"""
    bl_idname = "music_doll.string_flow_save_state"
    bl_label = "Save State"
    bl_description = "Save current hand states to skeleton (all fingers)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.stringflow_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        config = _get_string_flow_config(
            props, suffix=_get_active_suffix(context), skeleton=skel)

        # 保存左手状态（含全部手指）
        save_hand_state(config, skel, HandType.LEFT,
                        _left_position_from_props(props),
                        int(props.left_hand_string_index),
                        int(props.left_hand_fret_index))

        # 保存右手状态（含全部手指 + 触弦点 + 弓）
        save_hand_state(config, skel, HandType.RIGHT,
                        _right_position_from_props(props),
                        int(props.right_hand_string_index))

        self.report({'INFO'}, "State has been set (left + right hand)")
        return {'FINISHED'}


class STRINGFLOW_OT_load_state(Operator):
    """从骨骼加载左右手状态到控制器（全部手指）"""
    bl_idname = "music_doll.string_flow_load_state"
    bl_label = "Load State"
    bl_description = "Load hand states from skeleton to controllers (all fingers)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.stringflow_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        config = _get_string_flow_config(
            props, suffix=_get_active_suffix(context), skeleton=skel)

        load_hand_state(config, skel, HandType.LEFT,
                        _left_position_from_props(props),
                        int(props.left_hand_string_index),
                        int(props.left_hand_fret_index))
        load_hand_state(config, skel, HandType.RIGHT,
                        _right_position_from_props(props),
                        int(props.right_hand_string_index))

        self.report(
            {"INFO"}, f"State loaded. Left position: {props.left_hand_position_type}; "
                      f"Right position: {props.right_hand_position_type}")
        return {'FINISHED'}


class STRINGFLOW_OT_export_info(Operator):
    bl_idname = "music_doll.string_flow_export_info"
    bl_label = "Export Recorder Info"
    bl_description = "Export all recorder information to .violinist JSON file"

    def execute(self, context):
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        file_path = getattr(context.scene, ui_utils.SCENE_INFO_PATH, "")
        if not file_path:
            self.report({'ERROR'}, "请先在「角色操作」面板设置人物信息路径")
            return {'CANCELLED'}
        # 确保文件扩展名为 .violinist
        if not file_path.endswith('.violinist'):
            file_path = os.path.splitext(file_path)[0] + '.violinist'

        config = _get_string_flow_config(
            context.scene.stringflow_props,
            suffix=_get_active_suffix(context), skeleton=skel)
        export_recorder_info(file_path, config, skel)
        self.report({'INFO'}, f"Recorder info exported successfully to {file_path}")
        return {'FINISHED'}


class STRINGFLOW_OT_import_info(Operator):
    bl_idname = "music_doll.string_flow_import_info"
    bl_label = "Import Recorder Info"
    bl_description = "Import all recorder information from .violinist JSON file"

    def execute(self, context):
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        file_path = getattr(context.scene, ui_utils.SCENE_INFO_PATH, "")
        if not file_path:
            self.report({'ERROR'}, "请先在「角色操作」面板设置人物信息路径")
            return {'CANCELLED'}
        if not file_path.endswith('.violinist'):
            self.report(
                {'ERROR'}, f"文件扩展名不正确，请选择 .violinist 文件（当前: {os.path.splitext(file_path)[1]}）")
            return {'CANCELLED'}

        config = _get_string_flow_config(
            context.scene.stringflow_props,
            suffix=_get_active_suffix(context), skeleton=skel)
        success = import_recorder_info(file_path, config, skel)
        if success:
            self.report({'INFO'}, f"Recorder info imported successfully from {file_path}")
            return {'FINISHED'}
        self.report({'ERROR'}, f"Failed to import recorder info from {file_path}")
        return {'CANCELLED'}


class STRINGFLOW_OT_generate_left_hand_animation(Operator):
    bl_idname = "music_doll.string_flow_generate_left_hand_animation"
    bl_label = "Generate Left Hand Animation"
    bl_description = "Generate left hand animation from .string_flow file"

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        config = _get_string_flow_config(
            scene.stringflow_props, suffix=suffix,
            skeleton=_get_active_skeleton(context))
        path = _resolve_anim_path(scene, "left_hand_animation_file")
        if not path:
            self.report({'ERROR'}, "请选择 .string_flow 文件（且包含 left_hand_animation_file）")
            return {'CANCELLED'}
        if not os.path.exists(path):
            self.report({'ERROR'}, f"左手动画文件不存在: {path}")
            return {'CANCELLED'}
        try:
            make_left_hand_animation(path, config, suffix)
            self.report({'INFO'}, "Left hand animation generated successfully")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to generate left hand animation: {str(e)}")
            return {'CANCELLED'}


class STRINGFLOW_OT_generate_right_hand_animation(Operator):
    bl_idname = "music_doll.string_flow_generate_right_hand_animation"
    bl_label = "Generate Right Hand Animation"
    bl_description = "Generate right hand animation from .string_flow file"

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        config = _get_string_flow_config(
            scene.stringflow_props, suffix=suffix,
            skeleton=_get_active_skeleton(context))
        path = _resolve_anim_path(scene, "right_hand_animation_file")
        if not path:
            self.report({'ERROR'}, "请选择 .string_flow 文件（且包含 right_hand_animation_file）")
            return {'CANCELLED'}
        if not os.path.exists(path):
            self.report({'ERROR'}, f"右手动画文件不存在: {path}")
            return {'CANCELLED'}
        try:
            make_right_hand_animation(path, config, suffix)
            self.report({'INFO'}, "Right hand animation generated successfully")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to generate right hand animation: {str(e)}")
            return {'CANCELLED'}


class STRINGFLOW_OT_generate_string_animation(Operator):
    bl_idname = "music_doll.string_flow_generate_string_animation"
    bl_label = "Generate String Animation"
    bl_description = "Generate string animation from .string_flow file"

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        path = _resolve_anim_path(scene, "string_animation_file")
        if not path:
            self.report({'ERROR'}, "请选择 .string_flow 文件（且包含 string_animation_file）")
            return {'CANCELLED'}
        if not os.path.exists(path):
            self.report({'ERROR'}, f"弦动画文件不存在: {path}")
            return {'CANCELLED'}
        try:
            summary = apply_string_animation(path, suffix,
                                             _get_active_instrument(context))
            if summary["shape_keys"] == 0:
                self.report(
                    {'WARNING'},
                    f"弦动画未生成：共写入 0 个 shape key（文件共 {summary['total_entries']} 条数据，"
                    f"跳过品格0/1: {summary['skipped_f0f1']}，未找到目标乐器: "
                    f"{summary['skipped_no_instrument']}，乐器无shape key: "
                    f"{summary['skipped_no_shape_keys']}，未找到shape key: "
                    f"{summary['skipped_no_shape_key']}）。请检查目标乐器是否已设置"
                    f"（角色操作面板）且已生成弦 shape key。")
                return {'CANCELLED'}
            self.report(
                {'INFO'},
                f"String animation generated: {summary['shape_keys']} shape keys, "
                f"{summary['keyframes']} keyframes")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to generate string animation: {str(e)}")
            return {'CANCELLED'}


class STRINGFLOW_OT_generate_all_animation(Operator):
    bl_idname = "music_doll.string_flow_generate_all_animation"
    bl_label = "Generate All Animation"
    bl_description = "Generate all animation (left hand, right hand and string) from .string_flow file"

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        config = _get_string_flow_config(
            scene.stringflow_props, suffix=suffix,
            skeleton=_get_active_skeleton(context),
            instrument=_get_active_instrument(context))

        success_count = 0
        warning_count = 0

        def _run(kind, func):
            nonlocal success_count, warning_count
            path = _resolve_anim_path(scene, kind)
            if path and os.path.exists(path):
                try:
                    result = func(path)
                    # 弦动画返回统计字典；0 个 shape key 视为未生成
                    if isinstance(result, dict) and result.get("shape_keys", 1) == 0:
                        warning_count += 1
                        print(f"警告: {kind} 未写入任何 shape key 关键帧，弦动画未生成")
                        return False
                    success_count += 1
                    return True
                except Exception as e:
                    print(f"生成 {kind} 动画失败: {e}")
            warning_count += 1
            return False

        _run("left_hand_animation_file",
             lambda p: make_left_hand_animation(p, config, suffix))
        _run("right_hand_animation_file",
             lambda p: make_right_hand_animation(p, config, suffix))
        _run("string_animation_file",
             lambda p: apply_string_animation(p, suffix, config.target_instrument))

        if success_count > 0:
            self.report(
                {'INFO'}, f"Generated {success_count} animations with {warning_count} warnings")
            return {'FINISHED'}
        self.report({'ERROR'}, "No animations were generated successfully")
        return {'CANCELLED'}


class STRINGFLOW_OT_duplicate_performer(Operator):
    """复制当前角色，生成一个新角色（输入新名字）"""
    bl_idname = "music_doll.string_flow_duplicate_performer"
    bl_label = "复制角色"
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(default="", name="新名字")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name")

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        if not suffix:
            self.report({'ERROR'}, "请先在下拉框选中要复制的角色")
            return {'CANCELLED'}
        src = performer_utils.get_performer(suffix)
        if src is None:
            self.report(
                {'ERROR'}, f"找不到已登记的角色 {suffix}（请先初始化该角色）")
            return {'CANCELLED'}
        new_name = (self.new_name or "").strip()
        if not new_name:
            self.report({'ERROR'}, "请输入新名字")
            return {'CANCELLED'}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report(
                {'ERROR'}, "名字只能使用英文字母和数字（如 Ayaka / Player01），不能包含中文")
            return {'CANCELLED'}
        if performer_utils.has_performer(new_name):
            self.report({'ERROR'}, f"已存在名字 {new_name}，请换一个")
            return {'CANCELLED'}

        try:
            dup = performer_utils.duplicate_collection_tree(src.collection)
        except Exception as e:
            self.report({'ERROR'}, f"复制集合失败: {str(e)}")
            return {'CANCELLED'}
        if dup is None:
            self.report({'ERROR'}, "复制集合失败（未能生成副本）")
            return {'CANCELLED'}

        # 补上源名字/乐器元信息，让 resuffix 知道要替换什么
        from ..common import instrument_base
        instrument_base.set_coll_attr(dup, "name", src.name)
        instrument_base.set_coll_attr(dup, "instrument", src.instrument)

        new_perf = performer_utils.resuffix_performer(
            dup, new_name, new_name=new_name)

        # StringFlow 收尾：重建 ext driver + 整理演奏者根
        try:
            config = _get_string_flow_config(
                scene.stringflow_props, suffix=new_name,
                skeleton=new_perf.target_skeleton,
                instrument=new_perf.target_instrument)
            config.add_ext_drivers()
            config._organize_performer_root()
        except Exception as e:
            self.report(
                {'WARNING'}, f"复制完成，但整理演奏者结构失败: {str(e)}")

        self.report({'INFO'}, f"已复制角色为 {new_name}")
        return {'FINISHED'}


class STRINGFLOW_OT_rename_performer(Operator):
    """重命名当前角色：原地修改名字（名字即命名空间后缀），不生成新角色"""
    bl_idname = "music_doll.string_flow_rename_performer"
    bl_label = "重命名当前角色"
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(default="", name="新名字")

    def invoke(self, context, event):
        src = ui_utils.get_rename_target(context)
        if src is not None and src.name and src.name.isascii():
            self.new_name = src.name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name")

    def execute(self, context):
        scene = context.scene
        src = ui_utils.get_rename_target(context)
        if src is None:
            self.report(
                {'ERROR'}, "找不到当前角色（请先在下拉框选中，或指定其骨骼/乐器）")
            return {'CANCELLED'}
        new_name = (self.new_name or "").strip()
        if not new_name:
            self.report({'ERROR'}, "请输入新名字")
            return {'CANCELLED'}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report(
                {'ERROR'}, "名字只能使用英文字母和数字（如 Ayaka / Player01），不能包含中文")
            return {'CANCELLED'}
        if new_name == src.name:
            self.report({'ERROR'}, f"新名字与当前相同（{new_name}），无需重命名")
            return {'CANCELLED'}
        if performer_utils.has_performer(new_name):
            self.report({'ERROR'}, f"已存在名字 {new_name}，请换一个")
            return {'CANCELLED'}

        try:
            new_perf = performer_utils.resuffix_performer(
                src.collection, new_name, new_name=new_name)
        except Exception as e:
            self.report({'ERROR'}, f"重命名失败: {str(e)}")
            return {'CANCELLED'}

        # StringFlow 收尾：重建 ext driver + 整理演奏者根
        try:
            config = _get_string_flow_config(
                scene.stringflow_props, suffix=new_name,
                skeleton=new_perf.target_skeleton,
                instrument=new_perf.target_instrument)
            config.add_ext_drivers()
            config._organize_performer_root()
        except Exception as e:
            self.report(
                {'WARNING'}, f"重命名完成，但整理演奏者结构失败: {str(e)}")

        # 更新场景状态：把当前角色切到新名字
        try:
            setattr(scene, ui_utils.SCENE_ACTIVE_PERFORMER, new_name)
        except Exception:
            pass

        self.report({'INFO'}, f"已将角色重命名为 {new_name}")
        return {'FINISHED'}


# ── 面板 ──────────────────────────────────────────────────────

class STRINGFLOW_PT_main_panel(Panel):
    """StringFlow 乐器子面板（挂在 MusicDoll 统一主面板下，按乐器类型显示）"""
    bl_label = "StringFlow"
    bl_idname = "STRINGFLOW_PT_main_panel"
    bl_parent_id = "MUSICDOLL_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MusicDoll"

    @classmethod
    def poll(cls, context):
        return ui_utils.active_instrument(context) == "string_flow"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.stringflow_props

        # 1. 初始化模块
        box = layout.box()
        box.label(text="初始化", icon='TOOL_SETTINGS')
        col = box.column(align=True)
        col.prop(props, "one_hand_finger_number")
        col.prop(props, "string_number")
        row = box.row(align=True)
        row.operator("music_doll.string_flow_check_status")
        row.operator("music_doll.string_flow_setup_objects")

        # 2. 工具区（公共工具 + StringFlow 独有工具）
        ui_utils.draw_tools(layout, scene, tools=TOOLS)

        # 3. 左手状态选择
        box = layout.box()
        box.label(text="Left Hand State", icon='TRIA_LEFT')
        box.prop(props, "left_hand_position_type")
        box.prop(props, "left_hand_string_index")
        box.prop(props, "left_hand_fret_index")

        # 4. 右手状态选择
        box = layout.box()
        box.label(text="Right Hand State", icon='TRIA_RIGHT')
        box.prop(props, "right_hand_position_type")
        box.prop(props, "right_hand_string_index")

        # 5. 状态传输模块
        box = layout.box()
        box.label(text="Hand State Transfer", icon='FILE_REFRESH')
        row = box.row(align=True)
        row.operator("music_doll.string_flow_save_state",
                     text="Set", icon='IMPORT')
        row.operator("music_doll.string_flow_load_state",
                     text="Load", icon='EXPORT')

        # 6. 导入/导出模块（人物信息路径由角色模块统一设置）
        box = layout.box()
        box.label(text="Recorder Info I/O", icon='FILE')
        row = box.row(align=True)
        row.operator("music_doll.string_flow_export_info",
                     text="导出", icon='EXPORT')
        row.operator("music_doll.string_flow_import_info",
                     text="导入", icon='IMPORT')
        box.operator("music_doll.string_flow_export_to_unreal",
                     text="导出到 Unreal", icon='EXPORT')

        # 7. 动画生成模块
        box = layout.box()
        box.label(text="生成动画", icon='PLAY')
        box.prop(props, "string_flow_file_path", text="")
        row = box.row(align=True)
        row.operator("music_doll.string_flow_generate_left_hand_animation",
                     text="左手动画")
        row.operator("music_doll.string_flow_generate_right_hand_animation",
                     text="右手动画")
        row = box.row(align=True)
        row.operator("music_doll.string_flow_generate_string_animation",
                     text="弦动画")
        row = box.row()
        row.operator("music_doll.string_flow_generate_all_animation",
                     text="一键生成全部动画", icon='PLAY')


# ── 注册/注销 ──────────────────────────────────────────────────

def register():
    bpy.utils.register_class(StringFlowProperties)
    bpy.types.Scene.stringflow_props = PointerProperty(
        type=StringFlowProperties)

    bpy.utils.register_class(STRINGFLOW_OT_check_status)
    bpy.utils.register_class(STRINGFLOW_OT_setup_objects)
    bpy.utils.register_class(STRINGFLOW_OT_save_state)
    bpy.utils.register_class(STRINGFLOW_OT_load_state)
    bpy.utils.register_class(STRINGFLOW_OT_export_info)
    bpy.utils.register_class(STRINGFLOW_OT_import_info)
    bpy.utils.register_class(STRINGFLOW_OT_generate_left_hand_animation)
    bpy.utils.register_class(STRINGFLOW_OT_generate_right_hand_animation)
    bpy.utils.register_class(STRINGFLOW_OT_generate_string_animation)
    bpy.utils.register_class(STRINGFLOW_OT_generate_all_animation)
    bpy.utils.register_class(STRINGFLOW_OT_duplicate_performer)
    bpy.utils.register_class(STRINGFLOW_OT_rename_performer)
    bpy.utils.register_class(STRINGFLOW_PT_main_panel)

    # 注册本乐器工具模块（执行算子）
    from .tools import register as register_tools
    register_tools()

    # 登记本乐器 UI（角色生成器下拉 + 角色操作器接入）
    ui_utils.register_instrument(
        "string_flow", "StringFlow 小提琴", STRINGFLOW_PT_main_panel,
        rename_operator="music_doll.string_flow_rename_performer",
        duplicate_operator="music_doll.string_flow_duplicate_performer")


def unregister():
    from .tools import unregister as unregister_tools
    unregister_tools()

    # 注销本乐器 UI 登记
    ui_utils.unregister_instrument("string_flow")

    bpy.utils.unregister_class(STRINGFLOW_PT_main_panel)
    bpy.utils.unregister_class(STRINGFLOW_OT_rename_performer)
    bpy.utils.unregister_class(STRINGFLOW_OT_duplicate_performer)
    bpy.utils.unregister_class(STRINGFLOW_OT_generate_all_animation)
    bpy.utils.unregister_class(STRINGFLOW_OT_generate_string_animation)
    bpy.utils.unregister_class(STRINGFLOW_OT_generate_right_hand_animation)
    bpy.utils.unregister_class(STRINGFLOW_OT_generate_left_hand_animation)
    bpy.utils.unregister_class(STRINGFLOW_OT_import_info)
    bpy.utils.unregister_class(STRINGFLOW_OT_export_info)
    bpy.utils.unregister_class(STRINGFLOW_OT_load_state)
    bpy.utils.unregister_class(STRINGFLOW_OT_save_state)
    bpy.utils.unregister_class(STRINGFLOW_OT_setup_objects)
    bpy.utils.unregister_class(STRINGFLOW_OT_check_status)

    del bpy.types.Scene.stringflow_props
    bpy.utils.unregister_class(StringFlowProperties)
