# zheng_drift/enums.py
"""ZhengDrift 乐器模块 —— 枚举（迁移自 zheng_blender_addon/zheng_types.py）"""

from enum import Enum
from typing import Dict, Tuple


class LeftHandAction(Enum):
    """左手动作类型"""
    NORMAL = "Normal"      # 普通拨弦
    PRESS = "Press"        # 按弦


class RightHandAction(Enum):
    """右手动作类型"""
    NORMAL = "Normal"      # 普通拨弦
    TREMOLO = "Tremolo"    # 摇指


class HandPosition(Enum):
    """演奏位置（基于弦索引）"""
    FAR = "far"        # 0 弦（最远端）
    MIDDLE = "middle"  # 10 弦（中间）
    NEAR = "near"      # 20 弦（最近端）


class ObjectType(Enum):
    """Blender 物体类型（映射到 common.object_utils 的字符串类型）"""
    CUBE = "cube"
    CONE = "cone"
    SPHERE_EMPTY = "sphere"       # 注意：object_utils 用 "sphere" 而非 "sphere_empty"
    CONE_EMPTY = "cone_empty"
    SINGLE_ARROW = "single_arrow"


# 类型别名
ControllerMap = Dict[str, str]  # {描述：物体名}
RecorderMap = Dict[str, str]    # {键：物体名}
Location = Tuple[float, float, float]  # (x, y, z)
Rotation = Tuple[float, float, float, float]  # (w, x, y, z) 四元数
CheckResult = Dict[str, Dict[str, int]]  # check_all_objects 返回类型
