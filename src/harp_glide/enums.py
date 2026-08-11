# harp_glide/enums.py
"""HarpGlide 乐器模块 —— 枚举类型（迁移自 harp_blender_addon/harp_types.py）"""

from enum import Enum


class HandPoseState(Enum):
    FAR = "far"
    NEAR = "near"
    ATTACK = "attack"
    REST = "rest"


class PedalNote(Enum):
    """D-C-B 由左脚控制；E-F-G-A 由右脚控制"""
    D = "D"
    C = "C"
    B = "B"
    E = "E"
    F = "F"
    G = "G"
    A = "A"


class PedalState(Enum):
    STATE_0 = "state0"  # ♭ Flat
    STATE_1 = "state1"
    STATE_2 = "state2"  # ♮ Natural
    STATE_3 = "state3"
    STATE_4 = "state4"  # ♯ Sharp


class HarpPivotState(Enum):
    NEAR = "near"
    MID = "mid"
    FAR = "far"


# D / C / B 踏板由左脚控制
LEFT_FOOT_NOTES = frozenset({"D", "C", "B"})

HAND_POSE_ITEMS = [
    ("FAR",    "Far",    "常规演奏远端"),
    ("NEAR",   "Near",   "常规演奏近端"),
    ("ATTACK", "Attack", "拨弦瞬间"),
    ("REST",   "Rest",   "完成后休息姿势"),
]

PEDAL_NOTE_ITEMS = [
    ("D", "D (左脚)", ""),
    ("C", "C (左脚)", ""),
    ("B", "B (左脚)", ""),
    ("E", "E (右脚)", ""),
    ("F", "F (右脚)", ""),
    ("G", "G (右脚)", ""),
    ("A", "A (右脚)", ""),
]

PEDAL_STATE_ITEMS = [
    ("STATE_0", "0 (♭ Flat)",    ""),
    ("STATE_1", "1",              ""),
    ("STATE_2", "2 (♮ Natural)", ""),
    ("STATE_3", "3",              ""),
    ("STATE_4", "4 (♯ Sharp)",   ""),
]

TILT_STATE_ITEMS = [
    ("NEAR", "Near", "近端（向演奏者倾斜）"),
    ("MID",  "Mid",  "中间位置"),
    ("FAR",  "Far",  "远端（向远处倾斜）"),
]
