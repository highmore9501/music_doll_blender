# harp_glide/ui.py
"""HarpGlide 乐器模块 —— 面板与算子"""

import os

import bpy  # type: ignore
from bpy.types import Panel, Operator, PropertyGroup  # type: ignore
from bpy.props import (  # type: ignore
    StringProperty, EnumProperty, IntProperty,
    FloatProperty, BoolProperty, PointerProperty,
)

from ..common import ui_utils
from ..common import performer_utils
from ..common.tools import COMMON_TOOLS
from .base import HarpBaseState
from .enums import (
    HandPoseState, PedalNote, PedalState, HarpPivotState,
    HAND_POSE_ITEMS, PEDAL_NOTE_ITEMS, PEDAL_STATE_ITEMS, TILT_STATE_ITEMS,
)
from .state import (
    save_hand_pose, load_hand_pose,
    save_head_pose, load_head_pose,
    save_pedal_state, load_pedal_state,
    save_harp_tilt, load_harp_tilt,
    save_foot_rest, load_foot_rest,
)
from .io import export_harpist, import_harpist
from .animation import generate_all_animations
from .tools import INSTRUMENT_TOOLS
from .tools.string_tools import (
    create_string_shape_key,
    create_all_strings_shape_keys,
    linear_distribute_recorders,
)

TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS


# ── 辅助函数 ─────────────────────────────────────────────────

def _suffix(context) -> str:
    return ui_utils.get_active_suffix(context.scene)


def _skeleton(context):
    return ui_utils.get_target_skeleton(context)


def _instrument(context):
    return ui_utils.get_target_instrument(context)


def _hg_config(context) -> HarpBaseState:
    return HarpBaseState(
        performer_suffix=_suffix(context),
        target_skeleton=_skeleton(context),
        target_instrument=_instrument(context),
    )


# ── 属性组 ────────────────────────────────────────────────────

class HarpGlideProperties(PropertyGroup):
    """HarpGlide 面板场景属性"""
    __annotations__ = {
        "string_count": IntProperty(
            name="弦数", default=47, min=1, max=200),
        "left_far": IntProperty(
            name="左远", default=0, min=0, max=100),
        "left_near": IntProperty(
            name="左近", default=0, min=0, max=100),
        "left_mid_far": IntProperty(
            name="左中远", default=0, min=0, max=100),
        "left_mid_near": IntProperty(
            name="左中近", default=0, min=0, max=100),
        "right_far": IntProperty(
            name="右远", default=0, min=0, max=100),
        "right_near": IntProperty(
            name="右近", default=0, min=0, max=100),
        "tilt_state": EnumProperty(
            name="倾斜状态", items=TILT_STATE_ITEMS, default="NEAR"),
        "hand_pose_hand": EnumProperty(
            name="手", items=[("left", "Left", ""), ("right", "Right", "")],
            default="left"),
        "hand_pose_state": EnumProperty(
            name="姿势", items=HAND_POSE_ITEMS, default="FAR"),
        "pedal_note": EnumProperty(
            name="唱名", items=PEDAL_NOTE_ITEMS, default="D"),
        "pedal_state": EnumProperty(
            name="位置", items=PEDAL_STATE_ITEMS, default="STATE_2"),
        "string_index": IntProperty(
            name="弦序号", default=20, min=0, max=199),
        "string_amplitude": FloatProperty(
            name="振幅比例", default=0.005, min=0.0001, max=0.1,
            precision=4, step=0.0001),
        "animation_report": StringProperty(
            name="动画报告", default="", subtype="FILE_PATH"),
        "show_state_settings": BoolProperty(
            name="状态设置", default=False),
    }


# ── 算子 ─────────────────────────────────────────────────────

class HG_OT_setup_objects(Operator):
    """创建 HarpGlide 所有控件和弦位置标记"""
    bl_idname = "harp_glide.setup_objects"
    bl_label = "Setup Objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        cfg = _hg_config(context)
        skel = _skeleton(context)
        # 先把面板配置写回骨骼 JSON（与其它乐器模块一致：骨骼是唯一事实来源）
        if skel is not None:
            cfg.save_harp_config(props, skel)
        ok = cfg.setup_all_objects(string_count=int(props.string_count))
        if ok:
            self.report({"INFO"}, f"HarpGlide 控件已就绪（弦数：{props.string_count}）")
        else:
            self.report({"ERROR"}, "请先在「角色生成器」初始化角色")
        return {"FINISHED"}


class HG_OT_save_harp_config(Operator):
    """将面板参数（弦数 + 手部位置参数）保存到骨骼 JSON"""
    bl_idname = "harp_glide.save_harp_config"
    bl_label = "Save Harp Config"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        cfg = _hg_config(context)
        cfg.save_harp_config(props, skel)
        self.report({"INFO"}, "竖琴配置已保存")
        return {"FINISHED"}


class HG_OT_save_hand_pose(Operator):
    bl_idname = "harp_glide.save_hand_pose"
    bl_label = "Save"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        hand = props.hand_pose_hand
        state = HandPoseState[props.hand_pose_state]
        save_hand_pose(_suffix(context), hand, state, skel)
        save_head_pose(_suffix(context), state, skel)
        self.report({"INFO"}, f"已保存手部+头部姿势：{hand} {state.value}")
        return {"FINISHED"}


class HG_OT_load_hand_pose(Operator):
    bl_idname = "harp_glide.load_hand_pose"
    bl_label = "Load"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        hand = props.hand_pose_hand
        state = HandPoseState[props.hand_pose_state]
        load_hand_pose(_suffix(context), hand, state, skel)
        load_head_pose(_suffix(context), state, skel)
        self.report({"INFO"}, f"已加载手部+头部姿势：{hand} {state.value}")
        return {"FINISHED"}


class HG_OT_save_pedal(Operator):
    bl_idname = "harp_glide.save_pedal"
    bl_label = "Save"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        note = PedalNote[props.pedal_note]
        state = PedalState[props.pedal_state]
        save_pedal_state(_suffix(context), note, state, skel)
        self.report({"INFO"}, f"踏板已保存：{note.value} {state.value}")
        return {"FINISHED"}


class HG_OT_load_pedal(Operator):
    bl_idname = "harp_glide.load_pedal"
    bl_label = "Load"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        note = PedalNote[props.pedal_note]
        state = PedalState[props.pedal_state]
        load_pedal_state(_suffix(context), note, state, skel)
        self.report({"INFO"}, f"踏板已加载：{note.value} {state.value}")
        return {"FINISHED"}


class HG_OT_save_tilt(Operator):
    bl_idname = "harp_glide.save_tilt"
    bl_label = "Save"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        save_harp_tilt(_suffix(context),
                       HarpPivotState[props.tilt_state], skel)
        self.report({"INFO"}, f"竖琴倾斜已保存：{props.tilt_state}")
        return {"FINISHED"}


class HG_OT_load_tilt(Operator):
    bl_idname = "harp_glide.load_tilt"
    bl_label = "Load"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        load_harp_tilt(_suffix(context),
                       HarpPivotState[props.tilt_state], skel)
        self.report({"INFO"}, f"竖琴倾斜已加载：{props.tilt_state}")
        return {"FINISHED"}


class HG_OT_save_foot_rest(Operator):
    bl_idname = "harp_glide.save_foot_rest"
    bl_label = "Save Foot Rest"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        save_foot_rest(_suffix(context), skel)
        self.report({"INFO"}, "脚部休息位置已保存")
        return {"FINISHED"}


class HG_OT_load_foot_rest(Operator):
    bl_idname = "harp_glide.load_foot_rest"
    bl_label = "Load Foot Rest"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        load_foot_rest(_suffix(context), skel)
        self.report({"INFO"}, "脚部休息位置已加载")
        return {"FINISHED"}


class HG_OT_export(Operator):
    """导出 .harpist 文件（从骨骼 JSON + 物理弦标记）"""
    bl_idname = "harp_glide.export"
    bl_label = "Export .harpist"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        path = getattr(context.scene, ui_utils.SCENE_INFO_PATH, "")
        if not path:
            self.report({"ERROR"}, "请先在「角色操作」设置人物信息路径")
            return {"CANCELLED"}
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        try:
            export_harpist(path, _suffix(context), skel,
                           context.scene.md_hg_props)
            self.report({"INFO"}, f"已导出 → {path}")
        except Exception as e:
            self.report({"ERROR"}, f"导出失败：{e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class HG_OT_import(Operator):
    """从 .harpist 文件导入（写骨骼 JSON + 物理弦标记）"""
    bl_idname = "harp_glide.import"
    bl_label = "Import .harpist"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        path = getattr(context.scene, ui_utils.SCENE_INFO_PATH, "")
        if not path:
            self.report({"ERROR"}, "请先在「角色操作」设置人物信息路径")
            return {"CANCELLED"}
        if not os.path.exists(path):
            self.report({"ERROR"}, f"文件不存在：{path}")
            return {"CANCELLED"}
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        try:
            import_harpist(path, _suffix(context), skel,
                           context.scene.md_hg_props)
            self.report({"INFO"}, f"已导入 ← {path}")
        except Exception as e:
            self.report({"ERROR"}, f"导入失败：{e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class HG_OT_generate_performer_anim(Operator):
    bl_idname = "harp_glide.generate_performer_anim"
    bl_label = "生成演奏者动画"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        report = props.animation_report
        if not report or not os.path.exists(report):
            self.report({"ERROR"}, "请先选择有效的 .harpglide 报告文件")
            return {"CANCELLED"}
        try:
            from .animation import generate_harp_animation, generate_performance_animation
            import json
            with open(report, "r", encoding="utf-8") as f:
                rp = json.load(f)
            base = os.path.dirname(report)

            def _abs(p):
                return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
            suffix = _suffix(context)
            hp = _abs(rp.get("harp_animation", ""))
            pp = _abs(rp.get("performance_animation", ""))
            if hp and os.path.exists(hp):
                generate_harp_animation(hp, suffix)
            if pp and os.path.exists(pp):
                generate_performance_animation(pp, suffix)
            self.report({"INFO"}, "演奏者动画生成完成")
        except Exception as e:
            self.report({"ERROR"}, f"生成失败：{e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class HG_OT_generate_instrument_anim(Operator):
    bl_idname = "harp_glide.generate_instrument_anim"
    bl_label = "生成乐器动画"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        report = props.animation_report
        if not report or not os.path.exists(report):
            self.report({"ERROR"}, "请先选择有效的 .harpglide 报告文件")
            return {"CANCELLED"}
        try:
            from .animation import generate_shape_key_animations
            import json
            with open(report, "r", encoding="utf-8") as f:
                rp = json.load(f)
            base = os.path.dirname(report)

            def _abs(p):
                return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
            pp = _abs(rp.get("pedal_shape_animation", ""))
            sp = _abs(rp.get("string_animation", ""))
            if (pp and os.path.exists(pp)) or (sp and os.path.exists(sp)):
                generate_shape_key_animations(
                    pp if pp and os.path.exists(pp) else "",
                    sp if sp and os.path.exists(sp) else "")
            self.report({"INFO"}, "乐器动画生成完成")
        except Exception as e:
            self.report({"ERROR"}, f"生成失败：{e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class HG_OT_generate_all_anim(Operator):
    bl_idname = "harp_glide.generate_all_anim"
    bl_label = "一键生成所有动画"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        report = props.animation_report
        if not report or not os.path.exists(report):
            self.report({"ERROR"}, "请先选择有效的 .harpglide 报告文件")
            return {"CANCELLED"}
        try:
            generate_all_animations(report, _suffix(context))
            self.report({"INFO"}, "全部动画生成完成")
        except Exception as e:
            self.report({"ERROR"}, f"生成失败：{e}")
            return {"CANCELLED"}
        return {"FINISHED"}


# ── 工具算子 ─────────────────────────────────────────────────

class HG_OT_create_string_shape_key(Operator):
    bl_idname = "harp_glide.create_string_shape_key"
    bl_label = "生成弦 Shape Key"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        try:
            create_string_shape_key(skel, _suffix(context),
                                    int(props.string_index),
                                    props.string_amplitude)
            self.report({"INFO"}, f"弦 {props.string_index} Shape Key 创建完成")
        except Exception as e:
            self.report({"ERROR"}, f"失败：{e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class HG_OT_create_all_strings_shape_keys(Operator):
    bl_idname = "harp_glide.create_all_strings_shape_keys"
    bl_label = "批量生成所有弦 Shape Key"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_hg_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        try:
            create_all_strings_shape_keys(skel, _suffix(context),
                                          props.string_amplitude)
            self.report({"INFO"}, "批量生成完成")
        except Exception as e:
            self.report({"ERROR"}, f"失败：{e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class HG_OT_linear_distribute_recorders(Operator):
    bl_idname = "harp_glide.linear_distribute_recorders"
    bl_label = "线性分布弦位置"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            linear_distribute_recorders(_suffix(context))
            self.report({"INFO"}, "线性分布完成")
        except Exception as e:
            self.report({"ERROR"}, f"失败：{e}")
            return {"CANCELLED"}
        return {"FINISHED"}


# ── 重命名/复制算子 ───────────────────────────────────────────

class HG_OT_rename_performer(Operator):
    bl_idname = "harp_glide.rename_performer"
    bl_label = "重命名当前角色"
    bl_options = {"REGISTER", "UNDO"}
    new_name: StringProperty(default="", name="新名字")

    def invoke(self, context, event):
        src = ui_utils.get_rename_target(context)
        if src is not None and src.name and src.name.isascii():
            self.new_name = src.name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        src = ui_utils.get_rename_target(context)
        if src is None:
            self.report({"ERROR"}, "找不到当前角色")
            return {"CANCELLED"}
        new_name = self.new_name.strip()
        if not new_name:
            self.report({"ERROR"}, "请输入新名字")
            return {"CANCELLED"}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report({"ERROR"}, "名字只能用英文字母和数字")
            return {"CANCELLED"}
        if new_name == src.name:
            self.report({"ERROR"}, "新名字与当前相同")
            return {"CANCELLED"}
        if performer_utils.has_performer(new_name):
            self.report({"ERROR"}, f"已存在名字 {new_name}")
            return {"CANCELLED"}
        try:
            performer_utils.resuffix_performer(
                src.collection, new_name, new_name=new_name)
        except Exception as e:
            self.report({"ERROR"}, f"重命名失败：{e}")
            return {"CANCELLED"}
        try:
            setattr(context.scene, ui_utils.SCENE_ACTIVE_PERFORMER, new_name)
        except Exception:
            pass
        self.report({"INFO"}, f"已重命名为 {new_name}")
        return {"FINISHED"}


class HG_OT_duplicate_performer(Operator):
    bl_idname = "harp_glide.duplicate_performer"
    bl_label = "复制角色"
    bl_options = {"REGISTER", "UNDO"}
    new_name: StringProperty(default="", name="新名字")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        suffix = _suffix(context)
        if not suffix:
            self.report({"ERROR"}, "请先选中要复制的角色")
            return {"CANCELLED"}
        src = performer_utils.get_performer(suffix)
        if src is None:
            self.report({"ERROR"}, f"找不到角色 {suffix}")
            return {"CANCELLED"}
        new_name = self.new_name.strip()
        if not new_name:
            self.report({"ERROR"}, "请输入新名字")
            return {"CANCELLED"}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report({"ERROR"}, "名字只能用英文字母和数字")
            return {"CANCELLED"}
        if performer_utils.has_performer(new_name):
            self.report({"ERROR"}, f"已存在名字 {new_name}")
            return {"CANCELLED"}
        try:
            dup = performer_utils.duplicate_collection_tree(src.collection)
        except Exception as e:
            self.report({"ERROR"}, f"复制失败：{e}")
            return {"CANCELLED"}
        if dup is None:
            self.report({"ERROR"}, "复制集合失败")
            return {"CANCELLED"}
        from ..common import instrument_base
        instrument_base.set_coll_attr(dup, "name", src.name)
        instrument_base.set_coll_attr(dup, "instrument", src.instrument)
        performer_utils.resuffix_performer(dup, new_name, new_name=new_name)
        self.report({"INFO"}, f"已复制为 {new_name}")
        return {"FINISHED"}


# ── 面板 ─────────────────────────────────────────────────────

class HG_PT_main_panel(Panel):
    """HarpGlide 乐器子面板"""
    bl_label = "Harp Glide"
    bl_idname = "HARPGLIDE_PT_main_panel"
    bl_parent_id = "MUSICDOLL_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MusicDoll"

    # 记录上一次已同步配置的骨骼名（类属性：面板实例每次 draw 都新建）
    _synced_skeleton_name = ""

    @classmethod
    def poll(cls, context):
        return ui_utils.active_instrument(context) == "harp_glide"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.md_hg_props

        # 目标骨骼切换时：把骨骼 JSON config 回填到面板（读取从骨骼来）。
        # 只记录「骨骼名变化」时才回填，同一骨骼上用户正在编辑的值不会被覆盖。
        skel = _skeleton(context)
        skel_name = getattr(skel, "name", None) or ""
        if skel_name != type(self)._synced_skeleton_name:
            type(self)._synced_skeleton_name = skel_name
            if skel is not None:
                _hg_config(context).load_harp_config(props, skel)

        # 1. 竖琴设置
        box = layout.box()
        box.label(text="竖琴设置", icon="SETTINGS")
        row = box.row()
        row.prop(props, "string_count", text="弦数")
        row = box.row(align=True)
        row.prop(props, "left_far",  text="左远")
        row.prop(props, "left_near", text="左近")
        row = box.row(align=True)
        row.prop(props, "left_mid_far",  text="左中远")
        row.prop(props, "left_mid_near", text="左中近")
        row = box.row(align=True)
        row.prop(props, "right_far",  text="右远")
        row.prop(props, "right_near", text="右近")
        box.operator("harp_glide.save_harp_config", text="保存配置到骨骼")

        # 2. 初始化
        box = layout.box()
        box.label(text="初始化", icon="TOOL_SETTINGS")
        box.operator("harp_glide.setup_objects", text="Setup Objects")

        # 3. 工具区（公共工具 + 本乐器独有工具，折叠 + 按选中展开）
        ui_utils.draw_tools(layout, scene, tools=TOOLS)

        # 4. 状态设置（折叠）
        row = layout.row(align=True)
        row.prop(props, "show_state_settings",
                 icon="TRIA_DOWN" if props.show_state_settings else "TRIA_RIGHT",
                 icon_only=True, emboss=False)
        row.label(text="状态设置", icon="SETTINGS")

        if props.show_state_settings:
            state_box = layout.box()

            # 4.1 手部 + 头部姿势
            b = state_box.box()
            b.label(text="手部 + 头部姿势", icon="HAND")
            row = b.row(align=True)
            row.prop(props, "hand_pose_hand", text="手")
            row.prop(props, "hand_pose_state", text="状态")
            row = b.row(align=True)
            row.operator("harp_glide.save_hand_pose", text="Save")
            row.operator("harp_glide.load_hand_pose", text="Load")

            # 4.2 踏板状态
            b = state_box.box()
            b.label(text="踏板（D/C/B→左脚，E/F/G/A→右脚）", icon="ALIGN_BOTTOM")
            row = b.row(align=True)
            row.prop(props, "pedal_note",  text="唱名")
            row.prop(props, "pedal_state", text="位置")
            row = b.row(align=True)
            row.operator("harp_glide.save_pedal", text="Save")
            row.operator("harp_glide.load_pedal", text="Load")

            # 4.3 竖琴倾斜
            b = state_box.box()
            b.label(text="竖琴倾斜状态", icon="ORIENTATION_GLOBAL")
            b.prop(props, "tilt_state", text="状态")
            row = b.row(align=True)
            row.operator("harp_glide.save_tilt", text="Save")
            row.operator("harp_glide.load_tilt", text="Load")

            # 4.4 脚部休息
            b = state_box.box()
            b.label(text="脚部休息位置", icon="ALIGN_BOTTOM")
            row = b.row(align=True)
            row.operator("harp_glide.save_foot_rest", text="Save")
            row.operator("harp_glide.load_foot_rest", text="Load")

        # 5. 导出 / 导入
        box = layout.box()
        box.label(text="数据文件 (.harpist)", icon="FILE")
        row = box.row(align=True)
        row.operator("harp_glide.export",
                     text="Export .harpist", icon="EXPORT")
        row.operator("harp_glide.import",
                     text="Import .harpist", icon="IMPORT")
        box.operator("harp_glide.export_to_unreal",
                     text="导出到 Unreal", icon="EXPORT")

        # 6. 生成动画
        box = layout.box()
        box.label(text="生成动画", icon="PLAY")
        box.prop(props, "animation_report", text="")
        row = box.row(align=True)
        row.operator("harp_glide.generate_performer_anim", text="演奏者动画")
        row.operator("harp_glide.generate_instrument_anim", text="乐器动画")
        box.operator("harp_glide.generate_all_anim",
                     text="一键生成所有动画", icon="PLAY")


# ── 注册 / 注销 ───────────────────────────────────────────────

_CLASSES = (
    HarpGlideProperties,
    HG_OT_setup_objects,
    HG_OT_save_harp_config,
    HG_OT_save_hand_pose,
    HG_OT_load_hand_pose,
    HG_OT_save_pedal,
    HG_OT_load_pedal,
    HG_OT_save_tilt,
    HG_OT_load_tilt,
    HG_OT_save_foot_rest,
    HG_OT_load_foot_rest,
    HG_OT_export,
    HG_OT_import,
    HG_OT_generate_performer_anim,
    HG_OT_generate_instrument_anim,
    HG_OT_generate_all_anim,
    HG_OT_create_string_shape_key,
    HG_OT_create_all_strings_shape_keys,
    HG_OT_linear_distribute_recorders,
    HG_OT_rename_performer,
    HG_OT_duplicate_performer,
    HG_PT_main_panel,
)


def register():
    from .tools import register as tools_register
    tools_register()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.md_hg_props = PointerProperty(type=HarpGlideProperties)

    ui_utils.register_instrument(
        "harp_glide", "Harp Glide 竖琴", HG_PT_main_panel,
        rename_operator="harp_glide.rename_performer",
        duplicate_operator="harp_glide.duplicate_performer",
    )


def unregister():
    ui_utils.unregister_instrument("harp_glide")
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "md_hg_props"):
        del bpy.types.Scene.md_hg_props
    from .tools import unregister as tools_unregister
    tools_unregister()
