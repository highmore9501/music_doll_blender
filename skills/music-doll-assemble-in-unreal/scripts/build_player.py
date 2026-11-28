"""在 UE 里组装一个 MusicDoll 演奏者：导入 fbx → 接材质 → 建关卡 → 挂 BB_ 父级。

用法：把这份文件交给编辑器执行（Python 控制台、`-ExecutePythonScript=`、MCP 的 Python 工具都行），
先改下面的 CONFIG —— 里面的路径、资产名、乐器类**全是示例**，换成你自己工程里的。

顺序很重要：
  1) 导 fbx（骨骼网格 / 绑骨部件 / 世界部件）
  2) 导贴图
  3) 材质实例接到项目里的 mmd 母材质 + diffuse
  4) 建关卡、放乐器演员（BB_）、摆件、挂件

两个限制（不是这份脚本的 bug，是 UE 的）：
  - 建 SkeletalMeshSocket 没有 Python API，socket 得手动在 Mesh Editor 里加、或用 MCP 的
    skeletal_mesh.add_socket（见同目录 add_sockets.mjs）
  - 当前正打开着的关卡删不掉，跑之前先切到别的关卡
"""

import unreal

# --------------------------------------------------------------------------- 配置
# 全部是可选项示例（取自一次真实组装），换成自己工程的路径与名字。
CONFIG = {
    "folder": "/Game/MyCharacters/<角色名>",
    "texture_folder": "/Game/MyCharacters/<角色名>/Textures",
    "level": "/Game/MyCharacters/<角色名>/L_<场景名>",
    "fbx_dir": r"D:\path\to\exported_fbx",
    "fbx_files": [
        "<前缀>_body.fbx",
        "<前缀>_drum_kit.fbx",
        "<前缀>_stick_L.fbx",
        "<前缀>_stick_R.fbx",
        "<前缀>_stool.fbx",
    ],
    "texture_dir": r"D:\path\to\exported_textures",
    # (磁盘文件名, UE 里的资产名)：文件名来自 Blender 侧从 .blend 里抠出来的 png
    "textures": [
        ("<图1>.png", "<资产名1>"),
        ("<图2>.png", "<资产名2>"),
    ],
    "mmd_material": "/Game/<项目里那个只吃一张贴图的 mmd 母材质>",
    # 材质实例名 → 贴图资产名（材质实例名就是 Blender 里的材质名，导入时原样带进来）
    "material_textures": {
        "<材质名1>": "<资产名1>",
        "<材质名2>": "<资产名2>",
    },
    "default_material_texture": "<资产名1>",   # 表里没列到的槽位都用这张
    "instrument_class": "BeatBloomUnreal",    # 鼓手；钢琴 KeyRippleUnreal、吉他 FretDanceUnreal…
    "bb_label": "BB_<角色名>",
    "character_prefix": "<角色名>",
    # (标签, 资产名, socket 名)；socket 为 None 表示世界部件（挂到 BB_ 演员下面）
    "parts": [
        ("<角色名>_Body", "<前缀>_body", None),
        ("<角色名>_DrumKit", "<前缀>_drum_kit", None),
        ("<角色名>_Stool", "<前缀>_stool", None),
        ("<角色名>_Stick_L", "<前缀>_stick_L", "<socket 名 L>"),
        ("<角色名>_Stick_R", "<前缀>_stick_R", "<socket 名 R>"),
    ],
}

library = unreal.EditorAssetLibrary
asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

report = {}


# --------------------------------------------------------------------------- 1 导 fbx
imported = {}
for file_name in CONFIG["fbx_files"]:
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", CONFIG["fbx_dir"] + "\\" + file_name)
    task.set_editor_property("destination_path", CONFIG["folder"])
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)
    task.set_editor_property("replace_existing", True)
    asset_tools.import_asset_tasks([task])
    imported[file_name] = [str(path) for path in task.get_editor_property("imported_object_paths")]
report["import_fbx"] = imported


# --------------------------------------------------------------------------- 2 导贴图
textures = {}
for file_name, asset_name in CONFIG["textures"]:
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", CONFIG["texture_dir"] + "\\" + file_name)
    task.set_editor_property("destination_path", CONFIG["texture_folder"])
    task.set_editor_property("destination_name", asset_name)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)
    task.set_editor_property("replace_existing", True)
    asset_tools.import_asset_tasks([task])
    texture = library.load_asset(CONFIG["texture_folder"] + "/" + asset_name)
    if texture is not None:
        textures[asset_name] = texture
report["textures"] = sorted(textures.keys())


# --------------------------------------------------------------------------- 3 材质
mmd_material = library.load_asset(CONFIG["mmd_material"])
material_results = []
for asset_path in library.list_assets(CONFIG["folder"], recursive=False, include_folder=False):
    short_name = str(asset_path).split(".")[-1]
    instance = library.load_asset(str(asset_path))
    if not isinstance(instance, unreal.MaterialInstanceConstant):
        continue
    texture_name = CONFIG["material_textures"].get(short_name, CONFIG["default_material_texture"])
    texture = textures.get(texture_name)
    entry = {"material": short_name, "texture": texture_name}
    try:
        instance.set_editor_property("parent", mmd_material)
        if texture is not None:
            unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(instance, "diffuse", texture)
        unreal.MaterialEditingLibrary.update_material_instance(instance)
        library.save_loaded_asset(instance)
        entry["ok"] = True
    except Exception as error:
        entry["error"] = str(error)
    material_results.append(entry)
report["materials"] = material_results


# --------------------------------------------------------------------------- 4 关卡 + 挂件
if library.does_asset_exist(CONFIG["level"]):
    # 已经存在就别硬来：换个任务/手动删掉再跑，删一个正打开的关卡是失败的
    report["level"] = "已存在，跳过新建：" + CONFIG["level"]
else:
    report["new_level"] = level_subsystem.new_level(CONFIG["level"])

instrument_class = getattr(unreal, CONFIG["instrument_class"])
bb_actor = actor_subsystem.spawn_actor_from_class(instrument_class, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0))
bb_actor.set_actor_label(CONFIG["bb_label"])
report["bb_actor"] = {"label": bb_actor.get_actor_label(), "class": bb_actor.get_class().get_name()}

keep = unreal.AttachmentRule.KEEP_RELATIVE
snap = unreal.AttachmentRule.SNAP_TO_TARGET
body_actor = None
spawned = []
for label, asset_name, socket_name in CONFIG["parts"]:
    mesh = library.load_asset(CONFIG["folder"] + "/" + asset_name + "." + asset_name)
    if mesh is None:
        spawned.append({"label": label, "error": "资产没加载到"})
        continue
    actor = actor_subsystem.spawn_actor_from_object(mesh, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0))
    actor.set_actor_label(label)

    root_component = actor.get_editor_property("root_component")
    if root_component is not None:
        try:
            root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        except Exception:
            pass

    entry = {"label": label, "class": actor.get_class().get_name()}
    if socket_name is None:
        actor.attach_to_actor(bb_actor, "", keep, keep, keep, True)
        entry["parent"] = "BB"
        if asset_name.endswith("body"):
            body_actor = actor
    else:
        entry["attached"] = bool(actor.attach_to_actor(body_actor, socket_name, snap, snap, snap, True))
        entry["socket"] = socket_name
    spawned.append(entry)
report["spawned"] = spawned
report["saved_level"] = level_subsystem.save_current_level()

# --------------------------------------------------------------------------- 5 读回
verify = []
for actor in actor_subsystem.get_all_level_actors():
    entry = {"label": actor.get_actor_label(), "class": actor.get_class().get_name()}
    parent = actor.get_attach_parent_actor()
    if parent:
        entry["parent"] = parent.get_actor_label()
        entry["socket"] = str(actor.get_attach_parent_socket_name())
    try:
        origin, extent = actor.get_actor_bounds(False)
        entry["bounds"] = [
            [round(origin.x - extent.x, 1), round(origin.y - extent.y, 1), round(origin.z - extent.z, 1)],
            [round(origin.x + extent.x, 1), round(origin.y + extent.y, 1), round(origin.z + extent.z, 1)],
        ]
    except Exception as error:
        entry["bounds_error"] = str(error)
    verify.append(entry)
report["level_actors"] = verify

result = report
