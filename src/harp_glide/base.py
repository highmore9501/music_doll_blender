# harp_glide/base.py
"""HarpGlide 乐器模块 —— HarpBaseState（组合 Config + ObjectManager）"""

from .object_manager import HarpObjectManager


class HarpBaseState(HarpObjectManager):
    """竖琴基础状态：HarpConfig + HarpObjectManager 的组合入口

    state.py / io.py 的函数以独立函数形式调用，不混入此类。
    """

    def __init__(self, performer_suffix: str = "",
                 target_skeleton=None, target_instrument=None,
                 performer_name: str = ""):
        HarpObjectManager.__init__(
            self,
            performer_suffix=performer_suffix,
            target_skeleton=target_skeleton,
            target_instrument=target_instrument,
            performer_name=performer_name,
        )
