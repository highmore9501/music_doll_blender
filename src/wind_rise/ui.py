# wind_rise/ui.py
"""WindRise 乐器模块 —— 面板与算子"""

import os

import bpy  # type: ignore
from bpy.types import Panel, Operator, PropertyGroup  # type: ignore
from bpy.props import (  # type: ignore
    EnumProperty, IntProperty, PointerProperty, StringProperty, BoolProperty,
)

from ..common import ui_utils
from ..common import performer_utils
from ..common import i18n
from ..common.tools import COMMON_TOOLS

T = i18n.T
bl_label_set = i18n.bl_label_set
from .config import WindRiseConfig
from .enums import WIND_INSTRUMENT_TYPE_ITEMS, midi_to_name
from .state import (
    save_note_state, load_note_state,
    get_force_shape_keys, set_force_shape_keys,
    get_instrument_shape_keys, set_instrument_shape_keys,
)
from .io import export_wind, import_wind
from .animation import generate_animation_from_wind_rise
from .tools import INSTRUMENT_TOOLS, register as tools_register, unregister as tools_unregister

TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS


# ── 辅助函数 ──────────────────────────────────────────────────

def _suffix(context) -> str:
    return ui_utils.get_active_suffix(context.scene)


def _skeleton(context):
    return ui_utils.get_target_skeleton(context)


def _wr_config(context) -> WindRiseConfig:
    return WindRiseConfig(
        performer_suffix=_suffix(context),
        target_skeleton=_skeleton(context),
        target_instrument=ui_utils.get_target_instrument(context),
    )


def _instrument(context):
    """当前目标乐器（上一级 MusicDoll 定义），即乐器 Shape Key 的载体。"""
    return ui_utils.get_target_instrument(context)


# 人物 / 乐器 Shape Key 折叠区场景属性名（默认收起）
SCENE_SHOW_CHARACTER_SK = "md_wr_show_character_sk"
SCENE_SHOW_INSTRUMENT_SK = "md_wr_show_instrument_sk"


def _fold_header(box, scene, prop_name: str, label: str, icon: str):
    """折叠标题行：三角箭头（点击切换）+ 文本。"""
    row = box.row()
    row.prop(scene, prop_name,
             icon="TRIA_DOWN" if getattr(scene, prop_name, False)
             else "TRIA_RIGHT", icon_only=True, emboss=False)
    row.label(text=label, icon=icon)


def _get_note_items(self, context):
    props = context.scene.md_wr_props
    items = []
    for note in range(props.min_note, props.max_note + 1):
        name = f"{midi_to_name(note)} ({note})"
        items.append((str(note), name, T("MIDI 音高 %s") % note))
    return items


def _mesh_poll(_, obj):
    return obj is not None and obj.type == "MESH"


# ── 属性组 ────────────────────────────────────────────────────

class WindRiseProperties(PropertyGroup):
    __annotations__ = {
        "lip_mesh": PointerProperty(
            name=T("人物Mesh"),
            description=T("包含嘴唇 Shape Key 的角色网格"),
            type=bpy.types.Object,
            poll=_mesh_poll,
        ),
        "description": StringProperty(
            name=T("乐器说明"),
            description=T("指法说明 / 乐器描述（自由文本）"),
            default="",
        ),
        "current_note": EnumProperty(
            name=T("当前音高"),
            description=T("当前正在编辑的 MIDI 音符号"),
            items=_get_note_items,
        ),
        "new_character_sk": StringProperty(
            name=T("新人物 SK"),
            description=T("从人物 Mesh 选择要添加的 Shape Key"),
            default="",
        ),
        "new_instrument_sk": StringProperty(
            name=T("新乐器 SK"),
            description=T("从乐器 Mesh 选择要添加的 Shape Key"),
            default="",
        ),
        "instrument_type": EnumProperty(
            name=T("乐器类型"),
            description=T("导出到 .wind 的 instrument_type"),
            items=WIND_INSTRUMENT_TYPE_ITEMS,
            default="chinese_dizi",
        ),
        "custom_instrument_type": StringProperty(
            name=T("自定义乐器类型"),
            description=T("自定义乐器类型名称"),
            default="flute",
        ),
        "min_note": IntProperty(name=T("最小音高"), default=60),
        "max_note": IntProperty(name=T("最大音高"), default=84),
        "wind_rise_animation_file_path": StringProperty(
            name=T(".wind_rise 文件"),
            description=T("动画汇总 .wind_rise 文件路径"),
            subtype="FILE_PATH",
            default="",
        ),
    }


# ── 算子 ─────────────────────────────────────────────────────

class WR_OT_setup_objects(Operator):
    bl_idname = "music_doll.wind_rise_setup_objects"
    bl_label = T("Setup Objects")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ok = _wr_config(context).setup_all_objects()
        if ok:
            self.report({"INFO"}, T("WindRise 控件已就绪"))
        else:
            self.report({"ERROR"}, T("请先在「角色生成器」初始化角色"))
        return {"FINISHED"}


class WR_OT_save_state(Operator):
    bl_idname = "music_doll.wind_rise_save_state"
    bl_label = T("保存状态")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, T("请先选择目标骨骼"))
            return {"CANCELLED"}
        try:
            note = int(props.current_note)
            save_note_state(note, _suffix(context), skel,
                            props.lip_mesh, _instrument(context))
            self.report({"INFO"}, T("音高 %s 保存完成") % midi_to_name(note))
        except Exception as e:
            self.report({"ERROR"}, T("保存失败: %s") % str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class WR_OT_load_state(Operator):
    bl_idname = "music_doll.wind_rise_load_state"
    bl_label = T("加载状态")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, T("请先选择目标骨骼"))
            return {"CANCELLED"}
        try:
            note = int(props.current_note)
            load_note_state(note, _suffix(context), skel,
                            props.lip_mesh, _instrument(context))
            self.report({"INFO"}, T("音高 %s 加载完成") % midi_to_name(note))
        except Exception as e:
            self.report({"ERROR"}, T("加载失败: %s") % str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class WR_OT_export_wind(Operator):
    bl_idname = "music_doll.wind_rise_export_wind"
    bl_label = T("导出 .wind")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        path = getattr(context.scene, ui_utils.SCENE_INFO_PATH, "")
        if not path:
            self.report({"ERROR"}, T("请先在「角色操作」设置人物信息路径"))
            return {"CANCELLED"}
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, T("请先选择目标骨骼"))
            return {"CANCELLED"}
        props = context.scene.md_wr_props
        try:
            out = export_wind(path, skel, props.min_note, props.max_note)
            self.report({"INFO"}, T("导出完成: %s") % out)
        except Exception as e:
            self.report({"ERROR"}, T("导出失败: %s") % str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class WR_OT_import_wind(Operator):
    bl_idname = "music_doll.wind_rise_import_wind"
    bl_label = T("导入 .wind")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        path = getattr(context.scene, ui_utils.SCENE_INFO_PATH, "")
        if not path:
            self.report({"ERROR"}, T("请先在「角色操作」设置人物信息路径"))
            return {"CANCELLED"}
        if not os.path.exists(path):
            self.report({"ERROR"}, T("文件不存在: %s") % path)
            return {"CANCELLED"}
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, T("请先选择目标骨骼"))
            return {"CANCELLED"}
        try:
            config = import_wind(path, skel)
            props = context.scene.md_wr_props
            if "instrument_type" in config:
                it = str(config["instrument_type"])
                if it in [x[0] for x in WIND_INSTRUMENT_TYPE_ITEMS]:
                    props.instrument_type = it
                else:
                    props.instrument_type = "custom"
                    props.custom_instrument_type = it
            if "min_note" in config:
                props.min_note = int(config["min_note"])
            if "max_note" in config:
                props.max_note = int(config["max_note"])
            if "description" in config:
                props.description = str(config["description"])
            self.report({"INFO"}, T("导入完成"))
        except Exception as e:
            self.report({"ERROR"}, T("导入失败: %s") % str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class WR_OT_generate_animation(Operator):
    bl_idname = "music_doll.wind_rise_generate_animation"
    bl_label = T("生成动画")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        file_path = props.wind_rise_animation_file_path
        if not file_path:
            self.report({"ERROR"}, T("请先选择 .wind_rise 文件"))
            return {"CANCELLED"}
        if not file_path.endswith(".wind_rise"):
            self.report({"ERROR"}, T("选择的文件不是 .wind_rise 文件"))
            return {"CANCELLED"}
        if not os.path.exists(file_path):
            self.report({"ERROR"}, T("文件不存在: %s") % file_path)
            return {"CANCELLED"}
        try:
            generate_animation_from_wind_rise(
                file_path, _suffix(context),
                props.lip_mesh, _instrument(context))
            self.report({"INFO"}, T("动画生成完成"))
        except Exception as e:
            self.report({"ERROR"}, T("动画生成失败: %s") % str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


# ── Shape Key 管理算子 ────────────────────────────────────────

class WR_OT_add_character_sk(Operator):
    bl_idname = "music_doll.wind_rise_add_character_sk"
    bl_label = T("添加")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, T("请先选择目标骨骼"))
            return {"CANCELLED"}
        name = props.new_character_sk
        if not name:
            self.report({"WARNING"}, T("请从下拉菜单选择一个 Shape Key"))
            return {"CANCELLED"}
        lst = get_force_shape_keys(skel)
        if name not in lst:
            lst.append(name)
            set_force_shape_keys(skel, lst)
        props.new_character_sk = ""
        return {"FINISHED"}


class WR_OT_remove_character_sk(Operator):
    bl_idname = "music_doll.wind_rise_remove_character_sk"
    bl_label = ""
    bl_options = {"REGISTER", "UNDO"}
    sk_name: StringProperty()  # type: ignore

    def execute(self, context):
        skel = _skeleton(context)
        if skel is None:
            return {"CANCELLED"}
        lst = get_force_shape_keys(skel)
        if self.sk_name in lst:
            lst.remove(self.sk_name)
            set_force_shape_keys(skel, lst)
        return {"FINISHED"}


class WR_OT_add_instrument_sk(Operator):
    bl_idname = "music_doll.wind_rise_add_instrument_sk"
    bl_label = T("添加")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, T("请先选择目标骨骼"))
            return {"CANCELLED"}
        name = props.new_instrument_sk
        if not name:
            self.report({"WARNING"}, T("请从下拉菜单选择一个 Shape Key"))
            return {"CANCELLED"}
        lst = get_instrument_shape_keys(skel)
        if name not in lst:
            lst.append(name)
            set_instrument_shape_keys(skel, lst)
        props.new_instrument_sk = ""
        return {"FINISHED"}


class WR_OT_remove_instrument_sk(Operator):
    bl_idname = "music_doll.wind_rise_remove_instrument_sk"
    bl_label = ""
    bl_options = {"REGISTER", "UNDO"}
    sk_name: StringProperty()  # type: ignore

    def execute(self, context):
        skel = _skeleton(context)
        if skel is None:
            return {"CANCELLED"}
        lst = get_instrument_shape_keys(skel)
        if self.sk_name in lst:
            lst.remove(self.sk_name)
            set_instrument_shape_keys(skel, lst)
        return {"FINISHED"}


# ── 重命名 / 复制算子 ─────────────────────────────────────────

class WR_OT_rename_performer(Operator):
    bl_idname = "music_doll.wind_rise_rename_performer"
    bl_label = T("重命名当前角色")
    bl_options = {"REGISTER", "UNDO"}
    new_name: StringProperty(default="", name=T("新名字"))  # type: ignore

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
            self.report({"ERROR"}, T("找不到当前角色"))
            return {"CANCELLED"}
        new_name = self.new_name.strip()
        if not new_name:
            self.report({"ERROR"}, T("请输入新名字"))
            return {"CANCELLED"}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report({"ERROR"}, T("名字只能用英文字母和数字"))
            return {"CANCELLED"}
        if new_name == src.name:
            self.report({"ERROR"}, T("新名字与当前相同"))
            return {"CANCELLED"}
        if performer_utils.has_performer(new_name):
            self.report({"ERROR"}, T("已存在名字 %s") % new_name)
            return {"CANCELLED"}
        try:
            performer_utils.resuffix_performer(
                src.collection, new_name, new_name=new_name)
        except Exception as e:
            self.report({"ERROR"}, T("重命名失败：%s") % str(e))
            return {"CANCELLED"}
        try:
            setattr(context.scene, ui_utils.SCENE_ACTIVE_PERFORMER, new_name)
        except Exception:
            pass
        self.report({"INFO"}, T("已重命名为 %s") % new_name)
        return {"FINISHED"}


class WR_OT_duplicate_performer(Operator):
    bl_idname = "music_doll.wind_rise_duplicate_performer"
    bl_label = T("复制角色")
    bl_options = {"REGISTER", "UNDO"}
    new_name: StringProperty(default="", name=T("新名字"))  # type: ignore

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        suffix = _suffix(context)
        if not suffix:
            self.report({"ERROR"}, T("请先选中要复制的角色"))
            return {"CANCELLED"}
        src = performer_utils.get_performer(suffix)
        if src is None:
            self.report({"ERROR"}, T("找不到角色 %s") % suffix)
            return {"CANCELLED"}
        new_name = self.new_name.strip()
        if not new_name:
            self.report({"ERROR"}, T("请输入新名字"))
            return {"CANCELLED"}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report({"ERROR"}, T("名字只能用英文字母和数字"))
            return {"CANCELLED"}
        if performer_utils.has_performer(new_name):
            self.report({"ERROR"}, T("已存在名字 %s") % new_name)
            return {"CANCELLED"}
        try:
            dup = performer_utils.duplicate_collection_tree(src.collection)
        except Exception as e:
            self.report({"ERROR"}, T("复制失败：%s") % str(e))
            return {"CANCELLED"}
        if dup is None:
            self.report({"ERROR"}, T("复制集合失败"))
            return {"CANCELLED"}
        from ..common import instrument_base
        instrument_base.set_coll_attr(dup, "name", src.name)
        instrument_base.set_coll_attr(dup, "instrument", src.instrument)
        performer_utils.resuffix_performer(dup, new_name, new_name=new_name)
        self.report({"INFO"}, T("已复制为 %s") % new_name)
        return {"FINISHED"}


# ── 面板 ─────────────────────────────────────────────────────

class WR_PT_main_panel(Panel):
    """WindRise 乐器子面板"""
    bl_label = T("Wind Rise")
    bl_idname = "WINDRISE_PT_main_panel"
    bl_parent_id = "MUSICDOLL_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MusicDoll"

    @classmethod
    def poll(cls, context):
        return ui_utils.active_instrument(context) == "wind_rise"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.md_wr_props
        skel = _skeleton(context)

        # 1. 初始化
        box = layout.box()
        box.label(text=T("初始化"), icon="TOOL_SETTINGS")
        box.operator("music_doll.wind_rise_setup_objects",
                     text=T("Setup Objects"))

        # 2. 对象选择（人物 Mesh；乐器直接用上一级 MusicDoll 定义的目标乐器）
        box = layout.box()
        box.label(text=T("对象选择"), icon="OBJECT_DATA")
        box.prop(props, "lip_mesh", text=T("人物Mesh"))
        inst = _instrument(context)
        if inst:
            box.label(text=f"{T('乐器')}: {inst.name}", icon="OBJECT_DATA")
        else:
            box.label(text=T("乐器: （未设置，请在「角色操作」选择目标乐器）"),
                      icon="ERROR")

        # 3. 人物 Shape Key（折叠，默认收起）
        box = layout.box()
        _fold_header(box, scene, SCENE_SHOW_CHARACTER_SK,
                     T("人物 Shape Key（嘴唇）"), "SHAPEKEY_DATA")
        if getattr(scene, SCENE_SHOW_CHARACTER_SK, False):
            self._draw_sk_editor(box, context, skel, props.lip_mesh,
                                 get_force_shape_keys, "new_character_sk",
                                 "music_doll.wind_rise_add_character_sk",
                                 "music_doll.wind_rise_remove_character_sk")

        # 4. 乐器 Shape Key（折叠，默认收起；目标乐器来自上一级 MusicDoll）
        box = layout.box()
        _fold_header(box, scene, SCENE_SHOW_INSTRUMENT_SK,
                     T("乐器 Shape Key"), "SHAPEKEY_DATA")
        if getattr(scene, SCENE_SHOW_INSTRUMENT_SK, False):
            self._draw_sk_editor(box, context, skel, inst,
                                 get_instrument_shape_keys, "new_instrument_sk",
                                 "music_doll.wind_rise_add_instrument_sk",
                                 "music_doll.wind_rise_remove_instrument_sk")

        # 5. 乐器说明
        box = layout.box()
        box.label(text=T("乐器说明"), icon="INFO")
        box.prop(props, "description", text="")

        # 6. 工具区（公共工具 + WindRise 独有工具，折叠 + 按选中展开）
        ui_utils.draw_tools(layout, scene, tools=TOOLS)

        # 7. 状态管理
        box = layout.box()
        box.label(text=T("状态管理"), icon="FILE_TICK")
        box.prop(props, "current_note", text=T("当前音高"))
        row = box.row(align=True)
        row.operator("music_doll.wind_rise_save_state",
                     text=T("保存状态"), icon="EXPORT")
        row.operator("music_doll.wind_rise_load_state",
                     text=T("加载状态"), icon="IMPORT")

        # 8. 文件（.wind）
        box = layout.box()
        box.label(text=T("数据文件 (.wind)"), icon="FILE")
        box.prop(props, "instrument_type", text=T("乐器类型"))
        if props.instrument_type == "custom":
            box.prop(props, "custom_instrument_type", text=T("自定义类型"))
        row = box.row(align=True)
        row.prop(props, "min_note", text=T("最小"))
        row.prop(props, "max_note", text=T("最大"))
        row = box.row(align=True)
        row.operator("music_doll.wind_rise_export_wind",
                     text=T("导出 .wind"), icon="EXPORT")
        row.operator("music_doll.wind_rise_import_wind",
                     text=T("导入 .wind"), icon="IMPORT")
        box.operator("music_doll.wind_rise_export_to_unreal",
                     text=T("导出到 Unreal"), icon="EXPORT")

        # 9. 生成动画
        box = layout.box()
        box.label(text=T("生成动画"), icon="PLAY")
        box.prop(props, "wind_rise_animation_file_path", text="")
        box.operator("music_doll.wind_rise_generate_animation",
                     text=T("生成动画"), icon="PLAY")

    def _draw_sk_editor(self, box, context, skel, mesh_obj,
                        getter, new_prop_name, add_op, remove_op):
        if not mesh_obj or mesh_obj.type != "MESH" or not mesh_obj.data.shape_keys:
            box.label(text=T("请先选择含 Shape Key 的 Mesh"), icon="ERROR")
            return
        sk_data = mesh_obj.data.shape_keys
        selected = getter(skel) if skel else []

        if selected:
            col = box.column(align=True)
            for name in selected:
                row = col.row(align=True)
                row.label(text=name, icon="SHAPEKEY_DATA")
                op = row.operator(remove_op, text="", icon="X", emboss=False)
                op.sk_name = name
        else:
            box.label(text=T("（尚未添加 Shape Key）"), icon="INFO")

        row = box.row(align=True)
        row.prop_search(context.scene.md_wr_props, new_prop_name,
                        sk_data, "key_blocks", text="")
        row.operator(add_op, text=T("添加"), icon="ADD")


# ── 注册 / 注销 ───────────────────────────────────────────────

_CLASSES = (
    WindRiseProperties,
    WR_OT_setup_objects,
    WR_OT_save_state,
    WR_OT_load_state,
    WR_OT_export_wind,
    WR_OT_import_wind,
    WR_OT_generate_animation,
    WR_OT_add_character_sk,
    WR_OT_remove_character_sk,
    WR_OT_add_instrument_sk,
    WR_OT_remove_instrument_sk,
    WR_OT_rename_performer,
    WR_OT_duplicate_performer,
    WR_PT_main_panel,
)


def register():
    tools_register()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # Set bl_label dynamically after registration (i18n)
    bl_label_set(WR_OT_setup_objects, "Setup Objects")
    bl_label_set(WR_OT_save_state, "保存状态")
    bl_label_set(WR_OT_load_state, "加载状态")
    bl_label_set(WR_OT_export_wind, "导出 .wind")
    bl_label_set(WR_OT_import_wind, "导入 .wind")
    bl_label_set(WR_OT_generate_animation, "生成动画")
    bl_label_set(WR_OT_add_character_sk, "添加")
    bl_label_set(WR_OT_add_instrument_sk, "添加")
    bl_label_set(WR_OT_rename_performer, "重命名当前角色")
    bl_label_set(WR_OT_duplicate_performer, "复制角色")
    bl_label_set(WR_PT_main_panel, "Wind Rise")
    bpy.types.Scene.md_wr_props = PointerProperty(type=WindRiseProperties)
    for attr, label in ((SCENE_SHOW_CHARACTER_SK, T("显示人物 Shape Key")),
                        (SCENE_SHOW_INSTRUMENT_SK, T("显示乐器 Shape Key"))):
        if not hasattr(bpy.types.Scene, attr):
            setattr(bpy.types.Scene, attr, BoolProperty(
                name=label, description=T("展开/折叠 Shape Key 区"), default=False))
    ui_utils.register_instrument(
        "wind_rise",
        T("WindRise 吹奏"),
        WR_PT_main_panel,
        rename_operator="music_doll.wind_rise_rename_performer",
        duplicate_operator="music_doll.wind_rise_duplicate_performer",
    )


def unregister():
    ui_utils.unregister_instrument("wind_rise")
    if hasattr(bpy.types.Scene, "md_wr_props"):
        del bpy.types.Scene.md_wr_props
    for attr in (SCENE_SHOW_CHARACTER_SK, SCENE_SHOW_INSTRUMENT_SK):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    tools_unregister()
