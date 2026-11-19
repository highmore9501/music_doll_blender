# -*- coding: utf-8 -*-
"""MusicDoll 骨架改造 —— 普查器（只读）。

扫描一个目录（或若干个 .blend 文件），对每个文件报告骨架形态：

- 有几套骨架、分别叫什么、各多少骨（形变 / 非形变）；
- 骨骼集合（Blender 5.0 的 bone collections）清单；
- 是不是 MMD 系（有没有 全ての親 / センター / 操作中心 这类根）；
- 影子链规模：`_dummy_` / `_shadow_` / `捩` / `D` 后缀各多少；
- 已经做过多少 MCH 主骨（`MCH_` 前缀），有没有手 / 脚 / 手指的 IK 约束；
- 指尖叶骨（`先` 结尾的末端骨）有多少；
- 手部控制器类物体（`H_x` / `F_x` / `I_x` 这类 EMPTY）有多少。

**本脚本绝不写 .blend**：只用 open_mainfile 读，不 save。

用法（Blender 无头）：

    blender -b --factory-startup -P rig_survey.py -- <目录或文件...> \
        [--out report.json] [--names]

`--names` 会把每个骨架的骨骼名清单也写进报告（做命名研究用，报告会变大）。
"""
import json
import os
import sys
import traceback

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rig_common import open_mainfile_tolerant  # noqa: E402

MMD_ROOT_NAMES = {"全ての親", "センター", "操作中心", "グルーブ", "master", "root"}
MCH_PREFIXES = ("MCH_", "MCH-", "MCH.")
SHADOW_MARKERS = ("_shadow_", "_dummy_", "shadow_", "dummy_")
TWIST_MARKERS = ("捩", "twist", "Twist")
TIP_MARKERS = ("先", "_tip", "tip", "Tip")
CONTROLLER_PREFIXES = ("H_", "F_", "I_", "T_", "P_", "M_", "R_", "HP_", "FP_", "TP_")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    targets = []
    out_path = None
    with_names = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--out":
            index += 1
            out_path = argv[index]
        elif token == "--names":
            with_names = True
        else:
            targets.append(token)
        index += 1
    return targets, out_path, with_names


def collect_blend_files(targets):
    """把目标展开成 .blend 文件列表；目录递归、文件直接用、.txt 当"一行一个路径"的清单读。"""
    found = []
    for target in targets:
        if target.lower().endswith(".txt") and os.path.isfile(target):
            with open(target, encoding="utf-8-sig") as handle:
                for line in handle:
                    candidate = line.strip()
                    if candidate and candidate.lower().endswith(".blend") and os.path.isfile(candidate):
                        found.append(candidate)
        elif os.path.isdir(target):
            for root_dir, _dirs, files in os.walk(target):
                for file_name in files:
                    if file_name.lower().endswith(".blend"):
                        found.append(os.path.join(root_dir, file_name))
        elif os.path.isfile(target):
            found.append(target)
    return sorted(set(found))


def bone_flags(bone):
    """把一根骨归到影子 / 扭转 / 指尖 / 主骨哪一类（只按名字）。"""
    name = bone.name
    flags = []
    if name.startswith(MCH_PREFIXES):
        flags.append("mch")
    if any(marker in name for marker in SHADOW_MARKERS):
        flags.append("shadow")
    if any(marker in name for marker in TWIST_MARKERS):
        flags.append("twist")
    return flags


def is_tip_leaf(bone):
    """末端叶骨：没有子骨、且名字像 `先` 结尾，或短到只剩占位（<= 父骨 15%）。"""
    if bone.children:
        return False
    if bone.length <= 1e-9:
        return False
    if any(marker in bone.name for marker in TIP_MARKERS):
        return True
    if bone.parent is not None and bone.parent.length > 1e-9:
        return bone.length <= bone.parent.length * 0.15
    return False


def duplicate_pairs(bones):
    """头尾位置重合的骨对 —— 双链（形变链 + 传递链）的最硬证据。"""
    buckets = {}
    for bone in bones:
        key = (
            round(bone.head_local.x, 5), round(bone.head_local.y, 5), round(bone.head_local.z, 5),
            round(bone.tail_local.x, 5), round(bone.tail_local.y, 5), round(bone.tail_local.z, 5),
        )
        buckets.setdefault(key, []).append(bone)

    mixed_pairs = 0
    samples = []
    for group in buckets.values():
        if len(group) < 2:
            continue
        deform_flags = {bone.use_deform for bone in group}
        if len(deform_flags) < 2:
            continue
        mixed_pairs += 1
        if len(samples) < 6:
            samples.append(sorted(bone.name for bone in group))
    return mixed_pairs, samples


def constraint_summary(armature_object):
    """统计骨架上的约束：IK（含链长 / 极向量 / 角度）/ 复制旋转 / TRANSFORM。"""
    ik_list = []
    copy_rotation_count = 0
    transform_count = 0
    other_count = 0
    for pose_bone in armature_object.pose.bones:
        for con in pose_bone.constraints:
            if con.type == "IK":
                ik_list.append({
                    "bone": pose_bone.name,
                    "chain_count": con.chain_count,
                    "target": getattr(con.target, "name", None) if con.target else None,
                    "pole_target": getattr(con.pole_target, "name", None) if getattr(con, "pole_target", None) else None,
                    "pole_angle_deg": round(float(getattr(con, "pole_angle", 0.0)) * 57.295779513, 2),
                    "use_stretch": bool(getattr(con, "use_stretch", False)),
                    "use_y": True,
                })
            elif con.type == "COPY_ROTATION":
                copy_rotation_count += 1
            elif con.type == "TRANSFORM":
                transform_count += 1
            else:
                other_count += 1
    return ik_list, copy_rotation_count, transform_count, other_count


def survey_armature(armature_object, with_names):
    data = armature_object.data
    bones = list(data.bones)

    deform_bones = [bone for bone in bones if bone.use_deform]
    shadow_bones = [bone for bone in bones if any(marker in bone.name for marker in SHADOW_MARKERS)]
    twist_bones = [bone for bone in bones if any(marker in bone.name for marker in TWIST_MARKERS)]
    mch_bones = [bone for bone in bones if bone.name.startswith(MCH_PREFIXES)]
    tip_bones = [bone for bone in bones if is_tip_leaf(bone)]

    collections = []
    try:
        collections = [
            {"name": collection.name, "bones": len(collection.bones)}
            for collection in data.collections_all
        ]
    except Exception:  # noqa: BLE001
        collections = []

    mixed_pairs, mixed_samples = duplicate_pairs(bones)
    ik_list, copy_rotation_count, transform_count, other_count = constraint_summary(armature_object)

    roots = [bone.name for bone in bones if bone.parent is None]

    return {
        "object": armature_object.name,
        "data": data.name,
        "bone_count": len(bones),
        "deform_count": len(deform_bones),
        "nondeform_count": len(bones) - len(deform_bones),
        "roots": roots,
        "is_mmd": any(root in MMD_ROOT_NAMES for root in roots) or any(bone.name in MMD_ROOT_NAMES for bone in bones),
        "collections": collections,
        "shadow_count": len(shadow_bones),
        "twist_count": len(twist_bones),
        "mch_count": len(mch_bones),
        "mch_names": [bone.name for bone in mch_bones][:24],
        "tip_leaf_count": len(tip_bones),
        "tip_leaf_names": [bone.name for bone in tip_bones][:24],
        "duplicate_deform_pairs": mixed_pairs,
        "duplicate_samples": mixed_samples,
        "ik": ik_list,
        "copy_rotation_count": copy_rotation_count,
        "transform_count": transform_count,
        "other_constraint_count": other_count,
        "object_scale": [round(value, 5) for value in armature_object.scale],
        "names": [bone.name for bone in bones] if with_names else None,
    }


def survey_file(file_path, with_names):
    record = {
        "file": file_path,
        "size_mb": round(os.path.getsize(file_path) / (1024 * 1024), 2),
        "error": None,
        "open_warning": None,
        "blender": bpy.app.version_string,
        "armatures": [],
        "object_counts": {},
        "controllers": [],
        "texts": [],
    }
    ok, open_warning = open_mainfile_tolerant(file_path)
    record["open_warning"] = open_warning
    if not ok:
        record["error"] = "open failed: %s" % open_warning
        return record

    try:
        counts = {}
        for obj in bpy.data.objects:
            counts[obj.type] = counts.get(obj.type, 0) + 1
        record["object_counts"] = counts

        armature_objects = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
        for armature_object in armature_objects:
            record["armatures"].append(survey_armature(armature_object, with_names))

        controller_names = []
        for obj in bpy.data.objects:
            if obj.name.startswith(CONTROLLER_PREFIXES):
                controller_names.append(obj.name)
        record["controllers"] = sorted(controller_names)[:40]
        record["controller_count"] = len(controller_names)
        record["texts"] = [text.name for text in bpy.data.texts]
    except Exception:  # noqa: BLE001
        record["error"] = traceback.format_exc(limit=3)
    return record


def print_summary(records):
    header = "%-46s %3s %5s %5s %4s %4s %4s %4s %4s %4s" % (
        "file", "arm", "bones", "defor", "mmd", "shdw", "twst", "mch", "leaf", "ik")
    print(header)
    print("-" * len(header))
    for record in records:
        short_name = os.path.basename(record["file"])
        if record["error"]:
            print("%-46s ERROR %s" % (short_name[:46], record["error"].splitlines()[0][:60]))
            continue
        for armature in record["armatures"]:
            print("%-46s %3d %5d %5d %4s %4d %4d %4d %4d %4d" % (
                short_name[:46], len(record["armatures"]), armature["bone_count"],
                armature["deform_count"], "Y" if armature["is_mmd"] else "-",
                armature["shadow_count"], armature["twist_count"], armature["mch_count"],
                armature["tip_leaf_count"], len(armature["ik"])))


def main():
    targets, out_path, with_names = parse_args()
    files = collect_blend_files(targets)
    print("survey: %d blend files" % len(files))
    records = []
    for file_path in files:
        record = survey_file(file_path, with_names)
        records.append(record)
        status = "ok" if not record["error"] else record["error"].splitlines()[0][:80]
        print("  [%d/%d] %s :: %s" % (len(records), len(files), os.path.basename(file_path), status))

    print_summary(records)

    if out_path:
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump({"blender": bpy.app.version_string, "files": records}, handle, ensure_ascii=False, indent=1)
        print("survey written: %s" % out_path)


if __name__ == "__main__":
    main()
