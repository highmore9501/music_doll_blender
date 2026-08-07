# fret_dance/base.py
"""FretDance 乐器模块 —— BaseState（迁移自 fret_dance_blender/base_states.py）"""
from .enums import Instruments, BasePositions, LeftHandStates, RightHandStates
from .config import ControllerConfig
from .object_manager import BlenderObjectManager
from .state import StateTransfer
from .io import IOManager


class BaseState(ControllerConfig, BlenderObjectManager, StateTransfer, IOManager):
    """基础状态管理类 - 整合控制器配置、Blender对象管理、状态传输和IO功能

    通过多重继承整合以下模块:
    - ControllerConfig: 控制器配置
    - BlenderObjectManager: Blender场景对象操作
    - StateTransfer: 控制器与骨骼自定义属性之间的数据传输
    - IOManager: JSON文件导入导出
    """

    def __init__(self, instruments: Instruments, use_vibrato_bar: bool = False,
                 performer_suffix: str = "", target_skeleton=None,
                 target_instrument=None, performer_name=None):
        ControllerConfig.__init__(self, instruments, use_vibrato_bar,
                                  performer_suffix=performer_suffix,
                                  target_skeleton=target_skeleton,
                                  target_instrument=target_instrument,
                                  performer_name=performer_name)
