# wind_rise/tools/axis_rotation_tool.py
"""WindRise 专属工具 —— 轴旋转 + 轴移动（迁移自 wind_rise_blender/tools/axis_rotation_tool.py）

在 Edit Mode 下以两个物体的位置定义旋转轴/移动轴，对选中顶点进行实时旋转或平移。
"""

import math
from typing import Dict, List, Tuple

import bmesh  # type: ignore
import bpy  # type: ignore
from bpy.props import FloatProperty, PointerProperty  # type: ignore
from bpy.types import Operator, PropertyGroup  # type: ignore
from mathutils import Matrix, Vector  # type: ignore

from ...common import i18n
T = i18n.T
bl_label_set = i18n.bl_label_set


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
    selected_indices = [v.index for v in bm.verts if v.select]
    current_sel = frozenset(selected_indices)
    if key in cache:
        cached_sel, cached_pos = cache[key]
        if cached_sel == current_sel and len(cached_pos) == len(selected_indices):
            return cached_pos, selected_indices
    world_mat = mesh_obj.matrix_world
    orig = [world_mat @ v.co.copy() for v in bm.verts if v.select]
    cache[key] = (current_sel, orig)
    return orig, selected_indices


# ── 属性组 ────────────────────────────────────────────────────

def _angle_update(self, context):
    props = context.scene.windrise_axis_rot_props
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
    for i, idx in enumerate(selected_indices):
        rotated_world = rot_mat @ (orig_positions[i] - pivot) + pivot
        verts[idx].co = world_mat_inv @ rotated_world
    bmesh.update_edit_mesh(mesh)


def _move_update(self, context):
    props = context.scene.windrise_axis_move_props
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
    for i, idx in enumerate(selected_indices):
        verts[idx].co = world_mat_inv @ (orig_positions[i] + offset)
    bmesh.update_edit_mesh(mesh)


class WindRiseAxisRotProperties(PropertyGroup):
    object1: PointerProperty(name=T("物体1"), type=bpy.types.Object)
    object2: PointerProperty(name=T("物体2（旋转轴终点）"), type=bpy.types.Object)
    angle: FloatProperty(
        name=T("角度"), default=0.0, min=-180.0, max=180.0,
        step=1, precision=2, update=_angle_update)


class WindRiseAxisMoveProperties(PropertyGroup):
    object1: PointerProperty(name=T("物体1"), type=bpy.types.Object)
    object2: PointerProperty(name=T("物体2（移动方向终点）"), type=bpy.types.Object)
    distance: FloatProperty(
        name=T("距离"), default=0.0, min=-10.0, max=10.0,
        step=1, precision=3, update=_move_update)


# ── 算子 ─────────────────────────────────────────────────────

class WR_OT_reset_axis_rotation(Operator):
    bl_idname = "music_doll.tool_wind_rise_reset_axis_rot"

    def execute(self, context):
        props = context.scene.windrise_axis_rot_props
        if abs(props.angle) > 0.001:
            props.angle = 0.0
        mesh_obj = context.active_object
        if mesh_obj:
            _invalidate_rot_cache(mesh_obj.name)
        return {"FINISHED"}


class WR_OT_reset_axis_move(Operator):
    bl_idname = "music_doll.tool_wind_rise_reset_axis_move"

    def execute(self, context):
        props = context.scene.windrise_axis_move_props
        if abs(props.distance) > 0.0001:
            props.distance = 0.0
        mesh_obj = context.active_object
        if mesh_obj:
            _invalidate_move_cache(mesh_obj.name)
        return {"FINISHED"}


# ── 参数区绘制函数（供 ToolDef.draw 调用）────────────────────

def draw_axis_rotation_panel(layout) -> None:
    props = bpy.context.scene.windrise_axis_rot_props
    col = layout.column(align=True)
    col.prop(props, "object1", text=T("物体1"))
    col.prop(props, "object2", text=T("物体2"))
    layout.separator()
    layout.prop(props, "angle", slider=True)
    layout.operator("music_doll.tool_wind_rise_reset_axis_rot", text=T("重置旋转"))


def draw_axis_move_panel(layout) -> None:
    props = bpy.context.scene.windrise_axis_move_props
    col = layout.column(align=True)
    col.prop(props, "object1", text=T("物体1"))
    col.prop(props, "object2", text=T("物体2"))
    layout.separator()
    layout.prop(props, "distance", slider=True)
    layout.operator(
        "music_doll.tool_wind_rise_reset_axis_move", text=T("重置移动"))


# ── 注册 ─────────────────────────────────────────────────────

_CLASSES = (
    WindRiseAxisRotProperties,
    WindRiseAxisMoveProperties,
    WR_OT_reset_axis_rotation,
    WR_OT_reset_axis_move,
)


def register():
    bl_label_set(WR_OT_reset_axis_rotation, "重置旋转")
    bl_label_set(WR_OT_reset_axis_move, "重置移动")
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if not hasattr(bpy.types.Scene, "windrise_axis_rot_props"):
        bpy.types.Scene.windrise_axis_rot_props = PointerProperty(
            type=WindRiseAxisRotProperties)
    if not hasattr(bpy.types.Scene, "windrise_axis_move_props"):
        bpy.types.Scene.windrise_axis_move_props = PointerProperty(
            type=WindRiseAxisMoveProperties)


def unregister():
    if hasattr(bpy.types.Scene, "windrise_axis_rot_props"):
        del bpy.types.Scene.windrise_axis_rot_props
    if hasattr(bpy.types.Scene, "windrise_axis_move_props"):
        del bpy.types.Scene.windrise_axis_move_props
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
