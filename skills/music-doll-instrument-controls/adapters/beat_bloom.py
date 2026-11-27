"""BeatBloom（架子鼓）适配器。

固定乐器，controller_root 没有跟随要求。手指控件与 test 同名（T/I/M/R/P + 侧别），
极向量是 `<指>_pole_<侧>`（拇指也是 T_pole_L，不是 TP_L）。

模块会建 `Head_Control`（头往哪转）+ `Look_At`（视点，挂在 `Middle_Hand` 下）：
装完控件要把人物接上去 —— 颈上 IK、头骨复制旋转，见 head_chain。
"""


def build_config(performer, variant):
    from music_doll_blender.beat_bloom.config import BeatBloomConfig
    return BeatBloomConfig(
        performer_suffix=performer.name,
        target_skeleton=performer.target_skeleton,
    )


ADAPTER = {
    "instrument": "beat_bloom",
    "label": "BeatBloom 架子鼓",
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
        "T_L_test": "T_L",
        "I_L_test": "I_L",
        "M_L_test": "M_L",
        "R_L_test": "R_L",
        "P_L_test": "P_L",
        "T_L_pole_test": "T_pole_L",
        "I_L_pole_test": "I_pole_L",
        "M_L_pole_test": "M_pole_L",
        "R_L_pole_test": "R_pole_L",
        "P_L_pole_test": "P_pole_L",
        "T_R_test": "T_R",
        "I_R_test": "I_R",
        "M_R_test": "M_R",
        "R_R_test": "R_R",
        "P_R_test": "P_R",
        "T_R_pole_test": "T_pole_R",
        "I_R_pole_test": "I_pole_R",
        "M_R_pole_test": "M_pole_R",
        "R_R_pole_test": "R_pole_R",
        "P_R_pole_test": "P_pole_R",
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
