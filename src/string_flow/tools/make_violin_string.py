# string_flow/tools/make_violin_string.py
"""StringFlow 独有工具 —— 琴弦生成（迁移自 string_flow_blender/tools/make_violin_string.py）

改动点：
- 弦物体命名带演奏者后缀：string{number}_{suffix}；
- 三点定平面参考对象（position_s0_f0 / position_s3_f0 / middle_fret_board_position）
  按后缀解析（弦工具与 Rust 端 calculate_finger_positions 逻辑一致）；
- shape key 名 s{n}fret{k} 在弦数据内部，不需要后缀；
- 按弦位移按几何投影计算，未使用独立振幅参数。
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


def _set_parent_keep_world_transform(obj, target_parent) -> None:
    """把对象设置为 target_parent 子级，并保持世界坐标不变。"""
    world_matrix = obj.matrix_world.copy()
    obj.parent = target_parent
    if target_parent is not None:
        obj.matrix_parent_inverse = target_parent.matrix_world.inverted()
    else:
        obj.matrix_parent_inverse.identity()
    obj.matrix_world = world_matrix


def _infer_suffix_from_object(obj) -> str:
    """优先从对象所属演奏者关系推断后缀，失败再从对象名回退解析。"""
    if obj is None:
        return ""

    suffix = performer_utils.suffix_from_object(obj)
    if suffix:
        return suffix

    parsed = performer_utils.performer_from_object(obj.name)
    if parsed is not None:
        return parsed[0]
    return ""


def _find_reference_object(short_name: str, suffix: str, context_obj):
    """按后缀优先解析参考对象；找不到时在同短名对象里按上下文后缀回退匹配。"""
    full = performer_utils.resolve(short_name, suffix)
    if full in bpy.data.objects:
        return bpy.data.objects[full]

    base_suffix = _infer_suffix_from_object(context_obj)
    candidates = []
    for obj in bpy.data.objects:
        parsed = performer_utils.performer_from_object(obj.name)
        if parsed is None:
            continue
        cand_suffix, cand_short = parsed
        if cand_short == short_name:
            candidates.append((cand_suffix, obj))

    if base_suffix:
        for cand_suffix, cand_obj in candidates:
            if cand_suffix == base_suffix:
                return cand_obj

    if len(candidates) == 1:
        return candidates[0][1]

    raise ValueError(
        f"场景中缺少必要的参考对象: {full}；"
        f"且无法唯一匹配短名 {short_name} 的后缀对象")


def _build_loop_groups_by_distance(vertices, start_vertex, axis_dir, axis_len,
                                   subdivisions=None, verts_per_loop: int = 8):
    """按顶点到 start 的距离分桶为 loop，并按桶索引计算轴向比例。"""
    total_vertices = len(vertices)
    if total_vertices == 0:
        return []

    if subdivisions is not None:
        loop_count = int(subdivisions) + 2
    else:
        # 独立运行“生成ShapeKey”时没有 subdivisions，按常见圆柱拓扑推断侧面 loop 数。
        if total_vertices % verts_per_loop == 0:
            side_vertex_count = total_vertices
        elif total_vertices >= 2 and (total_vertices - 2) % verts_per_loop == 0:
            side_vertex_count = total_vertices - 2
        else:
            side_vertex_count = (
                total_vertices // verts_per_loop) * verts_per_loop
        if side_vertex_count < verts_per_loop * 2:
            raise ValueError("无法从当前网格推断有效的 loop 分组")
        loop_count = side_vertex_count // verts_per_loop

    groups = [
        {"indices": [], "loop_index": loop_idx, "t": 0.0}
        for loop_idx in range(loop_count)
    ]

    # 按“顶点到start距离”分桶；使用轴向投影上限做归一化，避免半径影响过大。
    for idx, v in enumerate(vertices):
        d = (v - start_vertex).length
        normalized = d / axis_len if axis_len > 1e-8 else 0.0
        normalized = max(0.0, min(1.0, normalized))
        bucket = int(round(normalized * (loop_count - 1))
                     ) if loop_count > 1 else 0
        bucket = max(0, min(loop_count - 1, bucket))
        groups[bucket]["indices"].append(idx)

    # 每个 loop 的 t 严格按索引比例计算（0=起点端, 1=终点端）。
    for group in groups:
        if loop_count > 1:
            group["t"] = group["loop_index"] / (loop_count - 1)
        else:
            group["t"] = 0.0

    return groups


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

    # 获取世界坐标（有父级时 .location 是局部坐标，这里必须使用 matrix_world）。
    p1 = start_obj.matrix_world.translation.copy()
    p2 = end_obj.matrix_world.translation.copy()

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


def make_violin_string_shape_keys(number: int = 1,
                                  subdivisions: int = 80, reverse_frets: bool = False,
                                  suffix: str = ""):
    """创建琴弦物体并自动生成所有 shape keys。

    检查选中的物体是否为两个（start 和 end），然后创建琴弦、细分并生成 shape keys。

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
    if not suffix:
        suffix = _infer_suffix_from_object(
            start_obj) or _infer_suffix_from_object(end_obj)
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

    generate_shape_keys_for_string(
        reverse_frets=reverse_frets,
        suffix=suffix,
        subdivisions=subdivisions,
    )

    print("\n" + "=" * 60)
    print(f"琴弦 {current_object.name} 创建完成！所有shape keys已自动生成。")
    print("=" * 60 + "\n")

    return current_object


def generate_shape_keys_for_string(reverse_frets: bool = False,
                                   suffix: str = "",
                                   subdivisions=None):
    """为选中的琴弦对象生成 shape key（前提：琴弦已被细分好）。

    按三点定平面（position_s0_f0 / position_s3_f0 / middle_fret_board_position，
    均按后缀解析）计算指板平面，为品格 1~20 生成按下变形的 shape key。
    """
    selected_objects = bpy.context.selected_objects
    if len(selected_objects) != 1:
        raise ValueError(
            f"请选择一个琴弦对象，当前选中了 {len(selected_objects)} 个")

    current_object = selected_objects[0]
    if not suffix:
        suffix = _infer_suffix_from_object(current_object)
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
    min_coord = min(coord_values)
    max_coord = max(coord_values)
    coord_span = max_coord - min_coord
    cap_eps = max(coord_span * 0.01, 1e-6)

    start_cap = [v for v in vertices if abs(
        getattr(v, main_axis) - min_coord) <= cap_eps]
    end_cap = [v for v in vertices if abs(
        getattr(v, main_axis) - max_coord) <= cap_eps]
    if not start_cap or not end_cap:
        raise ValueError("无法识别琴弦两端顶点，无法生成 shape key")

    # 使用两端端面中心作为弦轴端点，避免使用圆柱外圈顶点带来的半径误差。
    start_vertex = Vector((0.0, 0.0, 0.0))
    for v in start_cap:
        start_vertex += v
    start_vertex /= len(start_cap)

    end_vertex = Vector((0.0, 0.0, 0.0))
    for v in end_cap:
        end_vertex += v
    end_vertex /= len(end_cap)
    axis_vec = end_vertex - start_vertex
    axis_len = axis_vec.length
    if axis_len <= 1e-8:
        raise ValueError("琴弦长度过小，无法生成 shape key")
    axis_dir = axis_vec.normalized()

    loop_groups = _build_loop_groups_by_distance(
        vertices,
        start_vertex,
        axis_dir,
        axis_len,
        subdivisions=subdivisions,
        verts_per_loop=8,
    )
    if not loop_groups:
        raise ValueError("无法按弦轴分组顶点 loop，无法生成 shape key")
    print(f"检测到 loop 组数量: {len(loop_groups)}")

    print(f"主延伸轴: {main_axis}")
    print(f"弦轴起点(局部): {start_vertex}, 终点(局部): {end_vertex}")

    # 三点定平面（带后缀解析；与 Rust calculate_finger_positions 一致）
    required_objects = ['position_s0_f0', 'position_s3_f0',
                        'middle_fret_board_position']
    resolved_refs = {}
    for obj_name in required_objects:
        resolved_refs[obj_name] = _find_reference_object(
            obj_name, suffix, current_object)

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

        fret_position_ratio = calculate_fret_positions(fret, 1.0)
        if reverse_frets:
            fret_position_ratio = 1 - fret_position_ratio
        fret_position_ratio = max(0.0, min(1.0, fret_position_ratio))

        raw_position_local = start_vertex + axis_vec * fret_position_ratio
        raw_position_world = current_object.matrix_world @ raw_position_local

        to_point = raw_position_world - p1
        distance = to_point.dot(plane_normal)
        projected_position_world = raw_position_world - distance * plane_normal

        projected_position_local = current_object.matrix_world.inverted() @ projected_position_world
        max_displacement = projected_position_local - raw_position_local

        print(f"原始理论位置(局部): {raw_position_local}")
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

        # 应用该 fret 的变形（按 loop 中心算位移，整圈同位移，避免压扁 loop 截面）。
        for group in loop_groups:
            if not group["indices"]:
                continue
            t = group["t"]
            if t <= fret_position_ratio:
                if fret_position_ratio > 1e-8:
                    weight = t / fret_position_ratio
                else:
                    weight = 0.0
            else:
                tail_len = 1.0 - fret_position_ratio
                if tail_len > 1e-8:
                    weight = (1.0 - t) / tail_len
                else:
                    weight = 0.0

            center_local = Vector((0.0, 0.0, 0.0))
            indices = group["indices"]
            for i in indices:
                center_local += bm.verts[i].co
            center_local /= len(indices)

            center_world = morph_obj.matrix_world @ center_local
            to_center = center_world - p1
            center_distance = to_center.dot(plane_normal)
            center_projected_world = center_world - center_distance * plane_normal
            center_projected_local = morph_obj.matrix_world.inverted() @ center_projected_world
            displacement_to_plane = center_projected_local - center_local

            loop_displacement = -displacement_to_plane * weight
            for i in indices:
                bm.verts[i].co += loop_displacement

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

    # 计算与 shape key 生成完成后，再绑定到指板参考点同 parent，避免影响世界坐标计算。
    fretboard_parent = resolved_refs['middle_fret_board_position'].parent
    _set_parent_keep_world_transform(current_object, fretboard_parent)
    if fretboard_parent is not None:
        print(f"已设置父级为: {fretboard_parent.name}（保持世界坐标不变）")
    else:
        print("参考点无父级，琴弦保持无父级（保持世界坐标不变）")


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
