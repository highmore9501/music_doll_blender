# -*- coding: utf-8 -*-
"""方向箭头：给人工复核"这根手指的 Z 该朝哪"用（规则 §3.1 的第 1~2 步）。

做法和作者手工一致：在每根手指末节放一个**单箭头**空物体，箭头方向 = 指甲平面法线。
- 自动跑出来的方向只是**起始值**（手型特殊、指甲不明显、手指本身是弯的，机器判不准）；
- 你在 Blender 里直接把箭头转到位（吸附到平面 / 对齐旋转到平面），**再跑一次 rig_apply，
  它会优先读箭头**，按你转过的方向对齐 Z；
- 复核完删掉箭头即可（它们放在隐藏集合 `RigArrows` 里，删了不影响骨架）。

空物体的"单箭头"沿它自己的 **+Y** 显示，所以本模块用 +Y 当箭头方向。

用法：

    # 生成（已有就沿用，不覆盖你转过的方向）
    blender -b <file.blend> -P rig_arrows.py -- --create --side L [--save]
    # 打印现有箭头方向
    blender -b <file.blend> -P rig_arrows.py -- --print
    # 删掉
    blender -b <file.blend> -P rig_arrows.py -- --clear --save
"""
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rig_common as common  # noqa: E402

COLLECTION_NAME = "RigArrows"
FINGER_ORDER = ("thumb", "index", "middle", "ring", "pinky")
ARROW_PREFIX = "NailArrow"


def arrow_name(role, side):
    return "%s_%s_%s" % (ARROW_PREFIX, role, side)


def find_arrow(role, side):
    return bpy.data.objects.get(arrow_name(role, side))


def arrow_direction(armature_object, role, side):
    """读箭头的方向（世界空间 +Y，换算到骨架空间）。没有箭头返回 None。"""
    arrow = find_arrow(role, side)
    if arrow is None:
        return None
    world_direction = arrow.matrix_world.to_3x3() @ Vector((0.0, 1.0, 0.0))
    local_direction = armature_object.matrix_world.inverted().to_3x3() @ world_direction
    if local_direction.length < 1e-9:
        return None
    return local_direction.normalized()


def ensure_collection():
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
        bpy.context.scene.collection.children.link(collection)
        collection.hide_viewport = True
        collection.hide_render = True
    return collection


def create_arrow(armature_object, role, side, bone_name, direction, collection):
    """按方向摆一个单箭头（+Y 对准 direction）。已存在就不动它（保留人工转过的方向）。"""
    existing = find_arrow(role, side)
    if existing is not None:
        return existing, False
    bone = armature_object.data.bones[bone_name]
    location = armature_object.matrix_world @ ((bone.head_local + bone.tail_local) * 0.5)
    world_direction = (armature_object.matrix_world.to_3x3() @ direction).normalized()
    empty = bpy.data.objects.new(arrow_name(role, side), None)
    empty.empty_display_type = "SINGLE_ARROW"
    empty.empty_display_size = 0.012
    empty.show_in_front = True
    collection.objects.link(empty)
    empty.matrix_world = _matrix_from_y(world_direction, location)
    return empty, True


def _matrix_from_y(y_axis, location):
    """构造一个把本地 +Y 对准 y_axis 的变换矩阵。"""
    y_axis = y_axis.normalized()
    helper = Vector((0.0, 0.0, 1.0))
    if abs(y_axis.dot(helper)) > 0.95:
        helper = Vector((1.0, 0.0, 0.0))
    x_axis = y_axis.cross(helper).normalized()
    z_axis = x_axis.cross(y_axis).normalized()
    from mathutils import Matrix
    matrix = Matrix((
        (x_axis.x, y_axis.x, z_axis.x, location.x),
        (x_axis.y, y_axis.y, z_axis.y, location.y),
        (x_axis.z, y_axis.z, z_axis.z, location.z),
        (0.0, 0.0, 0.0, 1.0),
    ))
    return matrix


def finger_targets(bone_index, hand_name):
    """认出这只手的五指：{role: {"segments": [...], "last": 末节, "tip": 指尖骨}}。"""
    from rig_analyze import finger_role_of

    targets = {}
    for root_name, _depth, _length in common.find_finger_roots(bone_index, hand_name):
        role = finger_role_of(root_name)
        if role is None:
            continue
        parsed = common.analyze_finger_chain(bone_index, root_name)
        segments = [name for name in parsed["segments"] if name]
        if len(segments) < 3:
            continue
        targets[role] = {"segments": segments, "last": segments[-1], "tip": parsed["tip"],
                         "root": root_name}
    return targets


def _front_axis(bone_index):
    """人物前方（用于拇指的弯曲平面口径）：靠脚尖方向定，定不出来就返回 None（退回老办法）。"""
    foot_names = [name for name in bone_index
                  if common.role_from_name(name)["role"] == "foot"
                  and common.role_from_name(name)["variant"] in ("plain", "shadow")]
    try:
        front_axis, _evidence = common.detect_front_axis(bone_index, foot_names)
    except Exception:  # noqa: BLE001 - 定不出方向不该让出图失败
        return None
    return front_axis


def create_arrows(armature_object, side, report=print):
    """给一侧五指各摆一个箭头（方向 = 自动估的指甲法线，已有箭头不覆盖）。"""
    bone_index = common.build_bone_index(armature_object)
    collection = ensure_collection()
    created = []
    for hand_name in common.find_hand_candidates(bone_index):
        info = common.role_from_name(hand_name)
        if info["side"] != side:
            continue
        targets = finger_targets(bone_index, hand_name)
        if len(targets) < 4:
            continue
        nail_directions = common.finger_nail_directions(bone_index, hand_name, targets,
                                                         _front_axis(bone_index))
        for role in FINGER_ORDER:
            entry = targets.get(role)
            if not entry:
                continue
            direction = nail_directions.get(role)
            if direction is None:
                report("%s 算不出指甲方向，跳过" % role)
                continue
            arrow, was_created = create_arrow(armature_object, role, side, entry["last"],
                                              direction, collection)
            created.append((role, arrow.name, was_created))
            report("%s %-7s %s  %s" % (
                "新建" if was_created else "沿用", role, arrow.name,
                "(%.3f, %.3f, %.3f)" % tuple(arrow_direction(armature_object, role, side))))
    return created


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {"file": None, "create": False, "print": False, "clear": False,
               "save": False, "side": None}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--create":
            options["create"] = True
        elif token == "--print":
            options["print"] = True
        elif token == "--clear":
            options["clear"] = True
        elif token == "--save":
            options["save"] = True
        elif token == "--side":
            index += 1
            options["side"] = argv[index]
        else:
            options["file"] = token
        index += 1
    return options


def _main():
    options = _parse_args()
    if options["file"]:
        try:
            bpy.ops.wm.open_mainfile(filepath=options["file"], load_ui=False)
        except RuntimeError as error:
            print("open warning: %s" % str(error).splitlines()[0][:160])
    armature_object = next((obj for obj in bpy.data.objects if obj.type == "ARMATURE"), None)
    if armature_object is None:
        print("no armature")
        return
    if options["create"]:
        for side in ([options["side"]] if options["side"] else ["L", "R"]):
            create_arrows(armature_object, side)
    if options["print"]:
        for side in ("L", "R"):
            for role in FINGER_ORDER:
                direction = arrow_direction(armature_object, role, side)
                if direction is not None:
                    print("%s %-7s %s  %s" % (side, role, arrow_name(role, side),
                                              "(%.3f, %.3f, %.3f)" % tuple(direction)))
    if options["clear"]:
        for obj in list(bpy.data.objects):
            if obj.name.startswith(ARROW_PREFIX):
                bpy.data.objects.remove(obj, do_unlink=True)
                print("删除 %s" % obj.name)
    if options["save"]:
        bpy.ops.wm.save_mainfile()
        print("saved %s" % bpy.data.filepath)


if __name__ == "__main__":
    _main()
