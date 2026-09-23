# beat_bloom/config.py
"""BeatBloom 乐器模块 —— 配置与控件创建

基础控件 9 个：手掌 × 2、IK Pivot × 2、脚部 × 2、
特殊朝向（Middle_Hand / Invert_Middle_Hand / Head_Forward / Virtul_Middle_Hand / Look_At / Head_Control）× 6。
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

        # Middle_Hand：双手中点
        # Invert_Middle_Hand：相对 Head_Control 与 Middle_Hand 镜像点
        # Head_Forward：头部正常朝向前方参考点
        # Virtul_Middle_Hand：在 Middle_Hand / Invert_Middle_Hand 间切换
        # Look_At 挂 Virtul_Middle_Hand，Head_Control 挂 TrackTo
        self.special_controllers = {
            "middle_hand":  "Middle_Hand",
            "invert_middle_hand": "Invert_Middle_Hand",
            "head_forward": "Head_Forward",
            "virtual_middle_hand": "Virtul_Middle_Hand",
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

        Middle_Hand = (H_L + H_R) / 2
        Invert_Middle_Hand = 2 * Head_Control - Middle_Hand
        Virtul_Middle_Hand 在 Middle_Hand / Invert_Middle_Hand 间按半球判定切换
        Look_At 挂 Virtul_Middle_Hand，Head_Control TrackTo Look_At
        """
        middle = self.obj("Middle_Hand")
        invert_middle = self.obj("Invert_Middle_Hand")
        head_forward = self.obj("Head_Forward")
        virtual_middle = self.obj("Virtul_Middle_Hand")
        look_at = self.obj("Look_At")
        head = self.obj("Head_Control")
        left_hand = self.obj("H_L")
        right_hand = self.obj("H_R")
        controller_root = self.obj("controller_root")

        if not all([
            middle,
            invert_middle,
            head_forward,
            virtual_middle,
            look_at,
            head,
            left_hand,
            right_hand,
        ]):
            print("  ✗ 找不到特殊控制器对象，跳过约束设置")
            return

        # 1) Middle_Hand：位置始终为 H_L / H_R 的中点
        middle.animation_data_clear()
        for axis_index, axis_name in enumerate(['x', 'y', 'z']):
            driver = middle.driver_add("location", axis_index).driver
            driver.type = 'SCRIPTED'

            var_l = driver.variables.new()
            var_l.name = f"left_{axis_name}"
            var_l.type = 'TRANSFORMS'
            target_l = var_l.targets[0]
            target_l.id = left_hand
            target_l.transform_type = f'LOC_{axis_name.upper()}'
            target_l.transform_space = 'LOCAL_SPACE'

            var_r = driver.variables.new()
            var_r.name = f"right_{axis_name}"
            var_r.type = 'TRANSFORMS'
            target_r = var_r.targets[0]
            target_r.id = right_hand
            target_r.transform_type = f'LOC_{axis_name.upper()}'
            target_r.transform_space = 'LOCAL_SPACE'

            driver.expression = f"(left_{axis_name} + right_{axis_name}) / 2"

        # 2) Invert_Middle_Hand：位于 Middle_Hand -> Head_Control 延长线上，与 Head_Control 等距
        #    等价公式：invert = 2 * head - middle
        invert_middle.animation_data_clear()
        for axis_index, axis_name in enumerate(['x', 'y', 'z']):
            driver = invert_middle.driver_add("location", axis_index).driver
            driver.type = 'SCRIPTED'

            var_h = driver.variables.new()
            var_h.name = f"head_{axis_name}"
            var_h.type = 'TRANSFORMS'
            target_h = var_h.targets[0]
            target_h.id = head
            target_h.transform_type = f'LOC_{axis_name.upper()}'
            target_h.transform_space = 'LOCAL_SPACE'

            var_m = driver.variables.new()
            var_m.name = f"middle_{axis_name}"
            var_m.type = 'TRANSFORMS'
            target_m = var_m.targets[0]
            target_m.id = middle
            target_m.transform_type = f'LOC_{axis_name.upper()}'
            target_m.transform_space = 'LOCAL_SPACE'

            driver.expression = f"2 * head_{axis_name} - middle_{axis_name}"

        # 3) Virtul_Middle_Hand：复制 Middle_Hand / Invert_Middle_Hand，由半球判定切换 influence
        # 半球法向：head -> head_forward
        # 判定向量：head -> middle
        # dot >= 0 取 middle；dot < 0 取 invert
        for c in list(virtual_middle.constraints):
            virtual_middle.constraints.remove(c)

        copy_middle = virtual_middle.constraints.new('COPY_LOCATION')
        copy_middle.name = "Copy_Middle_Hand"
        copy_middle.target = middle

        copy_invert = virtual_middle.constraints.new('COPY_LOCATION')
        copy_invert.name = "Copy_Invert_Middle_Hand"
        copy_invert.target = invert_middle

        def _add_loc_var(driver, var_name: str, target_obj, axis_char: str) -> None:
            var = driver.variables.new()
            var.name = var_name
            var.type = 'TRANSFORMS'
            target = var.targets[0]
            target.id = target_obj
            target.transform_type = f'LOC_{axis_char}'
            target.transform_space = 'LOCAL_SPACE'

        dot_expr = "((mx-hx)*(fx-hx) + (my-hy)*(fy-hy) + (mz-hz)*(fz-hz))"

        mid_influence_driver = copy_middle.driver_add("influence").driver
        mid_influence_driver.type = 'SCRIPTED'
        for name, obj, axis in [
            ('mx', middle, 'X'), ('my', middle, 'Y'), ('mz', middle, 'Z'),
            ('hx', head, 'X'), ('hy', head, 'Y'), ('hz', head, 'Z'),
            ('fx', head_forward, 'X'), ('fy',
                                        head_forward, 'Y'), ('fz', head_forward, 'Z'),
        ]:
            _add_loc_var(mid_influence_driver, name, obj, axis)
        mid_influence_driver.expression = f"1.0 if {dot_expr} >= 0.0 else 0.0"

        inv_influence_driver = copy_invert.driver_add("influence").driver
        inv_influence_driver.type = 'SCRIPTED'
        for name, obj, axis in [
            ('mx', middle, 'X'), ('my', middle, 'Y'), ('mz', middle, 'Z'),
            ('hx', head, 'X'), ('hy', head, 'Y'), ('hz', head, 'Z'),
            ('fx', head_forward, 'X'), ('fy',
                                        head_forward, 'Y'), ('fz', head_forward, 'Z'),
        ]:
            _add_loc_var(inv_influence_driver, name, obj, axis)
        inv_influence_driver.expression = f"1.0 if {dot_expr} < 0.0 else 0.0"

        # Look_At 改为挂在 Virtul_Middle_Hand 下，Head_Control 只负责看向 Look_At。
        if look_at.parent != virtual_middle:
            look_at.parent = virtual_middle

        if controller_root is not None:
            if middle.parent != controller_root:
                middle.parent = controller_root
            if invert_middle.parent != controller_root:
                invert_middle.parent = controller_root
            if head_forward.parent != controller_root:
                head_forward.parent = controller_root
            if virtual_middle.parent != controller_root:
                virtual_middle.parent = controller_root
            if head.parent != controller_root:
                head.parent = controller_root

        # Head_Control 清除旧约束并添加 TrackTo
        for c in list(head.constraints):
            head.constraints.remove(c)
        track = head.constraints.new('TRACK_TO')
        track.name = "Track_Look_At"
        track.target = look_at
        track.track_axis = 'TRACK_Z'
        track.up_axis = 'UP_Y'
        print("  ✓ 特殊朝向控制器约束已设置，Look_At 现在为 Virtul_Middle_Hand 子级")

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
