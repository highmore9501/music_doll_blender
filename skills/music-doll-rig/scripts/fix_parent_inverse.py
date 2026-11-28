# -*- coding: utf-8 -*-
"""修正一批 .blend 里"保留变换地挂父级"留下的非单位 matrix_parent_inverse。

做法（与 SKILL.md「父子关系：只能无逆地挂」一致）：
    matrix_parent_inverse 归零，basis 换成 PI × basis
因为 世界 = 父级 × PI × basis = 父级 × (PI × basis)，所以每个物体的世界变换**一点不变**，
但写进 location / rotation 的数字从"世界值"变回真正的局部值 —— 导出到 Unreal 才是对的。

自带 location / rotation 动画的物体：默认**不碰**（关键帧还停在旧空间，改 basis 会让动作跳掉，
要另起 --animate 才会连关键帧一起换算；换算后关键帧之间的插值会有毫米级偏差，重要动画建议重烘）。
把 --animate 打开时，每条曲线每个键的值按 PI 换算、手柄跟着平移；Curve 不要调 fcurve.update()，
Blender 5.0 在对 slotted action 连续 update 时会崩（实测访问越界）。

不能动的情况（跳过 + 报告）：
  * 父级非均匀缩放、PI × basis 分解成 loc/rot/scale 会走样（剪切）；
  * 物体自带约束、动作被别的物体共用、有 NLA、曲线带修改器、缩放本身有动画、有 delta 变换、库链接。

改之前会把原文件备份到 --backup-dir（默认文件旁边 _parent_fix_backup/，按相对路径镜像）。

用法：
    blender -b --factory-startup -P fix_parent_inverse.py -- <目录或文件...> \
        [--json out.json] [--dry-run] [--animate] [--no-backup] [--backup-dir DIR]

先跑 check_parent_inverse.py 看清楚，再跑这个。
"""
import json
import math
import os
import shutil
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

IDENTITY = Matrix.Identity(4)
PI_SKIP_EPSILON = 1e-4
SCALE_TOLERANCE = 1e-3
PHYSICAL_TOLERANCE = 1e-4       # 0.1 毫米（米）
ROTATION_TOLERANCE_DEG = 0.02


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {"paths": [], "json": None, "dry_run": False,
               "backup": True, "backup_dir": None, "animate": False}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("--json", "--backup-dir") and index + 1 < len(argv):
            options[token[2:].replace("-", "_")] = argv[index + 1]
            index += 2
            continue
        if token == "--dry-run":
            options["dry_run"] = True
            index += 1
            continue
        if token == "--animate":
            options["animate"] = True
            index += 1
            continue
        if token == "--no-backup":
            options["backup"] = False
            index += 1
            continue
        options["paths"].append(token)
        index += 1
    return options


def expand(paths):
    files = []
    for path in paths:
        if os.path.isdir(path):
            for root, _dirs, names in os.walk(path):
                if "_parent_fix_backup" in root:
                    continue
                for name in sorted(names):
                    if name.lower().endswith(".blend"):
                        files.append(os.path.join(root, name))
        else:
            files.append(path)
    return files


def matrix_deviation(matrix):
    return max(abs(matrix[row][column] - IDENTITY[row][column])
               for row in range(4) for column in range(4))


def rotation_degrees(matrix):
    quaternion = matrix.to_quaternion()
    angle = math.degrees(quaternion.angle)
    return min(angle, 360.0 - angle)


def scale_error(engine_world, world):
    left = engine_world.to_scale()
    right = world.to_scale()
    return max(abs(left[index] / right[index] - 1.0) if right[index] else 0.0
               for index in range(3))


def action_fcurves(action):
    try:
        return list(action.fcurves)
    except AttributeError:
        pass
    curves = []
    try:
        for layer in action.layers:
            for strip in layer.strips:
                try:
                    bags = list(strip.channelbags)
                except AttributeError:
                    bags = []
                    for slot in action.slots:
                        bag = strip.channelbag(slot)
                        if bag is not None:
                            bags.append(bag)
                for bag in bags:
                    curves.extend(bag.fcurves)
    except Exception:  # noqa: BLE001
        pass
    return curves


def transform_curves(obj):
    """把物体自己身上驱动 location / rotation 的曲线按数组下标分好。"""
    groups = {"location": {}, "rotation_quaternion": {}, "rotation_euler": {},
              "rotation_axis_angle": {}, "scale": {}}
    if obj.animation_data is None or obj.animation_data.action is None:
        return groups
    for fcurve in action_fcurves(obj.animation_data.action):
        base = fcurve.data_path
        for key in groups:
            if base == key:
                groups[key][fcurve.array_index] = fcurve
    return groups


def curvy_frames(groups):
    frames = set()
    for group in groups.values():
        for fcurve in group.values():
            for point in fcurve.keyframe_points:
                frames.add(round(point.co[0], 6))
    return sorted(frames)


def sample_transform(curves, frame, rotation_mode):
    location = Vector((0.0, 0.0, 0.0))
    for axis in range(3):
        curve = curves["location"].get(axis)
        location[axis] = curve.evaluate(frame) if curve is not None else 0.0
    rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
    if curves["rotation_quaternion"]:
        components = []
        for axis in range(4):
            curve = curves["rotation_quaternion"].get(axis)
            components.append(curve.evaluate(frame) if curve is not None else
                              (1.0 if axis == 0 else 0.0))
        rotation = Quaternion(components)
    elif curves["rotation_euler"]:
        from mathutils import Euler
        angles = []
        for axis in range(3):
            curve = curves["rotation_euler"].get(axis)
            angles.append(curve.evaluate(frame) if curve is not None else 0.0)
        rotation = Euler(angles, rotation_mode).to_quaternion()
    scale = Vector((1.0, 1.0, 1.0))
    return location, rotation, scale



def snapshot_curve_values(groups):
    snapshot = []
    for group in groups.values():
        for fcurve in group.values():
            for point in fcurve.keyframe_points:
                snapshot.append((point, tuple(point.co), tuple(point.handle_left),
                                 tuple(point.handle_right)))
    return snapshot


def restore_curve_values(snapshot):
    for point, co, handle_left, handle_right in snapshot:
        point.co = co
        point.handle_left = handle_left
        point.handle_right = handle_right


def convert_animation(obj, parent_inverse, tolerance, rotation_mode):
    """把 location / rotation 曲线换算到"parent inverse 归零"之后的空间。

    返回 (ok, detail)。不 ok 时调用方负责回滚。
    """
    groups = transform_curves(obj)
    if not any(groups[key] for key in ("location", "rotation_quaternion",
                                       "rotation_euler", "rotation_axis_angle")):
        return True, "无动画"
    if groups["scale"]:
        return False, "缩放自带动画，没法只换位置/旋转"
    if obj.delta_location.length > 1e-9 or rotation_degrees(obj.delta_rotation_euler.to_matrix().to_4x4()) > 0.01:
        return False, "有 delta 变换"
    animation = obj.animation_data
    if animation.nla_tracks:
        return False, "有 NLA 轨道"
    object_users = [other for other in bpy.data.objects
                    if other.animation_data is not None
                    and other.animation_data.action is animation.action]
    if len(object_users) > 1:
        return False, "动作被多个物体共用（%s）" % "、".join(
            other.name for other in object_users[:4])
    for group in groups.values():
        for fcurve in group.values():
            if fcurve.modifiers:
                return False, "曲线带修改器"

    frames = curvy_frames(groups)
    if not frames:
        return True, "无关键帧"
    targets = {}
    for frame in frames:
        location, rotation, scale = sample_transform(groups, frame, rotation_mode)
        new_matrix = parent_inverse @ Matrix.LocRotScale(location, rotation, scale)
        new_location, new_rotation, _new_scale = new_matrix.decompose()
        if new_rotation.dot(rotation) < 0.0:
            new_rotation.negate()
        targets[frame] = (new_location, new_rotation)

    # 逐曲线、逐关键帧：整体平移到新值（手柄跟着平移，保持曲线形状）
    for path, group in groups.items():
        for axis, fcurve in group.items():
            for point in fcurve.keyframe_points:
                frame = round(point.co[0], 6)
                target = targets.get(frame)
                if target is None:
                    continue
                if path == "location":
                    new_value = target[0][axis]
                elif path == "rotation_quaternion":
                    new_value = target[1][axis]
                elif path == "rotation_euler":
                    new_value = target[1].to_euler(rotation_mode)[axis]
                else:
                    continue
                delta = new_value - point.co[1]
                point.co[1] = new_value
                point.handle_left[1] += delta
                point.handle_right[1] += delta
    return True, "%d 帧关键帧已换算" % len(frames)


def object_depth(obj):
    depth = 0
    node = obj.parent
    while node is not None:
        depth += 1
        node = node.parent
    return depth


def is_control_like(obj):
    name = obj.name
    if name.endswith("_test"):
        return True
    for prefix in ("H_L", "H_R", "HP_", "F_L", "F_R", "FP_", "I_", "M_",
                   "R_", "P_", "T_", "pole_", "ext_", "stick_",
                   "controller_root", "Head_Control", "Look_At",
                   "Middle_Hand", "Mid_Hand"):
        if name.startswith(prefix):
            return True
    for collection in obj.users_collection:
        if "controller" in collection.name.lower():
            return True
    return False



def process_file(path, options):
    try:
        bpy.ops.wm.open_mainfile(filepath=path)
    except Exception as error:  # noqa: BLE001
        return {"file": path, "error": str(error)[:200], "fixed": [], "skipped": []}
    bpy.context.view_layer.update()

    unit_scale = bpy.context.scene.unit_settings.scale_length or 1.0
    tolerance = PHYSICAL_TOLERANCE / unit_scale

    fixed = []
    skipped = []
    candidates = []
    for obj in bpy.data.objects:
        if obj.parent is None or obj.parent_type != 'OBJECT':
            continue
        deviation = matrix_deviation(obj.matrix_parent_inverse)
        if deviation <= PI_SKIP_EPSILON:
            continue
        parent_world = obj.parent.matrix_world
        engine_world = parent_world @ obj.matrix_basis
        location_error = (engine_world.translation - obj.matrix_world.translation).length
        rotation_error = rotation_degrees(engine_world @ obj.matrix_world.inverted())
        scale_delta = scale_error(engine_world, obj.matrix_world)
        record = {
            "object": obj.name,
            "parent": obj.parent.name,
            "parent_rotation_deg": round(rotation_degrees(parent_world), 2),
            "parent_inverse_deviation": round(deviation, 6),
            "location_error": round(location_error, 6),
            "rotation_error_deg": round(rotation_error, 3),
            "scale_error": round(scale_delta, 6),
            "control": is_control_like(obj),
        }
        if obj.library is not None:
            record["reason"] = "库链接，改不动"
            skipped.append(record)
            continue
        if obj.constraints:
            record["reason"] = "自带约束（%s）" % ",".join(
                constraint.type for constraint in obj.constraints)
            skipped.append(record)
            continue
        groups = transform_curves(obj)
        animated = any(groups[key] for key in ("location", "rotation_quaternion",
                                               "rotation_euler", "rotation_axis_angle"))
        if not animated and location_error <= tolerance \
                and rotation_error <= ROTATION_TOLERANCE_DEG and scale_delta <= SCALE_TOLERANCE:
            record["reason"] = "偏差在噪声量级"
            skipped.append(record)
            continue
        if animated:
            record["animated"] = True
            if not options.get("animate"):
                record["reason"] = "自带位置/旋转动画（关键帧还是旧空间的数，改 basis 会让动作跳掉）"
                skipped.append(record)
                continue
        candidates.append((object_depth(obj), obj, record, groups))

    candidates.sort(key=lambda item: item[0])
    print("[fix] %s: 候选 %d 个" % (os.path.basename(path), len(candidates)), flush=True)
    for _depth, obj, record, groups in candidates:

        old_inverse = obj.matrix_parent_inverse.copy()
        old_basis = obj.matrix_basis.copy()
        curve_snapshot = snapshot_curve_values(groups) if record.get("animated") else None


        target_basis = old_inverse @ old_basis
        obj.matrix_parent_inverse.identity()
        obj.matrix_basis = target_basis

        ok = True
        detail = ""
        if matrix_deviation(obj.matrix_parent_inverse) > PI_SKIP_EPSILON:
            ok = False
            detail = "parent inverse 没清干净"
        if ok and (obj.matrix_basis.translation - target_basis.translation).length > tolerance:
            ok = False
            detail = "basis 分解走样"
        if ok and record.get("animated"):
            converted, detail = convert_animation(obj, old_inverse, tolerance,
                                                  obj.rotation_mode)
            if not converted:
                ok = False
            else:
                record["animation_note"] = detail

        if not ok:
            obj.matrix_parent_inverse = old_inverse
            obj.matrix_basis = old_basis
            if curve_snapshot:
                restore_curve_values(curve_snapshot)
            bpy.context.view_layer.update()
            record["reason"] = "改不动：%s" % detail
            skipped.append(record)
            continue
        fixed.append(record)

    saved = False
    if fixed and not options["dry_run"]:
        if options["backup"]:
            backup_root = options["backup_dir"] or os.path.join(
                os.path.dirname(path), "_parent_fix_backup")
            relative = path.replace(":", "").lstrip("\\/")
            backup_path = os.path.join(backup_root, relative)
            if not os.path.exists(backup_path):
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                shutil.copy2(path, backup_path)
        try:
            bpy.ops.wm.save_mainfile()
            saved = True
        except Exception as error:  # noqa: BLE001
            return {"file": path, "error": "保存失败：%s" % str(error)[:200],
                    "fixed": fixed, "skipped": skipped}

    return {
        "file": path,
        "unit_scale": round(unit_scale, 4),
        "fixed": fixed,
        "skipped": skipped,
        "saved": saved,
    }


def main():
    options = parse_args()
    files = expand(options["paths"])
    results = [process_file(path, options) for path in files]
    payload = {
        "files": len(results),
        "files_changed": len([item for item in results if item.get("fixed")]),
        "total_fixed": sum(len(item.get("fixed") or []) for item in results),
        "total_skipped": sum(len(item.get("skipped") or []) for item in results),
        "dry_run": options["dry_run"],
        "results": results,
    }
    if options["json"]:
        with open(options["json"], "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
    print("HEADLESS " + json.dumps(
        {key: value for key, value in payload.items() if key != "results"},
        ensure_ascii=False))


if __name__ == "__main__":
    main()













