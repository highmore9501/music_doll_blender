"""验收：一次读全一个演奏者的装配状态（引用 / 配置 / 两套 rig / 映射表 / 图表骨骼引用 / 序列绑定）。

只读，不改任何东西。
"""

import re

import unreal

# ============================== CONFIG ==============================
PERFORMER_LABEL = "BB_米娅"
SEQUENCE_PATH = "/Game/我开始摇滚了"
PERFORMER_RIG = "/Game/MyCharacters/米娅鼓手/米娅_Drummer_CtrlRig"
KIT_RIG = "/Game/MusicInstructment/米娅_drumkit/米娅_DrumKit_CtrlRig"
# ====================================================================

library = unreal.EditorAssetLibrary
assembly = unreal.MusicDollAssemblyTools
BONE_RE = re.compile(r'\(Type=Bone,Name="([^"]*)"\)')

report = {}
actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

performer = None
for actor in actor_subsystem.get_all_level_actors():
    if actor.get_actor_label() == PERFORMER_LABEL:
        performer = actor
        break
report["performer_found"] = performer is not None

if performer is not None:
    state = assembly.inspect_assembly(performer)
    report["state"] = {
        "label": getattr(state, "label", None),
        "class": getattr(state, "class_name", None),
        "performer_mesh": getattr(state, "performer_mesh", None),
        "instrument_mesh": getattr(state, "instrument_mesh", None),
        "config_path": getattr(state, "config_path", None),
        "config_components": getattr(state, "config_component_count", 0),
        "recorders": getattr(state, "recorder_count", 0),
        "sequencer_open": getattr(state, "sequencer_open", False),
        "sequence": getattr(state, "sequence_path", None),
        "performer_rig": getattr(state, "performer_rig_name", None),
        "performer_rig_resolved": getattr(state, "performer_rig_resolved", False),
        "performer_controls": getattr(state, "performer_control_count", 0),
        "performer_bones": getattr(state, "performer_bone_count", 0),
        "instrument_rig": getattr(state, "instrument_rig_name", None),
        "instrument_rig_resolved": getattr(state, "instrument_rig_resolved", False),
        "instrument_controls": getattr(state, "instrument_control_count", 0),
        "mapping_count": getattr(state, "mapping_count", 0),
        "has_bone_control_mapping": getattr(state, "has_bone_control_mapping", False),
        "messages": [str(message) for message in (getattr(state, "messages", []) or [])],
    }

# 鼓槌挂接（名字以 BB_ 前缀推出来）
body_label = PERFORMER_LABEL.replace("BB_", "") + "_Body"
sticks = {}
for actor in actor_subsystem.get_all_level_actors():
    label = actor.get_actor_label()
    if label.startswith(PERFORMER_LABEL.replace("BB_", "") + "_Stick"):
        sticks[label] = {
            "parent": actor.get_attach_parent_actor().get_actor_label()
            if actor.get_attach_parent_actor() else None,
            "socket": str(actor.get_attach_parent_socket_name()) if actor.get_attach_parent_actor() else None,
        }
report["sticks"] = sticks


def rig_profile(path):
    rig = library.load_asset(path)
    if rig is None:
        return {"error": "missing"}
    keys = rig.get_hierarchy().get_all_keys()
    counts = {}
    for key in keys:
        name = str(key.type)
        counts[name] = counts.get(name, 0) + 1
    leftover = {}
    bones = {str(key.name) for key in keys if key.type == unreal.RigElementType.BONE}
    for model in rig.get_all_models():
        for node in model.get_nodes():
            for pin in node.get_pins():
                try:
                    default_value = str(pin.get_default_value())
                except Exception:
                    continue
                for bone_name in BONE_RE.findall(default_value):
                    if bone_name not in bones and bone_name != "None":
                        leftover[bone_name] = leftover.get(bone_name, 0) + 1
    return {
        "class": rig.get_class().get_name(),
        "elements": len(keys),
        "counts": counts,
        "nodes": len(rig.get_default_model().get_nodes()),
        "models": len(rig.get_all_models()),
        "variables": [str(item.get_editor_property("name")) for item in rig.get_member_variables()],
        "leftover_bone_refs": leftover,
    }


report["performer_rig"] = rig_profile(PERFORMER_RIG)
report["kit_rig"] = rig_profile(KIT_RIG)

# 序列绑定：两面 rig 的轨道是否都在
sequence = library.load_asset(SEQUENCE_PATH)
if sequence:
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    bindings = {}
    for binding in sequence.get_bindings():
        tracks = [str(track.get_display_name()) for track in binding.get_tracks()
                  if track.get_class().get_name() == "MovieSceneControlRigParameterTrack"]
        if tracks:
            bindings[binding.get_name()] = tracks
    report["sequence_rig_bindings"] = {
        key: value for key, value in bindings.items()
        if key.startswith(PERFORMER_LABEL.replace("BB_", ""))
    }

result = report
