# -*- coding: utf-8 -*-
"""MusicDoll 演奏者 —— 单位与缩放预处理（改造骨骼之前的第一步，2026-11-25 作者定）。

为什么要在改骨骼之前做这一步：

  Blender 的默认单位是“1 个单位 = 1 米”。而从 MMD / 游戏拆包来的模型，数字往往只有 0.0x 量级
  （`米娅-星彩` 导入后身高 1.77 个单位）。这串数字直接进 Unreal 就会按“米”解释成 1.7 厘米的小人，
  骨骼的缩放值也不是 1.0 —— UE 导入骨架时遇到非 1 的对象缩放，会把它烘进绑定位姿，
  之后重定向 / 动画怎么都对不上。

  所以统一口径：**场景单位改成 0.01 米（1 个单位 = 1 厘米），骨骼与网格的坐标一起放大约 100 倍，
  然后应用缩放**。两者相乘后角色真实尺寸不变（还是 1.77 米），但数字变成“厘米”，
  对象缩放回到 1.0，进 UE 就是对的。

做法（每一步都为了不动形变）：

  1. 先记下当前解算后的网格顶点（世界坐标，含修改器 / 约束 / 形态键）与骨骼头尾；
  2. 把要放大的对象从父级上摘下来（保留世界位置），避免“给子物体应用缩放时父级把位移吃掉”；
  3. 每个对象自身 scale 乘上倍数 → `transform_apply(scale=True)`，几何真被写进数据里，scale 回 1.0；
  4. 按原来的父子关系挂回去，并用 `matrix_parent_inverse` 把世界位置摆回原处；
  5. 单位设置改成 0.01 米；
  6. 再解算一遍网格，逐顶点比较“新坐标 = 倍数 × 旧坐标”，并核对真实尺寸（米）没变。
     这一条是真正的验收：只要 IK / 约束在放大过程中被改变了，这里立刻会红。

已处理过的文件会记在场景自定义属性 `md_unit_scale` / `md_unit_factor` 里，重复跑会直接拒绝（`--force` 可强制）。

用法：
    & $blender -b --factory-startup -P rig_units.py -- <file.blend> --dry-run
    & $blender -b --factory-startup -P rig_units.py -- <file.blend> --out <副本.blend>
    & $blender -b --factory-startup -P rig_units.py -- <file.blend> --save
"""
import argparse
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rig_common  # noqa: E402

GEOMETRY_TYPES = {"ARMATURE", "MESH", "CURVE", "SURFACE", "META", "FONT"}

SCENE_PROP_SCALE = "md_unit_scale"
SCENE_PROP_FACTOR = "md_unit_factor"
TEXT_BLOCK_NAME = "MusicDoll_Unit_Setup"

# 逐顶点比较的容差：放大 100 倍之后 1e-3 个单位 = 10 微米，比任何真实形变差都小得多。
VERTEX_TOLERANCE = 1e-3
# 骨骼头尾比较的容差（骨架单位）。
BONE_TOLERANCE = 1e-4
# 真实尺寸（米）允许的相对误差。
SIZE_TOLERANCE_METERS = 1e-4


def _log(message):
    print("HEADLESS " + json.dumps({"log": message}, ensure_ascii=False))


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="把单位改成 0.01 米并应用骨骼 / 网格缩放")
    parser.add_argument("blend", help="要处理的 .blend")
    parser.add_argument("--out", default=None, help="另存到新文件（推荐）")
    parser.add_argument("--save", action="store_true", help="就地保存")
    parser.add_argument("--unit-scale", type=float, default=0.01, help="目标单位：1 个单位 = 多少米")
    parser.add_argument("--factor", type=float, default=100.0, help="几何放大倍数")
    parser.add_argument("--armature", default=None, help="只处理这根骨架（默认处理文件里所有骨架与网格）")
    parser.add_argument("--dry-run", action="store_true", help="只报告现状，不改文件")
    parser.add_argument("--force", action="store_true", help="已经处理过也重跑")
    parser.add_argument("--json", action="store_true", help="完整报告以 JSON 输出")
    return parser.parse_args(argv)


def _geometry_objects(armature_name=None):
    """参与放大的对象：骨架 + 网格（曲线 / 文字等也一并算，避免留一半没放）。"""
    objects = [ob for ob in bpy.data.objects if ob.type in GEOMETRY_TYPES]
    if armature_name:
        armatures = [ob for ob in objects if ob.type == "ARMATURE" and ob.name == armature_name]
        if not armatures:
            raise SystemExit(f"找不到骨架 {armature_name}")
        keep = set(armatures)
        for ob in bpy.data.objects:
            if ob.type in GEOMETRY_TYPES and ob.type != "ARMATURE" and _has_armature_ancestor(ob, armatures):
                keep.add(ob)
        objects = [ob for ob in objects if ob in keep]
    return objects


def _has_armature_ancestor(ob, armatures):
    cursor = ob
    while cursor is not None:
        if cursor in armatures:
            return True
        cursor = cursor.parent
    return False


def _update():
    bpy.context.view_layer.update()


def _world_mesh_coordinates(mesh_object):
    """解算后的网格顶点世界坐标（含修改器、约束、形态键）。"""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_object.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        return [matrix @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def _bone_world_points(armature_object):
    matrix = armature_object.matrix_world
    points = []
    for bone in armature_object.data.bones:
        points.append(matrix @ bone.head_local)
        points.append(matrix @ bone.tail_local)
    return points


def _bounds(points):
    return {
        "min": [min(point[axis] for point in points) for axis in range(3)],
        "max": [max(point[axis] for point in points) for axis in range(3)],
    }


def _snapshot(objects):
    """记录解算后的几何与结构计数，用来核对“放大只改数值、不改形变”。"""
    _update()
    snapshot = {"meshes": {}, "bones": {}, "counts": {}}
    for ob in objects:
        if ob.type == "MESH":
            snapshot["meshes"][ob.name] = _world_mesh_coordinates(ob)
            snapshot["counts"][ob.name] = {
                "verts": len(ob.data.vertices),
                "vgroups": len(ob.vertex_groups),
                "modifiers": [modifier.type for modifier in ob.modifiers],
                "shape_keys": len(ob.data.shape_keys.key_blocks) if ob.data.shape_keys else 0,
            }
        elif ob.type == "ARMATURE":
            snapshot["bones"][ob.name] = _bone_world_points(ob)
            snapshot["counts"][ob.name] = {
                "bones": len(ob.data.bones),
                "constraints": sum(len(pose_bone.constraints) for pose_bone in ob.pose.bones),
                "deform_bones": sum(1 for bone in ob.data.bones if bone.use_deform),
            }
    return snapshot


def _detach_keep_world(ob):
    record = {
        "parent": ob.parent,
        "parent_type": ob.parent_type,
        "matrix_world": ob.matrix_world.copy(),
    }
    ob.parent = None
    ob.matrix_world = record["matrix_world"]
    return record


def _restore_parent(ob, record):
    """挂回原来的父级，并保持“应用缩放之后”的世界矩阵。

    注意：这里**不能**把世界矩阵写成“倍数 × 原世界矩阵” —— 倍数已经写进几何数据里了，
    对象自己的缩放现在必须是 1.0；再乘一次就是放大 10000 倍。

    parent inverse 必须归零：写成父级世界矩阵的逆时两者互相抵消，`location` 里存下的
    就是世界值，换到父级带旋转 / 缩放的引擎场景里会再乘一遍（见 SKILL.md
    「父子关系：只能无逆地挂」）。归零之后写回世界矩阵，得到的本地值才是真局部值。
    """
    parent = record["parent"]
    if parent is None:
        return
    world_after_apply = ob.matrix_world.copy()
    ob.parent = parent
    ob.parent_type = record["parent_type"]
    ob.matrix_parent_inverse.identity()
    ob.matrix_world = world_after_apply


def _apply_scale(objects, factor):
    """放大并应用：几何写进数据，对象缩放回 1.0。"""
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    hidden = {}
    for ob in objects:
        hidden[ob.name] = (ob.hide_viewport, ob.hide_get())
        ob.hide_viewport = False
        ob.hide_set(False)

    records = {}
    for ob in objects:
        records[ob.name] = _detach_keep_world(ob)

    for ob in objects:
        ob.scale = tuple(component * factor for component in ob.scale)
    _update()

    bpy.ops.object.select_all(action="DESELECT")
    for ob in objects:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    for ob in objects:
        _restore_parent(ob, records[ob.name])
        hide_viewport, hidden_get = hidden[ob.name]
        ob.hide_viewport = hide_viewport
        ob.hide_set(hidden_get)
    _update()
    return records


def _objects_report(objects):
    report = []
    for ob in objects:
        report.append({
            "name": ob.name,
            "type": ob.type,
            "parent": ob.parent.name if ob.parent else None,
            "scale": [round(value, 6) for value in ob.scale],
            "dimensions": [round(value, 4) for value in ob.dimensions],
        })
    return report


def _write_text_block(args, before, after, factor):
    lines = [
        "MusicDoll 单位与缩放预处理（改骨骼之前的第一步）",
        "",
        f"文件：{os.path.basename(args.blend)}",
        f"单位：1 个 Blender 单位 = {args.unit_scale:g} 米（原来是 {before['unit_scale']:g} 米）",
        f"几何放大：×{factor:g}，骨骼与网格的缩放值已应用回 1.0",
        f"真实尺寸：改前 {before['height_meters']:.4f} 米 → 改后 {after['height_meters']:.4f} 米",
        "逐顶点核对：新坐标 = 倍数 × 旧坐标（见 rig_units.py 的输出）",
        "",
        "为什么这么做：数字按“厘米”记、对象缩放回 1.0，进 Unreal 才是正确尺寸，",
        "骨架导入也不会把非 1 的缩放烘进绑定位姿。",
    ]
    text = bpy.data.texts.get(TEXT_BLOCK_NAME) or bpy.data.texts.new(TEXT_BLOCK_NAME)
    text.clear()
    text.write("\n".join(lines) + "\n")


def _summarize(objects, unit_scale):
    points = []
    for ob in objects:
        if ob.type == "MESH":
            points.extend(_world_mesh_coordinates(ob))
        elif ob.type == "ARMATURE":
            points.extend(_bone_world_points(ob))
    if not points:
        return {"height_meters": 0.0, "bounds": {"min": [0, 0, 0], "max": [0, 0, 0]}}
    bounds = _bounds(points)
    height = bounds["max"][2] - bounds["min"][2]
    return {
        "height_meters": height * unit_scale,
        "bounds": {key: [round(value, 4) for value in values] for key, values in bounds.items()},
    }


def _compare(snapshot_before, snapshot_after, factor):
    checks = {}

    vertex_worst = 0.0
    vertex_count = 0
    for name, before_points in snapshot_before["meshes"].items():
        after_points = snapshot_after["meshes"].get(name)
        if after_points is None or len(after_points) != len(before_points):
            checks[f"网格 {name} 顶点数"] = {"ok": False, "detail": "顶点数变了"}
            continue
        for old_point, new_point in zip(before_points, after_points):
            deviation = (new_point - old_point * factor).length
            if deviation > vertex_worst:
                vertex_worst = deviation
            vertex_count += 1
    checks["网格逐顶点：新坐标 = 倍数 × 旧坐标"] = {
        "ok": vertex_worst <= VERTEX_TOLERANCE,
        "worst": round(vertex_worst, 6),
        "tolerance": VERTEX_TOLERANCE,
        "vertices": vertex_count,
    }

    bone_worst = 0.0
    for name, before_points in snapshot_before["bones"].items():
        after_points = snapshot_after["bones"].get(name, [])
        if len(after_points) != len(before_points):
            checks[f"骨架 {name} 骨骼数"] = {"ok": False, "detail": "骨骼数变了"}
            continue
        for old_point, new_point in zip(before_points, after_points):
            deviation = (new_point - old_point * factor).length
            if deviation > bone_worst:
                bone_worst = deviation
    checks["骨骼头尾：新位置 = 倍数 × 旧位置"] = {
        "ok": bone_worst <= BONE_TOLERANCE * max(factor, 1.0),
        "worst": round(bone_worst, 6),
    }

    for name, before_counts in snapshot_before["counts"].items():
        after_counts = snapshot_after["counts"].get(name, {})
        checks[f"结构计数 {name}"] = {"ok": before_counts == after_counts, "before": before_counts, "after": after_counts}

    return checks


def main():
    args = _parse_args()
    opened, warning = rig_common.open_mainfile_tolerant(args.blend)
    if not opened:
        raise SystemExit(f"打不开 {args.blend}：{warning}")

    scene = bpy.context.scene
    scene_snapshot = {
        "unit_system": scene.unit_settings.system,
        "unit_scale": scene.unit_settings.scale_length,
        "length_unit": scene.unit_settings.length_unit,
    }
    objects = _geometry_objects(args.armature)
    before = {**scene_snapshot, **_summarize(objects, scene.unit_settings.scale_length)}

    already_scale = scene.get(SCENE_PROP_SCALE)
    already_factor = scene.get(SCENE_PROP_FACTOR)
    report = {
        "file": args.blend,
        "warning": warning,
        "before": before,
        "objects_before": _objects_report(objects),
        "already_applied": {"unit_scale": already_scale, "factor": already_factor},
        "dry_run": args.dry_run,
    }
    _log(f"改前：单位 {scene.unit_settings.scale_length:g} 米，身高 {before['height_meters']:.4f} 米")

    if args.dry_run:
        print("HEADLESS " + json.dumps(report, ensure_ascii=False, indent=1))
        return

    if already_scale is not None and not args.force:
        report["skipped"] = f"这个文件已经处理过（{SCENE_PROP_SCALE}={already_scale}），要重跑加 --force"
        print("HEADLESS " + json.dumps(report, ensure_ascii=False, indent=1))
        return

    snapshot_before = _snapshot(objects)
    _apply_scale(objects, args.factor)

    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = args.unit_scale
    scene.unit_settings.length_unit = "CENTIMETERS"
    scene[SCENE_PROP_SCALE] = args.unit_scale
    scene[SCENE_PROP_FACTOR] = args.factor
    _update()

    after = {**_summarize(objects, scene.unit_settings.scale_length)}
    snapshot_after = _snapshot(objects)
    report["after"] = after
    report["objects_after"] = _objects_report(objects)
    report["checks"] = _compare(snapshot_before, snapshot_after, args.factor)

    scales_ok = all(
        max(abs(component - 1.0) for component in ob.scale) <= 1e-6 for ob in objects
    )
    report["checks"]["对象缩放全部回到 1.0"] = {"ok": scales_ok}
    size_delta = abs(after["height_meters"] - before["height_meters"])
    report["checks"]["真实尺寸不变（米）"] = {
        "ok": size_delta <= SIZE_TOLERANCE_METERS,
        "before": round(before["height_meters"], 6),
        "after": round(after["height_meters"], 6),
    }
    report["failed"] = [name for name, check in report["checks"].items() if not check.get("ok")]

    _write_text_block(args, before, after, args.factor)

    target = args.out or (args.blend if args.save else None)
    if target:
        if not args.save and os.path.abspath(target) == os.path.abspath(args.blend):
            target = args.blend
        filepath = os.path.abspath(target)
        try:
            bpy.ops.wm.save_as_mainfile(filepath=filepath)
        except RuntimeError as error:
            if not os.path.exists(filepath):
                raise
            _log(f"保存时报错但文件已写出：{str(error).splitlines()[0][:160]}")
        report["saved"] = {"path": filepath, "exists": os.path.exists(filepath), "size": os.path.getsize(filepath)}

    print("HEADLESS " + json.dumps(report, ensure_ascii=False, indent=1))
    if report["failed"]:
        raise SystemExit(f"有 {len(report['failed'])} 项核对没通过：{report['failed']}")


main()
