# fret_dance/io.py
"""FretDance 乐器模块 —— 输入输出（迁移自 fret_dance_blender/io_manager.py）

导出/导入控制器信息 JSON。内容结构与 Unreal 侧一致（供 Rust 消费）；
导出文件名由用户选择，不带 `_unreal` 后缀。
"""

import json
import os
import bpy  # type: ignore

from ..common import io_utils
from .enums import Instruments, BasePositions, LeftHandStates, RightHandStates


# ── 右手 recorder_name 命名工具 ──────────────────────────────────
# 西班牙指法 → 控制器名映射
_FINGER_MAP = {
    "T_R": "p",   # 拇指 (pulgar)
    "I_R": "i",   # 食指 (índice)
    "M_R": "m",   # 中指 (medio)
    "R_R": "a",   # 无名指 (anular)
    "P_R": "ch",  # 小指 (chico)
}

# 有效的右手状态名称（用于校验从 recorder_name 中提取的 state）
_VALID_RIGHT_STATES = {"low", "end", "high", "release", "up", "down"}


def _compute_right_recorder_name(state_value: str, ctrl_name: str,
                                 use_vibrato_bar: bool) -> str:
    """从内部状态名和控制器名计算导出用的 recorder_name"""
    if ctrl_name == "H_R":
        if state_value in ("release", "up", "down"):
            return f"Vibrato_{state_value.capitalize()}_H_R"
        return f"Normal_P{state_value}_H_R"
    elif ctrl_name == "HP_R":
        if state_value in ("release", "up", "down"):
            return f"Vibrato_{state_value.capitalize()}_HP_R"
        return f"Normal_P{state_value}_HP_R"
    else:
        finger = _FINGER_MAP.get(ctrl_name)
        if finger is None:
            return ctrl_name
        return f"{finger}{state_value}"


def _parse_right_recorder_name(recorder_name: str) -> tuple[str, str] | None:
    """从 recorder_name 反推出 (state_value, ctrl_name)"""
    import re
    m = re.match(r"(?:Normal_P|Vibrato_)(\w+)_(H_R|HP_R)$", recorder_name)
    if m:
        state = m.group(1).lower()
        return (state, m.group(2))

    reverse_map = {v: k for k, v in _FINGER_MAP.items()}
    for suffix, ctrl_name in reverse_map.items():
        if recorder_name.startswith(suffix):
            state = recorder_name[len(suffix):]
            if state in _VALID_RIGHT_STATES:
                return (state, ctrl_name)

    return None


class IOManager:
    """输入输出管理类 - 负责骨骼自定义属性与 JSON 文件之间的转换导出"""

    # ── 导出 ──────────────────────────────────────────────────

    def export_controller_info(self, file_name: str, target_skeleton) -> None:
        """将控制器状态从骨骼自定义属性导出为 JSON 文件

        内容结构 → 与 `婕德_unreal.json` 一致（文件名不带 `_unreal`）。
        """
        # 1) 从骨骼读取内部数据
        data = self.get_all_controller_data(target_skeleton)
        result = io_utils.nested_dict()

        # 2) 左手 → NORMAL/OUTER/INNER/BARRE_LEFT_HAND_POSITIONS
        print("导出左手控制器信息...")
        left_hand_data = data.get("left_hand", {})
        for pos_name, pos_data in left_hand_data.items():
            for state_name, state_data in pos_data.items():
                if state_name.upper() == "NORMAL":
                    section = "NORMAL_LEFT_HAND_POSITIONS"
                elif state_name.upper() == "OUTER":
                    section = "OUTER_LEFT_HAND_POSITIONS"
                elif state_name.upper() == "INNER":
                    section = "INNER_LEFT_HAND_POSITIONS"
                elif state_name.upper() == "BARRE":
                    section = "BARRE_LEFT_HAND_POSITIONS"
                else:
                    continue
                for ctrl_name, ctrl_data in state_data.items():
                    result[section][pos_name][ctrl_name] = {
                        "position": ctrl_data.get("location", [0, 0, 0]),
                        "rotation": ctrl_data.get("rotation", [1, 0, 0, 0]),
                    }

        # 3) 指板位置（从物理物体读，与旧逻辑一致）
        print("导出指板位置记录器信息...")
        for position_enum, marker_name in self.guitar_fret_positions.items():
            obj = bpy.data.objects.get(self.obj_name(marker_name))
            if obj:
                result["LEFT_FINGER_POSITIONS"][position_enum] = list(
                    obj.location)

        # 4) 右手 → RIGHT_HAND_POSITIONS
        print("导出右手控制器信息...")
        right_hand_data = data.get("right_hand", {})
        for state_value, state_data in right_hand_data.items():
            for ctrl_name, ctrl_data in state_data.items():
                rname = _compute_right_recorder_name(
                    state_value, ctrl_name, self.use_vibrato_bar)
                result["RIGHT_HAND_POSITIONS"][rname] = {
                    "position": ctrl_data.get("location", [0, 0, 0]),
                    "rotation": ctrl_data.get("rotation", [1, 0, 0, 0]),
                }

        # 5) 其他设置（从骨骼读演奏者设置，保持无状态）
        settings = self.load_settings(target_skeleton)
        result["OTHER_SETTING"] = {
            "is_unreal": False,
            "use_vibrato_bar": settings["use_vibrato_bar"],
        }

        io_utils.save_json(file_name, result)
        print(f"控制器信息已导出到 {file_name}")

    # ── 导入 ──────────────────────────────────────────────────

    def import_controller_info(self, file_name: str, target_skeleton) -> None:
        """将 JSON 文件中的控制器状态导入到骨骼自定义属性

        旧格式 → 内部格式。
        """
        if not os.path.exists(file_name):
            raise FileNotFoundError(f"找不到文件: {file_name}")
        with open(file_name, "r", encoding="utf-8") as f:
            result = json.load(f)

        # 初始化内部数据结构
        data = {}
        data["left_hand"] = {}
        data["right_hand"] = {}

        # 1) 左手: NORMAL/OUTER/INNER/BARRE_LEFT_HAND_POSITIONS
        _left_section_map = {
            "NORMAL_LEFT_HAND_POSITIONS": (BasePositions, LeftHandStates.NORMAL),
            "OUTER_LEFT_HAND_POSITIONS": (BasePositions, LeftHandStates.OUTER),
            "INNER_LEFT_HAND_POSITIONS": (BasePositions, LeftHandStates.INNER),
            "BARRE_LEFT_HAND_POSITIONS": (BasePositions, LeftHandStates.BARRE),
        }
        for section, (pos_enum, state) in _left_section_map.items():
            section_data = result.get(section, {})
            for pos_name, pos_data in section_data.items():
                state_name = state.name  # "NORMAL" / "OUTER" / "INNER" / "BARRE"
                if pos_name not in data["left_hand"]:
                    data["left_hand"][pos_name] = {}
                if state_name not in data["left_hand"][pos_name]:
                    data["left_hand"][pos_name][state_name] = {}
                for ctrl_name, ctrl_info in pos_data.items():
                    data["left_hand"][pos_name][state_name][ctrl_name] = {
                        "location": ctrl_info.get("position", [0, 0, 0]),
                        "rotation": ctrl_info.get("rotation", [1, 0, 0, 0]),
                    }

        # 2) 指板位置 → 写入物理物体
        print("导入指板位置记录器信息...")
        fret_positions = result.get("LEFT_FINGER_POSITIONS", {})
        for position_enum, marker_name in self.guitar_fret_positions.items():
            loc = fret_positions.get(position_enum)
            full = self.obj_name(marker_name)
            if loc and full in bpy.data.objects:
                bpy.data.objects[full].location = loc

        # 3) 右手: RIGHT_HAND_POSITIONS
        print("导入右手控制器信息...")
        rh_data = result.get("RIGHT_HAND_POSITIONS", {})

        # 收集所有已知的右手控制器名，用于 raw 名称 fallback
        all_right_ctrl_names = set(self.right_hand_controllers.values())
        all_right_ctrl_names.update(self.right_finger_controllers.values())

        current_state = None  # 追踪当前 state，用于 raw 控制器名推断
        for rname, ctrl_info in rh_data.items():
            parsed = _parse_right_recorder_name(rname)
            if parsed is not None:
                state_value, ctrl_name = parsed
                current_state = state_value  # 更新当前 state
            else:
                # Fallback: 检查是否是原始控制器名（如 I_R, M_R 等）
                # 使用最近一次正确解析的 state 来推断
                if rname in all_right_ctrl_names and current_state is not None:
                    state_value = current_state
                    ctrl_name = rname
                    print(
                        f"  ✓ 使用当前 state '{state_value}' 推断 raw 控制器名: {rname}")
                else:
                    print(f"  警告: 无法解析右手 recorder_name: {rname}")
                    continue

            if state_value not in data["right_hand"]:
                data["right_hand"][state_value] = {}
            data["right_hand"][state_value][ctrl_name] = {
                "location": ctrl_info.get("position", [0, 0, 0]),
                "rotation": ctrl_info.get("rotation", [1, 0, 0, 0]),
            }

        # 4) 其他设置
        other = result.get("OTHER_SETTING", {})
        settings = self.load_settings(target_skeleton)
        data["instruments"] = data.get("instruments", settings["instrument"])
        data["use_vibrato_bar"] = other.get(
            "use_vibrato_bar", settings["use_vibrato_bar"])

        # 5) 写回骨骼：数据 + 演奏者设置（无状态化，与骨骼属性保持同步）
        self.set_all_controller_data(target_skeleton, data)
        self.save_settings(target_skeleton, data["instruments"],
                           data["use_vibrato_bar"])
        print(f"控制器信息已导入到 {target_skeleton.name}")
