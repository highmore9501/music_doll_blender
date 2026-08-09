# zheng_drift/tools/string_tools.py
"""ZhengDrift 乐器独有工具 —— 弦 Shape Key 生成 + 线性分布记录器
（迁移自 zheng_blender_addon/tools/string_tools.py）

对象名（弦记录器 / 弦物体 / shape key / Strings 集合）按演奏者后缀解析。
"""

import re  # type: ignore

import bmesh  # type: ignore
import bpy  # type: ignore
import mathutils  # type: ignore
from mathutils import Vector  # type: ignore

from ...common import object_utils
from ...common import performer_utils


def _get_strings_collection(suffix: str = ""):
    """获取/创建本演奏者的 Strings 集合（挂在 addons_<后缀> 下；无后缀兼容旧场景）"""
    if suffix:
        addons = performer_utils.find_addons_collection(suffix)
        if addons is None:
            raise ValueError("未找到角色 addons 目录，请先新建角色（初始化角色）")
        return object_utils.get_or_create_collection(
            performer_utils.resolve("Strings", suffix), addons)
    return object_utils.get_or_create_collection("Strings")


def create_string_shape_key(string_index: int, vibration_offset_ratio: float,
                            suffix: str = "") -> None:
    """为指定弦创建右手摇指和左手按弦的 Shape Key"""
    print(f"\n=== create_string_shape_key 开始 ===")
    print(f"弦序号：{string_index}, 振幅比例：{vibration_offset_ratio}")

    # 计算基准弦长
    try:
        head_0_name = performer_utils.resolve(f's{string_index}head', suffix)
        end_0_name = performer_utils.resolve(f's{string_index}end', suffix)

        if head_0_name in bpy.data.objects and end_0_name in bpy.data.objects:
            head_0_pos = bpy.data.objects[head_0_name].location
            end_0_pos = bpy.data.objects[end_0_name].location
            base_string_length = (end_0_pos - head_0_pos).length
            print(f"基准弦长：{base_string_length:.4f}")
        else:
            base_string_length = 1.0
            print(f"使用默认基准弦长：{base_string_length}")
    except Exception as e:
        print(f"计算基准弦长时出错：{e}")
        base_string_length = 1.0

    try:
        print("\n创建右手摇指弦...")
        create_right_side_shape_key(
            string_index, vibration_offset_ratio, base_string_length, suffix)

        print("\n创建左手按弦弦...")
        create_left_side_shape_key(
            string_index, vibration_offset_ratio, base_string_length, suffix)

        print(f"\n✓ 弦 {string_index} 的 shape keys 创建完成")
        print(f"=== create_string_shape_key 结束 ===\n")

    except Exception as e:
        print(f"\n✗ 错误：{str(e)}")
        raise


def create_all_strings_shape_keys(vibration_offset_ratio: float,
                                  suffix: str = "") -> None:
    """为所有 21 根弦创建右手摇指和左手按弦的 Shape Key"""
    print(f"\n=== create_all_strings_shape_keys 开始 ===")
    print(f"振幅比例：{vibration_offset_ratio}")
    print(f"将为所有 21 根弦批量创建 shape keys...\n")

    success_count = 0
    error_count = 0

    for i in range(21):
        try:
            print(f"\n[{i+1}/21] 处理弦 {i}...")

            head_0_name = performer_utils.resolve(f's{i}head', suffix)
            end_0_name = performer_utils.resolve(f's{i}end', suffix)

            if head_0_name in bpy.data.objects and end_0_name in bpy.data.objects:
                head_0_pos = bpy.data.objects[head_0_name].location
                end_0_pos = bpy.data.objects[end_0_name].location
                base_string_length = (end_0_pos - head_0_pos).length
                print(f"基准弦长（第 {i} 弦）：{base_string_length:.4f}")
            else:
                base_string_length = 1.0
                print(f"使用默认基准弦长：{base_string_length}")

            create_right_side_shape_key(
                i, vibration_offset_ratio, base_string_length, suffix)
            create_left_side_shape_key(
                i, vibration_offset_ratio, base_string_length, suffix)

            success_count += 1
            print(f"✓ 弦 {i} 创建成功")

        except Exception as e:
            error_count += 1
            print(f"✗ 弦 {i} 创建失败：{str(e)}")

    print(f"\n" + "=" * 60)
    print(f"批量创建完成！")
    print(f"  • 成功：{success_count} 根弦")
    print(f"  • 失败：{error_count} 根弦")
    print(f"  • 总计：{success_count + error_count} 根弦")
    print(f"=" * 60)
    print(f"=== create_all_strings_shape_keys 结束 ===\n")


def _build_cylinder_string(string_name, start_pos, end_pos,
                           base_string_length, track_target_obj):
    """创建指向终点的细分圆柱弦（共享逻辑）"""
    bpy.ops.mesh.primitive_cylinder_add(
        radius=base_string_length / 1200,
        depth=1,
        vertices=8,
        enter_editmode=False,
        align='WORLD',
        location=start_pos,
        scale=(1, 1, 1)
    )
    string_obj = bpy.context.active_object
    string_obj.name = string_name

    # 用 TRACK_TO 约束指向终点并应用变换
    track_constraint = string_obj.constraints.new(type='TRACK_TO')
    track_constraint.target = track_target_obj
    track_constraint.track_axis = 'TRACK_Z'
    track_constraint.up_axis = 'UP_Y'
    bpy.ops.object.visual_transform_apply()
    for constraint in string_obj.constraints:
        string_obj.constraints.remove(constraint)

    # 缩放弦到实际长度并移到中心
    string_vector = end_pos - start_pos
    string_length = string_vector.length
    string_obj.scale.z = string_length
    center_pos = (start_pos + end_pos) / 2
    string_obj.location = center_pos

    print(f"弦创建完成，长度：{string_length:.4f}, 中心位置：{center_pos}")

    # 细分圆柱（80 段）
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.loopcut_slide(
        MESH_OT_loopcut={
            "number_cuts": 80,
            "smoothness": 0,
            "falloff": 'INVERSE_SQUARE',
            "object_index": 0,
            "edge_index": 9,
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
            "release_confirm": False,
        }
    )
    bpy.ops.object.mode_set(mode='OBJECT')

    return string_obj, string_length


def _make_shape_key_from_temp(string_obj, temp_name, shape_key_name, suffix):
    """复制临时对象生成目标形状并写入 shape key（共享逻辑）"""
    if not string_obj.data.shape_keys:
        string_obj.shape_key_add(name='Basis')

    temp_obj = string_obj.copy()
    temp_obj.data = string_obj.data.copy()
    temp_obj.name = temp_name
    bpy.context.collection.objects.link(temp_obj)

    new_shape_key = string_obj.shape_key_add(
        name=shape_key_name, from_mix=False)

    return temp_obj, new_shape_key


def _finish_shape_key(string_obj, temp_obj, new_shape_key):
    """把临时对象顶点写入 shape key、删除临时对象、归零值"""
    for i, vert in enumerate(new_shape_key.data):
        vert.co = temp_obj.data.vertices[i].co

    bpy.data.objects.remove(temp_obj, do_unlink=True)
    new_shape_key.value = 0.0


def create_right_side_shape_key(string_index: int, vibration_offset_ratio: float,
                                base_string_length: float, suffix: str = "") -> None:
    """为指定弦创建右手摇指的 shape key"""
    print(f"\n=== create_right_side_shape_key 开始 ===")
    print(
        f"参数：string_index={string_index}, vibration_offset_ratio={vibration_offset_ratio}")

    # 1. 起点与中点位置
    head_obj_name = performer_utils.resolve(f's{string_index}head', suffix)
    mid_obj_name = performer_utils.resolve(f's{string_index}mid', suffix)

    if head_obj_name not in bpy.data.objects:
        raise ValueError(f"找不到起点物体：{head_obj_name}")
    if mid_obj_name not in bpy.data.objects:
        raise ValueError(f"找不到中点物体：{mid_obj_name}")

    head_obj = bpy.data.objects[head_obj_name]
    mid_obj = bpy.data.objects[mid_obj_name]
    start_pos = head_obj.location.copy()
    end_pos = mid_obj.location.copy()

    print(f"起点位置：{start_pos}")
    print(f"中点位置：{end_pos}")

    # 2-7. 创建细分圆柱弦
    string_name = performer_utils.resolve(f'string{string_index}_R', suffix)
    string_obj, string_length = _build_cylinder_string(
        string_name, start_pos, end_pos, base_string_length, mid_obj)

    # 8. 振动方向：s0head -> s20head
    s0head_name = performer_utils.resolve('s0head', suffix)
    s20head_name = performer_utils.resolve('s20head', suffix)
    if s0head_name not in bpy.data.objects or s20head_name not in bpy.data.objects:
        raise ValueError("找不到 s0head 或 s20head 物体")
    s0head_obj = bpy.data.objects[s0head_name]
    s20head_obj = bpy.data.objects[s20head_name]

    original_vector = s20head_obj.location - s0head_obj.location
    world_direction = original_vector.normalized()
    local_matrix = string_obj.matrix_world.to_3x3()
    local_direction = local_matrix.inverted() @ world_direction
    local_direction.normalize()
    print(f"振动方向（本地坐标）：{local_direction}")

    # 9. 生成 Shape Key
    temp_obj_name = performer_utils.resolve(
        f'string{string_index}_R_temp', suffix)
    shape_key_name = performer_utils.resolve(
        f'string{string_index}_vib', suffix)
    temp_obj, new_shape_key = _make_shape_key_from_temp(
        string_obj, temp_obj_name, shape_key_name, suffix)

    # 10. 空弦振动：从中间向两边二次方衰减
    bm = bmesh.new()
    bm.from_mesh(temp_obj.data)
    bm.verts.ensure_lookup_table()

    center = mathutils.Vector((0, 0, 0))
    for vert in bm.verts:
        center += vert.co
    center /= len(bm.verts)

    max_distance = 0
    distances = []
    for vert in bm.verts:
        distance = (vert.co - center).length
        distances.append(distance)
        if distance > max_distance:
            max_distance = distance

    for i, vert in enumerate(bm.verts):
        distance = distances[i]
        if max_distance > 0:
            ratio_val = (max_distance - distance) / max_distance
            ratio_val = ratio_val ** 2
        else:
            ratio_val = 1.0
        move_offset = local_direction * \
            (string_length * vibration_offset_ratio) * ratio_val
        vert.co += move_offset

    bm.to_mesh(temp_obj.data)
    bm.free()

    _finish_shape_key(string_obj, temp_obj, new_shape_key)

    # 14. 移入 Strings 集合
    _move_to_strings_collection(string_obj, suffix)
    print(f"弦物体已添加到 Strings 集合")
    print(f"=== create_right_side_shape_key 结束 ===\n")


def calculate_fret_position_ratio(fret_number: int) -> float:
    """根据 12 平均律计算品格位置比例"""
    return 1.0 - (1.0 / (2.0 ** (fret_number / 12.0)))


def create_left_side_shape_key(string_index: int, vibration_offset_ratio: float,
                               base_string_length: float, suffix: str = "") -> None:
    """为指定弦创建左手按弦的 shape key"""
    print(f"\n=== create_left_side_shape_key 开始 ===")
    print(
        f"参数：string_index={string_index}, vibration_offset_ratio={vibration_offset_ratio}")

    # 1. 中点与终点位置
    mid_obj_name = performer_utils.resolve(f's{string_index}mid', suffix)
    end_obj_name = performer_utils.resolve(f's{string_index}end', suffix)

    if mid_obj_name not in bpy.data.objects:
        raise ValueError(f"找不到起点物体：{mid_obj_name}")
    if end_obj_name not in bpy.data.objects:
        raise ValueError(f"找不到终点物体：{end_obj_name}")

    mid_obj = bpy.data.objects[mid_obj_name]
    end_obj = bpy.data.objects[end_obj_name]
    start_pos = mid_obj.location.copy()
    end_pos = end_obj.location.copy()

    print(f"起点位置（mid）：{start_pos}")
    print(f"终点位置（end）：{end_pos}")

    # 2-7. 创建细分圆柱弦
    string_name = performer_utils.resolve(f'string{string_index}_L', suffix)
    string_obj, string_length = _build_cylinder_string(
        string_name, start_pos, end_pos, base_string_length, end_obj)

    # 8. 按弦方向：s0head/s0end/s20head 三点平面法向量
    s0head_name = performer_utils.resolve('s0head', suffix)
    s0end_name = performer_utils.resolve('s0end', suffix)
    s20head_name = performer_utils.resolve('s20head', suffix)
    if (s0head_name not in bpy.data.objects or
            s0end_name not in bpy.data.objects or
            s20head_name not in bpy.data.objects):
        raise ValueError("找不到 s0head、s0end 或 s20head 物体")

    s0head_obj = bpy.data.objects[s0head_name]
    s0end_obj = bpy.data.objects[s0end_name]
    s20head_obj = bpy.data.objects[s20head_name]

    vec_s0 = s0end_obj.location - s0head_obj.location
    vec_s20 = s20head_obj.location - s0head_obj.location
    world_direction = vec_s20.cross(vec_s0)
    world_direction.normalize()

    local_matrix = string_obj.matrix_world.to_3x3()
    local_direction = local_matrix.inverted() @ world_direction
    local_direction.normalize()
    print(f"按弦方向（本地坐标）：{local_direction}")

    # 9. 生成 Shape Key
    temp_obj_name = performer_utils.resolve(
        f'string{string_index}_L_temp', suffix)
    shape_key_name = performer_utils.resolve(
        f'string{string_index}_press', suffix)
    temp_obj, new_shape_key = _make_shape_key_from_temp(
        string_obj, temp_obj_name, shape_key_name, suffix)

    # 10. 第 3 品按弦：分段线性插值变形
    fret_position_ratio = calculate_fret_position_ratio(3)
    print(f"第 3 品位置比例：{fret_position_ratio:.4f}")
    max_displacement = string_length * vibration_offset_ratio
    print(f"最大位移量：{max_displacement:.6f}")

    bm = bmesh.new()
    bm.from_mesh(temp_obj.data)
    bm.verts.ensure_lookup_table()

    vertices = [v.co for v in bm.verts]
    x_coords = [v.x for v in vertices]
    y_coords = [v.y for v in vertices]
    z_coords = [v.z for v in vertices]

    x_range = max(x_coords) - min(x_coords)
    y_range = max(y_coords) - min(y_coords)
    z_range = max(z_coords) - min(z_coords)

    ranges = {'x': x_range, 'y': y_range, 'z': z_range}
    main_axis = max(ranges.items(), key=lambda item: item[1])[0]

    coords_map = {'x': x_coords, 'y': y_coords, 'z': z_coords}
    coord_values = coords_map[main_axis]

    min_idx = coord_values.index(min(coord_values))
    max_idx = coord_values.index(max(coord_values))

    temp_start = vertices[min_idx]
    temp_end = vertices[max_idx]

    print(f"主延伸轴：{main_axis}, 起点索引：{min_idx}, 终点索引：{max_idx}")

    for vert in bm.verts:
        if string_length > 0:
            t = (vert.co - temp_start).length / (temp_end - temp_start).length
        else:
            t = 0

        if t <= fret_position_ratio:
            if fret_position_ratio > 0:
                segment_t = t / fret_position_ratio
            else:
                segment_t = 0
            displacement = local_direction * max_displacement * segment_t
        elif t < 1.0:
            if (1.0 - fret_position_ratio) > 0:
                segment_t = (t - fret_position_ratio) / \
                    (1.0 - fret_position_ratio)
            else:
                segment_t = 1.0
            displacement = local_direction * \
                max_displacement * (1.0 - segment_t)
        else:
            displacement = mathutils.Vector((0, 0, 0))

        vert.co += displacement

    bm.to_mesh(temp_obj.data)
    bm.free()

    _finish_shape_key(string_obj, temp_obj, new_shape_key)

    # 14. 移入 Strings 集合
    _move_to_strings_collection(string_obj, suffix)
    print(f"弦物体已添加到 Strings 集合")
    print(f"=== create_left_side_shape_key 结束 ===\n")


def _move_to_strings_collection(string_obj, suffix: str = "") -> None:
    """把弦物体从原集合移除并挂到本演奏者 Strings 集合"""
    strings_collection = _get_strings_collection(suffix)
    for collection in list(string_obj.users_collection):
        if string_obj.name in collection.objects:
            collection.objects.unlink(string_obj)
            break
    strings_collection.objects.link(string_obj)


# ── 线性分布记录器 ───────────────────────────────────────────

def get_common_suffix(name1: str, name2: str) -> str:
    """获取两个字符串的公共后缀"""
    min_len = min(len(name1), len(name2))
    suffix = ""
    for i in range(1, min_len + 1):
        if name1[-i] == name2[-i]:
            suffix = name1[-i] + suffix
        else:
            break
    return suffix


def _short_name_of(obj_name: str) -> str:
    """去掉已知演奏者后缀，返回短名（未登记则原样返回）"""
    parsed = performer_utils.performer_from_object(obj_name)
    if parsed:
        return parsed[1]
    return obj_name


def linear_distribute_recorders() -> None:
    """将选中的两个记录器之间的所有记录器进行线性分布。

    根据选中物体名称模式（如 s0head / s20head，或带演奏者后缀的
    s0head_Jd / s20head_Jd），自动识别序号范围并线性分布。
    """
    print("\n=== linear_distribute_recorders 开始 ===")

    selected = bpy.context.selected_objects
    if len(selected) != 2:
        raise ValueError("请选中两个物体")

    obj_a, obj_b = selected[0], selected[1]

    # 先去掉演奏者后缀，再提取公共后缀（避免把序号吞进后缀）
    short_a = _short_name_of(obj_a.name)
    short_b = _short_name_of(obj_b.name)
    suffix = get_common_suffix(short_a, short_b)

    if not suffix:
        raise ValueError("无法从选中的物体名称中提取公共后缀")

    print(f"检测到公共后缀：'{suffix}'")

    pattern = re.compile(r'^s(\d+)' + re.escape(suffix) + r'$')

    match_a = pattern.match(short_a)
    match_b = pattern.match(short_b)
    if not match_a or not match_b:
        raise ValueError(
            f"选中的物体名称不符合 'snumber{suffix}' 格式\n"
            f"  {obj_a.name} -> 匹配: {match_a is not None}\n"
            f"  {obj_b.name} -> 匹配: {match_b is not None}"
        )

    num_a = int(match_a.group(1))
    num_b = int(match_b.group(1))

    print(f"选中物体序号：{num_a}, {num_b}")

    # 收集场景中所有符合格式的物体（先去掉后缀再匹配）
    objects_with_numbers = []
    for obj in bpy.data.objects:
        match = pattern.match(_short_name_of(obj.name))
        if match:
            objects_with_numbers.append((int(match.group(1)), obj))

    if len(objects_with_numbers) < 2:
        raise ValueError("找到的符合格式的物体不足两个")

    objects_with_numbers.sort(key=lambda x: x[0])

    min_num = min(num_a, num_b)
    max_num = max(num_a, num_b)

    print(f"分布范围：[{min_num}, {max_num}]")

    target_objects = [(n, obj) for n, obj in objects_with_numbers
                      if min_num <= n <= max_num]

    if len(target_objects) < 2:
        raise ValueError("范围内物体不足两个")

    pos_a = obj_a.location
    pos_b = obj_b.location
    direction = pos_b - pos_a
    total_length = direction.length

    if total_length < 1e-6:
        raise ValueError("两个端点位置重合")

    direction.normalize()

    start_num = target_objects[0][0]
    end_num = target_objects[-1][0]
    num_span = end_num - start_num

    if num_span == 0:
        raise ValueError("序号范围为零")

    distributed_count = 0
    for num, obj in target_objects:
        t = (num - start_num) / num_span
        new_location = pos_a + direction * (t * total_length)
        obj.location = new_location
        distributed_count += 1

    print(f"✓ 已分布 {distributed_count} 个物体")
    print(f"=== linear_distribute_recorders 结束 ===\n")
