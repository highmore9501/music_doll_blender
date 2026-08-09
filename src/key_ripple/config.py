# key_ripple/config.py
"""KeyRipple 乐器模块 —— 配置（迁移自 key_ripple_blender/key_ripple_config.py）

命名接演奏者后缀（<短名>_<后缀>）；集合/物体创建改调 common.object_utils。
"""
from enum import Enum

import bpy  # type: ignore

from ..common import performer_utils
from ..common import object_utils


class HandType(Enum):
    LEFT = 'L'
    RIGHT = 'R'


class KeyType(Enum):
    WHITE = 'white'
    BLACK = 'black'


class PositionType(Enum):
    HIGH = 'high'
    LOW = 'low'
    MIDDLE = 'middle'


class KeyRipple:
    """当前blender中使用的配置文件（KeyRipple 钢琴）"""

    def __init__(self, one_hand_finger_number: int, leftest_position: int,
                 left_position: int, middle_left_position: int,
                 middle_right_position: int, right_position: int,
                 rightest_position: int, min_key: int, max_key: int,
                 hand_range: int, performer_suffix: str = "",
                 target_skeleton=None, target_instrument=None,
                 performer_name=None):
        # 键盘的基本设置
        self.one_hand_finger_number = one_hand_finger_number
        self.leftest_position = leftest_position
        self.left_position = left_position
        self.middle_left_position = middle_left_position
        self.middle_right_position = middle_right_position
        self.right_position = right_position
        self.rightest_position = rightest_position
        self.min_key = min_key
        self.max_key = max_key
        self.hand_range = hand_range

        # 演奏者后缀与目标（多演奏者命名空间 / 无状态化）
        self.suffix: str = performer_suffix
        self.target_skeleton = target_skeleton
        self.target_instrument = target_instrument
        self.performer_name: str = performer_name or (
            performer_suffix if performer_suffix else "Performer")
        self.instruments_name: str = "key_ripple"

        # 手指控制器信息
        self.finger_controllers = {}
        for finger_number in range(one_hand_finger_number):
            self.finger_controllers[finger_number] = f"{finger_number}_L"
        for finger_number in range(one_hand_finger_number, 2*one_hand_finger_number):
            self.finger_controllers[finger_number] = f"{finger_number}_R"

        # 手掌控制器信息
        self.hand_controllers = {
            "left_hand_controller": "H_L",
            "left_hand_pivot_controller": "HP_L",
            "right_hand_controller": "H_R",
            "right_hand_pivot_controller": "HP_R",
        }

        # 键盘基准点信息
        self.key_board_positions = {
            "black_key_position": "black_key",
            "highest_white_key_position": "highest_white_key",
            "lowest_white_key_position": "lowest_white_key",
            "lowest_white_key_position_end": "lowest_white_key_end",
            "normal_hand_expand_position": "normal_hand_expand_position",
            "wide_expand_hand_position": "wide_expand_hand_position"
        }

        # 接下来是一些辅助线
        self.guidelines = {
            "press_key_direction": "press_key_direction",
        }

        # 辅助目标点
        self.target_points = {
            "mid_hand_target": "Mid_Hand",
            "look_at_target": "Look_At",
            "head_control_target": "Head_Control"
        }

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

    def create_or_update_object(self, obj_name, obj_type="cube",
                                collection=None, rotation_mode='QUATERNION',
                                scale=1.0):
        """创建或更新物体的通用方法"""
        if hasattr(self, 'pre_obj_names') and obj_name in self.pre_obj_names:
            self.pre_obj_names.remove(obj_name)
        return object_utils.create_or_update_object(
            obj_name, obj_type, collection, rotation_mode, scale=scale)

    def move_object_to_collection(self, obj, collection):
        """将对象移动到指定集合"""
        object_utils.move_object_to_collection(obj, collection)

    def add_controllers(self):
        # 确保在对象模式下操作
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 获取主集合（addons 目录；角色未初始化时为空）
        main_collection = self._get_addons_collection()
        if main_collection is None:
            print("[ERROR] 未找到 addons 目录，请先新建角色（初始化角色）。")
            return

        # 创建控制器集合
        controllers_collection = self.get_or_create_collection(
            "Controllers", main_collection)

        # 创建控制器根节点（空物体；钢琴固定不动，不需要 controller_root_offset）
        self.create_or_update_object(
            self.obj_name("controller_root"), "sphere", controllers_collection)

        # 创建左右手子集合
        left_hand_controller_collection = self.get_or_create_collection(
            "Left_Hand_Controllers", controllers_collection)
        right_hand_controller_collection = self.get_or_create_collection(
            "Right_Hand_Controllers", controllers_collection)

        # 创建手指控制器
        for finger_number, controller_name in self.finger_controllers.items():
            if finger_number < self.one_hand_finger_number:
                self.create_or_update_object(
                    self.obj_name(controller_name), "cube", left_hand_controller_collection)
            else:
                self.create_or_update_object(
                    self.obj_name(controller_name), "cube", right_hand_controller_collection)

        # 创建手指辅助控件（ext_ 前缀）
        for finger_number, controller_name in self.finger_controllers.items():
            ext_name = self.obj_name(f"ext_{controller_name}")
            if finger_number < self.one_hand_finger_number:
                self.create_or_update_object(
                    ext_name, "cube", left_hand_controller_collection, scale=0.7)
            else:
                self.create_or_update_object(
                    ext_name, "cube", right_hand_controller_collection, scale=0.7)

        # 创建手掌控制器
        for hand_controller_name, controller_name in self.hand_controllers.items():
            if controller_name.endswith("_L"):
                collection = left_hand_controller_collection
            else:
                collection = right_hand_controller_collection
            self.create_or_update_object(
                self.obj_name(controller_name), "cube", collection)

        # 将手指控制器和 ext 控件设置为对应手掌控制器的子级
        for finger_number, controller_name in self.finger_controllers.items():
            if finger_number < self.one_hand_finger_number:
                palm_name = self.hand_controllers["left_hand_controller"]
            else:
                palm_name = self.hand_controllers["right_hand_controller"]

            palm_obj = bpy.data.objects.get(self.obj_name(palm_name))
            if palm_obj is None:
                continue

            finger_obj = bpy.data.objects.get(self.obj_name(controller_name))
            if finger_obj:
                finger_obj.parent = palm_obj

            ext_obj = bpy.data.objects.get(
                self.obj_name(f"ext_{controller_name}"))
            if ext_obj:
                ext_obj.parent = palm_obj

        # 手掌/枢轴 → controller_root（其它控件最低以 controller_root 为父级；
        # 钢琴固定不动，无需 controller_root_offset）
        controller_root = self.obj("controller_root")
        for name in ["HP_L", "H_L", "HP_R", "H_R"]:
            self._set_parent(name, controller_root)

        # 创建键盘基准点，并挂到 controller_root 下（钢琴固定，随 body 整体移动）
        positions_collection = self.get_or_create_collection(
            "Keyboard_Positions", controllers_collection)
        for position_name, obj_name in self.key_board_positions.items():
            self.create_or_update_object(
                self.obj_name(obj_name), "sphere", positions_collection)
        for obj_name in self.key_board_positions.values():
            self._set_parent(obj_name, controller_root)

        # 创建特殊的目标控制器（Mid_Hand / Look_At / Head_Control）
        # —— 对应 Rust 侧头部朝向动画（resolve/mid_hand.rs 读 *_Head_Control 记录器）、
        #    以及动画生成时需保留驱动/关键帧的 Mid_Hand（make_animation 专门跳过它）。
        #    原版历史版本在 add_controllers 里创建这些控件；当前 Rust 原版与旧移植版
        #    都丢了这段，导致三个控件从未被创建、Head_Control 状态无法保存。
        target_collection = self.get_or_create_collection(
            "Target_Controllers", controllers_collection)
        for target_key, target_name in self.target_points.items():
            self.create_or_update_object(
                self.obj_name(target_name), "cube", target_collection)

        # Mid_Hand 加 XYZ 驱动（居中于 H_L/H_R）；Look_At 挂到 Mid_Hand 下
        mid_hand = self.obj("Mid_Hand")
        look_at = self.obj("Look_At")
        if mid_hand is not None:
            self.add_mid_hand_driver(mid_hand)
            if look_at is not None:
                self.set_look_at_parent(look_at, mid_hand)

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

    def add_mid_hand_driver(self, mid_hand_obj):
        """为 Mid_Hand 添加驱动，使其位置正好位于 H_L 和 H_R 的正中间"""
        if mid_hand_obj.animation_data:
            mid_hand_obj.animation_data_clear()
            print(f"已清除 {mid_hand_obj.name} 的动画数据")

        h_l_name = self.obj_name(
            self.hand_controllers["left_hand_controller"])  # H_L
        h_r_name = self.obj_name(
            self.hand_controllers["right_hand_controller"])  # H_R

        for axis_index, axis_name in enumerate(['x', 'y', 'z']):
            driver = mid_hand_obj.driver_add("location", axis_index).driver
            driver.type = 'SCRIPTED'

            var1 = driver.variables.new()
            var1.name = f"h_l_{axis_name}"
            var1.type = 'TRANSFORMS'
            target1 = var1.targets[0]
            target1.id = bpy.data.objects.get(h_l_name)
            target1.transform_type = f'LOC_{axis_name.upper()}'
            target1.transform_space = 'WORLD_SPACE'

            var2 = driver.variables.new()
            var2.name = f"h_r_{axis_name}"
            var2.type = 'TRANSFORMS'
            target2 = var2.targets[0]
            target2.id = bpy.data.objects.get(h_r_name)
            target2.transform_type = f'LOC_{axis_name.upper()}'
            target2.transform_space = 'WORLD_SPACE'

            driver.expression = f"(h_l_{axis_name} + h_r_{axis_name}) / 2"

        print(f"已为 {mid_hand_obj.name} 控制器添加 XYZ 轴驱动，表达式: (h_l + h_r) / 2")

    def set_look_at_parent(self, look_at_obj, mid_hand_obj):
        """将 Look_At 设为 Mid_Hand 的子级"""
        look_at_obj.parent = mid_hand_obj
        look_at_obj.location = (0, 0, 0)
        print(
            f"已将 {look_at_obj.name} 设为 {mid_hand_obj.name} 的子级，初始位置: [0, 0, 0]")

    def add_finger_pole_targets(self):
        """为所有手指控制器创建/更新 pole target（绑定在对应 ext 控件下）

        pole 按左右手分别归入 addons 下的 Left/Right_Hand_Controllers 目录。
        """
        print("\n添加手指Pole Targets...")

        # 获取左右手控制器集合（pole 按左右手归入对应目录）
        main_collection = self._get_addons_collection()
        controllers_collection = self.get_or_create_collection(
            "Controllers", main_collection)
        left_hand_collection = self.get_or_create_collection(
            "Left_Hand_Controllers", controllers_collection)
        right_hand_collection = self.get_or_create_collection(
            "Right_Hand_Controllers", controllers_collection)

        for controller_key, controller_name in self.finger_controllers.items():
            full_ctrl = self.obj_name(controller_name)
            if full_ctrl not in bpy.data.objects:
                print(f"  • 控制器 {full_ctrl} 不存在，跳过")
                continue

            ext_name = self.obj_name(f"ext_{controller_name}")
            if ext_name not in bpy.data.objects:
                print(f"  • ext 控件 {ext_name} 不存在，跳过")
                continue

            # 按左右手确定 pole 应归属的集合
            pole_collection = (left_hand_collection
                               if controller_key < self.one_hand_finger_number
                               else right_hand_collection)

            pole_target_name = self.obj_name(f"{controller_name}_pole")
            ext_obj = bpy.data.objects[ext_name]

            if pole_target_name not in bpy.data.objects:
                bpy.ops.object.empty_add(type='CIRCLE', radius=0.1)
                pole_target = bpy.context.active_object
                pole_target.name = pole_target_name
                pole_target.parent = ext_obj
                pole_target.location = (0, 0, 1.0)
                self.move_object_to_collection(pole_target, pole_collection)
                print(
                    f"  • 已为 {full_ctrl} 创建 pole target: {pole_target_name} -> {ext_name}（{pole_collection.name}）")
            else:
                pole_target = bpy.data.objects[pole_target_name]
                # 确保归入正确的左右手目录（幂等）
                if pole_target.name not in pole_collection.objects:
                    self.move_object_to_collection(
                        pole_target, pole_collection)
                    print(f"  • {pole_target_name} 已归入 {pole_collection.name}")
                if pole_target.parent != ext_obj:
                    pole_target.parent = ext_obj
                    print(f"  • {pole_target_name} 已重新绑定到 {ext_name} 下方")
                else:
                    print(f"  • {pole_target_name} 已存在且绑定正确，跳过")

    def add_ext_drivers(self):
        """为每个手指的 ext 辅助控件添加 driver（ext.local = 2 * 手指.local）"""
        print("\n添加手指 ext 控制器驱动...")

        for finger_number, controller_name in self.finger_controllers.items():
            ext_name = self.obj_name(f"ext_{controller_name}")
            full_ctrl = self.obj_name(controller_name)

            if full_ctrl not in bpy.data.objects:
                print(f"  • 手指控制器 {full_ctrl} 不存在，跳过驱动")
                continue
            if ext_name not in bpy.data.objects:
                print(f"  • ext 控件 {ext_name} 不存在，跳过驱动")
                continue

            ext_obj = bpy.data.objects[ext_name]

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

            print(
                f"  ✓ 已为 {ext_name} 添加驱动: 2 * {full_ctrl}")

    def setup_all_objects(self):
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

        # 添加控制器和记录器
        self.add_controllers()
        self.add_finger_pole_targets()
        self.add_ext_drivers()

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

        钢琴固定不动：乐器（键盘）由用户手动绑定到 controller_root；不挂根。
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

    def check_objects_status(self):
        """检查Blender场景中所有控制器的状态（仅当前演奏者命名空间）"""
        expected_objects = set()

        for controller_name in self.finger_controllers.values():
            expected_objects.add(self.obj_name(controller_name))
        for controller_name in self.hand_controllers.values():
            expected_objects.add(self.obj_name(controller_name))
        for obj_name in self.key_board_positions.values():
            expected_objects.add(self.obj_name(obj_name))
        for obj_name in self.target_points.values():
            expected_objects.add(self.obj_name(obj_name))

        actual_objects = set()
        addons_collection = self._get_addons_collection()
        if addons_collection is None:
            print("[ERROR] 未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）。")
            return
        collections_to_check = [addons_collection]
        collections_to_check.extend(addons_collection.children_recursive)
        for coll in collections_to_check:
            for obj in coll.objects:
                actual_objects.add(obj.name)

        existing_objects = expected_objects.intersection(actual_objects)
        missing_objects = expected_objects.difference(actual_objects)
        unexpected_objects = actual_objects.difference(expected_objects)

        print("=" * 50)
        print("KeyRipple 对象状态报告")
        print("=" * 50)
        print(f"\n✓ 存在的对象: {len(existing_objects)}/{len(expected_objects)}")
        if existing_objects:
            for obj_name in sorted(existing_objects):
                print(f"    • {obj_name}")
        print(f"\n✗ 缺失的对象: {len(missing_objects)}")
        if missing_objects:
            for obj_name in sorted(missing_objects):
                print(f"    • {obj_name}")
        print(f"\n? 额外的对象: {len(unexpected_objects)}")
        if unexpected_objects:
            for obj_name in sorted(unexpected_objects)[:20]:
                print(f"    • {obj_name}")
            if len(unexpected_objects) > 20:
                print(f"    ... 还有 {len(unexpected_objects) - 20} 个对象")
        print("\n" + "=" * 50)
