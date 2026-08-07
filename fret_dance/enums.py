# fret_dance/enums.py
"""FretDance 乐器模块 —— 枚举定义（迁移自 fret_dance_blender/enums.py）"""
from enum import IntEnum, Enum
from collections import defaultdict


class Instruments(IntEnum):
    FINGER_STYLE_GUITAR = 0
    ELECTRIC_GUITAR = 1
    BASS = 2


class BasePositions(Enum):
    P0 = 'P0'
    P1 = 'P1'
    P2 = 'P2'
    P3 = 'P3'
    P4 = 'P4'


class LeftHandStates(Enum):
    NORMAL = "Normal"
    OUTER = "Outer"
    INNER = "Inner"
    BARRE = "Barre"


class RightHandStates(Enum):
    LOW = "low"
    END = "end"
    HIGH = "high"
    RELEASE = "release"   # 颤音摇杆-松开
    UP = "up"             # 颤音摇杆-上摇
    DOWN = "down"         # 颤音摇杆-下压


def nested_dict():
    return defaultdict(nested_dict)
