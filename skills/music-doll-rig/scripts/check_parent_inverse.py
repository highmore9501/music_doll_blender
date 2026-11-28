# -*- coding: utf-8 -*-
"""导出前自查：有没有"保留变换地挂父级"留下的非单位 `matrix_parent_inverse`。

为什么查这一条
--------------
Blender 算世界位置用的是

    世界 = 父级世界 × matrix_parent_inverse × 本地(location / rotation / scale)

用 `Ctrl+P` → Object (Keep Transform)，或者代码里写
`obj.matrix_parent_inverse = 父级.matrix_world.inverted()`，前两项正好互相抵消，
于是 **location / rotation 这两栏里存下来的其实是世界值**。
Blender 自己怎么读怎么算都自洽（抵消掉了），文件里看着一点问题都没有；
可导出器（`.harpist` / `.drummer` / `.animation` / 控制器的 FBX）只写 location / rotation，
引擎按"父级 × 本地"重建 —— 世界值被当成局部值又乘了一次父级，部件就飞到别处去了。

典型现场：父级是手腕（rest 朝向转 98°）时偏 1.18 m；父级带 99 倍缩放时偏 11 km。
而且只有跨引擎才暴露，Blender 里永远是对的。

两条判据（和文档「父子关系：只能无逆地挂」那一节一致）
------------------------------------------------------
1. 有父级的物体，`matrix_parent_inverse` 必须是单位阵；
2. 反向验收：父级世界 × 本地，算出来的落点必须等于场景里的实际位置。

用法：

    blender -b --factory-startup -P check_parent_inverse.py -- <file.blend> \
        [--json out.json] [--all]

    --all   连没有问题的物体也逐条列出来（默认只列有问题的）
    --json  把逐物体结果写成 JSON

退出码：只要有一处"父级世界 × 本地 ≠ 世界"（偏差超过 1e-5 或 0.01°）就返回 1 ——
这种一定是导出后会错位的，必须在导出前修掉。
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix

IDENTITY = Matrix.Identity(4)
PI_EPSILON = 1e-6
LOCATION_TOLERANCE = 1e-5
ROTATION_TOLERANCE_DEG = 0.01

CONTROL_COLLECTION_PREFIXES = (
    "Controllers", "Hand_Controllers", "Foot_Controllers", "Special_Controllers",
)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {"file": None, "json": None, "all": False}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--json" and index + 1 < len(argv):
            options["json"] = argv[index + 1]
            index += 2
            continue
        if token == "--all":
            options["all"] = True
            index += 1
            continue
        if options["file"] is None:
            options["file"] = token
        index += 1
    return options


def open_blend_file(filepath):
    try:
        bpy.ops.wm.open_mainfile(filepath=filepath)
    except Exception as error:  # noqa: BLE001
        print("[check] 打开 %s 抛了异常（文件多半已经载入）：%s" % (filepath, error))


def matrix_deviation(matrix, reference=IDENTITY):
    return max(abs(matrix[row][column] - reference[row][column])
               for row in range(4) for column in range(4))


def rotation_degrees(matrix):
    """矩阵旋转部分的角度（0~180°）。"""
    quaternion = matrix.to_quaternion()
    angle = math.degrees(quaternion.angle)
    return min(angle, 360.0 - angle)


def is_control_object(obj):
    if obj.name.endswith("_test"):
        return True
    for collection in obj.users_collection:
        for prefix in CONTROL_COLLECTION_PREFIXES:
            if collection.name.startswith(prefix):
                return True
    return False


def inspect_object(obj):
    """返回一条检查结果；没有父级 / 不是物体父级的返回 None。"""
    parent = obj.parent
    if parent is None or obj.parent_type != 'OBJECT':
        return None
    parent_world = parent.matrix_world
    basis = obj.matrix_basis
    world = obj.matrix_world
    engine_world = parent_world @ basis
    delta = engine_world @ world.inverted()
    location_error = delta.translation.length
    rotation_error = rotation_degrees(delta)
    return {
        "object": obj.name,
        "type": obj.type,
        "parent": parent.name,
        "parent_rotation_deg": round(rotation_degrees(parent_world), 3),
        "parent_scale": [round(value, 4) for value in parent_world.to_scale()],
        "parent_inverse_deviation": round(matrix_deviation(obj.matrix_parent_inverse), 6),
        "local_location": [round(value, 4) for value in basis.translation],
        "world_location": [round(value, 4) for value in world.translation],
        "engine_location": [round(value, 4) for value in engine_world.translation],
        "location_error": round(location_error, 9),
        "rotation_error_deg": round(rotation_error, 6),
        "is_control": is_control_object(obj),
        "broken": (location_error > LOCATION_TOLERANCE
                   or rotation_error > ROTATION_TOLERANCE_DEG),
    }


def print_hint():
    print("")
    print("修法（两条，别混）：")
    print("  • Blender 里：选中子物体 → Alt+P（保持变换）摘下来 → Ctrl+P → Object（不要带 Keep Transform）")
    print("    → 重新录一遍所有基准姿势（旧基准是按\"世界值冒充局部值\"记的）")
    print("  • 脚本里：obj.parent = parent → obj.matrix_parent_inverse.identity() → obj.matrix_world = 世界矩阵")


def main():
    options = parse_args()
    if not options["file"]:
        print(__doc__)
        return
    open_blend_file(options["file"])
    bpy.context.view_layer.update()

    unit_scale = bpy.context.scene.unit_settings.scale_length
    results = []
    for obj in bpy.data.objects:
        row = inspect_object(obj)
        if row is not None:
            results.append(row)

    offenders = [row for row in results if row["parent_inverse_deviation"] > PI_EPSILON]
    broken = [row for row in offenders if row["broken"]]
    control_offenders = [row for row in offenders if row["is_control"]]

    print("检查：%s" % options["file"])
    print("单位：1 个单位 = %.4g 米；有父级的物体 %d 个" % (unit_scale, len(results)))
    print("")
    header = "  %-6s %-28s %-8s %-20s %8s %-22s %-22s %10s %8s" % (
        "判定", "物体", "类型", "父级", "父级转", "本地(loc)", "世界(loc)", "偏差", "偏差°")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in (results if options["all"] else offenders):
        verdict = "BAD" if row["broken"] else ("注意" if row["parent_inverse_deviation"] > PI_EPSILON else "ok")
        print("  %-6s %-28s %-8s %-20s %7.1f° %-22s %-22s %9.6f %8.2f" % (
            verdict,
            row["object"][:28],
            row["type"],
            row["parent"][:20],
            row["parent_rotation_deg"],
            "(%.3f,%.3f,%.3f)" % tuple(row["local_location"]),
            "(%.3f,%.3f,%.3f)" % tuple(row["world_location"]),
            row["location_error"],
            row["rotation_error_deg"]))

    print("")
    print("挂了非单位 parent inverse 的物体：%d 个（其中控件 %d 个）；已经导致\"父级×本地 ≠ 世界\"：%d 个"
          % (len(offenders), len(control_offenders), len(broken)))
    if offenders:
        print_hint()

    if options["json"]:
        report_path = options["json"]
        if not os.path.isabs(report_path):
            report_path = os.path.join(os.path.dirname(options["file"]), report_path)
        with open(report_path, "w", encoding="utf-8") as report_file:
            json.dump({
                "file": options["file"],
                "unit_scale": unit_scale,
                "objects_with_parent": len(results),
                "offenders": offenders,
                "broken": broken,
                "passed": not broken,
            }, report_file, ensure_ascii=False, indent=2)
        print("报告：%s" % report_path)

    if broken:
        print("PARENT_INVERSE_RESULT FAIL %d" % len(broken))
        sys.exit(1)
    print("PARENT_INVERSE_RESULT OK")


if __name__ == "__main__":
    main()
