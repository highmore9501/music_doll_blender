# common/ui_utils.py
"""通用 UI 组件 —— 公共模块（对应 Unreal MusicDollUI 的演奏者选择器）

提供所有乐器共用的：
- 统一主面板（MUSICDOLL_PT_main_panel）：三大块 = 角色选择器/生成器 →
  角色基础属性/操作器 → 乐器子面板（按 md_instrument 只显示对应一个）；
- 角色选择器（下拉，扫描 Performers 根，默认空）与角色生成器（新建角色，折叠）；
- 角色基础属性（身份只读 + 骨骼/乐器/路径可编辑）与角色操作器（重命名/复制，折叠）；
- 乐器 UI 注册表（INSTRUMENT_UI）：各乐器模块登记 label / 面板 / 重命名复制算子；
- 演奏者切换联动（按 md_instrument 填充目标骨骼/乐器、回填设置）；
- 工具界面（工具下拉菜单：公共工具 + 乐器独有工具，折叠、按选中展开）；
- 场景级公共属性（当前演奏者 / 目标骨骼 / 目标乐器 / 路径 / 工具 / 折叠位）。
"""

import bpy  # type: ignore
from bpy.types import Panel, Operator  # type: ignore
from bpy.props import EnumProperty, StringProperty  # type: ignore

from . import performer_utils
from . import instrument_base
from .tools import ToolDef, find_tool
from . import i18n

T = i18n.T
bl_label_set = i18n.bl_label_set


# ── 场景公共属性（由 register_scene_props 注册）────────────────

# 场景属性名前缀（各乐器模块可用，避免与乐器特有属性冲突）
SCENE_ACTIVE_PERFORMER = "md_active_performer"
SCENE_TARGET_SKELETON = "md_target_skeleton"
SCENE_TARGET_INSTRUMENT = "md_target_instrument"
SCENE_INFO_PATH = "md_info_path"
SCENE_SHOW_TOOLS = "md_show_tools"
SCENE_ACTIVE_TOOL = "md_active_tool"
SCENE_SHOW_PERFORMER_GENERATOR = "md_show_performer_generator"
SCENE_SHOW_PERFORMER_OPS = "md_show_performer_ops"


def _first_valid_suffix(scene) -> str:
    """Performers 下第一个可用（ASCII）后缀，用于把坏枚举值重置回正常。"""
    for p in performer_utils.list_performers(scene):
        suf = p.suffix
        if isinstance(suf, str) and suf.isascii():
            return suf
    return ""


def get_active_suffix(scene) -> str:
    """当前角色名字（后缀已与名字合并，值就是 md_active_performer）。

    Blender 5.0 中文编码 bug：场景枚举 md_active_performer 可能残留坏字节，
    读取时抛 UnicodeDecodeError。这里捕获并尝试把枚举自愈成第一个有效名字。
    """
    try:
        active = getattr(scene, SCENE_ACTIVE_PERFORMER, "")
    except UnicodeDecodeError:
        active = _first_valid_suffix(scene)
        try:
            setattr(scene, SCENE_ACTIVE_PERFORMER, active)
        except Exception:
            pass
    return active


def get_active_performer(scene) -> performer_utils.PerformerInfo | None:
    """当前选中的演奏者（按后缀查询）。"""
    suffix = get_active_suffix(scene)
    if not suffix:
        return None
    return performer_utils.get_performer(suffix)


def active_instrument(context) -> str:
    """当前角色的乐器类型（如 "fret_dance" / "key_ripple"）；无角色返回 ""。"""
    p = get_active_performer(context.scene)
    return p.instrument if p is not None else ""


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

def get_performer_items(self, context):
    """角色下拉框项：扫描 Performers 根下的已登记角色，只显示「名字 + 乐器」。

    注意：
    - Blender 5.0 要求 EnumProperty 的 items 回调签名固定为 (self, context)；
    - 跳过非 ASCII / bytes 名字，避免把坏字节塞进枚举（中文编码 bug）。
    """
    items = [("", T("无"), "")]
    for p in performer_utils.list_performers(context):
        name = p.name
        if not name or not isinstance(name, str) or not name.isascii():
            continue
        label = name if not p.instrument else f"{name} [{p.instrument}]"
        items.append((name, label, p.instrument))
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


def on_target_skeleton_update(self, context):
    """选择目标骨骼：若骨骼属于某个已登记演奏者则自动选中它。"""
    scene = context.scene
    skel = getattr(scene, SCENE_TARGET_SKELETON, None)
    if skel is None:
        return
    suf = performer_utils.suffix_from_object(skel)
    if suf and getattr(scene, SCENE_ACTIVE_PERFORMER, "") != suf:
        setattr(scene, SCENE_ACTIVE_PERFORMER, suf)


def on_info_path_update(self, context):
    """编辑人物信息路径：写回当前演奏者的身份属性（导入/导出的唯一路径来源）。"""
    scene = context.scene
    path = getattr(scene, SCENE_INFO_PATH, "")
    p = get_active_performer(scene)
    if p is not None and p.collection is not None:
        instrument_base.set_coll_attr(p.collection, "info_path", path)


def performer_of(obj):
    """任意对象 → 所属演奏者（按后缀反查；读 ID 属性，不受枚举编码问题影响）"""
    if obj is None:
        return None
    suf = performer_utils.suffix_from_object(obj)
    if not suf:
        return None
    return performer_utils.get_performer(suf)


def get_rename_target(context):
    """定位要重命名/复制的角色：骨骼指针 → 乐器指针 → 下拉/后缀 → 选中对象。

    注意：下拉框枚举可能因 Blender 5.0 中文编码问题抛 UnicodeDecodeError，
    骨骼/乐器指针（PointerProperty）不受影响，故优先用指针。
    """
    scene = context.scene
    # 1) 目标骨骼指针（不碰枚举）
    skel = getattr(scene, SCENE_TARGET_SKELETON, None)
    if skel:
        p = performer_of(skel)
        if p is not None:
            return p
    # 2) 目标乐器指针（不碰枚举）
    inst = getattr(scene, SCENE_TARGET_INSTRUMENT, None)
    if inst:
        p = performer_of(inst)
        if p is not None:
            return p
    # 3) 当前下拉框/后缀（枚举可能因乱码崩溃，容忍）
    try:
        suffix = get_active_suffix(scene)
        if suffix:
            p = performer_utils.get_performer(suffix)
            if p is not None:
                return p
    except (UnicodeDecodeError, AttributeError):
        pass
    # 4) 选中对象反查
    for obj in context.selected_objects:
        p = performer_of(obj)
        if p is not None:
            return p
    return None


# ── 乐器 UI 注册表（角色生成器下拉 + 角色操作器接入）──────────

# instrument_id -> {"label", "panel", "rename_operator", "duplicate_operator"}
INSTRUMENT_UI: dict = {}


def register_instrument(instrument_id: str, label: str, panel_cls,
                        rename_operator: str = "",
                        duplicate_operator: str = "") -> None:
    """登记一个乐器模块的 UI（生成器下拉项 + 面板显示 + 重命名/复制算子）。"""
    INSTRUMENT_UI[instrument_id] = {
        "label": label,
        "panel": panel_cls,
        "rename_operator": rename_operator,
        "duplicate_operator": duplicate_operator,
    }


def unregister_instrument(instrument_id: str) -> None:
    """注销乐器 UI（幂等）。"""
    INSTRUMENT_UI.pop(instrument_id, None)


def get_instrument_items(self, context):
    """角色生成器的乐器下拉项：只列已注册乐器（2 参数回调，Blender 5.0 强制）。"""
    items = [("", T("（选择乐器）"), "")]
    for iid, info in INSTRUMENT_UI.items():
        items.append((iid, info["label"], iid))
    return items


# ── 面板绘制（三大块）────────────────────────────────────────

def _fold_header(row, scene, prop_name: str, label: str, icon: str):
    """折叠标题行：三角箭头（点击切换）+ 文本。"""
    row.prop(scene, prop_name,
             icon="TRIA_DOWN" if getattr(scene, prop_name, False)
             else "TRIA_RIGHT", icon_only=True, emboss=False)
    row.label(text=label, icon=icon)


def draw_performer_selector(layout, context):
    """块1：角色选择器（角色下拉；默认选项为空）。"""
    scene = context.scene
    box = layout.box()
    box.label(text=T("角色选择器"), icon="ARMATURE_DATA")
    box.prop(scene, SCENE_ACTIVE_PERFORMER, text=T("当前角色"))


def draw_performer_generator(layout, context):
    """块1b：角色生成器（折叠，默认收起；展开后提供「新建角色」）。"""
    scene = context.scene
    box = layout.box()
    row = box.row()
    _fold_header(row, scene, SCENE_SHOW_PERFORMER_GENERATOR,
                 T("角色生成器"), "ADD")
    if not getattr(scene, SCENE_SHOW_PERFORMER_GENERATOR, False):
        return
    box.operator("music_doll.create_performer", text=T("新建角色"))


def draw_performer_basic_info(layout, context, performer=None):
    """角色基础属性（名字+乐器身份 + 关联对象/路径）。

    归入「角色操作」面板（折叠）内显示，不再独立常显。
    """
    scene = context.scene
    if performer is None:
        performer = get_active_performer(scene)
    box = layout.box()
    box.label(text=T("角色基础属性"), icon="INFO")
    col = box.column(align=True)
    if performer is not None:
        col.label(text=f"{T('名字')}: {performer.name}")
        col.label(text=f"{T('乐器')}: {performer.instrument}")
    col = box.column(align=True)
    col.prop(scene, SCENE_TARGET_SKELETON, text=T("目标骨骼"))
    col.prop(scene, SCENE_TARGET_INSTRUMENT, text=T("目标乐器"))
    col.prop(scene, SCENE_INFO_PATH, text=T("人物信息路径"))


def draw_performer_ops(layout, context):
    """块2：角色操作面板（选择角色后出现，折叠，默认收起）。

    内含：角色基础属性（原独立常显）+ 复制/重命名（按乐器接入）。
    """
    scene = context.scene
    box = layout.box()
    row = box.row()
    _fold_header(row, scene, SCENE_SHOW_PERFORMER_OPS, T("角色操作"), "TOOL_SETTINGS")
    if not getattr(scene, SCENE_SHOW_PERFORMER_OPS, False):
        return
    # 角色基础属性（折叠后不再独立常显，统一归入本面板）
    draw_performer_basic_info(box, context)
    # 复制/重命名按乐器接入
    info = INSTRUMENT_UI.get(active_instrument(context), {})
    col = box.column(align=True)
    if info.get("duplicate_operator"):
        col.operator(info["duplicate_operator"], text=T("复制当前角色"))
    if info.get("rename_operator"):
        col.operator(info["rename_operator"], text=T("重命名当前角色"))


# ── 工具界面（工具下拉菜单）───────────────────────────────────

# 当前正在绘制的工具列表（由 draw_tools 注入，菜单 draw 时读取）。
# 工具列表按乐器不同（公共工具 + 该乐器独有工具），无法靠注册时的
# EnumProperty items 回调静态绑定，故用「注入式上下文 + Menu」实现下拉。
_CURRENT_TOOL_UI: dict = {"tools": [], "active": ""}


class MUSICDOLL_OT_set_active_tool(Operator):
    """选择工具：菜单项点击后把工具 id 写入场景，并刷新面板展开参数区"""
    bl_idname = "music_doll.set_active_tool"
    bl_label = "选择工具"
    bl_options = {'REGISTER', 'UNDO'}

    tool_id: StringProperty(default="")

    def execute(self, context):
        setattr(context.scene, SCENE_ACTIVE_TOOL, self.tool_id)
        return {'FINISHED'}


class MUSICDOLL_MT_tool_menu(bpy.types.Menu):
    """工具下拉菜单：列出当前乐器的全部工具（公共工具 + 独有工具）"""
    bl_idname = "MUSICDOLL_MT_tool_menu"
    bl_label = "工具"

    def draw(self, context):
        layout = self.layout
        tools = _CURRENT_TOOL_UI.get("tools", [])
        active = _CURRENT_TOOL_UI.get("active", "")
        if not tools:
            layout.label(text=T("（无可用工具）"), icon="INFO")
            return
        for t in tools:
            label = f"✓ {t.label}" if t.id == active else t.label
            op = layout.operator("music_doll.set_active_tool",
                                 text=label, icon=t.icon or "TOOL_SETTINGS")
            op.tool_id = t.id


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
    row.label(text=T("工具"), icon="TOOL_SETTINGS")

    if not getattr(scene, SCENE_SHOW_TOOLS, False):
        return

    # 注入当前工具列表，供菜单 draw 读取（每个乐器面板传入自己的 TOOLS）
    _CURRENT_TOOL_UI["tools"] = list(tools)
    _CURRENT_TOOL_UI["active"] = getattr(scene, SCENE_ACTIVE_TOOL, "")

    # 工具下拉菜单（列出公共工具 + 本乐器独有工具）
    active_tool = find_tool(tools, _CURRENT_TOOL_UI["active"])
    row = box.row(align=True)
    row.menu("MUSICDOLL_MT_tool_menu",
             text=active_tool.label if active_tool else "选择工具",
             icon=active_tool.icon if active_tool else "TOOL_SETTINGS")

    # 按选中工具展开操作区
    tool = active_tool
    if tool is None:
        return

    tool_box = box.box()
    tool_box.label(text=tool.label, icon=tool.icon)

    # 参数区（可选）
    if tool.draw is not None:
        tool.draw(tool_box, scene)

    # 执行按钮（无 operator 的工具由参数区自带按钮，如骨骼/控制器映射）
    if tool.operator:
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
            name=T("当前演奏者"),
            description=T("当前操作的演奏者（扫描 Performers 根）"),
            items=get_performer_items,
            update=on_active_performer_update,
            default=0,
        ))
    if not hasattr(bpy.types.Scene, SCENE_TARGET_SKELETON):
        setattr(bpy.types.Scene, SCENE_TARGET_SKELETON, PointerProperty(
            name=T("目标骨骼"),
            description=T("存储状态数据与演奏者设置的目标角色骨骼（Armature）"),
            type=bpy.types.Object,
            poll=_armature_poll,
            update=on_target_skeleton_update,
        ))
    if not hasattr(bpy.types.Scene, SCENE_TARGET_INSTRUMENT):
        setattr(bpy.types.Scene, SCENE_TARGET_INSTRUMENT, PointerProperty(
            name=T("目标乐器"),
            description=T("当前演奏者的乐器物体（动画作用域）"),
            type=bpy.types.Object,
            poll=_mesh_empty_poll,
        ))
    if not hasattr(bpy.types.Scene, SCENE_INFO_PATH):
        setattr(bpy.types.Scene, SCENE_INFO_PATH, StringProperty(
            name=T("人物信息路径"),
            description=T("人物信息保存路径（导入/导出）"),
            default="", subtype="FILE_PATH",
            update=on_info_path_update,
        ))
    if not hasattr(bpy.types.Scene, SCENE_SHOW_TOOLS):
        setattr(bpy.types.Scene, SCENE_SHOW_TOOLS, BoolProperty(
            name=T("显示工具"),
            description=T("展开/折叠工具区"),
            default=False,
        ))
    if not hasattr(bpy.types.Scene, SCENE_ACTIVE_TOOL):
        setattr(bpy.types.Scene, SCENE_ACTIVE_TOOL, StringProperty(
            name=T("当前工具"),
            description=T("当前选中的工具（空 = 未选择）"),
            default="",
        ))
    if not hasattr(bpy.types.Scene, SCENE_SHOW_PERFORMER_GENERATOR):
        setattr(bpy.types.Scene, SCENE_SHOW_PERFORMER_GENERATOR, BoolProperty(
            name=T("显示角色生成器"),
            description=T("展开/折叠角色生成器区"),
            default=False,
        ))
    if not hasattr(bpy.types.Scene, SCENE_SHOW_PERFORMER_OPS):
        setattr(bpy.types.Scene, SCENE_SHOW_PERFORMER_OPS, BoolProperty(
            name=T("显示角色操作"),
            description=T("展开/折叠角色操作区（重命名/复制）"),
            default=False,
        ))

    # 统一主面板与新建角色算子（父面板必须先于乐器子面板注册）。
    # 注意：bpy.types 上的属性名是 Blender 从 bl_idname 派生的 RNA 名
    # （"music_doll.create_performer" -> MUSIC_DOLL_OT_create_performer，MUSIC_DOLL
    # 带下划线），与 Python 类名 MUSICDOLL_OT_create_performer 不同，hasattr 判断
    # 必须用 RNA 名，否则重载时重复 register_class 会抛 "already registered"。
    if not hasattr(bpy.types, "MUSIC_DOLL_OT_create_performer"):
        bpy.utils.register_class(MUSICDOLL_OT_create_performer)
        bl_label_set(MUSICDOLL_OT_create_performer, "新建角色")
    if not hasattr(bpy.types, "MUSICDOLL_PT_main_panel"):
        bpy.utils.register_class(MUSICDOLL_PT_main_panel)
        bl_label_set(MUSICDOLL_PT_main_panel, "MusicDoll")
    # 工具下拉菜单相关类（RNA 名判断同上：set_active_tool 的 RNA 名带下划线）
    if not hasattr(bpy.types, "MUSIC_DOLL_OT_set_active_tool"):
        bpy.utils.register_class(MUSICDOLL_OT_set_active_tool)
        bl_label_set(MUSICDOLL_OT_set_active_tool, "选择工具")
    if not hasattr(bpy.types, "MUSICDOLL_MT_tool_menu"):
        bpy.utils.register_class(MUSICDOLL_MT_tool_menu)
        bl_label_set(MUSICDOLL_MT_tool_menu, "工具")


def unregister_scene_props():
    """注销公共场景属性 / 主面板 / 新建角色算子（幂等，逆序）。"""
    # 先注销类，再删属性
    if hasattr(bpy.types, "MUSICDOLL_PT_main_panel"):
        bpy.utils.unregister_class(MUSICDOLL_PT_main_panel)
    if hasattr(bpy.types, "MUSIC_DOLL_OT_create_performer"):
        bpy.utils.unregister_class(MUSICDOLL_OT_create_performer)
    # 工具下拉菜单相关类（逆序注销）
    if hasattr(bpy.types, "MUSICDOLL_MT_tool_menu"):
        bpy.utils.unregister_class(MUSICDOLL_MT_tool_menu)
    if hasattr(bpy.types, "MUSIC_DOLL_OT_set_active_tool"):
        bpy.utils.unregister_class(MUSICDOLL_OT_set_active_tool)
    for name in (SCENE_ACTIVE_PERFORMER,
                 SCENE_TARGET_SKELETON, SCENE_TARGET_INSTRUMENT,
                 SCENE_INFO_PATH, SCENE_SHOW_TOOLS, SCENE_ACTIVE_TOOL,
                 SCENE_SHOW_PERFORMER_GENERATOR, SCENE_SHOW_PERFORMER_OPS):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


# ── 统一主面板（唯一顶级面板）────────────────────────────────

class MUSICDOLL_PT_main_panel(Panel):
    """MusicDoll 统一主面板：三大块 = 角色选择/生成 → 基础属性/操作 → 乐器子面板。"""
    bl_label = "MusicDoll"
    bl_idname = "MUSICDOLL_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MusicDoll"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # 块1：角色选择器（常显，下拉默认空）
        draw_performer_selector(layout, context)

        # 块1b：角色生成器（折叠，默认收起）
        draw_performer_generator(layout, context)

        # 未选择角色：角色操作面板与乐器子面板都不显示
        if get_active_performer(scene) is None:
            return

        # 块2：角色操作面板（折叠，内含角色基础属性 + 复制/重命名）
        draw_performer_ops(layout, context)

        # 块3：乐器子面板由 Blender 按 bl_parent_id 自动绘制（各乐器 poll 过滤）


# ── 新建角色（角色生成器执行体）──────────────────────────────

class MUSICDOLL_OT_create_performer(Operator):
    """新建角色：登记演奏者身份（md_*）+ 建 Body/Instruments 骨架。

    弹窗内提供：名字 / 乐器类型 / 演奏者骨骼 / 乐器物体。
    Blender 5.0 的 Operator 不支持 PointerProperty（data-block 属性），
    因此骨骼/乐器物体复用场景级指针属性 SCENE_TARGET_SKELETON /
    SCENE_TARGET_INSTRUMENT，在弹窗里直接编辑，创建后自动登记进角色。
    """
    bl_idname = "music_doll.create_performer"
    bl_label = "新建角色"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(
        name=T("名字"), description=T("角色名字（仅英文字母和数字，如 Ayaka / Player01）"), default="")
    # Blender 5.0：items 为回调函数时 default 必须是整数索引（0 = 「（选择乐器）」占位项）
    instrument: EnumProperty(
        name=T("乐器"), description=T("角色所属乐器（只列已注册乐器）"),
        items=get_instrument_items, default=0,
    )

    def invoke(self, context, event):
        # 打开弹窗时，若场景目标骨骼/乐器物体为空，则预填场景中选中的对象
        scene = context.scene
        if getattr(scene, SCENE_TARGET_SKELETON, None) is None:
            for obj in context.selected_objects:
                if obj is not None and obj.type == "ARMATURE":
                    try:
                        setattr(scene, SCENE_TARGET_SKELETON, obj)
                    except Exception:
                        pass
                    break
        if getattr(scene, SCENE_TARGET_INSTRUMENT, None) is None:
            for obj in context.selected_objects:
                if obj is not None and obj.type in ("MESH", "EMPTY"):
                    try:
                        setattr(scene, SCENE_TARGET_INSTRUMENT, obj)
                    except Exception:
                        pass
                    break
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        scene = context.scene
        layout = self.layout
        layout.prop(self, "name")
        layout.prop(self, "instrument")
        layout.prop(scene, SCENE_TARGET_SKELETON, text=T("演奏者骨骼"))
        layout.prop(scene, SCENE_TARGET_INSTRUMENT, text=T("乐器物体"))

    def execute(self, context):
        scene = context.scene
        name = (self.name or "").strip()
        if not name:
            self.report({'ERROR'}, T("请输入名字"))
            return {'CANCELLED'}
        if not (name.isascii() and name.isalnum() and name[0].isalpha()):
            self.report(
                {'ERROR'}, T("名字只能使用英文字母和数字（如 Ayaka / Player01），不能包含中文"))
            return {'CANCELLED'}
        if performer_utils.has_performer(name):
            self.report({'ERROR'}, T("已存在名字 %s，请换一个") % name)
            return {'CANCELLED'}
        if not self.instrument:
            self.report({'ERROR'}, T("请选择乐器"))
            return {'CANCELLED'}

        target_skeleton = getattr(scene, SCENE_TARGET_SKELETON, None)
        target_instrument = getattr(scene, SCENE_TARGET_INSTRUMENT, None)

        performer_utils.get_or_create_performer(
            name, name, self.instrument,
            target_skeleton=target_skeleton,
            target_instrument=target_instrument,
        )

        # 自动选中新角色（目标骨骼/乐器物体已是场景属性，创建后即生效）
        try:
            setattr(scene, SCENE_ACTIVE_PERFORMER, name)
        except Exception:
            pass

        self.report(
            {'INFO'}, T("已新建角色 %s，乐器=%s") % (name, self.instrument))
        return {'FINISHED'}
