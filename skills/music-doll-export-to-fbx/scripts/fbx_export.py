"""把 MusicDoll 的演奏者 / 乐器 / 零配件导出成一组 fbx，并写一份装配清单。

    blender -b --factory-startup -P fbx_export.py -- <模型.blend> [--out 目录] [--dry-run]

做三件事：

1. 先跑一遍 fbx_analyze 的所有闸门（单位、骨架原点、骨骼网格变换、每个部件的真实父级）；
2. 一个部件一个 fbx：骨骼网格连骨架一起导；其余每个 mesh 复制一份、把「它的导出空间」应用进顶点再导；
3. 写 manifest.json：每个 fbx 是什么类别、要挂到世界原点还是哪根骨、顶点/形态键/材质各多少。

不修改、不保存源 .blend（所有改动只发生在内存里，进程结束就没了）。
"""

import datetime
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fbx_common


def default_out_dir(source_blend):
    stem, _ = os.path.splitext(source_blend)
    return stem + "_fbx"


def print_unit_table(plan):
    rows = []
    for unit in plan["units"]:
        parent = unit["parent"]
        if parent["type"] == "armature":
            parent_text = "骨骼网格（连骨架导出）"
        elif parent["type"] == "bone":
            parent_text = f"绑骨：{parent['bone']}（零偏移挂载）"
        elif unit.get("root_bone"):
            parent_text = f"世界原点，骨骼网格（根骨 {unit['root_bone']}）"
        else:
            parent_text = "世界原点（原地摆放）"
        rows.append([unit["file"], parent_text, str(sum(record["vertices"] for record in unit["meshes"]))])
    fbx_common.print_table(["fbx", "进 UE 之后怎么放", "顶点"], rows)


def main():
    options = fbx_common.parse_arguments()
    fbx_common.open_blend(options)
    scene = bpy.context.scene
    out_dir = options["out"] or default_out_dir(bpy.data.filepath)

    plan = fbx_common.build_plan(scene, options)
    fbx_common.print_table(
        ["结果", "检查项", "现场"],
        [["PASS" if gate["ok"] else "FAIL", gate["id"], gate["detail"]] for gate in plan["gates"]],
    )
    if not plan["ok"]:
        for gate in plan["gates"]:
            if not gate["ok"]:
                print(f"  ! {gate['id']}：{gate['fix']}")
        print("\n闸门未通过，不导出。先把上面这些改好（脚本不会替你改文件）。")
        raise SystemExit(2)

    if not plan["units"]:
        print("\n没有可导出的部件（全是控制器显示件？）。")
        raise SystemExit(2)

    print("")
    print_unit_table(plan)

    if options["dry_run"]:
        print(f"\n--dry-run：只演算，不写文件。目标目录 {out_dir}")
        return

    os.makedirs(out_dir, exist_ok=True)
    stale = sorted(
        name for name in os.listdir(out_dir)
        if name.lower().endswith(".fbx") and name not in {unit["file"] for unit in plan["units"]}
    )
    if stale:
        print(f"\n提醒：{out_dir} 里还有不属于这次的 fbx（{', '.join(stale)}），UE 导入时可能会混进来，自己清一下。")

    armature_obj = bpy.data.objects[plan["armature"]["object"]]
    millimetres = plan["unit"]["millimetres_per_unit"]

    exported = []
    bake_deviations = {}

    # 骨骼网格：骨架进 REST 再导，导出的是绑定姿势而不是当前帧的姿势
    armature_obj.data.pose_position = "REST"
    bpy.context.view_layer.update()

    for unit in plan["units"]:
        filepath = os.path.join(out_dir, unit["file"])
        if unit.get("armature"):
            meshes = [bpy.data.objects[record["object"]] for record in unit["meshes"]]
            size = fbx_common.export_objects([armature_obj] + meshes, filepath)
            print(
                f"  导出 {unit['file']}：骨架 + {len(meshes)} 个网格，"
                f"{size / 1024 / 1024:.2f} MB（rest 姿势）"
            )
        elif unit.get("root_bone"):
            record = unit["meshes"][0]
            source_obj = bpy.data.objects[record["object"]]
            bake_matrix = fbx_common.load_bake_matrix(record["bake_matrix"])
            duplicate, deviation = fbx_common.bake_duplicate(source_obj, bake_matrix)
            bake_deviations[record["object"]] = deviation
            bone_armature = None
            try:
                if deviation > fbx_common.BAKE_TOLERANCE_UNITS:
                    raise RuntimeError(
                        f"{record['object']} 烘焙自检失败：顶点偏差 {deviation * millimetres:.4f} mm"
                        f"（上限 {fbx_common.BAKE_TOLERANCE_UNITS * millimetres:.4f} mm）"
                    )
                bone_armature = fbx_common.create_root_bone_armature(unit["root_bone"])
                fbx_common.skin_to_root_bone(duplicate, bone_armature, unit["root_bone"])
                size = fbx_common.export_objects([bone_armature, duplicate], filepath)
            finally:
                fbx_common.drop_duplicate(duplicate, source_obj)
                fbx_common.remove_object(bone_armature)
            print(
                f"  导出 {unit['file']}：{record['object']} + 一根根骨 {unit['root_bone']}，"
                f"{size / 1024:.0f} KB，烘焙偏差 {deviation * millimetres:.5f} mm"
            )
        else:
            record = unit["meshes"][0]
            source_obj = bpy.data.objects[record["object"]]
            bake_matrix = fbx_common.load_bake_matrix(record["bake_matrix"])
            duplicate, deviation = fbx_common.bake_duplicate(source_obj, bake_matrix)
            bake_deviations[record["object"]] = deviation
            try:
                if deviation > fbx_common.BAKE_TOLERANCE_UNITS:
                    raise RuntimeError(
                        f"{record['object']} 烘焙自检失败：顶点偏差 {deviation * millimetres:.4f} mm"
                        f"（上限 {fbx_common.BAKE_TOLERANCE_UNITS * millimetres:.4f} mm）"
                    )
                size = fbx_common.export_objects([duplicate], filepath)
            finally:
                fbx_common.drop_duplicate(duplicate, source_obj)
            print(
                f"  导出 {unit['file']}：{record['object']}，{size / 1024:.0f} KB，"
                f"烘焙偏差 {deviation * millimetres:.5f} mm"
            )

        exported.append({
            "unit": unit,
            "path": filepath,
            "bytes": os.path.getsize(filepath),
            "sha256": fbx_common.file_digest(filepath),
        })

    armature_obj.data.pose_position = plan["armature"]["original_pose_position"]

    # ---- 装配清单 ----
    manifest = {
        "schema": fbx_common.SCHEMA,
        "source_blend": plan["source_blend"],
        "source_blend_sha256": fbx_common.file_digest(plan["source_blend"]),
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "blender_version": plan["blender_version"],
        "export_frame": plan["frame"],
        "unit": plan["unit"],
        "armature": plan["armature"],
        "export_options": {
            key: (sorted(value) if isinstance(value, set) else value)
            for key, value in fbx_common.FBX_EXPORT_OPTIONS.items()
        },
        "gates": plan["gates"],
        "warnings": plan["warnings"],
        "excluded": plan["excluded"],
        "units": [],
    }

    for entry in exported:
        unit = dict(entry["unit"])
        unit["bytes"] = entry["bytes"]
        unit["sha256"] = entry["sha256"]
        for record in unit["meshes"]:
            if record["object"] in bake_deviations:
                record["bake_deviation_mm"] = round(bake_deviations[record["object"]] * millimetres, 6)
        manifest["units"].append(unit)

    manifest["assembly"] = build_assembly_section(manifest["units"])
    fbx_common.save_json(os.path.join(out_dir, "manifest.json"), manifest)

    print("")
    print("== 装配清单 ==")
    for unit in manifest["units"]:
        parent = unit["parent"]
        if parent["type"] == "armature":
            how = "作为人物本体：SkeletalMesh，骨架就是本文件里的那一套"
        elif parent["type"] == "bone":
            how = f"挂到骨 {parent['bone']}，相对变换 = 0（顶点已经是骨骼空间的坐标）"
        elif unit.get("root_bone"):
            how = f"摆在原点，按 SkeletalMesh 导入（自带根骨 {unit['root_bone']} 与形态键）"
        else:
            how = "直接摆在原点（顶点已经是世界坐标）"
        print(f"  {unit['file']} → {how}")
    print("")
    print(f"输出目录：{out_dir}")
    print("下一步：跑 fbx_verify.py 把这批 fbx 导回 Blender 逐顶点核对。")


def build_assembly_section(units):
    """给后面「导进 UE 再拼起来」那一步看的说明（人读 + 程序读）。"""
    skeletal_files = [unit["file"] for unit in units if unit["parent"]["type"] == "armature"]
    bone_parts = [
        {"file": unit["file"], "bone": unit["parent"]["bone"], "relative_transform": "identity"}
        for unit in units if unit["parent"]["type"] == "bone"
    ]
    world_parts = [
        unit["file"] for unit in units
        if unit["parent"]["type"] == "world" and not unit.get("root_bone")
    ]
    world_skeletal_parts = [
        {"file": unit["file"], "bone": unit["root_bone"], "attach": "place_at_origin"}
        for unit in units if unit.get("root_bone")
    ]
    return {
        "skeletal_meshes": skeletal_files,
        "bone_parts": bone_parts,
        "world_parts": world_parts,
        "world_skeletal_parts": world_skeletal_parts,
        "rules": [
            "骨骼网格直接作为人物本体导入，不要额外挂父级。",
            "绑骨部件的顶点坐标已经是骨骼空间（原点在骨头、朝向是骨头的朝向），"
            "进 UE 后挂到对应骨骼并把相对变换保持为 0。",
            "世界坐标部件按原点摆放；它们本来就是场景里不动的东西（鼓台、凳子）。",
            "world_skeletal_parts 里的部件也摆原点，但必须按 SkeletalMesh 导入（它们带形态键，"
            "文件里那一根根骨只是为了让 UE 认成骨骼网格，不要拿它做动画）。",
            "FBX 里没有动画，也没有叶骨骼；单位是厘米（场景单位 0.01 米）。",
        ],
    }


if __name__ == "__main__":
    main()
