# beat_bloom/state.py
"""BeatBloom 乐器模块 —— 状态传输

所有状态数据存骨骼自定义属性 `beat_bloom_state_data`（JSON），
不在场景中创建记录器物体。

JSON 结构：
{
  "<component_name>": {
    "<state>": {
      "<ctrl_short>": {"location": [...], "rotation": [w,x,y,z]}
    }
  },
  "rest": {
    "<ctrl_short>": {"location": [...], "rotation": [...]}
  },
  "mapping_helpers": {
    "A": {
      "Middle_Hand":  [x, y, z],
      "Head_Control": [x, y, z],
      "H_L":  {"location": [...], "rotation": [...]},
      "H_R":  {"location": [...], "rotation": [...]}
    },
    "B": {...}, "C": {...}, "D": {...}
  }
}

控制器键的保存范围由 drivable_limbs 决定：
  right_hand → H_R / HP_R  + Head_Control
  left_hand  → H_L / HP_L  + Head_Control
  right_foot → F_R
  left_foot  → F_L
"""

import json

import bpy  # type: ignore

from ..common import performer_utils as _pu
from .enums import LIMB_CONTROLLERS, HAND_LIMBS

STATE_KEY = "beat_bloom_state_data"


# ── 骨骼 JSON 读写 ────────────────────────────────────────────

def _get_state(skeleton) -> dict:
    if skeleton is None:
        return {}
    raw = skeleton.get(STATE_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _set_state(skeleton, data: dict) -> None:
    if skeleton is None:
        return
    skeleton[STATE_KEY] = json.dumps(data, ensure_ascii=False)


# ── 控件读写 ──────────────────────────────────────────────────

def _read_ctrl(suffix: str, short: str) -> dict:
    """读取控件当前位置 + 四元数旋转"""
    obj = bpy.data.objects.get(_pu.resolve(short, suffix))
    if obj is None:
        return {"location": [0.0, 0.0, 0.0], "rotation": [1.0, 0.0, 0.0, 0.0]}
    quat = (obj.rotation_quaternion
            if obj.rotation_mode == "QUATERNION"
            else obj.rotation_euler.to_quaternion())
    return {
        "location": list(obj.location),
        "rotation": [quat.w, quat.x, quat.y, quat.z],
    }


def _read_ctrl_location_only(suffix: str, short: str) -> list:
    """只读取控件位置（Head_Control 用）"""
    obj = bpy.data.objects.get(_pu.resolve(short, suffix))
    if obj is None:
        return [0.0, 0.0, 0.0]
    return list(obj.location)


def _write_ctrl(suffix: str, short: str, data: dict) -> None:
    """将位置和旋转写回控件"""
    obj = bpy.data.objects.get(_pu.resolve(short, suffix))
    if obj is None:
        return
    loc = data.get("location", [0.0, 0.0, 0.0])
    rot = data.get("rotation", [1.0, 0.0, 0.0, 0.0])
    obj.location = (loc[0], loc[1], loc[2])
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (rot[0], rot[1], rot[2], rot[3])


def _write_ctrl_location(suffix: str, short: str, loc: list) -> None:
    """只写位置（Head_Control 用）"""
    obj = bpy.data.objects.get(_pu.resolve(short, suffix))
    if obj is None:
        return
    obj.location = (loc[0], loc[1], loc[2])


# ── 辅助：根据 drumkit 中的 component 决定需要操作哪些控制器 ──

def _ctrl_shorts_for_component(drumkit_dict: dict, component_name: str) -> dict:
    """返回 component 涉及的控制器短名集合，格式 {short: include_rotation_only}。

    实际上返回两组：
      ctrl_shorts  - 位置+旋转的控制器列表（hand/foot 控制器）
      has_head     - 是否包含 Head_Control（只存位置）
    """
    ctrl_shorts = []
    has_head = False

    if drumkit_dict is None:
        return ctrl_shorts, has_head

    all_components = drumkit_dict.get(
        "components", []) + drumkit_dict.get("special_actions", [])
    for comp in all_components:
        if comp["name"] != component_name:
            continue
        if "drivable_limbs" in comp:
            limbs = [d["limb"] for d in comp["drivable_limbs"]]
        elif "limbs" in comp:
            limbs = comp["limbs"]
        else:
            limbs = []

        for limb in limbs:
            ctrl_shorts.extend(LIMB_CONTROLLERS.get(limb, []))
            if limb in HAND_LIMBS:
                has_head = True
        break

    return list(dict.fromkeys(ctrl_shorts)), has_head  # 去重保序


# ── 状态保存 / 加载 ───────────────────────────────────────────

def save_state(suffix: str, component_name: str, state_name: str,
               skeleton, drumkit_dict: dict) -> None:
    """保存当前控件位置到骨骼 JSON 的 <component>/<state> 下"""
    ctrl_shorts, has_head = _ctrl_shorts_for_component(
        drumkit_dict, component_name)

    data = _get_state(skeleton)
    comp_data = data.setdefault(component_name, {})
    state_data = comp_data.setdefault(state_name, {})

    for short in ctrl_shorts:
        state_data[short] = _read_ctrl(suffix, short)

    if has_head:
        state_data["Head_Control"] = {
            "location": _read_ctrl_location_only(suffix, "Head_Control")}

    _set_state(skeleton, data)
    print(f"✓ 已保存 {component_name}/{state_name}")


def load_state(suffix: str, component_name: str, state_name: str,
               skeleton) -> bool:
    """从骨骼 JSON 加载 <component>/<state> 到控件；返回是否成功"""
    data = _get_state(skeleton)
    state_data = data.get(component_name, {}).get(state_name)
    if state_data is None:
        print(f"✗ 骨骼中不存在 {component_name}/{state_name} 状态数据")
        return False

    for short, ctrl_data in state_data.items():
        if short == "Head_Control":
            loc = ctrl_data.get("location", [0.0, 0.0, 0.0])
            _write_ctrl_location(suffix, "Head_Control", loc)
        else:
            _write_ctrl(suffix, short, ctrl_data)

    print(f"✓ 已加载 {component_name}/{state_name}")
    return True


def save_rest_state(suffix: str, skeleton) -> None:
    """保存手部休息状态（H_L/HP_L + R 系列 + Head_Control）"""
    rest_shorts = ["H_L", "HP_L", "H_R", "HP_R"]

    data = _get_state(skeleton)
    rest_data = data.setdefault("rest", {})

    for short in rest_shorts:
        rest_data[short] = _read_ctrl(suffix, short)

    rest_data["Head_Control"] = {
        "location": _read_ctrl_location_only(suffix, "Head_Control")}
    _set_state(skeleton, data)
    print("✓ 已保存 rest 状态")


def load_rest_state(suffix: str, skeleton) -> bool:
    """从骨骼 JSON 加载 rest 状态到控件；返回是否成功"""
    data = _get_state(skeleton)
    rest_data = data.get("rest")
    if rest_data is None:
        print("✗ 骨骼中不存在 rest 状态数据")
        return False

    for short, ctrl_data in rest_data.items():
        if short == "Head_Control":
            loc = ctrl_data.get("location", [0.0, 0.0, 0.0])
            _write_ctrl_location(suffix, "Head_Control", loc)
        else:
            _write_ctrl(suffix, short, ctrl_data)

    print("✓ 已加载 rest 状态")
    return True


def save_mapping(suffix: str, skeleton, key: str) -> None:
    """保存 A/B/C/D 之一的 Middle_Hand / Head_Control / H_L / H_R 位置到骨骼 JSON"""
    data = _get_state(skeleton)
    helpers = data.setdefault("mapping_helpers", {})
    entry = helpers.setdefault(key, {})

    entry["Middle_Hand"] = _read_ctrl_location_only(suffix, "Middle_Hand")
    entry["Head_Control"] = _read_ctrl_location_only(suffix, "Head_Control")
    entry["H_L"] = _read_ctrl(suffix, "H_L")
    entry["H_R"] = _read_ctrl(suffix, "H_R")

    _set_state(skeleton, data)
    print(f"✓ 已保存 mapping_helpers/{key}")


def load_mapping(suffix: str, skeleton, key: str) -> bool:
    """从骨骼 JSON 加载 mapping A/B/C/D 到控件；返回是否成功"""
    data = _get_state(skeleton)
    entry = data.get("mapping_helpers", {}).get(key)
    if entry is None:
        print(f"✗ 骨骼中不存在 mapping_helpers/{key}")
        return False

    if "Middle_Hand" in entry:
        _write_ctrl_location(suffix, "Middle_Hand", entry["Middle_Hand"])
    if "Head_Control" in entry:
        _write_ctrl_location(suffix, "Head_Control", entry["Head_Control"])
    if "H_L" in entry:
        _write_ctrl(suffix, "H_L", entry["H_L"])
    if "H_R" in entry:
        _write_ctrl(suffix, "H_R", entry["H_R"])

    print(f"✓ 已加载 mapping_helpers/{key}")
    return True
