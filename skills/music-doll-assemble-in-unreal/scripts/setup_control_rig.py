"""第 5–6 步：初始化演奏者控件、初始化乐器控件、建骨骼控件映射变量，然后编译两套 rig。

顺序不能换：配置已加载 → 序列已绑 rig → 初始化 → 建变量 → 编译。
编译这一步对应界面上「Initialize 之后打开 Control Rig 编辑器 Compile 再保存」，
少了它，映射变量还没编译成属性，第 7 步写不进去。
"""

import unreal

# ============================== CONFIG ==============================
SEQUENCE_PATH = "/Game/我开始摇滚了"
PERFORMER_LABEL = "BB_米娅"
PERFORMER_RIG = "/Game/MyCharacters/米娅鼓手/米娅_Drummer_CtrlRig"
KIT_RIG = "/Game/MusicInstructment/米娅_drumkit/米娅_DrumKit_CtrlRig"
# ====================================================================

library = unreal.EditorAssetLibrary
assembly = unreal.MusicDollAssemblyTools

report = {}
sequence = library.load_asset(SEQUENCE_PATH)
unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)

performer = None
for actor in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if actor.get_actor_label() == PERFORMER_LABEL:
        performer = actor
        break
report["performer_found"] = performer is not None


def messages_of(result_struct):
    return [str(message) for message in (getattr(result_struct, "messages", []) or [])]


def first_value(struct_value, *names, default=None):
    """工具集的结构体在 Python 里把 bXxx 暴露成 xxx，两种写法都试一遍。"""
    for name in names:
        try:
            return getattr(struct_value, name)
        except Exception:
            continue
    return default


def describe(result_struct):
    return {
        "success": bool(first_value(result_struct, "success", "b_success", default=False)),
        "count": int(first_value(result_struct, "affected_count", default=0)),
        "messages": messages_of(result_struct),
    }


if performer is not None:
    # 5 演奏者控件（内部走 SetupAllObjects：建 base_root/controller_root 一套 + 加映射变量）
    report["performer_setup"] = describe(assembly.setup_performer_control_rig(performer))
    # 5b 乐器控件（鼓手走 InitializeDrumKit：建每个鼓件的 *_beat 控件与同名 float 通道）
    report["instrument_setup"] = describe(assembly.initialize_instrument_control_rig(performer))
    # 6 映射变量（幂等；已存在时是重置成空表）
    report["mapping_init"] = describe(assembly.init_bone_control_mapping(performer))

    # 6b 编译两套 rig：变量要编译成属性才能写
    performer_rig = library.load_asset(PERFORMER_RIG)
    kit_rig = library.load_asset(KIT_RIG)
    report["performer_compiled"] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(performer_rig))
    report["kit_compiled"] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(kit_rig))
    report["performer_saved"] = bool(library.save_asset(PERFORMER_RIG))
    report["kit_saved"] = bool(library.save_asset(KIT_RIG))

    # 复核
    state = assembly.inspect_assembly(performer)
    report["state"] = {
        "performer_rig": getattr(state, "performer_rig_name", None),
        "controls": getattr(state, "performer_control_count", 0),
        "bones": getattr(state, "performer_bone_count", 0),
        "mapping_count": getattr(state, "mapping_count", 0),
        "instrument_rig": getattr(state, "instrument_rig_name", None),
        "instrument_controls": getattr(state, "instrument_control_count", 0),
        "messages": [str(message) for message in (getattr(state, "messages", []) or [])],
    }

report["ok"] = bool(report.get("state", {}).get("controls"))
result = report
