"""第 12–13 步：导入演奏者数据（Unreal 坐标的那份）→ 生成动画 → 量一下序列里真有多少键。

生成动画读的是动画数据文件（鼓手是 .beatbloom），它里面记着两个 .animation 的绝对路径；
换机器时要么把这两个文件也拷过去，要么把 .beatbloom 里的路径改成镜像路径
（这里就是拷过去 + 复制一份改了路径的 .beatbloom）。
"""

import unreal

# ============================== CONFIG ==============================
LEVEL_PATH = "/Game/BigCollection"
SEQUENCE_PATH = "/Game/我开始摇滚了"
BB_LABEL = "BB_米娅"

# 演奏者数据（Unreal 坐标）：本机镜像路径；导入后属性改回惯例路径
DRUMMER_PATH = "D:/kr_import/beat_bloom/asset/avatar/米娅_unreal.drummer"
DRUMMER_CANONICAL = "H:/beat_bloom_rust/asset/avatar/米娅_unreal.drummer"

# 动画数据：指向镜像路径的那份 .beatbloom
BEATBLOOM_PATH = "D:/kr_import/beat_bloom/output/final_result/米娅_mirror.beatbloom"
BEATBLOOM_CANONICAL = "H:/beat_bloom_rust/output/final_result/米娅_blender_猪猪侠_drums_all_0.beatbloom"

REFERENCE_LABEL = "BB_夜兰"      # 已经生成过的乐手，用对照键的数量量级
# ====================================================================

library = unreal.EditorAssetLibrary
assembly = unreal.MusicDollAssemblyTools
actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def first_value(struct_value, *names, default=None):
    """工具集的结构体在 Python 里把 bXxx 暴露成 xxx，两种写法都试一遍。"""
    for name in names:
        try:
            return getattr(struct_value, name)
        except Exception:
            continue
    return default


report = {}
level_subsystem.load_level(LEVEL_PATH)
sequence = library.load_asset(SEQUENCE_PATH)
unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)

actors = {}
for actor in actor_subsystem.get_all_level_actors():
    if actor.get_actor_label() in (BB_LABEL, REFERENCE_LABEL):
        actors[actor.get_actor_label()] = actor
report["actors"] = sorted(actors.keys())

performer = actors.get(BB_LABEL)
if performer is None:
    report["ok"] = False
    report["error"] = "关卡里没有 " + BB_LABEL
    result = report
    raise SystemExit

# ---- 导入记录器位姿 ----
imported = assembly.import_performer_data(performer, DRUMMER_PATH)
report["import"] = {
    "success": bool(first_value(imported, "success", "b_success", default=False)),
    "recorders": int(first_value(imported, "affected_count", "affectedCount", default=0)),
    "messages": [str(message) for message in (first_value(imported, "messages", default=[]) or [])],
}
performer.set_editor_property("io_file_path", DRUMMER_CANONICAL)

# ---- 生成动画 ----
performer.set_editor_property("animation_file_path", BEATBLOOM_PATH)
try:
    unreal.BeatBloomAnimationProcessor.generate_all_animation(performer)
    report["generate"] = "ok"
except Exception as error:
    report["generate"] = "ERR " + str(error)[:500]
performer.set_editor_property("animation_file_path", BEATBLOOM_CANONICAL)

report["saved_sequence"] = bool(library.save_asset(SEQUENCE_PATH))
report["saved_level"] = bool(level_subsystem.save_current_level())

# ---- 量键：参数数、通道数、总键数（与参照乐手对比）----
def measure_section(section):
    entry = {}
    try:
        entry["parameters"] = len(section.get_parameter_names())
    except Exception as error:
        entry["parameters_error"] = str(error)[:80]
    try:
        channels = section.get_all_channels()
        entry["channels"] = len(channels)
        total_keys = 0
        for channel in channels:
            try:
                total_keys += channel.get_num_keys()
            except Exception:
                pass
        entry["keys"] = total_keys
    except Exception as error:
        entry["channels_error"] = str(error)[:80]
    return entry


reloaded = library.load_asset(SEQUENCE_PATH)
for label in (BB_LABEL, REFERENCE_LABEL):
    prefix = label.replace("BB_", "")
    for binding in reloaded.get_bindings():
        if not binding.get_name().startswith(prefix):
            continue
        for track in binding.get_tracks():
            if track.get_class().get_name() != "MovieSceneControlRigParameterTrack":
                continue
            for section in track.get_sections():
                report.setdefault("keys", {})[binding.get_name()] = measure_section(section)

report["ok"] = report.get("generate") == "ok"
result = report
