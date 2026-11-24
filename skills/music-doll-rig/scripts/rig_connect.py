# -*- coding: utf-8 -*-
"""MusicDoll 骨架改造 —— 链条对接（只补 connect，不重建骨架）。

解决的是"骨架已经绑好了，但关节没连"这一种半成品：MMD / PMX 换算过来的骨架里，
骨的尾端只是一段偏移量，导进 Blender 之后 `use_connect` 全是 0；于是：
- 后一根的头没有压在前一根的尾上时，转动中间关节，两段之间会裂开；
- 就算压上了，没连的子骨仍然能被单独平移，拖 IK 控制器照样会散。

这个脚本只做一件事：按给定的链，把每对父子"尾→头"对齐（可选）并设成 `use_connect = True`。
它不认识形变骨、不改约束、不动权重 —— 那些是 `rig_apply.py` 的活。

用法：

    blender -b --factory-startup -P rig_connect.py -- <file.blend> \
        [--armature NAME] [--chains "足D.L>ひざD.L>足首D.L;…"] \
        [--fix-tails] [--reanchor-drive] [--dry-run] [--save] [--out 副本.blend] [--json out.json]

- `--chains`：分号分隔多条链，每条链用 `>` 连骨名（链首到链尾）。中文名、日文名都行。
  不给就跟分析器要：两臂 + 十指 + 两腿（分析器认出来的那条本体链）。
- `--fix-tails`：允许把前一根的尾端拽到后一根的头上。**默认不动尾端**，只连"已经重合"的关节，
  其余逐条报出来 —— 拽尾端会改那根骨的 Y 轴，进而改它的形变映射，得由人确认。
- `--reanchor-drive`：与 `--fix-tails` 一起用。尾端挪过的那根骨如果姿势是"局部空间"借来的
  （MMD 的 `mmd_additional_rotation`），把它重挂成 Copy Rotation（owner=LOCAL、
  target=LOCAL_OWNER_ORIENT、REPLACE），这样形变只跟本体骨有关、与它自己朝哪儿无关。
  MMD 影子腿链（`足D/ひざD/足首D`）必须开这个，不然尾端一挪腿就废。
- 没有 `--save` / `--out` 时只报告不写盘。

判据与 SKILL.md 的第四条硬规则一致：关节重合（差 ≤ `rig_common.CHAIN_JOINT_TOLERANCE`）+ `use_connect=1`。
"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rig_common as common  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {"file": None, "armature": None, "chains": [], "fix_tails": False,
               "reanchor_drive": False, "dry_run": False, "save": False, "out": None, "json": None}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--armature":
            index += 1
            options["armature"] = argv[index]
        elif token == "--chains":
            index += 1
            for chunk in argv[index].split(";"):
                names = [name.strip() for name in chunk.split(">") if name.strip()]
                if len(names) >= 2:
                    options["chains"].append(names)
        elif token == "--fix-tails":
            options["fix_tails"] = True
        elif token == "--reanchor-drive":
            options["reanchor_drive"] = True
        elif token == "--dry-run":
            options["dry_run"] = True
        elif token == "--save":
            options["save"] = True
        elif token == "--out":
            index += 1
            options["out"] = argv[index]
        elif token == "--json":
            index += 1
            options["json"] = argv[index]
        else:
            options["file"] = token
        index += 1
    return options


def find_armature(name=None):
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if name:
        armatures = [obj for obj in armatures if obj.name == name]
    return armatures[0] if armatures else None


def chains_from_analyzer(armature_object):
    """分析器认出来的链（两臂 / 十指 / 两腿），转成 [ [骨名…], … ]。

    注意：分析器给的是**本体链**（`足.L / ひざ.L / 足首.L`）。MMD 骨架里常并列一条影子链
    （`足D / ひざD / 足首D`），那条 IK 真正在用的链要自己用 `--chains` 写出来。
    """
    import rig_analyze as analyzer

    bone_index = common.build_bone_index(armature_object)
    foot_names = [name for name in bone_index
                  if common.role_from_name(name)["role"] == "foot"
                  and common.role_from_name(name)["variant"] in ("plain", "shadow")]
    front_axis, _evidence = common.detect_front_axis(bone_index, foot_names)
    result = analyzer.analyze_armature(armature_object, front_axis)

    chains = []
    for side in ("L", "R"):
        arm = result["arms"].get(side)
        if arm:
            chain = arm["chain"]
            names = [chain.get("upper"), chain.get("forearm"), chain.get("hand")]
            chains.append([name for name in names if name])
        leg = result["legs"].get(side)
        if leg:
            chain = leg["chain"]
            names = [chain.get("thigh"), chain.get("shin"), chain.get("foot")]
            names = [name for name in names if name]
            # 脚掌→脚趾是 Unreal 重定向链的最后一节；只接"头落在脚掌尾端上"的那根
            if names:
                toe_name = common.toe_continuation(bone_index, names[-1])
                if toe_name:
                    names.append(toe_name)
            chains.append(names)
        for role in ("thumb", "index", "middle", "ring", "pinky"):
            finger = result["fingers"].get(side, {}).get(role)
            if not finger:
                continue
            tip_name = (finger.get("leaf") or {}).get("tip_bone") or finger.get("tip")
            names = list(finger["segments"]) + ([tip_name] if tip_name else [])
            chains.append(names)
    return chains


def plain_source_of(armature_object, bone_name):
    """认出一根"影子 D 骨"背后真正驱动它的本体骨（`左足D` ← `左足`）。

    MMD 的接法是一条三级链：D 骨用 `mmd_additional_rotation` 从 `_shadow_X` 借局部旋转，
    `_shadow_X` 从 `_dummy_X` 复制姿势，`_dummy_X` 挂在真正的本体骨上（`_dummy_左足D` 的父是 `左足`）。
    顺着这条链走能找到本体骨；走不通就按名字去掉末尾的 `D`。
    """
    pose_bones = armature_object.pose.bones
    for constraint in pose_bones[bone_name].constraints:
        if constraint.type != "TRANSFORM":
            continue
        shadow_name = getattr(constraint, "subtarget", "")
        shadow = pose_bones.get(shadow_name) if shadow_name else None
        if shadow is None:
            continue
        for copy in shadow.constraints:
            dummy_name = getattr(copy, "subtarget", "")
            dummy = pose_bones.get(dummy_name) if dummy_name else None
            if dummy is not None and dummy.parent is not None:
                return dummy.parent.name
    fallback = bone_name[:-1] if bone_name.endswith("D") else None
    return fallback if fallback in armature_object.data.bones else None


def reanchor_drive(armature_object, bone_name, dry_run, record):
    """把"尾端挪过"的那根骨的姿势来源重挂成与静置帧无关的接法。

    为什么必须重挂：MMD 的 `mmd_additional_rotation` 是把 `_shadow_*` 的**局部**旋转 ADD 到
    这根骨的局部旋转上，这组数只在"它的静置帧和 `_shadow_*` 一样"时才成立。尾端一挪，静置帧变了，
    同一组数落到别的骨轴上 —— 实测腿骨弯 50° 时脚飞出去 23 cm。

    换成"本体骨的局部旋转、按本骨朝向解释"（Copy Rotation，owner=LOCAL、target=LOCAL_OWNER_ORIENT，
    REPLACE）之后，形变只取决于本体骨，与本骨朝哪儿无关：实测 rest 0 误差、屈膝 90° 误差 2 µm。
    """
    pose_bone = armature_object.pose.bones[bone_name]
    plain_name = plain_source_of(armature_object, bone_name)
    if plain_name is None:
        record["actions"].append("找不到本体骨，姿势没重挂（尾端改了，形变可能会歪）")
        return False
    muted = [constraint.name for constraint in pose_bone.constraints
             if constraint.type == "TRANSFORM" and not constraint.mute]
    if not muted:
        record["actions"].append("本来就不是局部空间驱动的，姿势不用重挂")
        return False
    record["actions"].append("姿势重挂到 %s（mute %s + Copy Rotation LOCAL/LOCAL_OWNER_ORIENT）" % (
        plain_name, "/".join(muted)))
    if dry_run:
        return True
    for constraint in pose_bone.constraints:
        if constraint.type == "TRANSFORM":
            constraint.mute = True
    driver_name = "MD_Drive_%s" % bone_name
    driver = pose_bone.constraints.get(driver_name)
    if driver is None:
        driver = pose_bone.constraints.new("COPY_ROTATION")
        driver.name = driver_name
    driver.target = armature_object
    driver.subtarget = plain_name
    driver.owner_space = "LOCAL"
    driver.target_space = "LOCAL_OWNER_ORIENT"
    driver.mix_mode = "REPLACE"
    driver.use_x = driver.use_y = driver.use_z = True
    driver.influence = 1.0
    driver.mute = False
    return True


def connect_chain(armature_object, chain_names, fix_tails, reanchor, dry_run, results):
    """把一条链接上：不重合的尾端（可选）拽过去，然后逐对设 `use_connect`。"""
    edit_bones = armature_object.data.edit_bones
    for parent_name, child_name in common.chain_joints(chain_names):
        record = {"parent": parent_name, "child": child_name, "actions": [], "retimed": []}
        parent_bone = edit_bones.get(parent_name)
        child_bone = edit_bones.get(child_name)
        if parent_bone is None or child_bone is None:
            record["actions"].append("骨不存在，跳过")
            results.append(record)
            continue
        if child_bone.parent != parent_bone:
            record["actions"].append("不是子级（父=%s），跳过" % (
                child_bone.parent.name if child_bone.parent else "-"))
            results.append(record)
            continue
        gap = (parent_bone.tail - child_bone.head).length
        if gap > common.CHAIN_JOINT_TOLERANCE:
            if not fix_tails:
                record["actions"].append("尾端离头 %.5f，没动（要改尾端加 --fix-tails）" % gap)
                results.append(record)
                continue
            record["actions"].append("尾端挪到子骨头上（原来差 %.5f）" % gap)
            if not dry_run:
                parent_bone.tail = child_bone.head.copy()
            if reanchor:
                record["retimed"].append(parent_name)
        if child_bone.use_connect:
            record["actions"].append("早就连着")
        else:
            record["actions"].append("connect=1")
            if not dry_run:
                child_bone.use_connect = True
        results.append(record)


def main():
    options = parse_args()
    if not options["file"]:
        print(__doc__)
        return
    ok, warning = common.open_mainfile_tolerant(options["file"])
    if warning:
        print("注意：载入时报错（已跳过）：%s" % warning)
    if not ok:
        print("CONNECT 打不开文件")
        return
    armature_object = find_armature(options["armature"])
    if armature_object is None:
        print("CONNECT 没找到骨架")
        return

    chains = options["chains"] or chains_from_analyzer(armature_object)
    print("骨架：%s（%d 根骨），要处理的链 %d 条" % (
        armature_object.name, len(armature_object.data.bones), len(chains)))

    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    results = []
    for chain_names in chains:
        print("")
        print("== %s ==" % " > ".join(chain_names))
        connect_chain(armature_object, chain_names, options["fix_tails"],
                      options["reanchor_drive"], options["dry_run"], results)

    bpy.ops.object.mode_set(mode="OBJECT")

    retimed = [name for record in results for name in record.get("retimed", [])]
    if retimed:
        print("")
        print("== 尾端挪过的骨，姿势来源重挂 ==")
        for name in retimed:
            record = {"parent": name, "child": "（重挂）", "actions": []}
            reanchor_drive(armature_object, name, options["dry_run"], record)
            print("  %-12s %s" % (name, "；".join(record["actions"])))
        bpy.context.view_layer.update()

    for record in results:
        if record["actions"]:
            print("  %-12s → %-12s %s" % (record["parent"], record["child"], "；".join(record["actions"])))

    # 连完之后按骨架真实状态复核一遍（不是按刚才的动作，而是按 read 回来的 use_connect）
    bone_index = common.build_bone_index(armature_object)
    pending = []
    for chain_names in chains:
        for item in common.chain_joint_report(bone_index, chain_names):
            if not item["exists"] or not item["parent_ok"] or not item["coincident"] or not item["connected"]:
                pending.append(item)
    if pending:
        print("")
        print("还有 %d 处没到位：" % len(pending))
        for item in pending:
            print("  %s → %s gap=%s connect=%s 父级=%s" % (
                item["parent"], item["child"],
                ("%.5f" % item["gap"]) if item["gap"] is not None else "n/a",
                "1" if item["connected"] else "0",
                "ok" if item["parent_ok"] else "不对"))
    else:
        print("")
        print("CONNECT RESULT: 全部到位（%d 处关节）" % sum(
            len(common.chain_joints(chain_names)) for chain_names in chains))

    if options["json"]:
        with open(options["json"], "w", encoding="utf-8") as handle:
            json.dump({"file": options["file"], "armature": armature_object.name,
                       "chains": chains, "actions": results,
                       "pending": [dict(item, gap=(round(item["gap"], 8) if item["gap"] is not None else None))
                                   for item in pending]},
                      handle, ensure_ascii=False, indent=1)
        print("json: %s" % options["json"])

    if options["dry_run"]:
        print("--dry-run：没有写盘")
        return
    if options["out"]:
        bpy.ops.wm.save_as_mainfile(filepath=options["out"], copy=True)
        print("已另存：%s" % options["out"])
    elif options["save"]:
        try:
            bpy.ops.wm.save_mainfile()
        except RuntimeError as error:
            message = str(error).splitlines()[0] if str(error) else ""
            print("存盘时 Blender 报了一条错（文件多半已写出，常见原因是缺贴图）：%s" % message)
        print("已保存：%s" % bpy.data.filepath)


if __name__ == "__main__":
    main()
