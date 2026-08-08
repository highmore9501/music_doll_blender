# fret_dance/object_manager.py
"""FretDance 乐器模块 —— Blender 对象管理（迁移自 fret_dance_blender/blender_object_manager.py）

公共能力（集合/物体创建、演奏者命名空间、根物体）改调 common/。
"""
import re

import bpy  # type: ignore

from ..common import performer_utils
from ..common import object_utils
from .enums import Instruments


class BlenderObjectManager:
    """Blender对象管理类 - 负责Blender场景中的对象操作"""

    def get_or_create_collection(self, name, parent_collection=None):
        """获取或创建集合（自动按演奏者后缀拼接完整集合名）"""
        full_name = self.obj_name(name)
        return object_utils.get_or_create_collection(full_name, parent_collection)

    def move_object_to_collection(self, obj, collection):
        """将对象移动到指定集合"""
        object_utils.move_object_to_collection(obj, collection)

    def create_or_update_object(self, obj_name, obj_type="cube", collection=None,
                                rotation_mode='QUATERNION', scale=1.0):
        """创建或更新物体的通用方法"""
        # 从pre_obj_names中移除同名物体
        if hasattr(self, 'pre_obj_names') and obj_name in self.pre_obj_names:
            self.pre_obj_names.remove(obj_name)
        return object_utils.create_or_update_object(
            obj_name, obj_type, collection, rotation_mode, scale=scale)

    # ── 演奏者结构与 Body 组织 ─────────────────────────────

    def _get_or_create_performer_collection(self):
        """获取/创建演奏者集合（仅后缀模式使用；无后缀返回 None）"""
        if not self.suffix:
            return None
        return performer_utils.get_or_create_performer(
            self.suffix, self.performer_name, self.instruments_name,
            target_skeleton=self.target_skeleton,
            target_instrument=self.target_instrument)

    def _get_addons_collection(self):
        """获取/创建本演奏者的 addons 目录。

        - 有后缀：挂到演奏者集合下（Performers/<名>/addons_<后缀>）
        - 无后缀（兼容旧场景）：全局根下的 addons
        """
        if self.suffix:
            performer = self._get_or_create_performer_collection()
            return performer_utils.get_or_create_collection(
                self.suffix, "addons", parent=performer.collection)
        return self.get_or_create_collection("addons")

    def _organize_body(self):
        """把目标骨骼和它的 Mesh 归位到 Body_<后缀>（仅后缀模式）"""
        if not self.suffix:
            return
        performer = self._get_or_create_performer_collection()
        if performer is None:
            return
        body_coll = performer_utils.get_or_create_collection(
            self.suffix, "Body", parent=performer.collection)
        skeleton = self.target_skeleton or performer.target_skeleton
        if skeleton is None:
            print("  • 未指定目标骨骼，跳过 Body 归位")
            return
        # 骨骼移入 Body
        self.move_object_to_collection(skeleton, body_coll)
        # 骨骼的 Mesh 子级移入 Body，并确保父级是骨骼
        for child in list(skeleton.children):
            if child.type == 'MESH':
                self.move_object_to_collection(child, body_coll)
                if child.parent != skeleton:
                    child.parent = skeleton
        print(f"  ✓ 骨骼 {skeleton.name} 及其 Mesh 已归位到 {body_coll.name}")

    def _organize_instrument(self):
        """把目标乐器物体归位到 Instruments_<后缀>（仅后缀模式）"""
        if not self.suffix:
            return
        inst = self.target_instrument
        if inst is None:
            return
        performer = self._get_or_create_performer_collection()
        if performer is None:
            return
        inst_coll = performer_utils.get_or_create_collection(
            self.suffix, "Instruments", parent=performer.collection)
        self.move_object_to_collection(inst, inst_coll)
        print(f"  ✓ 乐器 {inst.name} 已归位到 {inst_coll.name}")

    def _organize_performer_root(self):
        """创建演奏者根空物体 <乐器缩写>_<名称>，作为骨骼 / 控制器根 / 乐器的父级（仅后缀模式）。

        创建时直接复制骨骼的位置/旋转/缩放；之后可整体移动/缩放整个演奏者体系。
        """
        if not self.suffix:
            return
        performer = self._get_or_create_performer_collection()
        if performer is None:
            return
        root_obj = performer_utils.get_or_create_performer_root(
            performer, performer.collection)

        # 三个子根以它为父级：骨骼 / 控制器根 / 乐器
        skeleton = self.target_skeleton or performer.target_skeleton
        self._parent_to(root_obj, skeleton)
        self._parent_to(root_obj, self.obj("controller_root"))
        inst = self.target_instrument or performer.target_instrument
        self._parent_to(root_obj, inst)
        print(f"  ✓ 演奏者根 {root_obj.name} 就绪（骨骼/控制器根/乐器已挂到其下）")

    def _parent_to(self, parent_obj, child_obj):
        """把 child 挂到 parent 下（Blender 保持世界位置不变）"""
        object_utils.parent_to(parent_obj, child_obj)

    def add_controllers(self):
        """添加控制器对象到Blender场景中"""
        # 确保在对象模式下操作
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 创建或获取主集合（addons 目录）
        main_collection = self._get_addons_collection()

        # 创建控制器集合
        controllers_collection = self.get_or_create_collection(
            "Controllers", main_collection)

        # 创建控制器根节点（空物体，对齐 Unreal 模块的 controller_root / controller_root_offset）
        self.create_or_update_object(
            self.obj_name("controller_root"), "sphere", controllers_collection)
        self.create_or_update_object(
            self.obj_name("controller_root_offset"), "sphere", controllers_collection)

        # 创建左右手子集合
        left_hand_controller_collection = self.get_or_create_collection(
            "Left_Hand_Controllers", controllers_collection)
        right_hand_controller_collection = self.get_or_create_collection(
            "Right_Hand_Controllers", controllers_collection)

        # 添加左手控制器
        for controller_name, obj_name in self.left_hand_controllers.items():
            obj_type = "cone" if 'rotation' in controller_name else "cube"
            self.create_or_update_object(
                self.obj_name(obj_name), obj_type, left_hand_controller_collection)

        # 添加右手控制器
        for controller_name, obj_name in self.right_hand_controllers.items():
            obj_type = "cone" if 'rotation' in controller_name else "cube"
            self.create_or_update_object(
                self.obj_name(obj_name), obj_type, right_hand_controller_collection)

        # 添加左手手指控制器
        for controller_name, obj_name in self.left_finger_controllers.items():
            obj_type = "cone" if 'rotation' in controller_name else "cube"
            self.create_or_update_object(
                self.obj_name(obj_name), obj_type, left_hand_controller_collection)

        # 添加右手手指控制器
        for controller_name, obj_name in self.right_finger_controllers.items():
            obj_type = "cone" if 'rotation' in controller_name else "cube"
            self.create_or_update_object(
                self.obj_name(obj_name), obj_type, right_hand_controller_collection)

        # 设置控制器父子层级（按乐器规则）
        self.set_controller_hierarchy()

    # ── 控制器层级 ─────────────────────────────────────────────

    def set_controller_hierarchy(self):
        """按乐器规则设置手掌/手指父子层级（对齐 Unreal 模块）

        - 控制器根：controller_root_offset → controller_root
        - 左右手掌与枢轴（H_L/HP_L/H_R/HP_R）→ controller_root_offset
        - 左手（所有吉他）：手指为手掌子级
        - 右手（指弹/bass）：全部手指是手掌的子级
        - 右手（电吉他）：中指/无名指/小指是手掌的子级，
          大拇指是手掌的平级（同挂 controller_root_offset 下），食指是大拇指的子级
        """
        print("\n设置控制器父子层级...")
        h_r = self.obj("H_R")
        h_l = self.obj("H_L")
        t_r = self.obj("T_R")
        controller_root = self.obj("controller_root")
        controller_root_offset = self.obj("controller_root_offset")

        # 控制器根：controller_root_offset → controller_root
        self._set_parent("controller_root_offset", controller_root)

        # 左右手掌与枢轴 → controller_root_offset
        for name in ["H_L", "HP_L", "H_R", "HP_R"]:
            self._set_parent(name, controller_root_offset)

        # 左手：手指设置为手掌的子级
        for name in ["T_L", "I_L", "M_L", "R_L", "P_L"]:
            self._set_parent(name, h_l)  # 手掌为父级

        # 右手：按乐器类型设置
        if self.instruments == Instruments.ELECTRIC_GUITAR:
            for name in ["M_R", "R_R", "P_R"]:
                self._set_parent(name, h_r)
            self._set_parent("T_R", controller_root_offset)
            self._set_parent("I_R", t_r)
        else:
            for name in ["T_R", "I_R", "M_R", "R_R", "P_R"]:
                self._set_parent(name, h_r)
        print("  ✓ 控制器父子层级设置完成")

    def _set_parent(self, child_name, parent_obj):
        """将子控制器挂到指定父对象下（Blender 自动保持世界位置不变）"""
        full_child = self.obj_name(child_name)
        if parent_obj is None:
            print(f"  • 父对象不存在，跳过 {full_child} 的父子设置")
            return
        obj = bpy.data.objects.get(full_child)
        if obj is None:
            print(f"  • 控制器 {full_child} 不存在，跳过父子设置")
            return
        if obj.parent != parent_obj:
            obj.parent = parent_obj
        print(f"  ✓ {full_child} → {parent_obj.name}")

    # ── ext 辅助控件与 pole ───────────────────────────────────

    def add_finger_ext_and_poles(self):
        """为所有手指创建 ext 辅助控件与 pole，pole 挂 ext 下"""
        print("\n添加手指 ext 辅助控件与 pole...")
        main_collection = self._get_addons_collection()
        controllers_collection = self.get_or_create_collection(
            "Controllers", main_collection)
        left_col = self.get_or_create_collection(
            "Left_Hand_Controllers", controllers_collection)
        right_col = self.get_or_create_collection(
            "Right_Hand_Controllers", controllers_collection)

        for hand, collection in [("L", left_col), ("R", right_col)]:
            for finger_name in [f"T_{hand}", f"I_{hand}", f"M_{hand}", f"R_{hand}", f"P_{hand}"]:
                ext_name = self.obj_name(f"ext_{finger_name}")
                ext_obj = self.create_or_update_object(
                    ext_name, "cube", collection, scale=0.7)
                finger_obj = self.obj(finger_name)
                if finger_obj and finger_obj.parent and ext_obj.parent != finger_obj.parent:
                    ext_obj.parent = finger_obj.parent
                if finger_name.startswith("T_"):
                    pole_name = self.obj_name(f"TP_{hand}")
                else:
                    pole_name = self.obj_name(f"{finger_name}_pole")
                pole_obj = self.create_or_update_object(
                    pole_name, "sphere", collection)
                if pole_obj:
                    if pole_obj.parent != ext_obj:
                        pole_obj.parent = ext_obj
                    pole_obj.location = (0, 0, 1.0)
                    print(f"  ✓ {pole_name} → {ext_name}")

        print("  ✓ 手指 ext 辅助控件与 pole 创建完成")

    # ── ext 驱动 ──────────────────────────────────────────────

    def add_ext_drivers(self):
        """为每个手指的 ext 辅助控件添加 location 驱动"""
        print("\n添加手指 ext 控制器驱动...")
        for finger_name in ["T_L", "I_L", "M_L", "R_L", "P_L"]:
            self._add_ext_driver(finger_name, None)

        if self.instruments == Instruments.ELECTRIC_GUITAR:
            self._add_ext_driver("T_R", "H_R")
            for finger_name in ["I_R", "M_R", "R_R", "P_R"]:
                self._add_ext_driver(finger_name, None)
        else:
            for finger_name in ["T_R", "I_R", "M_R", "R_R", "P_R"]:
                self._add_ext_driver(finger_name, None)
        print("  ✓ 手指 ext 控制器驱动设置完成")

    def _add_ext_driver(self, finger_name, palm_name):
        """为单个手指的 ext 辅助控件添加 location 驱动"""
        ext_name = self.obj_name(f"ext_{finger_name}")
        if self.obj_name(finger_name) not in bpy.data.objects:
            print(f"  • 手指控制器 {finger_name} 不存在，跳过驱动")
            return
        if ext_name not in bpy.data.objects:
            print(f"  • ext 控件 {ext_name} 不存在，跳过驱动")
            return

        ext_obj = bpy.data.objects[ext_name]
        palm_obj = bpy.data.objects.get(
            self.obj_name(palm_name)) if palm_name else None

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
            target_f.id = bpy.data.objects[self.obj_name(finger_name)]
            target_f.transform_type = f'LOC_{axis_char}'
            target_f.transform_space = 'LOCAL_SPACE'

            if palm_obj is not None:
                var_p = driver.variables.new()
                var_p.name = "palm"
                var_p.type = 'TRANSFORMS'
                target_p = var_p.targets[0]
                target_p.id = palm_obj
                target_p.transform_type = f'LOC_{axis_char}'
                target_p.transform_space = 'LOCAL_SPACE'
                driver.expression = "2 * finger - palm"
            else:
                driver.expression = "2 * finger"

        print(
            f"  ✓ 已为 {ext_name} 添加驱动: ext = 2*{finger_name} - {palm_name}")

    def get_ext_controller_names(self):
        """生成所有 ext 辅助控件名称（含演奏者后缀）"""
        names = []
        for hand in ["L", "R"]:
            for finger_name in ["T", "I", "M", "R", "P"]:
                names.append(self.obj_name(f"ext_{finger_name}_{hand}"))
        return names

    def get_pole_controller_names(self):
        """生成所有手指 pole 名称（含拇指 TP_L/TP_R，含演奏者后缀）"""
        names = []
        for hand in ["L", "R"]:
            for finger_name in ["T", "I", "M", "R", "P"]:
                if finger_name == "T":
                    names.append(self.obj_name(f"TP_{hand}"))
                else:
                    names.append(self.obj_name(f"{finger_name}_{hand}_pole"))
        return names

    def add_fret_markers(self):
        """添加指板位置标记物体（Fret_P0~P4）到Blender场景中"""
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        main_collection = self._get_addons_collection()
        markers_collection = self.get_or_create_collection(
            "Recorders", main_collection)

        for recorder_name, obj_name in self.guitar_fret_positions.items():
            self.create_or_update_object(
                self.obj_name(obj_name), "sphere", markers_collection)

        controller_root_offset = self.obj("controller_root_offset")
        for obj_name in self.guitar_fret_positions.values():
            self._set_parent(obj_name, controller_root_offset)

    def setup_all_objects(self):
        """一次性设置所有控制器和指板位置标记（幂等）"""
        # 有后缀时，先组织演奏者集合与 Body（骨骼/Mesh 归位）、乐器目录
        self._organize_body()
        self._organize_instrument()

        # 记录添加控件前 addons 目录及其子集合中的所有物体名称（仅本演奏者）
        self.pre_obj_names = []
        addons_collection = self._get_addons_collection()
        collections_to_check = [addons_collection]
        for coll in addons_collection.children_recursive:
            collections_to_check.append(coll)
        for coll in collections_to_check:
            for obj in coll.objects:
                self.pre_obj_names.append(obj.name)

        # 添加控制器和指板标记
        self.add_controllers()
        self.add_fret_markers()

        # 添加手指 ext 辅助控件与 pole，并设置驱动
        self.add_finger_ext_and_poles()
        self.add_ext_drivers()

        # 创建演奏者根 <缩写>_<名称>，挂接骨骼/控制器根/乐器
        self._organize_performer_root()

        # 打印未使用的控件名称
        if self.pre_obj_names:
            print("\n未使用的控件:")
            for obj_name in self.pre_obj_names:
                print(f"  • {obj_name}")
        else:
            print("\n没有发现未使用的控件")

    def check_objects_status(self):
        """检查Blender中控制器和记录器的创建状态（仅当前演奏者命名空间）"""
        print("=" * 50)
        print("控制器和记录器状态检查报告")
        print("=" * 50)

        print("\n【控制器状态】")
        print("-" * 30)

        print("\n控制器根节点:")
        for root_name in ["controller_root", "controller_root_offset"]:
            full = self.obj_name(root_name)
            if full in bpy.data.objects:
                print(f"  ✓ {full} (已存在)")
            else:
                print(f"  ✗ {full} (缺失)")

        print("\n左手控制器:")
        missing_left_ctrl = []
        existing_left_ctrl = []
        for controller_name, obj_name in self.left_hand_controllers.items():
            full = self.obj_name(obj_name)
            if full in bpy.data.objects:
                existing_left_ctrl.append(full)
                print(f"  ✓ {full} (已存在)")
            else:
                missing_left_ctrl.append(full)
                print(f"  ✗ {full} (缺失)")

        print("\n右手控制器:")
        missing_right_ctrl = []
        existing_right_ctrl = []
        for controller_name, obj_name in self.right_hand_controllers.items():
            full = self.obj_name(obj_name)
            if full in bpy.data.objects:
                existing_right_ctrl.append(full)
                print(f"  ✓ {full} (已存在)")
            else:
                missing_right_ctrl.append(full)
                print(f"  ✗ {full} (缺失)")

        print("\n左手手指控制器:")
        missing_left_finger_ctrl = []
        existing_left_finger_ctrl = []
        for controller_name, obj_name in self.left_finger_controllers.items():
            full = self.obj_name(obj_name)
            if full in bpy.data.objects:
                existing_left_finger_ctrl.append(full)
                print(f"  ✓ {full} (已存在)")
            else:
                missing_left_finger_ctrl.append(full)
                print(f"  ✗ {full} (缺失)")

        print("\n右手手指控制器:")
        missing_right_finger_ctrl = []
        existing_right_finger_ctrl = []
        for controller_name, obj_name in self.right_finger_controllers.items():
            full = self.obj_name(obj_name)
            if full in bpy.data.objects:
                existing_right_finger_ctrl.append(full)
                print(f"  ✓ {full} (已存在)")
            else:
                missing_right_finger_ctrl.append(full)
                print(f"  ✗ {full} (缺失)")

        print("\n\n【手指 ext 辅助控件与 pole 状态】")
        print("-" * 30)
        for ext_name in self.get_ext_controller_names():
            status = "✓ 已存在" if ext_name in bpy.data.objects else "✗ 缺失"
            print(f"  {status} {ext_name}")
        for pole_name in self.get_pole_controller_names():
            status = "✓ 已存在" if pole_name in bpy.data.objects else "✗ 缺失"
            print(f"  {status} {pole_name}")

        print("\n\n【指板位置标记状态】")
        print("-" * 30)
        missing_fret_rec = []
        existing_fret_rec = []
        for recorder_name, obj_name in self.guitar_fret_positions.items():
            full = self.obj_name(obj_name)
            if full in bpy.data.objects:
                existing_fret_rec.append(full)
                print(f"  ✓ {full} (已存在)")
            else:
                missing_fret_rec.append(full)
                print(f"  ✗ {full} (缺失)")

        print("\n\n【统计信息】")
        print("-" * 30)

        total_ctrl = (len(self.left_hand_controllers) + len(self.right_hand_controllers) +
                      len(self.left_finger_controllers) + len(self.right_finger_controllers))
        existing_ctrl = (len(existing_left_ctrl) + len(existing_right_ctrl) +
                         len(existing_left_finger_ctrl) + len(existing_right_finger_ctrl))
        missing_ctrl = (len(missing_left_ctrl) + len(missing_right_ctrl) +
                        len(missing_left_finger_ctrl) + len(missing_right_finger_ctrl))

        print(f"控制器总数: {total_ctrl}")
        print(f"已存在: {existing_ctrl}")
        print(f"缺失: {missing_ctrl}")

        total_rec = len(self.guitar_fret_positions)
        existing_rec = len(existing_fret_rec)
        missing_rec = len(missing_fret_rec)

        print(f"\n指板标记总数: {total_rec}")
        print(f"已存在: {existing_rec}")
        print(f"缺失: {missing_rec}")

        total_objects = total_ctrl + total_rec
        total_existing = existing_ctrl + existing_rec
        total_missing = missing_ctrl + missing_rec

        print(f"\n对象总计: {total_objects}")
        print(f"已存在总计: {total_existing}")
        print(f"缺失总计: {total_missing}")
        print(
            f"完成度: {total_existing/total_objects*100:.1f}%" if total_objects > 0 else "完成度: 0%")

        if total_missing > 0:
            print("\n\n【缺失对象详细列表】")
            print("-" * 30)
            if missing_ctrl > 0:
                print("\n缺失的控制器:")
                for obj_name in (missing_left_ctrl + missing_right_ctrl +
                                 missing_left_finger_ctrl + missing_right_finger_ctrl):
                    print(f"  • {obj_name}")

            if missing_rec > 0:
                print("\n缺失的指板标记:")
                for obj_name in missing_fret_rec:
                    print(f"  • {obj_name}")

        print("\n" + "=" * 50)
        print("检查完成")
        print("=" * 50)

        return {
            'controllers': {
                'existing': existing_ctrl,
                'missing': missing_ctrl,
                'total': total_ctrl
            },
            'recorders': {
                'existing': existing_rec,
                'missing': missing_rec,
                'total': total_rec
            },
            'overall': {
                'existing': total_existing,
                'missing': total_missing,
                'total': total_objects
            }
        }

    # ── 旧场景迁移（一键按钮）────────────────────────────────

    def migrate_legacy_to_suffix(self):
        """把旧版「无后缀」的控件迁移到当前演奏者（有后缀 + 设计层级）。

        前提：self.suffix / self.target_skeleton 已设置（由面板/算子提供）。
        步骤：对象改名加后缀 -> 集合改名归类 -> Body 归类 -> 重建 ext driver
              -> 状态数据搬到骨骼 -> 写演奏者元信息与设置。
        """
        suffix = self.suffix
        skel = self.target_skeleton
        if not suffix or skel is None:
            print("[ERROR] migrate_legacy_to_suffix: 需要先设置演奏者后缀与目标骨骼")
            return False
        if performer_utils.has_performer(suffix):
            print(f"[WARN] 场景里已存在后缀为 {suffix} 的演奏者，继续（幂等，可续跑上次中断的迁移）。")
        if any(obj.name.endswith("_" + suffix) for obj in bpy.data.objects):
            print(f"[WARN] 检测到已有对象名以 _{suffix} 结尾（可能上次迁移中断），跳过改名步骤，继续整理。")

        performer_name = self.performer_name or performer_utils.strip_duplicate_suffix(
            skel.name)
        known = self._expected_short_names()
        renamed = 0
        warnings = []
        objects_to_process = []

        # 1) 收集旧 addons 集合树
        if "addons" in bpy.data.collections:
            addons_coll = bpy.data.collections["addons"]
            for coll in [addons_coll] + list(addons_coll.children_recursive):
                objects_to_process.extend(coll.objects)
        else:
            addons_coll = None
            print("[WARN] 没有找到全局 addons 集合，跳过控件归类。")

        # 2) 对象改名：短名 -> <短名>_<后缀>
        for obj in objects_to_process:
            base = performer_utils.strip_duplicate_suffix(obj.name)
            if base.endswith("_" + suffix):
                continue  # 已带后缀
            if base in known:
                new_name = performer_utils.resolve(base, suffix)
                if new_name != obj.name:
                    obj.name = new_name
                    renamed += 1
                    print(f"  [R] {obj.name} (原 {base})")
            elif re.fullmatch(r"string\d+", base):
                obj.name = f"{base}_{suffix}"
                renamed += 1
                print(f"  [R] {obj.name} (弦对象)")
            else:
                warnings.append((obj.name, base))

        # 3) 集合改名 + 归类
        performer = performer_utils.get_or_create_performer(
            suffix, performer_name, self.instruments_name, target_skeleton=skel)
        if addons_coll is not None:
            new_addons = performer_utils.get_or_create_collection(
                suffix, "addons", parent=performer.collection)
            for coll in list(addons_coll.children):
                base = performer_utils.strip_duplicate_suffix(coll.name)
                new_coll = performer_utils.get_or_create_collection(
                    suffix, base, parent=new_addons)
                self._move_objects(coll, new_coll)
                self._move_children(coll, new_coll, suffix)
                bpy.data.collections.remove(coll, do_unlink=True)
            self._move_objects(addons_coll, new_addons)
            # 从旧位置移除 addons（collection.users 是引用计数 int，不能遍历）
            for coll in list(bpy.data.collections):
                if addons_coll.name in coll.children:
                    coll.children.unlink(addons_coll)
            bpy.data.collections.remove(addons_coll, do_unlink=True)
            print(f"  [C] addons -> {new_addons.name}")

        # 4) 人物归类：Body_<后缀>（骨骼 + Mesh）
        body_coll = performer_utils.get_or_create_collection(
            suffix, "Body", parent=performer.collection)
        for obj in [skel] + self._collect_meshes(skel):
            self.move_object_to_collection(obj, body_coll)
            if obj != skel and obj.parent != skel:
                obj.parent = skel
        print(f"  [C] Body -> {body_coll.name}（骨骼+Mesh 已归位）")

        # 4b) 乐器物体归位到 Instruments_<后缀>
        self._organize_instrument()

        # 5) 重建 ext driver（对象已带新后缀）
        try:
            self.add_ext_drivers()
            print("  [D] ext driver 已按新后缀重建")
        except Exception as e:
            print(f"  [WARN] 重建 ext driver 失败: {e}")

        # 5b) 创建演奏者根 <缩写>_<名称>，挂接骨骼/控制器根/乐器
        self._organize_performer_root()

        # 6) 状态数据搬到骨骼（扫描全场景，支持中断后续跑）
        for obj in bpy.data.objects:
            if obj is not skel and obj.get("fret_dance_controller_data"):
                skel["fret_dance_controller_data"] = obj["fret_dance_controller_data"]
                del obj["fret_dance_controller_data"]
                print(f"  [M] 状态数据从 {obj.name} 搬到骨骼")
                break

        # 7) 写演奏者元信息与设置
        skel["fret_dance_instrument"] = int(self.instruments)
        skel["fret_dance_use_vibrato_bar"] = bool(self.use_vibrato_bar)
        from ..common import instrument_base
        instrument_base.set_coll_attr(
            performer.collection, "name", performer_name or suffix)
        instrument_base.set_coll_attr(
            performer.collection, "instrument", self.instruments_name)
        instrument_base.set_coll_attr(
            performer.collection, "skeleton", skel.name)
        print("  [M] 演奏者元信息与设置已写入")

        print("\n" + "=" * 60)
        print(f"迁移完成：改名 {renamed} 个对象，演奏者 {performer_name} ({suffix})")
        if warnings:
            print("以下对象无法识别短名，未自动改名（请手动确认）：")
            for name, base in warnings:
                print(f"  • {name}")
        print("=" * 60)
        return True

    def _expected_short_names(self):
        """从插件配置推导所有已知短名（对象层）"""
        names = set()
        names.update(self.left_hand_controllers.values())
        names.update(self.right_hand_controllers.values())
        names.update(self.left_finger_controllers.values())
        names.update(self.right_finger_controllers.values())
        names.add("controller_root")
        names.add("controller_root_offset")
        names.update(self.guitar_fret_positions.values())
        for hand in ["L", "R"]:
            for finger in ["T", "I", "M", "R", "P"]:
                names.add(f"ext_{finger}_{hand}")
                if finger == "T":
                    names.add(f"TP_{hand}")
                else:
                    names.add(f"{finger}_{hand}_pole")
        return names

    def _collect_meshes(self, skel):
        """收集要归类的 Mesh：骨骼子级"""
        result = []
        for child in skel.children:
            if child.type == "MESH" and child not in result:
                result.append(child)
        return result

    def _move_objects(self, src_coll, dst_coll):
        for obj in list(src_coll.objects):
            self.move_object_to_collection(obj, dst_coll)

    def _move_children(self, src_coll, dst_coll, suffix):
        for child in list(src_coll.children):
            base = performer_utils.strip_duplicate_suffix(child.name)
            new_child = performer_utils.get_or_create_collection(
                suffix, base, parent=dst_coll)
            self._move_objects(child, new_child)
            self._move_children(child, new_child, suffix)
            bpy.data.collections.remove(child, do_unlink=True)

    def unlock_object_location(self, obj):
        obj.lock_location[0] = False  # X
        obj.lock_location[1] = False  # Y
        obj.lock_location[2] = False  # Z

    def unlock_object_rotation(self, obj):
        obj.lock_rotation[0] = False  # X
        obj.lock_rotation[1] = False  # Y
        obj.lock_rotation[2] = False  # Z
