"""只读取一遍场景：这个模型能导出成哪些 fbx、每个部件的真实父级是什么。

    blender -b --factory-startup -P fbx_analyze.py -- <模型.blend> [--out 目录]

不改文件、不写 fbx；只打印表格 + 在 --out 目录里落一份 plan.json（fbx_export.py 会用同一套判定重算）。
任何一条闸门不过就以非 0 退出——闸门的意思是「人要先手动改好」，脚本不替你改。
"""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fbx_common


def format_mm(value):
    return "—" if value is None else f"{value:.3f}mm"


def main():
    options = fbx_common.parse_arguments()
    fbx_common.open_blend(options)
    scene = bpy.context.scene

    plan = fbx_common.build_plan(scene, options)

    print("")
    print(f"源文件：{plan['source_blend']}")
    print(
        f"Blender {plan['blender_version']} · 帧 {plan['frame']}"
        f" · 单位 {plan['unit']['system']} {plan['unit']['scale_length']:.4f}"
        f"（1 单位 = {plan['unit']['millimetres_per_unit']:.1f} mm）"
    )

    print("")
    print("== 闸门 ==")
    fbx_common.print_table(
        ["结果", "检查项", "现场"],
        [
            ["PASS" if gate["ok"] else "FAIL", gate["id"], gate["detail"]]
            for gate in plan["gates"]
        ],
    )
    for gate in plan["gates"]:
        if not gate["ok"]:
            print(f"  ! {gate['id']}：{gate['fix']}")

    print("")
    print(f"== 要导出的 fbx（{len(plan['units'])} 个）==")
    rows = []
    for unit in plan["units"]:
        mesh_records = unit["meshes"]
        vertex_total = sum(record["vertices"] for record in mesh_records)
        shape_key_total = sum(len(record["shape_keys"]) for record in mesh_records)
        parent = unit["parent"]
        if parent["type"] == "armature":
            parent_text = "骨骼网格（连骨架）"
        elif parent["type"] == "bone":
            parent_text = f"绑骨 {parent['bone']}"
        else:
            parent_text = "世界原点"
        kind_text = {"skeletal": "骨骼网格", "morph": "带形态键", "static": "普通"}.get(unit["kind"], unit["kind"])
        bbox = mesh_records[0]["bbox_export_space"]
        rows.append([
            unit["file"],
            kind_text,
            parent_text,
            f"{vertex_total}",
            f"{shape_key_total}",
            " ".join(f"{axis}[{bbox['min'][index]:.1f},{bbox['max'][index]:.1f}]"
                     for index, axis in enumerate(("x", "y", "z"))),
        ])
    fbx_common.print_table(["fbx", "类别", "真实父级", "顶点", "形态键", "导出空间包围盒"], rows)

    print("")
    print("== 每个部件的父级证据 ==")
    evidence_rows = []
    for unit in plan["units"]:
        for record in unit["meshes"]:
            resolution = record.get("resolution")
            stability = record.get("stability")
            if resolution is None:
                evidence_rows.append([record["object"], "骨骼网格（自带骨架）", "—", "—", "—"])
                continue
            matched = resolution["matched_ancestor"] or "—"
            evidence_rows.append([
                record["object"],
                f"{resolution['type']}" + (f" → {resolution['bone']}" if resolution["bone"] else ""),
                f"{matched}",
                format_mm(resolution["match_error_mm"]),
                (
                    "—" if stability is None
                    else f"{stability['translation_mm']:.3f}mm / {stability['rotation_deg']:.3f}° "
                         + ("稳定" if stability["ok"] else "漂移！")
                ),
            ])
    fbx_common.print_table(["部件", "判定", "重合的祖先", "重合误差", "两帧漂移"], evidence_rows)

    if plan["excluded"]:
        print("")
        print(f"== 不导出（{len(plan['excluded'])} 个）==")
        for entry in plan["excluded"]:
            print(f"  - {entry['object']}：{entry['reason']}")
        others = [
            obj.name for obj in scene.objects
            if obj.type not in {"MESH", "ARMATURE"}
        ]
        if others:
            print(f"  - 非网格/骨架一律不导：{', '.join(sorted(others)[:12])}"
                  + (" …" if len(others) > 12 else ""))

    if plan["warnings"]:
        print("")
        print("== 提醒 ==")
        for warning in plan["warnings"]:
            print(f"  · {warning}")

    if options["out"]:
        plan_path = os.path.join(options["out"], "plan.json")
        fbx_common.save_json(plan_path, plan)

    print("")
    if plan["ok"]:
        print("结论：闸门全过，可以跑 fbx_export.py。")
    else:
        print("结论：闸门未通过，脚本不会导出。先按上面的 ! 提示把文件改好。")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
