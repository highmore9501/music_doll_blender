# -*- coding: utf-8 -*-
"""标定 `pole_angle`：扫一圈角度，看 IK 解算后中间关节到底朝哪边弯。

判据是"中间关节相对肩→目标弦的偏移方向"与凸侧（手臂朝后）的夹角：
- 夹角小 = 这一档极向量真的把肘顶到了凸侧；
- 偏移量≈0 = 链是直的（或极向量没起作用），这种档位不能用来标定。

弦通常不水平，所以"正后方"要先投影到垂直于弦的平面上再比（那才是这一档能弯到的方向）。

用法：
    blender -b <file.blend> -P rig_pole_sweep.py -- \
        --owner MCH_ひじ.L [--hand H_L_test] [--pole HP_L_test] [--root MCH_腕.L] \
        [--target x,y,z | --targets "x,y,z;x,y,z"] [--range 60,150] [--step 5] \
        [--convex back|front] [--no-pole] [--json out.json]

`--convex`：中间关节要顶向哪一侧。手臂朝后（肘尖）、腿朝前（膝盖），两条链的方向正好相反。
owner 上有多条 IK 时，优先用"没 mute 且带极向量"的那条（MMD 自带的腿 IK 通常已经 mute 掉了）。
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rig_common as common  # noqa: E402

BACK = Vector((0.0, 1.0, 0.0))
FRONT = Vector((0.0, -1.0, 0.0))


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {"file": None, "owner": None, "hand": None, "pole": None, "targets": None,
               "step": 10.0, "no_pole": False, "json": None, "root": None, "angle_range": None,
               "convex": "back"}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--range":
            index += 1
            options["angle_range"] = [float(part) for part in argv[index].split(",")]
        elif token == "--convex":
            index += 1
            options["convex"] = argv[index]
        elif token == "--targets":
            index += 1
            options["targets"] = [Vector([float(part) for part in item.split(",")])
                                  for item in argv[index].split(";") if item]
        elif token == "--owner":
            index += 1
            options["owner"] = argv[index]
        elif token == "--hand":
            index += 1
            options["hand"] = argv[index]
        elif token == "--pole":
            index += 1
            options["pole"] = argv[index]
        elif token == "--root":
            index += 1
            options["root"] = argv[index]
        elif token == "--target":
            index += 1
            options["targets"] = [Vector([float(part) for part in argv[index].split(",")])]
        elif token == "--step":
            index += 1
            options["step"] = float(argv[index])
        elif token == "--no-pole":
            options["no_pole"] = True
        elif token == "--json":
            index += 1
            options["json"] = argv[index]
        else:
            options["file"] = token
        index += 1
    return options


def evaluated_bone_point(armature_object, bone_name, which):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = armature_object.evaluated_get(depsgraph)
    pose_bone = evaluated.pose.bones[bone_name]
    point = pose_bone.head if which == "head" else pose_bone.tail
    return evaluated.matrix_world @ point


def _fmt(vector):
    return "(%.4f, %.4f, %.4f)" % (vector[0], vector[1], vector[2])


def sweep_pose(armature_object, constraint, owner_name, root_head, target_point,
               start_angle, end_angle, step, convex_direction=BACK):
    """在一个目标位置上扫 pole_angle，返回每一档的测量结果。"""
    chord = target_point - root_head
    chord_length = chord.length
    chord_unit = chord / chord_length
    convex_raw = convex_direction - chord_unit * convex_direction.dot(chord_unit)
    if convex_raw.length < 1e-6:
        convex_raw = BACK - chord_unit * BACK.dot(chord_unit)
    convex_in_plane = convex_raw.normalized()
    # 极向量本身在垂直弦平面上的方向：中间关节应该朝这个方向弯，这一条与姿势无关（比"正后方"更本质）
    pole_in_plane = None
    if constraint.pole_target is not None:
        pole_point = constraint.pole_target.matrix_world.translation
        raw = pole_point - root_head
        raw = raw - chord_unit * raw.dot(chord_unit)
        if raw.length > 1e-6:
            pole_in_plane = raw.normalized()
    rows = []
    angle = start_angle
    while angle < end_angle - 1e-6:
        constraint.pole_angle = math.radians(angle)
        bpy.context.view_layer.update()
        elbow = evaluated_bone_point(armature_object, owner_name, "head")
        wrist = evaluated_bone_point(armature_object, owner_name, "tail")
        offset = (elbow - root_head) - chord_unit * (elbow - root_head).dot(chord_unit)
        dot_convex = offset.normalized().dot(convex_in_plane) if offset.length > 1e-9 else 0.0
        angle_to_convex = common.angle_between(offset, convex_in_plane) if offset.length > 1e-9 else None
        angle_to_pole = (common.angle_between(offset, pole_in_plane)
                         if (offset.length > 1e-9 and pole_in_plane is not None) else None)
        rows.append({
            "pole_angle_deg": round(angle, 1),
            "elbow_offset": round(offset.length, 5),
            "offset_ratio_percent": round(offset.length / chord_length * 100.0, 2),
            "dot_back": round(dot_convex, 3),
            "angle_to_back_deg": round(angle_to_convex, 1) if angle_to_convex is not None else None,
            "angle_to_pole_deg": round(angle_to_pole, 1) if angle_to_pole is not None else None,
            "elbow": [round(value, 4) for value in elbow],
            "wrist_error": round((wrist - target_point).length, 5),
        })
        angle += step
    return rows, convex_in_plane, pole_in_plane


def main():
    options = parse_args()
    if options["file"]:
        try:
            bpy.ops.wm.open_mainfile(filepath=options["file"], load_ui=False)
        except RuntimeError as error:
            print("open warning: %s" % str(error).splitlines()[0][:160])
    armature_object = next(obj for obj in bpy.data.objects if obj.type == "ARMATURE")
    owner_name = options["owner"]
    pose_bone = armature_object.pose.bones[owner_name]
    ik_constraints = [con for con in pose_bone.constraints if con.type == "IK"]
    # 有的骨架上同一根骨挂着两条 IK：MMD 自带的那条（已经 mute、没有极向量）和我们加的。
    # 扫的是我们那条 —— 优先"没 mute 且带极向量"，其次"没 mute"，最后才退回第一条。
    constraint = (next((con for con in ik_constraints if not con.mute and con.pole_target), None)
                  or next((con for con in ik_constraints if not con.mute), None)
                  or (ik_constraints[0] if ik_constraints else None))
    if constraint is None:
        print("%s 上没有 IK 约束" % owner_name)
        return
    if constraint.mute:
        print("注意：%s 上的 IK（%s）是 mute 的，扫它没有意义" % (owner_name, constraint.name))
    print("扫的约束：%s（mute=%s）" % (constraint.name, constraint.mute))
    convex_direction = FRONT if options["convex"] == "front" else BACK

    root_name = options["root"] or pose_bone.parent.name
    root_head = armature_object.matrix_world @ armature_object.data.bones[root_name].head_local
    target_object = constraint.target
    pole_object = constraint.pole_target

    if options["no_pole"]:
        constraint.pole_target = None
        print("没有极向量（pole_target=None）")
        bpy.context.view_layer.update()
    elif pole_object is not None and options["pole"]:
        print("极向量 = %s，位置 %s" % (pole_object.name, _fmt(pole_object.matrix_world.translation)))

    print("root=%s %s   IK 挂在 %s   target=%s" % (
        root_name, _fmt(root_head), owner_name,
        target_object.name if target_object else None))

    start_angle, end_angle = (options["angle_range"] if options["angle_range"] else (0.0, 360.0))
    targets = options["targets"] or [target_object.matrix_world.translation.copy()]
    all_results = []
    for target_point in targets:
        target_object.location = target_point
        bpy.context.view_layer.update()
        actual_target = target_object.matrix_world.translation.copy()
        rows, convex_in_plane, pole_in_plane = sweep_pose(
            armature_object, constraint, owner_name, root_head, actual_target,
            start_angle, end_angle, options["step"], convex_direction)
        best = max(rows, key=lambda row: (row["dot_back"] * row["elbow_offset"]))
        distinct = len({tuple(row["elbow"]) for row in rows})
        print("")
        print("目标 %s（到肩 %.4f）" % (_fmt(actual_target), (actual_target - root_head).length))
        print("  凸侧方向（%s投影到垂直弦平面）%s，与世界%s差 %.1f°" % (
            "正前" if options["convex"] == "front" else "正后",
            _fmt(convex_in_plane),
            "正前" if options["convex"] == "front" else "正后",
            common.angle_between(convex_in_plane, convex_direction)))
        if pole_in_plane is not None:
            print("  极向量方向（同上投影）%s，与凸侧差 %.1f°" % (
                _fmt(pole_in_plane), common.angle_between(pole_in_plane, convex_in_plane)))
        for row in rows:
            print("    pole_angle %6.1f°  中间关节偏移 %.5f（%.2f%%）  与凸侧 %s°  与极向量 %s°  末端误差 %.5f" % (
                row["pole_angle_deg"], row["elbow_offset"], row["offset_ratio_percent"],
                ("%5.1f" % row["angle_to_back_deg"]) if row["angle_to_back_deg"] is not None else "  n/a",
                ("%5.1f" % row["angle_to_pole_deg"]) if row["angle_to_pole_deg"] is not None else "  n/a",
                row["wrist_error"]))
        print("  最佳（朝凸侧）：pole_angle=%s°（与凸侧 %s°）  解算结果 %d 种/共 %d 档" % (
            best["pole_angle_deg"], best["angle_to_back_deg"], distinct, len(rows)))
        aligned = [row["pole_angle_deg"] for row in rows
                   if row["angle_to_pole_deg"] is not None and row["angle_to_pole_deg"] < 5.0
                   and row["offset_ratio_percent"] > 0.5]
        print("  中间关节朝极向量（<5°）且不塌的档位：%s" % (aligned or "无"))
        all_results.append({"target": list(actual_target), "back_in_plane": list(convex_in_plane),
                            "pole_in_plane": list(pole_in_plane) if pole_in_plane else None,
                            "rows": rows, "best": best})

    if options["json"]:
        with open(options["json"], "w", encoding="utf-8") as handle:
            json.dump({"file": options["file"], "owner": owner_name, "root": root_name,
                       "pole_target": pole_object.name if pole_object else None,
                       "results": all_results}, handle, ensure_ascii=False, indent=1)
        print("json: %s" % options["json"])


if __name__ == "__main__":
    main()
