# fret_dance/tools/strings.py
"""FretDance 乐器独有工具 —— 生成弦 shape key（迁移自 fret_dance_blender/tools/moveString.py）

弦创建、移动与 shape key 生成。提供纯函数 create_string_with_shape_keys() 与
执行算子 music_doll.tool_fret_dance_create_string。
"""
import re

import bpy  # type: ignore
import bmesh  # type: ignore
import mathutils  # type: ignore

from ...common import performer_utils
from ...common import ui_utils


def move_string(offset, direction_vector=None, ratio=1.0, suffix=""):
    """移动选中的顶点（offset: 移动距离；direction_vector: 方向；ratio: 衰减系数）"""
    print(f"=== move_string 开始 ===")
    print(
        f"参数: offset={offset}, direction_vector={direction_vector}, ratio={ratio}")

    if bpy.context.object.mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')

    bm = bmesh.from_edit_mesh(bpy.context.object.data)
    bm.verts.ensure_lookup_table()

    if direction_vector is None:
        try:
            p0_obj = bpy.data.objects[performer_utils.resolve(
                'Fret_P0', suffix)]
            p1_obj = bpy.data.objects[performer_utils.resolve(
                'Fret_P1', suffix)]

            p0_pos = p0_obj.location
            p1_pos = p1_obj.location
            direction_vector = p0_pos - p1_pos

            if direction_vector.length > 0:
                direction_vector.normalize()
            else:
                direction_vector = mathutils.Vector((0, 1, 0))

            current_obj_matrix = bpy.context.object.matrix_world.to_3x3()
            local_direction_vector = current_obj_matrix.inverted() @ direction_vector
            local_direction_vector.normalize()
            direction_vector = local_direction_vector
            print(f"使用 p1->p0 向量作为方向: {direction_vector}")
        except KeyError:
            direction_vector = mathutils.Vector((0, 1, 0))
            print("警告: p0 或 p1 对象不存在，使用默认方向")

    selected_points = [v for v in bm.verts if v.select]
    print(f"选择顶点数量: {len(selected_points)}")

    if not selected_points:
        print("没有选择顶点")
        return

    center = mathutils.Vector()
    for v in selected_points:
        center += v.co
    center /= len(selected_points)

    max_distance = 0
    for v in selected_points:
        distance = (v.co - center).length
        if distance > max_distance:
            max_distance = distance

    moved_count = 0
    for v in selected_points:
        distance = (v.co - center).length
        if max_distance > 0:
            ratio_val = (max_distance - distance) / max_distance
            ratio_val = ratio_val ** 2 * ratio
        else:
            ratio_val = ratio

        move_offset = direction_vector * offset * ratio_val
        v.co += move_offset
        moved_count += 1

    bmesh.update_edit_mesh(bpy.context.object.data)
    print(f"移动了 {moved_count} 个顶点")
    print(f"=== move_string 结束 ===")


def calculate_fret_positions(num_fret):
    """计算品格位置"""
    string_length = 1.0
    fret_position = string_length - (string_length / (2 ** (num_fret / 12.0)))
    return fret_position


def find_closest_division(fret_position, num_divisions):
    """找到最近的细分线"""
    division_size = 1.0 / num_divisions
    closest_division = round(fret_position / division_size)
    return int(closest_division)


def get_vertices_by_divisions(obj, all_vertices, num_divisions, deselected_vertices_num):
    """根据分割数获取顶点（按世界坐标 Z 轴排序，返回从 deselected 开始的顶点）"""
    vertex_positions = []
    for i, v in enumerate(all_vertices):
        world_coord = obj.matrix_world @ v.co
        vertex_positions.append((i, world_coord.z, v))

    vertex_positions.sort(key=lambda v: v[1], reverse=True)
    sorted_vertices = [v[2] for v in vertex_positions]

    start_idx = deselected_vertices_num
    result = sorted_vertices[start_idx:]
    return result


def generate_shape_keys_for_direction(
        obj, all_vertices, num_divisions, offset, direction_suffix,
        string_index, frets_info, vertices_per_loop, direction_vector):
    """为特定方向生成混合形状"""
    if not obj.data.shape_keys:
        obj.shape_key_add(name='Basis')

    for fret in range(0, 21):
        fret_info = frets_info[fret]
        closest_division = fret_info['closest_division']

        target_name = f"{obj.name}_fret{fret}{direction_suffix}"

        bpy.ops.object.mode_set(mode='OBJECT')
        new_obj = obj.copy()
        new_obj.data = obj.data.copy()
        new_obj.animation_data_clear()
        new_obj.name = target_name
        bpy.context.collection.objects.link(new_obj)

        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = new_obj
        new_obj.select_set(True)

        deselected_vertices_num = closest_division * vertices_per_loop
        vertices_to_move = get_vertices_by_divisions(
            new_obj, all_vertices, num_divisions, deselected_vertices_num)

        if vertices_to_move:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='DESELECT')

            bm = bmesh.from_edit_mesh(new_obj.data)
            bm.verts.ensure_lookup_table()

            for v in vertices_to_move:
                bm.verts[v.index].select = True
            bmesh.update_edit_mesh(new_obj.data)

            selected_verts = [v for v in bm.verts if v.select]

            center = mathutils.Vector((0, 0, 0))
            for v in selected_verts:
                center += v.co
            center /= len(selected_verts)

            max_distance = 0
            distances = []
            for v in selected_verts:
                distance = (v.co - center).length
                distances.append(distance)
                if distance > max_distance:
                    max_distance = distance

            moved_count = 0
            for i, v in enumerate(selected_verts):
                distance = distances[i]

                if max_distance > 0:
                    ratio_val = (max_distance - distance) / max_distance
                    ratio_val = ratio_val ** 2
                else:
                    ratio_val = 1.0

                move_offset = mathutils.Vector((
                    direction_vector[0] * offset * ratio_val,
                    direction_vector[1] * offset * ratio_val,
                    direction_vector[2] * offset * ratio_val
                ))
                v.co += move_offset
                moved_count += 1

            bmesh.update_edit_mesh(new_obj.data)
        else:
            print(f"没有顶点需要移动")

        bpy.ops.object.mode_set(mode='OBJECT')

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        new_obj.select_set(False)

        new_shape_key = obj.shape_key_add(name=target_name, from_mix=False)

        for i, vert in enumerate(new_shape_key.data):
            vert.co = new_obj.data.vertices[i].co

        new_target_name = f"s{string_index}fret{fret}{direction_suffix}"
        new_shape_key.name = new_target_name
        new_shape_key.value = 0.0

        bpy.data.objects.remove(new_obj, do_unlink=True)


def make_string_shape_keys(num_divisions=80, offset_ratio=0.005, suffix=""):
    """为主弦生成振动混合形状"""
    current_object = bpy.context.object

    z_coords = [v.co.z for v in current_object.data.vertices]
    z_distance = max(z_coords) - min(z_coords)
    x_coords = [v.co.x for v in current_object.data.vertices]
    x_distance = max(x_coords) - min(x_coords)
    y_coords = [v.co.y for v in current_object.data.vertices]
    y_distance = max(y_coords) - min(y_coords)
    string_length = max(z_distance, x_distance, y_distance)

    actual_offset = string_length * offset_ratio

    m = re.search(r"(\d+)", current_object.name)
    string_index = m.group(1) if m else "0"

    vertex_count = len(current_object.data.vertices)
    all_loops = num_divisions + 1
    vertices_per_loop = vertex_count // all_loops

    frets_info = []
    real_divisions = num_divisions + 1

    for num_fret in range(0, 21):
        fret_position = calculate_fret_positions(num_fret)
        closest_division = find_closest_division(fret_position, real_divisions)
        frets_info.append({
            'num_fret': num_fret,
            'closest_division': closest_division
        })

    try:
        fret_p0 = bpy.data.objects[performer_utils.resolve('Fret_P0', suffix)]
        fret_p1 = bpy.data.objects[performer_utils.resolve('Fret_P1', suffix)]

        current_obj_matrix = bpy.context.object.matrix_world.to_3x3()

        p1_location = fret_p1.location
        p0_location = fret_p0.location
        dir_y_world = p0_location - p1_location
        dir_y_world.normalize()

        local_direction = current_obj_matrix.inverted() @ dir_y_world
        local_direction.normalize()

        direction_vector_down = local_direction
        direction_vector_up = -local_direction
    except KeyError:
        direction_vector_up = mathutils.Vector((0, -1, 0))   # 向上
        direction_vector_down = mathutils.Vector((0, 1, 0))  # 向下

    all_vertices = list(current_object.data.vertices)

    generate_shape_keys_for_direction(
        current_object, all_vertices, num_divisions, abs(actual_offset), "up",
        string_index, frets_info, vertices_per_loop, direction_vector_up
    )

    generate_shape_keys_for_direction(
        current_object, all_vertices, num_divisions, abs(
            actual_offset), "down",
        string_index, frets_info, vertices_per_loop, direction_vector_down
    )

    bpy.context.view_layer.objects.active = current_object
    current_object.select_set(True)


def create_string_with_shape_keys(number, offset_ratio, suffix=""):
    """创建指定编号的弦并生成 shape keys"""
    sel = bpy.context.selected_objects
    if len(sel) != 2:
        raise Exception('请先选中两个对象（起点→终点）再运行脚本！')

    start, end = sel[0], sel[1]

    p1 = start.location
    p2 = end.location
    dist = (p2 - p1).length

    cyl_name = f"string{number}" if not suffix else f"string{number}_{suffix}"
    vertice_nubmers = 8

    bpy.ops.mesh.primitive_cylinder_add(
        radius=dist/1200,
        depth=1,
        vertices=vertice_nubmers,
        enter_editmode=False,
        align='WORLD',
        location=p1,
        scale=(1, 1, 1)
    )

    cyl = bpy.context.active_object
    cyl.name = cyl_name

    for constraint in cyl.constraints:
        cyl.constraints.remove(constraint)

    track_constraint = cyl.constraints.new(type='TRACK_TO')
    track_constraint.target = end
    track_constraint.track_axis = 'TRACK_Z'
    track_constraint.up_axis = 'UP_Y'

    bpy.ops.object.visual_transform_apply()

    for constraint in cyl.constraints:
        cyl.constraints.remove(constraint)

    cyl.scale.z = dist

    center_pos = (p1 + p2) / 2
    cyl.location = center_pos

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.loopcut_slide(
        MESH_OT_loopcut={
            "number_cuts": 80,
            "smoothness": 0,
            "falloff": 'INVERSE_SQUARE',
            "object_index": 0,
            "edge_index": vertice_nubmers+1,
            "mesh_select_mode_init": (True, False, False)
        },
        TRANSFORM_OT_edge_slide={
            "value": 0,
            "single_side": False,
            "use_even": False,
            "flipped": False,
            "use_clamp": True,
            "mirror": True,
            "snap": False,
            "snap_elements": {'INCREMENT'},
            "use_snap_project": False,
            "snap_target": 'CLOSEST',
            "use_snap_self": True,
            "use_snap_edit": True,
            "use_snap_nonedit": True,
            "use_snap_selectable": False,
            "snap_point": (0, 0, 0),
            "correct_uv": True,
            "release_confirm": False,
            "use_accurate": False,
        }
    )
    bpy.ops.object.mode_set(mode='OBJECT')

    bpy.context.view_layer.objects.active = cyl
    cyl.select_set(True)

    make_string_shape_keys(offset_ratio=offset_ratio, suffix=suffix)


# ── 执行算子 ──────────────────────────────────────────────────

class MUSICDOLL_OT_tool_fret_dance_create_string(bpy.types.Operator):
    """生成弦（含 shape key）"""
    bl_idname = "music_doll.tool_fret_dance_create_string"
    bl_label = "生成弦"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) == 2

    def execute(self, context):
        scene = context.scene
        suffix = ui_utils.get_active_suffix(scene)
        try:
            create_string_with_shape_keys(
                scene.fret_dance_string_number,
                scene.fret_dance_string_amplitude / 1000,
                suffix=suffix)
            self.report(
                {'INFO'}, f"Successfully created string {scene.fret_dance_string_number}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


def register():
    bpy.utils.register_class(MUSICDOLL_OT_tool_fret_dance_create_string)


def unregister():
    bpy.utils.unregister_class(MUSICDOLL_OT_tool_fret_dance_create_string)
