# beat_bloom/io.py
"""BeatBloom 乐器模块 —— .drummer 文件导入导出

从骨骼自定义属性（beat_bloom_state_data）读写，
导出格式保持扁平键名以兼容 Rust 侧消费：
  RECORDER_INFO  → <component>_<state>_<ctrl_short>
  MAPPING_HELPERS → Middle_Hand_A/B/C/D、Head_Control_A/B/C/D、Left_Hand_A/B/C/D、Right_Hand_A/B/C/D
"""

import json

import bpy  # type: ignore

from ..common import io_utils
from ..common import performer_utils
from .config import BeatBloomConfig
from .state import _get_state, _set_state, _ctrl_shorts_for_component
from .enums import HAND_LIMBS


def _old_pole_short(pole_short: str) -> str | None:
    """新 pole 短名 → 旧命名短名（一次性迁移）：'T_pole_L' → 'TP_L'，'I_pole_L' → 'I_L_pole'"""
    parts = pole_short.split("_pole_")
    if len(parts) != 2:
        return None
    prefix, hand = parts
    if prefix == "T":
        return f"TP_{hand}"
    return f"{prefix}_{hand}_pole"


def _resolve_pole_obj(cfg, pole_short: str):
    """按新名查找 pole 物体；找不到时回退旧命名并把物体改名为新名（幂等迁移）"""
    full = cfg.obj_name(pole_short)
    obj = bpy.data.objects.get(full)
    if obj is not None:
        return obj
    old_short = _old_pole_short(pole_short)
    if old_short:
        old_full = cfg.obj_name(old_short)
        old_obj = bpy.data.objects.get(old_full)
        if old_obj is not None:
            old_obj.name = full
            print(f"  [迁移] pole 控件 {old_full} → {full}")
            return old_obj
    return None


# ── 导出 ──────────────────────────────────────────────────────

def export_drummer(file_path: str, skeleton, drumkit_dict: dict,
                   for_unreal: bool = False) -> None:
    """从骨骼 JSON 导出 .drummer 文件（兼容原扁平格式）

    for_unreal=True 时坐标转换为 Unreal 空间，is_unreal 字段随之置 True。
    """
    _pos = io_utils.to_unreal_position if for_unreal else (lambda p: p)
    _rot = io_utils.to_unreal_rotation if for_unreal else (lambda r: r)

    state_data = _get_state(skeleton)

    recorder_info = {}
    mapping_helpers_out = {}

    all_components = (drumkit_dict.get("components", [])
                      + drumkit_dict.get("special_actions", []))

    for comp in all_components:
        comp_name = comp["name"]
        comp_states = state_data.get(comp_name, {})

        for state_name, ctrl_map in comp_states.items():
            for short, ctrl_data in ctrl_map.items():
                if short == "Head_Control":
                    key = f"{comp_name}_{state_name}_Head_Control"
                    recorder_info[key] = {
                        "location": _pos(ctrl_data.get("location", [0, 0, 0]))}
                else:
                    key = f"{comp_name}_{state_name}_{short}"
                    recorder_info[key] = {
                        "location": _pos(ctrl_data.get("location", [0, 0, 0])),
                        "rotation_quaternion": _rot(ctrl_data.get("rotation", [1, 0, 0, 0])),
                        "rotation_mode": "QUATERNION",
                    }

    # rest 状态（原 H_Rest_L / H_Rest_R 等扁平键）
    rest_map = state_data.get("rest", {})
    _REST_KEY_MAP = {
        "H_L":          "H_Rest_L",
        "HP_L":         "HP_Rest_L",
        "H_R":          "H_Rest_R",
        "HP_R":         "HP_Rest_R",
    }
    for short, flat_key in _REST_KEY_MAP.items():
        if short in rest_map:
            recorder_info[flat_key] = {
                "location": _pos(rest_map[short].get("location", [0, 0, 0])),
                "rotation_quaternion": _rot(rest_map[short].get("rotation", [1, 0, 0, 0])),
                "rotation_mode": "QUATERNION",
            }
    if "Head_Control" in rest_map:
        recorder_info["Head_Control_Rest"] = {
            "location": _pos(rest_map["Head_Control"].get("location", [0, 0, 0]))
        }

    # mapping_helpers
    helpers = state_data.get("mapping_helpers", {})
    for key in ("A", "B", "C", "D"):
        entry = helpers.get(key, {})
        if "Middle_Hand" in entry:
            mapping_helpers_out[f"Middle_Hand_{key}"] = {
                "location": _pos(entry["Middle_Hand"])}
        if "Head_Control" in entry:
            mapping_helpers_out[f"Head_Control_{key}"] = {
                "location": _pos(entry["Head_Control"])}
        if "H_L" in entry:
            mapping_helpers_out[f"Left_Hand_{key}"] = {
                "location": _pos(entry["H_L"].get("location", [0, 0, 0])),
                "rotation_quaternion": _rot(entry["H_L"].get("rotation", [1, 0, 0, 0])),
            }
        if "H_R" in entry:
            mapping_helpers_out[f"Right_Hand_{key}"] = {
                "location": _pos(entry["H_R"].get("location", [0, 0, 0])),
                "rotation_quaternion": _rot(entry["H_R"].get("rotation", [1, 0, 0, 0])),
            }

    export_data = {
        "is_unreal": for_unreal,
        "RECORDER_INFO": recorder_info,
        "MAPPING_HELPERS": mapping_helpers_out,
    }

    # pole_controller：挂在 ext 下的手指 pole 控件局部位置（短名键）
    suffix = performer_utils.suffix_from_object(skeleton) or ""
    cfg = BeatBloomConfig(performer_suffix=suffix)
    pole_controllers = {}
    pole_shorts = cfg.get_pole_controller_shorts()
    pole_found = 0
    for pole_short in pole_shorts:
        obj = _resolve_pole_obj(cfg, pole_short)
        if obj is not None:
            pole_controllers[pole_short] = {
                "location": _pos([obj.location.x, obj.location.y, obj.location.z]),
            }
            pole_found += 1
        else:
            print(f"  • pole 控件 {cfg.obj_name(pole_short)} 不存在，跳过（请先 Setup 创建）")
    export_data["pole_controller"] = pole_controllers
    print(f"  • pole 控件：{pole_found}/{len(pole_shorts)} 个")

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    print(f"✓ 导出 {len(recorder_info)} 条记录器信息 → {file_path}")


# ── 导入 ──────────────────────────────────────────────────────

def import_drummer(file_path: str, skeleton, drumkit_dict: dict) -> None:
    """从 .drummer 文件导入，填回骨骼自定义属性 beat_bloom_state_data"""
    with open(file_path, "r", encoding="utf-8") as f:
        import_data = json.load(f)

    if "RECORDER_INFO" not in import_data or "MAPPING_HELPERS" not in import_data:
        raise ValueError("文件格式不正确，缺少 RECORDER_INFO 或 MAPPING_HELPERS 字段")

    recorder_info = import_data["RECORDER_INFO"]
    mapping_helpers_in = import_data["MAPPING_HELPERS"]

    state_data = _get_state(skeleton)

    all_components = (drumkit_dict.get("components", [])
                      + drumkit_dict.get("special_actions", []))
    component_names = {c["name"] for c in all_components}

    # 解析 RECORDER_INFO
    for flat_key, ctrl_data in recorder_info.items():
        # rest 状态（固定键）
        rest_reverse = {
            "H_Rest_L":          ("rest", "H_L"),
            "HP_Rest_L":         ("rest", "HP_L"),
            "H_Rest_R":          ("rest", "H_R"),
            "HP_Rest_R":         ("rest", "HP_R"),
            "Head_Control_Rest": ("rest", "Head_Control"),
        }
        if flat_key in rest_reverse:
            section, short = rest_reverse[flat_key]
            rest_entry = state_data.setdefault(section, {})
            if short == "Head_Control":
                rest_entry[short] = {
                    "location": ctrl_data.get("location", [0, 0, 0])}
            else:
                rest_entry[short] = {
                    "location": ctrl_data.get("location", [0, 0, 0]),
                    "rotation": ctrl_data.get("rotation_quaternion", [1, 0, 0, 0]),
                }
            continue

        # 普通 component_state_ctrl 格式：贪心匹配最长 component 名
        matched = None
        for comp_name in component_names:
            prefix = comp_name + "_"
            if flat_key.startswith(prefix):
                rest_str = flat_key[len(prefix):]
                # rest_str 形如 "beat_H_R" 或 "beat_Head_Control"
                parts = rest_str.split("_", 1)
                if len(parts) == 2:
                    state_name, short = parts[0], parts[1]
                    matched = (comp_name, state_name, short)
                    break

        if matched is None:
            continue

        comp_name, state_name, short = matched
        comp_entry = state_data.setdefault(comp_name, {})
        state_entry = comp_entry.setdefault(state_name, {})

        if short == "Head_Control":
            state_entry[short] = {
                "location": ctrl_data.get("location", [0, 0, 0])}
        else:
            state_entry[short] = {
                "location": ctrl_data.get("location", [0, 0, 0]),
                "rotation": ctrl_data.get("rotation_quaternion", [1, 0, 0, 0]),
            }

    # 解析 MAPPING_HELPERS
    helpers = state_data.setdefault("mapping_helpers", {})
    for key in ("A", "B", "C", "D"):
        entry = helpers.setdefault(key, {})
        mh_key = f"Middle_Hand_{key}"
        hc_key = f"Head_Control_{key}"
        lh_key = f"Left_Hand_{key}"
        rh_key = f"Right_Hand_{key}"

        if mh_key in mapping_helpers_in:
            entry["Middle_Hand"] = mapping_helpers_in[mh_key].get("location", [
                                                                  0, 0, 0])
        if hc_key in mapping_helpers_in:
            entry["Head_Control"] = mapping_helpers_in[hc_key].get("location", [
                                                                   0, 0, 0])
        if lh_key in mapping_helpers_in:
            d = mapping_helpers_in[lh_key]
            entry["H_L"] = {
                "location": d.get("location", [0, 0, 0]),
                "rotation": d.get("rotation_quaternion", [1, 0, 0, 0]),
            }
        if rh_key in mapping_helpers_in:
            d = mapping_helpers_in[rh_key]
            entry["H_R"] = {
                "location": d.get("location", [0, 0, 0]),
                "rotation": d.get("rotation_quaternion", [1, 0, 0, 0]),
            }

    _set_state(skeleton, state_data)

    # pole_controller → 应用局部位置到对应 pole 控件
    suffix = performer_utils.suffix_from_object(skeleton) or ""
    cfg = BeatBloomConfig(performer_suffix=suffix)
    pole_data = import_data.get("pole_controller", {})
    for pole_short, pole_info in pole_data.items():
        obj = _resolve_pole_obj(cfg, pole_short)
        if obj is None:
            print(f"  • pole 控件 {cfg.obj_name(pole_short)} 不存在，跳过")
            continue
        loc = pole_info.get("location")
        if loc:
            obj.location = loc
            print(f"  ✓ 设置 {obj.name} 位置: {loc}")

    print(f"✓ 导入完成：{len(recorder_info)} 条记录器信息 ← {file_path}")
