# bellows_pulse/config.py
"""BellowsPulse 乐器模块 —— 配置（控件命名表 + 集合/物体创建 + setup）

手风琴和钢琴最大的结构差别不是手，而是**键区会动**：左右两个键区各自是一个刚体，
所以除了双手，还有 `pivot_left` / `pivot_right` 两根枢轴，以及两个「键区骨骼跟随器」
`left_bone` / `right_bone`——后者用 Copy Transforms 跟随骨架上的键区骨骼（目标留空，
由使用者在自己的骨架上接），双手再挂在这两个跟随器下面：风箱开合、键区整体移动时，
手和键区处在同一个坐标系里。键区的位置记录器也挂在两个跟随器下，记**局部坐标**；
键区动，记录器就跟着动。

风箱形变由引擎侧（Blender 约束 / Unreal 特制 IK）驱动，本模块只提供 pole target 控件
`accordion_pivot`，**不建任何风箱约束**。

层级（固定乐器，没有 controller_root_offset）：

    controller_root                  （Copy Location + Copy Rotation，目标留空）
    ├── HP_L / HP_R                  手部 IK 枢轴
    ├── F_L / FP_L / F_R / FP_R      双脚与脚部极向量（摆姿势用）
    ├── pivot_left / pivot_right     键区枢轴（风箱 IK 的两端）
    └── accordion_pivot              风箱 IK 的 pole target

    left_bone / right_bone           （Copy Transforms 跟随键区骨骼，目标留空）
    └── H_L / H_R                    手掌
        ├── 五指 + ext（ext 的位置由 driver 取 2 × 手指）
        │   └── *_pole               IK 极向量
        └── hand_back                （背带曲线的 Hook 目标，只在左手）

所有对象名都接演奏者后缀（`performer_utils.resolve`），集合名同理由
`get_or_create_collection` 统一加后缀，保证一个 Blender 文件里多个演奏者互不干扰。
"""

import bpy  # type: ignore

from ..common import performer_utils
from ..common import object_utils
from ..common import ext_utils

from .enums import (
    FINGER_BASES,
    HANDS,
    RIGHT_LAYOUT_BUTTONS,
    RIGHT_LAYOUT_KEYBOARD,
)


# ── 生成时就挂上的控件约束 ────────────────────────────────────
#
# 约束的**目标留空**：目标骨骼取决于使用者自己的骨架，模块无法预知；
# 已经存在的同类型约束一律不删、不改参数，避免重复 Setup 把用户接好的目标冲掉。
CONTROL_CONSTRAINTS = (
    ("controller_root", "COPY_LOCATION"),
    ("controller_root", "COPY_ROTATION"),
    ("left_bone", "COPY_TRANSFORMS"),
    ("right_bone", "COPY_TRANSFORMS"),
)

#: 约束名（固定英文名，只影响可读性；识别与去重都按类型判断）
CONTROL_CONSTRAINT_NAMES = {
    "COPY_LOCATION": "Copy Location",
    "COPY_ROTATION": "Copy Rotation",
    "COPY_TRANSFORMS": "Copy Transforms",
}

#: 键区骨骼跟随器的显示尺寸（PLAIN_AXES 的半径，大一点好在视口里点中）
BONE_FOLLOWER_DISPLAY_SIZE = 100.0

#: hand_back 的显示尺寸
HAND_BACK_DISPLAY_SIZE = 1.0


# ── 键区位置记录器 ────────────────────────────────────────
#
# 元组含义：(短名, 父级短名, 新建时的本地位置)。
# 本地位置只是「让几个点别叠在一起、好在视口里分别选中」的默认小偏移，
# 用户随后会挪到真实键位；已存在的记录器**不会被重置**。
#
# 父级是左右两个键区骨骼跟随器：键区整体移动时，记录器跟着键区走，
# 记下来的**局部坐标**不用跟着改。
#
# 点数出处（大纲 §5）：
#   右手键盘（`kbd_*`，钢琴式键区）4 点 = 最低白键近端 / 远端、最高白键、黑键高度；
#   右手按钮（`rb*`，巴扬键区）6 点 = 第 1/2/3 排各自的最低音 / 最高音；
#   左手按钮（`lb*`）3 点 = 第 1 排最低音 / 最高音、最后一排最高音。

LEFT_RECORDERS = (
    ("lb1_low", "left_bone", (0.0, 0.0, 0.0)),
    ("lb1_high", "left_bone", (0.5, 0.0, 0.0)),
    ("lb_last_high", "left_bone", (0.5, -0.2, 0.0)),
)

KEYBOARD_RECORDERS = (
    ("kbd_lowest_near", "right_bone", (0.0, 0.0, 0.0)),
    ("kbd_lowest_far", "right_bone", (0.0, -0.12, 0.0)),
    ("kbd_highest", "right_bone", (0.5, 0.0, 0.0)),
    ("kbd_black_height", "right_bone", (0.0, 0.0, 0.02)),
)

RIGHT_BUTTON_RECORDERS = (
    ("rb1_low", "right_bone", (0.0, 0.0, 0.0)),
    ("rb1_high", "right_bone", (0.5, 0.0, 0.0)),
    ("rb2_low", "right_bone", (0.0, -0.06, 0.0)),
    ("rb2_high", "right_bone", (0.5, -0.06, 0.0)),
    ("rb3_low", "right_bone", (0.0, -0.12, 0.0)),
    ("rb3_high", "right_bone", (0.5, -0.12, 0.0)),
)


def right_recorders_for_layout(layout: str):
    """右手类型 → 该建的那一组记录器（keyboard / buttons）。"""
    if layout == RIGHT_LAYOUT_BUTTONS:
        return RIGHT_BUTTON_RECORDERS
    return KEYBOARD_RECORDERS


def recorders_for_layout(layout: str):
    """某个右手类型下**应该存在**的全部记录器（左手 3 个 + 右侧对应的一组）。"""
    return tuple(LEFT_RECORDERS) + tuple(right_recorders_for_layout(layout))


class BellowsConfig:
    """手风琴配置：命名表 + 控件/记录器创建 + setup（多演奏者命名空间）"""

    def __init__(self, performer_suffix: str = "",
                 target_skeleton=None, target_instrument=None,
                 performer_name=None):
        self.suffix: str = performer_suffix
        self.target_skeleton = target_skeleton
        self.target_instrument = target_instrument
        self.performer_name: str = performer_name or (
            performer_suffix if performer_suffix else "Performer")
        self.instruments_name: str = "bellows_pulse"

        # ── 手部：手掌 + 手部 IK 枢轴（各 2 个）──
        self.hand_controllers = {
            "left_hand_controller": "H_L",
            "left_hand_ik_pivot": "HP_L",
            "right_hand_controller": "H_R",
            "right_hand_ik_pivot": "HP_R",
        }

        # ── 双脚：脚控件 + 脚部极向量（各 2 个）──
        self.foot_controllers = {
            "left_foot_controller": "F_L",
            "right_foot_controller": "F_R",
        }
        self.foot_pole_controllers = {
            "left_foot_pole": "FP_L",
            "right_foot_pole": "FP_R",
        }

        # ── 键区枢轴 + 风箱极向 ──
        self.key_zone_controllers = {
            "left_pivot": "pivot_left",
            "right_pivot": "pivot_right",
            "bellows_pivot": "accordion_pivot",
        }

        # ── 键区骨骼跟随器（世界对象，Copy Transforms 指向键区骨骼）──
        self.bone_follower_controllers = {
            "left_bone": "left_bone",
            "right_bone": "right_bone",
        }

        # ── 左掌辅助（背带曲线的 Hook 目标）──
        self.hand_helper_controllers = {
            "hand_back": "hand_back",
        }

        # 用于记录添加控件前的对象名称（setup 结束时打印"未使用的控件"）
        self.pre_obj_names = []

    # ── 后缀化命名 ──────────────────────────────────────────

    def obj_name(self, short: str) -> str:
        """短名 → 完整对象名（带演奏者后缀）"""
        return performer_utils.resolve(short, self.suffix)

    def obj(self, short: str):
        """按短名取对象"""
        return bpy.data.objects.get(self.obj_name(short))

    def finger_shorts(self, hand: str) -> list[str]:
        """某只手的手指短名：'L' → ['T_L', 'I_L', 'M_L', 'R_L', 'P_L']"""
        return [f"{base}_{hand}" for base in FINGER_BASES]

    @staticmethod
    def ext_short(finger_short: str) -> str:
        """手指短名 → ext 控件短名：'T_L' → 'ext_T_L'"""
        return f"ext_{finger_short}"

    @staticmethod
    def pole_short(finger_short: str) -> str:
        """手指短名 → 极向量短名（与 Unreal 端一致）：'T_L' → 'T_L_pole'"""
        return f"{finger_short}_pole"

    def get_pole_controller_shorts(self) -> list:
        """全部手指极向量短名（挂在各自 ext 下）"""
        shorts = []
        for hand in HANDS:
            for finger_short in self.finger_shorts(hand):
                shorts.append(self.pole_short(finger_short))
        return shorts

    def all_controller_shorts(self) -> list:
        """本模块应该存在的全部控制器短名（检查状态用）"""
        shorts = ["controller_root"]
        shorts.extend(self.hand_controllers.values())
        shorts.extend(self.foot_controllers.values())
        shorts.extend(self.foot_pole_controllers.values())
        shorts.extend(self.key_zone_controllers.values())
        shorts.extend(self.bone_follower_controllers.values())
        shorts.extend(self.hand_helper_controllers.values())
        for hand in HANDS:
            for finger_short in self.finger_shorts(hand):
                shorts.append(finger_short)
                shorts.append(self.ext_short(finger_short))
                shorts.append(self.pole_short(finger_short))
        return shorts

    # ── 集合/物体创建（改调 common） ────────────────────────

    def get_or_create_collection(self, name, parent_collection=None):
        """获取或创建集合（自动按演奏者后缀拼接完整集合名）"""
        return object_utils.get_or_create_collection(
            self.obj_name(name), parent_collection)

    def create_or_update_object(self, obj_name, obj_type="sphere",
                                collection=None, rotation_mode='QUATERNION',
                                scale=1.0):
        """创建或更新物体（幂等：已存在只归位，不重置 transform）"""
        if hasattr(self, 'pre_obj_names') and obj_name in self.pre_obj_names:
            self.pre_obj_names.remove(obj_name)
        return object_utils.create_or_update_object(
            obj_name, obj_type, collection, rotation_mode, scale=scale)

    def move_object_to_collection(self, obj, collection):
        """将对象移动到指定集合"""
        object_utils.move_object_to_collection(obj, collection)

    # ── 控制器创建 ──────────────────────────────────────────

    def add_controllers(self) -> None:
        """添加所有控制器（含 controller_root、骨骼跟随器、ext、极向量、双脚）"""
        print("\n添加控制器...")

        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        main_collection = self._get_addons_collection()
        if main_collection is None:
            print("[ERROR] 未找到 addons 目录，请先新建角色（初始化角色）。")
            return

        controllers_collection = self.get_or_create_collection(
            "Controllers", main_collection)
        controller_root = self.create_or_update_object(
            self.obj_name("controller_root"), "sphere", controllers_collection)

        hand_collection = self.get_or_create_collection(
            "Hand_Controllers", controllers_collection)
        left_hand_collection = self.get_or_create_collection(
            "Left_Hand", hand_collection)
        right_hand_collection = self.get_or_create_collection(
            "Right_Hand", hand_collection)
        foot_collection = self.get_or_create_collection(
            "Foot_Controllers", controllers_collection)
        key_zone_collection = self.get_or_create_collection(
            "Key_Zone_Controllers", controllers_collection)

        # 手掌与手部 IK 枢轴
        self.create_or_update_object(
            self.obj_name("H_L"), "sphere", left_hand_collection)
        self.create_or_update_object(
            self.obj_name("HP_L"), "sphere", left_hand_collection)
        self.create_or_update_object(
            self.obj_name("H_R"), "sphere", right_hand_collection)
        self.create_or_update_object(
            self.obj_name("HP_R"), "sphere", right_hand_collection)

        # 键区骨骼跟随器：Copy Transforms 指向键区骨骼（目标留空），双手挂在它下面
        left_bone_obj = self.create_or_update_object(
            self.obj_name("left_bone"), "axes", left_hand_collection,
            scale=BONE_FOLLOWER_DISPLAY_SIZE)
        right_bone_obj = self.create_or_update_object(
            self.obj_name("right_bone"), "axes", right_hand_collection,
            scale=BONE_FOLLOWER_DISPLAY_SIZE)

        # 五指 → 手掌；ext → 手掌；极向量 → ext（局部 (0,0,1)）
        for hand, collection in (("L", left_hand_collection),
                                 ("R", right_hand_collection)):
            palm_obj = self.obj(f"H_{hand}")
            if palm_obj is None:
                print(f"  • 手掌控制器 {self.obj_name(f'H_{hand}')} 不存在，跳过手指与 ext")
                continue
            for finger_short in self.finger_shorts(hand):
                finger_obj = self.create_or_update_object(
                    self.obj_name(finger_short), "sphere", collection)
                if finger_obj is not None and finger_obj.parent != palm_obj:
                    finger_obj.parent = palm_obj

                ext_obj = self.create_or_update_object(
                    self.obj_name(self.ext_short(finger_short)), "sphere",
                    collection, scale=0.7)
                if ext_obj is not None and ext_obj.parent != palm_obj:
                    ext_obj.parent = palm_obj

                pole_obj = self.create_or_update_object(
                    self.obj_name(self.pole_short(finger_short)), "circle",
                    collection)
                if pole_obj is None:
                    continue
                if pole_obj.parent != ext_obj:
                    pole_obj.parent = ext_obj
                    pole_obj.location = (0.0, 0.0, 1.0)

        # 左掌辅助：背带曲线的 Hook 目标（挂左掌下，跟手走）
        palm_left = self.obj("H_L")
        hand_back_obj = self.create_or_update_object(
            self.obj_name("hand_back"), "axes", left_hand_collection,
            scale=HAND_BACK_DISPLAY_SIZE)
        if hand_back_obj is not None and palm_left is not None \
                and hand_back_obj.parent != palm_left:
            hand_back_obj.parent = palm_left

        # 双脚与脚部极向量（与屁股下面的 IK 配套，只摆姿势、不参与数据）
        for short in self.foot_controllers.values():
            self.create_or_update_object(
                self.obj_name(short), "sphere", foot_collection)
        for short in self.foot_pole_controllers.values():
            self.create_or_update_object(
                self.obj_name(short), "circle", foot_collection)

        # 键区枢轴（球形空）与风箱极向（空环，便于辨认）
        for short in ("pivot_left", "pivot_right"):
            self.create_or_update_object(
                self.obj_name(short), "sphere", key_zone_collection)
        self.create_or_update_object(
            self.obj_name("accordion_pivot"), "circle", key_zone_collection)

        # 手掌 / 手部枢轴 / 双脚 / 键区枢轴 / 风箱极向 → controller_root
        for short in ("HP_L", "HP_R",
                      "F_L", "FP_L", "F_R", "FP_R",
                      "pivot_left", "pivot_right", "accordion_pivot"):
            self._set_parent(short, controller_root)

        # 双手挂在键区骨骼跟随器下（风箱开合、键区移动时手跟着走）
        self._set_parent("H_L", left_bone_obj)
        self._set_parent("H_R", right_bone_obj)

        # 跟骨骼走的控件补上约束（目标留空，由使用者接自己的骨骼）
        self._setup_control_constraints()

        print("  ✓ 控制器添加完成")

    def _set_parent(self, child_short, parent_obj) -> None:
        """把子控制器挂到指定父对象下（Blender 保持本地 transform，不搬世界位置）"""
        full_child = self.obj_name(child_short)
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

    def _setup_control_constraints(self) -> None:
        """给「要跟骨骼走」的控件补上约束（幂等：只补缺失的类型）。

        目标骨骼取决于使用者自己的骨架命名，模块无法预知，所以**目标一律留空**；
        已经存在的同类型约束不删除、不改参数——重复 Setup 不能把用户接好的目标
        冲掉（旧版本场景里已经接好目标的控件，再跑 Setup 也原样保留）。
        新建约束统一用 WORLD / WORLD 空间：目标设成骨骼后，在世界空间里直接对齐。
        """
        print("\n=== 设置控件约束 ===")
        for short, constraint_type in CONTROL_CONSTRAINTS:
            control_obj = self.obj(short)
            full_name = self.obj_name(short)
            if control_obj is None:
                print(f"  • 控件 {full_name} 不存在，跳过 {constraint_type}")
                continue
            if any(constraint.type == constraint_type
                   for constraint in control_obj.constraints):
                print(f"  ✓ {full_name} 已有 {constraint_type}")
                continue

            constraint = control_obj.constraints.new(constraint_type)
            constraint.name = CONTROL_CONSTRAINT_NAMES.get(
                constraint_type, constraint_type)
            if hasattr(constraint, "owner_space"):
                constraint.owner_space = 'WORLD'
                constraint.target_space = 'WORLD'
            if hasattr(constraint, "mix_mode"):
                constraint.mix_mode = 'REPLACE'
            print(f"  ✓ {full_name} 添加 {constraint_type}（目标留空）")

        print("=== 控件约束设置完成 ===\n")

    # ── ext 驱动 ────────────────────────────────────────────

    def add_ext_drivers(self) -> None:
        """为每个手指的 ext 辅助控件添加位置驱动 +「+X 轴指向手掌」约束（幂等）

        手指与 ext 都挂在同侧手掌下（手掌就是手指的父级）→ 位置驱动 `2 × 手指`。
        统一走 common.ext_utils，不自己写 driver。
        """
        print("\n添加手指 ext 控制器驱动...")
        for hand in HANDS:
            for base in FINGER_BASES:
                ext_utils.add_ext_driver(self, hand, base, hand_is_parent=True)
        print("  ✓ 手指 ext 控制器驱动设置完成")

    # ── 键区记录器创建（按设置） ─────────────────────────────

    def add_recorders(self, settings: dict) -> None:
        """按已保存的设置创建键区记录器，并删掉与当前设置不符的那一组。

        - 右手键盘 → 左 3 + 键盘 4；右手按钮 → 左 3 + 右按钮 6；
        - 另一组（`kbd_*` 或 `rb*`）如果存在就删掉：它已经和设置对不上，
          留着只会让人分不清哪些是有用的点；
        - 已存在的记录器**保持原位**（重复 Setup 不会把摆好的点归零）；
        - 只删名字精确匹配、带当前演奏者后缀的空物体，别的一概不碰。
        """
        print("\n添加键区位置记录器...")

        main_collection = self._get_addons_collection()
        if main_collection is None:
            print("[ERROR] 未找到 addons 目录，请先新建角色（初始化角色）。")
            return

        recorders_collection = self.get_or_create_collection(
            "Recorders", main_collection)
        positions_collection = self.get_or_create_collection(
            "Key_Zone_Positions", recorders_collection)

        layout = (settings.get("right") or {}).get("layout", RIGHT_LAYOUT_KEYBOARD)
        if layout == RIGHT_LAYOUT_BUTTONS:
            active_entries = recorders_for_layout(RIGHT_LAYOUT_BUTTONS)
            stale_entries = right_recorders_for_layout(RIGHT_LAYOUT_KEYBOARD)
        else:
            active_entries = recorders_for_layout(RIGHT_LAYOUT_KEYBOARD)
            stale_entries = right_recorders_for_layout(RIGHT_LAYOUT_BUTTONS)

        removed_count = 0
        for short, _parent_short, _offset in stale_entries:
            stale_obj = bpy.data.objects.get(self.obj_name(short))
            if stale_obj is None:
                continue
            full_name = stale_obj.name
            bpy.data.objects.remove(stale_obj, do_unlink=True)
            if full_name in self.pre_obj_names:
                self.pre_obj_names.remove(full_name)
            removed_count += 1
            print(f"  ✓ 已删除与当前设置不符的记录器：{full_name}")

        created_count = 0
        for short, parent_short, offset in active_entries:
            full_name = self.obj_name(short)
            already_exists = full_name in bpy.data.objects
            recorder_obj = self.create_or_update_object(
                full_name, "sphere", positions_collection)
            if recorder_obj is None:
                continue
            parent_obj = self.obj(parent_short)
            if parent_obj is None:
                print(f"  • 骨骼跟随器 {self.obj_name(parent_short)} 不存在，"
                      f"{full_name} 暂不挂父级")
            elif recorder_obj.parent != parent_obj:
                recorder_obj.parent = parent_obj
            if not already_exists:
                recorder_obj.location = offset
                created_count += 1

        print(f"  ✓ 记录器就绪（新建 {created_count} 个，删除 {removed_count} 个，"
              f"共 {len(active_entries)} 个）")

    # ── 状态检查 ────────────────────────────────────────────

    def check_all_objects(self, settings: dict | None = None) -> dict:
        """检查控制器与记录器的创建状态（仅当前演奏者命名空间）"""
        print("=" * 60)
        print("BellowsPulse 对象状态检查")
        print("=" * 60)

        controller_shorts = self.all_controller_shorts()
        existing_controllers = [short for short in controller_shorts
                                if self.obj(short) is not None]
        missing_controllers = [short for short in controller_shorts
                               if self.obj(short) is None]

        print(f"\n【控制器状态】共 {len(controller_shorts)} 个")
        for short in controller_shorts:
            mark = "✓" if self.obj(short) is not None else "✗"
            print(f"  {mark} {self.obj_name(short)}")

        recorder_shorts = []
        if settings is not None:
            layout = (settings.get("right") or {}).get(
                "layout", RIGHT_LAYOUT_KEYBOARD)
            recorder_shorts = list(recorders_for_layout(layout))
        existing_recorders = [short for short in recorder_shorts
                              if self.obj(short) is not None]
        missing_recorders = [short for short in recorder_shorts
                             if self.obj(short) is None]

        if settings is not None:
            print(f"\n【键区记录器状态】共 {len(recorder_shorts)} 个")
            for short in recorder_shorts:
                mark = "✓" if self.obj(short) is not None else "✗"
                print(f"  {mark} {self.obj_name(short)}")
        else:
            print("\n【键区记录器状态】骨骼上还没有保存乐器属性，未检查记录器")

        total_expected = len(controller_shorts) + len(recorder_shorts)
        total_existing = len(existing_controllers) + len(existing_recorders)
        print("\n【统计信息】")
        print(f"控制器：{len(existing_controllers)}/{len(controller_shorts)}")
        if settings is not None:
            print(f"记录器：{len(existing_recorders)}/{len(recorder_shorts)}")
        if total_expected > 0:
            print(f"完成度：{total_existing / total_expected * 100:.1f}%")
        else:
            print("完成度：0%")

        return {
            "controllers": {
                "existing": len(existing_controllers),
                "missing": len(missing_controllers),
                "total": len(controller_shorts),
            },
            "recorders": {
                "existing": len(existing_recorders),
                "missing": len(missing_recorders),
                "total": len(recorder_shorts),
            },
            "overall": {
                "existing": total_existing,
                "missing": len(missing_controllers) + len(missing_recorders),
                "total": total_expected,
            },
        }

    # ── 一次性设置 ──────────────────────────────────────────

    def setup_all_objects(self) -> bool:
        """创建/刷新所有控件与记录器（幂等）。返回是否成功。

        - 有后缀时要求角色已初始化（addons_<后缀> 存在），否则提示先新建角色；
        - 记录器按**骨骼里已保存的设置**创建；还没保存过设置就只建控件并提示
          （不然会凭空造出一套用户没确认过的点）；
        - 不重置已保存的状态、不重置记录器位置。
        """
        if self.suffix and performer_utils.find_addons_collection(self.suffix) is None:
            print("[ERROR] 未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）后重试。")
            return False

        self._organize_body()
        self._organize_instrument()

        # 记录添加控件前的对象名（仅本演奏者），结束时打印"未使用的控件"
        self.pre_obj_names = []
        addons_collection = self._get_addons_collection()
        if addons_collection is None:
            print("[ERROR] 未找到角色 addons 目录，请先新建角色（初始化角色）。")
            return False
        collections_to_check = [addons_collection]
        collections_to_check.extend(addons_collection.children_recursive)
        for collection in collections_to_check:
            for obj in collection.objects:
                self.pre_obj_names.append(obj.name)

        self.add_controllers()
        self.add_ext_drivers()

        from . import state as _state
        skeleton = self._target_skeleton()
        if _state.has_settings(skeleton):
            self.add_recorders(_state.load_settings(skeleton))
        else:
            print("\n  • 骨骼上还没有保存乐器属性，本次只建控件；"
                  "在面板里保存属性后再点一次「设置所有对象」即可建键区记录器")

        self._organize_performer_root()

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

    def _target_skeleton(self):
        """当前配置/演奏者对应的骨骼（配置没给时退回演奏者登记的骨骼）"""
        if self.target_skeleton is not None:
            return self.target_skeleton
        performer = self._get_performer_collection()
        if performer is None:
            return None
        return performer.target_skeleton

    def _organize_body(self):
        """把目标骨骼和它的 Mesh 归位到 Body_<后缀>（仅后缀模式）"""
        if not self.suffix:
            return
        performer = self._get_performer_collection()
        if performer is None:
            return
        body_collection = performer_utils.get_or_create_collection(
            self.suffix, "Body", parent=performer.collection)
        skeleton = self._target_skeleton()
        if skeleton is None:
            print("  • 未指定目标骨骼，跳过 Body 归位")
            return
        self.move_object_to_collection(skeleton, body_collection)
        for child in list(skeleton.children):
            if child.type == 'MESH':
                self.move_object_to_collection(child, body_collection)
                if child.parent != skeleton:
                    child.parent = skeleton
        print(f"  ✓ 骨骼 {skeleton.name} 及其 Mesh 已归位到 {body_collection.name}")

    def _organize_instrument(self):
        """把「目标乐器」（右键区 mesh）归位到 Instruments_<后缀>（仅后缀模式）

        左键区 mesh 由 bellows_pulse 自己的属性登记，归位与绑定留到键区 mesh 那一轮。
        """
        if not self.suffix:
            return
        instrument = self.target_instrument
        if instrument is None:
            return
        performer = self._get_performer_collection()
        if performer is None:
            return
        instrument_collection = performer_utils.get_or_create_collection(
            self.suffix, "Instruments", parent=performer.collection)
        self.move_object_to_collection(instrument, instrument_collection)
        print(f"  ✓ 乐器 {instrument.name} 已归位到 {instrument_collection.name}")

    def _organize_performer_root(self):
        """创建演奏者根空物体 BP_<名称>，作为骨骼 / controller_root 的父级（仅后缀模式）

        固定乐器：键区 mesh 由用户手动挂到键区骨骼下（骨骼父级），不挂根。
        """
        if not self.suffix:
            return
        performer = self._get_performer_collection()
        if performer is None:
            return
        root_obj = performer_utils.get_or_create_performer_root(
            performer, performer.collection)

        skeleton = self._target_skeleton()
        self._parent_to(root_obj, skeleton)
        self._parent_to(root_obj, self.obj("controller_root"))
        print(f"  ✓ 演奏者根 {root_obj.name} 就绪（骨骼/controller_root 已挂到其下；"
              f"键区 mesh 请手动骨骼父级到键区骨骼）")

    def _parent_to(self, parent_obj, child_obj) -> None:
        object_utils.parent_to(parent_obj, child_obj)
