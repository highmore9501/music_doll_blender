# bellows_pulse/state.py
"""BellowsPulse 乐器模块 —— 设置与状态存取

两个骨骼自定义属性键（都存演奏者骨骼上，随角色复制/重命名一起走）：

- `bellows_pulse_settings`：**乐器属性**。右手是键盘还是按钮、音域 / 排数 / 键数、
  左手排数…，由面板的「保存乐器属性到骨骼」写入；后续导出 `.accordion` 与生成动画
  一律读这里，不读面板（避免没保存的修改悄悄进入产物）。
- `bellows_pulse_state_data`：**基准手型**（动画阶段用）。左右手各一份控制器位姿：
  手掌 `H_*` 与手部枢轴 `HP_*` 存位置 + 旋转，五指存位置。
  ext / Mid_Hand / Look_At / Head_Control 由 driver 与约束驱动，不存。

数据键一律用**短名**（无演奏者后缀），场景控件才用带后缀的完整名——
这样不同演奏者的骨骼数据结构完全一致。
"""

import copy

import bpy  # type: ignore

from ..common import performer_utils
from ..common import state_io as _sio

from .enums import (
    FINGER_BASES,
    RIGHT_LAYOUT_KEYBOARD,
    RIGHT_LAYOUTS,
)

#: 乐器属性的骨骼属性键
SETTINGS_KEY = "bellows_pulse_settings"

#: 基准手型的骨骼属性键
STATE_KEY = "bellows_pulse_state_data"

#: 面板默认值（也是骨骼上还没有数据时读到的东西）
DEFAULT_SETTINGS = {
    "version": 1,
    "right": {
        "layout": RIGHT_LAYOUT_KEYBOARD,
        "min_note": 48,
        "max_note": 84,
        "anchor_note": 48,
        "first_row_keys": 14,
        "stagger": 0.5,
    },
    "left": {
        "rows": 6,
        "keys_per_row": 20,
        "first_main_bass": 36,
        "stagger": 0.5,
    },
    "left_instrument": "",
}


# ── 乐器属性：默认值 / 读 / 写 / 校验 ──────────────────────────

def _as_int(raw_value, default: int) -> int:
    """宽松取整数（JSON 里可能写成浮点）"""
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _as_float(raw_value, default: float) -> float:
    """宽松取浮点"""
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def default_settings() -> dict:
    """默认乐器属性（深拷贝，避免调用方改到常量）"""
    return copy.deepcopy(DEFAULT_SETTINGS)


def _merge_settings(base: dict, stored: dict) -> dict:
    """把骨骼里读到的设置合并到默认值上（缺项用默认值补齐）"""
    merged = copy.deepcopy(base)
    for stored_key, stored_value in (stored or {}).items():
        if isinstance(stored_value, dict) and isinstance(merged.get(stored_key), dict):
            merged[stored_key] = _merge_settings(
                merged[stored_key], stored_value)
        else:
            merged[stored_key] = stored_value
    return merged


def has_settings(skeleton) -> bool:
    """骨骼上是否已经保存过乐器属性"""
    if skeleton is None:
        return False
    raw = skeleton.get(SETTINGS_KEY)
    return bool(raw)


def load_settings(skeleton) -> dict:
    """读乐器属性（骨骼上没有数据时返回默认值）"""
    if skeleton is None:
        return default_settings()
    stored = _sio.get_state_data(skeleton, SETTINGS_KEY, None)
    return _merge_settings(DEFAULT_SETTINGS, stored or {})


def save_settings(skeleton, settings: dict) -> bool:
    """把乐器属性写回骨骼（调用方负责先校验）"""
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法保存乐器属性")
        return False
    _sio.set_state_data(skeleton, SETTINGS_KEY, normalize_settings(settings))
    print(f"  ✓ 乐器属性已写入骨骼 {skeleton.name}")
    return True


def normalize_settings(settings: dict) -> dict:
    """把设置整理成固定结构（补齐字段、统一类型、浮点四舍五入）

    面板与骨骼比较、写盘、导出都用同一份整理结果，避免浮点尾巴导致
    "看起来一样却判定为有未保存修改"。
    """
    right = (settings or {}).get("right") or {}
    left = (settings or {}).get("left") or {}
    return {
        "version": _as_int((settings or {}).get("version"), 1),
        "right": {
            "layout": str(right.get("layout", RIGHT_LAYOUT_KEYBOARD)),
            "min_note": _as_int(right.get("min_note"), 0),
            "max_note": _as_int(right.get("max_note"), 0),
            "anchor_note": _as_int(right.get("anchor_note"), 0),
            "first_row_keys": _as_int(right.get("first_row_keys"), 0),
            "stagger": round(_as_float(right.get("stagger"), 0.0), 4),
        },
        "left": {
            "rows": _as_int(left.get("rows"), 0),
            "keys_per_row": _as_int(left.get("keys_per_row"), 0),
            "first_main_bass": _as_int(left.get("first_main_bass"), 0),
            "stagger": round(_as_float(left.get("stagger"), 0.0), 4),
        },
        "left_instrument": str((settings or {}).get("left_instrument", "") or ""),
    }


def settings_equal(first: dict, second: dict) -> bool:
    """两份设置是否等价（浮点按 4 位小数比较）"""
    return normalize_settings(first) == normalize_settings(second)


def validate_settings(settings: dict) -> list[tuple[str, tuple]]:
    """校验乐器属性，返回 [(提示文本键, 格式化参数), ...]；空列表表示合法。

    提示文本用"中文原文作键 + T() 翻译"的方式，返回元组让面板负责翻译，
    校验层自己不依赖 i18n。
    """
    errors: list[tuple[str, tuple]] = []
    right = (settings or {}).get("right") or {}
    left = (settings or {}).get("left") or {}

    layout = right.get("layout")
    if layout not in RIGHT_LAYOUTS:
        errors.append(("右手键区类型无效：%s", (layout,)))
    elif layout == RIGHT_LAYOUT_KEYBOARD:
        min_note = _as_int(right.get("min_note"), 0)
        max_note = _as_int(right.get("max_note"), 0)
        if min_note > max_note:
            errors.append(("右键区最低音不能大于最高音", ()))
        if not 0 <= min_note <= 127:
            errors.append(("右键区最低音超出 midi 范围（0~127）：%d", (min_note,)))
        if not 0 <= max_note <= 127:
            errors.append(("右键区最高音超出 midi 范围（0~127）：%d", (max_note,)))
    else:
        anchor_note = _as_int(right.get("anchor_note"), 0)
        first_row_keys = _as_int(right.get("first_row_keys"), 0)
        if not 0 <= anchor_note <= 127:
            errors.append(("右手第 3 排最低音超出 midi 范围（0~127）：%d", (anchor_note,)))
        if first_row_keys < 2:
            errors.append(("右手第 1/3/5 排按钮数至少为 2", ()))

    rows = _as_int(left.get("rows"), 0)
    keys_per_row = _as_int(left.get("keys_per_row"), 0)
    first_main_bass = _as_int(left.get("first_main_bass"), 0)
    if not 3 <= rows <= 6:
        errors.append(("左手排数必须在 3~6 之间：%d", (rows,)))
    if keys_per_row < 1:
        errors.append(("左手每排按钮数至少为 1", ()))
    if not 0 <= first_main_bass <= 127:
        errors.append(("左手第 2 排最低音超出 midi 范围（0~127）：%d", (first_main_bass,)))

    return errors


# ── 左键区 mesh（存短名，重命名/复制角色不用改数据）────────────

def short_name_of_object(obj, suffix: str = "") -> str:
    """对象名 → 短名（去掉演奏者后缀）；没有后缀时原样返回"""
    if obj is None:
        return ""
    full_name = obj.name
    if suffix:
        marker = f"_{suffix}"
        if full_name.endswith(marker):
            return full_name[: -len(marker)]
    return full_name


def resolve_left_instrument(short: str, suffix: str = ""):
    """短名 → 场景里的网格对象；优先按「短名 + 后缀」解析，找不到再退回原名。"""
    if not short:
        return None
    candidates = []
    if suffix:
        candidates.append(performer_utils.resolve(short, suffix))
    candidates.append(short)
    for candidate in candidates:
        obj = bpy.data.objects.get(candidate)
        if obj is not None and obj.type == 'MESH':
            return obj
    return None


# ── 基准手型（动画阶段用）──────────────────────────────────────

def hand_controller_shorts(hand: str) -> list[str]:
    """一只手里要记录进基准手型的控制器短名：手掌、手部枢轴、五指"""
    shorts = [f"H_{hand}", f"HP_{hand}"]
    shorts.extend(f"{base}_{hand}" for base in FINGER_BASES)
    return shorts


def _hand_key(hand: str) -> str:
    return "left" if hand == "L" else "right"


def _reference_data(skeleton) -> dict:
    return _sio.get_state_data(skeleton, STATE_KEY, {}) or {}


def save_reference_hand(config, skeleton, hand: str) -> int:
    """把当前一只手的控制器位姿存成基准手型，返回写入的控制器数量。"""
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法保存基准手型")
        return 0

    controllers = {}
    for short in hand_controller_shorts(hand):
        ctrl_obj = bpy.data.objects.get(config.obj_name(short))
        if ctrl_obj is None:
            continue
        _sio.copy_transfer_between_object_and_dict(
            ctrl_obj, controllers, "set", key=short)

    state_data = _reference_data(skeleton)
    state_data.setdefault("reference_hand", {})[_hand_key(hand)] = controllers
    _sio.set_state_data(skeleton, STATE_KEY, state_data)

    print(f"  ✓ 已保存{'左' if hand == 'L' else '右'}手基准手型"
          f"（{len(controllers)} 个控制器）")
    return len(controllers)


def load_reference_hand(config, skeleton, hand: str) -> int:
    """把骨骼里的基准手型应用到一只手的控制器，返回应用的控制器数量。

    没有数据时抛 ValueError，由面板转成界面提示。
    """
    state_data = _reference_data(skeleton)
    controllers = (state_data.get("reference_hand") or {}).get(_hand_key(hand)) or {}
    if not controllers:
        raise ValueError("骨骼上还没有这只手的基准手型，请先保存")

    applied = 0
    for short in hand_controller_shorts(hand):
        ctrl_obj = bpy.data.objects.get(config.obj_name(short))
        if ctrl_obj is None or short not in controllers:
            continue
        _sio.copy_transfer_between_object_and_dict(
            ctrl_obj, controllers, "load", key=short)
        applied += 1

    print(f"  ✓ 已加载{'左' if hand == 'L' else '右'}手基准手型（{applied} 个控制器）")
    return applied


def reference_hand_saved(skeleton, hand: str) -> bool:
    """骨骼上是否已保存该手的基准手型"""
    if skeleton is None:
        return False
    state_data = _reference_data(skeleton)
    controllers = (state_data.get("reference_hand") or {}).get(_hand_key(hand)) or {}
    return bool(controllers)
