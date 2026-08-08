# fret_dance/config.py
"""FretDance 乐器模块 —— 控制器配置（迁移自 fret_dance_blender/controller_config.py）"""
from ..common import performer_utils as _pu
from .enums import Instruments, BasePositions, LeftHandStates, RightHandStates


class ControllerConfig:
    """控制器配置管理类 - 负责初始化所有控制器和状态配置映射"""

    def __init__(self, instruments: Instruments, use_vibrato_bar: bool = False,
                 performer_suffix: str = "", target_skeleton=None,
                 target_instrument=None, performer_name=None):
        self.instruments: Instruments = instruments
        self.use_vibrato_bar: bool = use_vibrato_bar
        # 演奏者后缀：短名 -> 完整对象名用；空 = 兼容旧场景（无后缀）
        self.suffix: str = performer_suffix
        # 目标骨骼（状态数据/演奏者设置载体）与目标乐器（弦动画作用域）
        self.target_skeleton = target_skeleton
        self.target_instrument = target_instrument
        self.performer_name: str = performer_name or (
            performer_suffix if performer_suffix else "Performer")
        # 乐器项目标识（跨乐器共存时用于区分，如 fret_dance / string_flow）
        self.instruments_name: str = "fret_dance"

        # 控制左手手掌位置和手臂ik的控制器,因为左手大拇指不参与演奏，所以也被归到这一类里
        self.left_hand_controllers = {
            "left_hand_controller": "H_L",
            "left_hand_ik_pivot_controller": "HP_L",
            "left_thumb_controller": "T_L",
        }

        # 控制右手手掌位置和手臂ik的控制器，因为右手大拇指要参与演奏，所以不被归到这一类里
        self.right_hand_controllers = {
            "right_hand_controller": "H_R",
            "right_hand_ik_pivot_controller": "HP_R",
        }

        # 控制左手手指位置
        self.left_finger_controllers = {
            "left_index_controller": "I_L",
            "left_middle_controller": "M_L",
            "left_ring_controller": "R_L",
            "left_little_controller": "P_L",
        }

        # 定义无效的组合
        self.invalid_combinations = {
            BasePositions.P0: [LeftHandStates.INNER],
            BasePositions.P2: [LeftHandStates.INNER],
            BasePositions.P1: [LeftHandStates.OUTER],
            BasePositions.P3: [LeftHandStates.OUTER]
        }

        # 控制右手手指位置
        # 电吉他右手同样配置五指（中指/无名指/小指挂手掌、食指挂大拇指）
        self.right_finger_controllers = {
            "right_thumb_controller": "T_R",
            "right_index_controller": "I_R",
            "right_middle_controller": "M_R",
            "right_ring_controller": "R_R",
            "right_little_controller": "P_R",
        }

        # 用于记录指板位置的五个基本点（保留为物理物体，用户可在场景中移动）
        self.guitar_fret_positions = {}
        for position in BasePositions:
            self.guitar_fret_positions[position.value] = f'Fret_{position.value}'

    # ── 辅助方法 ──────────────────────────────────────────────────

    def obj_name(self, short: str) -> str:
        """短名 → 完整对象名（带演奏者后缀）：obj_name('H_L') == 'H_L_Jd'"""
        return _pu.resolve(short, self.suffix)

    def obj(self, short: str):
        """按短名取对象（带演奏者后缀）：obj('H_L') -> bpy.data.objects.get('H_L_Jd')"""
        import bpy  # type: ignore
        return bpy.data.objects.get(self.obj_name(short))

    def get_all_left_controller_names(self) -> list[str]:
        """返回左手所有控制器名称（手掌+手指）"""
        names = list(self.left_hand_controllers.values())
        names.extend(self.left_finger_controllers.values())
        return names

    def get_all_right_controller_names(self) -> list[str]:
        """返回右手所有控制器名称（手掌+手指）"""
        names = list(self.right_hand_controllers.values())
        names.extend(self.right_finger_controllers.values())
        return names

    def get_valid_left_states(self, position: BasePositions) -> list[LeftHandStates]:
        """返回指定 position 下左手有效的所有 state"""
        invalid = self.invalid_combinations.get(position, [])
        return [s for s in LeftHandStates if s not in invalid]

    def get_all_valid_left_pairs(self) -> list[tuple[BasePositions, LeftHandStates]]:
        """返回左手所有有效的 (position, state) 组合"""
        pairs = []
        for pos in BasePositions:
            for state in self.get_valid_left_states(pos):
                pairs.append((pos, state))
        return pairs

    def get_right_hand_states(self) -> list[RightHandStates]:
        """返回右手所有有效的 state（根据 use_vibrato_bar 过滤）"""
        states = [RightHandStates.LOW,
                  RightHandStates.END, RightHandStates.HIGH]
        if self.use_vibrato_bar:
            states.extend([RightHandStates.RELEASE,
                          RightHandStates.UP, RightHandStates.DOWN])
        return states
