# zheng_drift/config.py
"""ZhengDrift 乐器模块 —— 配置（迁移自 zheng_blender_addon/zheng_controllers.py
+ zheng_recorders.py + zheng_helpers.py）

命名接演奏者后缀（<短名>_<后缀>）；集合/物体创建改调 common.object_utils；
controller_root 作为固定乐器根（古筝固定不动，无 controller_root_offset）。

层级约定：
- 控制器（手掌/枢轴/双脚）挂 controller_root，随演奏者根整体移动/缩放；
- 特殊朝向控制器（Middle_Hand / Look_At / Head_Control）保持世界对象：
  Middle_Hand 用世界空间 driver 取 H_L/H_R 中点，Head_Control 用 TrackTo 跟随，
  父级化反而会造成「本地 vs 世界」坐标错位，故不挂根；
- 记录器（弦 s{i}head/end/mid 与左右手状态）保持世界对象（等价于 key_ripple 把
  状态存骨骼的做法：记录器即状态存储，Rust 端按世界坐标消费），不挂 controller_root。
"""

import bpy  # type: ignore
from mathutils import Vector  # type: ignore

from ..common import performer_utils
from ..common import object_utils

from .enums import (
    LeftHandAction, RightHandAction, HandPosition, ObjectType, CheckResult,
)


class ZhengConfig:
    """古筝（21 弦）配置：命名表 + 控制器/记录器创建 + setup（多演奏者命名空间）"""

    def __init__(self, performer_suffix: str = "",
                 target_skeleton=None, target_instrument=None,
                 performer_name=None):
        self.suffix: str = performer_suffix
        self.target_skeleton = target_skeleton
        self.target_instrument = target_instrument
        self.performer_name: str = performer_name or (
            performer_suffix if performer_suffix else "Performer")
        self.instruments_name: str = "zheng_drift"

        # ── 左手系统（12 个控制器：7 主控 + 5 手指极向量） ──
        self.left_hand_controllers = {
            "left_hand_controller": "H_L",
            "left_hand_ik_pivot": "HP_L",
            "left_thumb_controller": "T_L",
            "left_index_controller": "I_L",
            "left_middle_controller": "M_L",
            "left_ring_controller": "R_L",
            "left_little_controller": "P_L",
            "left_thumb_pole": "T_L_pole",
            "left_index_pole": "I_L_pole",
            "left_middle_pole": "M_L_pole",
            "left_ring_pole": "R_L_pole",
            "left_little_pole": "P_L_pole",
        }

        # ── 右手系统（12 个控制器） ──
        self.right_hand_controllers = {
            "right_hand_controller": "H_R",
            "right_hand_ik_pivot": "HP_R",
            "right_thumb_controller": "T_R",
            "right_index_controller": "I_R",
            "right_middle_controller": "M_R",
            "right_ring_controller": "R_R",
            "right_little_controller": "P_R",
            "right_thumb_pole": "T_R_pole",
            "right_index_pole": "I_R_pole",
            "right_middle_pole": "M_R_pole",
            "right_ring_pole": "R_R_pole",
            "right_little_pole": "P_R_pole",
        }

        # ── 特殊朝向控制器（3 个） ──
        self.special_target_controllers = {
            "middle_hand": "Middle_Hand",
            "look_at": "Look_At",
            "head_control": "Head_Control",
        }

        # ── 双线性映射辅助控制器（8 个球形空物体，可导出/导入） ──
        self.bilinear_helpers = {
            "middle_hand_a": "Middle_Hand_A",
            "middle_hand_b": "Middle_Hand_B",
            "middle_hand_c": "Middle_Hand_C",
            "middle_hand_d": "Middle_Hand_D",
            "head_control_a": "Head_Control_A",
            "head_control_b": "Head_Control_B",
            "head_control_c": "Head_Control_C",
            "head_control_d": "Head_Control_D",
        }

        # ── 双脚控制器（4 个） ──
        self.foot_controllers = {
            "left_foot_controller": "F_L",
            "left_foot_pole": "F_L_pole",
            "right_foot_controller": "F_R",
            "right_foot_pole": "F_R_pole",
        }

        # ── 弦位置记录器（63 个：21 弦 × head/end/mid） ──
        self.string_recorders = {}
        for string_index in range(21):  # 0-20 弦
            self.string_recorders[f's{string_index}_head'] = f's{string_index}head'
            self.string_recorders[f's{string_index}_end'] = f's{string_index}end'
            self.string_recorders[f's{string_index}_mid'] = f's{string_index}mid'

        # 用于记录添加控件前的对象名称
        self.pre_obj_names = []

        # 注册 bilinear_map 函数到 driver namespace（幂等）
        self._register_bilinear_map()

    # ── 后缀化命名 ──────────────────────────────────────────

    def obj_name(self, short: str) -> str:
        """短名 → 完整对象名（带演奏者后缀）"""
        return performer_utils.resolve(short, self.suffix)

    def obj(self, short: str):
        """按短名取对象"""
        return bpy.data.objects.get(self.obj_name(short))

    # ── 集合/物体创建（改调 common） ────────────────────────

    def get_or_create_collection(self, name, parent_collection=None):
        """获取或创建集合（自动按演奏者后缀拼接完整集合名）"""
        full_name = self.obj_name(name)
        return object_utils.get_or_create_collection(full_name, parent_collection)

    def create_or_update_object(self, obj_name, obj_type=ObjectType.SPHERE_EMPTY,
                                collection=None, rotation_mode='QUATERNION',
                                scale=1.0):
        """创建或更新物体（obj_type 为 ObjectType 枚举或 object_utils 字符串；控件统一为球形空物体）"""
        if isinstance(obj_type, ObjectType):
            obj_type = obj_type.value
        if hasattr(self, 'pre_obj_names') and obj_name in self.pre_obj_names:
            self.pre_obj_names.remove(obj_name)
        return object_utils.create_or_update_object(
            obj_name, obj_type, collection, rotation_mode, scale=scale)

    def move_object_to_collection(self, obj, collection):
        """将对象移动到指定集合"""
        object_utils.move_object_to_collection(obj, collection)

    # ── 控制器创建 ──────────────────────────────────────────

    def add_controllers(self) -> None:
        """添加所有控制器到 Blender 场景（含 controller_root 与特殊朝向控制器）"""
        print("\n添加控制器...")

        # 确保在对象模式下操作
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 获取主集合（addons 目录；角色未初始化时为空）
        main_collection = self._get_addons_collection()
        if main_collection is None:
            print("[ERROR] 未找到 addons 目录，请先新建角色（初始化角色）。")
            return

        controllers_collection = self.get_or_create_collection(
            "Controllers", main_collection)

        # 控制器根节点（固定乐器，无 controller_root_offset）
        controller_root = self.create_or_update_object(
            self.obj_name("controller_root"), ObjectType.SPHERE_EMPTY, controllers_collection)

        foot_collection = self.get_or_create_collection(
            "Foot_Controllers", controllers_collection)
        hand_collection = self.get_or_create_collection(
            "Hand_Controllers", controllers_collection)
        left_hand_collection = self.get_or_create_collection(
            "Left_Hand", hand_collection)
        right_hand_collection = self.get_or_create_collection(
            "Right_Hand", hand_collection)
        target_collection = self.get_or_create_collection(
            "Target_Controllers", controllers_collection)
        bilinear_collection = self.get_or_create_collection(
            "Bilinear_Helpers", controllers_collection)

        # 双脚控制器（球形空物体；极向量 pole 用空环）
        for controller_name, obj_name in self.foot_controllers.items():
            obj_type = (ObjectType.CIRCLE_EMPTY if obj_name.endswith("_pole")
                        else ObjectType.SPHERE_EMPTY)
            self.create_or_update_object(
                self.obj_name(obj_name), obj_type, foot_collection)

        # 左右手控制器（含手指极向量；极向量 pole 用空环，其余球形空物体）
        for controller_name, obj_name in self.left_hand_controllers.items():
            obj_type = (ObjectType.CIRCLE_EMPTY if obj_name.endswith("_pole")
                        else ObjectType.SPHERE_EMPTY)
            self.create_or_update_object(
                self.obj_name(obj_name), obj_type, left_hand_collection)
        for controller_name, obj_name in self.right_hand_controllers.items():
            obj_type = (ObjectType.CIRCLE_EMPTY if obj_name.endswith("_pole")
                        else ObjectType.SPHERE_EMPTY)
            self.create_or_update_object(
                self.obj_name(obj_name), obj_type, right_hand_collection)

        # 特殊朝向控制器（球形空物体）
        for controller_name, obj_name in self.special_target_controllers.items():
            self.create_or_update_object(
                self.obj_name(obj_name), ObjectType.SPHERE_EMPTY, target_collection)

        # 双线性映射辅助控制器（球形空物体）
        print("\n创建双线性映射辅助控制器...")
        for controller_name, obj_name in self.bilinear_helpers.items():
            self.create_or_update_object(
                self.obj_name(obj_name), ObjectType.SPHERE_EMPTY, bilinear_collection)

        # 手指控制器挂到手掌控制器下，并创建 ext 辅助控件
        print("\n设置手指层级与创建 ext 辅助控件...")
        left_fingers = ["T_L", "I_L", "M_L", "R_L", "P_L"]
        right_fingers = ["T_R", "I_R", "M_R", "R_R", "P_R"]

        for hand_name, finger_names, collection in [
                ("H_L", left_fingers, left_hand_collection),
                ("H_R", right_fingers, right_hand_collection)]:
            palm_obj = self.obj(hand_name)
            if palm_obj is None:
                print(f"  • 手掌控制器 {self.obj_name(hand_name)} 不存在，跳过")
                continue
            for finger_name in finger_names:
                finger_obj = self.obj(finger_name)
                if finger_obj and finger_obj.parent != palm_obj:
                    finger_obj.parent = palm_obj
                    print(f"  ✓ 设置父子关系：{finger_obj.name} → {palm_obj.name}")
                ext_obj = self.create_or_update_object(
                    self.obj_name(
                        f"ext_{finger_name}"), ObjectType.SPHERE_EMPTY, collection,
                    scale=0.7)
                if ext_obj.parent != palm_obj:
                    ext_obj.parent = palm_obj
                    print(f"  ✓ 设置父子关系：{ext_obj.name} → {palm_obj.name}")

        # 手指极向量挂到对应 ext 控件下
        finger_poles = {
            "T_L_pole": "ext_T_L", "I_L_pole": "ext_I_L",
            "M_L_pole": "ext_M_L", "R_L_pole": "ext_R_L",
            "P_L_pole": "ext_P_L",
            "T_R_pole": "ext_T_R", "I_R_pole": "ext_I_R",
            "M_R_pole": "ext_M_R", "R_R_pole": "ext_R_R",
            "P_R_pole": "ext_P_R",
        }
        for pole_name, parent_name in finger_poles.items():
            pole_obj = self.obj(pole_name)
            parent_obj = self.obj(parent_name)
            if pole_obj and parent_obj and pole_obj.parent != parent_obj:
                pole_obj.parent = parent_obj
                print(f"  ✓ 设置父子关系：{pole_obj.name} → {parent_obj.name}")

        # 手掌/枢轴/双脚 → controller_root（其它控件最低以 controller_root 为父级；
        # 古筝固定不动，无需 controller_root_offset）
        for name in ["HP_L", "H_L", "HP_R", "H_R", "F_L", "F_R"]:
            self._set_parent(name, controller_root)

        # 特殊朝向控制器设置（Middle_Hand driver / Look_At / Head_Control）
        self._setup_special_controllers()

        print("  ✓ 控制器添加完成")

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

    def _setup_special_controllers(self) -> None:
        """为特殊朝向控制器添加 driver、父子关系和约束器。

        Middle_Hand / Look_At / Head_Control 保持世界对象（不挂 controller_root），
        避免「本地 vs 世界」坐标错位；Middle_Hand 用世界空间 driver 取 H_L/H_R 中点。
        """
        print("\n=== 设置特殊朝向控制器 ===")
        try:
            h_l_obj = self.obj("H_L")
            h_r_obj = self.obj("H_R")
            middle_hand_obj = self.obj("Middle_Hand")
            look_at_obj = self.obj("Look_At")
            head_control_obj = self.obj("Head_Control")

            if not all([h_l_obj, h_r_obj, middle_hand_obj, look_at_obj, head_control_obj]):
                print("  ✗ 找不到必要的控制器对象")
                return

            # 1. Middle_Hand driver：XYZ 位于 H_L / H_R 的世界中点
            print("\n设置 Middle_Hand Driver...")
            middle_hand_obj.animation_data_clear()
            for axis_index, axis_name in enumerate(['x', 'y', 'z']):
                driver = middle_hand_obj.driver_add(
                    "location", axis_index).driver
                driver.type = 'SCRIPTED'
                var1 = driver.variables.new()
                var1.name = f"h_l_{axis_name}"
                var1.type = 'TRANSFORMS'
                target1 = var1.targets[0]
                target1.id = h_l_obj
                target1.transform_type = f'LOC_{axis_name.upper()}'
                target1.transform_space = 'WORLD_SPACE'
                var2 = driver.variables.new()
                var2.name = f"h_r_{axis_name}"
                var2.type = 'TRANSFORMS'
                target2 = var2.targets[0]
                target2.id = h_r_obj
                target2.transform_type = f'LOC_{axis_name.upper()}'
                target2.transform_space = 'WORLD_SPACE'
                driver.expression = f"(h_l_{axis_name} + h_r_{axis_name}) / 2"
            print("  ✓ 已为 Middle_Hand 添加 XYZ 世界中点 driver")

            # 2. Look_At 为 Middle_Hand 的子级
            print("\n设置 Look_At 父子关系...")
            if look_at_obj.parent != middle_hand_obj:
                look_at_obj.parent = middle_hand_obj
                print("  ✓ 已设置 Look_At 为 Middle_Hand 的子级")

            # 3. Head_Control 添加 TrackTo 约束器（目标是 Look_At）
            print("\n设置 Head_Control 约束器...")
            for constraint in list(head_control_obj.constraints):
                head_control_obj.constraints.remove(constraint)
            track_to_constraint = head_control_obj.constraints.new('TRACK_TO')
            track_to_constraint.name = "Track_Look_At"
            track_to_constraint.target = look_at_obj
            track_to_constraint.track_axis = 'TRACK_Z'
            track_to_constraint.up_axis = 'UP_Y'
            print("  ✓ 已添加 TrackTo 约束器")

            print("=== 特殊朝向控制器设置完成 ===\n")
        except Exception as e:
            print(f"\n✗ 特殊朝向控制器设置失败：{str(e)}")
            import traceback
            traceback.print_exc()

    # ── ext 驱动 ────────────────────────────────────────────

    def add_ext_drivers(self) -> None:
        """为每个手指的 ext 辅助控件添加 driver（ext.local = 2 * 手指.local）"""
        print("\n添加手指 ext 控制器驱动...")
        left_fingers = ["T_L", "I_L", "M_L", "R_L", "P_L"]
        right_fingers = ["T_R", "I_R", "M_R", "R_R", "P_R"]
        for finger_name in left_fingers + right_fingers:
            self._add_ext_driver(finger_name)
        print("  ✓ 手指 ext 控制器驱动设置完成")

    def _add_ext_driver(self, finger_name: str) -> None:
        """为单个手指的 ext 辅助控件添加 location 驱动"""
        ext_name = self.obj_name(f"ext_{finger_name}")
        full_ctrl = self.obj_name(finger_name)

        if full_ctrl not in bpy.data.objects:
            print(f"  • 手指控制器 {full_ctrl} 不存在，跳过驱动")
            return
        if ext_name not in bpy.data.objects:
            print(f"  • ext 控件 {ext_name} 不存在，跳过驱动")
            return

        ext_obj = bpy.data.objects[ext_name]

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
            target_f.id = bpy.data.objects[full_ctrl]
            target_f.transform_type = f'LOC_{axis_char}'
            target_f.transform_space = 'LOCAL_SPACE'
            driver.expression = "2 * finger"

        print(f"  ✓ 已为 {ext_name} 添加驱动: 2 * {full_ctrl}")

    # ── 记录器创建 ──────────────────────────────────────────

    def add_recorders(self) -> None:
        """添加弦位置标记到 Blender 场景（物理参考点，供弦工具/导出使用）。

        左右手状态不再生成记录器物体，统一存演奏者骨骼自定义属性。
        """
        print("\n添加弦位置记录器...")

        main_collection = self._get_addons_collection()
        if main_collection is None:
            print("[ERROR] 未找到 addons 目录，请先新建角色（初始化角色）。")
            return

        recorders_collection = self.get_or_create_collection(
            "Recorders", main_collection)
        string_collection = self.get_or_create_collection(
            "String_Positions", recorders_collection)
        # Direction_Lines 保留空集合（与源码一致）
        self.get_or_create_collection("Direction_Lines", recorders_collection)

        for recorder_key, obj_name in self.string_recorders.items():
            self.create_or_update_object(
                self.obj_name(obj_name), ObjectType.SPHERE_EMPTY, string_collection)

        print("  ✓ 弦位置记录器添加完成")

    # ── 状态检查 ────────────────────────────────────────────

    def check_all_objects(self) -> CheckResult:
        """检查所有对象的创建状态（仅当前演奏者命名空间）"""
        print("=" * 60)
        print("Zheng Blender插件对象状态检查")
        print("=" * 60)

        existing_ctrl = 0
        missing_ctrl = 0
        existing_rec = 0
        missing_rec = 0

        all_controllers = (
            self.foot_controllers
            | self.left_hand_controllers
            | self.right_hand_controllers
            | self.special_target_controllers
        )

        print("\n【控制器状态】")
        for controller_key, obj_name in all_controllers.items():
            full = self.obj_name(obj_name)
            if full in bpy.data.objects:
                print(f"  ✓ {full}")
                existing_ctrl += 1
            else:
                print(f"  ✗ {full} (缺失)")
                missing_ctrl += 1

        all_recorders = self.string_recorders

        print(f"\n【弦位置记录器状态】(共 {len(all_recorders)} 个)")
        print(f"  string_recorders: {len(self.string_recorders)}")

        import sys
        for recorder_key, obj_name in all_recorders.items():
            full = self.obj_name(obj_name)
            if full in bpy.data.objects:
                print(f"  ✓ {full}")
                existing_rec += 1
            else:
                print(f"  ✗ {full} (缺失)")
                missing_rec += 1

        sys.stdout.flush()

        total_ctrl = len(all_controllers)
        total_rec = len(all_recorders)
        total_objects = total_ctrl + total_rec
        total_existing = existing_ctrl + existing_rec
        total_missing = missing_ctrl + missing_rec

        print(f"\n【统计信息】")
        print(f"控制器总数：{total_ctrl}")
        print(f"已存在：{existing_ctrl}, 缺失：{missing_ctrl}")
        print(f"记录器总数：{total_rec}")
        print(f"已存在：{existing_rec}, 缺失：{missing_rec}")
        print(f"对象总计：{total_objects}")
        print(f"已存在：{total_existing}, 缺失：{total_missing}")
        print(
            f"完成度：{total_existing/total_objects*100:.1f}%" if total_objects > 0 else "完成度：0%")

        return {
            'controllers': {'existing': existing_ctrl, 'missing': missing_ctrl, 'total': total_ctrl},
            'recorders': {'existing': existing_rec, 'missing': missing_rec, 'total': total_rec},
            'overall': {'existing': total_existing, 'missing': total_missing, 'total': total_objects}
        }

    # ── 一次性设置 ──────────────────────────────────────────

    def setup_all_objects(self) -> bool:
        """一次性设置所有控制器和记录器（幂等）。

        有后缀时要求角色已初始化（addons_<后缀> 存在）；否则提示先新建角色并中止。
        返回 True 表示成功，False 表示因角色未初始化而中止。
        """
        # 有后缀：先确认角色已初始化（addons 目录必须存在），否则提示先新建角色
        if self.suffix and performer_utils.find_addons_collection(self.suffix) is None:
            print("[ERROR] 未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）后重试。")
            return False

        # 整理演奏者 Body（骨骼/Mesh 归位）与乐器目录（幂等；角色初始化已做，这里兜底）
        self._organize_body()
        self._organize_instrument()

        # 记录添加控件前 addons 目录及其子集合中的所有物体名称（仅本演奏者）
        self.pre_obj_names = []
        addons_collection = self._get_addons_collection()
        if addons_collection is None:
            print("[ERROR] 未找到角色 addons 目录，请先新建角色（初始化角色）。")
            return False
        collections_to_check = [addons_collection]
        for coll in addons_collection.children_recursive:
            collections_to_check.append(coll)
        for coll in collections_to_check:
            for obj in coll.objects:
                self.pre_obj_names.append(obj.name)

        # 添加控制器、驱动与弦位置记录器
        self.add_controllers()
        self.add_ext_drivers()
        self.add_recorders()

        # 演奏者根 <缩写>_<名称>（挂接骨骼 / controller_root；乐器不挂根）
        self._organize_performer_root()

        # 打印未使用的控件名称
        if self.pre_obj_names:
            print("\n未使用的控件:")
            for obj_name in self.pre_obj_names:
                print(f"  • {obj_name}")
        else:
            print("\n没有发现未使用的控件")
        return True

    # ── 演奏者结构与根 ───────────────────────────────────────

    def _get_performer_collection(self):
        """获取当前演奏者集合（仅后缀模式；角色未初始化返回 None）"""
        if not self.suffix:
            return None
        return performer_utils.get_performer(self.suffix)

    def _get_addons_collection(self):
        """获取本演奏者的 addons 目录。

        - 有后缀：只查找角色初始化时创建的 addons_<后缀>；找不到返回 None
        - 无后缀（兼容旧场景）：全局根下的 addons（找不到时按需创建）
        """
        if self.suffix:
            return performer_utils.find_addons_collection(self.suffix)
        return self.get_or_create_collection("addons")

    def _organize_body(self):
        """把目标骨骼和它的 Mesh 归位到 Body_<后缀>（仅后缀模式）"""
        if not self.suffix:
            return
        performer = self._get_performer_collection()
        if performer is None:
            return
        body_coll = performer_utils.get_or_create_collection(
            self.suffix, "Body", parent=performer.collection)
        skeleton = self.target_skeleton or performer.target_skeleton
        if skeleton is None:
            print("  • 未指定目标骨骼，跳过 Body 归位")
            return
        self.move_object_to_collection(skeleton, body_coll)
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
        performer = self._get_performer_collection()
        if performer is None:
            return
        inst_coll = performer_utils.get_or_create_collection(
            self.suffix, "Instruments", parent=performer.collection)
        self.move_object_to_collection(inst, inst_coll)
        print(f"  ✓ 乐器 {inst.name} 已归位到 {inst_coll.name}")

    def _organize_performer_root(self):
        """创建演奏者根空物体 <乐器缩写>_<名称>，作为骨骼 / controller_root 的父级（仅后缀模式）

        古筝固定不动：乐器（琴）由用户手动绑定到 controller_root；不挂根。
        """
        if not self.suffix:
            return
        performer = self._get_performer_collection()
        if performer is None:
            return
        root_obj = performer_utils.get_or_create_performer_root(
            performer, performer.collection)

        # 子级：骨骼（body）与控制器根；乐器由用户手动绑定到 controller_root
        skeleton = self.target_skeleton or performer.target_skeleton
        self._parent_to(root_obj, skeleton)
        self._parent_to(root_obj, self.obj("controller_root"))
        print(
            f"  ✓ 演奏者根 {root_obj.name} 就绪（骨骼/controller_root 已挂到其下；乐器请手动绑定到 controller_root）")

    def _parent_to(self, parent_obj, child_obj):
        object_utils.parent_to(parent_obj, child_obj)

    # ── bilinear_map 双线性映射 ─────────────────────────────

    def _register_bilinear_map(self):
        """注册 bilinear_map 函数到 bpy.app.driver_namespace（幂等）"""
        if "bilinear_map" not in bpy.app.driver_namespace:
            bpy.app.driver_namespace["bilinear_map"] = self._bilinear_map_func

    @staticmethod
    def _bilinear_map_func(px, py, pz,
                           a0x, a0y, a0z, a1x, a1y, a1z, a2x, a2y, a2z, a3x, a3y, a3z,
                           b0x, b0y, b0z, b1x, b1y, b1z, b2x, b2y, b2z, b3x, b3y, b3z,
                           axis):
        """通过三角形重心坐标法，将点 P 从四边形 A 映射到四边形 B。

        四边形 A / B 顶点一一对应（凸四边形）。
        """
        P = Vector((px, py, pz))
        A = [Vector((a0x, a0y, a0z)),
             Vector((a1x, a1y, a1z)),
             Vector((a2x, a2y, a2z)),
             Vector((a3x, a3y, a3z))]
        B = [Vector((b0x, b0y, b0z)),
             Vector((b1x, b1y, b1z)),
             Vector((b2x, b2y, b2z)),
             Vector((b3x, b3y, b3z))]

        def triangle_area(v1, v2, v3):
            return (v2 - v1).cross(v3 - v1).length / 2.0

        def barycentric_coords(p, v0, v1, v2):
            area_total = triangle_area(v0, v1, v2)
            if area_total < 1e-10:
                return (1.0, 0.0, 0.0)
            u = triangle_area(p, v1, v2) / area_total
            v = triangle_area(p, v2, v0) / area_total
            w = 1.0 - u - v
            return (u, v, w)

        def inside_triangle(coords, eps=1e-5):
            return all(c >= -eps for c in coords)

        coords1 = barycentric_coords(P, A[0], A[1], A[2])
        if inside_triangle(coords1):
            u, v, w = coords1
            result = u * B[0] + v * B[1] + w * B[2]
        else:
            coords2 = barycentric_coords(P, A[0], A[2], A[3])
            u, v, w = coords2
            result = u * B[0] + v * B[2] + w * B[3]

        return result[axis]

    def clear_vector_interpolation_drivers(self, target) -> int:
        """清除目标物体上的向量插值 Driver（保留原实现，供工具/脚本使用）"""
        cleared_count = 0
        if target.animation_data:
            for i in range(3):
                driver = target.animation_data.drivers.find(
                    data_path="location", index=i)
                if driver is not None:
                    target.animation_data.drivers.remove(driver)
                    cleared_count += 1
        return cleared_count
