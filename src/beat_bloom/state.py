# beat_bloom/state.py
"""BeatBloom 乐器模块 —— 状态传输

所有状态数据存骨骼自定义属性 `beat_bloom_state_data`（JSON），
不在场景中创建记录器物体。

JSON 结构（组件 → 打法 → 状态 → 控件）：
{
  "<component>": {
    "techniques": {
      "<technique_id>": {
        "poses": {
          "ready": {"<ctrl_short>": {"location": [...], "rotation": [w,x,y,z]}},
          "beat":  {...},
          "rest":  {...}
        }
      }
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

「打法」是同一颗鼓、同一条肢体的一种击打方式（例如右手打地嗵可以手腕上下翻，
也可以手腕侧翻）。有哪些打法由 `.drumkit` 声明，这里只存每种打法的姿态。
某颗鼓只有一种打法时，读老结构（组件下直接是状态键）也等价于一条 `default`。

控制器键的保存范围：只录本次击打声明的那条肢体
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

# 打法层的键名与「只有一条默认打法」时的 id
TECHNIQUES_KEY = "techniques"
POSES_KEY = "poses"
DEFAULT_TECHNIQUE = "default"
STATE_NAMES = ("ready", "beat", "rest")

LEGACY_STATE_KEY_SUFFIXES = (
    "_rotation_L",
    "_rotation_R",
    "_rotation",
)


def _is_legacy_state_key(key: str) -> bool:
    """识别旧版拆分旋转键：H_rotation_L / F_rotation_R / H_rotation_Rest_L"""
    if not isinstance(key, str):
        return False
    key = key.strip()
    if not key:
        return False
    return any(key.endswith(suffix) or "_rotation_" in key for suffix in LEGACY_STATE_KEY_SUFFIXES)


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


def cleanup_legacy_state(skeleton) -> int:
    """清理旧版 split-rotation 残留键，返回实际删除数量。"""
    if skeleton is None:
        return 0

    data = _get_state(skeleton)
    if not data:
        return 0

    cleaned = 0

    for section_name, section_value in list(data.items()):
        if not isinstance(section_value, dict):
            continue

        if section_name == "mapping_helpers":
            for slot_name, slot_value in list(section_value.items()):
                if not isinstance(slot_value, dict):
                    continue
                for key in list(slot_value.keys()):
                    if _is_legacy_state_key(str(key)):
                        del slot_value[key]
                        cleaned += 1
            continue

        for state_name, state_value in list(section_value.items()):
            if not isinstance(state_value, dict):
                continue
            for key in list(state_value.keys()):
                if _is_legacy_state_key(str(key)):
                    del state_value[key]
                    cleaned += 1
            if not state_value:
                del section_value[state_name]

        if not section_value:
            del data[section_name]

    _set_state(skeleton, data)
    return cleaned


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
    """只读取控件位置（头部控制器用）"""
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
    """只写位置（头部控制器用）"""
    obj = bpy.data.objects.get(_pu.resolve(short, suffix))
    if obj is None:
        return
    obj.location = (loc[0], loc[1], loc[2])


# ── 打法表读写（含老结构兼容） ────────────────────────────────

def _legacy_poses(component_data: dict) -> dict:
    """老结构（组件下直接是 beat/ready/rest）取出来，包装成 poses 那一层。"""
    return {
        state_name: state_value
        for state_name, state_value in component_data.items()
        if state_name in STATE_NAMES and isinstance(state_value, dict)
    }


def component_techniques(state_data: dict, component_name: str) -> dict:
    """取某个组件的打法表 `{technique_id: {"poses": {...}}}`。

    老数据（组件下直接是状态键）等价于一条 `default`。
    """
    component_data = state_data.get(component_name)
    if not isinstance(component_data, dict):
        return {}

    techniques = component_data.get(TECHNIQUES_KEY)
    if isinstance(techniques, dict):
        return techniques

    legacy_poses = _legacy_poses(component_data)
    if not legacy_poses:
        return {}
    return {DEFAULT_TECHNIQUE: {POSES_KEY: legacy_poses}}


def ensure_component_techniques(state_data: dict, component_name: str) -> dict:
    """取打法表用于写入；老结构就地升级成新结构。"""
    component_data = state_data.setdefault(component_name, {})
    techniques = component_data.get(TECHNIQUES_KEY)
    if isinstance(techniques, dict):
        return techniques

    legacy_poses = _legacy_poses(component_data)
    component_data.clear()
    techniques = {DEFAULT_TECHNIQUE: {POSES_KEY: legacy_poses}} if legacy_poses else {}
    component_data[TECHNIQUES_KEY] = techniques
    return techniques


def technique_poses(state_data: dict, component_name: str, technique_id: str) -> dict:
    """取某条打法的三态 `{state_name: {ctrl_short: {...}}}`。"""
    technique_data = component_techniques(state_data, component_name).get(technique_id)
    if not isinstance(technique_data, dict):
        return {}
    poses = technique_data.get(POSES_KEY)
    return poses if isinstance(poses, dict) else {}


# ── 辅助：这条打法要录哪些控件 ────────────────────────────────

def technique_limb_override(drumkit_dict: dict, component_name: str,
                            technique_id: str) -> list:
    """这条打法在鼓组配置里额外声明的肢体。

    只用于合击打法（例如手 + 脚同时打同一个鼓件）。普通打法不声明，
    录制范围就只由面板上选中的那条肢体决定。
    """
    if drumkit_dict is None:
        return []

    all_components = (drumkit_dict.get("components", [])
                      + drumkit_dict.get("special_actions", []))
    for component in all_components:
        if component.get("name") != component_name:
            continue

        technique_entries = []
        for entry in component.get("drivable_limbs", []) or []:
            if isinstance(entry, dict):
                technique_entries.extend(entry.get("techniques", []) or [])
        # 特殊动作的打法直接挂在动作对象上
        technique_entries.extend(component.get("techniques", []) or [])

        overrides = []
        for technique in technique_entries:
            if not isinstance(technique, dict) or technique.get("id") != technique_id:
                continue
            for limb in technique.get("limbs", []) or []:
                if limb not in overrides:
                    overrides.append(limb)
        return overrides
    return []


def control_shorts_for_limbs(limbs: list) -> tuple:
    """肢体列表 → (位置+旋转控制器短名, 是否需要写 Head_Control)。"""
    ctrl_shorts = []
    has_head = False
    for limb in limbs:
        ctrl_shorts.extend(LIMB_CONTROLLERS.get(limb, []))
        if limb in HAND_LIMBS:
            has_head = True
    return list(dict.fromkeys(ctrl_shorts)), has_head


# ── 状态保存 / 加载 ───────────────────────────────────────────

def save_state(suffix: str, component_name: str, limb: str, technique_id: str,
               state_name: str, skeleton, drumkit_dict: dict) -> None:
    """把当前控件姿态存进 <component>/techniques/<technique>/poses/<state>。

    只录这条击打声明的那条肢体（手部另带 Head_Control），不再把该组件所有
    可驱动肢体的姿态一起录进来 —— 两只手都能打的鼓件，摆右手时会顺带把左手
    存到一个不相干的位置上。
    """
    recording_limbs = [limb] if limb else []
    for override_limb in technique_limb_override(
            drumkit_dict, component_name, technique_id):
        if override_limb not in recording_limbs:
            recording_limbs.append(override_limb)
    ctrl_shorts, has_head = control_shorts_for_limbs(recording_limbs)

    data = _get_state(skeleton)
    techniques = ensure_component_techniques(data, component_name)
    technique_data = techniques.setdefault(technique_id, {POSES_KEY: {}})
    poses = technique_data.setdefault(POSES_KEY, {})
    state_data = poses.setdefault(state_name, {})

    for short in ctrl_shorts:
        state_data[short] = _read_ctrl(suffix, short)

    if has_head:
        state_data["Head_Control"] = {
            "location": _read_ctrl_location_only(suffix, "Head_Control")}

    _set_state(skeleton, data)
    print(f"✓ 已保存 {component_name} / {technique_id} / {state_name}")


def load_state(suffix: str, component_name: str, technique_id: str,
               state_name: str, skeleton) -> bool:
    """从骨骼 JSON 加载某条打法的某个状态到控件；返回是否成功"""
    data = _get_state(skeleton)
    state_data = technique_poses(data, component_name, technique_id).get(state_name)
    if state_data is None:
        print(f"✗ 骨骼中不存在 {component_name} / {technique_id} / {state_name}")
        return False

    for short, ctrl_data in state_data.items():
        if short == "Head_Control":
            loc = ctrl_data.get("location", [0.0, 0.0, 0.0])
            _write_ctrl_location(suffix, "Head_Control", loc)
        else:
            _write_ctrl(suffix, short, ctrl_data)

    print(f"✓ 已加载 {component_name} / {technique_id} / {state_name}")
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

    # 头部控制器只存位置
    location_only_shorts = ("Head_Control",)
    for short, ctrl_data in rest_data.items():
        if short in location_only_shorts:
            loc = ctrl_data.get("location", [0.0, 0.0, 0.0])
            _write_ctrl_location(suffix, short, loc)
        else:
            _write_ctrl(suffix, short, ctrl_data)

    print("✓ 已加载 rest 状态")
    return True


def save_mapping(suffix: str, skeleton, key: str) -> None:
    """保存 A/B/C/D 之一的 Middle_Hand / Head_Control / H_L / H_R 位置到骨骼 JSON

    Middle_Hand 由左右手位置直接算出（控件本身不再跟随双手）。
    """
    data = _get_state(skeleton)
    helpers = data.setdefault("mapping_helpers", {})
    entry = helpers.setdefault(key, {})

    entry["Head_Control"] = _read_ctrl_location_only(suffix, "Head_Control")
    entry["H_L"] = _read_ctrl(suffix, "H_L")
    entry["H_R"] = _read_ctrl(suffix, "H_R")

    left_location = entry["H_L"].get("location", [0.0, 0.0, 0.0])
    right_location = entry["H_R"].get("location", [0.0, 0.0, 0.0])
    entry["Middle_Hand"] = [
        (left_location[axis_index] + right_location[axis_index]) / 2.0
        for axis_index in range(3)
    ]

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
