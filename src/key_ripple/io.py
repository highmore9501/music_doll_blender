# key_ripple/io.py
"""KeyRipple 乐器模块 —— .avatar 导入导出（迁移自 key_ripple_blender/tools/avatar_io.py）

.avatar 文件结构保持兼容（Rust/Unreal 侧继续消费）。
状态数据存骨骼（key_ripple_state_data），键盘基准点从 Empty 物体读取。
"""

import json
import os
from collections import defaultdict

import bpy  # type: ignore

from ..common import io_utils
from .config import KeyRipple, KeyType, PositionType
from .state import set_state_data


def export_avatar(
    file_path: str,
    key_ripple: KeyRipple,
    skeleton,
    for_unreal: bool = False,
) -> None:
    """导出 .avatar 文件（与旧版格式完全兼容）。

    for_unreal=True 时坐标转换为 Unreal 空间，is_unreal 字段随之置 True。
    """
    if not file_path.endswith(".avatar"):
        file_path = os.path.splitext(file_path)[0] + ".avatar"

    _pos = io_utils.to_unreal_position if for_unreal else (lambda p: p)
    _rot = io_utils.to_unreal_rotation if for_unreal else (lambda r: r)

    def nested_dict():
        return defaultdict(nested_dict)

    result = nested_dict()

    # ── 配置参数 ──────────────────────────────────────────────
    result["config"]["one_hand_finger_number"] = key_ripple.one_hand_finger_number
    result["config"]["leftest_position"] = key_ripple.leftest_position
    result["config"]["left_position"] = key_ripple.left_position
    result["config"]["middle_left_position"] = key_ripple.middle_left_position
    result["config"]["middle_right_position"] = key_ripple.middle_right_position
    result["config"]["right_position"] = key_ripple.right_position
    result["config"]["rightest_position"] = key_ripple.rightest_position
    result["config"]["min_key"] = key_ripple.min_key
    result["config"]["max_key"] = key_ripple.max_key
    result["config"]["hand_range"] = key_ripple.hand_range
    result["config"]["is_unreal"] = for_unreal

    # ── 从骨骼读取全部 state_data，转换为旧版 recorder 格式 ──
    raw = skeleton.get("key_ripple_state_data")
    all_states = json.loads(raw) if raw else []

    def get_recorder_section(ctrl_name):
        """返回 (top_key, sub_key) 如 ('finger_recorders', 'left_finger_recorders')"""
        # 手指控制器（骨骼/avatar 数据键 = 短名，无演奏者后缀）
        for fn, name in key_ripple.finger_controllers.items():
            if ctrl_name == name:
                side = "left_finger_recorders" if ctrl_name.endswith(
                    "_L") else "right_finger_recorders"
                return ("finger_recorders", side)
        # 手掌控制器
        for role, name in key_ripple.hand_controllers.items():
            if ctrl_name == name:
                side = "left_hand_recorders" if ctrl_name.endswith(
                    "_L") else "right_hand_recorders"
                return ("hand_recorders", side)
        # Head_Control
        if ctrl_name == "Head_Control":
            return ("target_points_recorders", "head_position_recorders")
        return None

    for state_entry in all_states:
        key_type_str = state_entry.get("key_type")      # "white" / "black"
        pos_type_str = state_entry.get(
            "position_type")  # "high" / "low" / "middle"
        controllers = state_entry.get("controllers", {})
        for ctrl_name, ctrl_data in controllers.items():
            section = get_recorder_section(ctrl_name)
            if section is None:
                continue
            top_key, sub_key = section
            recorder_name = f"{pos_type_str}_{key_type_str}_{ctrl_name}"
            entry = {
                "location": _pos(ctrl_data.get("location", [0, 0, 0])),
                "rotation_mode": "QUATERNION",
                "rotation_quaternion": _rot(ctrl_data.get("rotation", [1, 0, 0, 0])),
            }
            # 特殊处理旧版 Head_Control 嵌套结构
            if top_key == "target_points_recorders":
                result[top_key]["head_position_recorders"][recorder_name] = entry
            else:
                result[top_key][sub_key][recorder_name] = entry

    # ── 键盘基准点 ──────────────────────────────────────────
    for position_key, obj_name in key_ripple.key_board_positions.items():
        full = key_ripple.obj_name(obj_name)
        if full in bpy.data.objects:
            obj = bpy.data.objects[full]
            result["key_board_positions"][position_key] = {
                "name": obj_name,
                "location": _pos(list(obj.location)),
            }

    # ── pole 控件（挂在 ext 下的手指极向量，局部位置） ──
    pole_controllers = {}
    for pole_short in key_ripple.get_pole_controller_names():
        full = key_ripple.obj_name(pole_short)
        if full in bpy.data.objects:
            obj = bpy.data.objects[full]
            pole_controllers[pole_short] = {
                "location": _pos(list(obj.location)),
            }
    if pole_controllers:
        result["pole_controller"] = pole_controllers

    # ── 写入文件 ────────────────────────────────────────────
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(result, f, default=list, indent=4, ensure_ascii=False)
    print(f".avatar 已导出到 {file_path}")


def import_avatar(
    file_path: str,
    key_ripple: KeyRipple,
    skeleton,
) -> bool:
    """从 .avatar 文件导入数据。

    状态数据写入骨骼自定义属性，键盘基准点应用到 Empty 物体。
    """
    if not file_path.endswith(".avatar"):
        print("错误: 选择的文件不是 .avatar 文件")
        return False

    if not os.path.exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        return False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"成功读取 .avatar 文件: {file_path}")

        # ── 解析旧版 recorder 格式，按 (key_type, position_type) 分组 ──
        def parse_recorder_name(name):
            parts = name.split("_")
            if len(parts) < 3:
                return None
            pos_type = parts[0]      # "high" / "low" / "middle"
            key_type = parts[1]      # "white" / "black"
            ctrl_name = "_".join(parts[2:])  # 可能带后缀，如 "0_L_Jd"
            return (pos_type, key_type, ctrl_name)

        grouped = defaultdict(dict)

        # 手指记录器
        for side_key in ("left_finger_recorders", "right_finger_recorders"):
            recorders = data.get("finger_recorders", {}).get(side_key, {})
            for rec_name, rec_info in recorders.items():
                parsed = parse_recorder_name(rec_name)
                if parsed is None:
                    continue
                pos_type, key_type, ctrl_name = parsed
                entry = {
                    "location": rec_info.get("location", [0, 0, 0]),
                    "rotation": rec_info.get("rotation_quaternion", [1, 0, 0, 0]),
                }
                grouped[(key_type, pos_type)][ctrl_name] = entry

        # 手掌记录器
        for side_key in ("left_hand_recorders", "right_hand_recorders"):
            recorders = data.get("hand_recorders", {}).get(side_key, {})
            for rec_name, rec_info in recorders.items():
                parsed = parse_recorder_name(rec_name)
                if parsed is None:
                    continue
                pos_type, key_type, ctrl_name = parsed
                entry = {
                    "location": rec_info.get("location", [0, 0, 0]),
                    "rotation": rec_info.get("rotation_quaternion", [1, 0, 0, 0]),
                }
                grouped[(key_type, pos_type)][ctrl_name] = entry

        # Head_Control 记录器
        target_recorders = data.get("target_points_recorders", {})
        head_recorders = target_recorders.get(
            "head_position_recorders", target_recorders)
        for rec_name, rec_info in head_recorders.items():
            parsed = parse_recorder_name(rec_name)
            if parsed is None:
                continue
            pos_type, key_type, ctrl_name = parsed
            entry = {
                "location": rec_info.get("location", [0, 0, 0]),
                "rotation": rec_info.get("rotation_quaternion", [1, 0, 0, 0]),
            }
            grouped[(key_type, pos_type)][ctrl_name] = entry

        # ── 写入骨骼自定义属性 ────────────────────────────
        for (key_type_str, pos_type_str), ctrl_dict in grouped.items():
            state_entry = {
                "key_type": key_type_str,
                "position_type": pos_type_str,
                "controllers": ctrl_dict,
            }
            kt = KeyType.WHITE if key_type_str == "white" else KeyType.BLACK
            pt = PositionType.HIGH if pos_type_str == "high" else \
                PositionType.LOW if pos_type_str == "low" else PositionType.MIDDLE
            set_state_data(skeleton, kt, pt, state_entry)

        # ── 键盘基准点 ──────────────────────────────────────
        kb_data = data.get("key_board_positions", {})
        for position_key, position_info in kb_data.items():
            obj_name = position_info.get("name")
            # 旧文件基准点无后缀：若场景中找不到，尝试用当前演奏者后缀解析
            full = key_ripple.obj_name(obj_name) if obj_name else ""
            target = full if full in bpy.data.objects else (
                obj_name if obj_name in bpy.data.objects else None)
            if target:
                obj = bpy.data.objects[target]
                loc = position_info.get("location")
                if loc:
                    obj.location = loc
                    print(f"  ✓ 设置 {target} 位置: {loc}")

        # ── pole_controller：把局部位置应用到对应 pole 控件 ──
        pole_data = data.get("pole_controller", {})
        for pole_short, pole_info in pole_data.items():
            full = key_ripple.obj_name(pole_short)
            if full not in bpy.data.objects:
                print(f"  • pole 控件 {full} 不存在，跳过")
                continue
            loc = pole_info.get("location")
            if loc:
                bpy.data.objects[full].location = loc
                print(f"  ✓ 设置 {full} 位置: {loc}")

        print(f".avatar 已从 {file_path} 成功导入")
        return True

    except json.JSONDecodeError:
        print(f"错误: {file_path} 不是有效的JSON文件")
        return False
    except Exception as e:
        print(f"导入过程中发生错误: {str(e)}")
        return False
