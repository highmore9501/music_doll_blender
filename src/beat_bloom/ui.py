# beat_bloom/ui.py
"""BeatBloom 乐器模块 —— 面板与算子

- 状态存骨骼自定义属性，无全局单例；
- DrumKit 枚举 items 动态读骨骼 beat_bloom_drumkit_config；
- 面板挂在 MUSICDOLL_PT_main_panel 下，只在 beat_bloom 演奏者激活时显示；
- 场景属性键前缀 md_bb_，避免与独立安装的旧版插件冲突。
"""

import json
import os

import bpy  # type: ignore
from bpy.types import Panel, Operator, PropertyGroup  # type: ignore
from bpy.props import (  # type: ignore
    StringProperty, EnumProperty, PointerProperty,
)
from bpy_extras.io_utils import ImportHelper, ExportHelper  # type: ignore

from ..common import ui_utils
from ..common import performer_utils
from ..common import instrument_base
from ..common import i18n
from ..common.tools import COMMON_TOOLS
from .config import BeatBloomConfig, DRUMKIT_KEY
from .enums import STATE_ITEMS
from .state import (
    save_state, load_state,
    save_rest_state, load_rest_state,
    save_mapping, load_mapping,
)
from .io import export_drummer, import_drummer
from .animation import (
    clear_all_keyframe,
    make_animation_by_path,
    make_shape_key_animation,
)
from .tools import INSTRUMENT_TOOLS

T = i18n.T
bl_label_set = i18n.bl_label_set

TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS


# ── 演奏者/骨骼辅助 ──────────────────────────────────────────

def _get_active_suffix(context) -> str:
    return ui_utils.get_active_suffix(context.scene)


def _get_active_skeleton(context):
    skel = ui_utils.get_target_skeleton(context)
    if skel:
        return skel
    for obj in context.selected_objects:
        if obj is not None and obj.type == "ARMATURE":
            return obj
    return None


def _get_drumkit(context) -> dict | None:
    """读取当前演奏者骨骼的 drumkit 配置；无则返回 None"""
    skel = _get_active_skeleton(context)
    if skel is None:
        return None
    raw = skel.get(DRUMKIT_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _get_bb_config(context) -> BeatBloomConfig:
    return BeatBloomConfig(
        performer_suffix=_get_active_suffix(context),
        target_skeleton=_get_active_skeleton(context),
    )


def _on_beatbloom_path_update(self, context):
    """动画文件路径变更：写回当前演奏者的 md_animation_path（MusicDoll 层级数据）。"""
    perf = ui_utils.get_active_performer(context.scene)
    if perf is not None and perf.collection is not None:
        instrument_base.set_coll_attr(
            perf.collection, "animation_path", self.beatbloom_file_path)


def _sync_beatbloom_path(context) -> None:
    """绘制前把当前演奏者的 md_animation_path 回填到 props（切演奏者/重载后保持正确）。"""
    props = context.scene.md_bb_props
    perf = ui_utils.get_active_performer(context.scene)
    if perf is None or perf.collection is None:
        return
    stored = instrument_base.get_coll_attr(
        perf.collection, "animation_path") or ""
    if props.beatbloom_file_path != stored:
        props.beatbloom_file_path = stored


# ── 动态 EnumProperty 回调 ──────────────────────────────────
# Blender 5.0 要求 items 回调必须是 2 参数 (self, context)

def _get_component_items(self, context):
    """所有 drum component（含 special_actions）的 enum items"""
    dk = _get_drumkit(context)
    if not dk:
        return [("__none__", "（未加载 Drumkit）", "")]
    items = []
    for comp in dk.get("components", []):
        n = comp["name"]
        items.append((n, n, ""))
    for sa in dk.get("special_actions", []):
        n = sa["name"]
        items.append((n, n, ""))
    items.append(("__rest__", "Rest（休息态）", ""))
    return items or [("__none__", "（无组件）", "")]


# ── 属性组 ────────────────────────────────────────────────────

class BeatBloomProperties(PropertyGroup):
    """BeatBloom 面板场景属性"""
    __annotations__ = {
        # 当前选中的 drum component（动态，来自 drumkit 配置）
        "component": EnumProperty(
            name=T("Component"),
            description=T("Drum component"),
            items=_get_component_items,
            default=0,
        ),
        # 当前选中的击打状态
        "state": EnumProperty(
            name=T("State"),
            description=T("Hit state"),
            items=STATE_ITEMS,
            default="beat",
        ),
        # Mapping A/B/C/D
        "mapping_key": EnumProperty(
            name=T("Mapping State"),
            description=T("Mapping helper slot (A/B/C/D)"),
            items=[('A', 'A', ''), ('B', 'B', ''),
                   ('C', 'C', ''), ('D', 'D', '')],
            default='A',
        ),
        # .beatbloom 配置文件路径（用于生成动画；保存到演奏者 md_animation_path）
        "beatbloom_file_path": StringProperty(
            name="BeatBloom File",
            description=".beatbloom 配置文件路径（保存到演奏者 md_animation_path）",
            default="", subtype='FILE_PATH',
            update=_on_beatbloom_path_update,
        ),
    }


# ── 算子 ──────────────────────────────────────────────────────

class BB_OT_load_drumkit(Operator, ImportHelper):
    """加载 .drumkit 文件并写入骨骼自定义属性"""
    bl_idname = "music_doll.beat_bloom_load_drumkit"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".drumkit"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.drumkit", options={'HIDDEN'})
    }

    def execute(self, context):
        if not self.filepath.endswith(".drumkit"):
            self.report({'ERROR'}, T("请选择 .drumkit 文件"))
            return {'CANCELLED'}
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                dk = json.load(f)
            skel[DRUMKIT_KEY] = json.dumps(dk, ensure_ascii=False)
            self.report({'INFO'}, T("已加载 drumkit：%s") % dk.get('name', ''))
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, T("加载失败：%s") % e)
            return {'CANCELLED'}


class BB_OT_setup_objects(Operator):
    """创建 BeatBloom 12 个控件"""
    bl_idname = "music_doll.beat_bloom_setup_objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cfg = _get_bb_config(context)
        cfg.setup_all_objects()
        self.report({'INFO'}, T("BeatBloom 控件已就绪"))
        return {'FINISHED'}


class BB_OT_save_state(Operator):
    """将当前控件位置保存到骨骼（Set）"""
    bl_idname = "music_doll.beat_bloom_save_state"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.md_bb_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}
        comp = props.component
        if comp == "__none__":
            self.report({'ERROR'}, T("请先加载 Drumkit 配置"))
            return {'CANCELLED'}
        if comp == "__rest__":
            save_rest_state(_get_active_suffix(context), skel)
            self.report({'INFO'}, T("已保存 rest 状态"))
            return {'FINISHED'}
        dk = _get_drumkit(context)
        save_state(_get_active_suffix(context), comp, props.state, skel, dk)
        self.report({'INFO'}, T("已保存 %s/%s") % (comp, props.state))
        return {'FINISHED'}


class BB_OT_load_state(Operator):
    """从骨骼加载状态到控件（Load）"""
    bl_idname = "music_doll.beat_bloom_load_state"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.md_bb_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}
        comp = props.component
        if comp == "__none__":
            self.report({'ERROR'}, T("请先加载 Drumkit 配置"))
            return {'CANCELLED'}
        suffix = _get_active_suffix(context)
        if comp == "__rest__":
            ok = load_rest_state(suffix, skel)
        else:
            ok = load_state(suffix, comp, props.state, skel)
        if ok:
            self.report({'INFO'}, T("已加载 %s") % comp)
        else:
            self.report({'WARNING'}, T("骨骼中不存在 %s 状态数据，请先 Set") % comp)
        return {'FINISHED'}


class BB_OT_save_mapping(Operator):
    """将 Middle_Hand / Head_Control / H_L / H_R 保存到骨骼 mapping_helpers"""
    bl_idname = "music_doll.beat_bloom_save_mapping"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.md_bb_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}
        save_mapping(_get_active_suffix(context), skel, props.mapping_key)
        self.report({'INFO'}, T("已保存 Mapping %s") % props.mapping_key)
        return {'FINISHED'}


class BB_OT_load_mapping(Operator):
    """从骨骼 mapping_helpers 加载到 Middle_Hand / Head_Control / H_L / H_R"""
    bl_idname = "music_doll.beat_bloom_load_mapping"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.md_bb_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}
        ok = load_mapping(_get_active_suffix(context), skel, props.mapping_key)
        if ok:
            self.report({'INFO'}, T("已加载 Mapping %s") % props.mapping_key)
        else:
            self.report(
                {'WARNING'}, T("骨骼中不存在 Mapping %s，请先 Save") % props.mapping_key)
        return {'FINISHED'}


class BB_OT_export(Operator, ExportHelper):
    """导出 .drummer 文件（从骨骼 JSON 重组扁平格式）"""
    bl_idname = "music_doll.beat_bloom_export"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".drummer"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.drummer", options={'HIDDEN'})
    }

    def execute(self, context):
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}
        dk = _get_drumkit(context)
        if not dk:
            self.report({'ERROR'}, T("请先加载 Drumkit 配置"))
            return {'CANCELLED'}
        path = self.filepath
        if not path.endswith(".drummer"):
            path += ".drummer"
        try:
            export_drummer(path, skel, dk)
            self.report({'INFO'}, T("已导出 → %s") % path)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, T("导出失败：%s") % e)
            return {'CANCELLED'}


class BB_OT_import(Operator, ImportHelper):
    """从 .drummer 文件导入到骨骼 JSON"""
    bl_idname = "music_doll.beat_bloom_import"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".drummer"
    __annotations__ = {
        "filter_glob": StringProperty(default="*.drummer", options={'HIDDEN'})
    }

    def execute(self, context):
        if not self.filepath.endswith(".drummer"):
            self.report({'ERROR'}, T("请选择 .drummer 文件"))
            return {'CANCELLED'}
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}
        dk = _get_drumkit(context)
        if not dk:
            self.report({'ERROR'}, T("请先加载 Drumkit 配置"))
            return {'CANCELLED'}
        try:
            import_drummer(self.filepath, skel, dk)
            self.report({'INFO'}, T("已导入 ← %s") % self.filepath)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, T("导入失败：%s") % e)
            return {'CANCELLED'}


class BB_OT_execute_beatbloom(Operator):
    """执行 BeatBloom 动画（读取 .beatbloom 配置后生成 transform + shape key 关键帧）"""
    bl_idname = "music_doll.beat_bloom_execute_beatbloom"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.md_bb_props
        suffix = _get_active_suffix(context)
        perf = ui_utils.get_active_performer(context.scene)
        filepath = props.beatbloom_file_path
        if perf is not None and perf.collection is not None:
            stored = instrument_base.get_coll_attr(
                perf.collection, "animation_path") or ""
            if stored:
                filepath = stored

        if not filepath or not os.path.exists(filepath):
            self.report({'ERROR'}, T("请先选择有效的 .beatbloom 文件"))
            return {'CANCELLED'}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                config = json.load(f)

            from pathlib import Path
            project_root = Path(filepath).parent.parent.parent.absolute()

            anim_path = config.get("animation_path", "")
            sk_path = config.get("shape_key_animation_path", "")

            if not os.path.isabs(anim_path):
                anim_path = os.path.join(project_root, anim_path)
            if not os.path.isabs(sk_path):
                sk_path = os.path.join(project_root, sk_path)

            if not os.path.exists(anim_path):
                self.report({'ERROR'}, T("找不到动画文件：%s") % anim_path)
                return {'CANCELLED'}
            if not os.path.exists(sk_path):
                self.report({'ERROR'}, T("找不到 shape key 动画文件：%s") % sk_path)
                return {'CANCELLED'}

            clear_all_keyframe(["drum", "addons"], suffix=suffix)
            make_animation_by_path(anim_path, suffix=suffix)
            make_shape_key_animation(sk_path)

            self.report({'INFO'}, T("动画已生成：%s") % os.path.basename(filepath))
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, T("执行动画时出错：%s") % e)
            return {'CANCELLED'}


class BB_OT_duplicate_performer(Operator):
    """复制当前 BeatBloom 角色"""
    bl_idname = "music_doll.beat_bloom_duplicate_performer"
    bl_options = {'REGISTER', 'UNDO'}
    new_name: StringProperty(default="", name=T("新名字"))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        suffix = _get_active_suffix(context)
        if not suffix:
            self.report({'ERROR'}, T("请先在下拉框选中要复制的角色"))
            return {'CANCELLED'}
        src = performer_utils.get_performer(suffix)
        if src is None:
            self.report({'ERROR'}, T("找不到已登记的角色 %s（请先初始化该角色）") % suffix)
            return {'CANCELLED'}
        new_name = (self.new_name or "").strip()
        if not new_name:
            self.report({'ERROR'}, T("请输入新名字"))
            return {'CANCELLED'}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report({'ERROR'}, T("名字只能用英文字母和数字"))
            return {'CANCELLED'}
        if performer_utils.has_performer(new_name):
            self.report({'ERROR'}, T("已存在名字 %s，请换一个") % new_name)
            return {'CANCELLED'}
        try:
            dup = performer_utils.duplicate_collection_tree(src.collection)
        except Exception as e:
            self.report({'ERROR'}, T("复制集合失败：%s") % e)
            return {'CANCELLED'}
        if dup is None:
            self.report({'ERROR'}, T("复制集合失败（未能生成副本）"))
            return {'CANCELLED'}
        from ..common import instrument_base
        instrument_base.set_coll_attr(dup, "name", src.name)
        instrument_base.set_coll_attr(dup, "instrument", src.instrument)
        performer_utils.resuffix_performer(dup, new_name, new_name=new_name)
        self.report({'INFO'}, T("已复制角色为 %s") % new_name)
        return {'FINISHED'}


class BB_OT_rename_performer(Operator):
    """重命名当前 BeatBloom 角色"""
    bl_idname = "music_doll.beat_bloom_rename_performer"
    bl_options = {'REGISTER', 'UNDO'}
    new_name: StringProperty(default="", name=T("新名字"))

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
            self.report({'ERROR'}, T("找不到当前角色"))
            return {'CANCELLED'}
        new_name = (self.new_name or "").strip()
        if not new_name:
            self.report({'ERROR'}, T("请输入新名字"))
            return {'CANCELLED'}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report({'ERROR'}, T("名字只能用英文字母和数字"))
            return {'CANCELLED'}
        if new_name == src.name:
            self.report({'ERROR'}, T("新名字与当前相同（%s），无需重命名") % new_name)
            return {'CANCELLED'}
        if performer_utils.has_performer(new_name):
            self.report({'ERROR'}, T("已存在名字 %s，请换一个") % new_name)
            return {'CANCELLED'}
        try:
            performer_utils.resuffix_performer(
                src.collection, new_name, new_name=new_name)
        except Exception as e:
            self.report({'ERROR'}, T("重命名失败：%s") % e)
            return {'CANCELLED'}
        try:
            setattr(context.scene, ui_utils.SCENE_ACTIVE_PERFORMER, new_name)
        except Exception:
            pass
        self.report({'INFO'}, T("已将角色重命名为 %s") % new_name)
        return {'FINISHED'}


# ── 面板 ──────────────────────────────────────────────────────

class BB_PT_main_panel(Panel):
    """BeatBloom 乐器子面板"""
    bl_idname = "BEATBLOOM_PT_main_panel"
    bl_parent_id = "MUSICDOLL_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MusicDoll"

    @classmethod
    def poll(cls, context):
        return ui_utils.active_instrument(context) == "beat_bloom"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.md_bb_props
        _sync_beatbloom_path(context)

        # 1. DrumKit 配置
        box = layout.box()
        box.label(text=T("DrumKit Config"), icon='ARMATURE_DATA')
        box.operator("music_doll.beat_bloom_load_drumkit",
                     text=T("Load DrumKit Config"), icon='FILE_FOLDER')

        # 2. 初始化
        box = layout.box()
        box.label(text=T("Initialization"), icon='TOOL_SETTINGS')
        box.operator("music_doll.beat_bloom_setup_objects",
                     text=T("Setup Objects"), icon='OBJECT_DATA')

        # 3. 工具
        ui_utils.draw_tools(layout, scene, tools=TOOLS)

        # 4. 状态设置/加载
        box = layout.box()
        box.label(text=T("Set / Load State"), icon='FILE_REFRESH')
        col = box.column(align=True)
        col.prop(props, "component", text=T("Component"))
        col.prop(props, "state", text=T("State"))
        row = box.row(align=True)
        row.operator("music_doll.beat_bloom_save_state", text=T("Set"))
        row.operator("music_doll.beat_bloom_load_state", text=T("Load"))

        # 5. Mapping Helpers
        box = layout.box()
        box.label(text=T("Mapping Helpers"), icon='ORIENTATION_VIEW')
        col = box.column(align=True)
        col.prop(props, "mapping_key", text=T("Slot"))
        row = box.row(align=True)
        row.operator("music_doll.beat_bloom_save_mapping",
                     text=T("Save Mapping"))
        row.operator("music_doll.beat_bloom_load_mapping",
                     text=T("Load Mapping"))

        # 6. 导出 / 导入 .drummer
        box = layout.box()
        box.label(text=T("Export / Import"), icon='EXPORT')
        row = box.row(align=True)
        row.operator("music_doll.beat_bloom_export", text=T("Export .drummer"))
        row.operator("music_doll.beat_bloom_import", text=T("Import .drummer"))
        box.operator("music_doll.beat_bloom_export_to_unreal",
                     text=T("导出到 Unreal"), icon='EXPORT')

        # 7. 动画
        box = layout.box()
        box.label(text=T("Animation"), icon='PLAY')
        box.prop(props, "beatbloom_file_path", text="")
        box.operator("music_doll.beat_bloom_execute_beatbloom",
                     text=T("Execute Animation"), icon='PLAY')


# ── 注册 / 注销 ───────────────────────────────────────────────

_CLASSES = (
    BeatBloomProperties,
    BB_OT_load_drumkit,
    BB_OT_setup_objects,
    BB_OT_save_state,
    BB_OT_load_state,
    BB_OT_save_mapping,
    BB_OT_load_mapping,
    BB_OT_export,
    BB_OT_import,
    BB_OT_execute_beatbloom,
    BB_OT_duplicate_performer,
    BB_OT_rename_performer,
    BB_PT_main_panel,
)


def register():
    from .tools import register as tools_register
    tools_register()

    bl_label_set(BB_OT_load_drumkit, "Load DrumKit Config")
    bl_label_set(BB_OT_setup_objects, "Setup Objects")
    bl_label_set(BB_OT_save_state, "Set")
    bl_label_set(BB_OT_load_state, "Load")
    bl_label_set(BB_OT_save_mapping, "Save Mapping")
    bl_label_set(BB_OT_load_mapping, "Load Mapping")
    bl_label_set(BB_OT_export, "Export Recorder Info")
    bl_label_set(BB_OT_import, "Import Recorder Info")
    bl_label_set(BB_OT_execute_beatbloom, "Execute BeatBloom Animation")
    bl_label_set(BB_OT_duplicate_performer, "复制角色")
    bl_label_set(BB_OT_rename_performer, "重命名当前角色")
    bl_label_set(BB_PT_main_panel, "BeatBloom")

    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.md_bb_props = PointerProperty(type=BeatBloomProperties)

    from .tools import INSTRUMENT_TOOLS as _it  # noqa: F401

    ui_utils.register_instrument(
        "beat_bloom", T("BeatBloom 打击乐"), BB_PT_main_panel,
        rename_operator="music_doll.beat_bloom_rename_performer",
        duplicate_operator="music_doll.beat_bloom_duplicate_performer",
    )


def unregister():
    ui_utils.unregister_instrument("beat_bloom")

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

    if hasattr(bpy.types.Scene, "md_bb_props"):
        del bpy.types.Scene.md_bb_props

    from .tools import unregister as tools_unregister
    tools_unregister()
