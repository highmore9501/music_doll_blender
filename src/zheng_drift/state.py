# zheng_drift/state.py
"""ZhengDrift 乐器模块 —— 状态传输

左右手状态统一存**演奏者骨骼自定义属性**（zheng_drift_state_data），
头部采样数据存 **zheng_drift_head_sample_data**，与 key_ripple / fret_dance 一致；
不再在场景里生成大量记录器/辅助球体物体。
复用 common.state_io 的对象↔字典搬运工具（含约束器影响的真实变换）。

骨骼自定义属性结构（JSON）：数据键一律用**短名**（无演奏者后缀），
场景控件才用带后缀的完整名查找，保证不同演奏者的骨骼数据结构一致。
{
  "left_hand":  { "<action>": { "<position>": { "<短控制器名>": {"location": [...], "rotation": [...]} } } },
  "right_hand": { "<action>": { "<position>": { ... } } }
}
action：左手 Normal/Press；右手 Normal/Tremolo；position：far/middle/near

头部采样（zheng_drift_head_sample_data）：
{
  "origin": {"location": [...]},
  "left":  { "<action>_<position>": {"hand_location": [...], "head_location": [...]} },
  "right": { ... }
}
原点 = 默认坐姿下的头部位置；每条样本 = 某个手部状态下"这只手在哪、头该在哪"。
"""

import bpy  # type: ignore

from ..common import state_io as _sio

# 骨骼自定义属性键
STATE_KEY = "zheng_drift_state_data"
# 头部采样数据的骨骼自定义属性键（头部原点 + 左右手各状态下的一条样本）
HEAD_SAMPLE_KEY = "zheng_drift_head_sample_data"


def _get_state(skeleton) -> dict:
    return _sio.get_state_data(skeleton, STATE_KEY, {}) or {}


def _set_state(skeleton, data: dict) -> None:
    _sio.set_state_data(skeleton, STATE_KEY, data)


# ── 头部采样数据（存骨骼，键 = 手 + 状态） ──────────────────────

# 数据里表示"哪只手"的两个键；顺序固定，导出时按这个顺序写
HEAD_SIDES = ("left", "right")


def get_head_sample_data(skeleton) -> dict:
    """读取头部采样数据（`origin` + `left` / `right`）"""
    return _sio.get_state_data(skeleton, HEAD_SAMPLE_KEY, {}) or {}


def set_head_sample_data(skeleton, data: dict) -> None:
    """写回头部采样数据到骨骼自定义属性"""
    _sio.set_state_data(skeleton, HEAD_SAMPLE_KEY, data)


def hand_sample_states(hand: str) -> list[str]:
    """指定手的 6 个状态键（`{动作}_{位置}`，与导出 JSON 的键逐字一致）"""
    actions = ("Normal", "Press") if hand == "left" else ("Normal", "Tremolo")
    return [f"{action}_{position}" for action in actions
            for position in ("far", "middle", "near")]


def missing_head_sample_states(skeleton) -> list[str]:
    """尚未采集的头部样本键（原点单列成 `origin`），供导出/导入时提示"""
    data = get_head_sample_data(skeleton)
    missing = [] if "origin" in data else ["origin"]
    for hand in HEAD_SIDES:
        side_data = data.get(hand, {}) or {}
        for state_key in hand_sample_states(hand):
            if state_key not in side_data:
                missing.append(f"{hand}_{state_key}")
    return missing


def get_head_sample_summary(skeleton) -> dict:
    """各手已采集的状态键，供面板显示 `n/12`（`origin` 单独一项）"""
    data = get_head_sample_data(skeleton)
    return {
        "origin": "origin" in data,
        "left": sorted((data.get("left", {}) or {}).keys()),
        "right": sorted((data.get("right", {}) or {}).keys()),
    }


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


def _head_control_location(config) -> list | None:
    """当前 Head_Control 的位置（物体不存在时返回 None）"""
    head_control_obj = config.obj("Head_Control")
    if head_control_obj is None:
        return None
    return list(_read_ctrl_transform(head_control_obj)["location"])


def _capture_head_sample(config, skeleton, hand: str, action_str: str,
                         pos_str: str, controllers: dict) -> None:
    """顺手采一条头部样本：这个手部状态下"这只手在哪、头该在哪"

    手的位置直接取刚落盘的那只手 H_L / H_R，和手部状态数据是同一次读取的结果，
    不需要再读一遍物体。
    """
    head_location = _head_control_location(config)
    if head_location is None:
        print("  ⚠ 未找到 Head_Control，本次只保存了手部状态，未采集头部位置")
        return

    hand_short = "H_L" if hand == "left" else "H_R"
    hand_entry = controllers.get(hand_short)
    if hand_entry is None:
        print(f"  ⚠ 未找到 {hand_short} 的位置数据，本次未采集头部位置")
        return

    data = get_head_sample_data(skeleton)
    data.setdefault(hand, {})[f"{action_str}_{pos_str}"] = {
        "hand_location": list(hand_entry["location"]),
        "head_location": head_location,
    }
    set_head_sample_data(skeleton, data)
    print(f"  ✓ 已采集 {hand} 手 {action_str}/{pos_str} 的头部位置：{head_location}")


def _apply_head_sample(config, skeleton, hand: str, action_str: str,
                       pos_str: str) -> None:
    """把该手该状态采到的头部位置还原到 Head_Control"""
    data = get_head_sample_data(skeleton)
    sample = (data.get(hand, {}) or {}).get(f"{action_str}_{pos_str}")
    if sample is None:
        print(f"  • {hand} 手 {action_str}/{pos_str} 没有头部采样，头部保持当前位置")
        return

    head_control_obj = config.obj("Head_Control")
    if head_control_obj is None:
        print("  ⚠ 未找到 Head_Control，无法还原头部位置")
        return

    head_control_obj.location = sample["head_location"]
    print(f"  ✓ 已还原头部位置：{sample['head_location']}")


def save_hand_state(config, skeleton, hand: str, hand_position,
                    hand_action) -> None:
    """把指定手 + 状态的控制器 transform 写入骨骼（数据键 = 短名，无后缀），
    并顺手采集该状态下的头部位置
    """
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

    _capture_head_sample(config, skeleton, hand, action_str, pos_str, controllers)


def load_hand_state(config, skeleton, hand: str, hand_position,
                    hand_action) -> None:
    """从骨骼读取状态并应用到控制器（数据键 = 短名，无后缀），
    并把该状态采到的头部位置一并还原
    """
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

    _apply_head_sample(config, skeleton, hand, action_str, pos_str)


# ── 头部原点（默认坐姿下的头部位置） ──────────────────────────
#
# 头部位置靠"查表"决定：Rust 端拿主导手（离头部原点更远的那只手）的位置，
# 去同一只手的样本里按距离加权，取加权之后的头部位置。因此需要两样东西：
#   - **头部原点**：默认坐姿下头在哪。它只用于判断哪只手离头更远；
#   - **各手部状态的样本**：每只手的 6 个状态（远/中/近 × 动作）各一条，记录
#     保存该状态那一刻这只手在哪、头在哪。样本跟着手部状态一起采集，见
#     `save_hand_state` / `load_hand_state`，不需要单独的采集按钮。
#
# 原点摆错等于判据错，主导手判断会整体偏掉：采集时人物必须坐在默认坐姿上。


def _read_ctrl_transform(ctrl_obj) -> dict:
    """读取控制器物体的「位置 + 四元数旋转（w 在前）」，与打击乐 `_read_ctrl` 同口径"""
    transform_entry = {}
    _sio.copy_transfer_between_object_and_dict(ctrl_obj, transform_entry, "set")
    return transform_entry[ctrl_obj.name]


def save_head_origin(config, skeleton) -> bool:
    """采集默认坐姿下的头部位置（头部原点），返回是否采集成功"""
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法采集头部原点")
        return False

    head_location = _head_control_location(config)
    if head_location is None:
        print("  ⚠ 缺少 Head_Control 物体，无法采集头部原点")
        return False

    data = get_head_sample_data(skeleton)
    data["origin"] = {"location": head_location}
    set_head_sample_data(skeleton, data)

    print(f"\n✓ 已采集头部原点：{head_location}")
    return True


def load_head_origin(config, skeleton) -> bool:
    """把头部原点还原到 Head_Control，返回是否还原成功"""
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法还原头部原点")
        return False

    data = get_head_sample_data(skeleton)
    origin_entry = data.get("origin")
    if origin_entry is None:
        print("  ⚠ 骨骼中未找到头部原点，请先采集")
        return False

    head_control_obj = config.obj("Head_Control")
    if head_control_obj is None:
        print("  ⚠ 缺少 Head_Control 物体，无法还原头部原点")
        return False

    head_control_obj.location = origin_entry["location"]
    print(f"\n✓ 已还原头部原点：{list(head_control_obj.location)}")
    return True
