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
from ..common.tools import COMMON_TOOLS
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


def _get_note_items(self, context):
    props = context.scene.md_wr_props
    items = []
    for note in range(props.min_note, props.max_note + 1):
        name = f"{midi_to_name(note)} ({note})"
        items.append((str(note), name, f"MIDI 音高 {note}"))
    return items


def _mesh_poll(_, obj):
    return obj is not None and obj.type == "MESH"


# ── 属性组 ────────────────────────────────────────────────────

class WindRiseProperties(PropertyGroup):
    __annotations__ = {
        "lip_mesh": PointerProperty(
            name="人物Mesh",
            description="包含嘴唇 Shape Key 的角色网格",
            type=bpy.types.Object,
            poll=_mesh_poll,
        ),
        "instrument_mesh": PointerProperty(
            name="乐器Mesh",
            description="包含乐器 Shape Key 的乐器网格",
            type=bpy.types.Object,
            poll=_mesh_poll,
        ),
        "description": StringProperty(
            name="乐器说明",
            description="指法说明 / 乐器描述（自由文本）",
            default="",
        ),
        "current_note": EnumProperty(
            name="当前音高",
            description="当前正在编辑的 MIDI 音符号",
            items=_get_note_items,
        ),
        "new_character_sk": StringProperty(
            name="新人物 SK",
            description="从人物 Mesh 选择要添加的 Shape Key",
            default="",
        ),
        "new_instrument_sk": StringProperty(
            name="新乐器 SK",
            description="从乐器 Mesh 选择要添加的 Shape Key",
            default="",
        ),
        "instrument_type": EnumProperty(
            name="乐器类型",
            description="导出到 .wind 的 instrument_type",
            items=WIND_INSTRUMENT_TYPE_ITEMS,
            default="chinese_dizi",
        ),
        "custom_instrument_type": StringProperty(
            name="自定义乐器类型",
            description="自定义乐器类型名称",
            default="flute",
        ),
        "min_note": IntProperty(name="最小音高", default=60),
        "max_note": IntProperty(name="最大音高", default=84),
        "wind_rise_animation_file_path": StringProperty(
            name=".wind_rise 文件",
            description="动画汇总 .wind_rise 文件路径",
            subtype="FILE_PATH",
            default="",
        ),
        "show_tools": BoolProperty(name="工具", default=False),
    }


# ── 算子 ─────────────────────────────────────────────────────

class WR_OT_setup_objects(Operator):
    bl_idname = "music_doll.wind_rise_setup_objects"
    bl_label = "Setup Objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ok = _wr_config(context).setup_all_objects()
        if ok:
            self.report({"INFO"}, "WindRise 控件已就绪")
        else:
            self.report({"ERROR"}, "请先在「角色生成器」初始化角色")
        return {"FINISHED"}


class WR_OT_save_state(Operator):
    bl_idname = "music_doll.wind_rise_save_state"
    bl_label = "保存状态"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        try:
            note = int(props.current_note)
            save_note_state(note, _suffix(context), skel,
                            props.lip_mesh, props.instrument_mesh)
            self.report({"INFO"}, f"音高 {midi_to_name(note)} 保存完成")
        except Exception as e:
            self.report({"ERROR"}, f"保存失败: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class WR_OT_load_state(Operator):
    bl_idname = "music_doll.wind_rise_load_state"
    bl_label = "加载状态"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        try:
            note = int(props.current_note)
            load_note_state(note, _suffix(context), skel,
                            props.lip_mesh, props.instrument_mesh)
            self.report({"INFO"}, f"音高 {midi_to_name(note)} 加载完成")
        except Exception as e:
            self.report({"ERROR"}, f"加载失败: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class WR_OT_export_wind(Operator):
    bl_idname = "music_doll.wind_rise_export_wind"
    bl_label = "导出 .wind"
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
        props = context.scene.md_wr_props
        try:
            out = export_wind(path, skel, props.min_note, props.max_note)
            self.report({"INFO"}, f"导出完成: {out}")
        except Exception as e:
            self.report({"ERROR"}, f"导出失败: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class WR_OT_import_wind(Operator):
    bl_idname = "music_doll.wind_rise_import_wind"
    bl_label = "导入 .wind"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        path = getattr(context.scene, ui_utils.SCENE_INFO_PATH, "")
        if not path:
            self.report({"ERROR"}, "请先在「角色操作」设置人物信息路径")
            return {"CANCELLED"}
        if not os.path.exists(path):
            self.report({"ERROR"}, f"文件不存在: {path}")
            return {"CANCELLED"}
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
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
            inst_name = config.get("instrument_mesh_name", "")
            if inst_name:
                found = bpy.data.objects.get(inst_name)
                if found and found.type == "MESH":
                    props.instrument_mesh = found
            self.report({"INFO"}, "导入完成")
        except Exception as e:
            self.report({"ERROR"}, f"导入失败: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class WR_OT_generate_animation(Operator):
    bl_idname = "music_doll.wind_rise_generate_animation"
    bl_label = "生成动画"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        file_path = props.wind_rise_animation_file_path
        if not file_path:
            self.report({"ERROR"}, "请先选择 .wind_rise 文件")
            return {"CANCELLED"}
        if not file_path.endswith(".wind_rise"):
            self.report({"ERROR"}, "选择的文件不是 .wind_rise 文件")
            return {"CANCELLED"}
        if not os.path.exists(file_path):
            self.report({"ERROR"}, f"文件不存在: {file_path}")
            return {"CANCELLED"}
        try:
            generate_animation_from_wind_rise(
                file_path, _suffix(context),
                props.lip_mesh, props.instrument_mesh)
            self.report({"INFO"}, "动画生成完成")
        except Exception as e:
            self.report({"ERROR"}, f"动画生成失败: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


# ── Shape Key 管理算子 ────────────────────────────────────────

class WR_OT_add_character_sk(Operator):
    bl_idname = "music_doll.wind_rise_add_character_sk"
    bl_label = "添加"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        name = props.new_character_sk
        if not name:
            self.report({"WARNING"}, "请从下拉菜单选择一个 Shape Key")
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
    bl_label = "添加"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.md_wr_props
        skel = _skeleton(context)
        if skel is None:
            self.report({"ERROR"}, "请先选择目标骨骼")
            return {"CANCELLED"}
        name = props.new_instrument_sk
        if not name:
            self.report({"WARNING"}, "请从下拉菜单选择一个 Shape Key")
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
    bl_label = "重命名当前角色"
    bl_options = {"REGISTER", "UNDO"}
    new_name: StringProperty(default="", name="新名字")  # type: ignore

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


class WR_OT_duplicate_performer(Operator):
    bl_idname = "music_doll.wind_rise_duplicate_performer"
    bl_label = "复制角色"
    bl_options = {"REGISTER", "UNDO"}
    new_name: StringProperty(default="", name="新名字")  # type: ignore

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

class WR_PT_main_panel(Panel):
    """WindRise 乐器子面板"""
    bl_label = "Wind Rise"
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
        box.label(text="初始化", icon="TOOL_SETTINGS")
        box.operator("music_doll.wind_rise_setup_objects",
                     text="Setup Objects")

        # 2. 对象选择
        box = layout.box()
        box.label(text="对象选择", icon="OBJECT_DATA")
        box.prop(props, "lip_mesh", text="人物Mesh")
        box.prop(props, "instrument_mesh", text="乐器Mesh")

        # 3. 人物 Shape Key
        box = layout.box()
        box.label(text="人物 Shape Key（嘴唇）", icon="SHAPEKEY_DATA")
        self._draw_sk_editor(box, context, skel, props.lip_mesh,
                             get_force_shape_keys, "new_character_sk",
                             "music_doll.wind_rise_add_character_sk",
                             "music_doll.wind_rise_remove_character_sk")

        # 4. 乐器 Shape Key
        box = layout.box()
        box.label(text="乐器 Shape Key", icon="SHAPEKEY_DATA")
        self._draw_sk_editor(box, context, skel, props.instrument_mesh,
                             get_instrument_shape_keys, "new_instrument_sk",
                             "music_doll.wind_rise_add_instrument_sk",
                             "music_doll.wind_rise_remove_instrument_sk")

        # 5. 乐器说明
        box = layout.box()
        box.label(text="乐器说明", icon="INFO")
        box.prop(props, "description", text="")

        # 6. 状态管理
        box = layout.box()
        box.label(text="状态管理", icon="FILE_TICK")
        box.prop(props, "current_note", text="当前音高")
        row = box.row(align=True)
        row.operator("music_doll.wind_rise_save_state",
                     text="保存状态", icon="EXPORT")
        row.operator("music_doll.wind_rise_load_state",
                     text="加载状态", icon="IMPORT")

        # 7. 文件（.wind）
        box = layout.box()
        box.label(text="数据文件 (.wind)", icon="FILE")
        box.prop(props, "instrument_type", text="乐器类型")
        if props.instrument_type == "custom":
            box.prop(props, "custom_instrument_type", text="自定义类型")
        row = box.row(align=True)
        row.prop(props, "min_note", text="最小")
        row.prop(props, "max_note", text="最大")
        row = box.row(align=True)
        row.operator("music_doll.wind_rise_export_wind",
                     text="导出 .wind", icon="EXPORT")
        row.operator("music_doll.wind_rise_import_wind",
                     text="导入 .wind", icon="IMPORT")
        box.operator("music_doll.wind_rise_export_to_unreal",
                     text="导出到 Unreal", icon="EXPORT")

        # 8. 动画生成
        box = layout.box()
        box.label(text="生成动画", icon="PLAY")
        box.prop(props, "wind_rise_animation_file_path", text="")
        box.operator("music_doll.wind_rise_generate_animation",
                     text="生成动画", icon="PLAY")

        # 9. 工具（折叠）
        row = layout.row(align=True)
        row.prop(props, "show_tools",
                 icon="TRIA_DOWN" if props.show_tools else "TRIA_RIGHT",
                 icon_only=True, emboss=False)
        row.label(text="工具", icon="MODIFIER_ON")
        if props.show_tools:
            ui_utils.draw_tools(layout, scene, tools=TOOLS)

    def _draw_sk_editor(self, box, context, skel, mesh_obj,
                        getter, new_prop_name, add_op, remove_op):
        if not mesh_obj or mesh_obj.type != "MESH" or not mesh_obj.data.shape_keys:
            box.label(text="请先选择含 Shape Key 的 Mesh", icon="ERROR")
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
            box.label(text="（尚未添加 Shape Key）", icon="INFO")

        row = box.row(align=True)
        row.prop_search(context.scene.md_wr_props, new_prop_name,
                        sk_data, "key_blocks", text="")
        row.operator(add_op, text="添加", icon="ADD")


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
    bpy.types.Scene.md_wr_props = PointerProperty(type=WindRiseProperties)
    ui_utils.register_instrument(
        "wind_rise",
        "WindRise 管乐",
        WR_PT_main_panel,
        rename_operator="music_doll.wind_rise_rename_performer",
        duplicate_operator="music_doll.wind_rise_duplicate_performer",
    )


def unregister():
    ui_utils.unregister_instrument("wind_rise")
    if hasattr(bpy.types.Scene, "md_wr_props"):
        del bpy.types.Scene.md_wr_props
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    tools_unregister()
