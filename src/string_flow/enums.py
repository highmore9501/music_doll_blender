# string_flow/enums.py
"""StringFlow 乐器模块 —— 枚举（迁移自 string_flow_blender/string_flow.py）"""

from enum import Enum
from typing import Dict, Tuple


class StringFlowInstrumentType(Enum):
    """乐器类型（小提琴/中提琴/大提琴）。

    值即写入 .violinist 的 config.instrument 标识符，Rust 端（string_flow_rust
    的 parse_instrument_from_file）据此选择琴弦音高与品格范围配置：
    - violin → InstrumentConfig::violin()（空弦 E4=76 / A3=69 / D3=62 / G3=55）
    - viola  → InstrumentConfig::viola()（空弦 A3=69 / D3=62 / G3=55 / C3=48）
    - cello  → InstrumentConfig::cello()（空弦 A2=45 / D2=38 / G2=31 / C2=24）
    """
    VIOLIN = "violin"
    VIOLA = "viola"
    CELLO = "cello"


class HandType(Enum):
    """手类型"""
    LEFT = 'L'
    RIGHT = 'R'


class LeftHandPositionType(Enum):
    """左手位置类型（按品/弦上的手型）"""
    NORMAL = "Normal"
    INNER = "Inner"
    OUTER = "Outer"


class RightHandPositionType(Enum):
    """右手位置类型（弓法）"""
    NEAR = "near"
    FAR = "far"
    PIZZICATO = "pizzicato"


class ObjectType(Enum):
    """Blender 物体类型（映射到 common.object_utils 的字符串类型）"""
    CUBE = "cube"
    CONE = "cone"
    SPHERE_EMPTY = "sphere"       # 注意：object_utils 用 "sphere" 而非 "sphere_empty"
    CIRCLE_EMPTY = "circle"       # 空环（IK 极向量 / pole 用）
    CONE_EMPTY = "cone_empty"
    SINGLE_ARROW = "single_arrow"


# 类型别名
ControllerMap = Dict[str, str]  # {描述：物体名}
Location = Tuple[float, float, float]  # (x, y, z)
Rotation = Tuple[float, float, float, float]  # (w, x, y, z) 四元数
CheckResult = Dict[str, Dict[str, int]]  # check_all_objects 返回类型
