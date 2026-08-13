# harp_glide/object_manager.py
"""HarpGlide 乐器模块 —— 对象管理（控件创建 + 弦位置标记 + 特殊约束）"""

import bpy  # type: ignore

from ..common import performer_utils
from ..common import object_utils
from .config import HarpConfig


class HarpObjectManager(HarpConfig):
    """控件创建、弦位置标记、集合层级、演奏者组织"""

    # ── 公共集合辅助 ─────────────────────────────────────────────

    def _get_addons_collection(self):
        if self.suffix:
            return performer_utils.find_addons_collection(self.suffix)
        return object_utils.get_or_create_collection("addons")

    def _get_or_create_coll(self, short_name: str, parent):
        full = performer_utils.resolve(short_name, self.suffix)
        return object_utils.get_or_create_collection(full, parent)

    def _make(self, short: str, obj_type: str, coll, scale: float = 1.0):
        return object_utils.create_or_update_object(
            self.obj_name(short), obj_type, coll, scale=scale)

    def _parent(self, child_short: str, parent_short: str):
        child = self.obj(child_short)
        parent = self.obj(parent_short)
        object_utils.parent_to(parent, child)

    def _parent_obj(self, child_short: str, parent_obj):
        child = self.obj(child_short)
        object_utils.parent_to(parent_obj, child)

    # ── add_controllers ──────────────────────────────────────────

    def add_controllers(self) -> None:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        addons = self._get_addons_collection()
        if addons is None:
            print("[ERROR] 未找到 addons 目录，请先初始化角色。")
            return

        ctrl_coll = self._get_or_create_coll("Controllers", addons)
        root_coll = self._get_or_create_coll("controller_root", ctrl_coll)
        body_coll = self._get_or_create_coll("Body_Controllers", root_coll)
        hand_coll = self._get_or_create_coll("Hand_Controllers", root_coll)
        lh_coll = self._get_or_create_coll("Left_Hand", hand_coll)
        rh_coll = self._get_or_create_coll("Right_Hand", hand_coll)
        foot_coll = self._get_or_create_coll("Foot_Controllers", root_coll)
        pivot_coll = self._get_or_create_coll(
            "Harp_Pivot_Controllers", root_coll)
        tgt_coll = self._get_or_create_coll("Target_Controllers", ctrl_coll)

        # controller_root（空物体，固定乐器根）
        self._make("controller_root", "sphere", root_coll)

        # 身体控制器
        self._make("Head",         "cube", body_coll)
        self._make("Shoulder_Harp", "cube", body_coll)

        # 竖琴支点
        self._make("harp_pivot", "cube", pivot_coll)

        # 左手
        self._make("H_L",  "cube",   lh_coll)
        self._make("HP_L", "cube",   lh_coll)
        for s in self.left_finger_shorts:
            self._make(s, "sphere", lh_coll)
        # ext 辅助控件（0.7× 小方块，父级=H_L）
        for s in self.left_finger_shorts:
            self._make(f"ext_{s}", "cube", lh_coll, scale=0.7)
        # pole
        for s in self.left_finger_shorts:
            self._make(f"{s}_pole", "sphere", lh_coll)

        # 右手
        self._make("H_R",  "cube",   rh_coll)
        self._make("HP_R", "cube",   rh_coll)
        for s in self.right_finger_shorts:
            self._make(s, "sphere", rh_coll)
        for s in self.right_finger_shorts:
            self._make(f"ext_{s}", "cube", rh_coll, scale=0.7)
        for s in self.right_finger_shorts:
            self._make(f"{s}_pole", "sphere", rh_coll)

        # 脚部
        for short in self.foot_controllers.values():
            self._make(short, "cube", foot_coll)

        # 视线辅助（不挂 controller_root）
        self._make("Mid_Hand", "sphere",       tgt_coll)
        self._make("Look_At",  "single_arrow", tgt_coll)

        self._setup_hierarchy()
        print("✓ HarpGlide 控件已就绪")

    def _setup_hierarchy(self) -> None:
        """设置控件父子层级"""
        cr = self.obj("controller_root")
        # 手/脚/支点 → controller_root
        for short in ["H_L", "HP_L", "H_R", "HP_R",
                      "F_L", "FP_L", "F_R", "FP_R",
                      "harp_pivot"]:
            object_utils.parent_to(cr, self.obj(short))

        pivot = self.obj("harp_pivot")
        for short in ["Head", "Shoulder_Harp"]:
            object_utils.parent_to(pivot, self.obj(short))

        # 五指 → 手掌
        h_l = self.obj("H_L")
        h_r = self.obj("H_R")
        for s in self.left_finger_shorts:
            object_utils.parent_to(h_l, self.obj(s))
            object_utils.parent_to(h_l, self.obj(f"ext_{s}"))
        for s in self.right_finger_shorts:
            object_utils.parent_to(h_r, self.obj(s))
            object_utils.parent_to(h_r, self.obj(f"ext_{s}"))

        # pole → 对应 ext
        for s in self.left_finger_shorts + self.right_finger_shorts:
            ext = self.obj(f"ext_{s}")
            pole = self.obj(f"{s}_pole")
            object_utils.parent_to(ext, pole)

        # Shoulder_Harp → harp_pivot（覆盖 controller_root 父级）
        pivot = self.obj("harp_pivot")
        object_utils.parent_to(pivot, self.obj("Shoulder_Harp"))

        # Look_At → Mid_Hand
        object_utils.parent_to(self.obj("Mid_Hand"), self.obj("Look_At"))

    # ── add_string_markers ───────────────────────────────────────

    def add_string_markers(self, string_count: int) -> None:
        """创建弦位置标记（s{n}head / s{n}end），父级 = harp_pivot"""
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        addons = self._get_addons_collection()
        if addons is None:
            print("[ERROR] 未找到 addons 目录，请先初始化角色。")
            return

        rec_coll = self._get_or_create_coll("Recorders", addons)
        str_pos_coll = self._get_or_create_coll("String_Positions", rec_coll)
        pivot = self.obj("harp_pivot")

        for n in range(string_count):
            for suffix_part in ("head", "end"):
                short = f"s{n}{suffix_part}"
                obj = object_utils.create_or_update_object(
                    self.obj_name(short), "sphere", str_pos_coll)
                # 已存在的不重置 location，只确保父级正确
                if pivot and obj.parent != pivot:
                    obj.parent = pivot

        print(f"✓ 弦位置标记已就绪：{string_count} 根弦（{string_count * 2} 个标记）")

    # ── _setup_special_controllers ───────────────────────────────

    def _setup_special_controllers(self) -> None:
        """ext driver（先清后建）+ Mid_Hand driver（先清后建）"""
        self._setup_ext_drivers()
        self._setup_mid_hand_driver()

    def _setup_ext_drivers(self) -> None:
        """ext = 2 × 手指（LOCAL_SPACE），先清后建"""
        for s in self.left_finger_shorts + self.right_finger_shorts:
            self._add_ext_driver(s)

    def _add_ext_driver(self, finger_short: str) -> None:
        finger_name = self.obj_name(finger_short)
        ext_name = self.obj_name(f"ext_{finger_short}")
        finger_obj = bpy.data.objects.get(finger_name)
        ext_obj = bpy.data.objects.get(ext_name)
        if not finger_obj or not ext_obj:
            return

        # 先清除已有的 location driver
        if ext_obj.animation_data:
            for axis in range(3):
                fc = ext_obj.animation_data.drivers.find(
                    "location", index=axis)
                if fc:
                    ext_obj.animation_data.drivers.remove(fc)

        for axis_idx, axis_char in enumerate(["X", "Y", "Z"]):
            drv = ext_obj.driver_add("location", axis_idx).driver
            drv.type = "SCRIPTED"
            var = drv.variables.new()
            var.name = "finger"
            var.type = "TRANSFORMS"
            var.targets[0].id = finger_obj
            var.targets[0].transform_type = f"LOC_{axis_char}"
            var.targets[0].transform_space = "LOCAL_SPACE"
            drv.expression = "finger * 2.0"

    def _setup_mid_hand_driver(self) -> None:
        """Mid_Hand = (H_L + H_R) / 2（WORLD_SPACE），先清后建"""
        h_l = self.obj("H_L")
        h_r = self.obj("H_R")
        mid = self.obj("Mid_Hand")
        if not all([h_l, h_r, mid]):
            print("  ✗ 缺少 Mid_Hand driver 所需物体，跳过")
            return

        if mid.animation_data:
            for axis in range(3):
                fc = mid.animation_data.drivers.find("location", index=axis)
                if fc:
                    mid.animation_data.drivers.remove(fc)

        for axis_idx, axis_char in enumerate(["X", "Y", "Z"]):
            drv = mid.driver_add("location", axis_idx).driver
            drv.type = "SCRIPTED"

            v_l = drv.variables.new()
            v_l.name = f"hl_{axis_char.lower()}"
            v_l.type = "TRANSFORMS"
            v_l.targets[0].id = h_l
            v_l.targets[0].transform_type = f"LOC_{axis_char}"
            v_l.targets[0].transform_space = "WORLD_SPACE"

            v_r = drv.variables.new()
            v_r.name = f"hr_{axis_char.lower()}"
            v_r.type = "TRANSFORMS"
            v_r.targets[0].id = h_r
            v_r.targets[0].transform_type = f"LOC_{axis_char}"
            v_r.targets[0].transform_space = "WORLD_SPACE"

            drv.expression = f"(hl_{axis_char.lower()} + hr_{axis_char.lower()}) / 2.0"

    # ── setup_all_objects ────────────────────────────────────────

    def setup_all_objects(self, string_count: int = 47) -> bool:
        addons = self._get_addons_collection()
        if self.suffix and addons is None:
            print("[ERROR] 未找到角色 addons 目录，请先初始化角色。")
            return False

        self._organize_body()
        self._organize_instrument()
        self.add_controllers()
        self.add_string_markers(string_count)
        self._setup_special_controllers()
        self._organize_performer_root()
        return True

    # ── 演奏者结构组织（同 fret_dance） ─────────────────────────

    def _get_performer_collection(self):
        if not self.suffix:
            return None
        return performer_utils.get_performer(self.suffix)

    def _organize_body(self):
        if not self.suffix:
            return
        p = self._get_performer_collection()
        if p is None:
            return
        body_coll = performer_utils.get_or_create_collection(
            self.suffix, "Body", parent=p.collection)
        skeleton = self.target_skeleton or p.target_skeleton
        if skeleton is None:
            return
        object_utils.move_object_to_collection(skeleton, body_coll)
        for child in list(skeleton.children):
            if child.type == "MESH":
                object_utils.move_object_to_collection(child, body_coll)

    def _organize_instrument(self):
        if not self.suffix:
            return
        inst = self.target_instrument
        if inst is None:
            return
        p = self._get_performer_collection()
        if p is None:
            return
        inst_coll = performer_utils.get_or_create_collection(
            self.suffix, "Instruments", parent=p.collection)
        object_utils.move_object_to_collection(inst, inst_coll)

    def _organize_performer_root(self):
        if not self.suffix:
            return
        p = self._get_performer_collection()
        if p is None:
            return
        root_obj = performer_utils.get_or_create_performer_root(
            p, p.collection)
        skeleton = self.target_skeleton or p.target_skeleton
        object_utils.parent_to(root_obj, skeleton)
        object_utils.parent_to(root_obj, self.obj("controller_root"))
