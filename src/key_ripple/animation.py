# key_ripple/animation.py
"""KeyRipple 乐器模块 —— 动画生成（迁移自 key_ripple_blender/make_animation/make_animation.py）

通用动画工具（fcurve/shape key/driver/clear）改调 common.animation_utils。

钢琴键动画：
- 键物体已合并成「目标乐器」一个物体，全部 shape key 都在它上面，
  名字是 `key_<编号>_pressed`（不带演奏者后缀，与 Unreal 的 Morph Target 一致）；
- 写入前先整体清理目标乐器（所有 `key_*_pressed` 归零 + 清掉 shape key 动画 +
  清掉全部材质 Mix Shader Factor 的旧曲线），所以重复生成是覆盖而不是叠加；
- 目标物体只认面板的「目标乐器」，找不到就返回失败、由 UI 报错；
- 旧的 `is_pressed` 自定义属性已废弃（Factor 就是琴键发光），不再写入。
"""

import json
import os
import re

import bpy  # type: ignore

from ..common import animation_utils
from ..common import performer_utils


def clear_all_keyframe(collection_names=None, exclude_names=None, suffix=""):
    """清除关键帧（集合名自动按演奏者后缀解析）"""
    animation_utils.clear_all_keyframe(collection_names, exclude_names, suffix)


def clear_all_keyframe_preserve_drivers(collection_names=None, exclude_names=None,
                                        suffix=""):
    """清除关键帧但保留驱动器（备份 → 清空 → 恢复）"""
    animation_utils.clear_all_keyframe_preserve_drivers(
        collection_names, exclude_names, suffix)


def _driver_protected_object_names(suffix: str) -> list:
    """列出清关键帧时必须跳过的物体名（它们的动画是 driver，不是关键帧）。

    - 各手指 ext 辅助控件 `ext_<手指>_<手>`：位置 = 2 × 手指，由 driver 驱动；
    - `Mid_Hand`：位置 = H_L / H_R 的中点，由 driver 驱动；
    - 兜底：addons 目录里任何当前挂着 driver 的物体。

    这些物体被 `animation_data_clear()` 扫到就会丢掉 driver（ext 不再跟随手指、
    Mid_Hand 不再取中点），所以清理前先把名字准备好、交给 exclude_names 挡掉。
    """
    addons = performer_utils.find_addons_collection(suffix)
    if addons is None:
        return []

    collected_names = []
    animation_utils.collect_collection_objects(addons, [], collected_names)

    mid_hand_name = performer_utils.resolve("Mid_Hand", suffix)
    protected_names = []
    for object_name in collected_names:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            continue
        if object_name.startswith("ext_") or object_name == mid_hand_name:
            protected_names.append(object_name)
            continue
        if obj.animation_data and obj.animation_data.drivers:
            protected_names.append(object_name)
    return protected_names


def get_or_create_fcurve(datablock, data_path, index=0):
    """在 datablock 的动画 action 中查找或创建一条 fcurve（Blender 4.x/5.x 兼容）"""
    return animation_utils.get_or_create_fcurve(datablock, data_path, index)


def write_fcurve_points(fcurve, keyframes, clear_existing=True):
    """批量写入 fcurve 的关键帧点"""
    animation_utils.write_fcurve_points(fcurve, keyframes, clear_existing)


def make_animation(animation_file_path: str, suffix: str = ""):
    """根据动画数据批量写入物体 transform 关键帧（位置 + 四元数旋转）。

    suffix: 演奏者后缀；JSON 里的短名会自动解析成 <短名>_<后缀>
    """
    try:
        with open(animation_file_path, 'r') as f:
            animation_data = json.load(f)
    except Exception as e:
        print(f"无法读取动画文件: {e}")
        return

    # 第一步：按物体收集每一帧的数据（保持帧序），并做四元数符号一致性处理
    object_data = {}
    previous_quaternions = {}

    for frame_data in animation_data:
        frame = int(frame_data.get("frame", 0))
        if frame < 0:
            continue
        hand_infos = frame_data.get("hand_infos", {})

        for short_name, transform_data in hand_infos.items():
            obj_name = performer_utils.resolve(short_name, suffix)
            if obj_name not in bpy.data.objects:
                print(f"警告: 物体 {obj_name} 不存在于场景中")
                continue

            data_len = len(transform_data)
            entry = object_data.setdefault(obj_name, {"frames": []})

            if data_len == 7:
                # 合并格式 [x, y, z, w, i, j, k] → 位置 + 四元数旋转
                entry.setdefault("locations", []).append(transform_data[:3])
                quat = list(transform_data[3:])

                if obj_name in previous_quaternions:
                    dot = sum(
                        a * b for a, b in zip(previous_quaternions[obj_name], quat))
                    if dot < 0:
                        quat = [-x for x in quat]
                previous_quaternions[obj_name] = quat

                entry.setdefault("quats", []).append(quat)
                entry["frames"].append(frame)

            elif data_len == 4:
                # 旧格式兼容：纯四元数旋转 (w, x, y, z)
                quat = list(transform_data)

                if obj_name in previous_quaternions:
                    dot = sum(
                        a * b for a, b in zip(previous_quaternions[obj_name], quat))
                    if dot < 0:
                        quat = [-x for x in quat]
                previous_quaternions[obj_name] = quat

                entry.setdefault("quats", []).append(quat)
                entry["frames"].append(frame)

            elif data_len == 3:
                # 位置数据 [x, y, z]
                entry.setdefault("locations", []).append(transform_data[:3])
                entry["frames"].append(frame)

            else:
                print(f"警告: 物体 {obj_name} 的数据维度 {data_len} 无法识别")
                continue

    # 第二步：为每个物体准备 fcurve
    for obj_name, entry in object_data.items():
        obj = bpy.data.objects[obj_name]

        if not obj.animation_data:
            obj.animation_data_create()
        if not obj.animation_data.action:
            obj.animation_data.action = bpy.data.actions.new(
                f"{obj_name}_anim")

        if "locations" in entry:
            entry["location_fcurves"] = [
                get_or_create_fcurve(obj, "location", index=i)
                for i in range(3)]
        if "quats" in entry:
            obj.rotation_mode = 'QUATERNION'
            entry["quat_fcurves"] = [
                get_or_create_fcurve(obj, "rotation_quaternion", index=i)
                for i in range(4)]

    # 第三步：批量写入所有物体的关键帧
    for obj_name, entry in object_data.items():
        frames = entry["frames"]

        if "location_fcurves" in entry:
            for i, fcurve in enumerate(entry["location_fcurves"]):
                values = [loc[i] for loc in entry["locations"]]
                write_fcurve_points(fcurve, zip(frames, values))

        if "quat_fcurves" in entry:
            for i, fcurve in enumerate(entry["quat_fcurves"]):
                values = [quat[i] for quat in entry["quats"]]
                write_fcurve_points(fcurve, zip(frames, values))

    print(f"动画已成功从 {animation_file_path} 生成")


def extract_key_index(shape_key_name):
    """从shape key名称中提取键索引，例如: "key_21_pressed" -> "21" """
    numbers = re.findall(r'\d+', shape_key_name)
    if not numbers:
        return None
    return numbers[0]


def _last_number(text):
    """取字符串里最后一组数字（没有则返回 None）"""
    numbers = re.findall(r'\d+', text)
    return numbers[-1] if numbers else None


def _material_key_number(material_name):
    """从材质名里取键号（先剥掉演奏者后缀与 Blender 的 .001 副本后缀）。

    材质名沿用 `<键短名>_<演奏者后缀>` 约定（如 key_51_Jd），复制演奏者时 Blender
    还会追加 `.001`；这两种后缀都带数字，不剥掉就会取错键号、写错发光材质。
    """
    performer = performer_utils.performer_from_object(material_name)
    if performer is not None:
        return _last_number(performer[1])
    return _last_number(performer_utils.strip_duplicate_suffix(material_name))


def build_material_index_map(obj):
    """一次性建立 键索引 -> 材质 的映射，供批量生成动画时使用"""
    material_by_index = {}
    candidates = [slot.material for slot in obj.material_slots]
    candidates.extend(bpy.data.materials)

    for material in candidates:
        if not material:
            continue
        key_number = _material_key_number(material.name)
        if key_number is not None and key_number not in material_by_index:
            material_by_index[key_number] = material
    return material_by_index


def _iter_materials(obj):
    """目标乐器材质槽上的材质（去重，忽略空槽）"""
    seen_names = set()
    for slot in obj.material_slots:
        material = slot.material
        if material is None or material.name in seen_names:
            continue
        seen_names.add(material.name)
        yield material


def _iter_action_fcurves(action):
    """遍历 action 上的所有 fcurve（4.x 用 action.fcurves；5.x 走「层/条/通道包」）"""
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        return list(fcurves)
    collected = []
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for channelbag in getattr(strip, "channelbags", []):
                collected.extend(channelbag.fcurves)
    return collected


def _find_factor_target(material):
    """定位材质里 Mix Shader 节点的 Factor 参数，返回 (节点树, 因子节点, 数据路径)。

    优先沿已有 driver 的 data_path 找回原来的节点（场景里有多个 Mix Shader 时不会
    认错），找不到再退化为「第一个带 Factor 输入的 Mix Shader 节点」。
    """
    if not material or not material.node_tree:
        return None

    node_tree = material.node_tree

    factor_node = None
    if node_tree.animation_data and node_tree.animation_data.drivers:
        for driver in node_tree.animation_data.drivers:
            match = re.match(
                r'nodes\["(.+)"\]\.inputs\[(?:".+"|\d+)\]\.default_value$',
                driver.data_path)
            if not match:
                continue
            node = node_tree.nodes.get(match.group(1))
            if node is not None and "Factor" in node.inputs:
                factor_node = node
                break

    if factor_node is None:
        for node in node_tree.nodes:
            if node.type == 'MIX_SHADER' and "Factor" in node.inputs:
                factor_node = node
                break

    if factor_node is None:
        return None

    factor_index = list(factor_node.inputs).index(
        factor_node.inputs["Factor"])
    data_path = f'nodes["{factor_node.name}"].inputs[{factor_index}].default_value'
    return node_tree, factor_node, data_path


def _factor_data_paths(factor_node, data_path):
    """Factor 的两条等价数据路径：按输入名 / 按输入下标（旧版两种写法都出现过）"""
    name_data_path = f'nodes["{factor_node.name}"].inputs["Factor"].default_value'
    return (name_data_path, data_path)


def _clear_factor_animation(material):
    """清掉材质 Mix Shader Factor 上的残留 driver 与全部关键帧。

    Factor 就是琴键按下的发光（旧版 `is_pressed` 的替代），生成动画前必须整体清空，
    否则本次曲子没弹到的键会留着上一次的发光曲线。只动 Factor 这一条，不碰材质里
    其它节点的动画；没有 Factor 的材质静默跳过（清理阶段会遍历该乐器全部材质）。
    """
    located = _find_factor_target(material)
    if located is None:
        return
    node_tree, factor_node, data_path = located
    factor_paths = _factor_data_paths(factor_node, data_path)

    if node_tree.animation_data and node_tree.animation_data.drivers:
        for driver in list(node_tree.animation_data.drivers):
            if driver.data_path in factor_paths:
                node_tree.animation_data.drivers.remove(driver)

    if not node_tree.animation_data or not node_tree.animation_data.action:
        return
    for fcurve in _iter_action_fcurves(node_tree.animation_data.action):
        if fcurve.data_path in factor_paths:
            fcurve.keyframe_points.clear()


def _prepare_factor_fcurve(material):
    """定位材质中 Mix Shader 节点的 Factor 参数，清理其上遗留的 driver 与旧关键帧，并返回 fcurve"""
    if not material or not material.node_tree:
        print(
            f"警告: 材质 {material.name if material else 'None'} 没有节点树，无法设置 Factor")
        return None

    located = _find_factor_target(material)
    if located is None:
        print(f"警告: 材质 {material.name} 上未找到 Mix Shader 节点的 Factor 参数")
        return None
    node_tree, _factor_node, data_path = located

    _clear_factor_animation(material)

    if not node_tree.animation_data:
        node_tree.animation_data_create()
    if not node_tree.animation_data.action:
        node_tree.animation_data.action = bpy.data.actions.new(
            f"{material.name}_factor")

    fcurve = get_or_create_fcurve(node_tree, data_path, index=0)
    if fcurve is None:
        print(f"警告: 材质 {material.name} 上无法获取 Factor 的 fcurve")
        return None

    fcurve.keyframe_points.clear()

    return fcurve


# 钢琴键 shape key 名：key_<编号>_pressed（不带演奏者后缀，与 Unreal Morph Target 一致）
# 不锚定结尾：合并键物体时 Blender 可能给重名 shape key 追加 .001/.002
_PIANO_KEY_SHAPE_KEY_PATTERN = re.compile(r"^key_.+_pressed")


def _is_piano_key_shape_key(shape_key_name: str) -> bool:
    """是否是钢琴键的 pressed shape key"""
    return bool(_PIANO_KEY_SHAPE_KEY_PATTERN.match(shape_key_name))


def clear_piano_key_animation(obj) -> None:
    """清空目标乐器上的钢琴键动画（写入前调用，让重复生成是覆盖而不是叠加）。

    - 全部 `key_<编号>_pressed` shape key 归零，并清掉整条 shape key 动画：
      本次曲子没弹到的键不会残留上一次的动画；
    - 该乐器所有材质 Mix Shader Factor 的旧关键帧与残留 driver 一并清掉
      （Factor 就是琴键发光，等价于旧版 `is_pressed` 的作用）；
    - 其它 shape key（如 Basis）与材质里其它节点的动画不受影响。
    """
    if obj is None:
        return
    shape_keys = getattr(obj.data, "shape_keys", None)
    if not shape_keys:
        return

    for shape_key_block in shape_keys.key_blocks:
        if _is_piano_key_shape_key(shape_key_block.name):
            shape_key_block.value = 0.0
    if shape_keys.animation_data:
        shape_keys.animation_data_clear()

    for material in _iter_materials(obj):
        _clear_factor_animation(material)


def generate_piano_key_animation(piano_key_animation_path: str,
                                 keyboard_obj_name: str = 'keyboard') -> bool:
    """根据预先计算好的钢琴键动画数据在Blender中执行插帧操作（成功返回 True）。

    钢琴键已合并成「目标乐器」一个物体，全部 `key_<编号>_pressed` shape key 都在
    它上面；写入前先整体清理，然后再按 shape key 名逐条插帧。
    """
    try:
        with open(piano_key_animation_path, 'r') as f:
            piano_key_animation_data = json.load(f)
    except Exception as e:
        print(f"无法读取钢琴键动画数据文件: {e}")
        return False

    obj = bpy.data.objects.get(keyboard_obj_name)
    if obj is None:
        print(f"错误: 场景中找不到目标乐器 {keyboard_obj_name}（请检查面板的「目标乐器」）")
        return False

    if obj.type != 'MESH' or not obj.data.shape_keys:
        print(f"错误: 目标乐器 {keyboard_obj_name} 不是带 shape key 的网格，无法写入钢琴键动画")
        return False

    # 多演奏者：确保目标乐器的 mesh / 材质 / Action 是本演奏者独占的
    # （旧场景里复制出来的演奏者会共享这些数据，写动画会互相覆盖）
    if performer_utils.make_object_data_independent(obj):
        print(f"  • 目标乐器 {obj.name} 的 mesh/材质与其它演奏者共享，已复制为独立数据")

    shape_keys = obj.data.shape_keys
    key_blocks = shape_keys.key_blocks

    # 一个键都对不上时直接报错返回，避免白清一遍现有动画
    if not any(key_blocks.get(key_data["shape_key_name"]) is not None
               for key_data in piano_key_animation_data):
        print(f"错误: 目标乐器 {keyboard_obj_name} 上没有任何与 "
              f"{piano_key_animation_path} 对应的 shape key，请先创建合并后的钢琴 shape keys")
        return False

    # 写入前整体清理（清掉上一次的琴键动画与全部材质发光动画）
    clear_piano_key_animation(obj)

    material_by_index = build_material_index_map(obj)

    if not shape_keys.animation_data:
        shape_keys.animation_data_create()
    if not shape_keys.animation_data.action:
        shape_keys.animation_data.action = bpy.data.actions.new(
            f"{keyboard_obj_name}_shape_keys")

    key_infos = []
    missing_key_count = 0
    for key_data in piano_key_animation_data:
        shape_key_name = key_data["shape_key_name"]
        keyframes = key_data["keyframes"]

        shape_key = key_blocks.get(shape_key_name)
        if shape_key is None:
            print(f"警告: 未找到shape key {shape_key_name}")
            missing_key_count += 1
            continue

        shape_fcurve = get_or_create_fcurve(
            shape_keys, f'key_blocks["{shape_key_name}"].value')

        factor_fcurve = None
        key_index = extract_key_index(shape_key_name)
        if key_index is not None:
            material = material_by_index.get(key_index)
            if material is not None:
                factor_fcurve = _prepare_factor_fcurve(material)
            else:
                print(f"警告: 未找到与 shape key {shape_key_name} 对应的材质，无法驱动发光")
        else:
            print(f"警告: 无法从 shape key {shape_key_name} 中提取键索引，无法驱动发光")

        key_infos.append({
            "shape_key_fcurve": shape_fcurve,
            "factor_fcurve": factor_fcurve,
            "keyframes": keyframes,
        })

    for info in key_infos:
        frames = [float(kf["frame"]) for kf in info["keyframes"]]
        shape_values = [float(kf["shape_key_value"])
                        for kf in info["keyframes"]]

        write_fcurve_points(
            info["shape_key_fcurve"], zip(frames, shape_values))

        if info["factor_fcurve"] is not None:
            write_fcurve_points(
                info["factor_fcurve"], zip(frames, shape_values))

    if not key_infos:
        print(f"错误: {piano_key_animation_path} 里没有任何可写入的钢琴键")
        return False

    print(f"钢琴键动画已成功从 {piano_key_animation_path} 生成"
          f"（{len(key_infos)} 个键，缺失 {missing_key_count} 个）")
    return True


def make_animation_from_keyripple(keyripple_file_path: str,
                                  keyboard_obj_name: str = 'keyboard',
                                  suffix: str = "") -> bool:
    """从.keyripple文件生成动画（成功返回 True）"""
    try:
        with open(keyripple_file_path, 'r') as f:
            keyripple_data = json.load(f)
    except Exception as e:
        print(f"无法读取.keyripple文件: {e}")
        return False

    animation_file_path = keyripple_data.get("animation_path")
    piano_key_animation_path = keyripple_data.get("key_animation_path")

    if not animation_file_path or not piano_key_animation_path:
        print("错误: .keyripple文件中缺少必要的路径信息")
        return False

    if not os.path.exists(animation_file_path):
        print(f"错误: 动画文件不存在: {animation_file_path}")
        return False

    if not os.path.exists(piano_key_animation_path):
        print(f"错误: 钢琴键动画文件不存在: {piano_key_animation_path}")
        return False

    # 清除现有动画：
    # - 手指/手掌控制器等上一次的关键帧要清掉（它们在 addons_<后缀> 里）；
    # - ext 辅助控件与 Mid_Hand 的动画是 driver，先把它们的名字准备好挡掉，
    #   并整体改用「保留 driver」的清理，避免误伤 addons 里其它带 driver 的物体；
    # - 钢琴键（目标乐器）上的动画由 generate_piano_key_animation 自己整体清理，
    #   旧版列的 "keys" 集合在新结构里已不存在（键物体已合并进目标乐器）。
    protected_names = _driver_protected_object_names(suffix)
    if protected_names:
        print(f"  • 清理关键帧时保留 driver 的物体：{', '.join(protected_names)}")
    clear_all_keyframe_preserve_drivers(
        ["addons"], exclude_names=protected_names, suffix=suffix)

    # 生成手部动画
    make_animation(animation_file_path, suffix=suffix)

    # 生成钢琴键动画
    if not generate_piano_key_animation(piano_key_animation_path, keyboard_obj_name):
        print(f"钢琴键动画生成失败（目标乐器 {keyboard_obj_name}）")
        return False

    print(f"动画已成功从 {keyripple_file_path} 生成")
    return True
