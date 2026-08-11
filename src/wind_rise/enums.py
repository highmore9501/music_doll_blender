# wind_rise/enums.py
"""WindRise 乐器模块 —— 乐器类型枚举"""

SEMITONE_NAMES = [
    "C", "C#", "D", "D#", "E", "F",
    "F#", "G", "G#", "A", "A#", "B",
]

WIND_INSTRUMENT_TYPE_ITEMS = [
    ("chinese_dizi", "中式笛子", "中式笛子"),
    ("flute", "长笛", "Western concert flute"),
    ("clarinet", "单簧管", "Clarinet"),
    ("saxophone", "萨克斯", "Saxophone"),
    ("recorder", "竖笛", "Recorder"),
    ("custom", "自定义", "手动输入乐器类型名称"),
]

HAND_CONTROLLER_BASES = ["H", "HP", "T", "I", "M", "R", "P"]
FINGER_CONTROLLER_BASES = ["T", "I", "M", "R", "P"]
POLE_CONTROLLER_BASES = ["T", "I", "M", "R", "P"]
FOOT_CONTROLLER_BASES = ["F", "FP"]
HANDS = ["L", "R"]


def midi_to_name(note: int) -> str:
    """MIDI 音符号 → 完整音名，如 60 → 'C4'。"""
    octave = (note // 12) - 1
    return f"{SEMITONE_NAMES[note % 12]}{octave}"


def make_controller_name(base: str, hand: str) -> str:
    return f"{base}_{hand}"


def make_pole_controller_name(base: str, hand: str) -> str:
    return f"{base}_{hand}_pole"


def make_ext_controller_name(base: str, hand: str) -> str:
    return f"ext_{make_controller_name(base, hand)}"


def iter_hand_controllers():
    """遍历所有手部控制器短名（H/HP/T/I/M/R/P × L/R）。"""
    for hand in HANDS:
        for base in HAND_CONTROLLER_BASES:
            yield make_controller_name(base, hand)


def iter_finger_controllers(hand: str):
    for base in FINGER_CONTROLLER_BASES:
        yield make_controller_name(base, hand)


def iter_pole_controllers():
    for hand in HANDS:
        for base in POLE_CONTROLLER_BASES:
            yield make_pole_controller_name(base, hand)


def iter_foot_controllers():
    for hand in HANDS:
        for base in FOOT_CONTROLLER_BASES:
            yield make_controller_name(base, hand)


def get_palm_name_for_hand(hand: str) -> str:
    return f"H_{hand}"


def get_ext_name_for_pole(pole_name: str) -> str:
    """T_L_pole → ext_T_L"""
    parts = pole_name.rsplit("_", 2)
    if len(parts) >= 2:
        return f"ext_{parts[0]}_{parts[1]}"
    return ""
