"""第 3 步：把人物骨骼与乐器骨骼加进对应序列，并给两者各绑一条 Control Rig 轨道。

插件的 rig 定位靠「扫当前打开的序列里的 Control Rig 轨道」，所以这一步是后面所有初始化的前置。
"""

import unreal

# ============================== CONFIG ==============================
SEQUENCE_PATH = "/Game/我开始摇滚了"     # 鼓手用这条；钢琴 /Game/双钢琴，其余用同乐器在演戏的那条
BODY_LABEL = "米娅_Body"
KIT_LABEL = "米娅_DrumKit"
PERFORMER_RIG = "/Game/MyCharacters/米娅鼓手/米娅_Drummer_CtrlRig"
KIT_RIG = "/Game/MusicInstructment/米娅_drumkit/米娅_DrumKit_CtrlRig"
# ====================================================================

library = unreal.EditorAssetLibrary
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

report = {}
sequence = library.load_asset(SEQUENCE_PATH)
report["sequence"] = sequence.get_path_name() if sequence else None
report["opened"] = bool(unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence))

wanted = {}
for actor in actor_subsystem.get_all_level_actors():
    if actor.get_actor_label() in (BODY_LABEL, KIT_LABEL):
        wanted[actor.get_actor_label()] = actor
report["found_actors"] = sorted(wanted.keys())

bindings = {binding.get_name(): binding for binding in sequence.get_bindings()}
results = {}
for label, rig_path in ((BODY_LABEL, PERFORMER_RIG), (KIT_LABEL, KIT_RIG)):
    actor = wanted.get(label)
    entry = {}
    if actor is None:
        entry["error"] = "actor missing（先跑 assemble_performer.py）"
        results[label] = entry
        continue

    binding = bindings.get(label)
    if binding is None:
        binding = unreal.MovieSceneSequenceExtensions.add_possessable(sequence, actor)
        entry["binding"] = "created: " + (str(binding.get_name()) if binding else "None")
    else:
        entry["binding"] = "reused"
    if binding is None:
        entry["error"] = "add_possessable failed"
        results[label] = entry
        continue

    rig = library.load_asset(rig_path)
    rig_class = rig.get_control_rig_class() if rig else None
    entry["rig"] = rig.get_path_name() if rig else None
    if rig_class is None:
        entry["error"] = "rig 没有 generated class（资产没编译过？）"
        results[label] = entry
        continue

    # 注意参数顺序：world, level_sequence, control_rig_class, binding
    track = unreal.ControlRigSequencerLibrary.find_or_create_control_rig_track(
        world, sequence, rig_class, binding)
    entry["track"] = str(track.get_display_name()) if track else None
    results[label] = entry

report["results"] = results
report["saved"] = bool(library.save_asset(SEQUENCE_PATH))

# 保存后重开一次核对：绑定名应等于骨骼 Actor 的 label，各有一条 Control Rig 轨道
unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(library.load_asset(SEQUENCE_PATH))
check = {}
for binding in library.load_asset(SEQUENCE_PATH).get_bindings():
    if binding.get_name() in (BODY_LABEL, KIT_LABEL):
        check[binding.get_name()] = [str(track.get_display_name()) for track in binding.get_tracks()]
report["after_save"] = check
report["ok"] = bool(check) and all(check.get(label) for label in (BODY_LABEL, KIT_LABEL))

result = report
