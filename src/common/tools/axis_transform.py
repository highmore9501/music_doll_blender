# common/tools/axis_transform.py
"""公共工具 —— 轴旋转 + 轴移动（迁移自 wind_rise/tools/axis_rotation_tool.py）

在 Edit Mode 下以两个物体的位置定义旋转轴/移动轴，对选中顶点进行实时旋转或平移。
所有乐器共用（出现在各乐器工具下拉菜单中）。
场景属性使用 md_axis_ 前缀，避免与其他插件冲突。
"""

import math
from typing import Dict, List, Tuple

import bmesh  # type: ignore
import bpy  # type: ignore
from bpy.props import FloatProperty, PointerProperty  # type: ignore
from bpy.types import Operator, PropertyGroup  # type: ignore
from mathutils import Matrix, Vector  # type: ignore

from .. import i18n

T = i18n.T
bl_label_set = i18n.bl_label_set


# ── 场景属性名（md_axis_ 前缀，避免与其他插件冲突）────────────

SCENE_ROT_PROPS = "md_axis_rot_props"
SCENE_MOVE_PROPS = "md_axis_move_props"


# ── 顶点位置缓存（世界空间）──────────────────────────────────

_orig_pos_cache: Dict[str, Tuple[frozenset, List[Vector]]] = {}
_move_orig_pos_cache: Dict[str, Tuple[frozenset, List[Vector]]] = {}


def _invalidate_rot_cache(mesh_name: str) -> None:
    _orig_pos_cache.pop(mesh_name, None)


def _invalidate_move_cache(mesh_name: str) -> None:
    _move_orig_pos_cache.pop(mesh_name, None)


def _get_cache(cache, mesh_obj):
    mesh = mesh_obj.data
    key = mesh_obj.name
    bm = bmesh.from_edit_mesh(mesh)
    selected_indices = [vert.index for vert in bm.verts if vert.select]
    current_sel = frozenset(selected_indices)
    if key in cache:
        cached_sel, cached_positions = cache[key]
        if cached_sel == current_sel and len(cached_positions) == len(selected_indices):
            return cached_positions, selected_indices
    world_mat = mesh_obj.matrix_world
    orig_positions = [world_mat @ vert.co.copy()
                      for vert in bm.verts if vert.select]
    cache[key] = (current_sel, orig_positions)
    return orig_positions, selected_indices


# ── 属性组 ────────────────────────────────────────────────────

def _angle_update(self, context):
    props = getattr(context.scene, SCENE_ROT_PROPS, None)
    if props is None:
        return
    obj1, obj2 = props.object1, props.object2
    if not obj1 or not obj2:
        return
    mesh_obj = context.active_object
    if not mesh_obj or mesh_obj.type != "MESH" or context.mode != "EDIT_MESH":
        return

    angle_rad = math.radians(props.angle)
    axis = (obj2.location - obj1.location).normalized()
    if axis.length_squared < 1e-12:
        return
    pivot = obj1.location
    rot_mat = Matrix.Rotation(angle_rad, 4, axis)

    mesh = mesh_obj.data
    world_mat = mesh_obj.matrix_world
    world_mat_inv = world_mat.inverted()
    orig_positions, selected_indices = _get_cache(_orig_pos_cache, mesh_obj)
    bm = bmesh.from_edit_mesh(mesh)
    verts = bm.verts
    for sel_index, vert_index in enumerate(selected_indices):
        rotated_world = rot_mat @ (orig_positions[sel_index] - pivot) + pivot
        verts[vert_index].co = world_mat_inv @ rotated_world
    bmesh.update_edit_mesh(mesh)


def _move_update(self, context):
    props = getattr(context.scene, SCENE_MOVE_PROPS, None)
    if props is None:
        return
    obj1, obj2 = props.object1, props.object2
    if not obj1 or not obj2:
        return
    mesh_obj = context.active_object
    if not mesh_obj or mesh_obj.type != "MESH" or context.mode != "EDIT_MESH":
        return

    axis = (obj2.location - obj1.location).normalized()
    if axis.length_squared < 1e-12:
        return
    offset = axis * props.distance

    mesh = mesh_obj.data
    world_mat = mesh_obj.matrix_world
    world_mat_inv = world_mat.inverted()
    orig_positions, selected_indices = _get_cache(
        _move_orig_pos_cache, mesh_obj)
    bm = bmesh.from_edit_mesh(mesh)
    verts = bm.verts
    for sel_index, vert_index in enumerate(selected_indices):
        verts[vert_index].co = world_mat_inv @ (
            orig_positions[sel_index] + offset)
    bmesh.update_edit_mesh(mesh)


class AxisRotProperties(PropertyGroup):
    object1: PointerProperty(name=T("物体1"), type=bpy.types.Object)
    object2: PointerProperty(name=T("物体2（旋转轴终点）"), type=bpy.types.Object)
    angle: FloatProperty(
        name=T("角度"), default=0.0, min=-180.0, max=180.0,
        step=1, precision=2, update=_angle_update)


class AxisMoveProperties(PropertyGroup):
    object1: PointerProperty(name=T("物体1"), type=bpy.types.Object)
    object2: PointerProperty(name=T("物体2（移动方向终点）"), type=bpy.types.Object)
    distance: FloatProperty(
        name=T("距离"), default=0.0, min=-10.0, max=10.0,
        step=1, precision=3, update=_move_update)


# ── 算子 ─────────────────────────────────────────────────────

class MUSICDOLL_OT_tool_axis_rotation_reset(Operator):
    """重置轴旋转角度并丢弃本物体的原始顶点缓存"""
    bl_idname = "music_doll.tool_axis_rotation_reset"

    def execute(self, context):
        props = getattr(context.scene, SCENE_ROT_PROPS, None)
        if props is None:
            return {"CANCELLED"}
        if abs(props.angle) > 0.001:
            props.angle = 0.0
        mesh_obj = context.active_object
        if mesh_obj:
            _invalidate_rot_cache(mesh_obj.name)
        return {"FINISHED"}


class MUSICDOLL_OT_tool_axis_move_reset(Operator):
    """重置轴移动距离并丢弃本物体的原始顶点缓存"""
    bl_idname = "music_doll.tool_axis_move_reset"

    def execute(self, context):
        props = getattr(context.scene, SCENE_MOVE_PROPS, None)
        if props is None:
            return {"CANCELLED"}
        if abs(props.distance) > 0.0001:
            props.distance = 0.0
        mesh_obj = context.active_object
        if mesh_obj:
            _invalidate_move_cache(mesh_obj.name)
        return {"FINISHED"}


# ── 参数区绘制函数（供 ToolDef.draw 调用）────────────────────

def draw_axis_rotation_panel(layout, scene) -> None:
    props = getattr(scene, SCENE_ROT_PROPS, None)
    if props is None:
        layout.label(text=T("未初始化轴旋转参数"), icon="ERROR")
        return
    col = layout.column(align=True)
    col.prop(props, "object1", text=T("物体1"))
    col.prop(props, "object2", text=T("物体2"))
    layout.separator()
    layout.prop(props, "angle", slider=True)
    layout.operator("music_doll.tool_axis_rotation_reset", text=T("重置旋转"))


def draw_axis_move_panel(layout, scene) -> None:
    props = getattr(scene, SCENE_MOVE_PROPS, None)
    if props is None:
        layout.label(text=T("未初始化轴移动参数"), icon="ERROR")
        return
    col = layout.column(align=True)
    col.prop(props, "object1", text=T("物体1"))
    col.prop(props, "object2", text=T("物体2"))
    layout.separator()
    layout.prop(props, "distance", slider=True)
    layout.operator("music_doll.tool_axis_move_reset", text=T("重置移动"))


def draw(layout, scene) -> None:
    """ToolDef 参数区绘制：轴旋转面板"""
    draw_axis_rotation_panel(layout, scene)


def draw_move(layout, scene) -> None:
    """ToolDef 参数区绘制：轴移动面板"""
    draw_axis_move_panel(layout, scene)


# ── 注册 / 注销 ───────────────────────────────────────────────

_CLASSES = (
    AxisRotProperties,
    AxisMoveProperties,
    MUSICDOLL_OT_tool_axis_rotation_reset,
    MUSICDOLL_OT_tool_axis_move_reset,
)


def register():
    """注册本工具的类与场景属性（幂等：脚本重载时不会重复注册）。"""
    # 动态设置 bl_label（国际化）—— 必须在 register_class 之前，
    # 否则 Blender 已把旧 bl_label 拷进类型，UI 上切不到英文。
    bl_label_set(MUSICDOLL_OT_tool_axis_rotation_reset, "重置旋转")
    bl_label_set(MUSICDOLL_OT_tool_axis_move_reset, "重置移动")

    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if not hasattr(bpy.types.Scene, SCENE_ROT_PROPS):
        setattr(bpy.types.Scene, SCENE_ROT_PROPS,
                PointerProperty(type=AxisRotProperties))
    if not hasattr(bpy.types.Scene, SCENE_MOVE_PROPS):
        setattr(bpy.types.Scene, SCENE_MOVE_PROPS,
                PointerProperty(type=AxisMoveProperties))


def unregister():
    """注销场景属性与类（幂等，逆序）。"""
    for name in (SCENE_ROT_PROPS, SCENE_MOVE_PROPS):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
