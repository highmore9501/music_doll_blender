"""给已经用 music-doll-rig 改造过的演奏者安装 MusicDoll 乐器控件。

流程：
1. 在 MusicDoll 里初始化演奏者（新建角色：演奏者骨骼 + 乐器 + 名字）；
2. 调乐器模块的 setup_all_objects，生成整套实际控件；
3. 把实际控件的位置/旋转对齐到 rig skill 留下的 test 控件（保留控件自身缩放）；
4. 把人物骨架约束里的 test 控件引用替换为实际控件；
5. 有头部控件的乐器（架子鼓 / 钢琴 / 古筝…）顺手把上半身 / 头部控制链搭起来：
   颈上 IK（目标 Head_Control、极向量 Look_At）+ 头骨世界空间复制旋转；
6. 验收（对齐误差 / rest 网格 / 极向量 / IK 动作 / 残留引用），删除 test 控件，另存新文件。

用法（Blender 无头）：
    blender -b --factory-startup -P install_instrument_controls.py -- \
        --file "路径/角色.blend" --performer Mia --instrument string_flow \
        --out "路径/角色_小提琴.blend"

参数说明见 --help。脚本按“映射表 + 通用流程”组织，新增乐器时只需在
INSTRUMENT_ADAPTERS 里加一张 test→实际控件的短名映射。
"""

import argparse
import importlib
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.dont_write_bytecode = True

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import head_chain  # noqa: E402

ADDON_MODULE = "music_doll_blender"

# 每种乐器一张映射表：rig skill 的 test 控件名 → 乐器模块里的控件短名。
# 短名会交给 config.obj_name() 拼上演奏者后缀（如 H_L → H_L_Mia）。
INSTRUMENT_ADAPTERS = {
    "string_flow": {
        "instrument": "string_flow",
        "label": "StringFlow 提琴",
        "config_module": "music_doll_blender.string_flow.config",
        "config_class": "StringFlowConfig",
        "config_kwargs": {"instrument_type": "violin"},
        "variant_kwarg": "instrument_type",
        "default_variant": "violin",
        "controller_root": {
            "default": {"mode": "bone", "bone": "首", "label": "颈骨"},
            "variants": {
                # 小提琴 / 中提琴：琴身固定在颈下，根节点跟颈骨
                "violin": {"mode": "bone", "bone": "首", "label": "颈骨"},
                "viola": {"mode": "bone", "bone": "首", "label": "颈骨"},
                # 大提琴：尾钉位置必须由使用者指定，不能猜
                "cello": {"mode": "anchor_required", "label": "大提琴尾钉位置"},
            },
        },
        "test_to_short": {
            "H_L_test": "H_L",
            "H_R_test": "H_R",
            "HP_L_test": "HP_L",
            "HP_R_test": "HP_R",
            "F_L_test": "F_L",
            "F_R_test": "F_R",
            "FP_L_test": "FP_L",
            "FP_R_test": "FP_R",
            # 小提琴手指是数字命名：1=食指、2=中指、3=无名指、4=小指
            "I_L_test": "1_L",
            "M_L_test": "2_L",
            "R_L_test": "3_L",
            "P_L_test": "4_L",
            "T_L_test": "T_L",
            "I_R_test": "1_R",
            "M_R_test": "2_R",
            "R_R_test": "3_R",
            "P_R_test": "4_R",
            "T_R_test": "T_R",
            "I_L_pole_test": "pole_1_L",
            "M_L_pole_test": "pole_2_L",
            "R_L_pole_test": "pole_3_L",
            "P_L_pole_test": "pole_4_L",
            "T_L_pole_test": "TP_L",
            "I_R_pole_test": "pole_1_R",
            "M_R_pole_test": "pole_2_R",
            "R_R_pole_test": "pole_3_R",
            "P_R_pole_test": "pole_4_R",
            "T_R_pole_test": "TP_R",
        },
        # 动作等价验收：同一动作分别由 test 控件和实际控件驱动，逐骨结果必须一致。
        # 右手不列入：小提琴右手手指挂 Bow_Controller、不挂 H_R，这是乐器设计，
        # 与 test 层级不同，不能拿 H_R 单独平移来比。
        "behavior_samples": [
            {"name": "arm_lift", "target": "H_L_test",
             "kind": "translate", "delta": [0.0, 0.0, 0.05]},
            {"name": "hand_twist", "target": "H_L_test",
             "kind": "rotate_world", "axis": [0.0, 0.0, 1.0], "degrees": 20.0},
            {"name": "finger_bend", "target": "I_L_test",
             "kind": "translate_toward", "other": "H_L_test", "distance": 0.01,
             # 实际体系的极向量挂在 ext 上、会随手指移动（2 cm 级别），test 体系的
             # 极向量是静止的；因此同一动作下弯曲平面会有毫米/几度级差异，这是设计差异，
             # 不是替换错误。位置差仍要求 ≤2 mm。
             "tolerance_m": 0.002, "tolerance_deg": 5.0},
            {"name": "leg_forward", "target": "F_L_test",
             "kind": "translate", "delta": [0.0, 0.10, 0.0]},
        ],
    },
}

PROGRESS_TEXT_NAME = "MusicDoll_Instrument_Progress"


# ── 基础工具 ────────────────────────────────────────────────────────────

class InstallError(RuntimeError):
    pass


def log(message):
    print("[controls] " + str(message), flush=True)


def parse_arguments():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="给 music-doll-rig 改造过的演奏者安装 MusicDoll 乐器控件")
    parser.add_argument("--file", required=True, help="输入的 .blend（rig 改造完成）")
    parser.add_argument("--performer", required=True,
                        help="演奏者名字（英文字母/数字，兼作对象后缀）")
    parser.add_argument("--instrument", default="string_flow",
                        help="MusicDoll 乐器类型（内置 string_flow；其它乐器用 --adapter-file）")
    parser.add_argument("--adapter-file", default="",
                        help="可选：外部适配器 .py，定义 ADAPTER 字典（乐器映射/变体/controller_root）")
    parser.add_argument("--instrument-object", default="",
                        help="可选：乐器物体名（小提琴琴体等）；不给就不登记乐器物体")
    parser.add_argument("--variant", default="",
                        help="可选：乐器变体（string_flow: violin/viola/cello；省略用适配器默认）")
    parser.add_argument("--follow-bone", default="",
                        help="可选：覆盖 controller_root 跟随的骨骼名（如 首 / 上半身2）")
    parser.add_argument("--anchor-object", default="",
                        help="大提琴/竖琴：尾钉或支点所在的空物体名")
    parser.add_argument("--anchor-position", default="",
                        help="大提琴/竖琴：尾钉或支点世界坐标 \"x,y,z\"")
    parser.add_argument("--armature", default="",
                        help="可选：骨架物体名；文件里只有一套骨架时可省略")
    parser.add_argument("--neck-bone", default="",
                        help="可选：指定颈骨（默认按名字认 首 / neck）")
    parser.add_argument("--head-bone", default="",
                        help="可选：指定头骨（默认按名字认 頭 / head）")
    parser.add_argument("--pole-angle", type=float, default=None,
                        help="可选：上半身 IK 的 pole_angle（度）；不给就现场标定")
    parser.add_argument("--head-chain-only", action="store_true",
                        help="只重搭上半身 / 头部控制链（不重装乐器控件；重跑过 setup 之后用）")
    parser.add_argument("--out", default="",
                        help="输出 .blend；省略时在输入文件旁生成 <原名>_<乐器>.blend")
    parser.add_argument("--keep-test", action="store_true",
                        help="保留 test 控件（默认替换完成后删除）")
    parser.add_argument("--skip-pose-check", action="store_true",
                        help="跳过 IK / 复制旋转的动作验收")
    parser.add_argument("--report", default="",
                        help="可选：把结构化验收结果写到 JSON")
    arguments, unknown_arguments = parser.parse_known_args(argv)
    if unknown_arguments:
        log("忽略额外参数：" + " ".join(unknown_arguments))
    return arguments


def ensure_addon_enabled():
    if ADDON_MODULE in bpy.context.preferences.addons:
        return
    log("启用插件 " + ADDON_MODULE)
    bpy.ops.preferences.addon_enable(module=ADDON_MODULE)
    if ADDON_MODULE not in bpy.context.preferences.addons:
        raise InstallError("插件未能启用：" + ADDON_MODULE)


def open_blend_file(file_path):
    if not os.path.isfile(file_path):
        raise InstallError("文件不存在：" + file_path)
    if os.path.normcase(os.path.abspath(bpy.data.filepath)) != os.path.normcase(os.path.abspath(file_path)):
        log("打开文件 " + file_path)
        bpy.ops.wm.open_mainfile(filepath=file_path)


def find_armature(armature_name):
    if armature_name:
        armature = bpy.data.objects.get(armature_name)
        if armature is None or armature.type != "ARMATURE":
            raise InstallError("找不到骨架：" + armature_name)
        return armature
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        names = "、".join(obj.name for obj in armatures) or "（无）"
        raise InstallError(
            "文件里有 %d 套骨架（%s），请用 --armature 指定" % (len(armatures), names))
    return armatures[0]


def find_deformed_meshes(armature):
    meshes = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if any(modifier.type == "ARMATURE" and modifier.object == armature
               for modifier in obj.modifiers):
            meshes.append(obj)
    if not meshes:
        for child in armature.children:
            if child.type == "MESH":
                meshes.append(child)
    return meshes


def evaluated_vertices(mesh_objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    result = {}
    for mesh_object in mesh_objects:
        evaluated = mesh_object.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        result[mesh_object.name] = [vertex.co.copy() for vertex in mesh.vertices]
        evaluated.to_mesh_clear()
    return result


def compare_vertices(before, after):
    max_delta = 0.0
    worst_mesh = ""
    for mesh_name, before_coordinates in before.items():
        after_coordinates = after.get(mesh_name)
        if after_coordinates is None or len(after_coordinates) != len(before_coordinates):
            return float("inf"), mesh_name
        for before_coordinate, after_coordinate in zip(before_coordinates, after_coordinates):
            delta = (after_coordinate - before_coordinate).length
            if delta > max_delta:
                max_delta = delta
                worst_mesh = mesh_name
    return max_delta, worst_mesh


def world_pose_with_scale(target_matrix, current_scale):
    translation, rotation, _ = target_matrix.decompose()
    return Matrix.LocRotScale(translation, rotation, current_scale)


def set_world_pose(obj, target_matrix):
    obj.matrix_world = world_pose_with_scale(target_matrix, obj.matrix_world.to_scale())


def hierarchy_depth(obj):
    depth = 0
    parent = obj.parent
    while parent is not None:
        depth += 1
        parent = parent.parent
    return depth


def rotation_difference_degrees(first, second):
    """两个四元数之间的夹角（度）。

    mathutils 的 `.angle` 在差四元数 w<0 时给的是 ~360°（同一个旋转的另一种表示），
    直接拿来比会把"完全一致"读成"差了 360°"。这里折回 0~180°。
    """
    angle = first.rotation_difference(second).angle
    if angle > math.pi:
        angle = 2.0 * math.pi - angle
    return math.degrees(angle)


def group_by_hierarchy_depth(objects):
    groups = {}
    for obj in objects:
        groups.setdefault(hierarchy_depth(obj), []).append(obj)
    return [groups[key] for key in sorted(groups)]


# ── 初始化 + setup ──────────────────────────────────────────────────────

def initialize_performer(performer_name, instrument_id, armature, instrument_object):
    from music_doll_blender.common import performer_utils

    if not (performer_name.isascii() and performer_name.isalnum()
            and performer_name[0].isalpha()):
        raise InstallError(
            "演奏者名字只能用英文字母和数字、且以字母开头（收到：%s）" % performer_name)

    existing = performer_utils.get_performer(performer_name)
    if existing is not None:
        log("演奏者 %s 已存在，沿用" % performer_name)
        if existing.instrument and existing.instrument != instrument_id:
            raise InstallError(
                "演奏者 %s 已登记为 %s，与 --instrument %s 不一致"
                % (performer_name, existing.instrument, instrument_id))
        return existing

    log("初始化演奏者 %s（乐器 %s）" % (performer_name, instrument_id))
    return performer_utils.get_or_create_performer(
        performer_name, performer_name, instrument_id,
        target_skeleton=armature, target_instrument=instrument_object)


def resolve_variant(adapter, requested_variant):
    variants = (adapter.get("controller_root") or {}).get("variants") or {}
    default_variant = adapter.get("default_variant") or "default"
    variant = requested_variant or default_variant
    if variants and variant not in variants:
        raise InstallError(
            "不支持的变体：%s（可选：%s）"
            % (variant, "、".join(sorted(variants))))
    return variant


def load_adapter_file(file_path):
    import runpy
    namespace = runpy.run_path(file_path)
    adapter = namespace.get("ADAPTER")
    if not isinstance(adapter, dict):
        raise InstallError("适配器文件没有定义 ADAPTER 字典：" + file_path)
    instrument = adapter.get("instrument")
    if not instrument:
        raise InstallError("适配器缺少 instrument 字段：" + file_path)
    INSTRUMENT_ADAPTERS[instrument] = adapter
    log("加载外部适配器 %s（%s）" % (instrument, file_path))
    return instrument


def build_config(adapter, performer, variant):
    custom_builder = adapter.get("build_config")
    if callable(custom_builder):
        return custom_builder(performer, variant)
    module = importlib.import_module(adapter["config_module"])
    config_class = getattr(module, adapter["config_class"])
    kwargs = dict(adapter.get("config_kwargs") or {})
    variant_kwarg = adapter.get("variant_kwarg")
    if variant_kwarg:
        kwargs[variant_kwarg] = variant
    return config_class(
        performer_suffix=performer.name,
        target_skeleton=performer.target_skeleton,
        target_instrument=performer.target_instrument,
        performer_name=performer.name,
        **kwargs)


def run_setup_all_objects(config):
    result = config.setup_all_objects()
    if result is False:
        raise InstallError("setup_all_objects 返回 False（角色未初始化？）")
    return result


# ── controller_root 对齐（所有其它控件的前置条件）────────────────────

def resolve_controller_root_spec(adapter, variant, follow_bone_override):
    spec = adapter.get("controller_root") or {}
    variants = spec.get("variants") or {}
    chosen = variants.get(variant) or spec.get("default") or {"mode": "none"}
    resolved = dict(chosen)
    if follow_bone_override:
        resolved["mode"] = "bone"
        resolved["bone"] = follow_bone_override
    return resolved


def ensure_follow_constraint(control_object, constraint_type, target_object, bone_name):
    existing = None
    for constraint in control_object.constraints:
        if constraint.type == constraint_type:
            existing = constraint
            break
    if existing is None:
        existing = control_object.constraints.new(constraint_type)
        existing.name = {
            "COPY_LOCATION": "Follow_Location",
            "COPY_ROTATION": "Follow_Rotation",
        }.get(constraint_type, constraint_type)
    existing.target = target_object
    if hasattr(existing, "subtarget"):
        existing.subtarget = bone_name
    if hasattr(existing, "head_tail"):
        existing.head_tail = 0.0
    if hasattr(existing, "owner_space"):
        existing.owner_space = "WORLD"
    if hasattr(existing, "target_space"):
        existing.target_space = "WORLD"
    if hasattr(existing, "mix_mode"):
        existing.mix_mode = "REPLACE"
    if hasattr(existing, "use_offset"):
        existing.use_offset = False
    existing.mute = False
    existing.influence = 1.0
    return existing


def parse_anchor_position(text):
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise InstallError("--anchor-position 需要 \"x,y,z\" 三个数，收到：" + text)
    try:
        return Vector((float(parts[0]), float(parts[1]), float(parts[2])))
    except ValueError as error:
        raise InstallError("--anchor-position 解析失败：" + str(error))


def align_controller_root(armature, config, performer_name, adapter, arguments, variant):
    controller_root = bpy.data.objects.get(
        resolve_actual_name(config, "controller_root", performer_name))
    if controller_root is None:
        raise InstallError("找不到 controller_root，setup 没有建出来？")

    spec = resolve_controller_root_spec(adapter, variant, arguments.follow_bone)
    mode = spec.get("mode", "none")
    info = {
        "object": controller_root.name,
        "mode": mode,
    }
    if mode == "none":
        log("controller_root 按乐器规则不跟随骨骼，保持原位")
        return info

    if mode == "bone":
        bone_name = spec.get("bone") or "首"
        if bone_name not in armature.pose.bones:
            candidates = [bone.name for bone in armature.pose.bones
                          if any(token in bone.name
                                 for token in ("首", "neck", "上半身", "胸", "chest"))]
            raise InstallError(
                "找不到 controller_root 要跟随的骨骼 %s。候选：%s"
                % (bone_name, "、".join(candidates) or "（无）"))
        ensure_follow_constraint(controller_root, "COPY_LOCATION", armature, bone_name)
        ensure_follow_constraint(controller_root, "COPY_ROTATION", armature, bone_name)
        bpy.context.view_layer.update()

        target_matrix = armature.matrix_world @ armature.pose.bones[bone_name].matrix
        actual_matrix = controller_root.matrix_world
        translation_error = (
            actual_matrix.translation - target_matrix.translation).length
        rotation_error = rotation_difference_degrees(
            actual_matrix.to_quaternion(), target_matrix.to_quaternion())
        info.update({
            "bone": bone_name,
            "translation_error_m": translation_error,
            "rotation_error_deg": rotation_error,
        })
        log("controller_root 跟随骨骼 %s：误差 %.9f m / %.9f°"
            % (bone_name, translation_error, rotation_error))
        if translation_error > 1e-5 or rotation_error > 0.01:
            raise InstallError(
                "controller_root 没有对齐到骨骼 %s（%.6f m / %.6f°）"
                % (bone_name, translation_error, rotation_error))
        return info

    if mode == "anchor_required":
        anchor_object = None
        if arguments.anchor_object:
            anchor_object = bpy.data.objects.get(arguments.anchor_object)
            if anchor_object is None:
                raise InstallError("找不到锚点物体：" + arguments.anchor_object)

        if anchor_object is not None:
            world_matrix = anchor_object.matrix_world.copy()
            controller_root.matrix_world = world_matrix
            info["anchor_object"] = anchor_object.name
        elif arguments.anchor_position:
            position = parse_anchor_position(arguments.anchor_position)
            controller_root.matrix_world = Matrix.Translation(position)
            info["anchor_position"] = [round(value, 6) for value in position]
        else:
            raise InstallError(
                "%s 必须先指定尾钉 / 支点位置：用 --anchor-object 或 "
                "--anchor-position \"x,y,z\"；否则 controller_root 没有依据，"
                "后面的控件对齐不能做。" % spec.get("label", "这个乐器"))
        bpy.context.view_layer.update()
        info["world_location"] = [
            round(value, 6) for value in controller_root.matrix_world.translation]
        log("controller_root 放在锚点：%s" % info["world_location"])
        return info

    raise InstallError("未知的 controller_root 模式：" + str(mode))


# ── 映射解析 ────────────────────────────────────────────────────────────

def resolve_actual_name(config, short_name, performer_name):
    obj_name_method = getattr(config, "obj_name", None)
    if callable(obj_name_method):
        return obj_name_method(short_name)
    from music_doll_blender.common import performer_utils
    return performer_utils.resolve(short_name, performer_name)


def create_fallback_controls(adapter, config, performer, armature):
    """给乐器模块不生成的 test 对照项补一个同位置的空物体控件。

    典型情况：吉他模块没有脚部控件，但骨架的腿 IK 仍需要 F_L / FP_L 目标。
    适配器用 fallback_controls 声明这些项；控件挂在演奏者根/骨架下，
    位置抄 test 控件，随后正常参与映射/替换/删除 test。
    """
    performer_name = performer.name
    created = []
    for test_name, spec in (adapter.get("fallback_controls") or {}).items():
        test_object = bpy.data.objects.get(test_name)
        if test_object is None:
            continue
        short_name = spec["short"]
        actual_name = resolve_actual_name(config, short_name, performer_name)
        if bpy.data.objects.get(actual_name) is not None:
            continue
        control_object = bpy.data.objects.new(actual_name, None)
        control_object.empty_display_type = spec.get("display", "PLAIN_AXES")
        control_object.empty_display_size = float(spec.get("size", 0.1))
        control_object.hide_render = True

        parent_spec = spec.get("parent", "armature")
        if parent_spec == "armature":
            parent_object = armature
        elif parent_spec == "performer_root":
            from music_doll_blender.common import performer_utils
            parent_object = bpy.data.objects.get(
                performer_utils.get_performer_root_name(performer))
            if parent_object is None:
                parent_object = armature
        else:
            parent_object = bpy.data.objects.get(
                resolve_actual_name(config, parent_spec, performer_name))
        if parent_object is not None:
            # 挂父级只能"无逆"：parent inverse 写成父级世界矩阵的逆时两者互相抵消，
            # location 里存下的就是世界值 —— Blender 里自洽，导出到引擎会再乘一遍父级。
            control_object.parent = parent_object
            control_object.matrix_parent_inverse.identity()

        collection_name = spec.get("collection", "")
        collection_object = None
        if collection_name:
            collection_object = bpy.data.collections.get(
                resolve_actual_name(config, collection_name, performer_name))
            if collection_object is None:
                collection_object = bpy.data.collections.get(collection_name)
        if collection_object is None:
            collection_object = bpy.context.scene.collection
        collection_object.objects.link(control_object)
        control_object.matrix_world = test_object.matrix_world.copy()
        created.append({
            "test": test_name,
            "actual": control_object.name,
            "parent": parent_object.name if parent_object else None,
            "collection": collection_object.name,
        })
        log("补控件 %s（%s 没有对应实际控件）" % (control_object.name, test_name))
    return created


def build_mapping(mapping, config, performer_name):
    test_objects = {}
    actual_objects = {}
    missing_test = []
    missing_actual = []
    for test_name, short_name in mapping.items():
        test_object = bpy.data.objects.get(test_name)
        if test_object is None:
            missing_test.append(test_name)
            continue
        actual_name = resolve_actual_name(config, short_name, performer_name)
        actual_object = bpy.data.objects.get(actual_name)
        if actual_object is None:
            missing_actual.append(actual_name)
            continue
        test_objects[test_name] = test_object
        actual_objects[test_name] = actual_object
    return test_objects, actual_objects, missing_test, missing_actual


# ── 上半身 / 头部控制链 ─────────────────────────────────────────────────

def resolve_head_chain_spec(adapter, config, performer_name, arguments):
    """适配器里声明了 head_chain 的乐器：把短名解析成实际对象名与判据参数。

    形状（适配器里的写法）：
        "head_chain": {
            "head_control": "Head_Control",   # 乐器模块建的头部控制器
            "look_at": "Look_At",             # 视点（多数模块挂在 Middle_Hand 下）
            "test_head_control": "Head_Control_test",   # rig 阶段留的 test 控件（可选）
            "test_look_at": "Look_At_test",
            "look_distance": 1.0,             # 视点放在前方 链长 × 这个倍数
            "pole_angle": None,               # None = 现场标定
            "neck_bone": "", "head_bone": "", # 省略 = 按名字认
        }
    """
    declared = adapter.get("head_chain")
    if not declared:
        return None
    head_control_short = declared.get("head_control", "Head_Control")
    look_at_short = declared.get("look_at", "Look_At")
    return {
        "head_control_short": head_control_short,
        "look_at_short": look_at_short,
        "head_control": resolve_actual_name(
            config, head_control_short, performer_name),
        "look_at": resolve_actual_name(config, look_at_short, performer_name),
        "test_head_control": declared.get("test_head_control", "Head_Control_test"),
        "test_look_at": declared.get("test_look_at", "Look_At_test"),
        "neck_bone": arguments.neck_bone or declared.get("neck_bone", ""),
        "head_bone": arguments.head_bone or declared.get("head_bone", ""),
        "chain_count": declared.get("chain_count", 0),
        "look_distance": declared.get("look_distance", 1.0),
        "pole_angle": (arguments.pole_angle if arguments.pole_angle is not None
                       else declared.get("pole_angle")),
    }


def plan_head_chain(head_spec, armature):
    """判断这一轮该怎么接头部链：没有这个乐器 / 控件不全 / rig 阶段已搭好 / 从零搭。"""
    if head_spec is None:
        return {"mode": "absent"}
    head_control = bpy.data.objects.get(head_spec["head_control"])
    look_at = bpy.data.objects.get(head_spec["look_at"])
    missing = [name for name, obj in ((head_spec["head_control"], head_control),
                                      (head_spec["look_at"], look_at)) if obj is None]
    if missing:
        return {"mode": "missing", "spec": head_spec, "missing": missing}
    test_head = bpy.data.objects.get(head_spec["test_head_control"])
    test_look = bpy.data.objects.get(head_spec["test_look_at"])
    plan = {
        "spec": head_spec,
        "head_control": head_control,
        "look_at": look_at,
        "spine": None,
    }
    try:
        plan["spine"] = head_chain.detect_spine(armature, head_spec, lambda _message: None)
    except head_chain.HeadChainError:
        plan["spine"] = None
    if test_head is not None and test_look is not None:
        # rig 阶段（rig_upper）已经搭好链：把模块控件对齐到 test 控件、替换引用即可，
        # 位置与 pole_angle 都以 rig 阶段为准。
        plan["mode"] = "test"
        plan["test_mapping"] = {test_head.name: head_spec["head_control_short"],
                                test_look.name: head_spec["look_at_short"]}
    else:
        plan["mode"] = "build"
    return plan


def freeze_head_chain(plan, armature):
    """动作采样前临时静音上半身链（见 head_chain.constraints_to_freeze 的说明）。"""
    if plan.get("mode") != "test" or not plan.get("spine"):
        return None
    frozen = head_chain.constraints_to_freeze(
        armature, plan["head_control"], plan["spine"]["head"])
    if not frozen:
        return None
    log("动作采样期间临时静音上半身链（%s）" % "、".join(
        "%s.%s" % (pose_bone.name, constraint.name) for pose_bone, constraint in frozen))
    return head_chain.mute_all(frozen)


def finish_head_chain(plan, armature, deformed_meshes):
    """按 plan 把上半身 / 头部链接好，返回结构化结果（失败时抛 InstallError）。"""
    if plan["mode"] in ("absent", "missing"):
        return {"mode": plan["mode"],
                "missing": plan.get("missing", []),
                "passed": True}
    mode = plan["mode"]
    log("上半身 / 头部链：%s（%s）" % (
        "沿用 rig 阶段搭好的链，替换成模块控件" if mode == "test"
        else "按规则新建（颈上 IK + 头骨复制旋转）", plan["spec"]["head_control"]))
    result = head_chain.build(
        armature, plan["head_control"], plan["look_at"], plan["spec"], log,
        place=(mode == "build"),
        connect=(mode == "build"),
        strip=(mode == "build"),
        calibrate=True,
        mesh_reader=lambda: evaluated_vertices(deformed_meshes))
    result["mode"] = mode
    for check in result["checks"]:
        log("  [%s] %s —— %s" % ("PASS" if check["ok"] else "FAIL",
                                 check["name"], check["detail"]))
    if not result["passed"]:
        failed = [check["name"] for check in result["checks"] if not check["ok"]]
        raise InstallError("上半身 / 头部链自检失败：" + "；".join(failed))
    return result


# ── 对齐 ────────────────────────────────────────────────────────────────

def snapshot_test_matrices(test_objects):
    return {name: obj.matrix_world.copy() for name, obj in test_objects.items()}


def align_controls(test_matrices, actual_objects):
    ordered = list(actual_objects.values())
    for depth_group in group_by_hierarchy_depth(ordered):
        for actual_object in depth_group:
            test_name = next(
                name for name, value in actual_objects.items() if value == actual_object)
            set_world_pose(actual_object, test_matrices[test_name])
        bpy.context.view_layer.update()
    bpy.context.view_layer.update()


def check_alignment(test_matrices, actual_objects):
    max_translation = 0.0
    max_rotation_degrees = 0.0
    worst = []
    for test_name, actual_object in actual_objects.items():
        test_translation, test_rotation, _ = test_matrices[test_name].decompose()
        actual_translation, actual_rotation, _ = actual_object.matrix_world.decompose()
        translation_error = (actual_translation - test_translation).length
        rotation_error = rotation_difference_degrees(actual_rotation, test_rotation)
        max_translation = max(max_translation, translation_error)
        max_rotation_degrees = max(max_rotation_degrees, rotation_error)
        if translation_error > 1e-5 or rotation_error > 0.01:
            worst.append({
                "test": test_name,
                "actual": actual_object.name,
                "translation_error": translation_error,
                "rotation_error_deg": rotation_error,
            })
    return max_translation, max_rotation_degrees, worst


# ── 引用替换 ────────────────────────────────────────────────────────────

def iter_constraint_references(constraint):
    for attribute in ("target", "pole_target"):
        target = getattr(constraint, attribute, None)
        if target is not None:
            yield constraint, attribute, target


def replace_all_references(test_objects, actual_objects):
    """把所有指向 test 控件的引用换成实际控件（骨骼约束、物体约束、驱动、修改器、父级）。"""
    replaced = []
    test_names = set(test_objects)

    def replacement_for(obj):
        if obj is None:
            return None
        return actual_objects.get(obj.name)

    # 骨骼约束
    for armature in [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]:
        for pose_bone in armature.pose.bones:
            for constraint in pose_bone.constraints:
                for _, attribute, target in list(iter_constraint_references(constraint)):
                    actual = replacement_for(target)
                    if actual is not None:
                        setattr(constraint, attribute, actual)
                        replaced.append({
                            "where": "%s/%s.%s" % (armature.name, pose_bone.name, constraint.name),
                            "attribute": attribute,
                            "from": target.name,
                            "to": actual.name,
                        })

    # 物体约束（test 控件自己之间的父子/引用不用管，它们随后会被删除）
    for obj in bpy.data.objects:
        if obj.name in test_names:
            continue
        for constraint in obj.constraints:
            for _, attribute, target in list(iter_constraint_references(constraint)):
                actual = replacement_for(target)
                if actual is not None:
                    setattr(constraint, attribute, actual)
                    replaced.append({
                        "where": "%s/%s" % (obj.name, constraint.name),
                        "attribute": attribute,
                        "from": target.name,
                        "to": actual.name,
                    })

        # 修改器
        for modifier in obj.modifiers:
            for attribute in ("object", "target"):
                target = getattr(modifier, attribute, None)
                actual = replacement_for(target)
                if actual is not None:
                    setattr(modifier, attribute, actual)
                    replaced.append({
                        "where": "%s/%s" % (obj.name, modifier.name),
                        "attribute": attribute,
                        "from": target.name,
                        "to": actual.name,
                    })

        # 父级
        actual_parent = replacement_for(obj.parent)
        if actual_parent is not None:
            previous_parent_name = obj.parent.name
            world_matrix = obj.matrix_world.copy()
            obj.parent = actual_parent
            # 换父级同样是"无逆"：旧父级留下的 parent inverse 不归零，
            # 写回世界矩阵算出来的本地值就还是带旧父级那一层抵消的假局部值。
            obj.matrix_parent_inverse.identity()
            obj.matrix_world = world_matrix
            replaced.append({
                "where": obj.name,
                "attribute": "parent",
                "from": previous_parent_name,
                "to": actual_parent.name,
            })

        # 驱动变量
        if obj.animation_data and obj.animation_data.drivers:
            for fcurve in obj.animation_data.drivers:
                for variable in fcurve.driver.variables:
                    for variable_target in variable.targets:
                        actual = replacement_for(variable_target.id)
                        if actual is not None:
                            previous_id_name = variable_target.id.name
                            variable_target.id = actual
                            replaced.append({
                                "where": "%s/driver:%s" % (obj.name, fcurve.data_path),
                                "attribute": "driver_variable " + variable.name,
                                "from": previous_id_name,
                                "to": actual.name,
                            })
    return replaced


def find_remaining_test_references(test_objects):
    test_names = {obj.name for obj in bpy.data.objects
                  if obj.name.endswith("_test")}
    remaining = []

    def collect(obj, where, attribute, target):
        if target is not None and target.name in test_names:
            remaining.append({
                "where": where,
                "attribute": attribute,
                "target": target.name,
                "object": obj.name if obj else "",
            })

    for armature in [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]:
        for pose_bone in armature.pose.bones:
            for constraint in pose_bone.constraints:
                for _, attribute, target in iter_constraint_references(constraint):
                    collect(armature, "%s/%s.%s" % (armature.name, pose_bone.name, constraint.name),
                            attribute, target)
    for obj in bpy.data.objects:
        if obj.name in test_names:
            continue
        for constraint in obj.constraints:
            for _, attribute, target in iter_constraint_references(constraint):
                collect(obj, "%s/%s" % (obj.name, constraint.name), attribute, target)
        for modifier in obj.modifiers:
            for attribute in ("object", "target"):
                collect(obj, "%s/%s" % (obj.name, modifier.name), attribute,
                        getattr(modifier, attribute, None))
        collect(obj, obj.name, "parent", obj.parent)
        if obj.animation_data and obj.animation_data.drivers:
            for fcurve in obj.animation_data.drivers:
                for variable in fcurve.driver.variables:
                    for variable_target in variable.targets:
                        collect(obj, "%s/driver:%s" % (obj.name, fcurve.data_path),
                                "driver_variable " + variable.name, variable_target.id)
    return remaining


# ── 验收 ────────────────────────────────────────────────────────────────

def constraint_by_name(armature, name):
    for pose_bone in armature.pose.bones:
        for constraint in pose_bone.constraints:
            if constraint.name == name:
                return pose_bone, constraint
    return None, None


def chain_bones_from_ik(pose_bone, chain_count):
    bones = [pose_bone]
    current = pose_bone
    while len(bones) < chain_count and current.parent is not None:
        current = current.parent
        bones.append(current)
    bones.reverse()
    return bones


def bone_head_world(armature, pose_bone):
    return armature.matrix_world @ pose_bone.head


def bone_tail_world(armature, pose_bone):
    return armature.matrix_world @ pose_bone.tail


def bone_rotation_world(armature, pose_bone):
    return (armature.matrix_world @ pose_bone.matrix).to_quaternion()


def perpendicular_deviation(point, root, tip):
    chord = tip - root
    if chord.length < 1e-9:
        return Vector((0.0, 0.0, 0.0))
    chord_unit = chord.normalized()
    relative = point - root
    return relative - chord_unit * relative.dot(chord_unit)


def pole_alignment_degrees(armature, ik_constraint, pose_bone):
    chain = chain_bones_from_ik(pose_bone, ik_constraint.chain_count)
    root = bone_head_world(armature, chain[0])
    middle = bone_head_world(armature, chain[len(chain) // 2])
    tip = bone_tail_world(armature, pose_bone)
    pole = ik_constraint.pole_target.matrix_world.translation
    deviation = perpendicular_deviation(middle, root, tip)
    pole_deviation = perpendicular_deviation(pole, root, tip)
    if deviation.length < 1e-9 or pole_deviation.length < 1e-9:
        return None
    return math.degrees(deviation.angle(pole_deviation))


def pose_snapshot(armature):
    return {pose_bone.name: (armature.matrix_world @ pose_bone.matrix).copy()
            for pose_bone in armature.pose.bones}


def apply_behavior_delta(target_object, sample, control_objects):
    delta_kind = sample["kind"]
    if delta_kind == "translate":
        offset = Vector(sample["delta"])
        target_object.matrix_world = Matrix.Translation(offset) @ target_object.matrix_world
    elif delta_kind == "rotate_world":
        axis = Vector(sample["axis"]).normalized()
        angle = math.radians(sample["degrees"])
        translation, rotation, scale = target_object.matrix_world.decompose()
        rotation = Quaternion(axis, angle) @ rotation
        target_object.matrix_world = Matrix.LocRotScale(translation, rotation, scale)
    elif delta_kind == "translate_toward":
        other_object = control_objects[sample["other"]]
        direction = (other_object.matrix_world.translation
                     - target_object.matrix_world.translation)
        if direction.length > 1e-9:
            offset = direction.normalized() * sample["distance"]
            target_object.matrix_world = Matrix.Translation(offset) @ target_object.matrix_world
    else:
        raise InstallError("未知的动作样本类型：" + str(delta_kind))


def sample_behavior(armature, control_objects, samples):
    """逐样本摆一次目标，记录全身骨骼姿态，然后恢复。"""
    bpy.context.view_layer.update()
    rest_snapshot = pose_snapshot(armature)
    results = {}
    for sample in samples:
        target_object = control_objects[sample["target"]]
        rest_matrix = target_object.matrix_world.copy()
        apply_behavior_delta(target_object, sample, control_objects)
        bpy.context.view_layer.update()
        moved_snapshot = pose_snapshot(armature)
        max_bone_movement = max(
            (moved_snapshot[bone_name].translation
             - rest_snapshot[bone_name].translation).length
            for bone_name in rest_snapshot)
        results[sample["name"]] = {
            "moved": moved_snapshot,
            "max_bone_movement": max_bone_movement,
        }
        target_object.matrix_world = rest_matrix
        bpy.context.view_layer.update()
    restored_snapshot = pose_snapshot(armature)
    restore_error = max(
        (restored_snapshot[bone_name].translation
         - rest_snapshot[bone_name].translation).length
        for bone_name in rest_snapshot)
    return results, restore_error


def compare_behavior(reference_results, actual_results):
    """同一动作分别由 test 和实际控件驱动，逐骨比姿态差。"""
    summary = {}
    max_translation = 0.0
    max_rotation = 0.0
    for sample_name, reference in reference_results.items():
        actual = actual_results.get(sample_name)
        if actual is None:
            raise InstallError("动作样本缺失：" + sample_name)
        sample_translation = 0.0
        sample_rotation = 0.0
        for bone_name, reference_matrix in reference["moved"].items():
            actual_matrix = actual["moved"].get(bone_name)
            if actual_matrix is None:
                continue
            sample_translation = max(
                sample_translation,
                (reference_matrix.translation - actual_matrix.translation).length)
            sample_rotation = max(
                sample_rotation,
                rotation_difference_degrees(reference_matrix.to_quaternion(),
                                            actual_matrix.to_quaternion()))
        max_translation = max(max_translation, sample_translation)
        max_rotation = max(max_rotation, sample_rotation)
        summary[sample_name] = {
            "max_bone_movement_m": reference["max_bone_movement"],
            "test_vs_actual_translation_m": sample_translation,
            "test_vs_actual_rotation_deg": sample_rotation,
        }
    return summary, max_translation, max_rotation


def rest_pole_angles(armature):
    angles = {}
    for constraint_name in ("MD_IK_arm.L", "MD_IK_arm.R", "MD_IK_leg.L",
                            "MD_IK_leg.R", "MD_IK_index.L", "MD_IK_index.R"):
        pose_bone, constraint = constraint_by_name(armature, constraint_name)
        if pose_bone is None or constraint.pole_target is None:
            continue
        angles[constraint_name] = pole_alignment_degrees(armature, constraint, pose_bone)
    return angles


def describe_head_chain(head_info):
    """进度文本块里那一行：装没装、装在哪、链长多少。"""
    if not head_info:
        return "未处理"
    mode = head_info.get("mode")
    if mode == "absent":
        return "这个乐器没有头部控件，跳过"
    if mode == "missing":
        return "控件不全，跳过（缺 %s）" % "、".join(head_info.get("missing") or [])
    spine = head_info.get("spine") or {}
    return "%s：颈 %s、链 %s、极向量 %s、pole_angle %s°、rest 网格位移 %.7f m" % (
        "沿用 rig 阶段的链" if mode == "test" else "新建",
        spine.get("neck", "?"),
        " → ".join(spine.get("chain") or []),
        head_info.get("look_at", "?"),
        head_info.get("pole_angle_deg", "?"),
        head_info.get("rest_mesh_delta") or 0.0)


def write_progress_text(summary):
    text_block = bpy.data.texts.get(PROGRESS_TEXT_NAME)
    if text_block is None:
        text_block = bpy.data.texts.new(PROGRESS_TEXT_NAME)
    lines = [
        "MusicDoll 乐器控件安装记录（本段由脚本重写）",
        "<<< AUTO:BEGIN >>>",
        "演奏者: %s" % summary["performer"],
        "乐器: %s" % summary["instrument"],
        "变体: %s" % summary.get("variant", ""),
        "controller_root: %s" % json.dumps(
            summary.get("controller_root", {}), ensure_ascii=False),
        "控件映射: %d 项" % summary["mapped_control_count"],
        "约束引用替换: %d 处" % summary["replaced_reference_count"],
        "对齐最大误差: %.9f m / %.9f°" % (
            summary["align_max_translation"], summary["align_max_rotation_deg"]),
        "rest 网格最大位移: %.9f m" % summary["rest_mesh_max_delta"],
        "test 控件: %s" % ("已保留" if summary["test_kept"] else "已删除"),
        "动作等价: 最大位移差 %.9f m / 旋转差 %.9f°" % (
            summary["behavior_max_translation_m"], summary["behavior_max_rotation_deg"]),
        "极向量偏离: %s" % json.dumps(summary["pole_angles_deg"], ensure_ascii=False),
        "上半身/头部链: %s" % describe_head_chain(summary.get("head_chain")),
        "<<< AUTO:END >>>",
    ]
    text_block.clear()
    text_block.write("\n".join(lines) + "\n")


def save_output(file_path):
    output_directory = os.path.dirname(os.path.abspath(file_path))
    if output_directory:
        os.makedirs(output_directory, exist_ok=True)
    try:
        bpy.ops.wm.save_as_mainfile(filepath=file_path)
    except Exception as exc:
        if not os.path.isfile(file_path):
            raise InstallError("保存失败：%s" % exc)
        log("保存时抛出异常，但文件已写出：%s" % exc)


# ── 主流程 ──────────────────────────────────────────────────────────────

def run_head_chain_only(arguments, adapter, armature):
    """只重搭上半身 / 头部链：重跑过 setup_all_objects 之后修一次用。

    为什么不直接重跑安装脚本：装过乐器控件的文件已经没有 test 控件了；而 setup 会把
    `Look_At` 拉回 `Middle_Hand` 的原点（模块自己这么写），链的位置就跟着错，所以需要单独一步。
    """
    from music_doll_blender.common import performer_utils

    performer = performer_utils.get_performer(arguments.performer)
    if performer is None:
        raise InstallError(
            "文件里没有登记演奏者 %s；这个参数只用来修已经装过控件的文件"
            % arguments.performer)
    variant = resolve_variant(adapter, arguments.variant)
    config = build_config(adapter, performer, variant)
    deformed_meshes = find_deformed_meshes(armature)
    head_spec = resolve_head_chain_spec(adapter, config, performer.name, arguments)
    head_plan = plan_head_chain(head_spec, armature)
    if head_plan["mode"] in ("absent", "missing"):
        raise InstallError("这个乐器没有可修的头部链（%s）"
                           % describe_head_chain({"mode": head_plan["mode"],
                                                  "missing": head_plan.get("missing")}))
    if head_plan["mode"] == "test":
        # 还有 test 控件在：说明链是 rig 阶段搭的，应该走完整安装流程去替换，不是修。
        head_plan["mode"] = "build"
    head_info = finish_head_chain(head_plan, armature, deformed_meshes)

    text_block = bpy.data.texts.get(PROGRESS_TEXT_NAME)
    if text_block is not None:
        extra = "\n".join([
            "上半身/头部链（重搭）: %s" % describe_head_chain(head_info),
        ])
        text_block.write("\n" + extra + "\n")

    output_path = arguments.out
    if not output_path:
        root, extension = os.path.splitext(arguments.file)
        output_path = "%s_head_chain%s" % (root, extension)
    if os.path.normcase(os.path.abspath(output_path)) == os.path.normcase(
            os.path.abspath(arguments.file)):
        raise InstallError("输出文件不能覆盖输入文件（--out 换个路径）")
    save_output(output_path)
    summary = {
        "performer": performer.name,
        "instrument": arguments.instrument,
        "armature": armature.name,
        "head_chain": head_info,
        "output": output_path,
    }
    print("HEAD_CHAIN_RESULT " + json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    arguments = parse_arguments()
    ensure_addon_enabled()
    open_blend_file(arguments.file)

    adapter = INSTRUMENT_ADAPTERS.get(arguments.instrument)
    if arguments.adapter_file:
        loaded_instrument = load_adapter_file(arguments.adapter_file)
        if loaded_instrument != arguments.instrument:
            raise InstallError(
                "适配器乐器是 %s，与 --instrument %s 不一致"
                % (loaded_instrument, arguments.instrument))
        adapter = INSTRUMENT_ADAPTERS[arguments.instrument]
    if adapter is None:
        raise InstallError(
            "未知乐器 %s；请用 --adapter-file 提供适配器，或使用内置的 %s"
            % (arguments.instrument, "、".join(sorted(INSTRUMENT_ADAPTERS))))
    armature = find_armature(arguments.armature)
    log("骨架：" + armature.name)

    if arguments.head_chain_only:
        run_head_chain_only(arguments, adapter, armature)
        return

    # 先确认 test 控件在不在：全都不在 = 已经装过，做一次只读验收就退出
    present_test_names = [name for name in adapter["test_to_short"]
                          if bpy.data.objects.get(name) is not None]
    if not present_test_names:
        raise InstallError(
            "找不到任何 test 控件；这个文件可能已经装过乐器控件。"
            "如需重装，请用 rig skill 保留 test 控件的版本。")

    instrument_object = None
    if arguments.instrument_object:
        instrument_object = bpy.data.objects.get(arguments.instrument_object)
        if instrument_object is None:
            raise InstallError("找不到乐器物体：" + arguments.instrument_object)

    deformed_meshes = find_deformed_meshes(armature)
    if not deformed_meshes:
        raise InstallError("找不到受骨架驱动的 Mesh")
    log("受驱动 Mesh：" + "、".join(obj.name for obj in deformed_meshes))

    performer = initialize_performer(
        arguments.performer, arguments.instrument, armature, instrument_object)
    variant = resolve_variant(adapter, arguments.variant)
    config = build_config(adapter, performer, variant)
    run_setup_all_objects(config)

    # 关键顺序：controller_root 必须先跟到人物骨骼（颈骨/胸骨）或锚点，
    # 它是所有实际控件的父坐标系；它没定下来就摆下面的控件，等于白摆。
    controller_root_info = align_controller_root(
        armature, config, performer.name, adapter, arguments, variant)

    fallback_info = create_fallback_controls(
        adapter, config, performer, armature)

    # 有头部控件的乐器（架子鼓 / 钢琴 / 古筝…）：先把这一轮该怎么接链定下来。
    # mode=test  —— rig 阶段（rig_upper）已经搭好链，这里只把模块控件对齐过去、替换引用；
    # mode=build —— 没有链，等后面的控件替换做完，再按规则新建。
    head_spec = resolve_head_chain_spec(adapter, config, performer.name, arguments)
    head_plan = plan_head_chain(head_spec, armature)
    if head_plan["mode"] == "absent":
        log("这个乐器没有声明 head_chain，跳过上半身 / 头部链")
    elif head_plan["mode"] == "missing":
        log("乐器声明了 head_chain，但控件不全（缺 %s），跳过上半身 / 头部链"
            % "、".join(head_plan["missing"]))
    else:
        log("上半身 / 头部链：%s" % (
            "rig 阶段已搭好，本轮替换成模块控件" if head_plan["mode"] == "test"
            else "本轮按规则新建"))

    # rest 网格基线放在 setup 之后：初始化会改名/归位对象，但不改变形变；
    # 真正要比较的是“test 驱动”与“实际控件驱动”两个状态。
    vertices_before = evaluated_vertices(deformed_meshes)

    mapping = dict(adapter["test_to_short"])
    mapping.update(head_plan.get("test_mapping") or {})
    test_objects, actual_objects, missing_test, missing_actual = build_mapping(
        mapping, config, performer.name)
    if missing_actual:
        raise InstallError("缺少实际控件：" + "、".join(sorted(missing_actual)))
    if missing_test:
        raise InstallError(
            "缺少 test 控件：" + "、".join(sorted(missing_test))
            + "。请确认这是 rig skill 完整改造过的文件。")
    log("映射 %d 个控件" % len(test_objects))

    test_matrices = snapshot_test_matrices(test_objects)
    align_controls(test_matrices, actual_objects)
    align_max_translation, align_max_rotation, align_worst = check_alignment(
        test_matrices, actual_objects)
    log("对齐最大误差：%.9f m / %.9f°" % (align_max_translation, align_max_rotation))
    if align_worst:
        raise InstallError("控件对齐超差：" + json.dumps(align_worst, ensure_ascii=False))

    behavior_samples = adapter.get("behavior_samples") or []
    behavior_reference = {}
    behavior_restore_error_reference = 0.0
    if behavior_samples and not arguments.skip_pose_check:
        # 视点在多数乐器里跟手走，动一下手躯干就跟着弯；采样期间临时把这条链静音，
        # 否则“test 控件 vs 实际控件”的全身逐骨对比必然对不上（那是设计行为，不是装错）。
        freeze_states = freeze_head_chain(head_plan, armature)
        behavior_reference, behavior_restore_error_reference = sample_behavior(
            armature, test_objects, behavior_samples)
        if freeze_states:
            head_chain.restore_mutes(freeze_states)
        log("动作基线（test 驱动）采样完成：" + "、".join(behavior_reference))
        if behavior_restore_error_reference > 1e-5:
            raise InstallError(
                "动作基线采样后没有回到 rest（%.9f m）"
                % behavior_restore_error_reference)

    replaced_references = replace_all_references(test_objects, actual_objects)
    bpy.context.view_layer.update()
    log("替换约束/驱动引用 %d 处" % len(replaced_references))

    vertices_after = evaluated_vertices(deformed_meshes)
    rest_mesh_max_delta, worst_mesh = compare_vertices(vertices_before, vertices_after)
    log("rest 网格最大位移：%.9f m（%s）" % (rest_mesh_max_delta, worst_mesh))
    if rest_mesh_max_delta > 1e-5:
        raise InstallError(
            "替换后 rest 网格发生位移（%.9f m），说明对齐或约束替换不对"
            % rest_mesh_max_delta)

    remaining = find_remaining_test_references(test_objects)
    if remaining:
        raise InstallError(
            "还有 %d 处引用指向 test 控件：" % len(remaining)
            + json.dumps(remaining[:20], ensure_ascii=False))

    behavior_summary = {}
    behavior_max_translation = 0.0
    behavior_max_rotation = 0.0
    behavior_restore_error_actual = 0.0
    pole_angles = {}
    if behavior_samples and not arguments.skip_pose_check:
        freeze_states = freeze_head_chain(head_plan, armature)
        behavior_actual, behavior_restore_error_actual = sample_behavior(
            armature, actual_objects, behavior_samples)
        if freeze_states:
            head_chain.restore_mutes(freeze_states)
        behavior_summary, behavior_max_translation, behavior_max_rotation = compare_behavior(
            behavior_reference, behavior_actual)
        log("动作等价（test 与实际逐骨对比）：最大位移差 %.9f m / 旋转差 %.9f°"
            % (behavior_max_translation, behavior_max_rotation))
        log("动作等价明细：" + json.dumps(behavior_summary, ensure_ascii=False))
        sample_by_name = {sample["name"]: sample for sample in behavior_samples}
        for sample_name, values in behavior_summary.items():
            sample = sample_by_name[sample_name]
            tolerance_m = sample.get("tolerance_m", 1e-4)
            tolerance_deg = sample.get("tolerance_deg", 0.01)
            if (values["test_vs_actual_translation_m"] > tolerance_m
                    or values["test_vs_actual_rotation_deg"] > tolerance_deg):
                raise InstallError(
                    "动作等价验收失败：%s 位移差 %.9f m（容差 %.6f）、旋转差 %.6f°（容差 %.6f）"
                    % (sample_name,
                       values["test_vs_actual_translation_m"], tolerance_m,
                       values["test_vs_actual_rotation_deg"], tolerance_deg))
        if behavior_restore_error_actual > 1e-5:
            raise InstallError(
                "动作验收采样后没有回到 rest（%.9f m）" % behavior_restore_error_actual)

        pole_angles = rest_pole_angles(armature)
        log("极向量偏离：" + json.dumps(pole_angles, ensure_ascii=False))
        for constraint_name, angle in pole_angles.items():
            if angle is not None and angle > 2.0:
                raise InstallError(
                    "极向量偏离超差：%s=%.3f°" % (constraint_name, angle))

    # 复核恢复 rest 之后网格仍然一致
    vertices_restored = evaluated_vertices(deformed_meshes)
    restored_delta, restored_worst = compare_vertices(vertices_before, vertices_restored)
    if restored_delta > 1e-5:
        raise InstallError(
            "动作验收后未回到 rest（最大位移 %.9f m，%s）"
            % (restored_delta, restored_worst))

    # 最后接上半身 / 头部链：放在全部通用验收之后，它自己的 rest 网格位移单独量，
    # 免得“控件对齐有没有动网格”和“加链有没有动网格”两笔账混在一起。
    head_info = finish_head_chain(head_plan, armature, deformed_meshes)
    log("上半身 / 头部链：%s；pole_angle %s；rest 网格位移 %s m" % (
        head_info.get("mode"),
        head_info.get("pole_angle_deg", "-"),
        "%.7f" % head_info["rest_mesh_delta"]
        if head_info.get("rest_mesh_delta") is not None else "-"))

    test_kept = bool(arguments.keep_test)
    if not test_kept:
        for test_object in test_objects.values():
            if test_object.name in bpy.data.objects:
                bpy.data.objects.remove(test_object, do_unlink=True)
        log("已删除 %d 个 test 控件" % len(test_objects))

    summary = {
        "performer": performer.name,
        "instrument": arguments.instrument,
        "variant": variant,
        "armature": armature.name,
        "controller_root": controller_root_info,
        "fallback_controls": fallback_info,
        "mapped_control_count": len(actual_objects),
        "replaced_reference_count": len(replaced_references),
        "align_max_translation": align_max_translation,
        "align_max_rotation_deg": align_max_rotation,
        "rest_mesh_max_delta": rest_mesh_max_delta,
        "behavior": behavior_summary,
        "behavior_max_translation_m": behavior_max_translation,
        "behavior_max_rotation_deg": behavior_max_rotation,
        "pole_angles_deg": pole_angles,
        "head_chain": head_info,
        "test_kept": test_kept,
        "output": "",
    }
    write_progress_text(summary)

    output_path = arguments.out
    if not output_path:
        root, extension = os.path.splitext(arguments.file)
        output_path = "%s_%s%s" % (root, arguments.instrument, extension)
    if os.path.normcase(os.path.abspath(output_path)) == os.path.normcase(os.path.abspath(arguments.file)):
        raise InstallError("输出文件不能覆盖输入文件")
    summary["output"] = output_path
    save_output(output_path)
    log("已保存：" + output_path)

    if arguments.report:
        report_path = arguments.report
        if not os.path.isabs(report_path):
            report_path = os.path.join(os.path.dirname(output_path), report_path)
        with open(report_path, "w", encoding="utf-8") as report_file:
            json.dump(summary, report_file, ensure_ascii=False, indent=2)
        log("验收报告：" + report_path)

    print("CONTROLS_INSTALL_RESULT " + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except InstallError as error:
        print("CONTROLS_INSTALL_ERROR " + str(error), flush=True)
        sys.exit(1)
