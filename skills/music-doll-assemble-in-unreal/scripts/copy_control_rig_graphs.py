"""第 9–10 步：把已调好的同类乐手的 Control Rig 图表搬过来，并改掉里面的骨骼名。

分两趟跑（MODE 切）：
  1) MODE="import"：把源 rig 的整张图导成文本、导进目标 rig（此时骨骼名还是源乐手的）；
  2) MODE="patch"：遍历目标 rig 的所有图表（含折叠节点的内部图），把引脚上的骨骼名换成新角色的，
     并修鼓组那张「常量 RigElementKey」通道清单（必须换成新乐器自己的 *_beat 控件），然后编译保存。

分两趟的原因：导进来的节点和它所在的图表要各自取 controller 才能改引脚，
同一趟里刚导入就改，折叠图可能还没登记好。
"""

import re

import unreal

# ============================== CONFIG ==============================
MODE = "import"          # "import" | "patch"

# 演奏者：源是同类乐器里已调好的那位（这里用夜兰，因为她在「我开始摇滚了」里绑着）
SOURCE_PERFORMER_RIG = "/Game/MyCharacters/夜兰/夜兰_drummer_CtrlRig"
TARGET_PERFORMER_RIG = "/Game/MyCharacters/米娅鼓手/米娅_Drummer_CtrlRig"

# 乐器（鼓组）：源与目标
SOURCE_KIT_RIG = "/Game/MusicInstructment/夜兰drumkit/夜兰_drumkit_CtrlRig"
TARGET_KIT_RIG = "/Game/MusicInstructment/米娅_drumkit/米娅_DrumKit_CtrlRig"

# 源乐手有、目标没有的骨头：就近落到目标存在的那根上
SPECIAL_BONES = {
    "上半身3": "上半身2",
    "親指先_L": "左親指２_tip",
    "親指先_R": "右親指２_tip",
    # 鼓槌是挂在手骨 socket 上的独立 Actor，rig 里没有 stick 骨头：指到手腕，鼓槌跟着手腕走
    "stick_L": "左手首",
    "stick_R": "右手首",
}
# ====================================================================

library = unreal.EditorAssetLibrary
report = {"mode": MODE}
BONE_RE = re.compile(r'\(Type=Bone,Name="([^"]*)"\)')


def export_graph(rig):
    controller = rig.get_controller()
    nodes = rig.get_default_model().get_nodes()
    return controller.export_nodes_to_text([str(node.get_name()) for node in nodes], True)


def walk_pins(pin_list):
    for pin in pin_list:
        yield pin
        try:
            sub_pins = pin.get_sub_pins()
        except Exception:
            sub_pins = []
        for sub_pin in walk_pins(sub_pins):
            yield sub_pin


def translate_bone(bone_name, target_bones):
    if bone_name in SPECIAL_BONES and SPECIAL_BONES[bone_name] in target_bones:
        return SPECIAL_BONES[bone_name]
    match = re.match(r"^(.*)_(L|R)$", bone_name)
    candidates = []
    if match:
        part, side = match.groups()
        prefix = "左" if side == "L" else "右"
        candidates.append(prefix + part)
        if part.endswith("先"):
            candidates.append(prefix + part[:-1] + "３_tip")
    candidates.append(bone_name)
    for candidate in candidates:
        if candidate in target_bones:
            return candidate
    return None


if MODE == "import":
    for label, source_path, target_path in (
            ("performer", SOURCE_PERFORMER_RIG, TARGET_PERFORMER_RIG),
            ("kit", SOURCE_KIT_RIG, TARGET_KIT_RIG)):
        source = library.load_asset(source_path)
        target = library.load_asset(target_path)
        text = export_graph(source)
        before = len(target.get_default_model().get_nodes())
        try:
            imported = target.get_controller().import_nodes_from_text(text, True)
            report[label] = {"imported": len(imported or []), "before": before,
                             "after": len(target.get_default_model().get_nodes())}
        except Exception as error:
            report[label] = {"error": str(error)[:400]}
        unreal.BlueprintEditorLibrary.compile_blueprint(target)
        library.save_asset(target_path)
    report["ok"] = all("error" not in report.get(key, {}) for key in ("performer", "kit"))

elif MODE == "patch":
    def patch_rig(rig_path):
        rig = library.load_asset(rig_path)
        target_bones = {str(item.name) for item in rig.get_hierarchy().get_all_keys()
                        if item.type == unreal.RigElementType.BONE}
        root_controller = rig.get_controller()
        changed = {}
        failed = []
        for model in rig.get_all_models():
            try:
                controller = root_controller.get_controller_for_graph(model)
            except Exception as error:
                failed.append({"model": str(model.get_name()), "error": str(error)[:120]})
                continue
            if controller is None:
                continue
            for node in model.get_nodes():
                for pin in walk_pins(node.get_pins()):
                    try:
                        cpp_type = str(pin.get_cpp_type())
                        default_value = str(pin.get_default_value())
                        pin_path = str(pin.get_pin_path())
                    except Exception:
                        continue
                    if "RigElementKey" not in cpp_type and "CachedRigElement" not in cpp_type:
                        continue
                    match = BONE_RE.search(default_value)
                    if not match:
                        continue
                    old_name = match.group(1)
                    new_name = translate_bone(old_name, target_bones)
                    if new_name is None:
                        failed.append({"model": str(model.get_name()), "node": str(node.get_name()),
                                       "bone": old_name})
                        continue
                    if new_name == old_name:
                        continue
                    new_value = default_value.replace('Name="%s"' % old_name,
                                                      'Name="%s"' % new_name)
                    try:
                        controller.set_pin_default_value(pin_path, new_value)
                        changed[old_name] = changed.get(old_name, 0) + 1
                    except Exception as error:
                        failed.append({"model": str(model.get_name()), "node": str(node.get_name()),
                                       "bone": old_name, "error": str(error)[:100]})
        return rig, target_bones, changed, failed

    # 9b 演奏者：换骨骼名
    rig, bones, changed, failed = patch_rig(TARGET_PERFORMER_RIG)
    report["performer"] = {"changed_pins": sum(changed.values()),
                           "changed_bones": sorted(changed.keys()),
                           "failed": failed[:10], "failed_count": len(failed)}

    # 10b 鼓组：换通道清单（源乐手的 *_beat 控件名在目标 rig 上不存在）
    kit_rig = library.load_asset(TARGET_KIT_RIG)
    controls = [str(key.name) for key in kit_rig.get_hierarchy().get_all_keys()
                if key.type == unreal.RigElementType.CONTROL]
    beat_channels = [name for name in controls if name.endswith("_beat")]
    value = "(" + ",".join('(Type=Control,Name="%s")' % name for name in beat_channels) + ")"
    kit_controller = kit_rig.get_controller()
    channels_fixed = 0
    for node in kit_rig.get_default_model().get_nodes():
        if str(node.get_node_title()) != "常量 RigElementKey":
            continue
        for pin in node.get_pins():
            try:
                if str(pin.get_name()) != "Value":
                    continue
                kit_controller.set_pin_default_value(str(pin.get_pin_path()), value)
                channels_fixed += 1
            except Exception as error:
                report["kit_channel_error"] = str(error)[:200]
    report["kit"] = {"beat_channels": beat_channels, "channels_fixed": channels_fixed}

    # 编译 + 保存
    report["performer_compiled"] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(rig))
    report["kit_compiled"] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(kit_rig))
    report["performer_saved"] = bool(library.save_asset(TARGET_PERFORMER_RIG))
    report["kit_saved"] = bool(library.save_asset(TARGET_KIT_RIG))

    # 复核：还有没有指向不存在骨头的引用
    leftovers = {}
    for model in rig.get_all_models():
        for node in model.get_nodes():
            for pin in walk_pins(node.get_pins()):
                try:
                    default_value = str(pin.get_default_value())
                except Exception:
                    continue
                for bone_name in BONE_RE.findall(default_value):
                    if bone_name not in bones and bone_name != "None":
                        leftovers[bone_name] = leftovers.get(bone_name, 0) + 1
    report["leftover_bone_refs"] = leftovers
    report["ok"] = not leftovers and channels_fixed > 0

else:
    report["ok"] = False
    report["error"] = "MODE 只能是 import 或 patch"

result = report
