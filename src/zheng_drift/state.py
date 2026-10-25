# zheng_drift/state.py
"""ZhengDrift 乐器模块 —— 状态传输

左右手状态统一存**演奏者骨骼自定义属性**（zheng_drift_state_data），
映射辅助的四个采集点（手部中点 + 头部位置 + 左右手各自的位置与旋转）存 **zheng_drift_bilinear_data**，
与 key_ripple / fret_dance 一致；不再在场景里生成大量记录器/辅助球体物体。
复用 common.state_io 的对象↔字典搬运工具（含约束器影响的真实变换）。

骨骼自定义属性结构（JSON）：数据键一律用**短名**（无演奏者后缀），
场景控件才用带后缀的完整名查找，保证不同演奏者的骨骼数据结构一致。
{
  "left_hand":  { "<action>": { "<position>": { "<短控制器名>": {"location": [...], "rotation": [...]} } } },
  "right_hand": { "<action>": { "<position>": { ... } } }
}
action：左手 Normal/Press；右手 Normal/Tremolo；position：far/middle/near
"""

import bpy  # type: ignore

from ..common import state_io as _sio

# 骨骼自定义属性键
STATE_KEY = "zheng_drift_state_data"
# 映射辅助四个采集点的骨骼自定义属性键（手部中点 / 头部位置 / 左手 / 右手）
BILINEAR_KEY = "zheng_drift_bilinear_data"


def _get_state(skeleton) -> dict:
    return _sio.get_state_data(skeleton, STATE_KEY, {}) or {}


def _set_state(skeleton, data: dict) -> None:
    _sio.set_state_data(skeleton, STATE_KEY, data)


# ── 双线性辅助数据（存骨骼，键 = 完整短名，如 "Middle_Hand_A"） ──


def get_bilinear_data(skeleton) -> dict:
    """读取双线性辅助数据（键 = 完整短名，如 "Middle_Hand_A"）"""
    return _sio.get_state_data(skeleton, BILINEAR_KEY, {}) or {}


def set_bilinear_data(skeleton, data: dict) -> None:
    """写回双线性辅助数据到骨骼自定义属性"""
    _sio.set_state_data(skeleton, BILINEAR_KEY, data)


def migrate_legacy_bilinear_objects(config, skeleton) -> int:
    """把旧版双线性辅助空物体的位置迁移进骨骼自定义属性（幂等）。

    只在骨骼属性里还没有对应键的数据时写入；返回迁移条目数。
    """
    if skeleton is None:
        return 0
    data = get_bilinear_data(skeleton)
    migrated = 0
    changed = False
    for helper_name in config.bilinear_helpers.values():
        if helper_name in data:
            continue
        obj = bpy.data.objects.get(config.obj_name(helper_name))
        if obj is None or obj.type != 'EMPTY':
            continue
        data[helper_name] = {"location": list(obj.location)}
        migrated += 1
        changed = True
    if changed:
        set_bilinear_data(skeleton, data)
    return migrated


def _hand_key(hand: str) -> str:
    return "left_hand" if hand == "left" else "right_hand"


def _hand_controller_shorts(config, hand: str) -> list[str]:
    """返回指定手的控制器短名列表（数据键，无演奏者后缀；排除手指极向量）"""
    controllers = (config.left_hand_controllers if hand == "left"
                   else config.right_hand_controllers)
    names = []
    for key, short in controllers.items():
        if key.endswith("_pole") and "_ik_pivot" not in key:
            continue
        names.append(short)
    return names


# ── 保存 / 加载 ───────────────────────────────────────────────


def save_hand_state(config, skeleton, hand: str, hand_position,
                    hand_action) -> None:
    """把指定手 + 状态的控制器 transform 写入骨骼（数据键 = 短名，无后缀）"""
    state = _get_state(skeleton)
    action_str = hand_action.value
    pos_str = hand_position.value

    controllers = {}
    for short in _hand_controller_shorts(config, hand):
        ctrl = bpy.data.objects.get(config.obj_name(short))
        if ctrl is None:
            continue
        _sio.copy_transfer_between_object_and_dict(
            ctrl, controllers, "set", key=short)

    side = state.setdefault(_hand_key(hand), {})
    side.setdefault(action_str, {})[pos_str] = controllers
    _set_state(skeleton, state)

    print(f"已保存 {hand} 手 {action_str}/{pos_str} "
          f"({len(controllers)} 个控制器)")


def load_hand_state(config, skeleton, hand: str, hand_position,
                    hand_action) -> None:
    """从骨骼读取状态并应用到控制器（数据键 = 短名，无后缀）"""
    state = _get_state(skeleton)
    action_str = hand_action.value
    pos_str = hand_position.value

    controllers = (state.get(_hand_key(hand), {})
                   .get(action_str, {}).get(pos_str))
    if not controllers:
        raise ValueError(
            f"未找到 {hand} 手 {action_str}/{pos_str} 的已保存数据，请先保存")

    loaded = 0
    for short in _hand_controller_shorts(config, hand):
        ctrl = bpy.data.objects.get(config.obj_name(short))
        if ctrl is None or short not in controllers:
            continue
        _sio.copy_transfer_between_object_and_dict(
            ctrl, controllers, "load", key=short)
        loaded += 1

    print(f"已加载 {hand} 手 {action_str}/{pos_str} ({loaded} 个控制器)")


# ── 四点采集（Mapping Helpers，存演奏者骨骼自定义属性，不再用辅助球体） ──
#
# **采集方式（2026-09-30 起）**：四个槽位 A/B/C/D 由用户在「映射辅助」面板里
# **手动采集**，每个槽位同时记下当时的四项变换（与打击乐 MAPPING_HELPERS 同格式）：
#   - `Middle_Hand`：手部中点（Control Rig / Driver 自动算出的 H_L、H_R 中点）；
#   - `Head_Control`：头部位置；
#   - `Left_Hand` / `Right_Hand`：左右手主控制器 H_L / H_R 的位置 + 四元数旋转。
# 左右手必须单独存：头部目标由「离原始头部位置最远的那只手」决定，用中点代替单只手
# 会引入系统性偏移（原理见 docs/mapping_helpers_format.md 第 5 节）。
# 于是四个槽位的手部中点（A 空间）与头部位置（B 空间）定义了两套空间，
# Rust 端据此建立"手部中点空间 → 头部空间"的映射，槽位顺序两边一一对应。
#
# **槽位语义（2026-10 起，必须遵守）**：
#   - 槽位 A = **默认坐姿**。它同时是"原始头部位置"（头部原点），Rust 端直接拿
#     `Head_Control_A` 判断"哪只手离头更远、该由谁主导头部位置"；
#   - 槽位 B / C / D = 三个**极端坐姿**（手往三个方向伸到极限）。
# A 摆错等于原点错，主导手判断会整体偏掉。
#
# 旧口径（"在四个指定状态（A/B/C/D）下自动采集"）已废除；
# 旧的"四点尽量不共面、按四面体体积在 3D 仿射 / 2D 透视之间选路"也已废除——
# 现在 Rust 端用的是"主导手 + 姿势库局部加权"，不做仿射变换，没有共面退化问题。

# 槽位短名（与导出 JSON 的 `Middle_Hand_A` / `Head_Control_A` /
# `Left_Hand_A` / `Right_Hand_A` 对应）
MAPPING_SLOTS = ("a", "b", "c", "d")


def _mapping_objects(config):
    """取 Middle_Hand / Head_Control / H_L / H_R 四个控制器物体；缺失项为 None"""
    return (config.obj("Middle_Hand"), config.obj("Head_Control"),
            config.obj("H_L"), config.obj("H_R"))


def _read_ctrl_transform(ctrl_obj) -> dict:
    """读取控制器物体的「位置 + 四元数旋转（w 在前）」，与打击乐 `_read_ctrl` 同口径"""
    transform_entry = {}
    _sio.copy_transfer_between_object_and_dict(ctrl_obj, transform_entry, "set")
    return transform_entry[ctrl_obj.name]


def _apply_ctrl_transform(ctrl_obj, transform_entry: dict) -> None:
    """把存下的「位置 + 旋转」写回控制器物体（缺哪个字段就跳过哪个）"""
    _sio.copy_transfer_between_object_and_dict(
        ctrl_obj, {ctrl_obj.name: transform_entry}, "load")


def save_mapping(config, skeleton, slot_key: str) -> bool:
    """把当前 Middle_Hand / Head_Control 的位置、H_L / H_R 的位置与旋转存进指定槽位

    返回是否保存成功。槽位键统一转小写后再取大写做导出名。
    左右手控制器缺失时整槽都不写，避免导出半套数据。
    """
    slot_key = (slot_key or "").lower()
    if slot_key not in MAPPING_SLOTS:
        print(f"  ⚠ 未知的映射槽位：{slot_key}")
        return False
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法保存映射辅助数据")
        return False

    (middle_hand_obj, head_control_obj,
     left_hand_obj, right_hand_obj) = _mapping_objects(config)
    if not (middle_hand_obj and head_control_obj):
        print("  ⚠ 缺少 Middle_Hand / Head_Control 物体，无法保存映射辅助数据")
        return False
    if not (left_hand_obj and right_hand_obj):
        print("  ⚠ 缺少 H_L / H_R 左右手控制器，无法保存映射辅助数据")
        return False

    data = get_bilinear_data(skeleton)
    slot_letter = slot_key.upper()
    middle_hand_name = f"Middle_Hand_{slot_letter}"
    head_control_name = f"Head_Control_{slot_letter}"
    left_hand_name = f"Left_Hand_{slot_letter}"
    right_hand_name = f"Right_Hand_{slot_letter}"

    data[middle_hand_name] = {"location": list(middle_hand_obj.location)}
    data[head_control_name] = {"location": list(head_control_obj.location)}
    data[left_hand_name] = _read_ctrl_transform(left_hand_obj)
    data[right_hand_name] = _read_ctrl_transform(right_hand_obj)
    set_bilinear_data(skeleton, data)

    print(f"\n✓ 已采集槽位 {slot_letter}：")
    print(f"  {middle_hand_name}: {data[middle_hand_name]['location']}")
    print(f"  {head_control_name}: {data[head_control_name]['location']}")
    for hand_name in (left_hand_name, right_hand_name):
        print(f"  {hand_name}: 位置 {data[hand_name]['location']} "
              f"旋转 {data[hand_name]['rotation']}")
    return True


def load_mapping(config, skeleton, slot_key: str) -> bool:
    """把指定槽位（a/b/c/d）的位置还原到 Middle_Hand / Head_Control，
    位置 + 旋转还原到 H_L / H_R；旧数据没有左右手键时跳过，不报错
    """
    slot_key = (slot_key or "").lower()
    if slot_key not in MAPPING_SLOTS:
        print(f"  ⚠ 未知的映射槽位：{slot_key}")
        return False
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法加载映射辅助数据")
        return False

    (middle_hand_obj, head_control_obj,
     left_hand_obj, right_hand_obj) = _mapping_objects(config)
    if not (middle_hand_obj and head_control_obj):
        print("  ⚠ 缺少 Middle_Hand / Head_Control 物体，无法加载映射辅助数据")
        return False

    data = get_bilinear_data(skeleton)
    slot_letter = slot_key.upper()
    middle_hand_entry = data.get(f"Middle_Hand_{slot_letter}")
    head_control_entry = data.get(f"Head_Control_{slot_letter}")
    if not (middle_hand_entry and head_control_entry):
        print(f"  ⚠ 骨骼中未找到槽位 {slot_letter} 的数据，请先采集")
        return False

    middle_hand_obj.location = middle_hand_entry["location"]
    head_control_obj.location = head_control_entry["location"]
    print(f"\n✓ 已还原槽位 {slot_letter}：")
    print(f"  {middle_hand_obj.name}: {list(middle_hand_obj.location)}")
    print(f"  {head_control_obj.name}: {list(head_control_obj.location)}")

    # 左右手（旧版数据没有这两个键：提示后跳过，不影响中点/头部的还原结果）
    left_hand_entry = data.get(f"Left_Hand_{slot_letter}")
    right_hand_entry = data.get(f"Right_Hand_{slot_letter}")
    if not (left_hand_entry or right_hand_entry):
        print(f"  ⚠ 槽位 {slot_letter} 没有左右手数据（旧版采集），跳过左右手还原")
    for hand_name, hand_obj, hand_entry in (
            (f"Left_Hand_{slot_letter}", left_hand_obj, left_hand_entry),
            (f"Right_Hand_{slot_letter}", right_hand_obj, right_hand_entry)):
        if not hand_entry:
            if left_hand_entry or right_hand_entry:
                print(f"  ⚠ 槽位 {slot_letter} 缺少 {hand_name} 数据，跳过")
            continue
        if hand_obj is None:
            print(f"  ⚠ 找不到左右手控制器物体，无法还原 {hand_name}")
            continue
        _apply_ctrl_transform(hand_obj, hand_entry)
        print(f"  {hand_obj.name}: 位置 {list(hand_obj.location)} "
              f"旋转 {hand_entry.get('rotation')}")
    return True


def get_mapping_slot_summary(skeleton) -> dict:
    """返回各槽位的采集状态（槽位短名 → 是否已采集），供面板显示用

    只以 Middle_Hand + Head_Control 是否存在为准：旧槽位（没有左右手数据）
    仍算已采集，避免升级后把老资产判成"未采集"。
    """
    data = get_bilinear_data(skeleton)
    return {
        slot_key: (f"Middle_Hand_{slot_key.upper()}" in data
                   and f"Head_Control_{slot_key.upper()}" in data)
        for slot_key in MAPPING_SLOTS
    }
