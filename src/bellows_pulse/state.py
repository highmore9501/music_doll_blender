# bellows_pulse/state.py
"""BellowsPulse 乐器模块 —— 设置与状态存取

两个骨骼自定义属性键（都存演奏者骨骼上，随角色复制/重命名一起走）：

- `bellows_pulse_settings`：**乐器属性**。右手是键盘还是按钮、音域 / 排数 / 键数、
  左手排数…，由面板的「保存乐器属性到骨骼」写入；后续导出 `.accordion` 与生成动画
  一律读这里，不读面板（避免没保存的修改悄悄进入产物）。
- `bellows_pulse_state_data`：**基准手型**与**枢轴姿态**（动画阶段用）。
  基准手型：左右手各有两格（`low` 低位 / `high` 高位）的控制器位姿，手掌 `H_*` 与手部枢轴
  `HP_*` 存位置 + 旋转，五指只存位置；枢轴姿态：风箱「打开」「合拢」两种状态下，
  `pivot_left` / `pivot_right` 的位置 + 旋转（`accordion_pivot` 是静态极向，不采样）。
  ext 由 driver 与约束驱动，不存；骨骼跟随器与 hand_back 也不是位姿数据。

数据键一律用**短名**（无演奏者后缀），场景控件才用带后缀的完整名——
这样不同演奏者的骨骼数据结构完全一致。
"""

import copy

import bpy  # type: ignore

from ..common import performer_utils
from ..common import state_io as _sio

from .enums import (
    FINGER_BASES,
    HAND_POSE_LABELS,
    HAND_POSES,
    PIVOT_POSES,
    PIVOT_SHORTS,
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
#
# 一只手的基准手型存两格：
#
# - `low`（低位）：手指按在按钮上的演奏姿态，按下时的手指取它的形状；
# - `high`（高位）：手指放松的休息姿态，闲置与离键的手指取它的形状。
#
# 两格各自独立覆盖，互不影响——采完低位再采高位不会把低位顶掉。

def hand_controller_shorts(hand: str) -> list[str]:
    """一只手里要记录进基准手型的控制器短名：手掌、手部枢轴、五指"""
    shorts = [f"H_{hand}", f"HP_{hand}"]
    shorts.extend(f"{base}_{hand}" for base in FINGER_BASES)
    return shorts


def _hand_key(hand: str) -> str:
    return "left" if hand == "L" else "right"


def _is_finger_short(short: str) -> bool:
    """这个短名是不是五指控制器（`I_L` 这种）；`H_L` / `HP_L` 不是"""
    return short.split("_")[0] in FINGER_BASES


def _reference_data(skeleton) -> dict:
    return _sio.get_state_data(skeleton, STATE_KEY, {}) or {}


def _normalize_cell(controllers: dict) -> dict:
    """一格手型整理成存盘口径：手掌与极向量存位置 + 旋转，五指只存位置。

    手指控制器的朝向不参与动画（写关键帧时也只写位置），存下来只会让人以为它生效。
    """
    cell = {}
    for short, pose in (controllers or {}).items():
        if not isinstance(pose, dict):
            continue
        location = pose.get("location")
        if not isinstance(location, (list, tuple)) or len(location) != 3:
            continue
        entry = {"location": [float(value) for value in location]}
        if not _is_finger_short(short):
            rotation = pose.get("rotation") or pose.get("rotation_quaternion")
            if isinstance(rotation, (list, tuple)) and len(rotation) == 4:
                entry["rotation"] = [float(value) for value in rotation]
        cell[short] = entry
    return cell


def _hand_cells(raw_controllers) -> dict:
    """一只手的存储 → 两格 `{low: {...}, high: {...}}`。

    老数据是平铺的一格（外层直接就是 `H_L` 这种短名），那种情况当成两格相同——
    老资产没有"演奏 / 休息"之分，两格同源等于退回改之前的行为。
    """
    if not isinstance(raw_controllers, dict) or not raw_controllers:
        return {}
    if any(pose in raw_controllers for pose in HAND_POSES):
        return {
            pose: _normalize_cell(raw_controllers.get(pose))
            for pose in HAND_POSES
            if isinstance(raw_controllers.get(pose), dict)
        }
    flat = _normalize_cell(raw_controllers)
    if not flat:
        return {}
    return {pose: copy.deepcopy(flat) for pose in HAND_POSES}


def _save_cell(config, hand: str) -> dict:
    """把场景里当前这只手的状态读成一格手型。"""
    controllers = {}
    for short in hand_controller_shorts(hand):
        ctrl_obj = bpy.data.objects.get(config.obj_name(short))
        if ctrl_obj is None:
            continue
        if _is_finger_short(short):
            # 五指只取位置：约束算在内（ext 的跟随是约束给的），朝向不用。
            location = _sio.get_true_transform_value(ctrl_obj, "location")
            controllers[short] = {
                "location": [location.x, location.y, location.z]}
        else:
            _sio.copy_transfer_between_object_and_dict(
                ctrl_obj, controllers, "set", key=short)
    return controllers


def save_reference_hand(config, skeleton, hand: str, pose: str) -> int:
    """把当前一只手这一端的状态存成基准手型，返回写入的控制器数量。

    `pose` 是 [`HAND_POSES`] 里的一个（低位 / 高位）；只覆盖这一格，另一格原样保留。
    """
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法保存基准手型")
        return 0
    if pose not in HAND_POSES:
        print(f"  ⚠ 不认识的基准手型端点：{pose}")
        return 0

    controllers = _save_cell(config, hand)
    if not controllers:
        return 0

    state_data = _reference_data(skeleton)
    reference = state_data.setdefault("reference_hand", {})
    cells = _hand_cells(reference.get(_hand_key(hand)))
    cells[pose] = controllers
    reference[_hand_key(hand)] = cells
    _sio.set_state_data(skeleton, STATE_KEY, state_data)

    print(f"  ✓ 已保存{'左' if hand == 'L' else '右'}手"
          f"{HAND_POSE_LABELS[pose]}基准手型（{len(controllers)} 个控制器）")
    return len(controllers)


def load_reference_hand(config, skeleton, hand: str, pose: str) -> int:
    """把骨骼里这一端的手型应用到一只手的控制器，返回应用的控制器数量。

    没有这一端的数据时抛 ValueError，由面板转成界面提示。
    """
    state_data = _reference_data(skeleton)
    cells = _hand_cells(
        (state_data.get("reference_hand") or {}).get(_hand_key(hand)))
    controllers = cells.get(pose) or {}
    if not controllers:
        label = HAND_POSE_LABELS.get(pose, pose)
        raise ValueError(f"骨骼上还没有这只手的{label}手型，请先保存")

    applied = 0
    for short in hand_controller_shorts(hand):
        ctrl_obj = bpy.data.objects.get(config.obj_name(short))
        if ctrl_obj is None or short not in controllers:
            continue
        entry = controllers[short]
        # 五指只摆位置：把手型里的位置单独交给搬运函数，它就不会去动朝向。
        transfer = (entry if not _is_finger_short(short)
                    else {"location": entry.get("location")})
        _sio.copy_transfer_between_object_and_dict(
            ctrl_obj, {short: transfer}, "load", key=short)
        applied += 1

    print(f"  ✓ 已加载{'左' if hand == 'L' else '右'}手"
          f"{HAND_POSE_LABELS[pose]}基准手型（{applied} 个控制器）")
    return applied


def reference_hand_saved(skeleton, hand: str, pose: str) -> bool:
    """骨骼上是否已保存这只手这一端的基准手型"""
    if skeleton is None:
        return False
    state_data = _reference_data(skeleton)
    cells = _hand_cells(
        (state_data.get("reference_hand") or {}).get(_hand_key(hand)))
    return bool(cells.get(pose))


def reference_hands(skeleton) -> dict:
    """两只手的基准手型 `{手: {low: {短名: ...}, high: {短名: ...}}}`。

    没保存过的手不会出现在结果里；老数据（平铺的一格）展开成两格相同。
    导出 `.accordion` 的 `hands` 段直接用它。
    """
    if skeleton is None:
        return {}
    reference = _reference_data(skeleton).get("reference_hand") or {}
    hands = {}
    for hand_key, controllers in reference.items():
        cells = _hand_cells(controllers)
        if cells:
            hands[hand_key] = cells
    return hands


def save_reference_hands(skeleton, hands: dict) -> dict:
    """把导出的 `hands` 段整体写回骨骼，返回每只手、每端写入的控制器数量。

    新形状（`{left: {low: {...}, high: {...}}}`）与老形状（平铺的一格）都收，
    老形状展开成两格相同。文件只给了某一端时，另一端保持原样——导入别人的文件
    不该顺手清空本角色已经摆好的那一端。
    """
    if skeleton is None or not hands:
        return {}

    state_data = _reference_data(skeleton)
    reference = state_data.setdefault("reference_hand", {})
    written = {}
    for hand_key in ("left", "right"):
        incoming = hands.get(hand_key) or {}
        if not isinstance(incoming, dict) or not incoming:
            continue
        incoming_cells = _hand_cells(incoming)
        if not incoming_cells:
            continue
        cells = _hand_cells(reference.get(hand_key))
        cells.update(incoming_cells)
        reference[hand_key] = cells
        written[hand_key] = {pose: len(controllers)
                             for pose, controllers in incoming_cells.items()}

    if not written:
        return {}
    _sio.set_state_data(skeleton, STATE_KEY, state_data)
    print(f"  ✓ 基准手型已写入骨骼 {skeleton.name}：{written}")
    return written


# ── 枢轴姿态（风箱打开 / 合拢）────────────────────────────────
#
# 手风琴开合时，两个键区作为一个整体被推开或拉回，所以要采的正是 pivot_left / pivot_right
# 在这两个状态下的位置 + 旋转；`accordion_pivot` 是静态极向（用户摆一次、不参与计算），不采样。

def _pivot_pose_data(skeleton) -> dict:
    return _reference_data(skeleton).get("pivots") or {}


def save_pivot_pose(config, skeleton, pose_state: str) -> int:
    """把当前两个键区枢轴的位置 + 旋转存成指定风箱状态，返回写入的枢轴数量。

    存的是枢轴的**局部**位姿（枢轴挂在 controller_root 下），所以换角色、复制角色
    都不用换算；一个枢轴都没找到（没跑过「设置所有对象」）时返回 0，由面板报错。
    """
    if skeleton is None:
        print("  ⚠ 未指定目标骨骼，无法保存枢轴姿态")
        return 0

    pose_data = {}
    for short in PIVOT_SHORTS:
        pivot_obj = bpy.data.objects.get(config.obj_name(short))
        if pivot_obj is None:
            continue
        _sio.copy_transfer_between_object_and_dict(
            pivot_obj, pose_data, "set", key=short)

    if not pose_data:
        print("  ⚠ 没有找到键区枢轴，请先「设置所有对象」")
        return 0

    state_data = _reference_data(skeleton)
    state_data.setdefault("pivots", {})[pose_state] = pose_data
    _sio.set_state_data(skeleton, STATE_KEY, state_data)

    print(f"  ✓ 已保存枢轴姿态 [{pose_state}]（{len(pose_data)} 个枢轴）")
    return len(pose_data)


def load_pivot_pose(config, skeleton, pose_state: str) -> int:
    """把骨骼里某个风箱状态的枢轴姿态应用到两个键区枢轴，返回应用的枢轴数量。

    没有该状态的姿态时抛 ValueError，由面板转成界面提示。
    """
    pose_data = _pivot_pose_data(skeleton).get(pose_state) or {}
    if not pose_data:
        raise ValueError("骨骼上还没有这个状态的枢轴姿态，请先保存")

    applied = 0
    for short in PIVOT_SHORTS:
        pivot_obj = bpy.data.objects.get(config.obj_name(short))
        if pivot_obj is None or short not in pose_data:
            continue
        _sio.copy_transfer_between_object_and_dict(
            pivot_obj, pose_data, "load", key=short)
        applied += 1

    print(f"  ✓ 已加载枢轴姿态 [{pose_state}]（{applied} 个枢轴）")
    return applied


def pivot_pose_saved(skeleton, pose_state: str) -> bool:
    """骨骼上是否已保存该风箱状态的枢轴姿态"""
    if skeleton is None:
        return False
    return bool(_pivot_pose_data(skeleton).get(pose_state) or {})


def pivot_poses(skeleton) -> dict:
    """全部风箱状态的枢轴姿态 `{"open": {短名: {location, rotation}}, "closed": {...}}`。

    导出 `.accordion` 的 `pivots` 段直接用它；没采过的状态不会出现在结果里。
    """
    if skeleton is None:
        return {}
    poses = _pivot_pose_data(skeleton)
    return {pose_state: controllers for pose_state, controllers in poses.items()
            if isinstance(controllers, dict)}


def save_pivot_poses(skeleton, poses: dict) -> dict:
    """把导出的 `pivots` 段整体写回骨骼，返回每个风箱状态写入的枢轴数量。

    文件只带一个状态时，另一个状态保持原样（与基准手型同一套规则）。
    """
    if skeleton is None or not poses:
        return {}

    state_data = _reference_data(skeleton)
    stored = state_data.setdefault("pivots", {})
    written = {}
    for pose_state in PIVOT_POSES:
        pose_data = poses.get(pose_state) or {}
        if not pose_data:
            continue
        stored[pose_state] = pose_data
        written[pose_state] = len(pose_data)

    if not written:
        return {}
    _sio.set_state_data(skeleton, STATE_KEY, state_data)
    print(f"  ✓ 枢轴姿态已写入骨骼 {skeleton.name}：{written}")
    return written
