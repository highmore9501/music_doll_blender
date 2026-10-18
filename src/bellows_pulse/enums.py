# bellows_pulse/enums.py
"""BellowsPulse 乐器模块 —— 常量与纯函数（不碰 bpy）

只放「两边都要用」的领域数据与换算：

- 左右手、五指、右手键区类型等基本常量；
- 左手每一排代表什么功能（1 对位低音 … 6 减七和弦）；
- 右手按钮每排的键数规则（第 1/3/5 排 N 颗，第 2/4 排 N−1 颗）；
- midi 音高 → 音名（**只用于面板显示**，数据一律用 midi 数字，避免两套口径打架）。

规则出处：`bellows_pulse_rust/src/keymap/{keyboard,right_buttons,left_stradella}.rs`
与 `docs/项目大纲.md` §4.4 / §5。这里不实现任何建表逻辑，只是把常量对齐。
"""

# ── 基础常量 ──────────────────────────────────────────────

SEMITONE_NAMES = [
    "C", "C#", "D", "D#", "E", "F",
    "F#", "G", "G#", "A", "A#", "B",
]

#: 手别（与现有乐器一致：L / R）
HANDS = ("L", "R")

#: 手指短名主体：拇指 / 食指 / 中指 / 无名指 / 小指。
#: 与 `common.ext_utils` 的命名约定配套：手指 `<base>_<hand>`、ext `ext_<base>_<hand>`。
FINGER_BASES = ("T", "I", "M", "R", "P")

#: 只用于日志 / 面板提示
FINGER_LABELS = {
    "T": "拇指",
    "I": "食指",
    "M": "中指",
    "R": "无名指",
    "P": "小指",
}

# ── 右手键区类型（与 `.accordion` 的 right.layout 一一对应）──

RIGHT_LAYOUT_KEYBOARD = "keyboard"
RIGHT_LAYOUT_BUTTONS = "buttons"
RIGHT_LAYOUTS = (RIGHT_LAYOUT_KEYBOARD, RIGHT_LAYOUT_BUTTONS)

# ── 右手按钮：固定 5 排 ───────────────────────────────────

#: 巴扬右手按钮固定 5 排（项目约定，不开放配置）
RIGHT_BUTTON_ROWS = 5

#: 第 3 排（中间排）最低音为锚点；同一列相邻两排差 1 个半音，每往右一列差 3 个半音
RIGHT_ROW_SEMITONE_STEP = 1
RIGHT_COLUMN_SEMITONE_STEP = 3

#: 第 2/4 排比第 1/3/5 排少一颗按钮
RIGHT_SHORT_ROWS = (2, 4)

# ── 左手：每排的功能（1 基，排数不足时从第 6 排往上减）──────

LEFT_ROW_LABELS = {
    1: "对位低音",
    2: "主低音",
    3: "大三和弦",
    4: "小三和弦",
    5: "属七和弦",
    6: "减七和弦",
}


# ── 换算函数 ──────────────────────────────────────────────

def midi_to_name(note: int) -> str:
    """midi 音高 → 完整音名（C4 = 60），只用于显示。"""
    semitone = int(note)
    octave = semitone // 12 - 1
    return f"{SEMITONE_NAMES[semitone % 12]}{octave}"


def note_range_text(min_note: int, max_note: int) -> str:
    """音域显示文本，如 `C3–C6`。"""
    return f"{midi_to_name(min_note)}–{midi_to_name(max_note)}"


def keyboard_key_count(min_note: int, max_note: int) -> int:
    """右手键盘键数：最低音到最高音之间半音全排列。"""
    return max(0, int(max_note) - int(min_note) + 1)


def right_row_key_counts(first_row_keys: int) -> list[int]:
    """右手按钮每排键数（第 1/3/5 排 = N，第 2/4 排 = N − 1）。"""
    first_row_keys = int(first_row_keys)
    return [
        first_row_keys - 1 if row in RIGHT_SHORT_ROWS else first_row_keys
        for row in range(1, RIGHT_BUTTON_ROWS + 1)
    ]


def right_button_count(first_row_keys: int) -> int:
    """右手按钮总颗数。"""
    return sum(right_row_key_counts(first_row_keys))


def right_button_pitch_range(anchor_note: int, first_row_keys: int) -> tuple[int, int]:
    """右手按钮的音域（最低音, 最高音）。

    最低音取第 1 排第 1 列（锚点 − 2），最高音取第 3 排最后一列（锚点 + 3 × (N − 1)）。
    只用于面板显示与校验；真实建表由 Rust 端按同一规则推。
    """
    anchor_note = int(anchor_note)
    first_row_keys = int(first_row_keys)
    lowest = anchor_note - RIGHT_ROW_SEMITONE_STEP * 2
    highest = anchor_note + RIGHT_COLUMN_SEMITONE_STEP * (first_row_keys - 1)
    return lowest, highest


def left_row_labels(rows: int) -> list[str]:
    """左手每一排的功能名（排数不足时只取前几排）。"""
    return [LEFT_ROW_LABELS[row] for row in range(1, int(rows) + 1)
            if row in LEFT_ROW_LABELS]
