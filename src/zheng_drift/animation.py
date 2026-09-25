# zheng_drift/animation.py
"""ZhengDrift 乐器模块 —— 动画生成（迁移自 zheng_blender_addon/tools/animation_generator.py）

- 通用 fcurve 工具改调 common.animation_utils；
- 控制器/Head_Control 对象名按演奏者后缀解析；
- 弦振动 shape key 全部在「目标乐器」这一个物体上（生成时每根弦是独立物体，
  用户手动合并成目标乐器），命名 `string{N}_press` / `string{N}_vib`；
- 清除关键帧时**保留** Middle_Hand / ext 上的 driver（与源码一致）。
"""

import json

import bpy  # type: ignore

from ..common import animation_utils
from ..common import performer_utils

get_or_create_fcurve = animation_utils.get_or_create_fcurve
write_fcurve_points = animation_utils.write_fcurve_points


def _clear_object_animation(obj) -> None:
    """清除物体的所有动画数据（约束器/驱动不属于 animation_data 的会保留，
    但这里与源码语义一致：整段 animation_data_clear）"""
    if obj.animation_data:
        obj.animation_data_clear()


# ── 左右手动画 ───────────────────────────────────────────────

def _generate_hand_animation_from_file(animation_file_path: str, side: str,
                                       suffix: str = "") -> None:
    """根据手部动画文件批量写入控制器 transform 关键帧"""
    suffix_letter = 'L' if side == 'left' else 'R'
    side_label = '左手' if side == 'left' else '右手'

    print(f"\n=== 生成{side_label}动画 ===")

    hand_controllers = [
        f"H_{suffix_letter}",      # 手掌控制器
        f"HP_{suffix_letter}",     # 手掌轴点控制器
        f"T_{suffix_letter}",      # 拇指控制器
        f"I_{suffix_letter}",      # 食指控制器
        f"M_{suffix_letter}",      # 中指控制器
        f"R_{suffix_letter}",      # 无名指控制器
        f"P_{suffix_letter}",      # 小指控制器
        f"TP_{suffix_letter}",
        f"I_{suffix_letter}_pole",
        f"M_{suffix_letter}_pole",
        f"R_{suffix_letter}_pole",
        f"P_{suffix_letter}_pole",
    ]

    # 清除所有控制器的动画数据
    for controller_name in hand_controllers:
        full = performer_utils.resolve(controller_name, suffix)
        obj = bpy.data.objects.get(full)
        if obj is not None:
            _clear_object_animation(obj)

    # 读取动画文件
    with open(animation_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 新格式包含 left_hand / right_hand 两个字段；旧格式直接是数组
    if isinstance(data, dict) and f'{side}_hand' in data:
        keyframes = data[f'{side}_hand']
    else:
        keyframes = data

    # 第一步：按控制器收集每一帧的数据（保持帧序），并做四元数符号一致性处理。
    #
    # Rust 端输出的 performance JSON 每帧结构：
    #   {"frame": ..., "hand_infos": {"H_L": [x,y,z, w,i,j,k], "HP_L": [x,y,z],
    #    "T_L": [x,y,z], "I_L": [x,y,z], ...}, "state": ...}
    # hand_infos 的键就是控件短名（带左右手字母）；H_{L/R} 为 7 元素 =
    # 位置(前 3) + 旋转四元数(后 4)，其余控件为 3 元素位置。
    object_data = {}
    previous_quaternions = {}

    def _collect(obj_name, position, rotation):
        if obj_name not in bpy.data.objects:
            return
        entry = object_data.setdefault(obj_name, {})
        if position is not None and len(position) == 3:
            entry.setdefault("loc_frames", []).append(frame)
            entry.setdefault("locations", []).append(position[:3])
        if rotation is not None and len(rotation) == 4:
            quat = list(rotation)
            if obj_name in previous_quaternions:
                dot = sum(a * b for a, b in zip(
                    previous_quaternions[obj_name], quat))
                if dot < 0:
                    quat = [-x for x in quat]
            previous_quaternions[obj_name] = quat
            entry.setdefault("quat_frames", []).append(frame)
            entry.setdefault("quats", []).append(quat)

    for kf in keyframes:
        frame = int(kf['frame'])
        infos = kf.get('hand_infos')
        if not infos:
            continue

        # hand_infos 键即控件短名（H_L / HP_L / T_L / I_L ...）；
        # 值数组 3=位置；H_{L/R} 为 7 元素 [x,y,z, w,i,j,k] = 位置 + 旋转四元数。
        for short, values in infos.items():
            full = performer_utils.resolve(short, suffix)
            if len(values) == 7:
                # H_{L/R}：同时写位置（前 3）与旋转四元数（后 4）
                _collect(full, values[:3], values[3:7])
            else:
                _collect(full, values, None)

    # 第二步：为每个控制器准备 fcurve（位置 3 通道 / 四元数 4 通道）
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

    # 第三步：批量写入所有控制器的关键帧
    for obj_name, entry in object_data.items():
        if "location_fcurves" in entry:
            frames = entry["loc_frames"]
            for i, fcurve in enumerate(entry["location_fcurves"]):
                values = [loc[i] for loc in entry["locations"]]
                write_fcurve_points(fcurve, zip(frames, values))
        if "quat_fcurves" in entry:
            frames = entry["quat_frames"]
            for i, fcurve in enumerate(entry["quat_fcurves"]):
                values = [quat[i] for quat in entry["quats"]]
                write_fcurve_points(fcurve, zip(frames, values))

    print(f"  ✓ {side_label}动画生成完成，共 {len(keyframes)} 个关键帧")


def generate_left_hand_animation(animation_file_path: str, suffix: str = "") -> None:
    """生成左手动画"""
    _generate_hand_animation_from_file(animation_file_path, 'left', suffix)


def generate_right_hand_animation(animation_file_path: str, suffix: str = "") -> None:
    """生成右手动画"""
    _generate_hand_animation_from_file(animation_file_path, 'right', suffix)


# ── 弦振动动画 ───────────────────────────────────────────────

# 弦 shape key 命名：string{N}_press / string{N}_vib（N = 0-20，共 42 个），
# 与 Unreal 端 Morph Target 通道名一致。生成弦时每根弦是独立物体
# （string{i}_L / string{i}_R），用户随后手动把全部弦合并成一个物体，
# 即「目标乐器」；合并后 shape key 名不变，所以插帧时只需在该物体上按名查找。
def _string_shape_key_name(string_index: int, shape_key_type: str) -> str:
    """弦 shape key 名：'Vib' → string{N}_vib，'Press' → string{N}_press"""
    type_word = "vib" if shape_key_type == "Vib" else "press"
    return f"string{string_index}_{type_word}"


def _get_target_instrument(suffix: str = "", instrument=None):
    """目标乐器物体：优先显式传入，其次当前演奏者登记的乐器"""
    if instrument is not None:
        return instrument
    if not suffix:
        return None
    performer = performer_utils.get_performer(suffix)
    return performer.target_instrument if performer is not None else None


def generate_string_vibration_animation(animation_file_path: str,
                                        suffix: str = "",
                                        instrument=None) -> None:
    """生成弦振动动画（在「目标乐器」的 shape key 上批量插帧）

    Rust 端输出的事件为 `{string_index, frame, value, shape_key_type}`，
    shape_key_type 为 "Press"（左手按弦）或 "Vib"（右手摇指）；两类 shape key
    都在同一个物体（目标乐器，即合并后的弦）上，直接查找并插帧。
    """
    print("\n=== 生成弦振动动画 ===")

    obj = _get_target_instrument(suffix, instrument)
    if obj is None:
        print("  ⚠ 未找到目标乐器物体，请先指定目标乐器")
        return
    if obj.type != 'MESH' or not obj.data.shape_keys:
        print(f"  ⚠ 目标乐器 {obj.name} 没有 shape key")
        return

    shape_keys = obj.data.shape_keys
    key_blocks = shape_keys.key_blocks

    _clear_string_shape_key_animation(suffix, obj)

    with open(animation_file_path, 'r', encoding='utf-8') as f:
        events = json.load(f)

    # 按 shape key 收集每一帧的数据（保持帧序）
    shape_data = {}
    missing_keys = set()

    for event in events:
        shape_key_name = _string_shape_key_name(
            int(event['string_index']), event['shape_key_type'])
        if key_blocks.get(shape_key_name) is None:
            missing_keys.add(shape_key_name)
            continue

        entry = shape_data.setdefault(
            shape_key_name, {"frames": [], "values": []})
        entry["frames"].append(int(event['frame']))
        entry["values"].append(event['value'])

    if missing_keys:
        print(f"  ⚠ 目标乐器 {obj.name} 上缺少 Shape Key："
              f"{', '.join(sorted(missing_keys))}")
        existing_names = [key_block.name for key_block in key_blocks
                          if key_block.name != 'Basis']
        print(f"    该物体现有 Shape Key：{', '.join(existing_names[:10])}"
              f"{' ...' if len(existing_names) > 10 else ''}")

    if not shape_data:
        print("  ⚠ 没有可写入的弦 Shape Key")
        return

    if not shape_keys.animation_data:
        shape_keys.animation_data_create()
    if not shape_keys.animation_data.action:
        shape_keys.animation_data.action = bpy.data.actions.new(
            f"{obj.name}_string_shape_keys")

    # 批量写入所有 shape key 的关键帧
    for shape_key_name, entry in shape_data.items():
        shape_fcurve = get_or_create_fcurve(
            shape_keys, f'key_blocks["{shape_key_name}"].value')
        write_fcurve_points(
            shape_fcurve, zip(entry["frames"], entry["values"]))

    print(f"  ✓ 弦振动动画生成完成，共 {len(events)} 个事件，"
          f"{len(shape_data)} 个 Shape Key")


def _clear_string_shape_key_animation(suffix: str = "",
                                      instrument=None) -> None:
    """清除目标乐器上弦的 Shape Key 动画（保留 Shape Key 本身）

    只清弦 shape key 的值与整个 shape key 动画，**不动**乐器物体自身的
    变换动画（乐器整体动画不属于弦动画范围）。
    """
    print("  → 清除现有弦动画...")

    obj = _get_target_instrument(suffix, instrument)
    if obj is None or obj.type != 'MESH' or not obj.data.shape_keys:
        return

    shape_keys = obj.data.shape_keys
    for string_index in range(21):
        for shape_key_type in ("Press", "Vib"):
            shape_key_block = shape_keys.key_blocks.get(
                _string_shape_key_name(string_index, shape_key_type))
            if shape_key_block is not None:
                shape_key_block.value = 0.0

    if shape_keys.animation_data:
        shape_keys.animation_data_clear()


# ── 清除关键帧 ───────────────────────────────────────────────

def clear_all_keyframes(suffix: str = "", instrument=None) -> None:
    """清除关键帧（保留 Middle_Hand / ext 的 driver，与源码一致）"""
    print("\n=== 清除关键帧 ===")

    all_controllers = [
        # 左手
        "H_L", "HP_L", "T_L", "I_L", "M_L", "R_L", "P_L",
        "TP_L", "I_L_pole", "M_L_pole", "R_L_pole", "P_L_pole",
        # 右手
        "H_R", "HP_R", "T_R", "I_R", "M_R", "R_R", "P_R",
        "TP_R", "I_R_pole", "M_R_pole", "R_R_pole", "P_R_pole",
        # Target
        "Head_Control",
    ]

    for controller_name in all_controllers:
        full = performer_utils.resolve(controller_name, suffix)
        obj = bpy.data.objects.get(full)
        if obj is not None:
            _clear_object_animation(obj)

    # 清除目标乐器上弦的 Shape Key 动画
    _clear_string_shape_key_animation(suffix, instrument)

    print("  ✓ 已清除所有控制器和弦的关键帧")


# ── Target 动画 ──────────────────────────────────────────────

def generate_target_animation(animation_file_path: str,
                              suffix: str = "") -> None:
    """从目标动画文件生成 Head_Control 关键帧动画（批量写）"""
    print("\n=== 生成 Head_Control 动画 ===")

    obj = bpy.data.objects.get(performer_utils.resolve('Head_Control', suffix))
    if obj is None:
        print("  ⚠ 场景中未找到 Head_Control 物体")
        return

    _clear_object_animation(obj)

    with open(animation_file_path, 'r', encoding='utf-8') as f:
        keyframes = json.load(f)

    frames = []
    locations = []
    for kf in keyframes:
        frame = int(kf['frame'])
        if kf.get('head_control_position'):
            frames.append(frame)
            locations.append(kf['head_control_position'][:3])

    if not frames:
        print("  ⚠ Head_Control 动画数据为空")
        return

    if not obj.animation_data:
        obj.animation_data_create()
    if not obj.animation_data.action:
        obj.animation_data.action = bpy.data.actions.new(f"{obj.name}_anim")

    location_fcurves = [
        get_or_create_fcurve(obj, "location", index=i) for i in range(3)]
    for i, fcurve in enumerate(location_fcurves):
        values = [loc[i] for loc in locations]
        write_fcurve_points(fcurve, zip(frames, values))

    print(f"  ✓ Head_Control 动画生成完成，共 {len(keyframes)} 个关键帧")
