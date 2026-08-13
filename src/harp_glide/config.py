# harp_glide/config.py
"""HarpGlide 乐器模块 —— 配置（控件命名表 + 命名辅助 + harp config 骨骼读写）"""

import bpy  # type: ignore

from ..common import performer_utils as _pu
from ..common import state_io

STATE_KEY = "harp_glide_state_data"


class HarpConfig:
    """竖琴（竖琴演奏者）配置：控件命名表 + obj_name/obj 辅助"""

    def __init__(self, performer_suffix: str = "",
                 target_skeleton=None, target_instrument=None,
                 performer_name: str = ""):
        self.suffix: str = performer_suffix
        self.target_skeleton = target_skeleton
        self.target_instrument = target_instrument
        self.performer_name: str = performer_name or (
            performer_suffix if performer_suffix else "Performer")
        self.instruments_name: str = "harp_glide"

        # ── 身体控制器 ──
        self.body_controllers = {
            "head":          "Head",
            "shoulder_harp": "Shoulder_Harp",
        }

        # ── 左手（7 个主控） ──
        self.left_hand_controllers = {
            "left_hand_controller":   "H_L",
            "left_hand_ik_pivot":     "HP_L",
            "left_thumb_controller":  "T_L",
            "left_index_controller":  "I_L",
            "left_middle_controller": "M_L",
            "left_ring_controller":   "R_L",
            "left_little_controller": "P_L",
        }

        # ── 右手（7 个主控） ──
        self.right_hand_controllers = {
            "right_hand_controller":   "H_R",
            "right_hand_ik_pivot":     "HP_R",
            "right_thumb_controller":  "T_R",
            "right_index_controller":  "I_R",
            "right_middle_controller": "M_R",
            "right_ring_controller":   "R_R",
            "right_little_controller": "P_R",
        }

        # ── 脚部（4 个） ──
        self.foot_controllers = {
            "left_foot_controller":  "F_L",
            "left_foot_pole":        "FP_L",
            "right_foot_controller": "F_R",
            "right_foot_pole":       "FP_R",
        }

        # ── 视线辅助（不挂 controller_root） ──
        self.target_controllers = {
            "mid_hand": "Mid_Hand",
            "look_at":  "Look_At",
        }

        # ── 竖琴支点 ──
        self.harp_pivot_controllers = {
            "harp_pivot": "harp_pivot",
        }

        # 左/右手五指短名（用于 state 模块批量操作）
        self.left_finger_shorts = ["T_L", "I_L", "M_L", "R_L", "P_L"]
        self.right_finger_shorts = ["T_R", "I_R", "M_R", "R_R", "P_R"]

    # ── 命名辅助 ─────────────────────────────────────────────────

    def obj_name(self, short: str) -> str:
        return _pu.resolve(short, self.suffix)

    def obj(self, short: str):
        return bpy.data.objects.get(self.obj_name(short))

    # ── harp config 骨骼读写 ─────────────────────────────────────

    def get_harp_config(self, skeleton=None) -> dict:
        """从骨骼 JSON 读 config 节（缺失返回含默认值的 dict）"""
        sk = skeleton or self.target_skeleton
        data = state_io.get_state_data(sk, STATE_KEY, {})
        return data.get("config", {
            "string_count": 47,
            "left_far": 0, "left_near": 0,
            "left_mid_far": 0, "left_mid_near": 0,
            "right_far": 0, "right_near": 0,
        })

    def save_harp_config(self, props, skeleton=None) -> None:
        """将 PropertyGroup 里的 config 参数写回骨骼 JSON"""
        sk = skeleton or self.target_skeleton
        if sk is None:
            return
        data = state_io.get_state_data(sk, STATE_KEY, {})
        data["config"] = {
            "string_count": int(props.string_count),
            "left_far":     int(props.left_far),
            "left_near":    int(props.left_near),
            "left_mid_far": int(props.left_mid_far),
            "left_mid_near": int(props.left_mid_near),
            "right_far":    int(props.right_far),
            "right_near":   int(props.right_near),
        }
        state_io.set_state_data(sk, STATE_KEY, data)

    def load_harp_config(self, props, skeleton=None) -> None:
        """将骨骼 JSON 的 config 节回填到面板属性（读取从骨骼来）

        与 save_harp_config 对称；骨骼缺省键时保留面板当前值，不强行覆盖。
        """
        sk = skeleton or self.target_skeleton
        if sk is None:
            return
        cfg = self.get_harp_config(sk)
        props.string_count = int(cfg.get("string_count",   props.string_count))
        props.left_far = int(cfg.get("left_far",       props.left_far))
        props.left_near = int(cfg.get("left_near",      props.left_near))
        props.left_mid_far = int(cfg.get("left_mid_far",   props.left_mid_far))
        props.left_mid_near = int(
            cfg.get("left_mid_near",  props.left_mid_near))
        props.right_far = int(cfg.get("right_far",      props.right_far))
        props.right_near = int(cfg.get("right_near",     props.right_near))
