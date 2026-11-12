# bellows_pulse/io.py
"""BellowsPulse 乐器模块 —— `.accordion` 文件导入 / 导出

`.accordion` 是 Rust 指法阶段读的乐器配置（字段定义在 `bellows_pulse_rust/src/keymap/*.rs`），
本文件负责它在 Blender 侧的三份数据往返：

- **乐器属性**（骨骼 `bellows_pulse_settings`）→ `right` / `left` 段，字段名照 Rust 代码写；
- **键区记录器的局部坐标**（记录器挂在键区骨骼跟随器下，`.location` 就是枢轴坐标系里的值）
  → `points` 段；
- **左右手基准手型**（骨骼 `bellows_pulse_state_data` 的 `reference_hand`）→ `hands` 段。

`pivots`（枢轴姿态 / 周期 / max_range）要到动画阶段才有数据，这里写成空占位，
让 Rust 侧和后续动画阶段都能直接按同一份文件布局取值。

约定：

- 导出**只读骨骼里已保存的乐器属性**，不读面板——面板上没保存的修改不会悄悄进入产物；
- JSON 键一律**短名**（不带演奏者后缀），只有查找场景对象时才按后缀解析；
- 记录器缺失（没跑过「设置所有对象」）时跳过并打印提示，**不写占位坐标**，
  免得生成一份看起来完整、实际全在原点上的数据。
"""

import json
import os

from ..common import io_utils
from ..common import i18n

from .config import recorders_for_layout
from .enums import (
    PIVOT_POSES,
    RIGHT_BUTTON_ROWS,
    RIGHT_LAYOUT_BUTTONS,
    RIGHT_LAYOUT_KEYBOARD,
    RIGHT_LAYOUTS,
    keyboard_key_count,
)
from . import state

#: 抛给界面的提示文本用 T 翻译（控制台打印仍是中文，跟其它模块一致）
T = i18n.T

#: 文件扩展名（Rust 端读的就是这个）
FILE_EXTENSION = ".accordion"

#: 文件格式版本（本模块自己写、自己读；Rust 端按路径取字段，不认识这个键会忽略）
FILE_VERSION = 1

#: 写进文件的字段说明（给拿到文件的人看，不参与解析）
FILE_NOTE = (
    "MusicDoll Blender 插件的 BellowsPulse 导出：right / left 是 Rust 指法阶段读的键区配置，"
    "points 是键区记录器的局部坐标（左右各自相对键区骨骼跟随器），"
    "hands 是左右手基准手型，pivots 是风箱打开 / 合拢时两根键区枢轴的位姿。"
)

#: 基准手型的默认旋转（四元数恒等），文件里没写旋转时用它
IDENTITY_ROTATION = [1.0, 0.0, 0.0, 0.0]

#: 普通导出：恒等变换
_IDENTITY_TRANSFORM = (lambda point: point)


# ── 坐标转换（导出到 Unreal / 从 Unreal 文件导回）──────────────
#
# `common/io_utils` 的这两个转换都是对合（做两次等于没做）：位置 Y 取反、旋转反射共轭。
# 所以导出到 Unreal 用它，把 Unreal 文件导回 Blender 也用同一个函数。

def _numbers(value, expected_length: int):
    """把文件/骨骼里的数值数组转成 float 列表；不是这么长的数值数组就返回 None"""
    if not isinstance(value, (list, tuple)) or len(value) != expected_length:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _transform_pair(is_unreal: bool):
    """→ (位置转换, 旋转转换)；is_unreal 为假时是恒等变换"""
    if not is_unreal:
        return _IDENTITY_TRANSFORM, _IDENTITY_TRANSFORM
    return io_utils.to_unreal_position, io_utils.to_unreal_rotation


def _normalized(values) -> list:
    """数值列表：把 -0.0 归一成 0.0（Y 取反会把 0 变成 -0.0，写进文件没必要带符号）"""
    return [0.0 if value == 0 else float(value) for value in values]


def convert_pose_groups(groups: dict, position_to, rotation_to) -> dict:
    """把「组 → 短名 → 位姿」两层的坐标整体换到目标空间。

    `points` / `hands` / `pivots` 三段都是这个形状：外层是分组键（right / left / open…），
    里层是短名，值里至少有个 `location`，带旋转的（手型、枢轴）还有 `rotation_quaternion`。
    位置不是三个数的条目直接丢掉（导入时由后续步骤报告缺失），不写 0 占位。
    """
    converted = {}
    for group_key, controllers in (groups or {}).items():
        entries = {}
        for short, pose in (controllers or {}).items():
            if not isinstance(pose, dict):
                continue
            location = _numbers(pose.get("location"), 3)
            if location is None:
                continue
            entry = {"location": _normalized(position_to(location))}
            rotation = _numbers(pose.get("rotation_quaternion"), 4)
            if rotation is not None:
                entry["rotation_quaternion"] = _normalized(
                    rotation_to(rotation))
            entries[short] = entry
        converted[group_key] = entries
    return converted


# ── 路径与文件名 ──────────────────────────────────────────────

def _ensure_accordion_path(file_path: str) -> str:
    """把信息路径归一化成 `.accordion`（别的乐器写完的扩展名会被换掉）"""
    if not file_path:
        raise ValueError(T("请先在「角色操作」面板中设置人物信息路径"))
    return io_utils.ensure_extension(file_path, FILE_EXTENSION)


def target_file_name(file_path: str) -> str:
    """信息路径 → 实际写出的文件名（面板显示用；空路径返回空串）"""
    if not file_path:
        return ""
    return os.path.basename(_ensure_accordion_path(file_path))


# ── 乐器属性 → right / left 段 ────────────────────────────────

def right_section(settings: dict) -> dict:
    """乐器属性 → `right` 段（只写当前右手类型用得上的字段）。

    键盘写 `min_note` / `max_note` / `key_count`（Rust 用 `min_note + key_count` 建表，
    `max_note` 是面板上的原始值，一并留着便于对照）；按钮写 `rows` / `first_row_keys` /
    `anchor_note` / `stagger`。错排量只对按钮有意义，键盘段不写，免得读的人以为它生效。
    """
    right = settings.get("right") or {}
    if right.get("layout") == RIGHT_LAYOUT_BUTTONS:
        return {
            "layout": RIGHT_LAYOUT_BUTTONS,
            "rows": RIGHT_BUTTON_ROWS,
            "first_row_keys": int(right.get("first_row_keys", 0)),
            "anchor_note": int(right.get("anchor_note", 0)),
            "stagger": round(float(right.get("stagger", 0.0)), 4),
        }

    min_note = int(right.get("min_note", 0))
    max_note = int(right.get("max_note", 0))
    return {
        "layout": RIGHT_LAYOUT_KEYBOARD,
        "min_note": min_note,
        "max_note": max_note,
        "key_count": keyboard_key_count(min_note, max_note),
    }


def left_section(settings: dict) -> dict:
    """乐器属性 → `left` 段（左手 Stradella：排数 / 每排按钮数 / 第 2 排最低音 / 错排量）"""
    left = settings.get("left") or {}
    return {
        "rows": int(left.get("rows", 0)),
        "keys_per_row": int(left.get("keys_per_row", 0)),
        "first_main_bass": int(left.get("first_main_bass", 0)),
        "stagger": round(float(left.get("stagger", 0.0)), 4),
    }


# ── 记录器坐标 → points 段 ────────────────────────────────────

def recorder_points(config, settings: dict) -> dict:
    """键区记录器的局部坐标 → `points` 段 `{"right": {...}, "left": {...}}`。

    左右按记录器**父级**分组（左键区挂 `left_bone`、右键区挂 `right_bone`），
    不按名字前缀猜。坐标取 `.location`：记录器的父级就是键区跟随器，这已经是枢轴坐标系里的值。
    """
    layout = (settings.get("right") or {}).get(
        "layout", RIGHT_LAYOUT_KEYBOARD)
    points = {"right": {}, "left": {}}
    for short, parent_short, _offset in recorders_for_layout(layout):
        recorder_obj = config.obj(short)
        if recorder_obj is None:
            print(f"  • 记录器 {config.obj_name(short)} 不存在，跳过"
                  f"（请先「设置所有对象」）")
            continue
        side = "left" if parent_short == "left_bone" else "right"
        points[side][short] = {
            "location": [round(value, 6) for value in recorder_obj.location],
        }
    return points


# ── 位姿（基准手型 / 枢轴姿态）→ 文件里的写法 ────────────────
#
# 骨骼内部把旋转存在 `rotation` 键下；对外的文件格式跟其它乐器一致，
# 用 `rotation_quaternion`，导入时再转回骨骼结构。手型和枢轴共用一个转换。

def _pose_entries_to_file(controllers: dict) -> dict:
    """骨骼里的位姿 dict → 文件里的位姿 dict（旋转改键名、数值四舍五入）"""
    entries = {}
    for short, pose in (controllers or {}).items():
        if not isinstance(pose, dict):
            continue
        entries[short] = {
            "location": [round(value, 6)
                         for value in (pose.get("location") or [0.0, 0.0, 0.0])],
            "rotation_quaternion": [round(value, 6)
                                    for value in (pose.get("rotation")
                                                  or IDENTITY_ROTATION)],
        }
    return entries


def hands_section(skeleton) -> dict:
    """骨骼里的基准手型 → `hands` 段（`{left: {...}, right: {...}}`）"""
    return {hand_key: _pose_entries_to_file(controllers)
            for hand_key, controllers in (state.reference_hands(skeleton) or {}).items()}


def pivots_section(skeleton) -> dict:
    """骨骼里的枢轴姿态 → `pivots` 段（`{open: {...}, closed: {...}}`）。

    每个状态里是 `pivot_left` / `pivot_right` 的位置 + 旋转；没采过的状态不写。
    """
    return {pose_state: _pose_entries_to_file(controllers)
            for pose_state, controllers in (state.pivot_poses(skeleton) or {}).items()}


# ── 导出 ──────────────────────────────────────────────────────

def export_accordion(file_path: str, config, skeleton,
                     for_unreal: bool = False) -> dict:
    """把骨骼上的乐器属性、键区记录器坐标、基准手型、枢轴姿态写成 `.accordion`。

    `for_unreal=True` 时把 `points` / `hands` / `pivots` 三段的位置与旋转过一遍
    `common/io_utils` 的坐标系转换，并写 `is_unreal: true`；普通导出是恒等变换、
    写 `is_unreal: false`。

    返回 `{"path", "recorders", "hands", "pivots"}`（记录器数与各段写入的条数），
    面板拿它拼提示。骨骼上还没保存过乐器属性时抛 ValueError。
    """
    if skeleton is None:
        raise ValueError(T("请先选择目标骨骼"))
    if not state.has_settings(skeleton):
        raise ValueError(
            T("骨骼上还没有保存乐器属性，请先在面板里点「保存乐器属性到骨骼」"))

    position_to, rotation_to = _transform_pair(bool(for_unreal))
    settings = state.normalize_settings(state.load_settings(skeleton))
    points = convert_pose_groups(recorder_points(config, settings),
                                 position_to, rotation_to)
    hands = convert_pose_groups(hands_section(skeleton),
                                position_to, rotation_to)
    pivots = convert_pose_groups(pivots_section(skeleton),
                                 position_to, rotation_to)

    export_data = {
        "version": FILE_VERSION,
        "name": config.suffix or "BellowsPulse",
        "note": FILE_NOTE,
        "is_unreal": bool(for_unreal),
        "right": right_section(settings),
        "left": left_section(settings),
        "left_instrument": settings.get("left_instrument", ""),
        "points": points,
        "hands": hands,
        "pivots": pivots,
    }

    output_path = _ensure_accordion_path(file_path)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(export_data, handle, ensure_ascii=False, indent=2)

    recorder_count = len(points["right"]) + len(points["left"])
    hand_counts = {hand_key: len(controllers)
                   for hand_key, controllers in hands.items()}
    pivot_counts = {pose_state: len(controllers)
                    for pose_state, controllers in pivots.items()}
    coordinate_note = "（Unreal 坐标系）" if for_unreal else ""
    print(f"  ✓ 已导出{coordinate_note} {export_data['right']['layout']} 键区配置、"
          f"{recorder_count} 个记录器坐标、基准手型 {hand_counts}、"
          f"枢轴姿态 {pivot_counts} → {output_path}")
    return {"path": output_path, "recorders": recorder_count,
            "hands": hand_counts, "pivots": pivot_counts}


# ── 导入：文件 → 乐器属性 ─────────────────────────────────────

def _file_int(value, default: int = 0) -> int:
    """文件里的整数字段（数字或数字字符串都能读；读不出来用默认值，交给校验拒绝）"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _merged_right_layout(current_layout: str, right_in: dict) -> str:
    """文件里的右手类型：优先读 `layout`，没写就按字段推断，都推断不出来保留现值"""
    layout = right_in.get("layout")
    if layout in RIGHT_LAYOUTS:
        return layout
    if "key_count" in right_in:
        return RIGHT_LAYOUT_KEYBOARD
    if "first_row_keys" in right_in:
        return RIGHT_LAYOUT_BUTTONS
    return current_layout


def settings_from_file(file_data: dict, current: dict) -> dict:
    """把文件里的 `right` / `left` 段合并到当前设置上（文件没写的字段保留现值）。

    `.accordion` 只带 Rust 要的字段：键盘文件里没有按钮的锚点与第 1 排键数，
    按钮文件里没有键盘的音域。若整份结构照文件重建，另一套配置会被 0 覆盖，
    之后在面板切到那种键区就全是 0 了。
    """
    settings = state.normalize_settings(current)
    right_in = file_data.get("right") or {}
    left_in = file_data.get("left") or {}

    layout = _merged_right_layout(settings["right"]["layout"], right_in)
    settings["right"]["layout"] = layout

    if layout == RIGHT_LAYOUT_KEYBOARD:
        if "min_note" in right_in:
            settings["right"]["min_note"] = right_in["min_note"]
        if "max_note" in right_in:
            settings["right"]["max_note"] = right_in["max_note"]
        elif "key_count" in right_in:
            # 只给了键数：最高音 = 最低音 + 键数 − 1
            settings["right"]["max_note"] = (
                _file_int(settings["right"]["min_note"])
                + _file_int(right_in["key_count"]) - 1)
    else:
        for field_name in ("anchor_note", "first_row_keys", "stagger"):
            if field_name in right_in:
                settings["right"][field_name] = right_in[field_name]

    for field_name in ("rows", "keys_per_row", "first_main_bass", "stagger"):
        if field_name in left_in:
            settings["left"][field_name] = left_in[field_name]

    if "left_instrument" in file_data:
        settings["left_instrument"] = str(file_data.get("left_instrument") or "")

    return state.normalize_settings(settings)


def _format_validation_errors(errors: list[tuple[str, tuple]]) -> str:
    """校验错误 → 一行提示（校验层只给「文本键 + 参数」，这里翻译成当前语言）"""
    messages = []
    for message_key, message_args in errors:
        messages.append(T(message_key) % message_args if message_args
                        else T(message_key))
    return "；".join(messages)


# ── 导入：文件 → 场景对象 ─────────────────────────────────────

def apply_points(config, points: dict) -> dict:
    """把 `points` 段写回记录器对象，返回 `{"applied": n, "missing": n}`。

    缺对象（普通情况是导入的文件右手类型与场景里的记录器对不上）只计数并提示，
    不会自己建记录器——建哪一套由骨骼里的设置决定，那是「设置所有对象」的活。
    """
    applied = 0
    missing = 0
    for side in ("right", "left"):
        for short, entry in (points.get(side) or {}).items():
            recorder_obj = config.obj(short)
            if recorder_obj is None:
                missing += 1
                print(f"  • 记录器 {config.obj_name(short)} 不存在，跳过"
                      f"（切换过右手类型时请先「设置所有对象」）")
                continue
            location = _numbers(entry.get("location"), 3)
            if location is None:
                continue
            recorder_obj.location = (location[0], location[1], location[2])
            applied += 1
            print(f"  ✓ 记录器 {recorder_obj.name} 位置 → {list(recorder_obj.location)}")
    return {"applied": applied, "missing": missing}


def _pose_entries_from_file(controllers: dict) -> dict:
    """文件里的位姿 dict → 骨骼里的位姿 dict（`rotation_quaternion` → `rotation`）"""
    converted = {}
    for short, pose in (controllers or {}).items():
        if not isinstance(pose, dict):
            continue
        rotation = (_numbers(pose.get("rotation_quaternion"), 4)
                    or _numbers(pose.get("rotation"), 4)
                    or list(IDENTITY_ROTATION))
        converted[short] = {
            "location": _numbers(pose.get("location"), 3) or [0.0, 0.0, 0.0],
            "rotation": rotation,
        }
    return converted


def apply_hands(skeleton, hands: dict) -> dict:
    """把 `hands` 段写回骨骼，返回每只手写入的控制器数量。"""
    converted = {hand_key: _pose_entries_from_file(hands.get(hand_key))
                 for hand_key in ("left", "right")
                 if isinstance(hands.get(hand_key), dict)}
    return state.save_reference_hands(skeleton, converted)


def apply_pivots(skeleton, pivots: dict) -> dict:
    """把 `pivots` 段写回骨骼，返回每个风箱状态写入的枢轴数量。

    只写骨骼——把姿态摆到场景里的枢轴上要用户在面板上点「加载该状态」，
    这样导入一份别人的配置不会立刻把当前场景的姿势顶掉。
    """
    converted = {pose_state: _pose_entries_from_file(pivots.get(pose_state))
                 for pose_state in PIVOT_POSES
                 if isinstance(pivots.get(pose_state), dict)}
    return state.save_pivot_poses(skeleton, converted)


# ── 导入 ──────────────────────────────────────────────────────

def _read_accordion_file(file_path: str) -> dict:
    """读文件并做最基本的格式检查（必须是 JSON 对象，且有 right 或 left 段）"""
    if not os.path.exists(file_path):
        raise ValueError(T("文件不存在：%s") % file_path)
    with open(file_path, "r", encoding="utf-8") as handle:
        try:
            file_data = json.load(handle)
        except json.JSONDecodeError:
            raise ValueError(T("%s 不是有效的 JSON 文件") % file_path)
    if not isinstance(file_data, dict):
        raise ValueError(T("文件格式不正确：顶层不是 JSON 对象"))
    if not (file_data.get("right") or file_data.get("left")):
        raise ValueError(T("文件格式不正确：缺少 right / left 段"))
    return file_data


def import_accordion(file_path: str, config, skeleton) -> dict:
    """从 `.accordion` 读入，写回骨骼的乐器属性 / 基准手型 / 枢轴姿态，以及场景里的记录器坐标。

    文件里 `is_unreal` 为真（导出到 Unreal 的那份）时，位置与旋转先换回 Blender 空间再写入——
    转换是对合，同一个函数反着用即可，所以拿 Unreal 那份导回 Blender 不会左右镜像。

    返回 `{"path", "settings", "recorders": {applied, missing}, "hands", "pivots"}`，
    面板用它刷新分步字段并拼提示。文件里的乐器属性不合法时抛 ValueError 并且
    **一个字段都不写**（先校验、后落盘），免得把半份数据写进骨骼。
    """
    if skeleton is None:
        raise ValueError(T("请先选择目标骨骼"))
    if not file_path:
        raise ValueError(T("请先在「角色操作」面板中设置人物信息路径"))

    file_data = _read_accordion_file(_ensure_accordion_path(file_path))

    settings = settings_from_file(file_data, state.load_settings(skeleton))
    errors = state.validate_settings(settings)
    if errors:
        raise ValueError(T("文件里的乐器属性不合法：%s")
                         % _format_validation_errors(errors))

    if not state.save_settings(skeleton, settings):
        raise ValueError(T("请先选择目标骨骼"))

    position_to, rotation_to = _transform_pair(bool(file_data.get("is_unreal")))
    recorders = apply_points(
        config, convert_pose_groups(file_data.get("points") or {},
                                    position_to, rotation_to))
    hands = apply_hands(
        skeleton, convert_pose_groups(file_data.get("hands") or {},
                                      position_to, rotation_to))
    pivots = apply_pivots(
        skeleton, convert_pose_groups(file_data.get("pivots") or {},
                                      position_to, rotation_to))

    print(f"  ✓ 已导入 .accordion ← {file_path}"
          f"（记录器 {recorders['applied']} 个，缺失 {recorders['missing']} 个；"
          f"基准手型 {hands}；枢轴姿态 {pivots}）")
    return {"path": file_path, "settings": settings,
            "recorders": recorders, "hands": hands, "pivots": pivots}
