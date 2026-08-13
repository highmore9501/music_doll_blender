# beat_bloom/enums.py
"""BeatBloom 乐器模块 —— 枚举定义"""

from enum import Enum


class States(Enum):
    """击打状态（beat/ready/rest 三态）"""
    BEAT = "beat"
    READY = "ready"
    REST = "rest"


# 状态名称列表（供 Blender EnumProperty items 使用）
STATE_ITEMS = [(s.value, s.value.capitalize(), "") for s in States]

# 各肢体对应的控制器短名
LIMB_CONTROLLERS = {
    "right_hand": ["H_R", "HP_R"],
    "left_hand":  ["H_L", "HP_L"],
    "right_foot": ["F_R"],
    "left_foot":  ["F_L"],
}

# Head_Control 随手部动作一起记录
HAND_LIMBS = {"right_hand", "left_hand"}
