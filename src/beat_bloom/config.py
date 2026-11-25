# beat_bloom/config.py
"""BeatBloom 乐器模块 —— 配置与控件创建

基础控件：手掌 × 2、IK Pivot × 2、脚部 × 2、
特殊朝向（Middle_Hand / Look_At / Head_Control）× 3。
辅助控件（仅创建/驱动，不参与 save/load/export/import 数据传递）：
- 左右手五指控制器 + ext 辅助控件（挂在手掌 H_L/H_R 下）、
  各手指 pole target（挂在对应 ext 下，命名与 Unreal 端一致：T_pole_L / I_pole_L 等）
- 左右脚 pole target（FP_L / FP_R，与脚控件同级）
所有控件名带演奏者后缀（<短名>_<suffix>），通过 obj_name / obj 方法访问。
"""

import json

import bpy  # type: ignore

from ..common import performer_utils as _pu
from ..common import object_utils
from ..common import ext_utils

from .enums import LIMB_CONTROLLERS


# 骨骼自定义属性键
DRUMKIT_KEY = "beat_bloom_drumkit_config"

# 五指短名主体（手指 / ext / pole 命名共用）
FINGER_BASES = ["T", "I", "M", "R", "P"]


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

        # 鼓槌控件：分别挂在左右手掌下，需要参与导入导出（位置+旋转）
        self.stick_controllers = {
            "left_stick": "stick_L",
            "right_stick": "stick_R",
        }

        # 左右脚 pole target（与脚控件同级，仅创建，不参与数据传递）
        self.foot_pole_controllers = {
            "left_foot_pole":    "FP_L",
            "right_foot_pole":   "FP_R",
        }

        # Middle_Hand：双手中点（位置由动画关键帧提供，不挂驱动器）
        # Look_At 挂 Middle_Hand，Head_Control 挂 TrackTo
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
        return [f"{base}_{hand}" for base in FINGER_BASES]

    def ext_short(self, finger_short: str) -> str:
        """手指短名 → ext 辅助控件短名：'T_L' → 'ext_T_L'"""
        return f"ext_{finger_short}"

    def finger_pole_short(self, finger_short: str) -> str:
        """手指短名 → pole target 短名（与 Unreal 端一致）：'T_L' → 'T_pole_L'，'I_L' → 'I_pole_L'"""
        return f"{finger_short[0]}_pole_{finger_short[2:]}"

    def get_pole_controller_shorts(self) -> list:
        """手指 pole 短名（挂在 ext 下，与 Unreal 端一致）"""
        shorts = []
        for hand in ["L", "R"]:
            for finger_short in self.finger_shorts_for_hand(hand):
                shorts.append(self.finger_pole_short(finger_short))
        return shorts

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

        controller_root = object_utils.create_or_update_object(
            self.obj_name("controller_root"), "sphere", controllers_coll)

        for short in self.hand_controllers.values():
            obj = object_utils.create_or_update_object(
                self.obj_name(short), "cube", hand_coll)
            if obj and obj.parent != controller_root:
                obj.parent = controller_root

        for short in self.foot_controllers.values():
            obj = object_utils.create_or_update_object(
                self.obj_name(short), "cube", foot_coll)
            if obj and obj.parent != controller_root:
                obj.parent = controller_root

        for short in self.special_controllers.values():
            obj = object_utils.create_or_update_object(
                self.obj_name(short), "cube", special_coll)
            if obj and obj.parent != controller_root:
                obj.parent = controller_root

        # 鼓槌控件（挂在 H_L / H_R 下）
        left_hand = self.obj("H_L")
        right_hand = self.obj("H_R")
        for hand_short, stick_short in (("H_L", self.stick_controllers["left_stick"]),
                                        ("H_R", self.stick_controllers["right_stick"])):
            stick_obj = object_utils.create_or_update_object(
                self.obj_name(stick_short), "cube", hand_coll)
            hand_obj = left_hand if hand_short == "H_L" else right_hand
            if stick_obj and hand_obj is not None and stick_obj.parent != hand_obj:
                stick_obj.parent = hand_obj

        # 辅助控件：手指 + ext + pole（仅创建/驱动，不参与数据传递）
        self.add_finger_ext_and_poles(hand_coll)
        self.add_foot_poles(foot_coll)
        self.add_ext_drivers()

        self._organize_performer_root()
        self._setup_special_constraints()
        print("✓ BeatBloom 控件已就绪")

    def _setup_special_constraints(self) -> None:
        """设置 BeatBloom 特殊朝向链：

        Middle_Hand：双手中点，位置由动画关键帧提供（不挂驱动器），
        -Z 轴始终指向 controller_root
        Look_At 挂 Middle_Hand，Head_Control TrackTo Look_At
        """
        middle = self.obj("Middle_Hand")
        look_at = self.obj("Look_At")
        head = self.obj("Head_Control")
        controller_root = self.obj("controller_root")

        if not all([middle, look_at, head]):
            print("  ✗ 找不到特殊控制器对象，跳过约束设置")
            return

        # 旧版的中点辅助控件与正前方参考点：先把子级摘出来，再删除
        self._remove_legacy_special_controls(middle)

        # 中点改由动画关键帧驱动
        self._remove_location_drivers(middle)

        # Look_At 与中点重合
        if look_at.parent != middle:
            look_at.parent = middle
        look_at.matrix_parent_inverse.identity()
        look_at.location = (0.0, 0.0, 0.0)

        if controller_root is not None:
            for special_object in (middle, head):
                if special_object.parent != controller_root:
                    special_object.parent = controller_root

        # Middle_Hand 的朝向：-Z 轴始终指向 controller_root，
        # 这样中点空物体的局部坐标不会随位置漂移。
        # 中点几乎就在 controller_root 正上方，只锁一条轴时绕这条轴的滚转是任意的，
        # 会随两只手的高低差来回翻；Look_At 挂在它下面，滚转一晃头部朝向就跟着晃，
        # 所以这里用 Track To 并把 Y 轴锚到世界向上（滚转有了确定答案）。
        for middle_constraint in list(middle.constraints):
            middle.constraints.remove(middle_constraint)
        if controller_root is not None:
            middle_track = middle.constraints.new('TRACK_TO')
            middle_track.name = "Track_Controller_Root"
            middle_track.target = controller_root
            middle_track.track_axis = 'TRACK_NEGATIVE_Z'
            middle_track.up_axis = 'UP_Y'
            middle_track.use_target_z = False
            middle_track.target_space = 'WORLD'
            middle_track.owner_space = 'WORLD'

        # Head_Control 清除旧约束并添加 TrackTo
        for c in list(head.constraints):
            head.constraints.remove(c)
        track = head.constraints.new('TRACK_TO')
        track.name = "Track_Look_At"
        track.target = look_at
        track.track_axis = 'TRACK_Z'
        track.up_axis = 'UP_Y'
        print("  ✓ 特殊朝向控制器约束已设置，Look_At 现在为 Middle_Hand 子级")

    def _remove_legacy_special_controls(self, middle) -> None:
        """删除旧版的特殊朝向辅助控件。

        Invert_Middle_Hand / Virtul_Middle_Hand 只在场景里实时切换中点位置，
        Head_Forward 只用于判断中点在前还是在后；现在这两件事都由生成动画时算好。
        """
        for short in ("Virtul_Middle_Hand", "Invert_Middle_Hand", "Head_Forward"):
            legacy_object = self.obj(short)
            if legacy_object is None:
                continue
            for child in list(legacy_object.children):
                child.parent = middle
                child.matrix_parent_inverse.identity()
            bpy.data.objects.remove(legacy_object, do_unlink=True)
            print(f"  ✓ 已删除旧控件 {self.obj_name(short)}")

    @staticmethod
    def _remove_location_drivers(control_object) -> None:
        """摘掉位置驱动器，保留关键帧动画。"""
        animation = control_object.animation_data
        if animation is None:
            return
        for axis_index in range(3):
            if animation.drivers.find("location", index=axis_index) is not None:
                control_object.driver_remove("location", axis_index)

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
        controller_root = self.obj("controller_root")
        for short in self.foot_pole_controllers.values():
            obj = object_utils.create_or_update_object(
                self.obj_name(short), "circle", foot_coll)
            if obj and controller_root is not None and obj.parent != controller_root:
                obj.parent = controller_root
        print("  ✓ 脚部 pole target 创建完成")

    def add_ext_drivers(self) -> None:
        """为每个手指的 ext 辅助控件添加位置驱动 +「+X 轴指向手掌」约束（幂等）

        手指与 ext 都挂在手掌下（手掌就是手指的父级）→ 位置驱动 `ext = 2 × 手指`。
        """
        print("\n添加手指 ext 控制器驱动...")
        for hand in ["L", "R"]:
            for finger in FINGER_BASES:
                ext_utils.add_ext_driver(self, hand, finger, hand_is_parent=True)
        print("  ✓ 手指 ext 控制器驱动设置完成")

    def _organize_performer_root(self) -> None:
        """把 BeatBloom 的 controller_root 挂到音乐人根对象 BB_<suffix> 上。"""
        if not self.suffix:
            return
        performer = _pu.get_performer(self.suffix)
        if performer is None:
            return
        root_obj = _pu.get_or_create_performer_root(
            performer, performer.collection)
        controller_root = self.obj("controller_root")
        if controller_root is None:
            return
        if controller_root.parent != root_obj:
            controller_root.parent = root_obj

        top_level_targets = list(self.hand_controllers.values()) + \
            list(self.foot_controllers.values()) + \
            list(self.foot_pole_controllers.values()) + \
            list(self.special_controllers.values())
        for short in top_level_targets:
            obj = self.obj(short)
            if obj is not None and obj.parent != controller_root:
                obj.parent = controller_root


def performer_utils_find_addons(suffix: str):
    """获取演奏者的 addons 集合（无后缀时回退到全局 addons）"""
    if suffix:
        return _pu.find_addons_collection(suffix)
    return object_utils.get_or_create_collection("addons")
