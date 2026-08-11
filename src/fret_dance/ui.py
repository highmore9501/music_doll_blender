# fret_dance/ui.py
"""FretDance 乐器模块 —— 面板与算子（迁移自 fret_dance_blender/__init__.py）

公共演奏者选择/骨骼/乐器/路径改调 common.ui_utils。
移除 mmd2blender（用户明确 MMD 相关不迁移）。
"""

import os
import json

import bpy  # type: ignore
from bpy.types import Panel, Operator  # type: ignore
from bpy.props import (  # type: ignore
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
    BoolProperty,
)
from bpy_extras.io_utils import ImportHelper, ExportHelper  # type: ignore

from ..common import ui_utils
from ..common import performer_utils
from ..common.tools import COMMON_TOOLS
from .base import BaseState, Instruments, BasePositions, LeftHandStates, RightHandStates
from .animation import (
    clear_all_keyframe,
    clear_string_animation,
    clear_controller_root_animation,
    animate_hand,
    animate_string,
    animate_controller_root,
)
from .tools import INSTRUMENT_TOOLS


# 该乐器的工具列表 = 公共工具 + 乐器独有工具
TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS


# 定义全局的位置映射表
LEFT_HAND_POSITIONS_MAP = {
    'P0': [('Normal', "Normal", "Normal state"),
           ('Outer', "Outer", "Outer state"),
           ('Barre', "Barre", "Barre state")],
    'P1': [('Normal', "Normal", "Normal state"),
           ('Inner', "Inner", "Inner state"),
           ('Barre', "Barre", "Barre state")],
    'P2': [('Normal', "Normal", "Normal state"),
           ('Outer', "Outer", "Outer state"),
           ('Barre', "Barre", "Barre state")],
    'P3': [('Normal', "Normal", "Normal state"),
           ('Inner', "Inner", "Inner state"),
           ('Barre', "Barre", "Barre state")],
    'P4': [('Normal', "Normal", "Normal state")]
}


# ── 演奏者/后缀/骨骼辅助（多演奏者、插件无状态化） ──────────────

def _get_active_suffix(context):
    """当前角色名字（公共实现：后缀已与名字合并）"""
    return ui_utils.get_active_suffix(context.scene)


def _get_active_skeleton(context):
    """当前目标骨骼：优先公共场景指针，其次选中的 ARMATURE"""
    scene = context.scene
    skel = ui_utils.get_target_skeleton(context)
    if skel:
        return skel
    for obj in context.selected_objects:
        if obj is not None and obj.type == "ARMATURE":
            return obj
    return None


def _get_active_instrument(context):
    """当前目标乐器：优先公共场景指针，其次当前演奏者登记的乐器"""
    scene = context.scene
    inst = ui_utils.get_target_instrument(context)
    if inst:
        return inst
    suffix = _get_active_suffix(context)
    if suffix:
        p = performer_utils.get_performer(suffix)
        if p is not None and p.target_instrument is not None:
            return p.target_instrument
    return None


def _get_rename_target(context):
    """定位要重命名/复制的演奏者（公共实现）"""
    return ui_utils.get_rename_target(context)


def _build_base_state(context, use_skeleton=True):
    """按面板/骨骼设置构造 BaseState（无状态：可从骨骼加载设置）"""
    scene = context.scene
    suffix = _get_active_suffix(context)
    skeleton = _get_active_skeleton(context)
    instrument_obj = _get_active_instrument(context)
    state = BaseState(Instruments(int(scene.fret_dance_instruments)),
                      use_vibrato_bar=scene.fret_dance_use_vibrato_bar,
                      performer_suffix=suffix, target_skeleton=skeleton,
                      target_instrument=instrument_obj)
    if use_skeleton and skeleton is not None:
        settings = state.load_settings(skeleton)
        state.instruments = Instruments(settings["instrument"])
        state.use_vibrato_bar = settings["use_vibrato_bar"]
    return state


def _sync_settings_from_skeleton(scene, skeleton):
    """把骨骼上的演奏者设置回填到面板控件（无状态化）"""
    if skeleton is None:
        return
    state = BaseState(Instruments(int(scene.fret_dance_instruments)),
                      use_vibrato_bar=scene.fret_dance_use_vibrato_bar,
                      target_skeleton=skeleton)
    settings = state.load_settings(skeleton)
    scene.fret_dance_instruments = str(settings["instrument"])
    scene.fret_dance_use_vibrato_bar = settings["use_vibrato_bar"]


def _on_active_performer_update(self, context):
    """切换演奏者下拉框：联动目标骨骼/乐器 + 回填设置（无状态）"""
    ui_utils.on_active_performer_update(self, context)
    p = performer_utils.get_performer(
        getattr(context.scene, ui_utils.SCENE_ACTIVE_PERFORMER, ""))
    if p is not None:
        _sync_settings_from_skeleton(self, p.target_skeleton)


def _on_target_skeleton_update(self, context):
    """选择目标骨骼：回填设置（无状态）；若有已知演奏者则联动下拉框"""
    ui_utils.on_target_skeleton_update(self, context)
    skel = getattr(context.scene, ui_utils.SCENE_TARGET_SKELETON, None)
    if skel is None:
        return
    _sync_settings_from_skeleton(self, skel)


def get_performer_items(self, context):
    """演奏者下拉框：扫描 Performers 集合下的已登记演奏者（公共实现）"""
    return ui_utils.get_performer_items(self, context)


class FRET_DANCE_OT_setup_objects(Operator):
    """Setup all controller and fret marker objects"""
    bl_idname = "music_doll.fret_dance_setup_objects"
    bl_label = "设置控制器与指板标记"
    bl_options = {'REGISTER', 'UNDO'}

    suffix: StringProperty(default="")

    def invoke(self, context, event):
        # 后缀冲突检查：已存在同后缀演奏者 → 弹窗询问是否覆盖
        suffix = _get_active_suffix(context)
        if performer_utils.has_performer(suffix):
            self.suffix = suffix
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        suffix = self.suffix or _get_active_suffix(context)
        skeleton = _get_active_skeleton(context)
        base_state = _build_base_state(context, use_skeleton=False)
        # 把面板设置写回骨骼（无状态化：面板是编辑入口，这里提交）
        if skeleton is not None:
            base_state.save_settings(
                skeleton, int(scene.fret_dance_instruments),
                scene.fret_dance_use_vibrato_bar)
        if not base_state.setup_all_objects():
            self.report(
                {'ERROR'}, "设置失败：未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）")
            return {'CANCELLED'}
        self.report({'INFO'}, "All objects have been setup")
        return {'FINISHED'}


class FRET_DANCE_OT_check_status(Operator):
    """Check the status of controller and fret marker objects"""
    bl_idname = "music_doll.fret_dance_check_status"
    bl_label = "检查状态"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        base_state = _build_base_state(context)
        base_state.check_objects_status()
        self.report({'INFO'}, "Check complete. See console for details.")
        return {'FINISHED'}


class FRET_DANCE_OT_set_state(Operator):
    """Set hand states from controllers to target skeleton custom properties"""
    bl_idname = "music_doll.fret_dance_set_state"
    bl_label = "Set"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        base_state = _build_base_state(context)

        target_skeleton = _get_active_skeleton(context)
        if target_skeleton is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        base_position = BasePositions(scene.fret_dance_base_positions)
        left_hand_state = LeftHandStates(scene.fret_dance_left_hand_states)

        right_hand_state = None
        for state in RightHandStates:
            if state.value == scene.fret_dance_right_hand_states:
                right_hand_state = state
                break

        if right_hand_state is None:
            self.report({'ERROR'}, "Invalid right hand state")
            return {'CANCELLED'}

        base_state.transfer_left_hand_state(
            base_position, left_hand_state, target_skeleton, direction="set")
        base_state.transfer_right_hand_state(
            right_hand_state, target_skeleton, direction="set")

        self.report({'INFO'}, f"States saved to {target_skeleton.name}")
        return {'FINISHED'}


class FRET_DANCE_OT_load_state(Operator):
    """Load hand states from target skeleton custom properties to controllers"""
    bl_idname = "music_doll.fret_dance_load_state"
    bl_label = "Load"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        base_state = _build_base_state(context)

        target_skeleton = _get_active_skeleton(context)
        if target_skeleton is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        base_position = BasePositions(scene.fret_dance_base_positions)
        left_hand_state = LeftHandStates(scene.fret_dance_left_hand_states)

        right_hand_state = None
        for state in RightHandStates:
            if state.value == scene.fret_dance_right_hand_states:
                right_hand_state = state
                break

        if right_hand_state is None:
            self.report({'ERROR'}, "Invalid right hand state")
            return {'CANCELLED'}

        base_state.transfer_left_hand_state(
            base_position, left_hand_state, target_skeleton, direction="load")
        base_state.transfer_right_hand_state(
            right_hand_state, target_skeleton, direction="load")

        self.report({'INFO'}, f"States loaded from {target_skeleton.name}")
        return {'FINISHED'}


class FRET_DANCE_OT_export_info(Operator):
    """Export controller information to JSON file

    不再弹文件浏览器，直接使用角色信息里的「人物信息路径」；
    执行前先弹窗确认（会覆盖该路径指向的文件内容）。
    """
    bl_idname = "music_doll.fret_dance_export_info"
    bl_label = "导出人物信息"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        # 导出会覆盖文件里已有的信息 → 先弹窗确认
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(
            text="导出将覆盖「人物信息路径」指向的文件内容，确定继续？",
            icon="ERROR")

    def execute(self, context):
        scene = context.scene
        filepath = getattr(scene, ui_utils.SCENE_INFO_PATH, "")
        if not filepath:
            self.report({'ERROR'}, "请先在「角色操作」面板中设置人物信息路径")
            return {'CANCELLED'}

        base_state = _build_base_state(context)
        target_skeleton = _get_active_skeleton(context)
        if target_skeleton is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        try:
            base_state.export_controller_info(filepath, target_skeleton)
        except Exception as e:
            self.report({'ERROR'}, f"Export Controller Info Error: {str(e)}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Controller info exported to {filepath}")
        return {'FINISHED'}


class FRET_DANCE_OT_import_info(Operator):
    """Import controller information from JSON file

    不再弹文件浏览器，直接使用角色信息里的「人物信息路径」；
    执行前先弹窗确认（会覆盖场景中的演奏者信息）。
    """
    bl_idname = "music_doll.fret_dance_import_info"
    bl_label = "导入人物信息"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        # 导入会覆盖场景中的演奏者信息 → 先弹窗确认
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(
            text="导入将覆盖场景中的演奏者信息，确定继续？",
            icon="ERROR")

    def execute(self, context):
        scene = context.scene
        filepath = getattr(scene, ui_utils.SCENE_INFO_PATH, "")
        if not filepath:
            self.report({'ERROR'}, "请先在「角色操作」面板中设置人物信息路径")
            return {'CANCELLED'}

        base_state = _build_base_state(context)
        target_skeleton = _get_active_skeleton(context)
        if target_skeleton is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}

        try:
            base_state.import_controller_info(filepath, target_skeleton)
        except Exception as e:
            self.report({'ERROR'}, f"Import Controller Info Error: {str(e)}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Controller info imported from {filepath}")
        return {'FINISHED'}


class FRET_DANCE_OT_select_animation_file(Operator, ImportHelper):
    """Select animation configuration file"""
    bl_idname = "music_doll.fret_dance_select_animation_file"
    bl_label = "Select Animation Config"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    __annotations__ = {
        "filter_glob": StringProperty(
            default="*.json",
            options={'HIDDEN'},
            maxlen=255,
        )
    }

    def execute(self, context):
        try:
            with open(self.filepath, 'r') as f:
                data = json.load(f)

            required_keys = [
                "guitar_string_recorder_file",
                "left_hand_animation_file",
                "right_hand_animation_file"
            ]

            missing_keys = []
            for key in required_keys:
                if key not in data:
                    missing_keys.append(key)

            if missing_keys:
                self.report(
                    {'ERROR'}, f"Missing keys in JSON file: {', '.join(missing_keys)}")
                return {'CANCELLED'}

            missing_files = []
            for key in required_keys:
                file_path = data[key]
                if not os.path.exists(file_path):
                    missing_files.append(file_path)

            if missing_files:
                self.report(
                    {'WARNING'}, f"Following files not found: {', '.join(missing_files)}")

            self.report({'INFO'}, "Animation config file loaded successfully")
            context.scene.fret_dance_animation_file = self.filepath
            return {'FINISHED'}

        except json.JSONDecodeError as e:
            self.report({'ERROR'}, f"Invalid JSON format: {str(e)}")
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error reading file: {str(e)}")
            return {'CANCELLED'}


class FRET_DANCE_OT_generate_left_hand_animation(Operator):
    """Generate left hand animation from selected config file"""
    bl_idname = "music_doll.fret_dance_generate_left_hand_animation"
    bl_label = "Generate Left Hand Animation"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        config_path = scene.fret_dance_animation_file
        suffix = _get_active_suffix(context)

        if not config_path or not os.path.exists(config_path):
            self.report(
                {'ERROR'}, "Please select a valid animation configuration file")
            return {'CANCELLED'}

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            clear_all_keyframe(["Left_Hand_Controllers"], suffix=suffix)

            if 'left_hand_animation_file' in config and os.path.exists(config['left_hand_animation_file']):
                animate_hand(config['left_hand_animation_file'], suffix=suffix)
                self.report(
                    {'INFO'}, "Left hand animation generation completed")
            else:
                self.report(
                    {'WARNING'}, "Left hand animation file not found or specified")
                return {'CANCELLED'}

            return {'FINISHED'}

        except Exception as e:
            self.report(
                {'ERROR'}, f"Failed to generate left hand animation: {str(e)}")
            return {'CANCELLED'}


class FRET_DANCE_OT_generate_right_hand_animation(Operator):
    """Generate right hand animation from selected config file"""
    bl_idname = "music_doll.fret_dance_generate_right_hand_animation"
    bl_label = "Generate Right Hand Animation"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        config_path = scene.fret_dance_animation_file
        suffix = _get_active_suffix(context)

        if not config_path or not os.path.exists(config_path):
            self.report(
                {'ERROR'}, "Please select a valid animation configuration file")
            return {'CANCELLED'}

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            clear_all_keyframe(["Right_Hand_Controllers"], suffix=suffix)

            if 'right_hand_animation_file' in config and os.path.exists(config['right_hand_animation_file']):
                animate_hand(
                    config['right_hand_animation_file'], suffix=suffix)
                self.report(
                    {'INFO'}, "Right hand animation generation completed")
            else:
                self.report(
                    {'WARNING'}, "Right hand animation file not found or specified")
                return {'CANCELLED'}

            return {'FINISHED'}

        except Exception as e:
            self.report(
                {'ERROR'}, f"Failed to generate right hand animation: {str(e)}")
            return {'CANCELLED'}


class FRET_DANCE_OT_generate_string_animation(Operator):
    """Generate string animation from selected config file"""
    bl_idname = "music_doll.fret_dance_generate_string_animation"
    bl_label = "Generate String Animation"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        config_path = scene.fret_dance_animation_file
        suffix = _get_active_suffix(context)

        if not config_path or not os.path.exists(config_path):
            self.report(
                {'ERROR'}, "Please select a valid animation configuration file")
            return {'CANCELLED'}

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            clear_string_animation(
                suffix=suffix, instrument=_get_active_instrument(context))

            if 'guitar_string_recorder_file' in config and os.path.exists(config['guitar_string_recorder_file']):
                animate_string(
                    config['guitar_string_recorder_file'], suffix=suffix,
                    instrument=_get_active_instrument(context))
                self.report({'INFO'}, "String animation generation completed")
            else:
                self.report(
                    {'WARNING'}, "String animation file not found or specified")
                return {'CANCELLED'}

            return {'FINISHED'}

        except Exception as e:
            self.report(
                {'ERROR'}, f"Failed to generate string animation: {str(e)}")
            return {'CANCELLED'}


class FRET_DANCE_OT_generate_controller_root_animation(Operator):
    """Generate guitar offset (controller_root) animation from selected config file"""
    bl_idname = "music_doll.fret_dance_generate_controller_root_animation"
    bl_label = "Generate Controller Root Animation"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        config_path = scene.fret_dance_animation_file
        suffix = _get_active_suffix(context)

        if not config_path or not os.path.exists(config_path):
            self.report(
                {'ERROR'}, "Please select a valid animation configuration file")
            return {'CANCELLED'}

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            if 'controller_root_animation_file' in config and os.path.exists(config['controller_root_animation_file']):
                clear_controller_root_animation(suffix=suffix)
                animate_controller_root(
                    config['controller_root_animation_file'], suffix=suffix)
                self.report(
                    {'INFO'}, "Controller root animation generation completed")
            else:
                self.report(
                    {'WARNING'}, "Controller root animation file not found or specified")
                return {'CANCELLED'}

            return {'FINISHED'}

        except Exception as e:
            self.report(
                {'ERROR'}, f"Failed to generate controller root animation: {str(e)}")
            return {'CANCELLED'}


class FRET_DANCE_OT_generate_all_animation(Operator):
    """Generate all animations from selected config file"""
    bl_idname = "music_doll.fret_dance_generate_all_animation"
    bl_label = "Generate All Animations"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        config_path = scene.fret_dance_animation_file
        suffix = _get_active_suffix(context)

        if not config_path or not os.path.exists(config_path):
            self.report(
                {'ERROR'}, "Please select a valid animation configuration file")
            return {'CANCELLED'}

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            clear_all_keyframe(["addons"], suffix=suffix)
            clear_string_animation(
                suffix=suffix, instrument=_get_active_instrument(context))

            success_count = 0

            if 'left_hand_animation_file' in config and os.path.exists(config['left_hand_animation_file']):
                animate_hand(config['left_hand_animation_file'], suffix=suffix)
                success_count += 1
            else:
                self.report(
                    {'WARNING'}, "Left hand animation file not found or specified")

            if 'right_hand_animation_file' in config and os.path.exists(config['right_hand_animation_file']):
                animate_hand(
                    config['right_hand_animation_file'], suffix=suffix)
                success_count += 1
            else:
                self.report(
                    {'WARNING'}, "Right hand animation file not found or specified")

            if 'guitar_string_recorder_file' in config and os.path.exists(config['guitar_string_recorder_file']):
                animate_string(
                    config['guitar_string_recorder_file'], suffix=suffix,
                    instrument=_get_active_instrument(context))
                success_count += 1
            else:
                self.report(
                    {'WARNING'}, "String animation file not found or specified")

            if 'controller_root_animation_file' in config and os.path.exists(config['controller_root_animation_file']):
                animate_controller_root(
                    config['controller_root_animation_file'], suffix=suffix)
                success_count += 1
            else:
                self.report(
                    {'WARNING'}, "Controller root animation file not found or specified")

            if success_count > 0:
                self.report({'INFO'}, "All animations generation completed")
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, "No animation files found or specified")
                return {'CANCELLED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to generate animations: {str(e)}")
            return {'CANCELLED'}


class FRET_DANCE_OT_duplicate_performer(Operator):
    """复制当前角色，生成一个新角色（输入新名字）"""
    bl_idname = "music_doll.fret_dance_duplicate_performer"
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
            self.report({'ERROR'}, f"找不到已登记的角色 {suffix}（请先初始化该角色）")
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

        # 补上源名字/乐器元信息，让 resuffix 知道要替换什么；
        # instrument 决定根空物体前缀（FD/KR...），漏掉会导致回退成 MD_
        from ..common import instrument_base
        instrument_base.set_coll_attr(dup, "name", src.name)
        instrument_base.set_coll_attr(dup, "instrument", src.instrument)

        new_perf = performer_utils.resuffix_performer(
            dup, new_name, new_name=new_name)

        # 重建 ext driver（新名字）
        state = BaseState(Instruments(int(scene.fret_dance_instruments)),
                          use_vibrato_bar=scene.fret_dance_use_vibrato_bar,
                          performer_suffix=new_name,
                          target_skeleton=new_perf.target_skeleton)
        state.add_ext_drivers()

        # 确保新角色的根 <缩写>_<新名> 存在并挂接好
        state._organize_performer_root()

        # 继承源角色的设置（无状态化：从源骨骼读到新骨骼）
        if src.target_skeleton is not None and new_perf.target_skeleton is not None:
            settings = state.load_settings(src.target_skeleton)
            state.save_settings(new_perf.target_skeleton,
                                settings["instrument"], settings["use_vibrato_bar"])

        self.report({'INFO'}, f"已复制角色为 {new_name}")
        return {'FINISHED'}


class FRET_DANCE_OT_rename_performer(Operator):
    """重命名当前角色：原地修改名字（名字即命名空间后缀），不生成新角色"""
    bl_idname = "music_doll.fret_dance_rename_performer"
    bl_label = "重命名当前角色"
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(default="", name="新名字")

    def invoke(self, context, event):
        src = _get_rename_target(context)
        # 旧值非 ASCII（如被 Blender 中文编码问题弄乱）时不预填，让用户重新输入
        if src is not None and src.name and src.name.isascii():
            self.new_name = src.name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name")

    def execute(self, context):
        scene = context.scene
        src = _get_rename_target(context)
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

        # 重建 ext driver（新名字）+ 整理角色根（改名已由 resuffix 完成）
        try:
            state = BaseState(Instruments(int(scene.fret_dance_instruments)),
                              use_vibrato_bar=scene.fret_dance_use_vibrato_bar,
                              performer_suffix=new_name,
                              target_skeleton=new_perf.target_skeleton)
            state.add_ext_drivers()
            state._organize_performer_root()
        except Exception as e:
            self.report({'WARNING'}, f"重命名完成，但重建驱动失败: {str(e)}")

        # 更新场景状态：把当前角色切到新名字
        try:
            setattr(scene, ui_utils.SCENE_ACTIVE_PERFORMER, new_name)
        except Exception:
            pass

        self.report({'INFO'}, f"已将角色重命名为 {new_name}")
        return {'FINISHED'}


class FRET_DANCE_OT_migrate_legacy(Operator):
    """把旧版无后缀的控件迁移到当前演奏者（有后缀 + 设计层级）"""
    bl_idname = "music_doll.fret_dance_migrate_legacy"
    bl_label = "迁移旧场景到当前演奏者"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        suffix = _get_active_suffix(context)
        if not suffix:
            self.report({'ERROR'}, "请先输入演奏者后缀")
            return {'CANCELLED'}
        if performer_utils.has_performer(suffix):
            self.report({'ERROR'}, f"已存在后缀 {suffix} 的演奏者，请换一个后缀")
            return {'CANCELLED'}
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选中/指定目标骨骼")
            return {'CANCELLED'}

        base_state = _build_base_state(context, use_skeleton=False)
        if not base_state.migrate_legacy_to_suffix():
            self.report({'ERROR'}, "迁移失败，详见控制台")
            return {'CANCELLED'}
        self.report(
            {'INFO'}, f"迁移完成：演奏者 {base_state.performer_name} ({suffix})，详见控制台")
        return {'FINISHED'}


class FRET_DANCE_PT_main_panel(Panel):
    """FretDance 乐器子面板（挂在 MusicDoll 统一主面板下，按乐器类型显示）"""
    bl_label = "FretDance"
    bl_idname = "FRET_DANCE_PT_main_panel"
    bl_parent_id = "MUSICDOLL_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MusicDoll"

    @classmethod
    def poll(cls, context):
        return ui_utils.active_instrument(context) == "fret_dance"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # 第一大块：初始化
        box = layout.box()
        box.label(text="初始化", icon='TOOL_SETTINGS')
        row = box.row()
        row.prop(scene, "fret_dance_instruments")

        if scene.fret_dance_instruments == '1':
            row = box.row()
            row.prop(scene, "fret_dance_use_vibrato_bar",
                     text="Use Vibrato Bar (颤音摇杆)")

        row = box.row(align=True)
        row.operator("music_doll.fret_dance_check_status")
        row.operator("music_doll.fret_dance_setup_objects")

        row = box.row()
        row.operator("music_doll.fret_dance_migrate_legacy",
                     text="迁移旧场景到当前演奏者")

        # 工具区（公共工具 + 本乐器独有工具，折叠 + 按选中展开）
        ui_utils.draw_tools(layout, scene, tools=TOOLS)

        # 第三大块：Choose left hand state
        box = layout.box()
        box.label(text="选择左手状态", icon='HAND')
        row = box.row()
        row.prop(scene, "fret_dance_base_positions")
        row = box.row()
        row.prop(scene, "fret_dance_left_hand_states")

        # 第四大块：Choose right hand state
        box = layout.box()
        box.label(text="选择右手状态", icon='RIGHTARROW_THIN')
        row = box.row()
        row.prop(scene, "fret_dance_right_hand_states")

        # 第五大块：Set and Load
        box = layout.box()
        box.label(text="设置与加载", icon='FILE_REFRESH')
        row = box.row(align=True)
        row.operator("music_doll.fret_dance_set_state")
        row.operator("music_doll.fret_dance_load_state")

        # 第六大块：保存控制信息
        box = layout.box()
        box.label(text="导入/导出人物信息", icon='EXPORT')
        row = box.row(align=True)
        row.operator("music_doll.fret_dance_import_info", text="导入")
        row.operator("music_doll.fret_dance_export_info", text="导出")
        box.operator("music_doll.fret_dance_export_to_unreal",
                     text="导出到 Unreal", icon='EXPORT')

        # 第七大块：动画生成部分
        box = layout.box()
        box.label(text="生成动画", icon='PLAY')
        row = box.row()
        row.prop(scene, "fret_dance_animation_file", text="")

        row = box.row(align=True)
        row.operator("music_doll.fret_dance_generate_left_hand_animation",
                     text="左手动画")
        row.operator("music_doll.fret_dance_generate_right_hand_animation",
                     text="右手动画")

        row = box.row(align=True)
        row.operator(
            "music_doll.fret_dance_generate_string_animation", text="弦动画")
        row.operator(
            "music_doll.fret_dance_generate_controller_root_animation",
            text="吉他偏移")
        row = box.row()
        row.operator(
            "music_doll.fret_dance_generate_all_animation", text="一键生成全部动画")


def get_left_hand_states_items(self, context):
    """根据Base Position动态返回Left Hand States选项"""
    position = self.fret_dance_base_positions
    return LEFT_HAND_POSITIONS_MAP.get(position, [('Normal', "Normal", "Normal state")])


def get_right_hand_states_items(self, context):
    """根据 use_vibrato_bar 动态返回 Right Hand States 选项（无状态：优先读骨骼）"""
    items = [
        ('low', "Low", "Low position"),
        ('end', "End", "End position"),
        ('high', "High", "High position"),
    ]
    use_vibrato = context.scene.fret_dance_use_vibrato_bar
    skel = _get_active_skeleton(context)
    if skel is not None:
        probe = BaseState(Instruments(
            int(context.scene.fret_dance_instruments)))
        use_vibrato = probe.load_settings(skel)["use_vibrato_bar"]
    if use_vibrato:
        items += [
            ('release', "Release", "Vibrato bar release"),
            ('up', "Up", "Vibrato bar up"),
            ('down', "Down", "Vibrato bar down"),
        ]
    return items


# ── 注册/注销 ──────────────────────────────────────────────

def register():
    # 注册枚举属性
    bpy.types.Scene.fret_dance_instruments = EnumProperty(
        name="Instrument",
        description="Select instrument type",
        items=[
            ('0', "Finger Style Guitar", "Finger style guitar"),
            ('1', "Electric Guitar", "Electric guitar"),
            ('2', "Bass", "Bass guitar"),
        ],
        default='0'
    )

    bpy.types.Scene.fret_dance_base_positions = EnumProperty(
        name="Position",
        description="Select base position",
        items=[
            ('P0', "P0", "Position 0"),
            ('P1', "P1", "Position 1"),
            ('P2', "P2", "Position 2"),
            ('P3', "P3", "Position 3"),
            ('P4', "P4", "Position 4")
        ],
        default='P0'
    )

    bpy.types.Scene.fret_dance_left_hand_states = EnumProperty(
        name="State",
        description="Select left hand state",
        items=get_left_hand_states_items,
        default=0
    )

    bpy.types.Scene.fret_dance_right_hand_states = EnumProperty(
        name="State",
        description="Select right hand state",
        items=get_right_hand_states_items,
        default=0
    )

    bpy.types.Scene.fret_dance_use_vibrato_bar = bpy.props.BoolProperty(
        name="Use Vibrato Bar",
        description="Enable vibrato bar (颤音摇杆) for electric guitar",
        default=False
    )

    bpy.types.Scene.fret_dance_animation_file = StringProperty(
        name="Animation Config File",
        description="Path to animation configuration JSON file",
        subtype='FILE_PATH'
    )

    bpy.types.Scene.fret_dance_string_number = bpy.props.IntProperty(
        name="String Number",
        description="The index number of the string",
        default=0,
        min=0,
        max=6
    )

    bpy.types.Scene.fret_dance_string_amplitude = bpy.props.FloatProperty(
        name="String Amplitude",
        description="振幅与弦长的千分比",
        default=5.0,
        min=0.1,
        max=50.0,
        precision=4,
        step=0.01
    )

    bpy.types.Scene.fret_dance_target_mesh = PointerProperty(
        name="目标Mesh",
        description="存储控制器状态数据的目标角色 Mesh（旧字段，兼容保留）",
        type=bpy.types.Object,
        poll=lambda self, obj: obj is not None and obj.type == "MESH",
    )

    # 注册 Mesh 自定义属性（与旧插件一致）
    bpy.types.Object.fret_dance_controller_data = StringProperty(
        name="Controller Data",
        description="JSON: 所有控制器状态数据（左手各位置、右手各位置、指板位置、其他设置）",
        default="{}",
    )

    # 注册类
    bpy.utils.register_class(FRET_DANCE_OT_setup_objects)
    bpy.utils.register_class(FRET_DANCE_OT_check_status)
    bpy.utils.register_class(FRET_DANCE_OT_set_state)
    bpy.utils.register_class(FRET_DANCE_OT_load_state)
    bpy.utils.register_class(FRET_DANCE_OT_export_info)
    bpy.utils.register_class(FRET_DANCE_OT_import_info)
    bpy.utils.register_class(FRET_DANCE_PT_main_panel)
    bpy.utils.register_class(FRET_DANCE_OT_select_animation_file)
    bpy.utils.register_class(FRET_DANCE_OT_generate_left_hand_animation)
    bpy.utils.register_class(FRET_DANCE_OT_generate_right_hand_animation)
    bpy.utils.register_class(FRET_DANCE_OT_generate_string_animation)
    bpy.utils.register_class(FRET_DANCE_OT_generate_controller_root_animation)
    bpy.utils.register_class(FRET_DANCE_OT_generate_all_animation)
    bpy.utils.register_class(FRET_DANCE_OT_duplicate_performer)
    bpy.utils.register_class(FRET_DANCE_OT_rename_performer)
    bpy.utils.register_class(FRET_DANCE_OT_migrate_legacy)

    # 注册本乐器工具模块（执行算子）
    from .tools import register as register_tools
    register_tools()

    # 登记本乐器 UI（角色生成器下拉 + 角色操作器接入）
    ui_utils.register_instrument(
        "fret_dance", "FretDance 吉他", FRET_DANCE_PT_main_panel,
        rename_operator="music_doll.fret_dance_rename_performer",
        duplicate_operator="music_doll.fret_dance_duplicate_performer")


def unregister():
    # 注销本乐器工具模块
    from .tools import unregister as unregister_tools
    unregister_tools()

    # 注销本乐器 UI 登记
    ui_utils.unregister_instrument("fret_dance")

    bpy.utils.unregister_class(FRET_DANCE_PT_main_panel)
    bpy.utils.unregister_class(FRET_DANCE_OT_export_info)
    bpy.utils.unregister_class(FRET_DANCE_OT_import_info)
    bpy.utils.unregister_class(FRET_DANCE_OT_load_state)
    bpy.utils.unregister_class(FRET_DANCE_OT_set_state)
    bpy.utils.unregister_class(FRET_DANCE_OT_check_status)
    bpy.utils.unregister_class(FRET_DANCE_OT_setup_objects)
    bpy.utils.unregister_class(FRET_DANCE_OT_select_animation_file)
    bpy.utils.unregister_class(FRET_DANCE_OT_generate_all_animation)
    bpy.utils.unregister_class(
        FRET_DANCE_OT_generate_controller_root_animation)
    bpy.utils.unregister_class(FRET_DANCE_OT_generate_string_animation)
    bpy.utils.unregister_class(FRET_DANCE_OT_generate_right_hand_animation)
    bpy.utils.unregister_class(FRET_DANCE_OT_generate_left_hand_animation)
    bpy.utils.unregister_class(FRET_DANCE_OT_duplicate_performer)
    bpy.utils.unregister_class(FRET_DANCE_OT_rename_performer)
    bpy.utils.unregister_class(FRET_DANCE_OT_migrate_legacy)

    del bpy.types.Object.fret_dance_controller_data

    del bpy.types.Scene.fret_dance_target_mesh
    del bpy.types.Scene.fret_dance_instruments
    del bpy.types.Scene.fret_dance_base_positions
    del bpy.types.Scene.fret_dance_left_hand_states
    del bpy.types.Scene.fret_dance_right_hand_states
    del bpy.types.Scene.fret_dance_animation_file
    del bpy.types.Scene.fret_dance_string_number
    del bpy.types.Scene.fret_dance_string_amplitude
