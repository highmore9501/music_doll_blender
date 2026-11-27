"""KeyRipple（钢琴）适配器。

钢琴是固定乐器，controller_root 没有跟随要求。手指控件按钢琴自己的编号：
左手 0..4 = 小指→拇指，右手 5..9 = 拇指→小指；极向量按同一编号命名。

模块会建 `Head_Control` + `Look_At`（挂在 `Mid_Hand` 下、由双手驱动）：
装完控件要把人物接上去 —— 颈上 IK、头骨复制旋转，见 head_chain。
"""


def build_config(performer, variant):
    from music_doll_blender.key_ripple.config import KeyRipple
    return KeyRipple(
        one_hand_finger_number=5,
        leftest_position=28,
        left_position=40,
        middle_left_position=52,
        middle_right_position=76,
        right_position=88,
        rightest_position=100,
        min_key=21,
        max_key=108,
        hand_range=12,
        performer_suffix=performer.name,
        target_skeleton=performer.target_skeleton,
        target_instrument=performer.target_instrument,
        performer_name=performer.name,
    )


ADAPTER = {
    "instrument": "key_ripple",
    "label": "KeyRipple 钢琴",
    "build_config": build_config,
    "controller_root": {"default": {"mode": "none"}},
    "head_chain": {
        "head_control": "Head_Control",
        "look_at": "Look_At",
        "look_distance": 1.0,
    },
    "test_to_short": {
        "H_L_test": "H_L",
        "H_R_test": "H_R",
        "HP_L_test": "HP_L",
        "HP_R_test": "HP_R",
        "F_L_test": "F_L",
        "F_R_test": "F_R",
        "FP_L_test": "FP_L",
        "FP_R_test": "FP_R",
        # 左手 0..4 = 小指→拇指
        "T_L_test": "4_L",
        "I_L_test": "3_L",
        "M_L_test": "2_L",
        "R_L_test": "1_L",
        "P_L_test": "0_L",
        "T_L_pole_test": "pole_4",
        "I_L_pole_test": "pole_3",
        "M_L_pole_test": "pole_2",
        "R_L_pole_test": "pole_1",
        "P_L_pole_test": "pole_0",
        # 右手 5..9 = 拇指→小指
        "T_R_test": "5_R",
        "I_R_test": "6_R",
        "M_R_test": "7_R",
        "R_R_test": "8_R",
        "P_R_test": "9_R",
        "T_R_pole_test": "pole_5",
        "I_R_pole_test": "pole_6",
        "M_R_pole_test": "pole_7",
        "R_R_pole_test": "pole_8",
        "P_R_pole_test": "pole_9",
    },
    "behavior_samples": [
        {"name": "arm_lift", "target": "H_L_test",
         "kind": "translate", "delta": [0.0, 0.0, 0.05]},
        {"name": "hand_twist", "target": "H_L_test",
         "kind": "rotate_world", "axis": [0.0, 0.0, 1.0], "degrees": 20.0},
        {"name": "finger_bend", "target": "I_L_test",
         "kind": "translate_toward", "other": "H_L_test", "distance": 0.01,
         "tolerance_m": 0.002, "tolerance_deg": 5.0},
        {"name": "leg_forward", "target": "F_L_test",
         "kind": "translate", "delta": [0.0, 0.10, 0.0]},
    ],
}
