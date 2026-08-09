# common/object_utils.py
"""集合 / 物体幂等创建 —— 公共模块（对应各乐器插件里的 create_or_update_object 等）

提供所有乐器共用的集合创建、物体创建/更新、物体移动工具。
命名统一交给调用方（performer_utils.resolve / 各乐器 config 的 obj_name）。
"""

import bpy  # type: ignore


def get_or_create_collection(name: str,
                             parent_collection=None) -> bpy.types.Collection:
    """按完整名获取/创建集合（不自动加后缀，调用方传入完整名）。

    - 已存在则复用；
    - 未指定父集合时挂到场景主集合下。
    """
    if name in bpy.data.collections:
        collection = bpy.data.collections[name]
    else:
        collection = bpy.data.collections.new(name)
        if parent_collection is not None:
            parent_collection.children.link(collection)
        else:
            bpy.context.scene.collection.children.link(collection)

    # 确保挂在指定父集合下
    if parent_collection is not None and \
            collection.name not in [c.name for c in parent_collection.children]:
        parent_collection.children.link(collection)
    return collection


def move_object_to_collection(obj, collection) -> None:
    """把对象从所有现有集合移除并挂到目标集合。"""
    if obj is None or collection is None:
        return
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)


def move_children(obj, dest_coll) -> None:
    """把对象的全部子级移到目标集合。"""
    if obj is None or dest_coll is None:
        return
    for child in list(obj.children):
        move_object_to_collection(child, dest_coll)


def create_or_update_object(obj_name: str, obj_type: str = "cube",
                            collection=None, rotation_mode: str = "QUATERNION",
                            scale: float = 1.0):
    """创建或更新物体（幂等：已存在则复用并归位）。

    :param obj_name: 完整物体名（调用方负责加后缀）
    :param obj_type: "cube" / "cone" / "sphere" / "cone_empty" / "single_arrow"
    :param collection: 物体所属集合（可空）
    :param rotation_mode: 旋转模式，默认四元数
    :param scale: 物体缩放（cube 用）
    """
    # 已存在：归位并返回
    if obj_name in bpy.data.objects:
        obj = bpy.data.objects[obj_name]
        if collection is not None and obj.name not in collection.objects:
            move_object_to_collection(obj, collection)
        return obj

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    # 按类型创建
    if obj_type == "cube":
        bpy.ops.mesh.primitive_cube_add(
            size=0.2, enter_editmode=False, align="WORLD",
            location=(0, 0, 0), scale=(0.1 * scale, 0.1 * scale, 0.1 * scale))
    elif obj_type == "cone":
        bpy.ops.mesh.primitive_cone_add(
            enter_editmode=False, align="WORLD",
            location=(0, 0, 0), scale=(0.01, 0.01, 0.01))
    elif obj_type == "sphere":
        bpy.ops.object.empty_add(type="SPHERE", radius=0.01 * scale)
    elif obj_type == "cone_empty":
        bpy.ops.object.empty_add(type="CONE", radius=0.01 * scale)
    elif obj_type == "single_arrow":
        bpy.ops.object.empty_add(type="SINGLE_ARROW", radius=1.0 * scale)
    else:
        # 未知类型回退到 sphere 空物体
        bpy.ops.object.empty_add(type="SPHERE", radius=0.01 * scale)

    obj = bpy.context.active_object
    obj.name = obj_name

    # 旋转模式（mesh 物体没有 rotation_mode 属性）
    if hasattr(obj, "rotation_mode") and rotation_mode:
        obj.rotation_mode = rotation_mode

    if collection is not None:
        move_object_to_collection(obj, collection)

    return obj


def create_or_update_empty(obj_name: str, collection=None):
    """创建/更新一个空物体（SPHERE）。"""
    return create_or_update_object(obj_name, "sphere", collection)


def parent_to(parent_obj, child_obj) -> None:
    """把 child 挂到 parent 下（Blender 保持世界位置不变）。"""
    if parent_obj is None or child_obj is None:
        return
    if child_obj.parent != parent_obj:
        child_obj.parent = parent_obj


def zero_local_transform(obj) -> None:
    """把 obj 的本地 transform 归零（位置原点、无旋转、缩放 1）。"""
    if obj is None:
        return
    obj.location = (0, 0, 0)
    obj.scale = (1, 1, 1)
    if obj.rotation_mode == "QUATERNION":
        obj.rotation_quaternion = (1, 0, 0, 0)
    elif obj.rotation_mode == "AXIS_ANGLE":
        obj.rotation_axis_angle = (0, 0, 1, 0)
    else:
        obj.rotation_euler = (0, 0, 0)


def parent_and_zero_local(parent_obj, child_obj) -> None:
    """把 child 挂到 parent 下并归零本地 transform（从世界观察不变）。

    前提：parent 与 child 的世界 transform 一致（如父为演奏者根、子为身体骨骼，
    根在创建时复制了骨骼的 transform，故归零后世界坐标不变）。
    """
    if parent_obj is None or child_obj is None:
        return
    child_obj.parent = parent_obj
    zero_local_transform(child_obj)


def copy_transform_from(src_obj, dst_obj) -> None:
    """把 src 的位置/旋转/缩放复制给 dst（按 src 的旋转模式）。"""
    if src_obj is None or dst_obj is None:
        return
    dst_obj.location = src_obj.location
    dst_obj.rotation_mode = src_obj.rotation_mode
    if src_obj.rotation_mode == "QUATERNION":
        dst_obj.rotation_quaternion = src_obj.rotation_quaternion
    else:
        dst_obj.rotation_euler = src_obj.rotation_euler
    dst_obj.scale = src_obj.scale
