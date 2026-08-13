# beat_bloom/config.py
"""BeatBloom 乐器模块 —— 配置与控件创建

基础控件 9 个：手掌 × 2、IK Pivot × 2、脚部 × 2、
特殊朝向（Middle_Hand / Look_At / Head_Control）× 3。
辅助控件（仅创建/驱动，不参与 save/load/export/import 数据传递）：
- 左右手五指控制器 + ext 辅助控件（挂在手掌 H_L/H_R 下）、
  各手指 pole target（挂在对应 ext 下，拇指 TP_L/TP_R，其余 <手指>_pole）
- 左右脚 pole target（FP_L / FP_R，与脚控件同级）
所有控件名带演奏者后缀（<短名>_<suffix>），通过 obj_name / obj 方法访问。
"""

import json

import bpy  # type: ignore

from ..common import performer_utils as _pu
from ..common import object_utils

from .enums import LIMB_CONTROLLERS


# 骨骼自定义属性键
DRUMKIT_KEY = "beat_bloom_drumkit_config"


class BeatBloomConfig:
    """BeatBloom 配置：命名表 + 控件创建 + setup（多演奏者命名空间）"""

    def __init__(self, performer_suffix: str = "",
                 target_skeleton=None):
        self.suffix: str = performer_suffix
        self.target_skeleton = target_skeleton
        self.instruments_name: str = "beat_bloom"

        self.hand_controllers = {
            "left_hand_controller":          "H_L",
            "right_hand_controller":         "H_R",
            "left_hand_ik_pivot":            "HP_L",
            "right_hand_ik_pivot":           "HP_R",
        }

        self.foot_controllers = {
            "left_foot_controller":          "F_L",
            "right_foot_controller":         "F_R",
        }

        # 左右手五指控制器（辅助控件，仅创建，不参与数据传递）
        self.finger_controllers = {
            "left_thumb":   "T_L",
            "left_index":   "I_L",
            "left_middle":  "M_L",
            "left_ring":    "R_L",
            "left_little":  "P_L",
            "right_thumb":  "T_R",
            "right_index":  "I_R",
            "right_middle": "M_R",
            "right_ring":   "R_R",
            "right_little": "P_R",
        }

        # 左右脚 pole target（与脚控件同级，仅创建，不参与数据传递）
        self.foot_pole_controllers = {
            "left_foot_pole":    "FP_L",
            "right_foot_pole":   "FP_R",
        }

        # Middle_Hand 不挂根（用实时计算中点驱动位置），Look_At 挂 Middle_Hand，Head_Control 挂 TrackTo
        self.special_controllers = {
            "middle_hand":  "Middle_Hand",
            "look_at":      "Look_At",
            "head_control": "Head_Control",
        }

    # ── 命名辅助 ─────────────────────────────────────────────────

    def obj_name(self, short: str) -> str:
        """短名 → 完整对象名（带演奏者后缀）"""
        return _pu.resolve(short, self.suffix)

    def obj(self, short: str):
        """按短名取对象（带演奏者后缀）"""
        return bpy.data.objects.get(self.obj_name(short))

    def limb_controller_shorts(self, limb: str) -> list[str]:
        """肢体名 → 该肢体的控制器短名列表"""
        return LIMB_CONTROLLERS.get(limb, [])

    # ── 手指 / ext / pole 命名 ──────────────────────────────────

    def finger_shorts_for_hand(self, hand: str) -> list[str]:
        """手缩写（L/R）→ 该手 5 个手指控制器短名，如 'L' → ['T_L','I_L','M_L','R_L','P_L']"""
        return [f"{base}_{hand}" for base in ["T", "I", "M", "R", "P"]]

    def ext_short(self, finger_short: str) -> str:
        """手指短名 → ext 辅助控件短名：'T_L' → 'ext_T_L'"""
        return f"ext_{finger_short}"

    def finger_pole_short(self, finger_short: str) -> str:
        """手指短名 → pole target 短名：拇指 'TP_L'/'TP_R'，其余 '<手指>_pole'"""
        if finger_short.startswith("T_"):
            return f"TP_{finger_short[2:]}"
        return f"{finger_short}_pole"

    # ── Drumkit 配置读取 ─────────────────────────────────────────

    def drumkit_config(self) -> dict | None:
        """从骨骼自定义属性读取 drumkit 配置，返回 dict；缺失返回 None"""
        if self.target_skeleton is None:
            return None
        raw = self.target_skeleton.get(DRUMKIT_KEY)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_drumkit_config(self, drumkit_dict: dict) -> None:
        """将 drumkit 配置序列化写入骨骼自定义属性"""
        if self.target_skeleton is None:
            return
        self.target_skeleton[DRUMKIT_KEY] = json.dumps(
            drumkit_dict, ensure_ascii=False)

    # ── 控件创建 ─────────────────────────────────────────────────

    def setup_all_objects(self) -> None:
        """创建/更新基础控件 + 辅助控件（手指/ext/pole），并完成集合层级、ext 驱动和特殊约束设置"""
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        addons_coll = performer_utils_find_addons(self.suffix)
        if addons_coll is None:
            print("[ERROR] 未找到 addons 目录，请先新建角色（初始化角色）。")
            return

        controllers_coll = object_utils.get_or_create_collection(
            _pu.resolve("Controllers", self.suffix), addons_coll)

        hand_coll = object_utils.get_or_create_collection(
            _pu.resolve("Hand_Controllers", self.suffix), controllers_coll)
        foot_coll = object_utils.get_or_create_collection(
            _pu.resolve("Foot_Controllers", self.suffix), controllers_coll)
        special_coll = object_utils.get_or_create_collection(
            _pu.resolve("Special_Controllers", self.suffix), controllers_coll)

        for short in self.hand_controllers.values():
            object_utils.create_or_update_object(
                self.obj_name(short), "cube", hand_coll)

        for short in self.foot_controllers.values():
            object_utils.create_or_update_object(
                self.obj_name(short), "cube", foot_coll)

        for short in self.special_controllers.values():
            object_utils.create_or_update_object(
                self.obj_name(short), "cube", special_coll)

        # 辅助控件：手指 + ext + pole（仅创建/驱动，不参与数据传递）
        self.add_finger_ext_and_poles(hand_coll)
        self.add_foot_poles(foot_coll)
        self.add_ext_drivers()

        self._setup_special_constraints()
        print("✓ BeatBloom 控件已就绪")

    def _setup_special_constraints(self) -> None:
        """设置 Look_At 父子关系 + Head_Control TrackTo 约束"""
        middle = self.obj("Middle_Hand")
        look_at = self.obj("Look_At")
        head = self.obj("Head_Control")

        if not all([middle, look_at, head]):
            print("  ✗ 找不到特殊控制器对象，跳过约束设置")
            return

        # Look_At 挂到 Middle_Hand 下
        if look_at.parent != middle:
            look_at.parent = middle

        # Head_Control 清除旧约束并添加 TrackTo
        for c in list(head.constraints):
            head.constraints.remove(c)
        track = head.constraints.new('TRACK_TO')
        track.name = "Track_Look_At"
        track.target = look_at
        track.track_axis = 'TRACK_Z'
        track.up_axis = 'UP_Y'
        print("  ✓ 特殊朝向控制器约束已设置")

    # ── 手指 / ext / pole 辅助控件（仅创建/驱动，不参与数据传递）──

    def add_finger_ext_and_poles(self, hand_coll) -> None:
        """创建左右手五指控制器 + ext 辅助控件 + 各手指 pole target：

        - 手指控制器与 ext 辅助控件都挂在手掌（H_L / H_R）下
        - 每个手指的 pole target 挂在对应的 ext 控件下
        """
        print("\n添加手指 ext 辅助控件与 pole target...")
        for hand in ["L", "R"]:
            palm = self.obj(f"H_{hand}")
            if palm is None:
                print(f"  • 手掌 H_{hand} 不存在，跳过该手")
                continue
            for finger_short in self.finger_shorts_for_hand(hand):
                # 手指控制器（挂在手掌下）
                finger_obj = object_utils.create_or_update_object(
                    self.obj_name(finger_short), "cube", hand_coll)
                if finger_obj and finger_obj.parent != palm:
                    finger_obj.parent = palm

                # ext 辅助控件（挂在手掌下，与手指同级，略小以便区分）
                ext_short = self.ext_short(finger_short)
                ext_obj = object_utils.create_or_update_object(
                    self.obj_name(ext_short), "cube", hand_coll, scale=0.7)
                if ext_obj and ext_obj.parent != palm:
                    ext_obj.parent = palm

                # pole target（挂在对应 ext 下）
                pole_short = self.finger_pole_short(finger_short)
                pole_obj = object_utils.create_or_update_object(
                    self.obj_name(pole_short), "circle", hand_coll)
                if pole_obj:
                    if pole_obj.parent != ext_obj:
                        pole_obj.parent = ext_obj
                    pole_obj.location = (0, 0, 1.0)
                    print(
                        f"  ✓ {self.obj_name(pole_short)} → {self.obj_name(ext_short)}")
        print("  ✓ 手指 ext 辅助控件与 pole target 创建完成")

    def add_foot_poles(self, foot_coll) -> None:
        """创建左右脚 pole target（FP_L / FP_R，与脚控件同级）"""
        print("\n添加脚部 pole target...")
        for short in self.foot_pole_controllers.values():
            object_utils.create_or_update_object(
                self.obj_name(short), "circle", foot_coll)
        print("  ✓ 脚部 pole target 创建完成")

    def add_ext_drivers(self) -> None:
        """为每个手指的 ext 辅助控件添加 location 驱动（幂等）"""
        print("\n添加手指 ext 控制器驱动...")
        for hand in ["L", "R"]:
            for finger_short in self.finger_shorts_for_hand(hand):
                self._add_ext_driver(finger_short)
        print("  ✓ 手指 ext 控制器驱动设置完成")

    def _add_ext_driver(self, finger_short: str) -> None:
        """为单个手指的 ext 辅助控件添加 location 驱动：ext = 2 * finger（LOCAL_SPACE）"""
        ext_short = self.ext_short(finger_short)
        ext_obj = self.obj(ext_short)
        finger_obj = self.obj(finger_short)
        if finger_obj is None:
            print(f"  • 手指控制器 {finger_short} 不存在，跳过驱动")
            return
        if ext_obj is None:
            print(f"  • ext 控件 {ext_short} 不存在，跳过驱动")
            return

        # 清除已有的 location 驱动（保证可重复运行）
        if ext_obj.animation_data and ext_obj.animation_data.drivers:
            for axis_index in range(3):
                fcurve = ext_obj.animation_data.drivers.find(
                    "location", index=axis_index)
                if fcurve:
                    ext_obj.animation_data.drivers.remove(fcurve)

        for axis_index, axis_char in enumerate(['X', 'Y', 'Z']):
            driver = ext_obj.driver_add("location", axis_index).driver
            driver.type = 'SCRIPTED'

            var_f = driver.variables.new()
            var_f.name = "finger"
            var_f.type = 'TRANSFORMS'
            target_f = var_f.targets[0]
            target_f.id = finger_obj
            target_f.transform_type = f'LOC_{axis_char}'
            target_f.transform_space = 'LOCAL_SPACE'
            driver.expression = "2 * finger"

        print(
            f"  ✓ 已为 {self.obj_name(ext_short)} 添加驱动: ext = 2*{finger_short}")


def performer_utils_find_addons(suffix: str):
    """获取演奏者的 addons 集合（无后缀时回退到全局 addons）"""
    if suffix:
        return _pu.find_addons_collection(suffix)
    return object_utils.get_or_create_collection("addons")
