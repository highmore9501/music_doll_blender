# harp_glide/tools/string_tools.py
"""竖琴弦工具（迁移自 harp_blender_addon/tools/string_tools.py）

主要改动：
- 弦物体命名带演奏者后缀：string{n}_{suffix}（无后缀兼容旧场景），
  生成后归入本演奏者的 Strings_<suffix> 集合；
- create_string_shape_key 从物理 s{n}head_<suffix> / s{n}end_<suffix> 对象读位置；
  振动方向改从骨骼 JSON hand_poses.left.far/near 读（替代原 H_L_far/H_L_near 物理对象），
  经 H_L 父级世界矩阵还原成世界方向后，再按弦物体自身矩阵转成物体局部方向
  （shape key 顶点坐标所在空间）；
- create_all_strings_shape_keys 从骨骼 JSON config.string_count 读弦数；
- linear_distribute_recorders 沿用原逻辑（操作物理对象 location）。
"""

import bpy     # type: ignore
import bmesh  # type: ignore
from mathutils import Vector  # type: ignore

from ...common import i18n; T = i18n.T
from ...common import object_utils
from ...common import performer_utils as _pu
from ...common import state_io
from ..config import STATE_KEY


# ── 参数区绘制（供 ToolDef.draw 使用）─────────────────────────

def draw_create_string_shape_key(layout, scene):
    props = scene.md_hg_props
    layout.prop(props, "string_index", text=T("弦序号"))
    layout.prop(props, "string_amplitude", text=T("振幅比例"))


def draw_create_all_strings_shape_keys(layout, scene):
    props = scene.md_hg_props
    layout.prop(props, "string_amplitude", text=T("振幅比例"))


def draw_linear_distribute(layout, scene):
    layout.label(text=T("选中两端 Empty，中间弦标记将线性分布"), icon="INFO")


# ── 弦物体集合（按演奏者后缀归位）────────────────────────────

def _move_to_strings_collection(string_obj, suffix: str = "") -> None:
    """把生成的弦物体归入本演奏者的 Strings 集合

    - 有后缀 → addons_<后缀>/Strings_<后缀>（与 zheng_drift 弦工具一致，
      避免落到当前激活集合里串到别的演奏者名下）；
    - 找不到 addons 目录时保留在原集合，不中断弦的生成；
    - 无后缀 → 全局 Strings 集合（兼容旧场景）。
    """
    if suffix:
        addons = _pu.find_addons_collection(suffix)
        if addons is None:
            print("  ⚠ 未找到角色 addons 目录，弦物体保留在原集合（请先初始化角色）")
            return
        strings_coll = object_utils.get_or_create_collection(
            _pu.resolve("Strings", suffix), addons)
    else:
        strings_coll = object_utils.get_or_create_collection("Strings")
    object_utils.move_object_to_collection(string_obj, strings_coll)


# ── 内部辅助：振动方向 ───────────────────────────────────────

def _get_vibration_dir(suffix: str, skeleton) -> Vector:
    """从骨骼 JSON hand_poses.left.far/near 计算振动方向（世界方向）

    记录的是 H_L 的局部 location（相对其父级，通常是 controller_root_<suffix>），
    因此差值要经父级的世界矩阵变换才是世界方向——否则整个角色/骨骼带有旋转
    时（如骨骼对象带 ±90° 轴转换），振动方向会跟着偏掉。
    """
    data = state_io.get_state_data(skeleton, STATE_KEY, {})
    poses = data.get("hand_poses", {}).get("left", {})

    far_entry = poses.get("far",  {}).get("H_L", {})
    near_entry = poses.get("near", {}).get("H_L", {})

    far_loc = far_entry.get("location",  [0.0, 0.0, 0.0])
    near_loc = near_entry.get("location", [0.0, 0.0, 0.0])

    direction = Vector(far_loc) - Vector(near_loc)
    if direction.length <= 1e-8:
        return Vector((0.0, 1.0, 0.0))  # 回退方向

    hand_ctrl = bpy.data.objects.get(_pu.resolve("H_L", suffix))
    parent_obj = hand_ctrl.parent if hand_ctrl else None
    if parent_obj is not None:
        # 局部 location 所在空间 → 世界：matrix_world = parent.matrix_world
        # @ matrix_parent_inverse @ matrix_basis（location 属于 matrix_basis）
        local_to_world = parent_obj.matrix_world @ hand_ctrl.matrix_parent_inverse
        direction = local_to_world.to_3x3() @ direction

    direction.normalize()
    return direction


# ── Shape Key 生成 ────────────────────────────────────────────

# primitive_cylinder_add(vertices=8) 的顶点数（只有首尾两圈，未环切细分）
_RAW_CYLINDER_VERT_COUNT = 16


def _is_unsubdivided_leftover(string_obj) -> bool:
    """是否是生成中途失败留下的未细分圆柱（无 shape key 且只有首尾两圈顶点）

    这种残留物直接复用会把 shape key 写在弦身没有中间顶点的网格上（弦不会弯），
    工具自己重新建一根即可，故按「工具自己的中间产物」处理。
    """
    mesh = string_obj.data
    if string_obj.type != "MESH" or mesh is None:
        return False
    return not mesh.shape_keys and len(mesh.vertices) <= _RAW_CYLINDER_VERT_COUNT


def _add_vibration_shape_key(string_obj, shape_key_name: str,
                             world_dir: Vector, string_length: float,
                             ratio: float) -> None:
    """为弦物体添加一个振动 Shape Key（二次方衰减从中点向两端）

    振动方向按**弦物体自身矩阵**转到物体局部坐标——shape key 顶点坐标就在
    该空间里，用父级（harp_pivot）矩阵或世界方向直接当局部方向都会在物体
    自身有旋转/缩放时把振动方向带偏。
    """
    local_dir = string_obj.matrix_world.to_3x3().inverted() @ world_dir
    if local_dir.length > 1e-8:
        local_dir.normalize()
    else:
        local_dir = Vector((0.0, 1.0, 0.0))  # 回退方向

    temp = string_obj.copy()
    temp.data = string_obj.data.copy()
    bpy.context.collection.objects.link(temp)

    new_sk = string_obj.shape_key_add(name=shape_key_name, from_mix=False)

    bm = bmesh.new()
    bm.from_mesh(temp.data)
    bm.verts.ensure_lookup_table()

    center = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    max_dist = max((v.co - center).length for v in bm.verts) or 1e-10

    for v in bm.verts:
        dist = (v.co - center).length
        t = ((max_dist - dist) / max_dist) ** 2
        v.co += local_dir * (string_length * ratio) * t

    bm.to_mesh(temp.data)
    bm.free()

    for i, sk_vert in enumerate(new_sk.data):
        sk_vert.co = temp.data.vertices[i].co

    bpy.data.objects.remove(temp, do_unlink=True)
    new_sk.value = 0.0


def create_string_shape_key(skeleton, suffix: str,
                            string_index: int, ratio: float) -> None:
    """为指定弦创建振动 Shape Key

    弦物体命名 string{n}_{suffix}（无后缀兼容旧场景），生成后归入本演奏者的
    Strings 集合；从 s{n}head_<suffix> / s{n}end_<suffix> 物理对象读位置。
    振动方向从骨骼 JSON hand_poses.left.far/near 读。
    """
    head_name = _pu.resolve(f"s{string_index}head", suffix)
    end_name = _pu.resolve(f"s{string_index}end",  suffix)

    head_obj = bpy.data.objects.get(head_name)
    end_obj = bpy.data.objects.get(end_name)
    if not head_obj or not end_obj:
        raise ValueError(f"找不到弦位置标记：{head_name} / {end_name}")

    start_pos = head_obj.matrix_world.translation.copy()
    end_pos = end_obj.matrix_world.translation.copy()

    string_vec = end_pos - start_pos
    string_length = string_vec.length
    if string_length < 1e-6:
        raise ValueError(f"弦 {string_index} 头尾重合，无法生成")

    string_name = _pu.resolve(f"string{string_index}", suffix)
    string_obj = bpy.data.objects.get(string_name)

    # 上次生成中途失败留下的未细分圆柱：删掉重建（否则复用会把 shape key
    # 写到弦身没有中间顶点的网格上）
    if string_obj is not None and _is_unsubdivided_leftover(string_obj):
        print(f"  ⚠ {string_name} 是未细分的残留圆柱"
              f"（{len(string_obj.data.vertices)} 顶点），重建")
        bpy.data.objects.remove(string_obj, do_unlink=True)
        string_obj = None

    # 创建或复用弦圆柱物体
    if string_obj is None:
        bpy.ops.mesh.primitive_cylinder_add(
            radius=string_length / 1200,
            depth=1, vertices=8,
            enter_editmode=False, align="WORLD",
            location=start_pos)
        string_obj = bpy.context.active_object
        string_obj.name = string_name

        track = string_obj.constraints.new("TRACK_TO")
        track.target = end_obj
        track.track_axis = "TRACK_Z"
        track.up_axis = "UP_Y"
        bpy.ops.object.visual_transform_apply()
        string_obj.constraints.remove(track)

        string_obj.scale.z = string_length
        string_obj.location = (start_pos + end_pos) / 2

        bpy.ops.object.mode_set(mode="EDIT")
        # edge_index=9：8 顶点圆柱的第 9 条边是纵向边，环切才会沿弦长切出一圈圈
        # 横环（edge 0 是端盖的 n-gon 环边，环被 n-gon 截断，切不出弦身顶点）；
        # 参数名必须用 mesh_select_mode_init（Blender 无 mesh_select_mode_changed）。
        bpy.ops.mesh.loopcut_slide(
            MESH_OT_loopcut={"number_cuts": 80, "smoothness": 0,
                             "falloff": "INVERSE_SQUARE", "object_index": 0,
                             "edge_index": 9,
                             "mesh_select_mode_init": (True, False, False)},
            TRANSFORM_OT_edge_slide={"value": 0.0})
        bpy.ops.object.mode_set(mode="OBJECT")

        string_obj.shape_key_add(name="Basis")
    elif not string_obj.data.shape_keys:
        string_obj.shape_key_add(name="Basis")

    _move_to_strings_collection(string_obj, suffix)

    vib_dir = _get_vibration_dir(suffix, skeleton)

    for sk_type, direction_mult in (("inner", 1.0), ("outer", -1.0)):
        sk_name = f"string{string_index}_{sk_type}"
        if sk_name in (string_obj.data.shape_keys.key_blocks if string_obj.data.shape_keys else []):
            continue
        _add_vibration_shape_key(string_obj, sk_name,
                                 vib_dir * direction_mult,
                                 string_length, ratio)

    print(f"✓ 弦 {string_index} Shape Key 创建完成")


def create_all_strings_shape_keys(skeleton, suffix: str, ratio: float) -> None:
    """批量为所有弦创建 Shape Key，弦数从骨骼 JSON config.string_count 读"""
    data = state_io.get_state_data(skeleton, STATE_KEY, {})
    string_count = int(data.get("config", {}).get("string_count", 47))
    for i in range(string_count):
        try:
            create_string_shape_key(skeleton, suffix, i, ratio)
        except Exception as e:
            print(f"  ✗ 弦 {i} 失败：{e}")
    print(f"✓ 批量生成完成（{string_count} 根弦）")


# ── 线性分布弦位置标记 ───────────────────────────────────────

def linear_distribute_recorders(suffix: str) -> None:
    """在当前选中的两端 Empty 之间线性分布中间的 s{n}head/end 物体

    沿用原 linear_distribute_recorders 逻辑：
    选中物体必须恰好是两个，分别作为起点和终点，
    同名前缀的中间物体按序号线性插值其 location。
    """
    selected = [o for o in bpy.context.selected_objects
                if o.type == "EMPTY"]
    if len(selected) != 2:
        raise ValueError("请选中恰好两个 Empty 物体作为起点和终点")

    obj_a, obj_b = selected
    # 按名称序号排序（s0head < s46head 等）

    def _index(obj):
        import re
        m = re.search(r's(\d+)', obj.name)
        return int(m.group(1)) if m else 0

    if _index(obj_a) > _index(obj_b):
        obj_a, obj_b = obj_b, obj_a

    start_pos = obj_a.location.copy()
    end_pos = obj_b.location.copy()
    start_idx = _index(obj_a)
    end_idx = _index(obj_b)

    if end_idx <= start_idx:
        raise ValueError("两端物体序号相同，无法线性分布")

    total = end_idx - start_idx
    # 确定是 head 还是 end 系列
    import re
    m = re.match(r's\d+(head|end)', obj_a.name.split("_")
                 [0] if "_" in obj_a.name else obj_a.name)
    part = m.group(1) if m else "head"

    for i in range(start_idx + 1, end_idx):
        t = (i - start_idx) / total
        new_loc = start_pos.lerp(end_pos, t)
        short = f"s{i}{part}"
        full = _pu.resolve(short, suffix)
        obj = bpy.data.objects.get(full)
        if obj:
            obj.location = new_loc

    print(f"✓ 线性分布完成：s{start_idx} → s{end_idx}（{total - 1} 个中间标记）")
