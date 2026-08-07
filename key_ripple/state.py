# key_ripple/state.py
"""KeyRipple 乐器模块 —— 状态管理（迁移自 key_ripple_blender/tools/state_manager.py）

负责控制器 ↔ 骨骼自定义属性(key_ripple_state_data) 之间的状态存取。
通用搬运用 common.state_io；控制器名按演奏者后缀解析。
"""

import json

import bpy  # type: ignore

from ..common import state_io as _sio
from .config import KeyRipple, HandType, KeyType, PositionType


def get_true_transform_value(obj, transform_type):
    """获取对象的真实变换值，处理约束器影响（复用 common.state_io）"""
    return _sio.get_true_transform_value(obj, transform_type)


# ── 骨骼自定义属性读写 ─────────────────────────────────────────────


def get_state_data(skeleton, key_type: KeyType, position_type: PositionType) -> dict | None:
    """从骨骼读取指定 (key_type, position_type) 的状态条目"""
    raw = skeleton.get("key_ripple_state_data")
    arr = json.loads(raw) if raw else []
    for item in arr:
        if item.get("key_type") == key_type.value and item.get("position_type") == position_type.value:
            return item
    return None


def set_state_data(skeleton, key_type: KeyType, position_type: PositionType, data: dict) -> None:
    """写入指定 (key_type, position_type) 的状态条目到骨骼（合并 controllers 而非替换）"""
    raw = skeleton.get("key_ripple_state_data")
    arr = json.loads(raw) if raw else []
    for i, item in enumerate(arr):
        if item.get("key_type") == key_type.value and item.get("position_type") == position_type.value:
            existing_ctrl = item.get("controllers", {})
            new_ctrl = data.get("controllers", {})
            existing_ctrl.update(new_ctrl)
            item["controllers"] = existing_ctrl
            arr[i] = item
            break
    else:
        arr.append(data)
    skeleton["key_ripple_state_data"] = json.dumps(arr, ensure_ascii=False)


# ── 控制器 ↔ 字典数据搬运 ──────────────────────────────────────────


def copy_transfer_between_object_and_dict(obj, data_dict: dict, direction: str = "set"):
    """obj ↔ JSON dict 之间的数据搬运（复用 common.state_io）"""
    return _sio.copy_transfer_between_object_and_dict(obj, data_dict, direction)


# ── 控制器名称收集 ──────────────────────────────────────────────────


def _get_controllers_for_hand(key_ripple: KeyRipple, hand_type: HandType) -> list:
    """返回指定手部的全部控制器完整名称列表（手指+手掌+Head_Control）"""
    names = []
    for fn, ctrl_name in key_ripple.finger_controllers.items():
        if (hand_type == HandType.LEFT and ctrl_name.endswith("_L")) or \
           (hand_type == HandType.RIGHT and ctrl_name.endswith("_R")):
            names.append(key_ripple.obj_name(ctrl_name))
    for role, ctrl_name in key_ripple.hand_controllers.items():
        if (hand_type == HandType.LEFT and ctrl_name.endswith("_L")) or \
           (hand_type == HandType.RIGHT and ctrl_name.endswith("_R")):
            names.append(key_ripple.obj_name(ctrl_name))
    if hand_type == HandType.LEFT:
        names.append(key_ripple.obj_name("Head_Control"))
    return names


# ── 保存 / 加载 ─────────────────────────────────────────────────────


def save_state(
    key_ripple: KeyRipple,
    skeleton,
    hand_type: HandType,
    key_type: KeyType,
    position_type: PositionType,
) -> None:
    """一次性保存指定手部 + Head_Control 的控制器状态到骨骼"""
    controller_names = _get_controllers_for_hand(key_ripple, hand_type)
    data = {
        "key_type": key_type.value,
        "position_type": position_type.value,
        "controllers": {},
    }
    for ctrl_name in controller_names:
        ctrl = bpy.data.objects.get(ctrl_name)
        if ctrl is None:
            continue
        copy_transfer_between_object_and_dict(ctrl, data["controllers"], "set")

    set_state_data(skeleton, key_type, position_type, data)
    print(f"已保存 {hand_type.value} 手 {key_type.value}/{position_type.value} "
          f"({len(data['controllers'])} 个控制器)")


def load_state(
    key_ripple: KeyRipple,
    skeleton,
    hand_type: HandType,
    key_type: KeyType,
    position_type: PositionType,
) -> None:
    """从骨骼加载控制器状态并应用到指定手部 + Head_Control"""
    data = get_state_data(skeleton, key_type, position_type)
    if data is None:
        raise ValueError(
            f"未找到 {key_type.value}/{position_type.value} 的已保存数据，请先保存")

    controller_names = _get_controllers_for_hand(key_ripple, hand_type)
    loaded = 0
    for ctrl_name in controller_names:
        ctrl = bpy.data.objects.get(ctrl_name)
        if ctrl is None:
            continue
        if ctrl_name not in data.get("controllers", {}):
            continue
        copy_transfer_between_object_and_dict(
            ctrl, data["controllers"], "load")
        loaded += 1

    print(f"已加载 {hand_type.value} 手 {key_type.value}/{position_type.value} "
          f"({loaded} 个控制器)")
