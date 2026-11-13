# bellows_pulse/animation.py
"""BellowsPulse 乐器模块 —— 动画写入（读 Rust 产物，按控制器名写关键帧）

Rust 侧 `cargo run -- gen` 一次写出四份产物，其中三份要进 Blender：

- `.animation`：手掌 `H_L` / `H_R` 的位置 + 四元数，以及五指控制器的位置 + 四元数。
  五指挂在 `H_*` 下面，文件里存的就是手腕局部坐标，直接写 `location` 即可；
- `.pivot_animation`：`pivot_left` / `pivot_right` 的位置 + 四元数。风箱的形变由场景里
  现成的约束解算，Rust 只给这两个枢轴；
- `.key_animation`：按键形变。每颗按钮一条 shape key 曲线，名字 `L{排}_{列}_pressed` /
  `R{排}_{列}_pressed`：左边那套在左键区网格上，右边那套在右键区网格（目标乐器）上。

`.activity_curve` **不读**：枢轴的开合已经按活动曲线烘焙进 `.pivot_animation`，
Blender 侧没有第二处要用它。

# 输入

面板上选的是产物清单 `output/final_result/{stem}.bellows`，里面的 `animation_paths`
列着这几份文件的路径。清单里的路径相对 Rust 的工作目录写（`output/animation/…`），
而清单自己在 `output/final_result/` 下，所以按清单的位置往上两级反推工作目录再拼路径。

# 写之前先清理

同一份场景反复生成动画必须是**覆盖**而不是叠加：

- addons 目录里控制器上的关键帧先摘掉，driver 不动（ext 跟随手指靠 driver，不是关键帧）；
- 两块键区网格的 shape key 归零，再清掉 shape key 动画。

清理放在**校验之后**：清单缺文件、网格上没有对得上的 shape key 这类情况直接报错返回，
不白清一遍现有动画。

# 缺项怎么处理

- 手掌 `H_*`、枢轴 `pivot_*` 解析不到 → 报错（没跑「设置所有对象」，场景里根本没法写）；
- 某块网格上一个对得上的 shape key 都没有 → 报错（键区网格选错，或者排号与 Rust 对不上）；
- 个别手指控制器、个别 shape key 缺失 → 只提示并跳过，其余照常写入。
"""

import json
import os

from ..common import animation_utils
from ..common import i18n

T = i18n.T

#: 产物清单的扩展名（Rust 端 `pipeline/artifacts.rs` 写出的就是它）
MANIFEST_EXTENSION = ".bellows"

#: 清单里的格式标记，用来挡掉别的乐器的产物清单
MANIFEST_FORMAT = "bellows_pulse"

#: 清单里"动画文件路径"那一项的键
MANIFEST_ANIMATION_KEY = "animation_paths"

#: 手 + 手腕、枢轴、按键形变三份产物的扩展名
HAND_EXTENSION = ".animation"
PIVOT_EXTENSION = ".pivot_animation"
KEY_EXTENSION = ".key_animation"

#: 按键形变 shape key 名的手别前缀（`L3_5_pressed` 的 `L`）
LEFT_SHAPE_KEY_PREFIX = "L"

#: 场景里必须存在的控制器短名：缺了这些就没法写动画（其余手指只提示）
REQUIRED_CONTROLLER_SHORTS = ("H_L", "H_R", "pivot_left", "pivot_right")


# ── 产物清单与路径 ────────────────────────────────────────────

def _artifact_roots(manifest_path: str) -> list:
    """按清单的位置反推"Rust 工作目录"，按可能性从高到低排列。

    清单在 `<工作目录>/output/final_result/` 下，往上一级是 `output/`，
    再往上一级才是工作目录；清单里的 `output/animation/…` 拼在它后面正好对上。
    另外两个候选是清单所在目录与当前目录，兜住"清单被单独挪出来"的情况。
    """
    manifest_directory = os.path.dirname(os.path.abspath(manifest_path))
    working_directory_guess = os.path.dirname(os.path.dirname(manifest_directory))
    roots = [working_directory_guess, manifest_directory, os.getcwd()]
    return [root for root in roots if root]


def resolve_artifact_path(manifest_path: str, stored_path: str):
    """清单里的路径 → 本机真实路径；都找不到时返回 None。

    绝对路径能直接打开就用它，否则依次拿几个候选工作目录去拼，取第一个真实存在的。
    """
    if not stored_path:
        return None
    if os.path.isabs(stored_path) and os.path.exists(stored_path):
        return stored_path

    for root in _artifact_roots(manifest_path):
        candidate_path = os.path.normpath(os.path.join(root, stored_path))
        if os.path.exists(candidate_path):
            return candidate_path
    return None


def _artifact_kind(stored_path: str):
    """按扩展名判断这是哪一份产物：`animation` / `pivot` / `key`；其它返回 None。"""
    extension = os.path.splitext(stored_path)[1]
    return {
        HAND_EXTENSION: "animation",
        PIVOT_EXTENSION: "pivot",
        KEY_EXTENSION: "key",
    }.get(extension)


def read_manifest(manifest_path: str) -> dict:
    """读产物清单，返回 `{"animation", "pivot", "key"}` 三份产物的本机路径。

    清单不存在、格式不对、只做到指法阶段、任何一份产物找不到，都抛 ValueError。
    """
    if not manifest_path:
        raise ValueError(T("请先选择 .bellows 产物清单"))
    if not os.path.exists(manifest_path):
        raise ValueError(T("产物清单不存在：%s") % manifest_path)

    with open(manifest_path, "r", encoding="utf-8") as handle:
        try:
            manifest = json.load(handle)
        except json.JSONDecodeError:
            raise ValueError(T("%s 不是有效的 JSON 文件") % manifest_path)

    if not isinstance(manifest, dict):
        raise ValueError(T("产物清单格式不正确：顶层不是 JSON 对象"))
    if manifest.get("format") != MANIFEST_FORMAT:
        raise ValueError(T("这不是 BellowsPulse 的产物清单（format = %s）")
                         % manifest.get("format"))

    stored_paths = manifest.get(MANIFEST_ANIMATION_KEY) or []
    if not stored_paths:
        raise ValueError(T("这份清单只做到指法阶段，还没有动画文件；请跑完整的 gen"))

    resolved_paths = {"animation": None, "pivot": None, "key": None}
    for stored_path in stored_paths:
        kind = _artifact_kind(stored_path)
        if kind is None:
            continue
        real_path = resolve_artifact_path(manifest_path, stored_path)
        if real_path is None:
            raise ValueError(
                T("清单里的产物找不到：%s（路径是按清单位置反推的，"
                  "请确认产物没有被挪走）") % stored_path)
        resolved_paths[kind] = real_path

    kind_labels = (
        ("animation", "手部动画"),
        ("pivot", "枢轴动画"),
        ("key", "按键形变"),
    )
    missing_labels = [T(label) for kind, label in kind_labels
                      if resolved_paths[kind] is None]
    if missing_labels:
        raise ValueError(T("产物清单里缺少：%s") % "、".join(missing_labels))

    return resolved_paths


def _read_json(file_path: str, what: str):
    """读一份产物（UTF-8 JSON）；读不出来抛 ValueError。"""
    with open(file_path, "r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError:
            raise ValueError(T("%s 文件不是有效的 JSON：%s") % (T(what), file_path))


# ── 计划：要先看清往哪儿写，再动手改场景 ─────────────────────

def _frame_short_names(frame_records) -> list:
    """一份 `.animation` 里出现过的全部控制器短名（去重，保持出现顺序）。"""
    short_names = []
    for frame_record in frame_records or []:
        if not isinstance(frame_record, dict):
            continue
        for short_name in (frame_record.get("hand_infos") or {}):
            if short_name not in short_names:
                short_names.append(short_name)
    return short_names


def _missing_controllers(frame_records, config) -> list:
    """这份动画要写的控制器里，场景中没有的那些（短名）。"""
    return [short_name for short_name in _frame_short_names(frame_records)
            if config.obj(short_name) is None]


def _resolved_objects(frame_records, config) -> list:
    """这份动画要写的控制器里，场景中真实存在的那些（对象）。"""
    objects = []
    for short_name in _frame_short_names(frame_records):
        found = config.obj(short_name)
        if found is not None:
            objects.append(found)
    return objects


def _keybed_of_shape_key(shape_key_name: str, left_instrument, right_instrument):
    """shape key 名 → 它该在哪块键区网格上：左手前缀在左键区，其余在右键区。"""
    if shape_key_name.startswith(LEFT_SHAPE_KEY_PREFIX):
        return left_instrument
    return right_instrument


def _shape_key_table(mesh_object) -> dict:
    """网格上现有的 shape key：名字 → key block；不是带 shape key 的网格时返回空 dict。"""
    if mesh_object is None or mesh_object.type != 'MESH':
        return {}
    shape_keys = getattr(mesh_object.data, "shape_keys", None)
    if not shape_keys:
        return {}
    return {key_block.name: key_block for key_block in shape_keys.key_blocks}


def plan_key_curves(curves, left_instrument, right_instrument) -> dict:
    """按键形变 → 按落点分组 `{网格名: {"keybed": 网格, "curves": [...]}}`。

    每条形变带上解析好的 `(帧, 值)` 点，写盘时直接用，不再回头读文件。
    """
    key_plan = {}
    for curve in curves or []:
        if not isinstance(curve, dict):
            continue
        shape_key_name = str(curve.get("shape_key") or "")
        if not shape_key_name:
            continue

        keybed = _keybed_of_shape_key(
            shape_key_name, left_instrument, right_instrument)
        if keybed is None:
            raise ValueError(
                T("%s 找不到对应的键区网格：请在面板④里设置左键区网格，"
                  "并确认右键区（目标乐器）已经指定") % shape_key_name)

        points = []
        for point in curve.get("keyframes") or []:
            if not isinstance(point, dict):
                continue
            try:
                frame = float(point.get("frame"))
                value = float(point.get("value"))
            except (TypeError, ValueError):
                continue
            points.append((frame, value))
        if not points:
            continue

        group = key_plan.setdefault(
            keybed.name, {"keybed": keybed, "curves": []})
        group["curves"].append({"shape_key": shape_key_name, "points": points})

    return key_plan


def _validate_key_plan(key_plan: dict) -> None:
    """一块网格上一个对得上的 shape key 都没有时抛错（键区网格选错或排号对不上）。"""
    if not key_plan:
        raise ValueError(T("按键形变文件里没有可写入的曲线"))
    for group in key_plan.values():
        keybed = group["keybed"]
        existing_names = _shape_key_table(keybed)
        matched = [curve for curve in group["curves"]
                   if curve["shape_key"] in existing_names]
        if not matched:
            raise ValueError(
                T("键区网格 %s 上没有任何与按键形变对得上的 shape key"
                  "（排号或网格选错了）") % keybed.name)


# ── 写出 ──────────────────────────────────────────────────────

def write_transform_animation(frame_records, config, label: str) -> dict:
    """把一份 `.animation` 写成场景物体关键帧；返回写入的对象数与缺失清单。"""
    result = animation_utils.apply_transform_animation(
        frame_records, config.obj_name)
    print(f"  ✓ {T(label)}：{result['objects']} 个控制器")
    if result["missing"]:
        print(f"  • {T(label)}：{len(result['missing'])} 个控制器在场景里找不到，已跳过："
              f"{'、'.join(result['missing'])}")
    return result


def write_key_plan(key_plan: dict) -> dict:
    """按计划写按键形变；返回写入的曲线数与没找到的 shape key。"""
    written_curves = 0
    missing_shape_keys = []

    for group in key_plan.values():
        keybed = group["keybed"]
        shape_keys = getattr(keybed.data, "shape_keys", None)
        if not shape_keys:
            raise ValueError(
                T("键区网格 %s 上没有 shape key，无法写按键形变") % keybed.name)

        if not shape_keys.animation_data:
            shape_keys.animation_data_create()
        animation_utils.get_or_create_action(
            shape_keys, f"{keybed.name}_shape_keys")

        existing_names = _shape_key_table(keybed)
        for curve in group["curves"]:
            shape_key_name = curve["shape_key"]
            if shape_key_name not in existing_names:
                missing_shape_keys.append(shape_key_name)
                continue
            fcurve = animation_utils.get_or_create_fcurve(
                shape_keys, f'key_blocks["{shape_key_name}"].value')
            animation_utils.write_fcurve_points(fcurve, curve["points"])
            written_curves += 1

    print(f"  ✓ 按键形变：{written_curves} 条 shape key 曲线")
    if missing_shape_keys:
        preview = "、".join(missing_shape_keys[:10])
        more = "…" if len(missing_shape_keys) > 10 else ""
        print(f"  • 按键形变：{len(missing_shape_keys)} 个 shape key 在网格上找不到，"
              f"已跳过：{preview}{more}")

    return {"curves": written_curves, "missing": missing_shape_keys}


def clear_previous_animation(config, left_instrument, right_instrument,
                             target_objects=()) -> None:
    """清掉上一次生成的动画：控制器关键帧与两块网格的 shape key 曲线。

    清的是**本乐器的全部控制器**（`all_controller_shorts`），不只是这次文件里出现的那些：
    上一首曲子用到、这一首没用到的手指，也要把旧曲线摘掉，否则它会一直停在上一首的姿势上。
    只动关键帧——控制器上的 driver（ext 跟随手指、手背 Hook 之类）原样保留。
    """
    controlled_objects = []
    for short_name in config.all_controller_shorts():
        found = config.obj(short_name)
        if found is not None and found not in controlled_objects:
            controlled_objects.append(found)
    for target in target_objects:
        if target is not None and target not in controlled_objects:
            controlled_objects.append(target)
    for controlled in controlled_objects:
        animation_utils.clear_animation_preserve_drivers(controlled)

    for keybed in (left_instrument, right_instrument):
        if keybed is None or keybed.type != 'MESH':
            continue
        animation_utils.reset_shape_keys(keybed)
        animation_utils.clear_shape_key_animation(keybed)


def generate_animation(manifest_path: str, config, left_instrument,
                       right_instrument) -> dict:
    """按产物清单把三类动画写进场景，返回各段的写入统计。

    读文件、校验落点全部在改动场景之前完成；任何一步不成立都抛 ValueError，
    场景保持原样。`left_instrument` / `right_instrument` 是两块键区网格
    （左键区由面板登记，右键区就是目标乐器）。
    """
    resolved_paths = read_manifest(manifest_path)
    hand_entries = _read_json(resolved_paths["animation"], "手部动画")
    pivot_entries = _read_json(resolved_paths["pivot"], "枢轴动画")
    key_curves = _read_json(resolved_paths["key"], "按键形变")

    if not isinstance(hand_entries, list) or not isinstance(pivot_entries, list):
        raise ValueError(T("手部 / 枢轴动画文件格式不正确：顶层不是数组"))
    if not isinstance(key_curves, list):
        raise ValueError(T("按键形变文件格式不正确：顶层不是数组"))

    # 校验一：必须存在的控制器（手掌、枢轴）在不在
    hand_targets = _resolved_objects(hand_entries, config)
    pivot_targets = _resolved_objects(pivot_entries, config)
    if not hand_targets:
        raise ValueError(
            T("手部动画里的控制器在场景里一个都找不到："
              "请检查当前角色是否选对、以及有没有跑过「设置所有对象」"))

    missing_controllers = _missing_controllers(hand_entries, config)
    for short_name in _missing_controllers(pivot_entries, config):
        if short_name not in missing_controllers:
            missing_controllers.append(short_name)
    fatal_missing = [short_name for short_name in missing_controllers
                     if short_name in REQUIRED_CONTROLLER_SHORTS]
    if fatal_missing:
        raise ValueError(
            T("场景里找不到控制器 %s：请先点「设置所有对象」") % "、".join(fatal_missing))

    # 校验二：按键形变的落点
    key_plan = plan_key_curves(key_curves, left_instrument, right_instrument)
    _validate_key_plan(key_plan)

    # 校验通过之后才动场景
    clear_previous_animation(
        config, left_instrument, right_instrument,
        target_objects=hand_targets + pivot_targets)

    hand_result = write_transform_animation(hand_entries, config, "手部动画")
    pivot_result = write_transform_animation(pivot_entries, config, "枢轴动画")
    key_result = write_key_plan(key_plan)

    print(f"  ✓ 动画已写入：手部 {hand_result['objects']} 个控制器、"
          f"枢轴 {pivot_result['objects']} 个、按键 {key_result['curves']} 条曲线"
          f"（清单 {os.path.basename(manifest_path)}）")

    return {
        "manifest": manifest_path,
        "paths": resolved_paths,
        "hand": hand_result,
        "pivot": pivot_result,
        "key": key_result,
        "missing_controllers": missing_controllers,
    }
