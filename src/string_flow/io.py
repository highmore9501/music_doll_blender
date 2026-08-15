# string_flow/io.py
"""StringFlow 乐器模块 —— .violinist 导入导出（迁移自 string_flow_blender/string_flow.py）

导出结构与 Rust 端（Animator）消费格式完全兼容（字节级）：
- 顶层键：config / left_finger_recorders / left_hand_position_recorders /
  left_thumb_position_recorders / right_hand_position_recorders /
  right_thumb_position_recorders / right_finger_recorders / other_recorders；
- 每条记录器：{location, rotation_mode, rotation_quaternion}
  （Rust 只读 location 与 rotation_quaternion，务必保留四元数格式）；
- 例外：bow_position_* 只写 location（Bow 旋转已停采，回放时由指向约束实时决定，Rust 端不读）；
- JSON 键一律短名（无演奏者后缀），仅 Blender 内对象查找用带后缀名。

数据来源：
- 状态记录器（左右手 + bow/stp）从骨骼 string_flow_state_data 读取，缺失键补默认
  （等价原版"对象存在但从未 Set，位于原点"）；
- 物理位置标记（position_s{i}_f0/f12、mid_s{i}、f9_s{i}、middle_fret_board_position）
  从对象读取。

for_unreal=True 时坐标/旋转做 Unreal 转换（复用 common.io_utils），config.is_unreal=true。
"""

import json
import os
import re
from collections import defaultdict

import bpy  # type: ignore
from mathutils import Euler  # type: ignore

from ..common import io_utils
from ..common import state_io as _sio

from .state import STATE_KEY


def _nested_dict():
    return defaultdict(_nested_dict)


# ── recorder 名解析（短名 → 骨骼定位） ──────────────────────

_LEFT_FINGER_RE = re.compile(r"^p_s(\d)_f(\d+)_(\d+)_L_(\w+)$")
_LEFT_HAND_RE = re.compile(r"^(H_L|HP_L)_s(\d)_f(\d+)_(\w+)$")
_LEFT_THUMB_RE = re.compile(r"^(T_L)_s(\d)_f(\d+)_(\w+)$")
_RIGHT_HAND_RE = re.compile(r"^(H_R|HP_R)_(\w+)_s(\d)$")
_RIGHT_THUMB_RE = re.compile(r"^(T_R)_(\w+)_s(\d)$")
_RIGHT_FINGER_RE = re.compile(r"^p_s(\d)_(\d+)_R_(\w+)$")
_STP_RE = re.compile(r"^stp_(\d)_(\w+)$")
_BOW_RE = re.compile(r"^bow_position_s(\d)_(\w+)$")


def _parse_recorder(name):
    """解析 recorder 名 → (side, string_idx, fret_idx|None, pos_key, controller_short)。

    左右手命名规则（与原版生成规则一致）：
    - 左手：p_s{i}_f{j}_{finger}_L_{pos} / {H_L|HP_L}_s{i}_f{j}_{pos} / T_L_s{i}_f{j}_{pos}
    - 右手：p_s{i}_{finger}_R_{pos} / {H_R|HP_R}_{pos}_s{i} / T_R_{pos}_s{i}
    - other：stp_{i}_{pos}（→ String_Touch_Point）/ bow_position_s{i}_{pos}（→ Bow_Controller）
    """
    m = _LEFT_FINGER_RE.match(name)
    if m:
        return ("left", int(m.group(1)), int(m.group(2)),
                m.group(4), f"{m.group(3)}_L")
    m = _LEFT_HAND_RE.match(name)
    if m:
        return ("left", int(m.group(2)), int(m.group(3)),
                m.group(4), m.group(1))
    m = _LEFT_THUMB_RE.match(name)
    if m:
        return ("left", int(m.group(2)), int(m.group(3)),
                m.group(4), m.group(1))
    m = _RIGHT_HAND_RE.match(name)
    if m:
        return ("right", int(m.group(3)), None, m.group(2), m.group(1))
    m = _RIGHT_THUMB_RE.match(name)
    if m:
        return ("right", int(m.group(3)), None, m.group(2), m.group(1))
    m = _RIGHT_FINGER_RE.match(name)
    if m:
        return ("right", int(m.group(1)), None, m.group(3),
                f"{m.group(2)}_R")
    m = _STP_RE.match(name)
    if m:
        return ("right", int(m.group(1)), None, m.group(2),
                "String_Touch_Point")
    m = _BOW_RE.match(name)
    if m:
        return ("right", int(m.group(1)), None, m.group(2),
                "Bow_Controller")
    return None


def _lookup_state_entry(state: dict, parsed) -> dict | None:
    """从骨骼 state 按 (side, string, fret, pos, ctrl) 反查条目"""
    side, s, fret, pos, ctrl = parsed
    side_data = state.get("left_hand" if side == "left" else "right_hand", {})
    s_data = side_data.get(f"string_{s}", {})
    if fret is not None:
        slot = s_data.get(f"fret_{fret}", {}).get(pos, {})
    else:
        slot = s_data.get(pos, {})
    return slot.get(ctrl)


# ── 条目构造 ─────────────────────────────────────────────────

def _default_entry(_pos, _rot) -> dict:
    """缺失状态键的默认条目（等价原版"对象存在但从未 Set，位于原点"）"""
    return {
        "location": _pos([0, 0, 0]),
        "rotation_mode": "QUATERNION",
        "rotation_quaternion": _rot([1, 0, 0, 0]),
    }


def _state_entry(state: dict, recorder_name: str, _pos, _rot) -> dict:
    """按 recorder 名从骨骼取条目（缺失补默认）"""
    parsed = _parse_recorder(recorder_name)
    entry = _lookup_state_entry(state, parsed) if parsed else None
    if entry is not None:
        loc = _pos(entry.get("location", [0, 0, 0]))
        rot = _rot(entry.get("rotation", [1, 0, 0, 0]))
        return {
            "location": loc,
            "rotation_mode": "QUATERNION",
            "rotation_quaternion": rot,
        }
    return _default_entry(_pos, _rot)


def _state_entry_location_only(state: dict, recorder_name: str, _pos) -> dict:
    """按 recorder 名从骨骼取条目，只导出 location（Bow 旋转已停采；缺失补默认原点）"""
    parsed = _parse_recorder(recorder_name)
    entry = _lookup_state_entry(state, parsed) if parsed else None
    if entry is not None:
        return {"location": _pos(entry.get("location", [0, 0, 0]))}
    return {"location": _pos([0, 0, 0])}


def _object_entry(obj, _pos, _rot) -> dict:
    """从对象读条目（对齐原版导出：按旋转模式写四元数或欧拉）"""
    loc = _pos([obj.location.x, obj.location.y, obj.location.z])
    if obj.rotation_mode == 'QUATERNION':
        q = obj.rotation_quaternion
        return {
            "location": loc,
            "rotation_mode": "QUATERNION",
            "rotation_quaternion": _rot([q.w, q.x, q.y, q.z]),
        }
    e = obj.rotation_euler
    return {
        "location": loc,
        "rotation_mode": obj.rotation_mode,
        "rotation_euler": [e.x, e.y, e.z],
    }


def _extract_rotation(rec_info: dict) -> list:
    """从文件条目提取四元数 [w,x,y,z]（优先 rotation_quaternion，否则欧拉转四元数）"""
    quat = rec_info.get("rotation_quaternion")
    if quat and len(quat) == 4:
        return list(quat)
    euler = rec_info.get("rotation_euler")
    if euler and len(euler) == 3:
        q = Euler((euler[0], euler[1], euler[2])).to_quaternion()
        return [q.w, q.x, q.y, q.z]
    return [1, 0, 0, 0]


# ── 导出 ─────────────────────────────────────────────────────

# 状态记录器节（从骨骼读）
_STATE_SECTIONS = [
    "left_finger_recorders",
    "left_hand_position_recorders",
    "left_thumb_position_recorders",
    "right_hand_position_recorders",
    "right_thumb_position_recorders",
    "right_finger_recorders",
]


def _old_pole_short(pole_short: str) -> str | None:
    """新 pole 短名 → 旧命名短名（一次性迁移）：'pole_1_L' → '1_L_pole'，'TP_L' → 'T_L_pole'"""
    if pole_short.startswith("TP_"):
        return f"T_{pole_short[3:]}_pole"
    if pole_short.startswith("pole_"):
        return f"{pole_short[5:]}_pole"
    return None


def _resolve_pole_obj(config, pole_short: str):
    """按新名查找 pole 物体；找不到时回退旧命名并把物体改名为新名（幂等迁移）"""
    full = config.obj_name(pole_short)
    obj = bpy.data.objects.get(full)
    if obj is not None:
        return obj
    old_short = _old_pole_short(pole_short)
    if old_short:
        old_full = config.obj_name(old_short)
        old_obj = bpy.data.objects.get(old_full)
        if old_obj is not None:
            old_obj.name = full
            print(f"  [迁移] pole 控件 {old_full} → {full}")
            return old_obj
    return None


def export_recorder_info(file_path: str, config, skeleton,
                         for_unreal: bool = False) -> None:
    """导出所有记录器信息到 .violinist JSON 文件（与原版结构完全兼容）。

    :param for_unreal: True 时坐标/旋转做 Unreal 转换（Y 取反 + 旋转反射共轭），
        config.is_unreal 随之置 True；普通导出为恒等变换、不写 is_unreal。
    """
    _pos = io_utils.to_unreal_position if for_unreal else (lambda p: p)
    _rot = io_utils.to_unreal_rotation if for_unreal else (lambda r: r)

    print("\n开始导出记录器信息...")
    print(f"目标文件：{file_path}")

    result = _nested_dict()

    # 配置参数
    result['config']['one_hand_finger_number'] = config.one_hand_finger_number
    result['config']['string_number'] = config.string_number
    if for_unreal:
        result['config']['is_unreal'] = True

    # 状态记录器（从骨骼读；缺失补默认条目）
    state = _sio.get_state_data(skeleton, STATE_KEY, {}) or {}
    state_count = 0
    for section in _STATE_SECTIONS:
        for recorder_name in getattr(config, section):
            result[section][recorder_name] = _state_entry(
                state, recorder_name, _pos, _rot)
            state_count += 1

    # other_recorders：物理标记从对象读；bow/stp 从骨骼读
    marker_count = 0
    for recorder_name in config.other_recorders:
        if _STP_RE.match(recorder_name):
            result['other_recorders'][recorder_name] = _state_entry(
                state, recorder_name, _pos, _rot)
            state_count += 1
            continue
        if _BOW_RE.match(recorder_name):
            # Bow 旋转已停采（回放时由指向约束实时决定，Rust 端不读，见施工计划 D4），
            # 只导出位置
            result['other_recorders'][recorder_name] = _state_entry_location_only(
                state, recorder_name, _pos)
            state_count += 1
            continue
        full = config.obj_name(recorder_name)
        obj = bpy.data.objects.get(full)
        if obj is not None:
            result['other_recorders'][recorder_name] = _object_entry(
                obj, _pos, _rot)
            marker_count += 1
        else:
            # 与原版一致：物理标记对象不存在时写 None（提醒先 Setup）
            result['other_recorders'][recorder_name] = None

    # pole_controller：手指 pole（挂在 ext 下）的局部位置，短名键
    pole_controllers = {}
    pole_shorts = config.get_pole_controller_names()
    pole_found = 0
    for pole_short in pole_shorts:
        obj = _resolve_pole_obj(config, pole_short)
        if obj is not None:
            pole_controllers[pole_short] = {
                "location": _pos([obj.location.x, obj.location.y, obj.location.z]),
            }
            pole_found += 1
        else:
            print(f"  • pole 控件 {config.obj_name(pole_short)} 不存在，跳过（请先 Setup 创建）")
    result['pole_controller'] = pole_controllers

    # 写入文件
    io_utils.save_json(file_path, dict(result))

    print("=" * 60)
    print("✓ 记录器信息导出成功!")
    print("=" * 60)
    print(f" • 状态记录器：{state_count} 条")
    print(f" • 物理位置标记：{marker_count} 个")
    print(f" • pole 控件：{pole_found}/{len(pole_shorts)} 个")
    print(f" • 格式：{'Unreal（Y 取反 + 旋转反射共轭）' if for_unreal else 'Blender 原生'}")
    print(f" • 文件路径：{file_path}")
    print("=" * 60)


# ── 导入 ─────────────────────────────────────────────────────


def _write_state_entry(state: dict, parsed, entry: dict) -> None:
    """把条目写入骨骼 state（按 (side, string, fret, pos, ctrl) 定位）"""
    side, s, fret, pos, ctrl = parsed
    side_data = state.setdefault(
        "left_hand" if side == "left" else "right_hand", {})
    s_data = side_data.setdefault(f"string_{s}", {})
    if fret is not None:
        slot = s_data.setdefault(f"fret_{fret}", {}).setdefault(pos, {})
    else:
        slot = s_data.setdefault(pos, {})
    slot[ctrl] = entry


def import_recorder_info(file_path: str, config, skeleton) -> bool:
    """从 .violinist JSON 文件导入记录器信息。

    - 状态记录器写入骨骼 string_flow_state_data（之后用 Load 应用到控制器）；
    - 物理位置标记写回对象（对象名按演奏者后缀解析）。
    """
    print("\n开始导入记录器信息...")
    print(f"源文件：{file_path}")

    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"找不到文件：{file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        state = _sio.get_state_data(skeleton, STATE_KEY, {}) or {}
        loaded_count = 0

        # 状态记录器节 → 骨骼
        for section in _STATE_SECTIONS:
            section_data = data.get(section, {})
            for recorder_name, rec_info in section_data.items():
                if rec_info is None:
                    print(f"  - 跳过 {recorder_name} (源数据中为None)")
                    continue
                parsed = _parse_recorder(recorder_name)
                if parsed is None:
                    print(f"  - 跳过无法识别的记录器 {recorder_name}")
                    continue
                entry = {
                    "location": rec_info.get("location", [0, 0, 0]),
                    "rotation": _extract_rotation(rec_info),
                }
                _write_state_entry(state, parsed, entry)
                loaded_count += 1

        # other_recorders：物理标记 → 对象；bow/stp → 骨骼
        other = data.get("other_recorders", {})
        for recorder_name, rec_info in other.items():
            if rec_info is None:
                continue
            if _STP_RE.match(recorder_name):
                parsed = _parse_recorder(recorder_name)
                if parsed is not None:
                    entry = {
                        "location": rec_info.get("location", [0, 0, 0]),
                        "rotation": _extract_rotation(rec_info),
                    }
                    _write_state_entry(state, parsed, entry)
                    loaded_count += 1
                continue
            if _BOW_RE.match(recorder_name):
                # Bow 旋转已停采：只导入位置，不写 rotation（加载时不动 Bow 旋转）
                parsed = _parse_recorder(recorder_name)
                if parsed is not None:
                    entry = {
                        "location": rec_info.get("location", [0, 0, 0]),
                    }
                    _write_state_entry(state, parsed, entry)
                    loaded_count += 1
                continue
            # 物理位置标记：写回对象（短名 → 带后缀查找）
            full = config.obj_name(recorder_name)
            obj = bpy.data.objects.get(full)
            if obj is None:
                print(f"  ✗ 跳过 {recorder_name} (对象不存在)")
                continue
            loc = rec_info.get("location")
            if loc:
                obj.location = (loc[0], loc[1], loc[2])
            quat = rec_info.get("rotation_quaternion")
            if quat and len(quat) == 4:
                obj.rotation_quaternion = (quat[0], quat[1], quat[2], quat[3])
            loaded_count += 1

        # pole_controller：应用局部位置到对应 pole 控件
        pole_data = data.get("pole_controller", {})
        for pole_short, pole_info in pole_data.items():
            obj = _resolve_pole_obj(config, pole_short)
            if obj is None:
                print(f"  ✗ 跳过 {pole_short} (pole 控件不存在)")
                continue
            loc = pole_info.get("location")
            if loc:
                obj.location = (loc[0], loc[1], loc[2])

        _sio.set_state_data(skeleton, STATE_KEY, state)

        print("=" * 60)
        print("✓ 记录器信息导入成功!")
        print("=" * 60)
        print(f" • 共导入 {loaded_count} 条（状态写骨骼，物理标记写对象）")
        print(f" • 文件路径：{file_path}")
        print("=" * 60)
        return True

    except FileNotFoundError as e:
        print(f"\n✗ 错误：{e}")
        return False
    except json.JSONDecodeError as e:
        print(f"\n✗ JSON 格式错误：{e}")
        return False
    except Exception as e:
        print(f"\n✗ 导入过程中发生错误：{e}")
        import traceback
        traceback.print_exc()
        return False
