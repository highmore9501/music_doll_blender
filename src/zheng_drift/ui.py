# zheng_drift/ui.py
"""ZhengDrift 乐器模块 —— 面板与算子（迁移自 zheng_blender_addon/__init__.py）

- 公共演奏者选择/骨骼/乐器/路径改调 common.ui_utils；
- 导入/导出标准姿势用角色模块的「人物信息路径」（SCENE_INFO_PATH），不再用文件浏览器；
- 乐器面板只保留 zheng_animation_file（动画/配置文件路径）这一个 FILE_PATH；
- 工具下拉 = 公共工具 + ZhengDrift 独有工具（弦 Shape Key / 线性分布）。
"""

import json
import os

import bpy  # type: ignore
from bpy.types import Panel, Operator, PropertyGroup  # type: ignore
from bpy.props import (  # type: ignore
    StringProperty,
    PointerProperty,
    EnumProperty,
)

from ..common import ui_utils
from ..common import performer_utils
from ..common.tools import COMMON_TOOLS
from .config import ZhengConfig
from .enums import LeftHandAction, RightHandAction, HandPosition
from .state import (
    save_hand_state,
    load_hand_state,
    save_bilinear_helpers,
    load_bilinear_helpers,
)
from .io import export_recorder_info, import_recorder_info
from .animation import (
    generate_left_hand_animation,
    generate_right_hand_animation,
    generate_string_vibration_animation,
    generate_target_animation,
    clear_all_keyframes,
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


def _get_zheng_config(props, suffix="", skeleton=None, instrument=None) -> ZhengConfig:
    return ZhengConfig(
        performer_suffix=suffix,
        target_skeleton=skeleton,
        target_instrument=instrument,
    )


def _position_from_props(props, hand) -> HandPosition:
    value = props.left_hand_position if hand == "left" else props.right_hand_position
    return getattr(HandPosition, value)


def _action_from_props(props, hand):
    value = props.left_hand_action if hand == "left" else props.right_hand_action
    enum_cls = LeftHandAction if hand == "left" else RightHandAction
    return getattr(enum_cls, value)


# ── 动画文件路径解析（支持 .zhengdrift 配置） ────────────────

def _resolve_anim_path(scene, kind: str) -> str:
    """从 zheng_animation_file 解析出指定类型的动画文件路径。

    - .zhengdrift 配置：取 kind（performance_animation / target_animation /
      string_animation），相对路径按配置文件目录解析；
    - 其它文件：原样返回（作为 performance 用）。
    """
    file_path = scene.zhengdrift_props.zheng_animation_file
    if not file_path:
        return ""
    if file_path.endswith(".zhengdrift"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            print(f"解析 .zhengdrift 配置失败：{e}")
            return ""
        rel = config_data.get(kind)
        if not rel:
            return ""
        if not os.path.isabs(rel):
            rel = os.path.join(os.path.dirname(file_path), rel)
        return rel
    return file_path


# ── 属性组 ────────────────────────────────────────────────────

class ZhengDriftProperties(PropertyGroup):
    """ZhengDrift 面板属性（左右手状态选择 + 动画/配置文件路径）"""
    __annotations__ = {
        "left_hand_position": EnumProperty(
            name="位置",
            description="选择左手演奏位置",
            items=[('FAR', 'Far', '远端（0 弦区域）'),
                   ('MIDDLE', 'Middle', '中间（10 弦区域）'),
                   ('NEAR', 'Near', '近端（20 弦区域）')],
            default='FAR'),
        "left_hand_action": EnumProperty(
            name="动作",
            description="选择左手动作类型",
            items=[('NORMAL', 'Normal', '普通拨弦'),
                   ('PRESS', 'Press', '按弦')],
            default='NORMAL'),
        "right_hand_position": EnumProperty(
            name="位置",
            description="选择右手演奏位置",
            items=[('FAR', 'Far', '远端（0 弦区域）'),
                   ('MIDDLE', 'Middle', '中间（10 弦区域）'),
                   ('NEAR', 'Near', '近端（20 弦区域）')],
            default='FAR'),
        "right_hand_action": EnumProperty(
            name="动作",
            description="选择右手动作类型",
            items=[('NORMAL', 'Normal', '普通拨弦'),
                   ('TREMOLO', 'Tremolo', '摇指')],
            default='NORMAL'),

        # .zhengdrift 配置 / 动画文件路径（乐器面板唯一 FILE_PATH；
        # 乐器物体/人物信息路径由角色模块「角色操作」面板统一设置）
        "zheng_animation_file": StringProperty(
            name="动画文件",
            description="动画配置文件路径（.zhengdrift）或手部动画文件路径",
            default="", subtype='FILE_PATH'),
    }


# ── 算子 ──────────────────────────────────────────────────────

class ZHENG_OT_check_status(Operator):
    bl_idname = "music_doll.zheng_drift_check_status"
    bl_label = "Check Objects Status"
    bl_description = "Check the status of all ZhengDrift objects"

    def execute(self, context):
        config = _get_zheng_config(
            context.scene.zhengdrift_props, suffix=_get_active_suffix(context))
        config.check_all_objects()
        return {'FINISHED'}


class ZHENG_OT_setup_objects(Operator):
    bl_idname = "music_doll.zheng_drift_setup_objects"
    bl_label = "Setup All Objects"
    bl_description = "Create all ZhengDrift controllers and recorders"

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        config = _get_zheng_config(
            scene.zhengdrift_props, suffix=suffix,
            skeleton=_get_active_skeleton(context),
            instrument=_get_active_instrument(context))
        if not config.setup_all_objects():
            self.report(
                {'ERROR'}, "设置失败：未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）")
            return {'CANCELLED'}
        self.report({'INFO'}, "All objects have been setup")
        return {'FINISHED'}


class ZHENG_OT_save_left_hand_state(Operator):
    bl_idname = "music_doll.zheng_drift_save_left_hand_state"
    bl_label = "Save Left Hand"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.zhengdrift_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        config = _get_zheng_config(
            props, suffix=_get_active_suffix(context), skeleton=skel)
        position = _position_from_props(props, "left")
        action = _action_from_props(props, "left")
        save_hand_state(config, skel, "left", position, action)
        # 满足四态时保存 Middle_Hand / Head_Control 位置
        save_bilinear_helpers(config, position, action,
                              _position_from_props(props, "right"),
                              _action_from_props(props, "right"))
        self.report({'INFO'}, "Left hand state has been set")
        return {'FINISHED'}


class ZHENG_OT_save_right_hand_state(Operator):
    bl_idname = "music_doll.zheng_drift_save_right_hand_state"
    bl_label = "Save Right Hand"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.zhengdrift_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        config = _get_zheng_config(
            props, suffix=_get_active_suffix(context), skeleton=skel)
        position = _position_from_props(props, "right")
        action = _action_from_props(props, "right")
        save_hand_state(config, skel, "right", position, action)
        save_bilinear_helpers(config,
                              _position_from_props(props, "left"),
                              _action_from_props(props, "left"),
                              position, action)
        self.report({'INFO'}, "Right hand state has been set")
        return {'FINISHED'}


class ZHENG_OT_load_left_hand_state(Operator):
    bl_idname = "music_doll.zheng_drift_load_left_hand_state"
    bl_label = "Load Left Hand"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.zhengdrift_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        config = _get_zheng_config(
            props, suffix=_get_active_suffix(context), skeleton=skel)
        position = _position_from_props(props, "left")
        action = _action_from_props(props, "left")
        try:
            load_hand_state(config, skel, "left", position, action)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        load_bilinear_helpers(config, position, action,
                              _position_from_props(props, "right"),
                              _action_from_props(props, "right"))
        self.report({'INFO'}, "Left hand state has been loaded")
        return {'FINISHED'}


class ZHENG_OT_load_right_hand_state(Operator):
    bl_idname = "music_doll.zheng_drift_load_right_hand_state"
    bl_label = "Load Right Hand"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.zhengdrift_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        config = _get_zheng_config(
            props, suffix=_get_active_suffix(context), skeleton=skel)
        position = _position_from_props(props, "right")
        action = _action_from_props(props, "right")
        try:
            load_hand_state(config, skel, "right", position, action)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        load_bilinear_helpers(config,
                              _position_from_props(props, "left"),
                              _action_from_props(props, "left"),
                              position, action)
        self.report({'INFO'}, "Right hand state has been loaded")
        return {'FINISHED'}


class ZHENG_OT_export_info(Operator):
    bl_idname = "music_doll.zheng_drift_export_info"
    bl_label = "导出控制器信息"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 人物信息路径由角色模块「角色操作」面板统一设置
        file_path = getattr(context.scene, ui_utils.SCENE_INFO_PATH, "")
        if not file_path:
            self.report({'ERROR'}, "请先在「角色操作」面板中设置人物信息路径")
            return {'CANCELLED'}
        config = _get_zheng_config(
            context.scene.zhengdrift_props, suffix=_get_active_suffix(context))
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        try:
            export_recorder_info(file_path, config, skel)
            self.report(
                {'INFO'}, f"Controller info exported to {file_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            return {'CANCELLED'}


class ZHENG_OT_import_info(Operator):
    bl_idname = "music_doll.zheng_drift_import_info"
    bl_label = "导入控制器信息"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 人物信息路径由角色模块「角色操作」面板统一设置
        file_path = getattr(context.scene, ui_utils.SCENE_INFO_PATH, "")
        if not file_path:
            self.report({'ERROR'}, "请先在「角色操作」面板中设置人物信息路径")
            return {'CANCELLED'}
        config = _get_zheng_config(
            context.scene.zhengdrift_props, suffix=_get_active_suffix(context))
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        try:
            import_recorder_info(file_path, config, skel)
            self.report(
                {'INFO'}, f"Controller info imported from {file_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {str(e)}")
            return {'CANCELLED'}


class ZHENG_OT_generate_left_hand_animation(Operator):
    bl_idname = "music_doll.zheng_drift_generate_left_hand_animation"
    bl_label = "生成左手动画"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        if not scene.zhengdrift_props.zheng_animation_file:
            self.report({'ERROR'}, "Please select an animation file")
            return {'CANCELLED'}
        path = _resolve_anim_path(scene, "performance_animation")
        if not path or not os.path.exists(path):
            self.report({'ERROR'}, f"Animation file not found: {path}")
            return {'CANCELLED'}
        try:
            generate_left_hand_animation(path, suffix=suffix)
            self.report({'INFO'}, "Left hand animation generated")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Animation generation failed: {str(e)}")
            return {'CANCELLED'}


class ZHENG_OT_generate_right_hand_animation(Operator):
    bl_idname = "music_doll.zheng_drift_generate_right_hand_animation"
    bl_label = "生成右手动画"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        if not scene.zhengdrift_props.zheng_animation_file:
            self.report({'ERROR'}, "Please select an animation file")
            return {'CANCELLED'}
        path = _resolve_anim_path(scene, "performance_animation")
        if not path or not os.path.exists(path):
            self.report({'ERROR'}, f"Animation file not found: {path}")
            return {'CANCELLED'}
        try:
            generate_right_hand_animation(path, suffix=suffix)
            self.report({'INFO'}, "Right hand animation generated")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Animation generation failed: {str(e)}")
            return {'CANCELLED'}


class ZHENG_OT_generate_string_animation(Operator):
    bl_idname = "music_doll.zheng_drift_generate_string_animation"
    bl_label = "生成弦振动动画"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        if not scene.zhengdrift_props.zheng_animation_file:
            self.report({'ERROR'}, "Please select an animation file")
            return {'CANCELLED'}
        path = _resolve_anim_path(scene, "string_animation")
        if not path or not os.path.exists(path):
            self.report({'ERROR'}, f"Animation file not found: {path}")
            return {'CANCELLED'}
        try:
            generate_string_vibration_animation(path, suffix=suffix)
            self.report({'INFO'}, "String vibration animation generated")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Animation generation failed: {str(e)}")
            return {'CANCELLED'}


class ZHENG_OT_generate_all_animation(Operator):
    bl_idname = "music_doll.zheng_drift_generate_all_animation"
    bl_label = "一键生成全部动画"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        if not scene.zhengdrift_props.zheng_animation_file:
            self.report({'ERROR'}, "Please select an animation file")
            return {'CANCELLED'}

        try:
            config_file_path = scene.zhengdrift_props.zheng_animation_file
            performance_path = None
            target_path = None
            string_path = None

            # 检查是否是 .zhengdrift config 文件
            if config_file_path.endswith('.zhengdrift'):
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                performance_path = config_data.get('performance_animation')
                target_path = config_data.get('target_animation')
                string_path = config_data.get('string_animation')
                base_dir = os.path.dirname(config_file_path)
                if performance_path and not os.path.isabs(performance_path):
                    performance_path = os.path.join(base_dir, performance_path)
                if target_path and not os.path.isabs(target_path):
                    target_path = os.path.join(base_dir, target_path)
                if string_path and not os.path.isabs(string_path):
                    string_path = os.path.join(base_dir, string_path)
            else:
                performance_path = config_file_path

            # 清除所有关键帧
            clear_all_keyframes(suffix)

            success_count = 0

            # 手部动画（performance）
            if performance_path and os.path.exists(performance_path):
                try:
                    generate_left_hand_animation(
                        performance_path, suffix=suffix)
                    generate_right_hand_animation(
                        performance_path, suffix=suffix)
                    success_count += 1
                except Exception as e:
                    print(f"手部动画生成失败：{e}")

            # Target 动画
            if target_path and os.path.exists(target_path):
                try:
                    generate_target_animation(target_path, suffix=suffix)
                    success_count += 1
                except Exception as e:
                    print(f"Target 动画生成失败：{e}")

            # 弦动画
            if string_path and os.path.exists(string_path):
                try:
                    generate_string_vibration_animation(
                        string_path, suffix=suffix)
                    success_count += 1
                except Exception as e:
                    print(f"弦动画生成失败：{e}")

            if success_count > 0:
                self.report(
                    {'INFO'}, f"Generated {success_count} animation(s)")
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, "No animations were generated")
                return {'CANCELLED'}

        except Exception as e:
            self.report({'ERROR'}, f"Animation generation failed: {str(e)}")
            return {'CANCELLED'}


class ZHENG_OT_duplicate_performer(Operator):
    """复制当前角色，生成一个新角色（输入新名字）"""
    bl_idname = "music_doll.zheng_drift_duplicate_performer"
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

        # ZhengDrift 收尾：重建 ext driver + 整理演奏者根
        try:
            config = _get_zheng_config(
                scene.zhengdrift_props, suffix=new_name,
                skeleton=new_perf.target_skeleton,
                instrument=new_perf.target_instrument)
            config.add_ext_drivers()
            config._organize_performer_root()
        except Exception as e:
            self.report(
                {'WARNING'}, f"复制完成，但整理演奏者结构失败: {str(e)}")

        self.report({'INFO'}, f"已复制角色为 {new_name}")
        return {'FINISHED'}


class ZHENG_OT_rename_performer(Operator):
    """重命名当前角色：原地修改名字（名字即命名空间后缀），不生成新角色"""
    bl_idname = "music_doll.zheng_drift_rename_performer"
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

        # ZhengDrift 收尾：重建 ext driver + 整理演奏者根
        try:
            config = _get_zheng_config(
                scene.zhengdrift_props, suffix=new_name,
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

class ZHENG_PT_main_panel(Panel):
    """ZhengDrift 乐器子面板（挂在 MusicDoll 统一主面板下，按乐器类型显示）"""
    bl_label = "ZhengDrift"
    bl_idname = "ZHENG_PT_main_panel"
    bl_parent_id = "MUSICDOLL_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MusicDoll"

    @classmethod
    def poll(cls, context):
        return ui_utils.active_instrument(context) == "zheng_drift"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.zhengdrift_props

        # 1. 初始化模块
        box = layout.box()
        box.label(text="初始化", icon='TOOL_SETTINGS')
        row = box.row(align=True)
        row.operator("music_doll.zheng_drift_check_status")
        row.operator("music_doll.zheng_drift_setup_objects")

        # 2. 工具区（公共工具 + ZhengDrift 独有工具）
        ui_utils.draw_tools(layout, scene, tools=TOOLS)

        # 3. 左手状态选择
        box = layout.box()
        box.label(text="选择左手状态", icon='HAND')
        box.prop(props, "left_hand_position")
        box.prop(props, "left_hand_action")

        # 4. 右手状态选择
        box = layout.box()
        box.label(text="选择右手状态", icon='RIGHTARROW_THIN')
        box.prop(props, "right_hand_position")
        box.prop(props, "right_hand_action")

        # 5. 设置与加载模块（含四态 bilinear 保存/恢复）
        box = layout.box()
        box.label(text="设置与加载", icon='FILE_REFRESH')
        row = box.row(align=True)
        row.operator("music_doll.zheng_drift_save_left_hand_state",
                     text="Save Left Hand")
        row.operator("music_doll.zheng_drift_save_right_hand_state",
                     text="Save Right Hand")
        row = box.row(align=True)
        row.operator("music_doll.zheng_drift_load_left_hand_state",
                     text="Load Left Hand")
        row.operator("music_doll.zheng_drift_load_right_hand_state",
                     text="Load Right Hand")

        # 6. 导入/导出标准姿势（人物信息路径由角色模块统一设置）
        box = layout.box()
        box.label(text="导入/导出标准姿势", icon='EXPORT')
        row = box.row(align=True)
        row.operator("music_doll.zheng_drift_import_info", text="导入")
        row.operator("music_doll.zheng_drift_export_info", text="导出")

        # 7. 动画生成模块
        box = layout.box()
        box.label(text="生成动画", icon='PLAY')
        box.prop(props, "zheng_animation_file", text="")
        row = box.row(align=True)
        row.operator("music_doll.zheng_drift_generate_left_hand_animation",
                     text="左手动画")
        row.operator("music_doll.zheng_drift_generate_right_hand_animation",
                     text="右手动画")
        row = box.row(align=True)
        row.operator("music_doll.zheng_drift_generate_string_animation",
                     text="弦振动动画")
        row = box.row()
        row.operator("music_doll.zheng_drift_generate_all_animation",
                     text="一键生成全部动画", icon='PLAY')


# ── 注册/注销 ──────────────────────────────────────────────────

def register():
    bpy.utils.register_class(ZhengDriftProperties)
    bpy.types.Scene.zhengdrift_props = PointerProperty(
        type=ZhengDriftProperties)

    bpy.utils.register_class(ZHENG_OT_check_status)
    bpy.utils.register_class(ZHENG_OT_setup_objects)
    bpy.utils.register_class(ZHENG_OT_save_left_hand_state)
    bpy.utils.register_class(ZHENG_OT_save_right_hand_state)
    bpy.utils.register_class(ZHENG_OT_load_left_hand_state)
    bpy.utils.register_class(ZHENG_OT_load_right_hand_state)
    bpy.utils.register_class(ZHENG_OT_export_info)
    bpy.utils.register_class(ZHENG_OT_import_info)
    bpy.utils.register_class(ZHENG_OT_generate_left_hand_animation)
    bpy.utils.register_class(ZHENG_OT_generate_right_hand_animation)
    bpy.utils.register_class(ZHENG_OT_generate_string_animation)
    bpy.utils.register_class(ZHENG_OT_generate_all_animation)
    bpy.utils.register_class(ZHENG_OT_duplicate_performer)
    bpy.utils.register_class(ZHENG_OT_rename_performer)
    bpy.utils.register_class(ZHENG_PT_main_panel)

    # 注册本乐器工具模块（执行算子）
    from .tools import register as register_tools
    register_tools()

    # 登记本乐器 UI（角色生成器下拉 + 角色操作器接入）
    ui_utils.register_instrument(
        "zheng_drift", "ZhengDrift 古筝", ZHENG_PT_main_panel,
        rename_operator="music_doll.zheng_drift_rename_performer",
        duplicate_operator="music_doll.zheng_drift_duplicate_performer")


def unregister():
    from .tools import unregister as unregister_tools
    unregister_tools()

    # 注销本乐器 UI 登记
    ui_utils.unregister_instrument("zheng_drift")

    bpy.utils.unregister_class(ZHENG_PT_main_panel)
    bpy.utils.unregister_class(ZHENG_OT_rename_performer)
    bpy.utils.unregister_class(ZHENG_OT_duplicate_performer)
    bpy.utils.unregister_class(ZHENG_OT_generate_all_animation)
    bpy.utils.unregister_class(ZHENG_OT_generate_string_animation)
    bpy.utils.unregister_class(ZHENG_OT_generate_right_hand_animation)
    bpy.utils.unregister_class(ZHENG_OT_generate_left_hand_animation)
    bpy.utils.unregister_class(ZHENG_OT_import_info)
    bpy.utils.unregister_class(ZHENG_OT_export_info)
    bpy.utils.unregister_class(ZHENG_OT_load_right_hand_state)
    bpy.utils.unregister_class(ZHENG_OT_load_left_hand_state)
    bpy.utils.unregister_class(ZHENG_OT_save_right_hand_state)
    bpy.utils.unregister_class(ZHENG_OT_save_left_hand_state)
    bpy.utils.unregister_class(ZHENG_OT_setup_objects)
    bpy.utils.unregister_class(ZHENG_OT_check_status)

    del bpy.types.Scene.zhengdrift_props
    bpy.utils.unregister_class(ZhengDriftProperties)
