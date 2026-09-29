# zheng_drift/state.py
"""ZhengDrift 乐器模块 —— 状态传输

左右手状态统一存**演奏者骨骼自定义属性**（zheng_drift_state_data），
映射辅助的四个采集点（手部中点 + 头部位置）存 **zheng_drift_bilinear_data**，
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
# 映射辅助四个采集点（手部中点 + 头部位置）的骨骼自定义属性键
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
# **手动采集**，每个槽位同时记下当时的两个位置：
#   - `Middle_Hand`：手部中点（Control Rig / Driver 自动算出的 H_L、H_R 中点）；
#   - `Head_Control`：头部位置。
# 于是这 8 个点定义了两个空间，Rust 端据此建立"手部中点空间 → 头部空间"的映射：
#   A 空间 = 四个手部中点；B 空间 = 四个头部位置。槽位顺序两边一一对应。
#
# 采集建议：四个槽位要尽量让手部中点**不要落在同一个平面上**（四面体体积越大越好），
# Rust 端按四面体体积在"3D 仿射"与"2D 透视"之间自动选路，四点越接近共面映射越容易退化。
# 旧口径（"在四个指定状态（A/B/C/D）下自动采集"）已废除。

# 槽位短名（与导出 JSON 的 `Middle_Hand_A` / `Head_Control_A` 对应）
MAPPING_SLOTS = ("a", "b", "c", "d")


def _mapping_objects(config):
    """取 Middle_Hand / Head_Control 两个控制器物体；缺失时返回 (None, None)"""
    return config.obj("Middle_Hand"), config.obj("Head_Control")


def save_mapping(config, skeleton, slot_key: str) -> bool:
    """把当前 Middle_Hand / Head_Control 的位置存进指定槽位（a/b/c/d）

    返回是否保存成功。槽位键统一转小写后再取大写做导出名。
    """
    slot_key = (slot_key or "").lower()
    if slot_key not in MAPPING_SLOTS:
        print(f"  ⚠ 未知的映射槽位：{slot_key}")
        return False
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法保存映射辅助数据")
        return False

    middle_hand_obj, head_control_obj = _mapping_objects(config)
    if not (middle_hand_obj and head_control_obj):
        print("  ⚠ 缺少 Middle_Hand / Head_Control 物体，无法保存映射辅助数据")
        return False

    data = get_bilinear_data(skeleton)
    mh_name = f"Middle_Hand_{slot_key.upper()}"
    hc_name = f"Head_Control_{slot_key.upper()}"
    data[mh_name] = {"location": list(middle_hand_obj.location)}
    data[hc_name] = {"location": list(head_control_obj.location)}
    set_bilinear_data(skeleton, data)

    print(f"\n✓ 已采集槽位 {slot_key.upper()}：")
    print(f"  {mh_name}: {data[mh_name]['location']}")
    print(f"  {hc_name}: {data[hc_name]['location']}")
    return True


def load_mapping(config, skeleton, slot_key: str) -> bool:
    """把指定槽位（a/b/c/d）的位置还原到 Middle_Hand / Head_Control"""
    slot_key = (slot_key or "").lower()
    if slot_key not in MAPPING_SLOTS:
        print(f"  ⚠ 未知的映射槽位：{slot_key}")
        return False
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法加载映射辅助数据")
        return False

    middle_hand_obj, head_control_obj = _mapping_objects(config)
    if not (middle_hand_obj and head_control_obj):
        print("  ⚠ 缺少 Middle_Hand / Head_Control 物体，无法加载映射辅助数据")
        return False

    data = get_bilinear_data(skeleton)
    mh_entry = data.get(f"Middle_Hand_{slot_key.upper()}")
    hc_entry = data.get(f"Head_Control_{slot_key.upper()}")
    if not (mh_entry and hc_entry):
        print(f"  ⚠ 骨骼中未找到槽位 {slot_key.upper()} 的数据，请先采集")
        return False

    middle_hand_obj.location = mh_entry["location"]
    head_control_obj.location = hc_entry["location"]
    print(f"\n✓ 已还原槽位 {slot_key.upper()}：")
    print(f"  {middle_hand_obj.name}: {list(middle_hand_obj.location)}")
    print(f"  {head_control_obj.name}: {list(head_control_obj.location)}")
    return True


def get_mapping_slot_summary(skeleton) -> dict:
    """返回各槽位的采集状态（槽位短名 → 是否已采集），供面板显示用"""
    data = get_bilinear_data(skeleton)
    return {
        slot_key: (f"Middle_Hand_{slot_key.upper()}" in data
                   and f"Head_Control_{slot_key.upper()}" in data)
        for slot_key in MAPPING_SLOTS
    }
