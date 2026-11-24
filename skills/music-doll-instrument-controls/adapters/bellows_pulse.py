"""BellowsPulse（手风琴）适配器。

手风琴是固定乐器，但按作者规则 controller_root 必须跟随胸骨；
setup 会先建目标留空的 Copy Location / Copy Rotation，安装时填目标即可。
"""

ADAPTER = {
    "instrument": "bellows_pulse",
    "label": "BellowsPulse 手风琴",
    "config_module": "music_doll_blender.bellows_pulse.config",
    "config_class": "BellowsConfig",
    "controller_root": {
        "default": {"mode": "bone", "bone": "上半身2", "label": "胸骨"},
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
        "T_L_pole_test": "T_L_pole",
        "I_L_pole_test": "I_L_pole",
        "M_L_pole_test": "M_L_pole",
        "R_L_pole_test": "R_L_pole",
        "P_L_pole_test": "P_L_pole",
        "T_R_test": "T_R",
        "I_R_test": "I_R",
        "M_R_test": "M_R",
        "R_R_test": "R_R",
        "P_R_test": "P_R",
        "T_R_pole_test": "T_R_pole",
        "I_R_pole_test": "I_R_pole",
        "M_R_pole_test": "M_R_pole",
        "R_R_pole_test": "R_R_pole",
        "P_R_pole_test": "P_R_pole",
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
