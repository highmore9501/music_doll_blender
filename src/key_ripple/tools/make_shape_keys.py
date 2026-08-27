# key_ripple/tools/make_shape_keys.py
"""KeyRipple 乐器独有工具 —— 为所有钢琴键创建 shape keys（迁移自 key_ripple_blender/tools/make_shape_keys.py）

提供纯函数 create_shape_keys_for_selected() 与执行算子 music_doll.tool_key_ripple_make_shape_keys。
"""
import bmesh  # type: ignore
import bpy  # type: ignore
from math import radians
import mathutils  # type: ignore

from ...common import i18n
T = i18n.T


def create_shape_keys_for_selected():
    """为选中物体的每个按键创建 Basis + pressed shape key"""
    context = bpy.context
    selected_objects = context.selected_objects

    if not selected_objects:
        raise Exception(T("没有选中任何物体"))

    view_3d = None
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            view_3d = area.spaces[0]
            break

    if not view_3d:
        raise Exception(T("请在3D视图中运行此脚本"))

    original_selection = [obj for obj in context.selected_objects]
    original_active = context.view_layer.objects.active

    bpy.context.scene.transform_orientation_slots[0].type = 'VIEW'
    bpy.context.scene.tool_settings.transform_pivot_point = 'CURSOR'

    for obj in selected_objects:
        if obj.type != 'MESH':
            print(T("跳过非网格物体: %s") % obj.name)
            continue

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        # 1. 创建Basis形状键
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.object.use_shape_key_edit_mode = True
        if not obj.data.shape_keys:
            bpy.ops.object.shape_key_add(from_mix=False)
            obj.data.shape_keys.key_blocks[0].name = "Basis"

        # 2. 复制当前状态创建Pressed形状键
        bpy.ops.object.shape_key_add(from_mix=True)
        pressed_key_name = f"{obj.name}_pressed"
        obj.data.shape_keys.key_blocks[-1].name = pressed_key_name

        # 3. 进入编辑模式并全选顶点
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')

        obj.data.shape_keys.key_blocks[-1].value = 1.0

        cursor_loc = bpy.context.scene.cursor.location

        # 创建旋转矩阵：绕世界X轴旋转-5度
        rot_angle = radians(-5)
        rot_matrix = mathutils.Matrix.Rotation(rot_angle, 4, 'X')
        bm = bmesh.from_edit_mesh(obj.data)

        bm.verts.ensure_lookup_table()
        bm.verts.layers.shape.keys()

        for vert in bm.verts:
            if vert.select:
                world_co = obj.matrix_world @ vert.co
                translated_co = world_co - cursor_loc
                rotated_co = rot_matrix @ translated_co
                new_world_co = rotated_co + cursor_loc
                vert.co = obj.matrix_world.inverted() @ new_world_co

        bmesh.update_edit_mesh(obj.data)

        # 5. 回到对象模式
        bpy.ops.object.mode_set(mode='OBJECT')

        # 6. 将Pressed形状键的权重设置回0，恢复到Basis状态
        obj.data.shape_keys.key_blocks[-1].value = 0.0

        print(T("已为 %s 创建形状键: Basis 和 %s") % (obj.name, pressed_key_name))

    # 恢复原始选中状态
    bpy.ops.object.select_all(action='DESELECT')
    for obj in original_selection:
        obj.select_set(True)
    context.view_layer.objects.active = original_active


# ── 执行算子 ──────────────────────────────────────────────────

class MUSICDOLL_OT_tool_key_ripple_make_shape_keys(bpy.types.Operator):
    """为钢琴键创建 shape keys"""
    bl_idname = "music_doll.tool_key_ripple_make_shape_keys"
    bl_label = "创建钢琴键 Shape Keys"
    bl_description = T("为所有选中钢琴键创建 Basis 与 pressed shape keys")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            create_shape_keys_for_selected()
            self.report({'INFO'}, T("钢琴键 shape keys 创建完成"))
        except Exception as e:
            self.report({'ERROR'}, T("创建失败: %s") % str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


def register():
    i18n.bl_label_set(
        MUSICDOLL_OT_tool_key_ripple_make_shape_keys, "创建钢琴键 Shape Keys")
    bpy.utils.register_class(MUSICDOLL_OT_tool_key_ripple_make_shape_keys)


def unregister():
    bpy.utils.unregister_class(MUSICDOLL_OT_tool_key_ripple_make_shape_keys)
