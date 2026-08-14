# string_flow/config.py
"""StringFlow 乐器模块 —— 配置（迁移自 string_flow_blender/string_flow.py）

命名接演奏者后缀（<短名>_<后缀>）；集合/物体创建改调 common.object_utils；
controller_root 作为固定乐器根（小提琴固定不动，无 controller_root_offset）。

与原架构的关键差异：
- 状态不再生成约 230 个记录器物体（sphere），统一存演奏者骨骼自定义属性（见 state.py）；
- 只保留物理位置标记对象：弦端点 position_s{i}_f0/f12、中点 mid_s{i}/f9_s{i}（带 driver）、
  middle_fret_board_position（三点定平面第三点，Rust 端与琴弦工具共用）；
- controller_root 替代原版硬编码的 "violin" 父级；
- 右手手指/拇指与手掌 H_R 挂 Bow_Controller（右手整体进入弓的局部空间）；
- 右手 ext 用 driver（Bow 局部空间 2*finger - palm）、左手 ext 用 driver（H_L 局部空间）；
- Bow_Controller 不再采集旋转（回放时由指向约束实时决定，Rust 端不读）。

层级约定（移植后）：
- 枢轴 HP_R / 弓 / 触弦点 → controller_root（原 violin 帧）；
- 左手手指/拇指/ext → H_L；右手手指/拇指/H_R/ext → Bow_Controller；
- pole（空环）→ 对应 ext 下，沿局部 Z 偏移 1.0；
- 物理位置标记不挂根（世界对象，Rust 按世界坐标消费）。
"""

import bpy  # type: ignore

from ..common import performer_utils
from ..common import object_utils

from .enums import ObjectType, LeftHandPositionType, RightHandPositionType, CheckResult


class StringFlowConfig:
    """小提琴（4 弦）配置：命名表 + 控制器/位置标记创建 + setup（多演奏者命名空间）"""

    def __init__(self, performer_suffix: str = "",
                 target_skeleton=None, target_instrument=None,
                 performer_name=None, one_hand_finger_number: int = 4):
        self.suffix: str = performer_suffix
        self.target_skeleton = target_skeleton
        self.target_instrument = target_instrument
        self.performer_name: str = performer_name or (
            performer_suffix if performer_suffix else "Performer")
        self.instruments_name: str = "string_flow"

        # 左手手指数量（可调 1~N；命名表按它生成，外星人多指也支持）
        self.one_hand_finger_number = one_hand_finger_number
        # 弦数（小提琴固定 4 根）
        self.string_number = 4

        # ── 左手手指控制器（数字命名，StringFlow 特点） ──
        self.finger_controllers = {}
        for finger_number in range(1, one_hand_finger_number + 1):
            self.finger_controllers[finger_number] = f"{finger_number}_L"

        # ── 右手手指控制器 ──
        self.right_finger_controllers = {}
        for finger_number in range(1, one_hand_finger_number + 1):
            self.right_finger_controllers[finger_number] = f"{finger_number}_R"

        # ── 手掌/枢轴/拇指控制器 ──
        self.hand_controllers = {
            "right_hand_controller": "H_R",
            "right_hand_pivot_controller": "HP_R",
            "right_thumb_controller": "T_R",
            "left_hand_controller": "H_L",
            "left_hand_pivot_controller": "HP_L",
            "left_thumb_controller": "T_L",
        }

        # ── 状态记录器命名表（数据键 = 短名，存骨骼；不再生成物体） ──
        self.left_finger_recorders = []
        self.left_hand_position_recorders = []
        self.left_thumb_position_recorders = []
        # 左手：0/3 弦 × 1/9/12 品 × 全部手指 × 三状态
        for string_num in [0, 3]:
            for fret_num in [1, 9, 12]:
                for finger_num in range(1, one_hand_finger_number + 1):
                    for state in LeftHandPositionType:
                        self.left_finger_recorders.append(
                            f"p_s{string_num}_f{fret_num}_{finger_num}_L_{state.value}")
                for state in LeftHandPositionType:
                    for controller in ["H_L", "HP_L"]:
                        self.left_hand_position_recorders.append(
                            f"{controller}_s{string_num}_f{fret_num}_{state.value}")
                    for controller in ["T_L"]:
                        self.left_thumb_position_recorders.append(
                            f"{controller}_s{string_num}_f{fret_num}_{state.value}")

        # 右手：4 弦 × 三状态 × 全部手指
        self.right_finger_recorders = []
        self.right_hand_position_recorders = []
        self.right_thumb_position_recorders = []
        for string_num in range(0, self.string_number):
            for position in RightHandPositionType:
                for finger_num in range(1, one_hand_finger_number + 1):
                    self.right_finger_recorders.append(
                        f"p_s{string_num}_{finger_num}_R_{position.value}")
            for position in RightHandPositionType:
                for controller in ["H_R", "HP_R"]:
                    self.right_hand_position_recorders.append(
                        f"{controller}_{position.value}_s{string_num}")
                for controller in ["T_R"]:
                    self.right_thumb_position_recorders.append(
                        f"{controller}_{position.value}_s{string_num}")

        # ── 辅助控制器 ──
        self.other_controllers = {
            "string_touch_point_controller": "String_Touch_Point",  # 触弦点控制器
            "bow_controller": "Bow_Controller",
        }

        # ── 其他记录器（other_recorders 完整键列表：物理标记对象 + bow/stp 状态键） ──
        self.other_recorders = []
        for i in range(0, self.string_number):
            self.other_recorders.append(f"mid_s{i}")
            self.other_recorders.append(f"f9_s{i}")
            for position in RightHandPositionType:
                self.other_recorders.append(f"bow_position_s{i}_{position.value}")
                self.other_recorders.append(f"stp_{i}_{position.value}")
            for j in [0, 12]:
                self.other_recorders.append(f"position_s{i}_f{j}")
        self.other_recorders.append("middle_fret_board_position")

        # ── 物理位置标记对象（保留为世界对象；其余状态键存骨骼） ──
        self.physical_markers = []
        for i in range(0, self.string_number):
            self.physical_markers.append(f"position_s{i}_f0")
            self.physical_markers.append(f"position_s{i}_f12")
            self.physical_markers.append(f"mid_s{i}")
            self.physical_markers.append(f"f9_s{i}")
        self.physical_markers.append("middle_fret_board_position")

        # 辅助线（原版为空列表，保留字段）
        self.guide_lines = []

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
        """创建或更新物体（obj_type 为 ObjectType 枚举或 object_utils 字符串）。

        注意：不锁定任何对象的旋转（用户需在视口手动旋转左右手控件摆姿势）。
        """
        if isinstance(obj_type, ObjectType):
            obj_type = obj_type.value
        return object_utils.create_or_update_object(
            obj_name, obj_type, collection, rotation_mode, scale=scale)

    def move_object_to_collection(self, obj, collection):
        """将对象移动到指定集合"""
        object_utils.move_object_to_collection(obj, collection)

    # ── 控制器创建 ──────────────────────────────────────────

    def add_controllers(self) -> None:
        """添加所有控制器（controller_root + 左右手 + ext/pole + 弓/触弦点）"""
        print("\n添加控制器...")

        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        main_collection = self._get_addons_collection()
        if main_collection is None:
            print("[ERROR] 未找到 addons 目录，请先新建角色（初始化角色）。")
            return

        controllers_collection = self.get_or_create_collection(
            "Controllers", main_collection)
        left_col = self.get_or_create_collection(
            "Left_Hand_Controllers", controllers_collection)
        right_col = self.get_or_create_collection(
            "Right_Hand_Controllers", controllers_collection)
        other_col = self.get_or_create_collection(
            "Other_Controllers", controllers_collection)

        # controller_root（固定乐器根，替代原版硬编码 "violin" 父级）
        controller_root = self.create_or_update_object(
            self.obj_name("controller_root"), ObjectType.SPHERE_EMPTY,
            controllers_collection)

        # Bow_Controller 先建（右手手指要挂其下，必须保证先存在）
        self.create_or_update_object(
            self.obj_name(self.other_controllers["bow_controller"]),
            ObjectType.CUBE, other_col)

        # 手掌/枢轴/拇指（cube）
        for controller_name in self.hand_controllers.values():
            collection = left_col if controller_name.endswith("_L") else right_col
            self.create_or_update_object(
                self.obj_name(controller_name), ObjectType.CUBE, collection)

        # 手指控制器（cube；数字命名 1_L~N_L / 1_R~N_R）
        for finger_name in (list(self.finger_controllers.values())
                            + list(self.right_finger_controllers.values())):
            collection = left_col if finger_name.endswith("_L") else right_col
            self.create_or_update_object(
                self.obj_name(finger_name), ObjectType.CUBE, collection)

        # 手指 ext 辅助控件与 pole
        self.add_finger_ext_and_poles(left_col, right_col)

        # 其他控制器（Bow_Controller 已提前创建）
        for controller_name in self.other_controllers.values():
            if controller_name == self.other_controllers["bow_controller"]:
                continue
            self.create_or_update_object(
                self.obj_name(controller_name), ObjectType.CUBE, other_col)

        # ── 层级（原版 set_parent_for_object 语义） ──
        palm_L = self.obj("H_L")
        bow = self.obj("Bow_Controller")
        if palm_L is not None:
            for n in range(1, self.one_hand_finger_number + 1):
                self._parent_to(palm_L, self.obj(f"{n}_L"))
            self._parent_to(palm_L, self.obj("T_L"))
        if bow is not None:
            for n in range(1, self.one_hand_finger_number + 1):
                self._parent_to(bow, self.obj(f"{n}_R"))
            self._parent_to(bow, self.obj("T_R"))
            # 右手手掌 H_R → Bow_Controller（与手指同级同空间，右手整体为弓子级）
            self._parent_to(bow, self.obj("H_R"))
        # 左手手掌/枢轴、右手枢轴/弓/触弦点 → controller_root（原 violin 帧）
        for short in ["H_L", "HP_L", "HP_R",
                      "Bow_Controller", "String_Touch_Point"]:
            self._parent_to(controller_root, self.obj(short))

        print("  ✓ 控制器添加完成")

    def add_finger_ext_and_poles(self, left_col, right_col) -> None:
        """创建手指 ext 辅助控件与手指级 pole。

        - ext 与对应手指同级：左手挂 H_L 下；右手挂 Bow_Controller 下（与手指/手掌同级同空间）；
        - pole（空环）挂对应 ext 下，沿局部 Z 偏移 1.0（幂等：仅新挂载时设置位置）。
        """
        finger_specs = []
        for hand in ["L", "R"]:
            for finger_number in range(1, self.one_hand_finger_number + 1):
                finger_specs.append((f"{finger_number}_{hand}", hand))
            finger_specs.append((f"T_{hand}", hand))  # 拇指

        palm_L = self.obj("H_L")
        bow = self.obj("Bow_Controller")

        for finger_name, hand in finger_specs:
            collection = left_col if hand == "L" else right_col
            ext_name = f"ext_{finger_name}"
            ext_obj = self.create_or_update_object(
                self.obj_name(ext_name), ObjectType.CUBE, collection, scale=0.7)

            # ext 与手指同级：左手挂 H_L；右手挂 Bow_Controller（driver 在局部空间直算）
            if hand == "L":
                self._parent_to(palm_L, ext_obj)
            else:
                self._parent_to(bow, ext_obj)

            # pole（空环）挂 ext 下，沿局部 Z 偏移 1.0（仅首次挂载时设置，不重置用户调整）
            pole_name = f"{finger_name}_pole"
            pole_obj = self.create_or_update_object(
                self.obj_name(pole_name), ObjectType.CIRCLE_EMPTY, collection)
            if pole_obj is not None and pole_obj.parent != ext_obj:
                pole_obj.parent = ext_obj
                pole_obj.location = (0, 0, 1.0)
                print(f"  ✓ {pole_name} → {ext_name}")

    def add_ext_drivers(self) -> None:
        """左手 ext driver（2×手指，H_L 局部空间）+ 右手 ext driver（2×手指−手掌，Bow 局部空间）"""
        print("\n添加手指 ext 控制器驱动...")

        # 左手：手指为手掌子级，ext 在 H_L 局部空间 = 2 * 手指（driver）
        for finger_number in range(1, self.one_hand_finger_number + 1):
            self._add_ext_driver(f"{finger_number}_L")
        self._add_ext_driver("T_L")

        # 右手：手指/手掌同为 Bow 子级，ext 在 Bow 局部空间 = 2 * 手指 - 手掌（driver）
        for finger_number in range(1, self.one_hand_finger_number + 1):
            self._add_ext_driver_right(f"{finger_number}_R")
        self._add_ext_driver_right("T_R")

        print("  ✓ 手指 ext 控制器驱动设置完成")

    def _add_ext_driver(self, finger_name: str) -> None:
        """为单个左手手指的 ext 辅助控件添加 location 驱动（先清后建，幂等）。

        左手：手指为 H_L 子级，ext 与手指同级（也挂 H_L 下），
        在 H_L 局部空间里手掌即原点，表达式 ext = 2 * 手指（局部坐标）。
        """
        ext_full = self.obj_name(f"ext_{finger_name}")
        finger_full = self.obj_name(finger_name)

        if finger_full not in bpy.data.objects:
            print(f"  • 手指控制器 {finger_full} 不存在，跳过驱动")
            return
        if ext_full not in bpy.data.objects:
            print(f"  • ext 控件 {ext_full} 不存在，跳过驱动")
            return

        ext_obj = bpy.data.objects[ext_full]

        # 清除已有的 location 驱动（保证可重复运行）
        if ext_obj.animation_data and ext_obj.animation_data.drivers:
            for axis_index in range(3):
                fcurve = ext_obj.animation_data.drivers.find(
                    "location", index=axis_index)
                if fcurve:
                    ext_obj.animation_data.drivers.remove(fcurve)

        # 为 XYZ 三个轴分别添加驱动
        for axis_index, axis_char in enumerate(['X', 'Y', 'Z']):
            driver = ext_obj.driver_add("location", axis_index).driver
            driver.type = 'SCRIPTED'

            var_f = driver.variables.new()
            var_f.name = "finger"
            var_f.type = 'TRANSFORMS'
            target_f = var_f.targets[0]
            target_f.id = bpy.data.objects[finger_full]
            target_f.transform_type = f'LOC_{axis_char}'
            target_f.transform_space = 'LOCAL_SPACE'

            # 左手：手指为 H_L 子级，ext 在 H_L 局部空间里手掌即原点
            driver.expression = "2 * finger"

        print(f"  ✓ 已为 {ext_full} 添加驱动: 2 * {finger_full}（H_L 局部空间）")

    def _add_ext_driver_right(self, finger_name: str) -> None:
        """为单个右手手指的 ext 辅助控件添加 location 驱动（先清后建，幂等）。

        右手：手指与手掌 H_R 同为 Bow_Controller 子级，ext 与手指同级（也挂
        Bow_Controller 下），在 Bow 局部空间里 ext = 2 * 手指 - 手掌（局部坐标
        driver），确保 ext 位于"手掌 → 手指"的延长线上（与左手 2*finger 同构，
        仅多一个手掌变量；取代 v0.4 的两个 Copy Location 世界坐标约束）。
        """
        ext_full = self.obj_name(f"ext_{finger_name}")
        finger_full = self.obj_name(finger_name)
        palm_full = self.obj_name("H_R")

        if finger_full not in bpy.data.objects:
            print(f"  • 手指控制器 {finger_full} 不存在，跳过驱动")
            return
        if ext_full not in bpy.data.objects:
            print(f"  • ext 控件 {ext_full} 不存在，跳过驱动")
            return
        if palm_full not in bpy.data.objects:
            print(f"  • 手掌控制器 {palm_full} 不存在，跳过驱动")
            return

        ext_obj = bpy.data.objects[ext_full]

        # 清除已有的约束与 location 驱动（保证可重复运行）
        for c in list(ext_obj.constraints):
            ext_obj.constraints.remove(c)
        if ext_obj.animation_data and ext_obj.animation_data.drivers:
            for axis_index in range(3):
                fcurve = ext_obj.animation_data.drivers.find(
                    "location", index=axis_index)
                if fcurve:
                    ext_obj.animation_data.drivers.remove(fcurve)

        # 为 XYZ 三个轴分别添加驱动
        for axis_index, axis_char in enumerate(['X', 'Y', 'Z']):
            driver = ext_obj.driver_add("location", axis_index).driver
            driver.type = 'SCRIPTED'

            # 手指位置变量（Bow 局部空间）
            var_f = driver.variables.new()
            var_f.name = "finger"
            var_f.type = 'TRANSFORMS'
            target_f = var_f.targets[0]
            target_f.id = bpy.data.objects[finger_full]
            target_f.transform_type = f'LOC_{axis_char}'
            target_f.transform_space = 'LOCAL_SPACE'

            # 手掌位置变量（Bow 局部空间）
            var_p = driver.variables.new()
            var_p.name = "palm"
            var_p.type = 'TRANSFORMS'
            target_p = var_p.targets[0]
            target_p.id = bpy.data.objects[palm_full]
            target_p.transform_type = f'LOC_{axis_char}'
            target_p.transform_space = 'LOCAL_SPACE'

            # 右手：手指/手掌同为 Bow 子级，ext 在 Bow 局部空间 = 2*finger - palm
            driver.expression = "2 * finger - palm"

        print(
            f"  ✓ 已为 {ext_full} 添加驱动: 2 * {finger_full} - {palm_full}（Bow 局部空间）")

    def get_ext_controller_names(self) -> list:
        """生成所有 ext 辅助控件名称（与手指同级）"""
        names = []
        for hand in ["L", "R"]:
            for finger_number in range(1, self.one_hand_finger_number + 1):
                names.append(f"ext_{finger_number}_{hand}")
            names.append(f"ext_T_{hand}")
        return names

    def get_pole_controller_names(self) -> list:
        """生成所有手指 pole 名称（含拇指 T_L_pole / T_R_pole）"""
        names = []
        for hand in ["L", "R"]:
            for finger_number in range(1, self.one_hand_finger_number + 1):
                names.append(f"{finger_number}_{hand}_pole")
            names.append(f"T_{hand}_pole")
        return names

    # ── 物理位置标记 ────────────────────────────────────────

    def add_recorders(self) -> None:
        """只创建物理位置标记对象（弦端点/中点/平面参考点），不再生成状态记录器。

        所有指板物理标记挂到 controller_root 下（跟随控制器体系整体移动/缩放）；
        mid/f9 的 LOCAL_SPACE driver 与 position_s{i}_f0/f12 同处 controller_root 局部空间，计算一致。
        """
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        main_collection = self._get_addons_collection()
        if main_collection is None:
            print("[ERROR] 未找到 addons 目录，请先新建角色（初始化角色）。")
            return

        controller_root = self.obj("controller_root")
        if controller_root is None:
            print("[ERROR] 未找到 controller_root，请先 Setup 创建控制器后再添加位置标记。")
            return

        recorders_collection = self.get_or_create_collection(
            "Recorders", main_collection)
        other_collection = self.get_or_create_collection(
            "Other_Recorders", recorders_collection)

        # 弦端点 position_s{i}_f0 / f12（挂 controller_root）
        for i in range(0, self.string_number):
            for j in [0, 12]:
                obj = self.create_or_update_object(
                    self.obj_name(f"position_s{i}_f{j}"),
                    ObjectType.SPHERE_EMPTY, other_collection)
                self._parent_to(controller_root, obj)
        # 中点 / 9 品参考（带 driver，挂 controller_root）
        for i in range(0, self.string_number):
            mid_obj = self.create_or_update_object(
                self.obj_name(f"mid_s{i}"), ObjectType.SPHERE_EMPTY, other_collection)
            self._parent_to(controller_root, mid_obj)
            f9_obj = self.create_or_update_object(
                self.obj_name(f"f9_s{i}"), ObjectType.SPHERE_EMPTY, other_collection)
            self._parent_to(controller_root, f9_obj)
        # 三点定平面第三点（挂 controller_root）
        obj = self.create_or_update_object(
            self.obj_name("middle_fret_board_position"),
            ObjectType.SPHERE_EMPTY, other_collection)
        self._parent_to(controller_root, obj)

        # 为每根弦的中点/9 品位置记录器添加驱动（幂等：已存在跳过）
        for i in range(0, self.string_number):
            mid_name = self.obj_name(f"mid_s{i}")
            if mid_name in bpy.data.objects:
                recorder_obj = bpy.data.objects[mid_name]
                for axis_index in range(3):
                    self._add_driver_for_axis(
                        recorder_obj, 'location', axis_index, i)
            f9_name = self.obj_name(f"f9_s{i}")
            if f9_name in bpy.data.objects:
                recorder_obj = bpy.data.objects[f9_name]
                for axis_index in range(3):
                    self._add_driver_for_f9_axis(
                        recorder_obj, 'location', axis_index, i)

    def _add_driver_for_axis(self, obj, prop, axis_index, string_index) -> None:
        """mid_s{i} 中点 driver：(A + B) * 0.5（A=position_s{i}_f0, B=position_s{i}_f12）"""
        # 检查驱动是否已经存在
        if obj.animation_data and obj.animation_data.drivers:
            for fcurve in obj.animation_data.drivers:
                if fcurve.data_path == prop and fcurve.array_index == axis_index:
                    print(f"驱动已存在于 {obj.name} 的 {prop}[{axis_index}]，跳过添加")
                    return

        driver = obj.driver_add(prop, axis_index).driver
        driver.type = 'SCRIPTED'
        driver.expression = "(A + B) * 0.5"

        a_target = bpy.data.objects.get(
            self.obj_name(f"position_s{string_index}_f0"))
        if a_target:
            var_a = driver.variables.new()
            var_a.name = "A"
            var_a.type = 'TRANSFORMS'
            var_a.targets[0].id = a_target
            var_a.targets[0].transform_type = 'LOC_X' if axis_index == 0 else (
                'LOC_Y' if axis_index == 1 else 'LOC_Z')
            var_a.targets[0].transform_space = 'LOCAL_SPACE'

        b_target = bpy.data.objects.get(
            self.obj_name(f"position_s{string_index}_f12"))
        if b_target:
            var_b = driver.variables.new()
            var_b.name = "B"
            var_b.type = 'TRANSFORMS'
            var_b.targets[0].id = b_target
            var_b.targets[0].transform_type = 'LOC_X' if axis_index == 0 else (
                'LOC_Y' if axis_index == 1 else 'LOC_Z')
            var_b.targets[0].transform_space = 'LOCAL_SPACE'

    def _add_driver_for_f9_axis(self, obj, prop, axis_index, string_index) -> None:
        """f9_s{i} 9 品位置 driver：A + 0.4053964424986395 * (B - A)"""
        # 检查驱动是否已经存在
        if obj.animation_data and obj.animation_data.drivers:
            for fcurve in obj.animation_data.drivers:
                if fcurve.data_path == prop and fcurve.array_index == axis_index:
                    print(f"驱动已存在于 {obj.name} 的 {prop}[{axis_index}]，跳过添加")
                    return

        driver = obj.driver_add(prop, axis_index).driver
        driver.type = 'SCRIPTED'
        # A 是第 0 品位置，B 是弦末端位置（第 12 品之后）
        driver.expression = "A + 0.4053964424986395 * (B-A)"

        a_target = bpy.data.objects.get(
            self.obj_name(f"position_s{string_index}_f0"))
        if a_target:
            var_a = driver.variables.new()
            var_a.name = "A"
            var_a.type = 'TRANSFORMS'
            var_a.targets[0].id = a_target
            var_a.targets[0].transform_type = 'LOC_X' if axis_index == 0 else (
                'LOC_Y' if axis_index == 1 else 'LOC_Z')
            var_a.targets[0].transform_space = 'LOCAL_SPACE'

        b_target = bpy.data.objects.get(
            self.obj_name(f"position_s{string_index}_f12"))
        if b_target:
            var_b = driver.variables.new()
            var_b.name = "B"
            var_b.type = 'TRANSFORMS'
            var_b.targets[0].id = b_target
            var_b.targets[0].transform_type = 'LOC_X' if axis_index == 0 else (
                'LOC_Y' if axis_index == 1 else 'LOC_Z')
            var_b.targets[0].transform_space = 'LOCAL_SPACE'

    # ── 检查 ────────────────────────────────────────────────

    def check_all_objects(self) -> CheckResult:
        """检查当前演奏者命名空间内的对象状态（存在/缺失），只报告不移动对象。"""
        print("=" * 60)
        print("StringFlow 对象状态检查")
        print("=" * 60)

        controllers = (list(self.finger_controllers.values())
                       + list(self.right_finger_controllers.values())
                       + list(self.hand_controllers.values())
                       + self.get_ext_controller_names()
                       + self.get_pole_controller_names()
                       + list(self.other_controllers.values())
                       + ["controller_root"])

        print("\n【控制器状态】")
        existing_ctrl = 0
        missing_ctrl = 0
        for short in controllers:
            full = self.obj_name(short)
            if full in bpy.data.objects:
                existing_ctrl += 1
                print(f"  ✓ {full}")
            else:
                missing_ctrl += 1
                print(f"  ✗ {full} (缺失)")

        print("\n【物理位置标记状态】")
        existing_marker = 0
        missing_marker = 0
        for short in self.physical_markers:
            full = self.obj_name(short)
            if full in bpy.data.objects:
                existing_marker += 1
                print(f"  ✓ {full}")
            else:
                missing_marker += 1
                print(f"  ✗ {full} (缺失)")

        print("\n【弦物体状态】（由琴弦工具创建）")
        existing_string = 0
        missing_string = 0
        for i in range(self.string_number):
            full = self.obj_name(f"string{i}")
            if full in bpy.data.objects:
                existing_string += 1
                print(f"  ✓ {full}")
            else:
                missing_string += 1
                print(f"  ✗ {full} (缺失)")

        total = len(controllers) + len(self.physical_markers) + self.string_number
        existing = existing_ctrl + existing_marker + existing_string
        missing = missing_ctrl + missing_marker + missing_string

        print(f"\n【统计信息】")
        print(f"控制器：{existing_ctrl}/{len(controllers)}；"
              f"物理标记：{existing_marker}/{len(self.physical_markers)}；"
              f"弦物体：{existing_string}/{self.string_number}")
        print(f"对象总计：{existing}/{total}，缺失：{missing}"
              + (f"，完成度：{existing/total*100:.1f}%" if total > 0 else ""))

        return {
            'controllers': {'existing': existing_ctrl, 'missing': missing_ctrl,
                            'total': len(controllers)},
            'markers': {'existing': existing_marker, 'missing': missing_marker,
                        'total': len(self.physical_markers)},
            'strings': {'existing': existing_string, 'missing': missing_string,
                        'total': self.string_number},
            'overall': {'existing': existing, 'missing': missing, 'total': total},
        }

    # ── 一次性设置 ──────────────────────────────────────────

    def setup_all_objects(self) -> bool:
        """一次性设置所有控制器和物理位置标记（幂等）。

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

        # 添加控制器、驱动与物理位置标记
        self.add_controllers()
        self.add_ext_drivers()
        self.add_recorders()

        # 演奏者根 <缩写>_<名称>（挂接骨骼 / controller_root；乐器不挂根）
        self._organize_performer_root()
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

        小提琴固定不动：乐器由用户手动绑定到 controller_root；不挂根。
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
