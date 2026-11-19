# -*- coding: utf-8 -*-
"""MusicDoll 骨架改造 —— 公共核心（骨架读取与几何，只依赖 bpy / mathutils）。

这里的函数全部是"读骨架、算几何"，不做任何写入。分析器、执行器、验收器共用同一套口径，
避免三份代码各自认链、各自判方向。名字解析在 rig_roles.py。

术语（对应 SKILL.md 的规则章）：
- 前方向：角色脚尖指向的方向。MMD 系一般是 -Y，但不做假定，一律从脚骨量。
- 凸侧：一条链弯起来时中间关节凸出去的那一侧（肘尖朝后、膝盖朝前、指节朝指甲）。
- 形变骨 / 机制骨：use_deform 真 / 假。
"""
import math
import os
import sys

from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rig_roles import parse_bone_name, role_from_name  # noqa: E402,F401  (对外统一从 rig_common 取)


# ── 打开文件 ────────────────────────────────────────────────────────────
def open_mainfile_tolerant(filepath):
    """打开 .blend，容忍"载入成功但报了错"的文件。

    有些老模型的状态键（shape key）指针坏了，Blender 会删掉坏键后照常载入，但 `open_mainfile`
    仍然抛 RuntimeError。这类文件完全可以继续分析/改造，所以：抛错但对象已载入 → 只记一条警告。
    返回 (是否可用, 警告文本或 None)。
    """
    import bpy as _bpy

    try:
        _bpy.ops.wm.open_mainfile(filepath=filepath, load_ui=False)
        return True, None
    except RuntimeError as error:
        warning = str(error).splitlines()[0][:200] if str(error) else "open_mainfile raised"
        if _bpy.data.objects:
            return True, warning
        return False, warning


# ── 骨架读取 ────────────────────────────────────────────────────────────
def build_bone_index(armature_object):
    """把骨架读成 {名字: 字典}，含父、子、头尾、长度、形变、矩阵。"""
    index = {}
    for bone in armature_object.data.bones:
        index[bone.name] = {
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else None,
            "children": [child.name for child in bone.children],
            "head": bone.head_local.copy(),
            "tail": bone.tail_local.copy(),
            "length": bone.length,
            "deform": bone.use_deform,
            "matrix": bone.matrix_local.copy(),
            "connected": bone.use_connect,
        }
    return index


def bone_axes(bone_entry):
    """返回骨骼在骨架空间的 (X, Y, Z) 单位轴；Y 是骨自身方向。"""
    rotation = bone_entry["matrix"].to_3x3()
    return (
        (rotation @ Vector((1.0, 0.0, 0.0))).normalized(),
        (rotation @ Vector((0.0, 1.0, 0.0))).normalized(),
        (rotation @ Vector((0.0, 0.0, 1.0))).normalized(),
    )


def bone_direction(bone_entry):
    """骨方向（head→tail 的单位向量）。"""
    direction = bone_entry["tail"] - bone_entry["head"]
    if direction.length < 1e-9:
        return Vector((0.0, 0.0, 0.0))
    return direction.normalized()


def project_perpendicular(vector, axis):
    """把 vector 投影到与 axis 垂直的平面上（axis 需为单位向量）。"""
    return vector - axis * vector.dot(axis)


def angle_between(vector_a, vector_b):
    """两个向量的夹角（度）。任一为零向量时返回 None。"""
    if vector_a is None or vector_b is None:
        return None
    if vector_a.length < 1e-9 or vector_b.length < 1e-9:
        return None
    cosine = max(-1.0, min(1.0, vector_a.normalized().dot(vector_b.normalized())))
    return math.degrees(math.acos(cosine))


# ── 链结构 ──────────────────────────────────────────────────────────────
def single_chain(bone_index, start_name, max_depth=6):
    """从 start 往下走，只要每层恰好一个子骨就继续。

    返回 (骨名列表, 是否自然结束)。走到 max_depth 还没结束说明这不是一条短链（裙骨、发骨都是
    十几层），调用方应当把它排除，而不是截断后当成手指链。
    """
    chain = [start_name]
    current = start_name
    while True:
        children = bone_index[current]["children"]
        if len(children) != 1:
            return chain, True
        if len(chain) >= max_depth:
            return chain, False
        current = children[0]
        chain.append(current)


def logical_chain(bone_index, raw_names):
    """去掉 MCH / 影子镜像后的"实际骨链"。

    有些骨架给每一节都配一根镜像机制骨（Coco 的 `MCH_Index1_R`、东风谷早苗的 `MCH_親指０`），
    链会变成 MCH/本体交替的一长串；按逻辑骨数（去掉镜像）判断它是不是一条三节手指链。
    """
    logical = []
    for name in raw_names:
        info = role_from_name(name)
        if info["variant"] in ("mechanism", "shadow"):
            continue
        logical.append(name)
    return logical


def finger_depth(spine):
    """一条链的"逻辑节数"：MCH 并行链按 MCH 那几节算，影子骨不计数。"""
    mechanism = [name for name in spine if role_from_name(name)["variant"] == "mechanism"]
    others = [name for name in spine if role_from_name(name)["variant"] not in ("mechanism", "shadow")]
    return max(len(mechanism), len(others))


def chain_is_pure(bone_index, spine):
    """这条链在路上有没有分叉（某根骨有 2 个以上"还能继续往下"的子骨）。

    腕骨（Coco 的 Carpal1/Carpal2）是分叉的：它下面同时挂着食指和中指，所以它不是"一根手指"，
    不能当成手指链的起点，要往下钻到真正只覆盖一根手指的骨。
    """
    for name in spine:
        continuing = [child for child in bone_index[name]["children"] if bone_index[child]["children"]]
        if len(continuing) > 1:
            return False
    return True


def find_finger_roots(bone_index, hand_name, max_roots=8, max_visit=120, max_hop=2):
    """从手掌往下找五指各自的第一根骨。

    手指不一定直接挂在手掌下面（Coco 是 手掌 → 腕骨 → 指骨，东风谷早苗 是 手掌 → MCH_指骨），
    所以逐层往下找，**第一个构成合法手指链、且路上不分叉的骨**就是那根手指的起点，找到就不再往下钻。

    `max_hop` 限制只往下看两层：手指离手掌最多隔一层腕骨；再往下钻会把头发、裙摆的短链
    误当成手指（那些链局部看也是 3~5 节）。
    返回 [(根骨名, 逻辑节数, 链总长)]。
    """
    roots = []
    queue = [(child, 1) for child in bone_index[hand_name]["children"]]
    visited = 0
    while queue and len(roots) < max_roots and visited < max_visit:
        name, hop = queue.pop(0)
        visited += 1
        spine, terminated = chain_spine(bone_index, name, max_depth=8)
        depth = finger_depth(spine)
        ends_at_leaf = not bone_index[spine[-1]]["children"]
        if terminated and ends_at_leaf and 3 <= depth <= 5 and chain_is_pure(bone_index, spine):
            total_length = sum(bone_index[item]["length"] for item in spine
                               if role_from_name(item)["variant"] != "shadow")
            roots.append((name, depth, total_length))
            continue
        if hop < max_hop:
            queue.extend((child, hop + 1) for child in bone_index[name]["children"])
    return roots


def find_finger_chains(bone_index, hand_name):
    """认手掌用的结构证据：挂着至少 4 条长度相近的手指链。"""
    roots = find_finger_roots(bone_index, hand_name)
    if len(roots) < 4:
        return []
    lengths = sorted(item[2] for item in roots)
    median_length = lengths[len(lengths) // 2]
    similar = [item for item in roots if 0.35 * median_length <= item[2] <= 2.8 * median_length]
    if len(similar) >= 4:
        return sorted(similar, key=lambda item: item[2], reverse=True)
    return []


def leaf_descendant_counts(bone_index):
    """每个骨下面有多少个叶子骨（用来快速筛掉不可能是指掌的骨）。"""
    counts = {}

    def count_leaves(name, seen):
        if name in counts:
            return counts[name]
        if name in seen:
            return 0
        seen.add(name)
        children = bone_index[name]["children"]
        if not children:
            counts[name] = 1
            return 1
        total = 0
        for child in children:
            total += count_leaves(child, seen)
        counts[name] = total
        return total

    for name in bone_index:
        count_leaves(name, set())
    return counts


def find_hand_candidates(bone_index, min_leaves=5):
    """全骨架扫一遍，返回像手掌的骨名（子树里挂着至少 4 条相似手指链）。

    `min_leaves` 只是提速用的粗筛：一只手往下至少有 5 个指尖骨，低于 5 个叶子的骨不可能是指掌。
    """
    leaf_counts = leaf_descendant_counts(bone_index)
    found = []
    for name, leaf_count in leaf_counts.items():
        if leaf_count < min_leaves:
            continue
        if len(find_finger_chains(bone_index, name)) >= 4:
            found.append(name)
    return found


def is_leaf_tip(bone_index, name):
    """判断一根骨是不是"指尖骨"性质的末端骨。

    两条判据（任一成立）：名字带 先/tip/Nub 之类；或者名字 = 父名 + ".001"（Blender 复制出来的
    末端副本），且自己没有子骨。
    """
    entry = bone_index[name]
    if entry["children"]:
        return False
    _tags, stem, _side = parse_bone_name(name)
    role = role_from_name(name)
    if role["variant"] == "leaf":
        return True
    markers = ("先", "先端", "tip", "Tip", "Nub", "nub", "Leaf", "leaf", "End", "end")
    if any(marker in stem for marker in markers):
        return True
    parent = entry["parent"]
    if parent and name.startswith(parent) and name != parent:
        return True
    return False


def chain_spine(bone_index, start_name, max_depth=8):
    """从 start 往下取"链的脊柱"：每层取那个还能继续往下走的子骨。

    手指链常有两种写法：
    - 单链：`人指１ → 人指２ → 人指３ → 人指先`；
    - MCH 并行双链：`MCH_人指１ → MCH_人指２ → MCH_人指３`，每节 MCH 下面挂一根本体形变骨
      （东风谷早苗、Coco 都是这样）——这时本体骨自己是叶子，不构成父子链。
    所以每层优先走"还有子骨"的那一支，并且优先与起点同变体（MCH 起点就走 MCH 支）。

    返回 (骨名列表, 是否自然结束)。
    """
    start_variant = role_from_name(start_name)["variant"]
    path = [start_name]
    current = start_name
    while len(path) < max_depth:
        children = bone_index[current]["children"]
        if not children:
            return path, True
        continuation = [child for child in children if bone_index[child]["children"]]
        if not continuation:
            # 已经是最后一段：优先取本体形变骨当末端，没有再取第一根
            deform_children = [child for child in children if bone_index[child]["deform"]]
            current = (deform_children or children)[0]
        else:
            def score(child_name):
                variant_same = role_from_name(child_name)["variant"] == start_variant
                depth = len(chain_spine_sizes(bone_index, child_name))
                return (0 if variant_same else 1, -depth)

            continuation.sort(key=score)
            current = continuation[0]
        path.append(current)
    return path, False


def chain_spine_sizes(bone_index, start_name, limit=12):
    """取一条往下最长路径的长度（用于在分叉时判断哪一支是"主链"）。"""
    best = 0
    queue = [(start_name, 1)]
    while queue and len(queue) < 200:
        name, depth = queue.pop(0)
        best = max(best, depth)
        if depth >= limit:
            continue
        for child in bone_index[name]["children"]:
            queue.append((child, depth + 1))
    return list(range(best))


def analyze_finger_chain(bone_index, root_name):
    """把一条手指链解成"三节 + 指尖"，并区分功能链与本体骨。

    返回 dict：
    - `spine`：实际走出来的链；
    - `segments`：**功能链**的三节（有 MCH 主骨就是主骨，因为 IK 挂它）；
    - `deform_segments`：对应每一节的本体形变骨（MCH 写法下就是每节的卫星骨）；
    - `tip`：指尖骨（没有则 None）；
    - `extra`：比三节多出来的近端骨；
    - `note`：需要人工确认的地方。
    """
    spine, _terminated = chain_spine(bone_index, root_name)
    variants = [(name, role_from_name(name)["variant"]) for name in spine]
    mechanism_segments = [name for name, variant in variants if variant == "mechanism"]
    deform_spine = [name for name, variant in variants if variant not in ("mechanism", "shadow")]

    note = None
    if len(mechanism_segments) >= 3:
        segments = mechanism_segments[:3]
        deform_segments = []
        for name in segments:
            satellites = [child for child in bone_index[name]["children"]
                          if role_from_name(child)["variant"] not in ("mechanism", "shadow")
                          and bone_index[child]["deform"]]
            deform_segments.append(satellites[0] if satellites else None)
        tail = spine[spine.index(segments[-1]) + 1:]
        tail_deform = [name for name in tail if role_from_name(name)["variant"] not in ("mechanism", "shadow")]
        tip = tail_deform[-1] if tail_deform else None
        extra = mechanism_segments[3:]
        note = "MCH 并行链：功能链取 MCH 三节，本体骨是每节的卫星骨"
        if extra:
            note += "；另有近端 MCH 骨 %s" % ", ".join(extra)
        return {
            "spine": spine, "segments": segments, "deform_segments": deform_segments,
            "tip": tip, "extra": extra, "note": note,
        }

    chain = list(deform_spine)
    tip = None
    if len(chain) >= 4 and is_leaf_tip(bone_index, chain[-1]):
        tip = chain[-1]
        chain = chain[:-1]
    extra = []
    if len(chain) > 3:
        extra = chain[:-3]
        chain = chain[-3:]
    if extra:
        note = "取远端三节为指骨；近端另有 %s（基节/掌骨），不参与 IK" % ", ".join(extra)
    return {
        "spine": spine, "segments": chain, "deform_segments": chain,
        "tip": tip, "extra": extra, "note": note,
    }


# ── 前方向 / 凸侧 ────────────────────────────────────────────────────────
def detect_front_axis(bone_index, foot_names):
    """用脚骨（踝→趾的方向）量角色前方向。返回 (单位向量, 依据说明)。"""
    vectors = []
    for foot_name in foot_names:
        entry = bone_index.get(foot_name)
        if entry is None:
            continue
        direction = project_perpendicular(bone_direction(entry), Vector((0.0, 0.0, 1.0)))
        if direction.length > 1e-6:
            vectors.append(direction.normalized())
    if not vectors:
        return None, "no usable foot bone"
    summed = Vector((0.0, 0.0, 0.0))
    for vector in vectors:
        summed += vector
    if summed.length < 1e-6:
        return None, "foot directions cancel out"
    return summed.normalized(), "foot bone horizontal direction (%d bones: %s)" % (len(vectors), ", ".join(foot_names))


def hand_plane_normal(bone_index, hand_name, finger_root_names, thumb_root_name=None):
    """手掌平面法线（即指甲平面法线）。

    方向的正负按规则的判据定：拇指在掌心侧，所以法线要**背离拇指**（那就是指甲朝向）。
    没有拇指信息时返回的法线符号不确定，调用方应当报"不确定"而不是硬用。
    返回 (法线, 横向量)。
    """
    hand_direction = bone_direction(bone_index[hand_name])
    positions = [bone_index[name]["head"] for name in finger_root_names]
    if len(positions) < 3:
        return None, None
    center = Vector((0.0, 0.0, 0.0))
    for position in positions:
        center += position
    center /= len(positions)
    across = None
    best_distance = 0.0
    for first_index in range(len(positions)):
        for second_index in range(first_index + 1, len(positions)):
            distance = (positions[first_index] - positions[second_index]).length
            if distance > best_distance:
                best_distance = distance
                across = positions[second_index] - positions[first_index]
    if across is None or best_distance < 1e-9:
        return None, None
    normal = hand_direction.cross(across.normalized())
    if normal.length < 1e-9:
        return None, None
    normal.normalize()

    if thumb_root_name and thumb_root_name in bone_index:
        thumb_position = bone_index[thumb_root_name]["head"]
        if normal.dot(thumb_position - center) > 0.0:
            normal = -normal
    return normal, across.normalized()


def chain_arch(bone_index, chain_names):
    """量一条链的拱形：中间关节相对首尾弦的偏移。

    返回字典：弦长、偏移量、偏移比例（%）、偏移方向（单位向量）、每个中间关节的明细。
    两节链（上臂+前臂、大腿+小腿）的中间关节就是链上第二根骨的头，同样适用。
    链长不足 2 时返回 None。
    """
    if len(chain_names) < 2:
        return None
    root_head = bone_index[chain_names[0]]["head"]
    end_tail = bone_index[chain_names[-1]]["tail"]
    chord = end_tail - root_head
    chord_length = chord.length
    if chord_length < 1e-9:
        return None
    chord_unit = chord / chord_length

    joints = []
    for name in chain_names[1:]:
        head = bone_index[name]["head"]
        offset = head - root_head
        along = offset.dot(chord_unit)
        perpendicular = offset - chord_unit * along
        joints.append({
            "bone": name,
            "offset": perpendicular.length,
            "ratio_percent": perpendicular.length / chord_length * 100.0,
            "direction": perpendicular.normalized() if perpendicular.length > 1e-9 else None,
        })

    max_ratio = max(joint["ratio_percent"] for joint in joints)
    representative = max(joints, key=lambda joint: joint["offset"])
    return {
        "chord_length": chord_length,
        "joints": joints,
        "max_offset_ratio_percent": max_ratio,
        "direction": representative["direction"],
        "direction_bone": representative["bone"],
    }


def chain_segment_length(bone_index, chain_names):
    """链的总长（头到尾），用于核对"够不够长"。"""
    if not chain_names:
        return 0.0
    head = bone_index[chain_names[0]]["head"]
    tail = bone_index[chain_names[-1]]["tail"]
    return (tail - head).length


def palm_plane_normal(bone_index, hand_name, index_root=None, pinky_root=None, side=None):
    """手掌平面法线：用**食指根、小指根、手腕**三个点定平面（作者 2026-11-17 的口径）。

    三点不共线（手腕离开两指的连线），比"手方向 × 掌宽"稳；四个指根几乎共线，
    拿它们拟合平面是病态的（实测偏 60°）。

    **左右手要换向**：同一个点序算出来的叉积，在镜像的右手上给出的是相反的那一侧
    （靠手腕 → 食指根 → 小指根的绕行方向，左手和右手天然相反）。所以左手的法线取
    `(食指根-腕)×(小指根-腕)`、右手取它的反号 —— 这一步不做，右手的"指甲侧"会整体翻 180°，
    手指就会朝手背弯（2026-11-18 作者看图发现的）。
    """
    if not (index_root and pinky_root and hand_name):
        return None
    for name in (index_root, pinky_root, hand_name):
        if name not in bone_index:
            return None
    if side is None:
        side = role_from_name(hand_name)["side"]
    wrist = bone_index[hand_name]["head"]
    index_head = bone_index[index_root]["head"]
    pinky_head = bone_index[pinky_root]["head"]
    normal = (index_head - wrist).cross(pinky_head - wrist)
    if normal.length < 1e-9:
        return None
    normal.normalize()
    if side == "R":
        normal = -normal
    return normal


def thumb_bend_plane_direction(bone_index, hand_name, thumb_entry, front_axis):
    """拇指 Z 的目标方向（作者 2026-11-18 的口径）。

    **肘、腕、拇指末端三点定一个平面，拇指就在这个平面里弯** —— 这个平面就是它的拱形平面。
    平面里有两个方向，取**朝向人物前方**的那一个（拇指指甲朝前），其余骨骼的 Z 再各自
    投影到"垂直于该骨方向"的平面上即可（`align_roll_to` 就是这么做的）。

    与人物是 T 型还是 A 型姿态无关：只用到这三个关节的相对位置和"前方"，不用骨头的 roll。
    返回单位向量；三点共线 / 前方几乎垂直于该平面时返回 None（调用方退回老办法）。
    """
    if not (hand_name and thumb_entry and thumb_entry.get("last")):
        return None
    if hand_name not in bone_index or thumb_entry["last"] not in bone_index:
        return None
    wrist = bone_index[hand_name]["head"]
    thumb_tip = bone_index[thumb_entry["last"]]["tail"]

    # 肘：从手往上走，第一根"前臂"骨的头（中间可能夹着扭转骨，所以按角色找，不按层数）。
    elbow = None
    current = bone_index.get(hand_name, {}).get("parent")
    guard = 0
    while current and guard < 8:
        if role_from_name(current)["role"] == "forearm":
            elbow = bone_index[current]["head"]
            break
        current = bone_index[current]["parent"]
        guard += 1
    if elbow is None:
        return None

    normal = (wrist - elbow).cross(thumb_tip - elbow)
    if normal.length < 1e-9:
        return None
    normal.normalize()
    in_plane = front_axis - normal * front_axis.dot(normal)
    if in_plane.length < 0.2:
        return None
    return in_plane.normalized()


def finger_nail_directions(bone_index, hand_name, entries, front_axis=None):
    """每根手指的 Z 目标方向（指甲侧），作者 2026-11-18 更正后的口径：

    - **四指**：手掌平面（食指根 / 小指根 / 手腕三点）的法线，**左右手符号相反**
      （见 `palm_plane_normal`；不再用"现有 Z 的多数票"来自动纠符号 —— 那一步在右手上
      一直是"照着错的原始朝向投赞成票"，投不出来）；四指共用同一个方向；
    - **拇指**：**肘 / 腕 / 拇指末端三点定弯曲平面**，取平面内朝向人物前方的那一侧
      （见 `thumb_bend_plane_direction`）。

    给了 `front_axis` 才用新的拇指口径；没给时退回老办法（拇指链自身拱形凸侧），只为兼容
    没有前方向信息的调用。返回 {role: 单位向量}。
    """
    side = role_from_name(hand_name)["side"]
    palm = palm_plane_normal(bone_index, hand_name,
                             (entries.get("index") or {}).get("root"),
                             (entries.get("pinky") or {}).get("root"),
                             side=side)
    if palm is None:
        return {}

    directions = {}
    for role, entry in entries.items():
        if role != "thumb":
            directions[role] = palm
            continue
        thumb_direction = None
        if front_axis is not None:
            thumb_direction = thumb_bend_plane_direction(bone_index, hand_name, entry, front_axis)
        if thumb_direction is None:
            thumb_direction = _thumb_arch_direction(bone_index, entries, entry, palm)
        if thumb_direction is not None:
            directions[role] = thumb_direction
    return directions


def _thumb_arch_direction(bone_index, entries, entry, palm):
    """拇指的老口径（兜底用）：取自身链的拱形凸侧；拱形退化时把手掌法线绕拇指轴转 90°。"""
    from mathutils import Quaternion

    arch = chain_arch(bone_index, entry["segments"])
    if arch and arch["direction"] is not None and arch["max_offset_ratio_percent"] >= 0.5:
        return arch["direction"].normalized()
    y_axis = bone_direction(bone_index[entry["last"]])
    rotated = palm.copy()
    if y_axis.length > 1e-9:
        rotated.rotate(Quaternion(y_axis, math.radians(90.0)))
    index_root = (entries.get("index") or {}).get("root")
    if index_root and index_root in bone_index:
        to_index = bone_index[index_root]["head"] - bone_index[entry["last"]]["head"]
        to_index = to_index - y_axis * to_index.dot(y_axis)
        if to_index.length > 1e-9 and rotated.dot(to_index) > 0.0:
            rotated = -rotated
    return rotated.normalized()
