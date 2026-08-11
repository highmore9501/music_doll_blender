# wind_rise/config.py
"""WindRise 乐器模块 —— 控件配置与场景对象管理"""

import bpy  # type: ignore

from ..common import performer_utils
from ..common import object_utils
from ..common import instrument_base
from .enums import (
    HANDS,
    FINGER_CONTROLLER_BASES,
    POLE_CONTROLLER_BASES,
    iter_hand_controllers,
    iter_finger_controllers,
    iter_pole_controllers,
    iter_foot_controllers,
    make_controller_name,
    make_pole_controller_name,
    make_ext_controller_name,
    get_ext_name_for_pole,
)

_INSTRUMENT_ID = "wind_rise"


class WindRiseConfig:
    """WindRise 控件配置与场景对象管理。"""

    def __init__(self, performer_suffix: str = "",
                 target_skeleton=None, target_instrument=None):
        self.suffix: str = performer_suffix
        self.target_skeleton = target_skeleton
        self.target_instrument = target_instrument
        self.instruments_name = _INSTRUMENT_ID

    # ── 命名辅助 ──────────────────────────────────────────────

    def obj_name(self, short: str) -> str:
        return performer_utils.resolve(short, self.suffix)

    def obj(self, short: str):
        return bpy.data.objects.get(self.obj_name(short))

    # ── addons 集合 ───────────────────────────────────────────

    def _get_addons_collection(self):
        if self.suffix:
            return performer_utils.find_addons_collection(self.suffix)
        return object_utils.get_or_create_collection("addons")

    # ── 演奏者结构 ────────────────────────────────────────────

    def _get_performer_collection(self):
        if not self.suffix:
            return None
        return performer_utils.get_performer(self.suffix)

    def _organize_body(self):
        if not self.suffix:
            return
        performer = self._get_performer_collection()
        if performer is None:
            return
        body_coll = performer_utils.get_or_create_collection(
            self.suffix, "Body", parent=performer.collection)
        skeleton = self.target_skeleton or performer.target_skeleton
        if skeleton is None:
            return
        object_utils.move_object_to_collection(skeleton, body_coll)
        for child in list(skeleton.children):
            if child.type == "MESH":
                object_utils.move_object_to_collection(child, body_coll)
                if child.parent != skeleton:
                    child.parent = skeleton

    def _organize_instrument(self):
        if not self.suffix:
            return
        inst = self.target_instrument
        if inst is None:
            return
        performer = self._get_performer_collection()
        if performer is None:
            return
        inst_coll = performer_utils.get_or_create_collection(
            self.suffix, "Instruments", parent=performer.collection)
        object_utils.move_object_to_collection(inst, inst_coll)

    def _organize_performer_root(self):
        """创建演奏者根 WR_<名>，挂接骨骼、controller_root、脚部控件和 Breath_Control。"""
        if not self.suffix:
            return
        performer = self._get_performer_collection()
        if performer is None:
            return
        root_obj = performer_utils.get_or_create_performer_root(
            performer, performer.collection)

        skeleton = self.target_skeleton or performer.target_skeleton
        object_utils.parent_to(root_obj, skeleton)
        object_utils.parent_to(root_obj, self.obj("controller_root"))
        for short in ["F_L", "FP_L", "F_R", "FP_R", "Breath_Control"]:
            child = self.obj(short)
            if child is not None:
                object_utils.parent_to(root_obj, child)

    # ── 控件创建 ──────────────────────────────────────────────

    def add_controllers(self):
        """创建所有控件（带演奏者后缀，幂等）。"""
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        addons = self._get_addons_collection()
        if addons is None:
            print("[WindRise] 未找到 addons 目录，请先在「角色生成器」初始化角色。")
            return

        ctrl_coll = object_utils.get_or_create_collection(
            self.obj_name("Controllers"), addons)
        hand_coll = object_utils.get_or_create_collection(
            self.obj_name("Hand_Controllers"), ctrl_coll)
        foot_coll = object_utils.get_or_create_collection(
            self.obj_name("Foot_Controllers"), ctrl_coll)
        head_coll = object_utils.get_or_create_collection(
            self.obj_name("Head_Controllers"), ctrl_coll)
        breath_coll = object_utils.get_or_create_collection(
            self.obj_name("Breath_Controllers"), ctrl_coll)

        # controller_root → controller_root_offset
        self._make_obj("controller_root", "sphere", ctrl_coll, size=0.05)
        self._make_obj("controller_root_offset",
                       "sphere", ctrl_coll, size=0.05)
        cr = self.obj("controller_root")
        cro = self.obj("controller_root_offset")
        if cr and cro:
            cro.parent = cr

        # 手部控制器（父级 = controller_root_offset）
        for ctrl_short in iter_hand_controllers():
            self._make_obj(ctrl_short, "cube", hand_coll, size=0.04)
            o = self.obj(ctrl_short)
            if o and cro:
                o.parent = cro

        # ext 辅助控件（父级 = controller_root_offset）
        for hand in HANDS:
            for base in FINGER_CONTROLLER_BASES:
                ext_short = f"ext_{base}_{hand}"
                self._make_obj(ext_short, "cube", hand_coll, size=0.03)
                o = self.obj(ext_short)
                if o and cro:
                    o.parent = cro

        # pole 控件（父级 = 对应 ext）
        for hand in HANDS:
            for base in POLE_CONTROLLER_BASES:
                pole_short = f"{base}_{hand}_pole"
                self._make_obj(pole_short, "sphere", hand_coll, size=0.02)
                pole = self.obj(pole_short)
                ext_short = f"ext_{base}_{hand}"
                ext_obj = self.obj(ext_short)
                if pole:
                    pole.parent = ext_obj if ext_obj else cro

        # 脚部控制器（父级由 _organize_performer_root 挂接）
        for ctrl_short in iter_foot_controllers():
            self._make_obj(ctrl_short, "cube", foot_coll, size=0.04)

        # Head_Control（父级 = controller_root）
        self._make_obj("Head_Control", "sphere", head_coll, size=0.05)
        head = self.obj("Head_Control")
        if head and cr:
            head.parent = cr

        # Breath_Control（父级由 _organize_performer_root 挂接）
        self._make_obj("Breath_Control", "sphere", breath_coll, size=0.05)

    def _make_obj(self, short: str, obj_type: str, collection,
                  size: float = 0.04):
        full_name = self.obj_name(short)
        obj = object_utils.create_or_update_object(
            full_name, obj_type, collection, rotation_mode="QUATERNION",
            scale=size)
        return obj

    # ── ext driver ────────────────────────────────────────────

    def add_ext_drivers(self):
        """为所有 ext 辅助控件添加 2×手指-手掌 的位置驱动（LOCAL_SPACE，幂等）。"""
        for hand in HANDS:
            palm_short = f"H_{hand}"
            palm_obj = self.obj(palm_short)
            for base in FINGER_CONTROLLER_BASES:
                finger_short = f"{base}_{hand}"
                self._add_single_ext_driver(finger_short, palm_obj)

    def _add_single_ext_driver(self, finger_short: str, palm_obj) -> None:
        ext_short = f"ext_{finger_short}"
        finger_obj = self.obj(finger_short)
        ext_obj = self.obj(ext_short)
        if finger_obj is None or ext_obj is None:
            return

        # 先清除已有的 location driver（幂等）
        if ext_obj.animation_data and ext_obj.animation_data.drivers:
            for axis_index in range(3):
                fc = ext_obj.animation_data.drivers.find(
                    "location", index=axis_index)
                if fc:
                    ext_obj.animation_data.drivers.remove(fc)

        for axis_index, axis_char in enumerate(["X", "Y", "Z"]):
            driver = ext_obj.driver_add("location", axis_index).driver
            driver.type = "SCRIPTED"

            var_f = driver.variables.new()
            var_f.name = "finger"
            var_f.type = "TRANSFORMS"
            target_f = var_f.targets[0]
            target_f.id = finger_obj
            target_f.transform_type = f"LOC_{axis_char}"
            target_f.transform_space = "LOCAL_SPACE"

            if palm_obj is not None:
                var_p = driver.variables.new()
                var_p.name = "palm"
                var_p.type = "TRANSFORMS"
                target_p = var_p.targets[0]
                target_p.id = palm_obj
                target_p.transform_type = f"LOC_{axis_char}"
                target_p.transform_space = "LOCAL_SPACE"
                driver.expression = "2 * finger - palm"
            else:
                driver.expression = "2 * finger"

    # ── setup_all_objects ─────────────────────────────────────

    def setup_all_objects(self) -> bool:
        """创建/刷新所有控件并组织演奏者目录结构（幂等）。"""
        if self.suffix and performer_utils.find_addons_collection(self.suffix) is None:
            print("[WindRise][ERROR] 未找到角色 addons 目录，请先在「角色生成器」初始化角色。")
            return False

        self._organize_body()
        self._organize_instrument()
        self.add_controllers()
        self.add_ext_drivers()
        self._organize_performer_root()
        return True

    # ── 演奏者设置（乐器类型、音域）存骨骼 ───────────────────────

    def save_settings(self, skeleton, instrument_type: str, description: str,
                      min_note: int, max_note: int) -> None:
        from ..common import state_io
        data = state_io.get_state_data(skeleton, "wind_rise_state_data") or {}
        config = data.get("config", {})
        config["instrument_type"] = instrument_type
        config["description"] = description
        config["min_note"] = min_note
        config["max_note"] = max_note
        data["config"] = config
        state_io.set_state_data(skeleton, "wind_rise_state_data", data)

    def load_settings(self, skeleton) -> dict:
        from ..common import state_io
        data = state_io.get_state_data(skeleton, "wind_rise_state_data") or {}
        return data.get("config", {})
