# zheng_drift/state.py
"""ZhengDrift 乐器模块 —— 状态传输

左右手状态统一存**演奏者骨骼自定义属性**（zheng_drift_state_data），
与 key_ripple / fret_dance 一致；不再在场景里生成大量记录器物体。
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


def _get_state(skeleton) -> dict:
    return _sio.get_state_data(skeleton, STATE_KEY, {}) or {}


def _set_state(skeleton, data: dict) -> None:
    _sio.set_state_data(skeleton, STATE_KEY, data)


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


# ── 四态 bilinear 保存/恢复（对象：Middle_Hand / Head_Control / 辅助球体） ──

# 四态定义（A/B/C/D）：
#   A: 左手 Normal + 右手 Tremolo + Far/Far
#   B: 左手 Press + 右手 Normal + Far/Far
#   C: 左手 Normal + 右手 Tremolo + Near/Near
#   D: 左手 Press + 右手 Normal + Near/Near


def _detect_state_key(left_position, left_action,
                      right_position, right_action) -> str | None:
    """检测是否满足四态之一，返回 state_key（a/b/c/d）；否则返回 None"""
    if (left_action.value == "Normal" and right_action.value == "Tremolo" and
            left_position.value == "far" and right_position.value == "far"):
        return "a"
    if (left_action.value == "Press" and right_action.value == "Normal" and
            left_position.value == "far" and right_position.value == "far"):
        return "b"
    if (left_action.value == "Normal" and right_action.value == "Tremolo" and
            left_position.value == "near" and right_position.value == "near"):
        return "c"
    if (left_action.value == "Press" and right_action.value == "Normal" and
            left_position.value == "near" and right_position.value == "near"):
        return "d"
    return None


def save_bilinear_helpers(config, left_position, left_action,
                          right_position, right_action) -> bool:
    """满足四态时，把 Middle_Hand / Head_Control 位置保存到对应辅助球体"""
    state_key = _detect_state_key(
        left_position, left_action, right_position, right_action)
    if not state_key:
        return False

    middle_hand_obj = config.obj("Middle_Hand")
    head_control_obj = config.obj("Head_Control")
    mh_helper = config.obj(f"Middle_Hand_{state_key.upper()}")
    hc_helper = config.obj(f"Head_Control_{state_key.upper()}")

    if middle_hand_obj and head_control_obj and mh_helper and hc_helper:
        mh_helper.location = middle_hand_obj.location.copy()
        hc_helper.location = head_control_obj.location.copy()
        print(
            f"\n✓ 检测到 {state_key.upper()} 态，已保存 Middle_Hand 和 Head_Control 的位置")
        print(f"  {mh_helper.name}: {list(mh_helper.location)}")
        print(f"  {hc_helper.name}: {list(hc_helper.location)}")
        return True
    return False


def load_bilinear_helpers(config, left_position, left_action,
                          right_position, right_action) -> bool:
    """满足四态时，从辅助球体加载位置到 Middle_Hand / Head_Control"""
    state_key = _detect_state_key(
        left_position, left_action, right_position, right_action)
    if not state_key:
        return False

    middle_hand_obj = config.obj("Middle_Hand")
    head_control_obj = config.obj("Head_Control")
    mh_helper = config.obj(f"Middle_Hand_{state_key.upper()}")
    hc_helper = config.obj(f"Head_Control_{state_key.upper()}")

    if middle_hand_obj and head_control_obj and mh_helper and hc_helper:
        middle_hand_obj.location = mh_helper.location.copy()
        head_control_obj.location = hc_helper.location.copy()
        print(
            f"\n✓ 检测到 {state_key.upper()} 态，已从辅助球体加载位置到 Middle_Hand 和 Head_Control")
        print(f"  {middle_hand_obj.name}: {list(middle_hand_obj.location)}")
        print(f"  {head_control_obj.name}: {list(head_control_obj.location)}")
        return True
    return False
