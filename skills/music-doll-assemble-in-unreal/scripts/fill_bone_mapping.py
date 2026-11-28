"""第 7–8 步：骨骼控件映射表。

从「同类乐器里已经绑在序列上的那位乐手」读语义模板（哪个控件该落在哪根骨头），
按骨骼命名风格换算成新角色的骨头名，写进 BoneControlPairMapping，再同步控件位置。

换名规则是可配置的：模板和目标的骨骼命名风格不一样时（_L/_R 后缀 vs 左/右 前缀、先 vs ３_tip），
这里要按实际情况改 translate_bone。查不到的会列在 unresolved 里，不会硬塞。
"""

import re

import unreal

# ============================== CONFIG ==============================
SEQUENCE_PATH = "/Game/我开始摇滚了"
PERFORMER_LABEL = "BB_米娅"
TEMPLATE_LABEL = "BB_夜兰"           # 必须真的绑在这条序列里，否则读不到 rig
PERFORMER_RIG = "/Game/MyCharacters/米娅鼓手/米娅_Drummer_CtrlRig"

# 模板里没有、目标骨骼集合里也没有对应物的骨头：就近落到存在的那根上
SPECIAL = {
    "上半身3": "上半身2",
    "親指先_L": "左親指２_tip",
    "親指先_R": "右親指２_tip",
}
# ====================================================================

library = unreal.EditorAssetLibrary
assembly = unreal.MusicDollAssemblyTools

report = {}
sequence = library.load_asset(SEQUENCE_PATH)
unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)

actors = {}
for actor in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if actor.get_actor_label() in (PERFORMER_LABEL, TEMPLATE_LABEL):
        actors[actor.get_actor_label()] = actor
report["actors"] = sorted(actors.keys())

performer = actors.get(PERFORMER_LABEL)
template_actor = actors.get(TEMPLATE_LABEL)
if performer is None or template_actor is None:
    report["ok"] = False
    report["error"] = "缺演员：确认 %s 与 %s 都在关卡里" % (PERFORMER_LABEL, TEMPLATE_LABEL)
    result = report
else:
    template = [{"control": str(getattr(pair, "control_name")),
                 "bone": str(getattr(pair, "bone_name"))}
                for pair in assembly.get_bone_control_mapping(template_actor)]
    report["template"] = template

    rig = library.load_asset(PERFORMER_RIG)
    target_bones = {str(key.name) for key in rig.get_hierarchy().get_all_keys()
                    if key.type == unreal.RigElementType.BONE}
    report["target_bone_count"] = len(target_bones)

    def translate_bone(template_bone):
        """模板骨骼名 → 目标骨骼名：先按规则生成候选，再到目标骨头集合里查存在性。"""
        if template_bone in SPECIAL and SPECIAL[template_bone] in target_bones:
            return SPECIAL[template_bone]
        match = re.match(r"^(.*)_(L|R)$", template_bone)
        candidates = []
        if match:
            part, side = match.groups()
            prefix = "左" if side == "L" else "右"
            candidates.append(prefix + part)
            if part.endswith("先"):
                candidates.append(prefix + part[:-1] + "３_tip")
        candidates.append(template_bone)
        for candidate in candidates:
            if candidate in target_bones:
                return candidate
        return None

    pairs = []
    unresolved = []
    for item in template:
        bone = translate_bone(item["bone"])
        if bone is None:
            unresolved.append(item)
        else:
            pairs.append({"control": item["control"], "bone": bone})
    report["translated"] = pairs
    report["unresolved"] = unresolved

    # 7 写映射表（结构体类型要用工具集的 MusicDollBoneControlPairInfo）
    pair_structs = []
    for item in pairs:
        pair = unreal.MusicDollBoneControlPairInfo()
        pair.set_editor_property("bone_name", item["bone"])
        pair.set_editor_property("control_name", item["control"])
        pair_structs.append(pair)
    written = assembly.set_bone_control_mapping(performer, pair_structs)
    report["write"] = {
        "success": bool(getattr(written, "success", False)),
        "count": int(getattr(written, "affected_count", 0)),
        "messages": [str(message) for message in (getattr(written, "messages", []) or [])],
    }

    readback = assembly.get_bone_control_mapping(performer)
    report["readback"] = [{"control": str(getattr(pair, "control_name")),
                           "bone": str(getattr(pair, "bone_name"))} for pair in readback]

    # 8 同步控件位置（只有同步上，IK 才有正确的起点）
    synced = assembly.sync_bone_control_mapping(performer)
    report["sync"] = {
        "success": bool(getattr(synced, "success", False)),
        "synced": int(getattr(synced, "affected_count", 0)),
        "failed": int(getattr(synced, "failed_count", 0)),
        "messages": [str(message) for message in (getattr(synced, "messages", []) or [])],
    }

    # 复核：控件全局坐标应等于对应骨头的全局坐标
    hierarchy = rig.get_hierarchy()
    positions = {}
    for control_name, bone_name in (("H_L", "左手首"), ("H_R", "右手首"),
                                    ("F_L", "左足首D"), ("Head_Control", "頭")):
        entry = {}
        for key_type, name, label in ((unreal.RigElementType.CONTROL, control_name, "control"),
                                      (unreal.RigElementType.BONE, bone_name, "bone")):
            try:
                key = unreal.RigElementKey()
                key.set_editor_property("type", key_type)
                key.set_editor_property("name", name)
                transform = hierarchy.get_global_transform(key)
                entry[label] = [round(transform.translation.x, 2),
                                round(transform.translation.y, 2),
                                round(transform.translation.z, 2)]
            except Exception as error:
                entry[label + "_error"] = str(error)[:100]
        positions[control_name] = entry
    report["positions"] = positions

    library.save_asset(PERFORMER_RIG)
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    report["ok"] = report["sync"]["synced"] > 0 and not unresolved

result = report
