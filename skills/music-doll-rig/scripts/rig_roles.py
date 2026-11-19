# -*- coding: utf-8 -*-
"""按名字判断骨骼角色（不依赖 bpy，纯字符串）。

一个骨名要回答两个问题：
- **它是什么**（role）：上臂 / 前臂 / 手掌 / 大腿 / 小腿 / 脚掌 / 脚趾；
- **它是哪一种**（variant）：
  - `plain`      —— 本体骨（通常是形变骨，也是 IK 链的首选）；
  - `shadow`     —— MMD 的 `足D` / `_dummy_` / `_shadow_` 影子链，附着在本体骨上；
  - `mechanism`  —— `MCH_` 主骨，非形变，只负责传递层级和承接约束；
  - `twist` / `segment` / `aux` / `leaf` / `ik` —— 结构骨，不参与"三段"判定。

这样同一个 `足首` 在 `足首`、`足首D`、`MCH_足首` 三种写法下都能被认出来，
调用方再按需选本体或主骨。
"""

NAME_PREFIXES = (
    ("_shadow_", "shadow"),
    ("_dummy_", "shadow"),
    ("MCH_", "mechanism"),
    ("MCH-", "mechanism"),
    ("MCH.", "mechanism"),
    ("Tar_", "aux"),
    ("DEF-", "plain"),
    ("ORG-", "aux"),
    ("cf_s_", "aux"),
    ("cf_d_", "plain"),
    ("+", "aux"),
)

SIDE_SUFFIXES = (
    (".L", "L"), (".R", "R"), (".l", "L"), (".r", "R"),
    ("_L", "L"), ("_R", "R"), ("_l", "L"), ("_r", "R"),
    ("-L", "L"), ("-R", "R"), (".Left", "L"), (".Right", "R"),
)
SIDE_PREFIXES = (
    ("Left", "L"), ("Right", "R"), ("L_", "L"), ("R_", "R"),
    # MMD 日文骨名把侧别写在前面：左腕 / 右ひじ / 左人指１
    ("左", "L"), ("右", "R"),
)

ROLE_STEMS = {
    "upper_arm": ("腕", "上腕", "上膊", "二の腕"),
    "forearm": ("ひじ", "肘", "前腕", "下腕"),
    "hand": ("手首", "手先", "手"),
    "thigh": ("足", "腿", "太腿", "太もも", "脚"),
    "shin": ("ひざ", "膝", "脛"),
    "foot": ("足首", "足先"),
    "toe": ("つま先", "足先EX"),
}

ROLE_KEYWORDS = (
    ("upper_arm", ("upperarm", "upper_arm", "upper arm", "arm", "arms")),
    ("forearm", ("forearm", "fore_arm", "lowerarm", "lower_arm", "lower arm", "elbow", "forearmbend")),
    ("hand", ("hand", "wrist")),
    ("thigh", ("thigh", "upperleg", "upper_leg", "upper leg", "thighbend", "thigh_def")),
    # 注意：不认光杆的 `leg` —— Daz 系把大腿叫 `Leg_L`、小腿叫 `Knee_L`，而有的骨架反过来，
    # 单看名字判不出来。大腿/小腿一律用"从脚掌往上数"的结构结果，名字只做复核。
    ("shin", ("shin", "lowerleg", "lower_leg", "lower leg", "calf", "knee", "shinbend")),
    ("foot", ("foot", "ankle")),
    ("toe", ("toe", "toes")),
)

TWIST_MARKERS = ("捩", "twist", "Twist")
AUX_MARKERS = ("Aux", "aux", "補助", "helper", "Helper", "stretch", "Stretch", "scale_fix", "pole", "Pole", "_track_")
LEAF_MARKERS = ("先", "先端", "tip", "Tip", "末端", "Nub", "nub", "Leaf", "leaf", "End", "end")
IK_MARKERS = ("IK", "ik", "ＩＫ")


def parse_bone_name(name):
    """拆出 (变体标记列表, 主干, 侧别)。主干去掉机制/影子前缀和侧别后缀。"""
    working = name
    tags = []
    changed = True
    while changed:
        changed = False
        for prefix, tag in NAME_PREFIXES:
            if working.startswith(prefix) and len(working) > len(prefix):
                tags.append(tag)
                working = working[len(prefix):]
                changed = True
                break

    side = None
    for suffix, suffix_side in SIDE_SUFFIXES:
        if working.endswith(suffix) and len(working) > len(suffix):
            side = suffix_side
            working = working[: -len(suffix)]
            break
    if side is None:
        for prefix, prefix_side in SIDE_PREFIXES:
            if working.startswith(prefix) and len(working) > len(prefix):
                side = prefix_side
                working = working[len(prefix):]
                break
    # VRM 这类把侧别夹在中间：J_Bip_L_Foot / J_Bip_R_Hand
    if side is None:
        for infix, infix_side in (("_L_", "L"), ("_R_", "R"), (".L.", "L"), (".R.", "R")):
            if infix in working:
                side = infix_side
                break
    return tags, working, side


def role_from_name(name):
    """返回 dict：role / variant / confidence / reason。

    role 为 None 表示"不是三段主骨"。variant 说明它属于哪一种骨。
    """
    tags, stem, side = parse_bone_name(name)
    lower_stem = stem.lower()
    bare_stem = lower_stem.replace("_", "").replace(".", "").replace(" ", "")

    def result(role, variant, confidence, reason=None):
        return {"role": role, "variant": variant, "confidence": confidence, "reason": reason,
                "stem": stem, "side": side}

    # 影子 / 机制前缀直接决定变体，但角色仍然按主干认
    variant_from_prefix = "plain"
    if "shadow" in tags:
        variant_from_prefix = "shadow"
    elif "mechanism" in tags:
        variant_from_prefix = "mechanism"
    # 有的骨架把 MCH 写在中间：Elbow_MCH_L / Arm_MCH_L
    if variant_from_prefix == "plain":
        for token in stem.replace("-", "_").replace(".", "_").split("_"):
            if token.upper() == "MCH":
                variant_from_prefix = "mechanism"
                break
    # 机制骨（MCH）即使名字里带"捩/twist"也仍然是链上的真骨（东风谷早苗 的 MCH_手捩 就是前臂），
    # 所以变体永远给 mechanism，把结构标记降级成 reason。
    def structural(marker):
        if variant_from_prefix == "mechanism":
            return result(None, "mechanism", None, marker)
        if variant_from_prefix == "shadow":
            return result(None, "shadow", None, marker)
        return result(None, marker, None)

    # 结构骨先排除：扭转 / IK / 辅助 / 末端
    if any(marker in stem for marker in TWIST_MARKERS) or "twist" in lower_stem:
        return structural("twist")
    if any(marker in stem for marker in IK_MARKERS) or "ik" in lower_stem.replace("pick", ""):
        return structural("ik")
    if any(marker in stem for marker in AUX_MARKERS):
        return structural("aux")
    if any(marker in stem for marker in LEAF_MARKERS):
        return structural("leaf")
    # 末尾的 D 是 MMD 影子链（足D / ひざD / 足首D）；只认大写 D
    if len(stem) > 1 and stem.endswith("D"):
        inner = role_from_name(stem[:-1])
        if inner["role"]:
            return result(inner["role"], "shadow", inner["confidence"], "D-suffix")

    role = None
    confidence = None
    for candidate_role, stems in ROLE_STEMS.items():
        if stem in stems:
            role, confidence = candidate_role, "high"
            break
    if role is None:
        ordered = ("upper_arm", "forearm", "hand", "thigh", "shin", "foot", "toe")
        by_role = dict(ROLE_KEYWORDS)
        for candidate_role in ordered:
            for keyword in by_role[candidate_role]:
                if bare_stem == keyword.replace("_", "").replace(" ", ""):
                    role, confidence = candidate_role, "high"
                    break
            if role:
                break
    if role is None:
        # 包含匹配：关键词从长到短试，否则 `forearm_ref` 会先命中 `arm`（上臂）而不是 `forearm`
        ordered = ("upper_arm", "forearm", "hand", "thigh", "shin", "foot", "toe")
        by_role = dict(ROLE_KEYWORDS)
        keyword_pairs = []
        for candidate_role in ordered:
            for keyword in by_role[candidate_role]:
                keyword_pairs.append((keyword.replace("_", "").replace(" ", ""), candidate_role))
        keyword_pairs.sort(key=lambda item: -len(item[0]))
        for keyword, candidate_role in keyword_pairs:
            if keyword in bare_stem:
                role, confidence = candidate_role, "low"
                break

    if role is None:
        # 分段骨（Arm01 / Elbow01 / 人指１）：主干末尾是数字，不算三段主骨
        if stem and stem[-1] in "1234567890０１２３４５６７８９":
            return result(None, "segment", None)
        return result(None, "plain", None)

    # 名字带数字后缀的分段骨，即使角色认得也别当成主骨（如 Arm01_L）
    if stem and stem[-1] in "1234567890０１２３４５６７８９":
        return result(None, "segment", None, "numeric-segment")

    return result(role, variant_from_prefix, confidence)
