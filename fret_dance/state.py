# fret_dance/state.py
"""FretDance 乐器模块 —— 状态传输（迁移自 fret_dance_blender/state_transfer.py）

控制器 ↔ 骨骼自定义属性(JSON) 之间的数据传输。
通用搬运用 common.state_io。
"""

from ..common.performer_utils import resolve as _pu_resolve
from .enums import BasePositions, LeftHandStates, RightHandStates, Instruments


def _get_data(mesh_obj) -> dict:
    """从骨骼自定义属性读取完整 JSON 数据（FretDance 状态键）"""
    if mesh_obj is None:
        return {}
    raw = mesh_obj.get("fret_dance_controller_data")
    if not raw:
        return {}
    try:
        import json
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _set_data(mesh_obj, data: dict) -> None:
    """将完整 JSON 数据写入骨骼自定义属性"""
    if mesh_obj is None:
        return
    import json
    mesh_obj["fret_dance_controller_data"] = json.dumps(
        data, ensure_ascii=False)


def _read_controller(suffix: str, ctrl_name: str) -> dict:
    """读取单个控制器的当前位置和旋转（四元数）"""
    import bpy  # type: ignore
    ctrl = bpy.data.objects.get(_pu_resolve(ctrl_name, suffix))
    if ctrl is None:
        return {"location": [0.0, 0.0, 0.0], "rotation": [1.0, 0.0, 0.0, 0.0]}
    quat = ctrl.rotation_quaternion if ctrl.rotation_mode == "QUATERNION" else ctrl.rotation_euler.to_quaternion()
    return {
        "location": [ctrl.location.x, ctrl.location.y, ctrl.location.z],
        "rotation": [quat.w, quat.x, quat.y, quat.z],
    }


def _write_controller(suffix: str, ctrl_name: str, ctrl_data: dict) -> None:
    """将位置和旋转写入控制器"""
    import bpy  # type: ignore
    ctrl = bpy.data.objects.get(_pu_resolve(ctrl_name, suffix))
    if ctrl is None:
        return
    loc = ctrl_data.get("location", [0.0, 0.0, 0.0])
    rot = ctrl_data.get("rotation", [1.0, 0.0, 0.0, 0.0])
    ctrl.location = (loc[0], loc[1], loc[2])
    ctrl.rotation_mode = "QUATERNION"
    ctrl.rotation_quaternion = (rot[0], rot[1], rot[2], rot[3])


class StateTransfer:
    """状态传输类 - 负责控制器与骨骼自定义属性(JSON)之间的数据传输"""

    # ── 左手状态传输 ──────────────────────────────────────────

    def transfer_left_hand_state(
        self,
        base_position: BasePositions,
        left_hand_state: LeftHandStates,
        target_skeleton,
        direction: str = "set",
    ) -> bool:
        pos_name = base_position.value
        state_name = left_hand_state.name

        print(
            f"{'设置' if direction == 'set' else '加载'}左手位置: {pos_name}, 状态: {state_name}")

        if base_position in self.invalid_combinations and left_hand_state in self.invalid_combinations[base_position]:
            print(f"警告: {pos_name} 位置不支持 {state_name} 状态")
            return False

        all_controllers = list(self.left_hand_controllers.values())
        all_controllers.extend(self.left_finger_controllers.values())

        if direction == "set":
            data = _get_data(target_skeleton)
            if "left_hand" not in data:
                data["left_hand"] = {}
            if pos_name not in data["left_hand"]:
                data["left_hand"][pos_name] = {}

            for ctrl_name in all_controllers:
                ctrl_data = _read_controller(self.suffix, ctrl_name)
                if state_name not in data["left_hand"][pos_name]:
                    data["left_hand"][pos_name][state_name] = {}
                data["left_hand"][pos_name][state_name][ctrl_name] = ctrl_data

            data["instruments"] = int(self.instruments)
            data["use_vibrato_bar"] = self.use_vibrato_bar
            _set_data(target_skeleton, data)
            print(f"  已保存 {len(all_controllers)} 个控制器到 {target_skeleton.name}")
        else:
            data = _get_data(target_skeleton)
            loaded_count = 0
            for ctrl_name in all_controllers:
                ctrl_data = (
                    data.get("left_hand", {})
                    .get(pos_name, {})
                    .get(state_name, {})
                    .get(ctrl_name)
                )
                if ctrl_data is not None:
                    _write_controller(self.suffix, ctrl_name, ctrl_data)
                    loaded_count += 1
            print(f"  已加载 {loaded_count} 个控制器从 {target_skeleton.name}")

        print(
            f"左手{('设置' if direction == 'set' else '加载')}完成: {pos_name} + {state_name}")
        return True

    # ── 右手状态传输 ──────────────────────────────────────────

    def transfer_right_hand_state(
        self,
        right_hand_state: RightHandStates,
        target_skeleton,
        direction: str = "set",
    ) -> bool:
        state_value = right_hand_state.value

        print(f"{'设置' if direction == 'set' else '加载'}右手位置: {state_value}")

        all_controllers = list(self.right_hand_controllers.values())
        all_controllers.extend(self.right_finger_controllers.values())

        if direction == "set":
            data = _get_data(target_skeleton)
            if "right_hand" not in data:
                data["right_hand"] = {}

            for ctrl_name in all_controllers:
                ctrl_data = _read_controller(self.suffix, ctrl_name)
                if state_value not in data["right_hand"]:
                    data["right_hand"][state_value] = {}
                data["right_hand"][state_value][ctrl_name] = ctrl_data

            data["instruments"] = int(self.instruments)
            data["use_vibrato_bar"] = self.use_vibrato_bar
            _set_data(target_skeleton, data)
            print(f"  已保存 {len(all_controllers)} 个控制器到 {target_skeleton.name}")
        else:
            data = _get_data(target_skeleton)
            loaded_count = 0
            for ctrl_name in all_controllers:
                ctrl_data = (
                    data.get("right_hand", {})
                    .get(state_value, {})
                    .get(ctrl_name)
                )
                if ctrl_data is not None:
                    _write_controller(self.suffix, ctrl_name, ctrl_data)
                    loaded_count += 1
            print(f"  已加载 {loaded_count} 个控制器从 {target_skeleton.name}")

        print(
            f"右手{('设置' if direction == 'set' else '加载')}完成: {state_value}")
        return True

    # ── IOManager 接口 ────────────────────────────────────────

    def get_all_controller_data(self, target_skeleton) -> dict:
        return _get_data(target_skeleton)

    def set_all_controller_data(self, target_skeleton, data: dict) -> None:
        _set_data(target_skeleton, data)

    # ── 演奏者设置（插件无状态化） ────────────────────────────

    def load_settings(self, skeleton) -> dict:
        """从骨骼读演奏者设置（乐器类型 / 是否摇把），供 UI 回填"""
        if skeleton is None:
            return {"instrument": int(self.instruments),
                    "use_vibrato_bar": self.use_vibrato_bar}
        instrument = skeleton.get("fret_dance_instrument")
        if instrument is None:
            instrument = int(self.instruments)
        vibrato = skeleton.get("fret_dance_use_vibrato_bar")
        if vibrato is None:
            vibrato = self.use_vibrato_bar
        return {"instrument": int(instrument), "use_vibrato_bar": bool(vibrato)}

    def save_settings(self, skeleton, instrument: int, use_vibrato_bar: bool) -> None:
        """把演奏者设置写回骨骼（乐器类型 / 是否摇把）"""
        if skeleton is None:
            return
        skeleton["fret_dance_instrument"] = int(instrument)
        skeleton["fret_dance_use_vibrato_bar"] = bool(use_vibrato_bar)
