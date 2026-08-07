# common/ui_utils.py
"""通用 UI 组件 —— 公共模块（对应 Unreal MusicDollUI 的演奏者选择器）

提供所有乐器共用的：
- 演奏者下拉项生成（扫描 Performers 根，可带乐器类型过滤/标签）；
- 演奏者切换联动（按 md_instrument 填充目标骨骼/乐器、回填设置）；
- 工具界面（工具下拉菜单：公共工具 + 乐器独有工具，折叠、按选中展开）；
- 场景级公共属性（当前演奏者 / 目标骨骼 / 目标乐器 / 路径 / 工具）。
"""

import bpy  # type: ignore

from . import performer_utils
from . import instrument_base
from .tools import ToolDef, find_tool


# ── 场景公共属性（由 register_scene_props 注册）────────────────

# 场景属性名前缀（各乐器模块可用，避免与乐器特有属性冲突）
SCENE_ACTIVE_PERFORMER = "md_active_performer"
SCENE_TARGET_SKELETON = "md_target_skeleton"
SCENE_TARGET_INSTRUMENT = "md_target_instrument"
SCENE_INFO_PATH = "md_info_path"
SCENE_ANIMATION_PATH = "md_animation_path"
SCENE_SHOW_TOOLS = "md_show_tools"
SCENE_ACTIVE_TOOL = "md_active_tool"


def get_active_suffix(scene) -> str:
    """当前演奏者后缀：下拉框选中的演奏者优先，其次后缀输入框。"""
    active = getattr(scene, SCENE_ACTIVE_PERFORMER, None)
    if active:
        return active
    return getattr(scene, "md_performer_suffix", "")


def get_active_performer(scene) -> performer_utils.PerformerInfo | None:
    """当前选中的演奏者（按后缀查询）。"""
    suffix = get_active_suffix(scene)
    if not suffix:
        return None
    return performer_utils.get_performer(suffix)


def get_target_skeleton(context):
    """当前目标骨骼：优先场景指针，其次选中的 ARMATURE。"""
    scene = context.scene
    skel = getattr(scene, SCENE_TARGET_SKELETON, None)
    if skel:
        return skel
    for obj in context.selected_objects:
        if obj is not None and obj.type == "ARMATURE":
            return obj
    return None


def get_target_instrument(context):
    """当前目标乐器：优先场景指针，其次当前演奏者登记的乐器。"""
    scene = context.scene
    inst = getattr(scene, SCENE_TARGET_INSTRUMENT, None)
    if inst:
        return inst
    p = get_active_performer(scene)
    if p is not None and p.target_instrument is not None:
        return p.target_instrument
    return None


# ── 演奏者下拉项 ──────────────────────────────────────────────

def get_performer_items(self, context, instrument_filter=None):
    """演奏者下拉框项：扫描 Performers 根下的已登记演奏者。

    :param instrument_filter: 仅列出该乐器类型（None = 全部列出）
    """
    items = [("", "无（旧场景/手动输入后缀）", "")]
    for p in performer_utils.list_performers(context):
        if instrument_filter and p.instrument != instrument_filter:
            continue
        label = f"{p.name} ({p.suffix})"
        if p.instrument:
            label += f" [{p.instrument}]"
        items.append((p.suffix, label, p.instrument))
    return items


# ── 切换联动 ──────────────────────────────────────────────────

def on_active_performer_update(self, context):
    """切换演奏者下拉框：联动目标骨骼/乐器 + 回填设置（无状态）。"""
    scene = context.scene
    suffix = getattr(scene, SCENE_ACTIVE_PERFORMER, "")
    p = performer_utils.get_performer(suffix)
    if p is not None:
        if p.target_skeleton is not None:
            setattr(scene, SCENE_TARGET_SKELETON, p.target_skeleton)
        if p.target_instrument is not None:
            setattr(scene, SCENE_TARGET_INSTRUMENT, p.target_instrument)
        if p.info_path:
            setattr(scene, SCENE_INFO_PATH, p.info_path)
        if p.animation_path:
            setattr(scene, SCENE_ANIMATION_PATH, p.animation_path)


def on_target_skeleton_update(self, context):
    """选择目标骨骼：若骨骼属于某个已登记演奏者则自动选中它。"""
    scene = context.scene
    skel = getattr(scene, SCENE_TARGET_SKELETON, None)
    if skel is None:
        return
    suf = performer_utils.suffix_from_object(skel)
    if suf and getattr(scene, SCENE_ACTIVE_PERFORMER, "") != suf:
        setattr(scene, SCENE_ACTIVE_PERFORMER, suf)


# ── 面板绘制 ──────────────────────────────────────────────────

def draw_performer_selector(layout, scene):
    """绘制公共的「演奏者选择」区域（演奏者下拉 + 目标骨骼/乐器 + 路径）。"""
    box = layout.box()
    box.label(text="演奏者", icon="ARMATURE_DATA")
    col = box.column()
    col.prop(scene, SCENE_ACTIVE_PERFORMER, text="当前演奏者")
    if hasattr(scene, "md_performer_suffix"):
        col.prop(scene, "md_performer_suffix", text="后缀(手动)")
    col.prop(scene, SCENE_TARGET_SKELETON, text="目标骨骼")
    col.prop(scene, SCENE_TARGET_INSTRUMENT, text="目标乐器")
    col.prop(scene, SCENE_INFO_PATH, text="人物信息路径")
    col.prop(scene, SCENE_ANIMATION_PATH, text="动画文件路径")


# ── 工具界面（工具下拉菜单）───────────────────────────────────

def get_tool_items(self, context, tools=None):
    """工具下拉框项：空项 + tools 列表（公共 + 乐器独有）。

    :param tools: 该乐器的工具列表（ToolDef），由乐器模块通过 draw_tools 传入
    """
    items = [("", "（无）", "未选择工具")]
    if tools:
        for t in tools:
            items.append((t.id, t.label, t.id))
    return items


def draw_tools(layout, scene, tools=None):
    """绘制统一的「工具」界面：可折叠 + 下拉选择工具 + 按选中展开操作区。

    :param tools: 该乐器的工具列表 = COMMON_TOOLS + 乐器独有工具
    """
    if tools is None:
        tools = []

    box = layout.box()
    # 折叠标题行
    row = box.row()
    row.prop(scene, SCENE_SHOW_TOOLS,
             icon="TRIA_DOWN" if getattr(scene, SCENE_SHOW_TOOLS, False)
             else "TRIA_RIGHT", icon_only=True, emboss=False)
    row.label(text="工具", icon="TOOL_SETTINGS")

    if not getattr(scene, SCENE_SHOW_TOOLS, False):
        return

    # 工具下拉
    row = box.row()
    row.prop(scene, SCENE_ACTIVE_TOOL, text="工具")

    # 按选中工具展开操作区
    tool_id = getattr(scene, SCENE_ACTIVE_TOOL, "")
    tool = find_tool(tools, tool_id)
    if tool is None:
        return

    tool_box = box.box()
    tool_box.label(text=tool.label, icon=tool.icon)

    # 参数区（可选）
    if tool.draw is not None:
        tool.draw(tool_box, scene)

    # 执行按钮
    tool_box.operator(tool.operator, text=tool.label)


# ── 场景属性注册 ──────────────────────────────────────────────

def register_scene_props():
    """注册公共场景属性（演奏者/骨骼/乐器/路径/工具）。幂等：已存在则跳过。"""
    from bpy.props import (  # type: ignore
        EnumProperty, StringProperty, PointerProperty, BoolProperty,
    )

    def _mesh_empty_poll(self, obj):
        return obj is not None and obj.type in ("MESH", "EMPTY")

    def _armature_poll(self, obj):
        return obj is not None and obj.type == "ARMATURE"

    if not hasattr(bpy.types.Scene, SCENE_ACTIVE_PERFORMER):
        setattr(bpy.types.Scene, SCENE_ACTIVE_PERFORMER, EnumProperty(
            name="当前演奏者",
            description="当前操作的演奏者（扫描 Performers 根）",
            items=get_performer_items,
            update=on_active_performer_update,
            default=0,
        ))
    if not hasattr(bpy.types.Scene, "md_performer_suffix"):
        setattr(bpy.types.Scene, "md_performer_suffix", StringProperty(
            name="演奏者后缀",
            description="演奏者命名空间后缀（如 Jd），对象命名 <短名>_<后缀>",
            default="",
        ))
    if not hasattr(bpy.types.Scene, SCENE_TARGET_SKELETON):
        setattr(bpy.types.Scene, SCENE_TARGET_SKELETON, PointerProperty(
            name="目标骨骼",
            description="存储状态数据与演奏者设置的目标角色骨骼（Armature）",
            type=bpy.types.Object,
            poll=_armature_poll,
            update=on_target_skeleton_update,
        ))
    if not hasattr(bpy.types.Scene, SCENE_TARGET_INSTRUMENT):
        setattr(bpy.types.Scene, SCENE_TARGET_INSTRUMENT, PointerProperty(
            name="目标乐器",
            description="当前演奏者的乐器物体（动画作用域）",
            type=bpy.types.Object,
            poll=_mesh_empty_poll,
        ))
    if not hasattr(bpy.types.Scene, SCENE_INFO_PATH):
        setattr(bpy.types.Scene, SCENE_INFO_PATH, StringProperty(
            name="人物信息路径",
            description="人物信息保存路径（导入/导出）",
            default="", subtype="FILE_PATH",
        ))
    if not hasattr(bpy.types.Scene, SCENE_ANIMATION_PATH):
        setattr(bpy.types.Scene, SCENE_ANIMATION_PATH, StringProperty(
            name="动画文件路径",
            description="动画文件路径",
            default="", subtype="FILE_PATH",
        ))
    if not hasattr(bpy.types.Scene, SCENE_SHOW_TOOLS):
        setattr(bpy.types.Scene, SCENE_SHOW_TOOLS, BoolProperty(
            name="显示工具",
            description="展开/折叠工具区",
            default=False,
        ))
    if not hasattr(bpy.types.Scene, SCENE_ACTIVE_TOOL):
        setattr(bpy.types.Scene, SCENE_ACTIVE_TOOL, StringProperty(
            name="当前工具",
            description="当前选中的工具（空 = 未选择）",
            default="",
        ))


def unregister_scene_props():
    """注销公共场景属性（幂等）。"""
    for name in (SCENE_ACTIVE_PERFORMER, "md_performer_suffix",
                 SCENE_TARGET_SKELETON, SCENE_TARGET_INSTRUMENT,
                 SCENE_INFO_PATH, SCENE_ANIMATION_PATH,
                 SCENE_SHOW_TOOLS, SCENE_ACTIVE_TOOL):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
