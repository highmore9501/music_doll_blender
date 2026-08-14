# string_flow/tools/make_violin_string.py
"""StringFlow 独有工具 —— 琴弦生成（迁移自 string_flow_blender/tools/make_violin_string.py）

改动点：
- 弦物体命名带演奏者后缀：string{number}_{suffix}；
- 三点定平面参考对象（position_s0_f0 / position_s3_f0 / middle_fret_board_position）
  按后缀解析（弦工具与 Rust 端 calculate_finger_positions 逻辑一致）；
- shape key 名 s{n}fret{k} 在弦数据内部，不需要后缀；
- offset_ratio 参数保留（原版 UI 引用但属性未定义、函数内也未实际使用——此处补场景属性
  并传入签名，算法与原版保持一致）。
"""

import re

import bpy  # type: ignore
import bmesh  # type: ignore
import mathutils  # type: ignore
from mathutils import Vector  # type: ignore

from ...common import performer_utils


_STRING_NAME_RE = re.compile(r"^string(\d+)")


def _string_index_from_name(obj_name: str):
    """从弦对象名解析弦号：'string0_Jd' -> '0'；'string3' -> '3'"""
    base = obj_name.split("_")[0]
    m = _STRING_NAME_RE.match(base)
    return m.group(1) if m else None


def create_violin_string(start_obj_name: str, end_obj_name: str, number: int = 1,
                         subdivisions: int = 80, suffix: str = ""):
    """在 Blender 中创建琴弦物体（string{number}_{suffix}）。

    根据给定的 start 和 end 位置，创建一个均匀细分的圆柱体作为原始琴弦。
    """
    # 获取 start 和 end 对象
    if start_obj_name not in bpy.data.objects or end_obj_name not in bpy.data.objects:
        raise ValueError(f"未找到对象: {start_obj_name} 或 {end_obj_name}")

    start_obj = bpy.data.objects[start_obj_name]
    end_obj = bpy.data.objects[end_obj_name]

    # 获取世界坐标（起点/终点对象未父级化，.location 即世界坐标）
    p1 = start_obj.location
    p2 = end_obj.location

    print(f"起点: {p1}")
    print(f"终点: {p2}")

    # 计算两点间距离
    direction = p2 - p1
    string_length = direction.length
    radius = string_length * 0.002

    print(f"琴弦长度: {string_length:.4f}")

    # 创建基础圆柱体（8 个圆周顶点足够）
    bpy.ops.mesh.primitive_cylinder_add(
        radius=radius,
        depth=1,  # 初始高度为 1
        vertices=8,  # 圆周顶点数
        location=p1,
    )

    cylinder = bpy.context.active_object
    cylinder.name = performer_utils.resolve(f"string{number}", suffix)

    print(f"创建圆柱体: {cylinder.name}")

    bpy.ops.object.mode_set(mode='OBJECT')

    # 创建旋转矩阵，使圆柱体的 Z 轴指向终点
    z_axis = direction.normalized()

    # 创建垂直于 Z 轴的 X 轴（优先使用世界 Z 轴来避免万向锁）
    world_z = mathutils.Vector((0, 0, 1))
    if abs(z_axis.dot(world_z)) > 0.99:
        x_axis = mathutils.Vector((1, 0, 0))
    else:
        x_axis = world_z.cross(z_axis).normalized()

    y_axis = z_axis.cross(x_axis).normalized()
    x_axis = y_axis.cross(z_axis).normalized()

    rotation_matrix = mathutils.Matrix((
        (x_axis.x, y_axis.x, z_axis.x, 0),
        (x_axis.y, y_axis.y, z_axis.y, 0),
        (x_axis.z, y_axis.z, z_axis.z, 0),
        (0, 0, 0, 1),
    ))

    cylinder.rotation_euler = rotation_matrix.to_euler()
    print("已应用旋转，使其指向终点")

    # 缩放 Z 轴以达到正确的长度
    cylinder.scale.z = string_length
    print(f"缩放Z轴到: {string_length:.4f}")

    # 移动到中点位置
    center_pos = (p1 + p2) * 0.5
    cylinder.location = center_pos
    print(f"移动到中心位置: {center_pos}")

    print(f"\n成功创建琴弦 {cylinder.name}")
    return cylinder


def calculate_fret_positions(num_fret: int, scale_length: float = 1.0) -> float:
    """计算每个品格的位置（从弦枕到琴桥的比例）。使用 12 平均律。"""
    return scale_length * (1.0 - (1.0 / (2 ** (num_fret / 12.0))))


def make_violin_string_shape_keys(offset_ratio: float = 0.005, number: int = 1,
                                  subdivisions: int = 80, reverse_frets: bool = False,
                                  suffix: str = ""):
    """创建琴弦物体并自动生成所有 shape keys。

    检查选中的物体是否为两个（start 和 end），然后创建琴弦、细分并生成 shape keys。

    :param offset_ratio: 移动偏移比例（保留参数；原版函数体内未实际使用，算法保持一致）
    :param number: 琴弦编号
    :param subdivisions: 沿圆柱体长度方向的细分数
    :param reverse_frets: 是否反序遍历品格
    :param suffix: 演奏者后缀
    """
    selected_objects = bpy.context.selected_objects
    if len(selected_objects) != 2:
        raise ValueError(
            f"请选择两个对象（start和end），当前选中了 {len(selected_objects)} 个")

    start_obj = selected_objects[0]
    end_obj = selected_objects[1]
    print(f"选中对象: {start_obj.name} (start), {end_obj.name} (end)")

    # 创建琴弦
    print("\n=== 创建琴弦 ===")
    current_object = create_violin_string(
        start_obj_name=start_obj.name,
        end_obj_name=end_obj.name,
        number=number,
        subdivisions=subdivisions,
        suffix=suffix,
    )

    print(f"\n琴弦创建完成，进行自动细分...")
    print(f"=== 自动环切细分 ===")
    bpy.context.view_layer.objects.active = current_object
    current_object.select_set(True)

    bpy.ops.object.mode_set(mode='EDIT')

    # 进行循环切割（环切）
    bpy.ops.mesh.loopcut_slide(
        MESH_OT_loopcut={
            "number_cuts": subdivisions,
            "smoothness": 0,
            "falloff": 'INVERSE_SQUARE',
            "object_index": 0,
            "edge_index": 9,  # 圆柱体有 8 个顶点，第 9 条边是第一条环边
            "mesh_select_mode_init": (True, False, False),
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
        },
    )

    bpy.ops.object.mode_set(mode='OBJECT')
    print("细分完成！现在进行shape key生成...")

    # 自动生成所有 shape keys
    print("\n=== 自动生成Shape Keys ===")
    bpy.context.view_layer.objects.active = current_object
    current_object.select_set(True)

    generate_shape_keys_for_string(reverse_frets=reverse_frets, suffix=suffix)

    print("\n" + "=" * 60)
    print(f"琴弦 {current_object.name} 创建完成！所有shape keys已自动生成。")
    print("=" * 60 + "\n")

    return current_object


def generate_shape_keys_for_string(reverse_frets: bool = False,
                                   suffix: str = ""):
    """为选中的琴弦对象生成 shape key（前提：琴弦已被细分好）。

    按三点定平面（position_s0_f0 / position_s3_f0 / middle_fret_board_position，
    均按后缀解析）计算指板平面，为品格 1~20 生成按下变形的 shape key。
    """
    selected_objects = bpy.context.selected_objects
    if len(selected_objects) != 1:
        raise ValueError(
            f"请选择一个琴弦对象，当前选中了 {len(selected_objects)} 个")

    current_object = selected_objects[0]
    print(f"\n=== 为琴弦 {current_object.name} 生成shape key ===")

    bpy.context.view_layer.objects.active = current_object
    current_object.select_set(True)

    vertices = [v.co for v in current_object.data.vertices]
    x_coords = [v.x for v in vertices]
    y_coords = [v.y for v in vertices]
    z_coords = [v.z for v in vertices]

    x_range = max(x_coords) - min(x_coords)
    y_range = max(y_coords) - min(y_coords)
    z_range = max(z_coords) - min(z_coords)

    ranges = {'x': x_range, 'y': y_range, 'z': z_range}
    main_axis = max(ranges.items(), key=lambda item: item[1])[0]

    coord_values = {'x': x_coords, 'y': y_coords, 'z': z_coords}[main_axis]
    min_idx = coord_values.index(min(coord_values))
    max_idx = coord_values.index(max(coord_values))

    start_vertex = vertices[min_idx]
    end_vertex = vertices[max_idx]

    print(f"主延伸轴: {main_axis}")
    print(f"起点索引: {min_idx}, 终点索引: {max_idx}")

    # 三点定平面（带后缀解析；与 Rust calculate_finger_positions 一致）
    required_objects = ['position_s0_f0', 'position_s3_f0',
                        'middle_fret_board_position']
    resolved_refs = {}
    for obj_name in required_objects:
        full = performer_utils.resolve(obj_name, suffix)
        if full not in bpy.data.objects:
            raise ValueError(f"场景中缺少必要的参考对象: {full}")
        resolved_refs[obj_name] = bpy.data.objects[full]

    p1 = resolved_refs['position_s0_f0'].matrix_world.translation
    p2 = resolved_refs['position_s3_f0'].matrix_world.translation
    p3 = resolved_refs['middle_fret_board_position'].matrix_world.translation

    v1 = p2 - p1
    v2 = p3 - p1
    plane_normal = v1.cross(v2).normalized()

    # 检查是否有 basis shape key，没有就生成一个
    if not current_object.data.shape_keys:
        current_object.shape_key_add(name='Basis')

    # 删除非 Basis 的 shape key
    for shape_key in current_object.data.shape_keys.key_blocks[:]:
        if shape_key.name != 'Basis':
            current_object.shape_key_remove(shape_key)

    # 在循环前创建一个临时副本（保存 Basis 状态，用作后续复制的源）
    temp_obj = current_object.copy()
    temp_obj.data = current_object.data.copy()
    bpy.context.collection.objects.link(temp_obj)
    print(f"创建基础临时对象: {temp_obj.name}")

    # 为每个品格创建 shape key
    for fret in range(1, 21):
        print(f"\n处理品格 {fret}")

        if bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        fret_position_ratio = (1 - calculate_fret_positions(fret, 1.0))
        if reverse_frets:
            fret_position_ratio = 1 - fret_position_ratio

        raw_position_world = (current_object.matrix_world @ start_vertex) + \
            (current_object.matrix_world @ end_vertex -
             current_object.matrix_world @ start_vertex) * fret_position_ratio

        to_point = raw_position_world - p1
        distance = to_point.dot(plane_normal)
        projected_position_world = raw_position_world - distance * plane_normal

        projected_position_local = current_object.matrix_world.inverted() @ projected_position_world

        original_position_local = start_vertex + \
            (end_vertex - start_vertex) * fret_position_ratio
        max_displacement = projected_position_local - original_position_local

        print(f"原始理论位置(局部): {original_position_local}")
        print(f"投影后位置(局部): {projected_position_local}")
        print(f"最大位移向量: {max_displacement}")

        # 从 temp_obj 复制生成用于变形的 morph_obj
        morph_obj = temp_obj.copy()
        morph_obj.data = temp_obj.data.copy()
        bpy.context.collection.objects.link(morph_obj)

        print(f"创建变形对象: {morph_obj.name}, "
              f"fret_position_ratio={fret_position_ratio:.4f}")

        # 选择 morph 对象进行编辑
        bpy.context.view_layer.objects.active = morph_obj
        morph_obj.select_set(True)
        current_object.select_set(False)

        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(morph_obj.data)
        bm.verts.ensure_lookup_table()

        # 应用该 fret 的变形
        for v in bm.verts:
            # 计算顶点在弦上的位置比例 (0=弦头, 1=弦尾)
            t = (v.co - start_vertex).length / \
                (end_vertex - start_vertex).length

            if t <= fret_position_ratio:  # 弦头到按弦点段
                if fret_position_ratio > 0:
                    segment_t = t / fret_position_ratio
                else:
                    segment_t = 0
                displacement = max_displacement * segment_t
            else:  # 按弦点到弦尾段
                if (1 - fret_position_ratio) > 0:
                    segment_t = (t - fret_position_ratio) / \
                        (1 - fret_position_ratio)
                else:
                    segment_t = 0
                displacement = max_displacement * (1 - segment_t)

            v.co += displacement

        bmesh.update_edit_mesh(morph_obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')

        # 现在在原对象上创建 shape key
        bpy.context.view_layer.objects.active = current_object
        current_object.select_set(True)
        morph_obj.select_set(False)

        new_shape_key = current_object.shape_key_add(
            name=f'fret{fret}', from_mix=False)

        # 将变形后的 morph_obj 顶点坐标复制到 shape key
        for i, vert in enumerate(new_shape_key.data):
            vert.co = morph_obj.data.vertices[i].co

        new_shape_key.value = 0

        # 删除本次循环的变形对象
        bpy.data.objects.remove(morph_obj, do_unlink=True)
        print(f"品格 {fret} 完成，删除变形对象")

    # 删除基础临时对象
    bpy.data.objects.remove(temp_obj, do_unlink=True)
    print("\n删除基础临时对象，所有shape key生成完毕")

    # 重命名 shape key（加弦号前缀：fret{n} → s{弦号}fret{n}）
    rename_shape_key(current_object)


def rename_shape_key(obj) -> None:
    """把琴弦对象的 shape key 重命名为 s{弦号}fret{品格}。

    弦号从对象名解析（string{number}_{suffix}），不再假设名字以数字结尾。
    """
    string_index = _string_index_from_name(obj.name)
    if string_index is None:
        print(f"  • 无法从对象名解析弦号: {obj.name}，跳过重命名")
        return
    for shape_key in obj.data.shape_keys.key_blocks:
        if not shape_key.name.startswith("s"):
            shape_key.name = f"s{string_index}" + shape_key.name
