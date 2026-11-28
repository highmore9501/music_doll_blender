"""第 1–2 步：在 BigCollection 里搭出 BB_<角色> 一组，填好引用，加载乐器配置，并从网格生成两套 Control Rig。

跑之前改下面的 CONFIG。任何一步失败都写在返回的 JSON 里，不静默跳过。
"""

import os

import unreal

# ============================== CONFIG ==============================
LEVEL_PATH = "/Game/BigCollection"
FOLDER = "/Game/MyCharacters/米娅鼓手"                 # 人物与鼓组资产所在目录
KIT_RIG_FOLDER = "/Game/MusicInstructment/米娅_drumkit"  # 鼓组 rig 放这里，跟其它乐手一致
BODY_MESH = FOLDER + "/米娅-星彩_body"
KIT_MESH = FOLDER + "/米娅-星彩_drum_kit"
STOOL_MESH = FOLDER + "/米娅-星彩_stool"
STICK_L_MESH = FOLDER + "/米娅-星彩_stick_L"
STICK_R_MESH = FOLDER + "/米娅-星彩_stick_R"

BB_LABEL = "BB_米娅"
STICK_SOCKETS = ("Stick_L", "Stick_R")

# 数据文件：作者机器在 H 盘；换机器时把文件拷过去、用 CONFIG_LOAD_PATH 加载，
# 加载完属性会改回 CONFIG_PATH（惯例路径，给下一个人看）。
CONFIG_PATH = "H:/beat_bloom_rust/asset/drum_kit/米娅_blender.drumkit"
CONFIG_LOAD_PATH = CONFIG_PATH
DRUMMER_FILE = "H:/beat_bloom_rust/asset/avatar/米娅_unreal.drummer"
ANIMATION_FILE = ""

PERFORMER_RIG = FOLDER + "/米娅_Drummer_CtrlRig"
KIT_RIG = KIT_RIG_FOLDER + "/米娅_DrumKit_CtrlRig"

# 参照位置：摆到这个乐手旁边，避免整套人叠在别人身上
REFERENCE_LABEL = "BB_辛焱"
OFFSET = (400.0, 0.0, 0.0)
# ====================================================================

library = unreal.EditorAssetLibrary
actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
assembly = unreal.MusicDollAssemblyTools

report = {"phases": {}}


def phase(name, payload):
    report["phases"][name] = payload


def struct_field(struct_value, *names, default=None):
    """工具集的结构体在 Python 里把 bXxx 暴露成 xxx，两种写法都试。"""
    for name in names:
        try:
            return getattr(struct_value, name)
        except Exception:
            pass
        try:
            return struct_value.get_editor_property(name)
        except Exception:
            pass
    return default


def messages_of(result_struct):
    return [str(message) for message in (struct_field(result_struct, "messages", default=[]) or [])]


current_world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
if LEVEL_PATH.split("/")[-1] not in (current_world.get_path_name() if current_world else ""):
    phase("load_level", level_subsystem.load_level(LEVEL_PATH))

# ---- 清掉同名旧 actor：脚本可重复执行 ----
removed = []
for actor in actor_subsystem.get_all_level_actors():
    label = actor.get_actor_label()
    if label == BB_LABEL or label.startswith(BB_LABEL.replace("BB_", "") + "_"):
        removed.append(label)
        actor_subsystem.destroy_actor(actor)
phase("removed_previous", removed)

# ---- 摆位 ----
reference_location = unreal.Vector(0, 0, 0)
for actor in actor_subsystem.get_all_level_actors():
    if actor.get_actor_label() == REFERENCE_LABEL:
        reference_location = actor.get_actor_location()
        break
target_location = unreal.Vector(reference_location.x + OFFSET[0],
                                reference_location.y + OFFSET[1],
                                reference_location.z + OFFSET[2])
phase("location", [round(target_location.x, 1), round(target_location.y, 1), round(target_location.z, 1)])

keep = unreal.AttachmentRule.KEEP_RELATIVE
snap = unreal.AttachmentRule.SNAP_TO_TARGET

beat_bloom = actor_subsystem.spawn_actor_from_class(unreal.BeatBloomUnreal, target_location,
                                                    unreal.Rotator(0, 0, 0))
beat_bloom.set_actor_label(BB_LABEL)


def spawn_mesh(label, asset_path, parent=None, socket=""):
    mesh = library.load_asset(asset_path)
    if mesh is None:
        return {"error": "asset missing: " + asset_path}
    actor = actor_subsystem.spawn_actor_from_object(mesh, target_location, unreal.Rotator(0, 0, 0))
    actor.set_actor_label(label)
    component_name = "static_mesh_component" if isinstance(mesh, unreal.StaticMesh) else "skeletal_mesh_component"
    try:
        actor.get_editor_property(component_name).set_mobility(unreal.ComponentMobility.MOVABLE)
    except Exception as error:
        return {"error": "set_mobility: " + str(error)[:120]}
    entry = {"class": actor.get_class().get_name()}
    if parent is not None:
        rules = snap if socket else keep
        entry["attached"] = bool(actor.attach_to_actor(parent, socket, rules, rules, rules, True))
        entry["socket"] = str(actor.get_attach_parent_socket_name()) if entry["attached"] else None
    return actor if parent is None else actor


body_actor = spawn_mesh(BB_LABEL.replace("BB_", "") + "_Body", BODY_MESH, beat_bloom)
kit_actor = spawn_mesh(BB_LABEL.replace("BB_", "") + "_DrumKit", KIT_MESH, beat_bloom)
stool_actor = spawn_mesh(BB_LABEL.replace("BB_", "") + "_Stool", STOOL_MESH, beat_bloom)
stick_l = spawn_mesh(BB_LABEL.replace("BB_", "") + "_Stick_L", STICK_L_MESH, body_actor, STICK_SOCKETS[0])
stick_r = spawn_mesh(BB_LABEL.replace("BB_", "") + "_Stick_R", STICK_R_MESH, body_actor, STICK_SOCKETS[1])
phase("spawned", {
    "body": getattr(body_actor, "get_actor_label", lambda: None)(),
    "kit": getattr(kit_actor, "get_actor_label", lambda: None)(),
    "stool": getattr(stool_actor, "get_actor_label", lambda: None)(),
    "sticks": [getattr(stick_l, "get_actor_label", lambda: None)(),
               getattr(stick_r, "get_actor_label", lambda: None)()],
})

# Outliner 里所有乐手平铺在 players 目录下，父级与子物体都在这一层
PLAYERS_FOLDER = "players"
for actor in (beat_bloom, body_actor, kit_actor, stool_actor, stick_l, stick_r):
    if hasattr(actor, "set_folder_path"):
        actor.set_folder_path(PLAYERS_FOLDER)
phase("folder", PLAYERS_FOLDER)

# ---- 1 填引用（工具集写后读回）----
reference_result = assembly.set_performer_references(beat_bloom, body_actor, kit_actor)
phase("references", {
    "success": struct_field(reference_result, "success", "b_success", default=False),
    "messages": messages_of(reference_result),
})
beat_bloom.set_editor_property("io_file_path", DRUMMER_FILE)
beat_bloom.set_editor_property("animation_file_path", ANIMATION_FILE)

# ---- 1b 加载乐器配置 ----
config_result = assembly.load_performer_config(beat_bloom, CONFIG_LOAD_PATH)
phase("config", {
    "success": struct_field(config_result, "success", "b_success", default=False),
    "components": struct_field(config_result, "affected_count", default=0),
    "messages": messages_of(config_result),
})
if CONFIG_LOAD_PATH != CONFIG_PATH:
    beat_bloom.set_editor_property("drum_kit_config_path", CONFIG_PATH)
config = beat_bloom.get_editor_property("drum_kit_config")
phase("config_state", {
    "path": beat_bloom.get_editor_property("drum_kit_config_path"),
    "components": len(config.get_editor_property("components")),
    "recorders": len(beat_bloom.get_editor_property("recorder_transforms")),
})

# ---- 2 生成两套 Control Rig 资产 ----
def ensure_rig(asset_path, mesh_asset_path):
    if not library.does_asset_exist(asset_path):
        mesh = library.load_asset(mesh_asset_path)
        rig = unreal.ControlRigBlueprintFactory.create_control_rig_from_skeletal_mesh_or_skeleton(mesh)
        if rig is None:
            return {"error": "create_control_rig failed"}
        library.rename_asset(rig.get_path_name().split(".")[0], asset_path)
        library.save_asset(asset_path)
    rig = library.load_asset(asset_path)
    return {
        "path": rig.get_path_name(),
        "class": rig.get_class().get_name(),
        "generated_class": rig.get_control_rig_class().get_path_name() if rig.get_control_rig_class() else None,
    }


phase("performer_rig", ensure_rig(PERFORMER_RIG, BODY_MESH))
phase("kit_rig", ensure_rig(KIT_RIG, KIT_MESH))

level_subsystem.save_current_level()
report["ok"] = True
result = report
