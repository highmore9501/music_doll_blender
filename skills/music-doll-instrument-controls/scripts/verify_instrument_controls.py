"""独立验收 MusicDoll 乐器控件安装结果（可在 test 控件删除后运行）。

检查：
1. 演奏者 / 乐器 / 骨架登记正确；
2. 乐器控件齐全，test 控件已删除且没有残留引用；
3. MD_* 约束都指向实际控件，极向量在 rest 下与关节弯曲方向一致；
4. 手 / 手指 / 腿 / 手掌复制旋转对动作有正确响应；
5. 有头部控件的乐器：上半身 / 头部链（颈上 IK、头骨复制旋转、Track_To、控件位置、跟得住）；
6. 可选：与 rig 改造原件的 rest 网格逐顶点对照。

用法：
    blender -b --factory-startup -P verify_instrument_controls.py -- \
        --file "最终.blend" --performer Mia --instrument string_flow \
        --reference "rig原件.blend" --report report.json
"""

import argparse
import json
import math
import os
import sys

import bpy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
sys.dont_write_bytecode = True

import head_chain
import install_instrument_controls as installer


def parse_arguments():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="验收 MusicDoll 乐器控件安装结果")
    parser.add_argument("--file", required=True,
                        help="装好乐器控件的 .blend")
    parser.add_argument("--performer", required=True,
                        help="演奏者名字（对象后缀）")
    parser.add_argument("--instrument", default="string_flow")
    parser.add_argument("--adapter-file", default="",
                        help="可选：外部适配器 .py（与安装时同一份）")
    parser.add_argument("--variant", default="",
                        help="乐器变体（string_flow: violin/viola/cello）")
    parser.add_argument("--follow-bone", default="",
                        help="覆盖 controller_root 跟随的骨骼名")
    parser.add_argument("--anchor-position", default="",
                        help="大提琴/竖琴：期望的尾钉/支点世界坐标 \"x,y,z\"")
    parser.add_argument("--armature", default="",
                        help="可选：骨架名；只有一套骨架时可省略")
    parser.add_argument("--reference", default="",
                        help="可选：rig 改造原件，用来对照 rest 网格")
    parser.add_argument("--report", default="",
                        help="可选：验收结果 JSON")
    parser.add_argument("--allow-test", action="store_true",
                        help="允许 test 控件仍存在（只检查没有被引用，不判失败）")
    parser.add_argument("--neck-bone", default="",
                        help="可选：指定颈骨（与安装时一致）")
    parser.add_argument("--head-bone", default="",
                        help="可选：指定头骨（与安装时一致）")
    arguments, unknown = parser.parse_known_args(argv)
    if unknown:
        print("[verify] 忽略额外参数：" + " ".join(unknown))
    return arguments


def ensure_addon():
    if installer.ADDON_MODULE not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=installer.ADDON_MODULE)


def find_armature(armature_name):
    if armature_name:
        armature = bpy.data.objects.get(armature_name)
        if armature is None or armature.type != "ARMATURE":
            raise installer.InstallError("找不到骨架：" + armature_name)
        return armature
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise installer.InstallError("骨架不唯一，请用 --armature 指定")
    return armatures[0]


def find_mesh(armature):
    meshes = installer.find_deformed_meshes(armature)
    if not meshes:
        raise installer.InstallError("找不到受骨架驱动的 Mesh")
    return meshes[0]


def evaluated_world_vertices(mesh_object):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated = mesh_object.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    matrix = evaluated.matrix_world.copy()
    coordinates = [matrix @ vertex.co for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    return coordinates


def check_performer(performer_name, instrument_id):
    from music_doll_blender.common import performer_utils
    performer = performer_utils.get_performer(performer_name)
    result = {"found": performer is not None}
    if performer is None:
        return result
    result["instrument"] = performer.instrument
    result["skeleton"] = performer.target_skeleton.name if performer.target_skeleton else None
    result["instrument_object"] = (
        performer.target_instrument.name if performer.target_instrument else None)
    result["instrument_matches"] = performer.instrument == instrument_id
    return result


def check_controls(adapter, performer_name):
    from music_doll_blender.common import performer_utils
    missing = []
    present = []
    for short_name in set(adapter["test_to_short"].values()):
        full_name = performer_utils.resolve(short_name, performer_name)
        if bpy.data.objects.get(full_name) is None:
            missing.append(full_name)
        else:
            present.append(full_name)
    return {"present": len(present), "missing": missing}


def head_test_control_names(adapter):
    declared = adapter.get("head_chain") or {}
    return [declared.get("test_head_control", "Head_Control_test"),
            declared.get("test_look_at", "Look_At_test")]


def check_test_objects(adapter):
    names = list(adapter["test_to_short"])
    names.extend(head_test_control_names(adapter))
    return [name for name in names if bpy.data.objects.get(name) is not None]


def check_references(armature, adapter):
    test_names = set(adapter["test_to_short"])
    test_names.update(head_test_control_names(adapter))
    dangling = []
    wrong = []
    target_counts = {}
    for pose_bone in armature.pose.bones:
        for constraint in pose_bone.constraints:
            for attribute in ("target", "pole_target"):
                if not hasattr(constraint, attribute):
                    continue
                target = getattr(constraint, attribute)
                if target is None:
                    if constraint.name.startswith("MD_"):
                        dangling.append({
                            "bone": pose_bone.name,
                            "constraint": constraint.name,
                            "attribute": attribute,
                        })
                    continue
                if target.name in test_names:
                    wrong.append({
                        "bone": pose_bone.name,
                        "constraint": constraint.name,
                        "attribute": attribute,
                        "target": target.name,
                    })
                if constraint.name.startswith("MD_"):
                    target_counts[target.name] = target_counts.get(target.name, 0) + 1
    return {
        "dangling": dangling,
        "still_points_to_test": wrong,
        "target_counts": target_counts,
    }


def check_parent_inverse(adapter):
    """导出前自查：控件身上的 `matrix_parent_inverse` 必须是单位阵。

    Blender 的世界 = 父级 × `matrix_parent_inverse` × 本地；"保留变换地挂父级"会让前两项抵消，
    于是 location 里存下的其实是世界值。Blender 里怎么算都自洽，可导出器只写 location，
    引擎按"父级 × 本地"再乘一遍父级 —— 部件就落错地方（手腕下面偏 1 m 级，带缩放的父级下面偏几公里）。

    只查控件：骨架和带骨架修改器的人物网格走 FBX，导出器自己会把 parent inverse 归零；
    还没删的 `_test` 控件也不查（它们马上会被删掉，且是 rig 阶段的临时件）。
    """
    from mathutils import Matrix
    identity = Matrix.Identity(4)
    test_names = set(adapter["test_to_short"])
    test_names.update(head_test_control_names(adapter))
    offenders = []
    checked = 0
    for obj in bpy.data.objects:
        if obj.type == 'ARMATURE' or obj.parent is None:
            continue
        if obj.parent_type != 'OBJECT':
            continue
        if obj.name in test_names or obj.name.endswith("_test"):
            continue
        if any(modifier.type == 'ARMATURE' for modifier in obj.modifiers):
            continue
        checked += 1
        deviation = max(abs(obj.matrix_parent_inverse[row][column] - identity[row][column])
                        for row in range(4) for column in range(4))
        if deviation <= 1e-6:
            continue
        engine_position = (obj.parent.matrix_world @ obj.matrix_basis).translation
        offenders.append({
            "object": obj.name,
            "parent": obj.parent.name,
            "deviation": round(deviation, 6),
            "position_error": round(
                (engine_position - obj.matrix_world.translation).length, 6),
        })
    return {"checked": checked, "offenders": offenders, "passed": not offenders}


def check_controller_root(armature, performer_name, adapter, variant, follow_bone,
                          anchor_position_text):
    from music_doll_blender.common import performer_utils
    root = bpy.data.objects.get(performer_utils.resolve("controller_root", performer_name))
    if root is None:
        return {"found": False, "passed": False}
    spec = installer.resolve_controller_root_spec(adapter, variant, follow_bone)
    mode = spec.get("mode", "none")
    result = {"found": True, "mode": mode, "object": root.name}
    if mode == "none":
        follow_constraints = [
            constraint for constraint in root.constraints
            if constraint.type in ("COPY_LOCATION", "COPY_ROTATION")
        ]
        result["constraints"] = [
            {
                "name": constraint.name,
                "type": constraint.type,
                "target": getattr(getattr(constraint, "target", None), "name", None),
                "subtarget": getattr(constraint, "subtarget", ""),
            }
            for constraint in follow_constraints
        ]
        result["passed"] = not follow_constraints
        return result

    if mode == "bone":
        bone_name = spec.get("bone") or "首"
        if bone_name not in armature.pose.bones:
            result.update({"passed": False, "error": "骨骼不存在：" + bone_name})
            return result
        result["bone"] = bone_name
        target_matrix = armature.matrix_world @ armature.pose.bones[bone_name].matrix
        actual_matrix = root.matrix_world
        translation_error = (actual_matrix.translation - target_matrix.translation).length
        rotation_error = installer.rotation_difference_degrees(
            actual_matrix.to_quaternion(), target_matrix.to_quaternion())
        result["translation_error_m"] = translation_error
        result["rotation_error_deg"] = rotation_error
        result["constraints"] = [
            {
                "name": constraint.name,
                "type": constraint.type,
                "target": getattr(getattr(constraint, "target", None), "name", None),
                "subtarget": getattr(constraint, "subtarget", ""),
                "owner_space": getattr(constraint, "owner_space", None),
                "target_space": getattr(constraint, "target_space", None),
            }
            for constraint in root.constraints
            if constraint.type in ("COPY_LOCATION", "COPY_ROTATION")
        ]
        # 功能检查：颈骨转 5°，controller_root 的旋转也应转 ~5°
        pose_bone = armature.pose.bones[bone_name]
        before_root_rotation = root.matrix_world.to_quaternion().copy()
        original_mode = pose_bone.rotation_mode
        pose_bone.rotation_mode = "QUATERNION"
        original_quaternion = pose_bone.rotation_quaternion.copy()
        pose_bone.rotation_quaternion = (
            installer.Quaternion((0.0, 1.0, 0.0), math.radians(5.0))
            @ pose_bone.rotation_quaternion)
        bpy.context.view_layer.update()
        root_rotation_delta = installer.rotation_difference_degrees(
            before_root_rotation, root.matrix_world.to_quaternion())
        result["follow_rotation_delta_deg"] = root_rotation_delta
        pose_bone.rotation_quaternion = original_quaternion
        pose_bone.rotation_mode = original_mode
        bpy.context.view_layer.update()
        result["passed"] = (
            translation_error <= 1e-5
            and rotation_error <= 0.01
            and abs(root_rotation_delta - 5.0) <= 0.5)
        return result

    if mode == "anchor_required":
        result["world_location"] = [
            round(value, 6) for value in root.matrix_world.translation]
        if anchor_position_text:
            expected = installer.parse_anchor_position(anchor_position_text)
            result["anchor_error_m"] = (root.matrix_world.translation - expected).length
            result["passed"] = result["anchor_error_m"] <= 1e-5
        else:
            result["passed"] = None
        return result

    result["passed"] = False
    result["error"] = "未知模式：" + str(mode)
    return result


def check_pole_angles(armature):
    angles = installer.rest_pole_angles(armature)
    bad = {name: angle for name, angle in angles.items()
           if angle is not None and angle > 2.0}
    return {"angles_deg": angles, "bad": bad}


def check_motion(armature):
    """不依赖 test 控件，只确认实际控件能驱动骨架。"""
    pose_bone, constraint = installer.constraint_by_name(armature, "MD_IK_arm.L")
    hand_target = constraint.target if constraint is not None else None
    pose_bone_rot, constraint_rot = installer.constraint_by_name(armature, "MD_Rot_arm.L")
    pose_bone_leg, constraint_leg = installer.constraint_by_name(armature, "MD_IK_leg.L")
    pose_bone_finger, constraint_finger = installer.constraint_by_name(armature, "MD_IK_index.L")

    metrics = {}

    if pose_bone is not None and hand_target is not None:
        before = installer.bone_tail_world(armature, pose_bone)
        rest_matrix = hand_target.matrix_world.copy()
        hand_target.matrix_world = installer.Matrix.Translation((0.0, 0.0, 0.05)) @ hand_target.matrix_world
        bpy.context.view_layer.update()
        after = installer.bone_tail_world(armature, pose_bone)
        metrics["arm_tip_moved_m"] = (after - before).length
        hand_target.matrix_world = rest_matrix
        bpy.context.view_layer.update()

    if pose_bone_rot is not None and constraint_rot is not None:
        target = constraint_rot.target
        rest_matrix = target.matrix_world.copy()
        before_rotation = installer.bone_rotation_world(armature, pose_bone_rot)
        translation, rotation, scale = target.matrix_world.decompose()
        rotation = installer.Quaternion((0.0, 0.0, 1.0), math.radians(20.0)) @ rotation
        target.matrix_world = installer.Matrix.LocRotScale(translation, rotation, scale)
        bpy.context.view_layer.update()
        after_rotation = installer.bone_rotation_world(armature, pose_bone_rot)
        metrics["hand_rotation_delta_deg"] = installer.rotation_difference_degrees(
            before_rotation, after_rotation)
        target.matrix_world = rest_matrix
        bpy.context.view_layer.update()

    if pose_bone_leg is not None and constraint_leg is not None:
        target = constraint_leg.target
        rest_matrix = target.matrix_world.copy()
        before = installer.bone_tail_world(armature, pose_bone_leg)
        target.matrix_world = installer.Matrix.Translation((0.0, 0.10, 0.0)) @ target.matrix_world
        bpy.context.view_layer.update()
        after = installer.bone_tail_world(armature, pose_bone_leg)
        metrics["leg_tip_moved_m"] = (after - before).length
        target.matrix_world = rest_matrix
        bpy.context.view_layer.update()

    if pose_bone_finger is not None and constraint_finger is not None:
        target = constraint_finger.target
        palm = constraint_rot.target if constraint_rot is not None else None
        if palm is not None:
            rest_matrix = target.matrix_world.copy()
            before = installer.bone_tail_world(armature, pose_bone_finger)
            direction = (palm.matrix_world.translation
                         - target.matrix_world.translation)
            if direction.length > 1e-9:
                target.matrix_world = installer.Matrix.Translation(
                    direction.normalized() * 0.01) @ target.matrix_world
                bpy.context.view_layer.update()
                after = installer.bone_tail_world(armature, pose_bone_finger)
                metrics["finger_tip_moved_m"] = (after - before).length
            target.matrix_world = rest_matrix
            bpy.context.view_layer.update()

    passed = (
        metrics.get("arm_tip_moved_m", 0.0) > 0.04
        and abs(metrics.get("hand_rotation_delta_deg", 0.0) - 20.0) < 2.0
        and metrics.get("leg_tip_moved_m", 0.0) > 0.08
        and metrics.get("finger_tip_moved_m", 0.0) > 0.005
    )
    return {"metrics": metrics, "passed": passed}


def resolve_head_spec(adapter, performer_name, arguments):
    """适配器里的 head_chain 短名 → 实际对象名（验收时不需要 config，按后缀解析即可）。"""
    from music_doll_blender.common import performer_utils

    declared = adapter.get("head_chain")
    if not declared:
        return None
    head_control_short = declared.get("head_control", "Head_Control")
    look_at_short = declared.get("look_at", "Look_At")
    return {
        "head_control_short": head_control_short,
        "look_at_short": look_at_short,
        "head_control": performer_utils.resolve(head_control_short, performer_name),
        "look_at": performer_utils.resolve(look_at_short, performer_name),
        "neck_bone": arguments.neck_bone or declared.get("neck_bone", ""),
        "head_bone": arguments.head_bone or declared.get("head_bone", ""),
        "chain_count": declared.get("chain_count", 0),
        "look_distance": declared.get("look_distance", 1.0),
        "pole_angle": declared.get("pole_angle"),
    }


def check_head_chain(armature, spec):
    """上半身 / 头部链：控件在不在、链对不对、拖得动、看不看得着视点。"""
    if spec is None:
        return {"checked": False, "reason": "这个乐器没有声明 head_chain"}
    head_control = bpy.data.objects.get(spec["head_control"])
    look_at = bpy.data.objects.get(spec["look_at"])
    if head_control is None or look_at is None:
        return {"checked": True, "present": False, "passed": False,
                "missing": [name for name, obj in ((spec["head_control"], head_control),
                                                   (spec["look_at"], look_at))
                            if obj is None]}
    try:
        spine = head_chain.detect_spine(armature, spec, lambda _message: None)
    except head_chain.HeadChainError as error:
        return {"checked": True, "present": True, "passed": False, "error": str(error)}

    neck_pose_bone = armature.pose.bones[spine["neck"]]
    head_pose_bone = armature.pose.bones[spine["head"]]
    ik_constraint = None
    for constraint in neck_pose_bone.constraints:
        if constraint.type == "IK" and constraint.target is head_control:
            ik_constraint = constraint
            break
    rotation_constraint = None
    for constraint in head_pose_bone.constraints:
        if constraint.type == "COPY_ROTATION" and constraint.target is head_control:
            rotation_constraint = constraint
            break
    track_constraint = None
    for constraint in head_control.constraints:
        if constraint.type == "TRACK_TO" and constraint.target is look_at:
            track_constraint = constraint
            break

    geometry = head_chain.spine_geometry(armature, spine, spec)
    probes = head_chain.measure_poses(armature, spine, head_control, look_at, geometry)
    reach = max(item["gap"] for item in probes)
    rotation = max(item["rotation_error"] for item in probes)
    aims = [item["aim_error"] for item in probes if item["aim_error"] is not None]
    bends = [item["bend_error"] for item in probes if item["bend_error"] is not None]
    aim = max(aims) if aims else 0.0
    bend = max(bends) if bends else 0.0

    placement_error = (head_chain.evaluated_world(head_control).translation
                       - geometry["chain_end"]).length
    look_offset = head_chain.evaluated_world(look_at).translation - geometry["chain_end"]
    look_forward_cos = (look_offset.normalized().dot(geometry["head_forward"])
                        if look_offset.length > 1e-9 else 0.0)
    reach_tolerance = geometry["chain_length"] * head_chain.REACH_TOLERANCE_RATIO

    checks = [
        {"name": "头部控制器在头部骨骼位置",
         "ok": placement_error <= geometry["chain_length"] * head_chain.PLACEMENT_TOLERANCE_RATIO,
         "detail": "离颈尾 %.6f m" % placement_error},
        {"name": "视点在人物正前方", "ok": look_forward_cos >= 0.99,
         "detail": "偏离头骨 Z 轴 %.2f°，距颈尾 %.4f m" % (
             math.degrees(math.acos(max(-1.0, min(1.0, look_forward_cos)))),
             look_offset.length)},
        {"name": "颈上 IK（链长 / 目标 / 极向量）",
         "ok": (ik_constraint is not None
                and ik_constraint.chain_count == len(spine["chain"])
                and ik_constraint.target is head_control
                and ik_constraint.pole_target is look_at),
         "detail": ("chain=%d target=%s pole=%s pole_angle=%.1f°" % (
             ik_constraint.chain_count,
             getattr(getattr(ik_constraint, "target", None), "name", None),
             getattr(getattr(ik_constraint, "pole_target", None), "name", None),
             math.degrees(ik_constraint.pole_angle)) if ik_constraint is not None
             else "没有指向 %s 的 IK（应为链长 %d）" % (head_control.name, len(spine["chain"])))},
        {"name": "头骨世界空间复制旋转",
         "ok": (rotation_constraint is not None
                and rotation_constraint.owner_space == "WORLD"
                and rotation_constraint.target_space == "WORLD"
                and rotation_constraint.mix_mode == "REPLACE"),
         "detail": "目标 %s" % (getattr(getattr(rotation_constraint, "target", None),
                                     "name", None) if rotation_constraint else "没有")},
        {"name": "Track_To（Z→视点、Y 朝上）",
         "ok": (track_constraint is not None
                and track_constraint.track_axis == "TRACK_Z"
                and track_constraint.up_axis == "UP_Y"
                and not track_constraint.use_target_z),
         "detail": "target=%s track=%s up=%s use_target_z=%s" % (
             getattr(getattr(track_constraint, "target", None), "name", None),
             getattr(track_constraint, "track_axis", None),
             getattr(track_constraint, "up_axis", None),
             getattr(track_constraint, "use_target_z", None))},
        {"name": "颈尾跟住头部控制器", "ok": reach <= reach_tolerance,
         "detail": "最大差 %.5f m（容差 %.5f）" % (reach, reach_tolerance)},
        {"name": "头骨朝向 = 头部控制器", "ok": rotation <= head_chain.ROTATION_TOLERANCE_DEG,
         "detail": "最大 %.3f°" % rotation},
        {"name": "头骨 Z 轴指向视点", "ok": aim <= head_chain.AIM_TOLERANCE_DEG,
         "detail": "最大 %.2f°" % aim},
        {"name": "躯干往极向量那侧弯", "ok": bend <= head_chain.BEND_TOLERANCE_DEG,
         "detail": "最大偏 %.1f°" % bend},
    ]
    return {
        "checked": True,
        "present": True,
        "spine": spine,
        "head_control": head_control.name,
        "look_at": look_at.name,
        "chain_length": geometry["chain_length"],
        "pole_angle_deg": round(math.degrees(ik_constraint.pole_angle), 2)
        if ik_constraint is not None else None,
        "probes": probes,
        "checks": checks,
        "failed": [item["name"] for item in checks if not item["ok"]],
        "passed": all(item["ok"] for item in checks),
    }


def main():
    arguments = parse_arguments()
    ensure_addon()

    if arguments.adapter_file:
        installer.load_adapter_file(arguments.adapter_file)
    adapter = installer.INSTRUMENT_ADAPTERS.get(arguments.instrument)
    if adapter is None:
        raise installer.InstallError(
            "未知乐器 %s；请用 --adapter-file 提供适配器" % arguments.instrument)
    reference_vertices = None
    if arguments.reference:
        installer.open_blend_file(arguments.reference)
        reference_armature = find_armature(arguments.armature)
        reference_mesh = find_mesh(reference_armature)
        reference_vertices = evaluated_world_vertices(reference_mesh)
        print("[verify] 参考 rest 顶点：" + str(len(reference_vertices)))

    installer.open_blend_file(arguments.file)
    armature = find_armature(arguments.armature)
    mesh = find_mesh(armature)

    summary = {
        "file": arguments.file,
        "performer": arguments.performer,
        "instrument": arguments.instrument,
        "armature": armature.name,
        "mesh": mesh.name,
    }
    summary["performer_info"] = check_performer(arguments.performer, arguments.instrument)
    summary["controls"] = check_controls(adapter, arguments.performer)
    summary["remaining_test_objects"] = check_test_objects(adapter)
    summary["allow_test"] = bool(arguments.allow_test)
    summary["references"] = check_references(armature, adapter)
    summary["parent_inverse"] = check_parent_inverse(adapter)
    summary["pole"] = check_pole_angles(armature)
    summary["controller_root"] = check_controller_root(
        armature, arguments.performer, adapter, arguments.variant,
        arguments.follow_bone, arguments.anchor_position)
    summary["motion"] = check_motion(armature)
    head_spec = resolve_head_spec(adapter, arguments.performer, arguments)
    summary["head_chain"] = check_head_chain(armature, head_spec)

    if reference_vertices is not None:
        current_vertices = evaluated_world_vertices(mesh)
        if len(current_vertices) != len(reference_vertices):
            summary["rest_mesh"] = {
                "checked": True,
                "vertex_count_matches": False,
                "reference_count": len(reference_vertices),
                "current_count": len(current_vertices),
            }
        else:
            max_delta = max(
                (current - reference).length
                for current, reference in zip(current_vertices, reference_vertices))
            summary["rest_mesh"] = {
                "checked": True,
                "vertex_count_matches": True,
                "max_delta_m": max_delta,
                "passed": max_delta <= 1e-5,
            }
    else:
        summary["rest_mesh"] = {"checked": False}

    failures = []
    if not summary["performer_info"].get("found"):
        failures.append("没有登记演奏者 " + arguments.performer)
    elif not summary["performer_info"].get("instrument_matches"):
        failures.append("演奏者登记的乐器与 --instrument 不一致")
    if summary["controls"]["missing"]:
        failures.append("缺少控件：" + "、".join(summary["controls"]["missing"]))
    if summary["remaining_test_objects"] and not arguments.allow_test:
        failures.append("还有 test 控件：" + "、".join(summary["remaining_test_objects"]))
    if summary["references"]["still_points_to_test"]:
        failures.append("约束仍指向 test 控件")
    if summary["references"]["dangling"]:
        failures.append("有 MD_ 约束目标为空（可能引用了已删除对象）")
    if summary["parent_inverse"]["offenders"]:
        failures.append("控件挂了非单位 matrix_parent_inverse（保留变换地挂父级，导出后会错位）："
                        + "、".join(item["object"]
                                   for item in summary["parent_inverse"]["offenders"]))
    if summary["pole"]["bad"]:
        failures.append("极向量偏离超差")
    if summary["controller_root"].get("passed") is False:
        failures.append("controller_root 没有按乐器规则对齐")
    if not summary["motion"]["passed"]:
        failures.append("动作响应不合格")
    head_result = summary["head_chain"]
    if head_result.get("checked") and not head_result.get("passed"):
        if head_result.get("missing"):
            failures.append("头部链控件缺失：" + "、".join(head_result["missing"]))
        elif head_result.get("error"):
            failures.append("头部链认不出躯干骨：" + head_result["error"])
        else:
            failures.append("上半身 / 头部链不合格：" + "、".join(
                head_result.get("failed") or []))
    if summary["rest_mesh"].get("checked") and not summary["rest_mesh"].get("passed"):
        failures.append("rest 网格与参考不一致")

    summary["failures"] = failures
    summary["passed"] = not failures

    print("[verify] " + json.dumps(summary, ensure_ascii=False, indent=2))
    if arguments.report:
        report_path = arguments.report
        if not os.path.isabs(report_path):
            report_path = os.path.join(os.path.dirname(arguments.file), report_path)
        with open(report_path, "w", encoding="utf-8") as report_file:
            json.dump(summary, report_file, ensure_ascii=False, indent=2)
        print("[verify] 报告：" + report_path)

    if failures:
        print("VERIFY_RESULT FAIL " + json.dumps(failures, ensure_ascii=False))
        sys.exit(1)
    print("VERIFY_RESULT PASS")


if __name__ == "__main__":
    try:
        main()
    except installer.InstallError as error:
        print("VERIFY_ERROR " + str(error))
        sys.exit(1)
