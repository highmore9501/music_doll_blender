"""MusicDoll → FBX 导出共用逻辑。

三份脚本都用这一份：

- fbx_analyze.py  只读：把场景里的 mesh 分成「骨骼网格 / 带 shape key 的部件 / 普通部件」，
                  判定每个部件的真实父级（世界原点还是某根骨），打印表格 + 落 plan.json；
- fbx_export.py   执行：按 plan 把部件烘焙到各自的导出空间，一个部件一个 fbx，写 manifest.json；
- fbx_verify.py   验收：把导出的 fbx 重新导回空场景，逐顶点 / 逐骨和源文件比。

判定口径（为什么这么算）写在 SKILL.md 里，这里只保证算法和它一致。
"""

import hashlib
import json
import math
import os
import re
import sys
import unicodedata

import bpy
import mathutils


SCHEMA = "music-doll-fbx/1"

# 场景单位必须是 0.01 米（1 个单位 = 1 厘米）；float32 存 0.01 会读成 0.009999999776
UNIT_SCALE_EXPECTED = 0.01
UNIT_SCALE_TOLERANCE = 1e-5

# 「这个祖先物体是不是就是某根骨」的判据
PARENT_TRANSLATION_TOLERANCE_MM = 1.0
PARENT_ROTATION_TOLERANCE_DEG = 0.5

# 「这个部件在动画中是否刚性跟随这根骨」的判据（两帧之间关系矩阵的变化量）
STABILITY_TRANSLATION_TOLERANCE_MM = 2.0
STABILITY_ROTATION_TOLERANCE_DEG = 0.5

# 烘焙自检：副本顶点应当等于「烘焙矩阵 × 源顶点」，只允许 float32 级别的误差
BAKE_TOLERANCE_UNITS = 0.005

# 顶点数不超过这个数、又没有材质、又在控制器集合里 → 当成控制器的显示方块
CONTROL_WIDGET_VERTEX_LIMIT = 12
CONTROL_COLLECTION_KEYWORDS = ("controller", "controllers")

# 导出参数。这些值决定「进 UE 之后尺寸和朝向对不对」，改动前先看 SKILL.md 的导出参数表。
FBX_EXPORT_OPTIONS = {
    "use_selection": True,
    "object_types": {"ARMATURE", "MESH"},
    "add_leaf_bones": False,        # 不导出叶骨骼
    "bake_anim": False,             # 不导出动画
    "use_mesh_modifiers": True,
    "apply_unit_scale": True,       # Apply Unit：按场景单位（0.01 米）写进 FBX
    "apply_scale_options": "FBX_SCALE_NONE",
    "embed_textures": True,
    "path_mode": "AUTO",
    "mesh_smooth_type": "OFF",
    "use_custom_props": False,
    "use_tspace": False,
    "check_existing": False,
}


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

DEFAULT_OPTIONS = {
    "blend": None,
    "out": None,
    "prefix": None,
    "frame": None,
    "tolerance_mm": PARENT_TRANSLATION_TOLERANCE_MM,
    "tolerance_deg": PARENT_ROTATION_TOLERANCE_DEG,
    "stability_mm": STABILITY_TRANSLATION_TOLERANCE_MM,
    "stability_deg": STABILITY_ROTATION_TOLERANCE_DEG,
    "armature": None,
    "exclude": [],
    "include": [],
    "body_name": None,
    "dry_run": False,
    "no_stability": False,
    "morph_with_armature": False,
    "json": None,
    "unresolved": "fail",   # fail / world
}


def parse_arguments(argv=None):
    """解析 `-- <blend.blend> --out DIR --dry-run` 这种风格；`--` 之后才是我们的参数。"""
    raw = list(sys.argv if argv is None else argv)
    if "--" in raw:
        raw = raw[raw.index("--") + 1:]
    else:
        raw = [item for item in raw if item.endswith(".blend")]

    options = dict(DEFAULT_OPTIONS)
    index = 0
    while index < len(raw):
        token = raw[index]
        if not token.startswith("--"):
            if options["blend"] is None:
                options["blend"] = token
            else:
                raise SystemExit(f"多余的参数：{token}")
            index += 1
            continue

        key = token[2:].replace("-", "_")
        if key in {"dry_run", "no_stability", "morph_with_armature"}:
            options[key] = True
            index += 1
            continue
        if index + 1 >= len(raw):
            raise SystemExit(f"参数 {token} 后面缺值")
        value = raw[index + 1]
        if key in {"exclude", "include"}:
            options[key] = [item.strip() for item in value.split(",") if item.strip()]
        elif key in {"tolerance_mm", "tolerance_deg", "stability_mm", "stability_deg"}:
            options[key] = float(value)
        elif key == "frame":
            options[key] = int(value)
        elif key in options:
            options[key] = value
        else:
            raise SystemExit(f"不认识的参数：{token}")
        index += 2

    return options


def open_blend(options):
    """没打开文件，或者打开的不是要求的文件，就打开它。"""
    requested = options.get("blend")
    current = bpy.data.filepath
    if requested and os.path.abspath(requested) != os.path.abspath(current or ""):
        if not os.path.exists(requested):
            raise SystemExit(f"找不到文件：{requested}")
        bpy.ops.wm.open_mainfile(filepath=requested)
    if not bpy.data.filepath:
        raise SystemExit("没有打开任何 .blend")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def millimetres_per_unit(scene):
    """1 个 Blender 单位等于多少毫米。单位 0.01 米时是 10。"""
    return scene.unit_settings.scale_length * 1000.0


def matrix_to_list(matrix):
    return [[round(value, 8) for value in row] for row in matrix]


def load_bake_matrix(values):
    return mathutils.Matrix([[float(value) for value in row] for row in values])


def matrix_delta(matrix_source, matrix_target):
    """返回 (平移距离（单位）, 旋转角度（度）)：把 source 变成 target 要动多少。"""
    delta = matrix_source.inverted() @ matrix_target
    translation = delta.translation.length
    rotation_degrees = math.degrees(abs(delta.to_quaternion().angle))
    return translation, rotation_degrees


def is_identity(matrix, tolerance=1e-6):
    identity = mathutils.Matrix.Identity(4)
    return all(abs(matrix[row][col] - identity[row][col]) <= tolerance for row in range(4) for col in range(4))


def display_width(text):
    width = 0
    for character in str(text):
        width += 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
    return width


def pad(text, width):
    text = str(text)
    return text + " " * max(0, width - display_width(text))


def print_table(headers, rows, indent="  "):
    widths = [display_width(header) for header in headers]
    for row in rows:
        for column, cell in enumerate(row):
            widths[column] = max(widths[column], display_width(cell))
    print(indent + " | ".join(pad(header, widths[column]) for column, header in enumerate(headers)))
    print(indent + "-+-".join("-" * width for width in widths))
    for row in rows:
        print(indent + " | ".join(pad(cell, widths[column]) for column, cell in enumerate(row)))


def sanitize_filename(text, fallback="part"):
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(text)).strip().strip(".")
    return cleaned or fallback


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def world_matrix_of(object_ref, depsgraph):
    return object_ref.evaluated_get(depsgraph).matrix_world.copy()


# ---------------------------------------------------------------------------
# 场景检查（闸门）
# ---------------------------------------------------------------------------

def gate_unit(scene):
    unit = scene.unit_settings
    scale = unit.scale_length
    ok = unit.system == "METRIC" and abs(scale - UNIT_SCALE_EXPECTED) <= UNIT_SCALE_TOLERANCE
    return {
        "id": "unit_0.01m",
        "ok": ok,
        "detail": f"unit_system={unit.system} scale_length={scale:.9f} length_unit={unit.length_unit}（要求 METRIC / 0.01）",
        "fix": "属性编辑器 → 场景属性 → 单位：系统选 Metric、单位比例 0.01、长度 Meters；改完再跑。",
    }


def gate_armature_origin(armature_obj):
    matrix = armature_obj.matrix_world
    ok = (
        abs(matrix.translation.length) <= 1e-5
        and max(abs(value) for value in armature_obj.rotation_euler) <= 1e-5
        and max(abs(value - 1.0) for value in armature_obj.scale) <= 1e-5
    )
    return {
        "id": "armature_at_origin",
        "ok": ok,
        "detail": (
            f"{armature_obj.name}: location={[round(value, 6) for value in armature_obj.location]}"
            f" rotation={[round(value, 6) for value in armature_obj.rotation_euler]}"
            f" scale={[round(value, 6) for value in armature_obj.scale]}"
        ),
        "fix": "选中骨架 → 侧栏物体属性 → 位置 / 旋转 / 缩放全部归零（有父级时先 alt+p 清父级再归零）。",
    }


def gate_skeletal_mesh_origin(armature_obj, depsgraph):
    offenders = []
    for mesh_obj in skeletal_meshes(armature_obj):
        matrix = world_matrix_of(mesh_obj, depsgraph)
        if not is_identity(matrix, tolerance=1e-5):
            offenders.append(f"{mesh_obj.name}（位移 {[round(value, 4) for value in matrix.translation]}）")
    return {
        "id": "skeletal_mesh_identity",
        "ok": not offenders,
        "detail": "骨骼网格的物体变换必须是单位矩阵" + (f"；不满足：{'，'.join(offenders)}" if offenders else ""),
        "fix": "骨骼网格应当以骨架为父级、自身变换归零；不要对它单独应用变换（会破坏绑定）。",
    }


def resolve_armature(scene, requested_name):
    armatures = sorted([obj for obj in scene.objects if obj.type == "ARMATURE"], key=lambda item: item.name)
    if requested_name:
        for armature_obj in armatures:
            if armature_obj.name == requested_name:
                return armature_obj, None
        return None, f"找不到名为 {requested_name} 的骨架"
    if len(armatures) == 1:
        return armatures[0], None
    if not armatures:
        return None, "场景里没有骨架"
    names = "，".join(armature_obj.name for armature_obj in armatures)
    return None, f"场景里有 {len(armatures)} 套骨架（{names}），用 --armature 指定这一份导谁"


def skeletal_meshes(armature_obj):
    """带 Armature 变形器、且目标就是这套骨架的 mesh。"""
    found = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if any(modifier.type == "ARMATURE" and modifier.object == armature_obj for modifier in obj.modifiers):
            found.append(obj)
    return sorted(found, key=lambda item: item.name)


# ---------------------------------------------------------------------------
# 部件分类
# ---------------------------------------------------------------------------

def parent_chain(object_ref):
    chain = []
    current = object_ref
    while current is not None:
        chain.append(current.name)
        current = current.parent
    return chain


def collection_names(object_ref):
    return sorted(collection.name for collection in object_ref.users_collection)


def is_control_widget(object_ref):
    """控制器用的显示方块：通常在 controller 集合里、顶点少、没材质、挂着 Track To 之类。"""
    names = " ".join(collection_names(object_ref)).lower()
    in_controller_collection = any(keyword in names for keyword in CONTROL_COLLECTION_KEYWORDS)
    small_and_bare = (
        len(object_ref.data.vertices) <= CONTROL_WIDGET_VERTEX_LIMIT
        and not object_ref.data.materials
    )
    tracked = any(
        constraint.type in {"TRACK_TO", "DAMPED_TRACK", "LOCKED_TRACK", "COPY_LOCATION", "COPY_ROTATION"}
        for constraint in object_ref.constraints
    )
    reasons = []
    if in_controller_collection:
        reasons.append("在控制器集合里")
    if small_and_bare:
        reasons.append(f"只有 {len(object_ref.data.vertices)} 个顶点且无材质")
    if tracked:
        reasons.append("挂着跟踪/复制约束")
    certain = in_controller_collection or (small_and_bare and tracked)
    return certain, reasons


def mesh_role(mesh_obj):
    for modifier in mesh_obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object is not None:
            return "skeletal"
    if mesh_obj.data.shape_keys and len(mesh_obj.data.shape_keys.key_blocks) > 1:
        return "morph"
    return "static"


def material_texture_report(mesh_obj):
    """每个材质的贴图情况：只有走标准 Principled BSDF 的贴图，FBX 才带得出去。

    mmd_tools 的 toon 材质用的是 `mmd_shader` / `mmd_base_tex` 这类自建节点组，
    Blender 的 FBX 导出器找不到它们，贴图不会进 fbx（实测：米娅的 32 个身体材质全部如此，
    鼓台的 5 个标准材质正常带出 10 张图）。
    """
    report = {}
    for slot in mesh_obj.material_slots:
        material = slot.material
        if material is None or not material.use_nodes:
            continue
        images = [
            node.image.name for node in material.node_tree.nodes
            if getattr(node, "image", None) is not None
        ]
        if not images:
            continue
        has_principled = any(node.type == "BSDF_PRINCIPLED" for node in material.node_tree.nodes)
        report[material.name] = {"images": images, "exportable": has_principled}
    return report


def material_image_names(mesh_obj):
    names = []
    for material in material_texture_report(mesh_obj).values():
        for name in material["images"]:
            if name not in names:
                names.append(name)
    return names


# ---------------------------------------------------------------------------
# 真实父级判定
# ---------------------------------------------------------------------------

def find_matching_bone(ancestor_world, armature_obj, evaluated_armature, millimetres, options):
    """找一个世界矩阵和这个祖先物体重合的骨：先看形变骨，再看全部骨。"""
    candidates = [bone for bone in evaluated_armature.pose.bones if bone.bone.use_deform]
    candidates += [bone for bone in evaluated_armature.pose.bones if not bone.bone.use_deform]
    best = None
    for pose_bone in candidates:
        bone_world = armature_obj.matrix_world @ pose_bone.matrix
        translation, rotation = matrix_delta(bone_world, ancestor_world)
        translation_mm = translation * millimetres
        if translation_mm > options["tolerance_mm"] or rotation > options["tolerance_deg"]:
            continue
        score = translation_mm + rotation * 10.0
        if best is None or score < best["score"]:
            best = {
                "bone": pose_bone.name,
                "deform": pose_bone.bone.use_deform,
                "score": score,
                "translation_mm": translation_mm,
                "rotation_deg": rotation,
            }
    return best


def resolve_parent(mesh_obj, armature_obj, evaluated_armature, depsgraph, millimetres, options):
    """搞清楚这个 mesh 的真实父级：世界原点，还是某根骨。

    规则（对应 SKILL.md）：
    1. 直接挂在骨上（parent_type == 'BONE'）→ 就是那根骨；
    2. 否则沿父链往上走，遇到一个物体的世界矩阵和某根骨重合 → 那根骨就是真实父级
       （「绑定到中转空物体、空物体再 copy location/rotation 到骨头」的情形）；
    3. 走到顶都没重合 → 世界原点。
    """
    if mesh_obj.parent is armature_obj and mesh_obj.parent_type == "BONE" and mesh_obj.parent_bone:
        bone_world = armature_obj.matrix_world @ evaluated_armature.pose.bones[mesh_obj.parent_bone].matrix
        return {
            "type": "bone",
            "bone": mesh_obj.parent_bone,
            "matched_ancestor": armature_obj.name,
            "match_error_mm": 0.0,
            "match_rotation_deg": 0.0,
            "bone_world": bone_world,
            "chain_note": "mesh 直接以骨骼为父级",
        }

    ancestor = mesh_obj.parent
    suspicious = []
    while ancestor is not None:
        ancestor_world = world_matrix_of(ancestor, depsgraph)
        if is_identity(ancestor_world, tolerance=1e-5):
            return {
                "type": "world",
                "bone": None,
                "matched_ancestor": ancestor.name,
                "match_error_mm": 0.0,
                "match_rotation_deg": 0.0,
                "suspicious_ancestors": suspicious,
                "chain_note": f"祖先 {ancestor.name} 在世界原点（单位矩阵）",
            }
        match = find_matching_bone(ancestor_world, armature_obj, evaluated_armature, millimetres, options)
        if match is not None:
            bone_world = armature_obj.matrix_world @ evaluated_armature.pose.bones[match["bone"]].matrix
            return {
                "type": "bone",
                "bone": match["bone"],
                "matched_ancestor": ancestor.name,
                "match_error_mm": match["translation_mm"],
                "match_rotation_deg": match["rotation_deg"],
                "bone_world": bone_world,
                "suspicious_ancestors": [],
                "chain_note": f"祖先 {ancestor.name} 与骨 {match['bone']} 重合",
            }
        suspicious.append(ancestor.name)
        ancestor = ancestor.parent

    if mesh_obj.parent is None:
        return {
            "type": "world",
            "bone": None,
            "matched_ancestor": None,
            "match_error_mm": 0.0,
            "match_rotation_deg": 0.0,
            "suspicious_ancestors": [],
            "chain_note": "没有父级",
        }

    return {
        "type": "unresolved",
        "bone": None,
        "matched_ancestor": None,
        "match_error_mm": float("nan"),
        "match_rotation_deg": float("nan"),
        "suspicious_ancestors": suspicious,
        "chain_note": "父链上没有和任何骨重合的物体",
    }


# ---------------------------------------------------------------------------
# 建计划
# ---------------------------------------------------------------------------

def derive_prefix(armature_obj, requested_prefix):
    if requested_prefix:
        return requested_prefix
    matched = re.match(r"^(?P<base>.*)_(?:arm|armature|rig|skeleton)(?:_(?P<suffix>.+))?$", armature_obj.name)
    if matched:
        return matched.group("base")
    return armature_obj.name


def derive_performer_suffix(armature_obj):
    """`米娅-星彩_arm_Mia` 的 performer 后缀是 `Mia`，用来从部件名里剥掉。"""
    tokens = armature_obj.name.split("_")
    if len(tokens) > 2 and tokens[-2] in {"arm", "armature", "rig", "skeleton"}:
        return tokens[-1]
    return None


def derive_part_base_name(mesh_obj, performer_suffix):
    name = mesh_obj.name
    if performer_suffix and name.endswith("_" + performer_suffix):
        name = name[: -(len(performer_suffix) + 1)]
    return name


def describe_mesh(mesh_obj, depsgraph, kind, bake_matrix=None, resolution=None, stability=None):
    mesh_world = world_matrix_of(mesh_obj, depsgraph)
    space_matrix = bake_matrix if bake_matrix is not None else mesh_world
    points = [space_matrix @ vertex.co for vertex in mesh_obj.data.vertices]
    textures = material_texture_report(mesh_obj)
    record = {
        "object": mesh_obj.name,
        "kind": kind,
        "parent_chain": parent_chain(mesh_obj),
        "collections": collection_names(mesh_obj),
        "vertices": len(mesh_obj.data.vertices),
        "polygons": len(mesh_obj.data.polygons),
        "vertex_groups": len(mesh_obj.vertex_groups),
        "shape_keys": (
            [key_block.name for key_block in mesh_obj.data.shape_keys.key_blocks]
            if mesh_obj.data.shape_keys else []
        ),
        "materials": [slot.material.name if slot.material else "" for slot in mesh_obj.material_slots],
        "material_textures": textures,
        "material_images": sorted({
            name for material in textures.values() for name in material["images"]
        }),
        "textures_exportable": sum(1 for material in textures.values() if material["exportable"]),
        "textures_not_exportable": sum(1 for material in textures.values() if not material["exportable"]),
        "modifiers": [
            {
                "type": modifier.type,
                "object": getattr(getattr(modifier, "object", None), "name", ""),
                "show_viewport": modifier.show_viewport,
            }
            for modifier in mesh_obj.modifiers
        ],
        "world_matrix": matrix_to_list(mesh_world),
        "bbox_export_space": {
            "min": [round(min(getattr(point, axis) for point in points), 4) for axis in ("x", "y", "z")],
            "max": [round(max(getattr(point, axis) for point in points), 4) for axis in ("x", "y", "z")],
        },
    }
    if bake_matrix is not None:
        record["bake_matrix"] = matrix_to_list(bake_matrix)
    if resolution is not None:
        record["resolution"] = {
            "type": resolution["type"],
            "bone": resolution.get("bone"),
            "matched_ancestor": resolution.get("matched_ancestor"),
            "match_error_mm": round(float(resolution.get("match_error_mm", 0.0)), 4),
            "match_rotation_deg": round(float(resolution.get("match_rotation_deg", 0.0)), 4),
            "suspicious_ancestors": list(resolution.get("suspicious_ancestors", [])),
            "note": resolution.get("chain_note", ""),
        }
    if stability is not None:
        record["stability"] = stability
    if mesh_obj.data.shape_keys and len(mesh_obj.data.shape_keys.key_blocks) > 1 and mesh_obj.modifiers:
        record["warning"] = (
            "带 shape key 又有修改器：Blender 不能对带形态键的网格应用修改器，"
            "导出时这些修改器不会被应用"
        )
    return record


def sample_stability(mesh_obj, armature_obj, depsgraph, resolution, millimetres, options):
    """在两个不同帧上量「部件相对这根骨的关系」，判断它是不是真的刚性跟随。"""
    if options["no_stability"] or resolution["type"] != "bone":
        return None
    scene = bpy.context.scene
    bone_name = resolution["bone"]
    current_frame = scene.frame_current
    span = max(1, (scene.frame_end - scene.frame_start) // 3)
    probe_frames = sorted({current_frame, min(scene.frame_end, current_frame + span)})
    if len(probe_frames) < 2:
        probe_frames = [scene.frame_start, max(scene.frame_start + 1, scene.frame_end)]

    relations = []
    for frame in probe_frames:
        scene.frame_set(frame)
        frame_depsgraph = bpy.context.evaluated_depsgraph_get()
        frame_armature = armature_obj.evaluated_get(frame_depsgraph)
        bone_world = armature_obj.matrix_world @ frame_armature.pose.bones[bone_name].matrix
        mesh_world = mesh_obj.evaluated_get(frame_depsgraph).matrix_world.copy()
        relations.append((frame, bone_world.inverted() @ mesh_world))

    scene.frame_set(current_frame)
    bpy.context.view_layer.update()

    worst_translation = 0.0
    worst_rotation = 0.0
    reference = relations[0][1]
    for _, relation in relations[1:]:
        translation, rotation = matrix_delta(reference, relation)
        worst_translation = max(worst_translation, translation * millimetres)
        worst_rotation = max(worst_rotation, rotation)
    return {
        "frames": probe_frames,
        "translation_mm": round(worst_translation, 4),
        "rotation_deg": round(worst_rotation, 4),
        "ok": worst_translation <= options["stability_mm"] and worst_rotation <= options["stability_deg"],
    }


def build_plan(scene, options):
    """把场景读成一份计划：闸门 + 部件表 + 每个部件的真实父级和烘焙矩阵。"""
    if options["frame"] is not None:
        scene.frame_set(options["frame"])
    depsgraph = bpy.context.evaluated_depsgraph_get()

    plan = {
        "schema": SCHEMA,
        "source_blend": bpy.data.filepath,
        "blender_version": bpy.app.version_string,
        "frame": scene.frame_current,
        "unit": {
            "system": scene.unit_settings.system,
            "scale_length": scene.unit_settings.scale_length,
            "length_unit": scene.unit_settings.length_unit,
            "millimetres_per_unit": millimetres_per_unit(scene),
            "fps": scene.render.fps,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
        },
        "gates": [],
        "units": [],
        "excluded": [],
        "warnings": [],
    }

    armature_obj, armature_error = resolve_armature(scene, options["armature"])
    plan["gates"].append(gate_unit(scene))
    if armature_obj is None:
        plan["gates"].append({
            "id": "armature_resolved",
            "ok": False,
            "detail": armature_error,
            "fix": "用 --armature 指定骨架名。",
        })
        plan["ok"] = False
        return plan

    original_pose_position = armature_obj.data.pose_position
    plan["gates"].append({
        "id": "armature_resolved",
        "ok": True,
        "detail": f"{armature_obj.name}（{len(armature_obj.data.bones)} 骨，原 pose_position={original_pose_position}）",
        "fix": "",
    })

    # 判定父级要看「骨真的跟着控制器走」的姿势，所以先强制 POSE（导出骨骼网格时才切 REST）
    armature_obj.data.pose_position = "POSE"
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_armature = armature_obj.evaluated_get(depsgraph)

    plan["gates"].append(gate_armature_origin(armature_obj))
    plan["gates"].append(gate_skeletal_mesh_origin(armature_obj, depsgraph))

    millimetres = millimetres_per_unit(scene)
    prefix = derive_prefix(armature_obj, options["prefix"])
    performer_suffix = derive_performer_suffix(armature_obj)
    plan["armature"] = {
        "object": armature_obj.name,
        "data": armature_obj.data.name,
        "bones": len(armature_obj.data.bones),
        "prefix": prefix,
        "original_pose_position": original_pose_position,
    }

    # 1) 骨骼网格：带 Armature 变形器、目标是这套骨架的 mesh，全部进同一个 fbx
    skeletal_unit = {
        "file": sanitize_filename(options["body_name"] or f"{prefix}_body") + ".fbx",
        "kind": "skeletal",
        "armature": armature_obj.name,
        "parent": {"type": "armature", "attach": "skeletal_mesh_component"},
        "meshes": [],
    }
    skeletal_mesh_objects = skeletal_meshes(armature_obj)
    for mesh_obj in skeletal_mesh_objects:
        if mesh_obj.name in options["exclude"]:
            plan["excluded"].append({"object": mesh_obj.name, "reason": "命令行 --exclude"})
            continue
        skeletal_unit["meshes"].append(describe_mesh(mesh_obj, depsgraph, "skeletal"))

    # 2) 其它 mesh：逐个判定父级
    static_units = []
    handled = {mesh_obj.name for mesh_obj in skeletal_mesh_objects}
    for obj in sorted(scene.objects, key=lambda item: item.name):
        if obj.type != "MESH" or obj.name in handled:
            continue
        if obj.name in options["exclude"]:
            plan["excluded"].append({"object": obj.name, "reason": "命令行 --exclude"})
            continue
        control, reasons = is_control_widget(obj)
        if control and obj.name not in options["include"]:
            plan["excluded"].append({"object": obj.name, "reason": "控制器显示件：" + "、".join(reasons)})
            continue
        if not control and reasons and obj.name not in options["include"]:
            plan["warnings"].append(
                f"{obj.name}：{'、'.join(reasons)}，但证据不足，仍按部件处理；要排除请加 --exclude {obj.name}"
            )

        mesh_world = world_matrix_of(obj, depsgraph)
        resolution = resolve_parent(obj, armature_obj, evaluated_armature, depsgraph, millimetres, options)
        if resolution["type"] == "world" and resolution.get("suspicious_ancestors"):
            plan["warnings"].append(
                f"{obj.name}：父链 {' → '.join(resolution['suspicious_ancestors'])} 带着变换，却没有和任何骨重合，"
                f"所以按「世界原点」处理 —— 进 UE 后它不会跟着手/脚动。如果它是乐器（鼓棒之类），"
                f"回 Blender 把这处父级修好再导（文件本身有问题时 Blender 会报 "
                f"'Could not find op_from … Bone Parent'）。"
            )
        if resolution["type"] == "unresolved":
            if options["unresolved"] == "world":
                resolution["type"] = "world"
                resolution["chain_note"] += "（按 --unresolved world 处理）"
            else:
                plan["gates"].append({
                    "id": f"parent_resolved:{obj.name}",
                    "ok": False,
                    "detail": f"{obj.name}：{resolution['chain_note']}；父链 {parent_chain(obj)}",
                    "fix": (
                        "这个部件的父级既不是世界原点也不是某根骨，UE 里没有可以挂的位置。"
                        "先手动把它的父级换成骨（或换成 copy 骨头的空物体），或者用 --exclude 跳过。"
                    ),
                })

        bake_matrix = (
            resolution["bone_world"].inverted() @ mesh_world
            if resolution["type"] == "bone" else mesh_world.copy()
        )
        kind = mesh_role(obj)
        unit = {
            "file": sanitize_filename(f"{prefix}_{derive_part_base_name(obj, performer_suffix)}") + ".fbx",
            "kind": kind,
            "armature": None,
            "parent": (
                {"type": "bone", "bone": resolution["bone"], "attach": "socket_zero_offset", "space": "bone_rest"}
                if resolution["type"] == "bone"
                else {"type": "world", "attach": "place_at_origin"}
            ),
            "meshes": [describe_mesh(
                obj, depsgraph, kind,
                bake_matrix=bake_matrix,
                resolution=resolution,
                stability=sample_stability(obj, armature_obj, depsgraph, resolution, millimetres, options),
            )],
        }
        if kind == "morph" and options["morph_with_armature"]:
            unit["armature"] = armature_obj.name
            unit["notes"] = "带形态键的网格连骨架一起导出（计划里的写法）；实测骨架不会给它加蒙皮，" \
                            "进 UE 仍是静态网格，只是多带了一份骨架数据"
        static_units.append(unit)

    if skeletal_unit["meshes"]:
        plan["units"].append(skeletal_unit)
    plan["units"].extend(sorted(static_units, key=lambda item: item["file"]))

    used_names = {}
    for unit in plan["units"]:
        if unit["file"] in used_names:
            used_names[unit["file"]] += 1
            base, extension = os.path.splitext(unit["file"])
            unit["file"] = f"{base}_{used_names[unit['file']]}{extension}"
        else:
            used_names[unit["file"]] = 1
        for record in unit["meshes"]:
            if record.get("textures_not_exportable"):
                plan["warnings"].append(
                    f"{record['object']}：{record['textures_not_exportable']} 个材质用的是 mmd_tools 的 "
                    f"toon 节点（mmd_shader / mmd_base_tex），FBX 带不走它们的贴图，导出后这些材质是纯色。"
                    f"要带贴图，先把材质换成标准的 Principled BSDF + Image Texture。"
                )

    plan["ok"] = all(gate["ok"] for gate in plan["gates"])
    return plan


# ---------------------------------------------------------------------------
# 烘焙与导出
# ---------------------------------------------------------------------------

def select_only(objects):
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def bake_duplicate(source_obj, bake_matrix):
    """复制一份网格 → 把烘焙矩阵应用进顶点 → 返回 (副本, 自检偏差)。

    应用之后副本的物体变换是单位矩阵，顶点坐标就是「导出空间」里的坐标：
    - 真实父级是骨头：顶点坐标是骨骼空间（原点在骨头、朝向是骨头的朝向）；
    - 真实父级是世界原点：顶点坐标就是世界坐标。
    """
    original_object_name = source_obj.name
    original_data_name = source_obj.data.name
    source_positions = [vertex.co.copy() for vertex in source_obj.data.vertices]

    duplicate = source_obj.copy()
    duplicate.data = source_obj.data.copy()
    duplicate.parent = None
    duplicate.matrix_parent_inverse = mathutils.Matrix.Identity(4)
    bpy.context.scene.collection.objects.link(duplicate)

    # 让副本在 fbx 里用回原名：先把源改个后缀，副本再占原名
    source_obj.name = original_object_name + "__SRC"
    duplicate.name = original_object_name
    duplicate.data.name = original_data_name

    duplicate.matrix_world = bake_matrix
    select_only([duplicate])
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    deviation = 0.0
    for index, position in enumerate(source_positions):
        expected = bake_matrix @ position
        deviation = max(deviation, (expected - duplicate.data.vertices[index].co).length)
    return duplicate, deviation


def drop_duplicate(duplicate, source_obj):
    """删掉副本，把源物体的名字还回去。"""
    if duplicate is not None and duplicate.name in bpy.data.objects:
        bpy.data.objects.remove(duplicate, do_unlink=True)
    if source_obj.name.endswith("__SRC"):
        source_obj.name = source_obj.name[: -len("__SRC")]


def export_objects(objects, filepath):
    if os.path.exists(filepath):
        os.remove(filepath)
    select_only(objects)
    bpy.ops.export_scene.fbx(filepath=filepath, **FBX_EXPORT_OPTIONS)
    return os.path.getsize(filepath)


def load_plan(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, payload):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(f"已写出 {path}")
