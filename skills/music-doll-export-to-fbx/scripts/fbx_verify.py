"""验收：把 fbx_export.py 导出的那批 fbx 重新导回空场景，和源文件逐项比。

    blender -b --factory-startup -P fbx_verify.py -- <模型.blend> --out <导出目录>

比的东西：

| 检查 | 判据 |
|---|---|
| 骨架 | 骨名集合一致（多一个就是叶骨骼）、每根骨的 rest 世界矩阵偏差 |
| 蒙皮 | 每个顶点的 (骨名, 权重) 和源文件一致 |
| 骨骼网格 | 顶点数、世界坐标逐顶点偏差、形态键名单、材质/贴图数 |
| 部件 | 顶点数、导出空间坐标逐顶点偏差（就是在验证「烘焙」有没有走形） |
| 部件形态键 | 每个形态键的顶点坐标偏差 |
| 杂物 | fbx 里不该出现空物体 / 灯光 / 摄像机；不该有动画 |

结果写 verify.json；任何一项不过就以非 0 退出。
"""

import os
import sys

import bpy
import numpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fbx_common


COORDINATE_TOLERANCE_UNITS = 0.01      # 1 个单位 = 1 厘米，0.01 单位 = 0.1 mm
BONE_TOLERANCE_UNITS = 0.005
WEIGHT_TOLERANCE = 0.002


def coordinates_of(mesh_data):
    values = numpy.empty(len(mesh_data.vertices) * 3, dtype=numpy.float64)
    mesh_data.vertices.foreach_get("co", values)
    return values.reshape(-1, 3)


def key_coordinates(key_block):
    values = numpy.empty(len(key_block.data) * 3, dtype=numpy.float64)
    key_block.data.foreach_get("co", values)
    return values.reshape(-1, 3)


def apply_matrix(points, matrix):
    numbers = numpy.array([list(row) for row in matrix], dtype=numpy.float64)
    rotation = numbers[:3, :3]
    translation = numbers[:3, 3]
    return points @ rotation.T + translation


def weight_map(mesh_obj, bone_names):
    group_names = {group.index: group.name for group in mesh_obj.vertex_groups}
    mapping = {}
    for vertex in mesh_obj.data.vertices:
        items = tuple(sorted(
            (group_names[item.group], round(item.weight, 4))
            for item in vertex.groups
            if item.weight > 0.0 and group_names[item.group] in bone_names
        ))
        if items:
            mapping[vertex.index] = items
    return mapping


def collect_expectations(manifest, plan_source_path):
    """从源文件里把每个部件「导出空间里的坐标」算出来，作为比对基准。

    导出空间的坐标 = 烘焙矩阵 × 网格本地坐标（烘焙矩阵对「父级是世界原点」的部件就是它的世界矩阵，
    对「父级是骨」的部件是「骨头世界矩阵的逆 × 网格世界矩阵」——后者正好把姿势约掉，留下骨骼空间坐标）。
    """
    scene = bpy.context.scene
    armature_obj = bpy.data.objects[manifest["armature"]["object"]]
    armature_obj.data.pose_position = "POSE"
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    bone_names = {bone.name for bone in armature_obj.data.bones}
    expectations = {"units": {}, "bones": {}, "bone_names": bone_names}

    for bone in armature_obj.data.bones:
        expectations["bones"][bone.name] = [
            [float(value) for value in row] for row in (armature_obj.matrix_world @ bone.matrix_local)
        ]

    for unit in manifest["units"]:
        unit_expectation = {"meshes": {}}
        for record in unit["meshes"]:
            mesh_obj = bpy.data.objects[record["object"]]
            mesh_world = mesh_obj.evaluated_get(depsgraph).matrix_world.copy()
            space_matrix = (
                fbx_common.load_bake_matrix(record["bake_matrix"])
                if "bake_matrix" in record else mesh_world
            )
            mesh_expectation = {
                "vertices": len(mesh_obj.data.vertices),
                "coordinates": apply_matrix(coordinates_of(mesh_obj.data), space_matrix),
                "shape_keys": {},
                "materials": len([slot for slot in mesh_obj.material_slots if slot.material]),
                "material_images": fbx_common.material_texture_report(mesh_obj),
                "weights": weight_map(mesh_obj, bone_names) if unit["kind"] == "skeletal" else None,
            }
            if mesh_obj.data.shape_keys:
                for key_block in mesh_obj.data.shape_keys.key_blocks:
                    mesh_expectation["shape_keys"][key_block.name] = apply_matrix(
                        key_coordinates(key_block), space_matrix
                    )
            unit_expectation["meshes"][record["object"]] = mesh_expectation
        expectations["units"][unit["file"]] = unit_expectation
    return expectations


def import_fbx(path, scale):
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path, global_scale=scale, ignore_leaf_bones=False)
    bpy.context.view_layer.update()


def check_unit(unit, expectation, scale, context):
    path = unit["path"]
    import_fbx(path, scale)
    checks = []

    extra_types = sorted({
        obj.type for obj in bpy.data.objects if obj.type not in {"MESH", "ARMATURE"}
    })
    checks.append({
        "check": "没有空物体/灯光/摄像机",
        "ok": not extra_types,
        "detail": "干净" if not extra_types else f"多出 {extra_types}",
    })
    checks.append({
        "check": "没有动画",
        "ok": not bpy.data.actions,
        "detail": f"actions={len(bpy.data.actions)}",
    })

    imported_meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    imported_armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    expected_names = set(expectation["meshes"].keys())
    imported_names = {obj.name for obj in imported_meshes}
    checks.append({
        "check": "网格对象名",
        "ok": expected_names == imported_names,
        "detail": f"源 {sorted(expected_names)} / 导入 {sorted(imported_names)}",
    })

    if unit.get("root_bone"):
        if not imported_armatures:
            checks.append({
                "check": "根骨骨架",
                "ok": False,
                "detail": "fbx 里没有骨架 —— UE 会把它当静态网格导入，形态键会丢",
            })
        else:
            root_armature = imported_armatures[0]
            imported_bone_names = sorted(bone.name for bone in root_armature.data.bones)
            checks.append({
                "check": "根骨骨架（应该只有一根骨头）",
                "ok": imported_bone_names == [unit["root_bone"]],
                "detail": f"期望 [{unit['root_bone']}] / 导入 {imported_bone_names}",
            })

    if unit.get("armature"):
        if not imported_armatures:
            checks.append({"check": "骨架存在", "ok": False, "detail": "fbx 里没有骨架"})
        else:
            imported_armature = imported_armatures[0]
            imported_bone_names = {bone.name for bone in imported_armature.data.bones}
            missing = sorted(context["source_bone_names"] - imported_bone_names)
            extra = sorted(imported_bone_names - context["source_bone_names"])
            checks.append({
                "check": "骨名集合（多出来的就是叶骨骼）",
                "ok": not missing and not extra,
                "detail": f"{len(imported_bone_names)} 根；缺 {missing[:6]}；多 {extra[:6]}",
            })
            worst_bone = 0.0
            worst_bone_name = ""
            for bone_name, expected_matrix in context["source_bone_matrices"].items():
                if bone_name not in imported_bone_names:
                    continue
                imported_matrix = (
                    imported_armature.matrix_world @ imported_armature.data.bones[bone_name].matrix_local
                )
                deviation = max(
                    abs(imported_matrix[row][column] - expected_matrix[row][column])
                    for row in range(4) for column in range(4)
                )
                if deviation > worst_bone:
                    worst_bone = deviation
                    worst_bone_name = bone_name
            checks.append({
                "check": "骨骼 rest 矩阵",
                "ok": worst_bone <= BONE_TOLERANCE_UNITS,
                "detail": f"最大偏差 {worst_bone * 1000:.4f} mm（{worst_bone_name}）",
            })

    for object_name, mesh_expectation in expectation["meshes"].items():
        imported_mesh = next((obj for obj in imported_meshes if obj.name == object_name), None)
        if imported_mesh is None:
            checks.append({"check": f"{object_name} 存在", "ok": False, "detail": "没导进来"})
            continue
        imported_world = imported_mesh.matrix_world
        checks.append({
            "check": f"{object_name} 物体变换",
            "ok": fbx_common.is_identity(imported_world, tolerance=1e-4),
            "detail": f"位移 {[round(value, 4) for value in imported_world.translation]}",
        })
        checks.append({
            "check": f"{object_name} 顶点数",
            "ok": len(imported_mesh.data.vertices) == mesh_expectation["vertices"],
            "detail": f"源 {mesh_expectation['vertices']} / 导入 {len(imported_mesh.data.vertices)}",
        })
        if len(imported_mesh.data.vertices) == mesh_expectation["vertices"]:
            actual = apply_matrix(coordinates_of(imported_mesh.data), imported_world)
            deviation = numpy.abs(actual - mesh_expectation["coordinates"]).max()
            checks.append({
                "check": f"{object_name} 逐顶点坐标",
                "ok": deviation <= COORDINATE_TOLERANCE_UNITS,
                "detail": f"最大偏差 {deviation * 1000:.5f} mm",
            })

        imported_key_names = (
            [key.name for key in imported_mesh.data.shape_keys.key_blocks]
            if imported_mesh.data.shape_keys else []
        )
        checks.append({
            "check": f"{object_name} 形态键名单",
            "ok": imported_key_names == list(mesh_expectation["shape_keys"].keys()),
            "detail": f"源 {len(mesh_expectation['shape_keys'])} 个 / 导入 {len(imported_key_names)} 个",
        })
        for key_name, expected_coordinates in mesh_expectation["shape_keys"].items():
            key_block = (
                imported_mesh.data.shape_keys.key_blocks.get(key_name)
                if imported_mesh.data.shape_keys else None
            )
            if key_block is None:
                continue
            actual = apply_matrix(key_coordinates(key_block), imported_world)
            deviation = numpy.abs(actual - expected_coordinates).max()
            checks.append({
                "check": f"{object_name} / 形态键 {key_name}",
                "ok": deviation <= COORDINATE_TOLERANCE_UNITS,
                "detail": f"最大偏差 {deviation * 1000:.5f} mm",
            })

        imported_materials = len([slot for slot in imported_mesh.material_slots if slot.material])
        checks.append({
            "check": f"{object_name} 材质数",
            "ok": imported_materials == mesh_expectation["materials"],
            "detail": f"源 {mesh_expectation['materials']} / 导入 {imported_materials}",
        })
        if mesh_expectation["material_images"]:
            imported_material_names = {
                slot.material.name: slot.material
                for slot in imported_mesh.material_slots if slot.material
            }
            lost_exportable = []
            not_exportable = []
            for material_name, source_texture in mesh_expectation["material_images"].items():
                material = imported_material_names.get(material_name)
                has_texture = False
                if material is not None and material.use_nodes:
                    has_texture = any(
                        getattr(node, "image", None) is not None for node in material.node_tree.nodes
                    )
                if has_texture:
                    continue
                if source_texture["exportable"]:
                    lost_exportable.append(material_name)
                else:
                    not_exportable.append(material_name)
            checks.append({
                "check": f"{object_name} 贴图（标准材质）",
                "ok": not lost_exportable,
                "detail": (
                    f"{len(mesh_expectation['material_images']) - len(not_exportable)} 个标准材质的贴图都在"
                    + (f"；丢了：{'，'.join(lost_exportable[:6])}" if lost_exportable else "")
                ),
            })
            if not_exportable:
                checks.append({
                    "check": f"{object_name} 贴图（toon 材质，仅供参考）",
                    "ok": True,
                    "detail": (
                        f"{len(not_exportable)} 个材质用 mmd_tools 的 toon 节点，FBX 本来就带不走它们的贴图"
                        f"（{'，'.join(not_exportable[:6])} …）"
                    ),
                })

        if unit.get("root_bone"):
            root_weights = weight_map(imported_mesh, {unit["root_bone"]})
            unweighted = [
                vertex.index for vertex in imported_mesh.data.vertices
                if vertex.index not in root_weights
            ]
            lightest = min(
                (weight for items in root_weights.values() for _, weight in items),
                default=0.0,
            )
            checks.append({
                "check": f"{object_name} 根骨蒙皮",
                "ok": not unweighted and lightest >= 1.0 - WEIGHT_TOLERANCE,
                "detail": (
                    f"{len(root_weights)}/{len(imported_mesh.data.vertices)} 个顶点有权重；"
                    f"没蒙到的 {len(unweighted)} 个；最小权重 {lightest:.5f}"
                ),
            })

        if mesh_expectation["weights"] is not None:
            imported_weights = weight_map(imported_mesh, context["source_bone_names"])
            missing_vertices = [
                index for index in mesh_expectation["weights"] if index not in imported_weights
            ]
            worst_weight = 0.0
            weight_mismatch = 0
            for index, expected_items in mesh_expectation["weights"].items():
                imported_items = imported_weights.get(index, ())
                if [name for name, _ in expected_items] != [name for name, _ in imported_items]:
                    weight_mismatch += 1
                    continue
                for (_, expected_weight), (_, imported_weight) in zip(expected_items, imported_items):
                    worst_weight = max(worst_weight, abs(expected_weight - imported_weight))
            checks.append({
                "check": f"{object_name} 蒙皮权重",
                "ok": not missing_vertices and weight_mismatch == 0 and worst_weight <= WEIGHT_TOLERANCE,
                "detail": (
                    f"有骨架权重的顶点 {len(mesh_expectation['weights'])} 个；"
                    f"缺失 {len(missing_vertices)}；组不匹配 {weight_mismatch}；最大权重差 {worst_weight:.5f}"
                ),
            })

    return checks


def main():
    options = fbx_common.parse_arguments()
    fbx_common.open_blend(options)
    out_dir = options["out"]
    if not out_dir:
        raise SystemExit("要用 --out 指向 fbx_export.py 的输出目录（里面有 manifest.json）")

    manifest_path = os.path.join(out_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise SystemExit(f"找不到 {manifest_path}；先跑 fbx_export.py")

    manifest = fbx_common.load_plan(manifest_path)
    for unit in manifest["units"]:
        unit["path"] = os.path.join(out_dir, unit["file"])

    expectations = collect_expectations(manifest, options["blend"])
    scale = 1.0 / manifest["unit"]["scale_length"]

    context = {
        "source_bone_names": expectations["bone_names"],
        "source_bone_matrices": expectations["bones"],
    }

    all_checks = []
    for unit in manifest["units"]:
        print("")
        print(f"== {unit['file']}（{unit['kind']}）==")
        checks = check_unit(unit, expectations["units"][unit["file"]], scale, context)
        fbx_common.print_table(
            ["结果", "检查", "现场"],
            [["PASS" if check["ok"] else "FAIL", check["check"], check["detail"]] for check in checks],
        )
        for check in checks:
            check["ok"] = bool(check["ok"])
            check["file"] = unit["file"]
        all_checks.extend(checks)

    failed = [check for check in all_checks if not check["ok"]]
    summary = {
        "ok": not failed,
        "checks": len(all_checks),
        "failed": len(failed),
        "details": all_checks,
    }
    fbx_common.save_json(os.path.join(out_dir, "verify.json"), summary)

    print("")
    if failed:
        print(f"验收未通过：{len(failed)} 项 FAIL（见上面表格 / verify.json）")
        for check in failed:
            print(f"  - {check['file']} · {check['check']}：{check['detail']}")
        raise SystemExit(3)
    print(f"验收通过：{len(all_checks)} 项全过。")


if __name__ == "__main__":
    main()
