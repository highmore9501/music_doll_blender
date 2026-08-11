# harp_glide/tools/string_tools.py
"""竖琴弦工具（迁移自 harp_blender_addon/tools/string_tools.py）

主要改动：
- create_string_shape_key 从物理 s{n}head/end 对象读位置（沿用）
- 振动方向改从骨骼 JSON hand_poses.left.far/near 读（替代原 H_L_far/H_L_near 物理对象）
- create_all_strings_shape_keys 从骨骼 JSON config.string_count 读弦数
- linear_distribute_recorders 沿用原逻辑（操作物理对象 location）
"""

import bpy     # type: ignore
import bmesh  # type: ignore
from mathutils import Vector  # type: ignore

from ...common import performer_utils as _pu
from ...common import state_io
from ..config import STATE_KEY


# ── 参数区绘制（供 ToolDef.draw 使用）─────────────────────────

def draw_create_string_shape_key(layout, scene):
    props = scene.md_hg_props
    layout.prop(props, "string_index", text="弦序号")
    layout.prop(props, "string_amplitude", text="振幅比例")


def draw_create_all_strings_shape_keys(layout, scene):
    props = scene.md_hg_props
    layout.prop(props, "string_amplitude", text="振幅比例")


def draw_linear_distribute(layout, scene):
    layout.label(text="选中两端 Empty，中间弦标记将线性分布", icon="INFO")


# ── 内部辅助：振动方向 ───────────────────────────────────────

def _get_vibration_dir(suffix: str, skeleton) -> Vector:
    """从骨骼 JSON hand_poses.left.far/near 计算振动方向"""
    data = state_io.get_state_data(skeleton, STATE_KEY, {})
    poses = data.get("hand_poses", {}).get("left", {})

    far_entry = poses.get("far",  {}).get("H_L", {})
    near_entry = poses.get("near", {}).get("H_L", {})

    far_loc = far_entry.get("location",  [0.0, 0.0, 0.0])
    near_loc = near_entry.get("location", [0.0, 0.0, 0.0])

    direction = Vector(far_loc) - Vector(near_loc)
    if direction.length > 1e-8:
        direction.normalize()
    else:
        direction = Vector((0.0, 1.0, 0.0))  # 回退方向
    return direction


# ── Shape Key 生成 ────────────────────────────────────────────

def _add_vibration_shape_key(string_obj, shape_key_name: str,
                             world_dir: Vector, string_length: float,
                             ratio: float) -> None:
    """为弦物体添加一个振动 Shape Key（二次方衰减从中点向两端）"""
    # harp_pivot 局部方向（弦 shape key 在 harp_pivot 坐标系下定义）
    pivot_obj = None
    for parent in [string_obj.parent, string_obj.parent.parent if string_obj.parent else None]:
        if parent and parent.name.startswith("harp_pivot"):
            pivot_obj = parent
            break
    if pivot_obj:
        local_dir = pivot_obj.matrix_world.inverted().to_3x3() @ world_dir
        local_dir.normalize()
    else:
        local_dir = world_dir

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

    从 s{n}head_<suffix> / s{n}end_<suffix> 物理对象读位置（沿用原逻辑）。
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

    string_name = f"string{string_index}"
    # 创建或复用弦圆柱物体
    if string_name not in bpy.data.objects:
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
        bpy.ops.mesh.loopcut_slide(
            MESH_OT_loopcut={"number_cuts": 80, "smoothness": 0,
                             "falloff": "INVERSE_SQUARE", "object_index": 0,
                             "edge_index": 0, "mesh_select_mode_changed": False},
            TRANSFORM_OT_edge_slide={"value": 0.0})
        bpy.ops.object.mode_set(mode="OBJECT")

        string_obj.shape_key_add(name="Basis")
    else:
        string_obj = bpy.data.objects[string_name]

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
