"""FretDance（吉他）适配器。

吉他模块没有脚部控件，但骨架的腿 IK 仍需要 F_L / FP_L 目标；
这里用 fallback_controls 在 test 脚控件的原位补两个空物体控件，再正常替换。
controller_root 按规则跟随胸骨。
"""


def build_config(performer, variant):
    from music_doll_blender.fret_dance.base import BaseState
    from music_doll_blender.fret_dance.enums import Instruments
    variant_map = {
        "finger_style": Instruments.FINGER_STYLE_GUITAR,
        "electric": Instruments.ELECTRIC_GUITAR,
        "bass": Instruments.BASS,
    }
    instrument_type = variant_map.get(variant or "finger_style")
    if instrument_type is None:
        raise RuntimeError("未知吉他变体：" + str(variant))
    return BaseState(
        instrument_type,
        use_vibrato_bar=(variant == "electric"),
        performer_suffix=performer.name,
        target_skeleton=performer.target_skeleton,
        target_instrument=performer.target_instrument,
        performer_name=performer.name,
    )


ADAPTER = {
    "instrument": "fret_dance",
    "label": "FretDance 吉他",
    "build_config": build_config,
    "default_variant": "finger_style",
    "controller_root": {
        "default": {"mode": "bone", "bone": "上半身2", "label": "胸骨"},
        "variants": {
            "finger_style": {"mode": "bone", "bone": "上半身2", "label": "胸骨"},
            "electric": {"mode": "bone", "bone": "上半身2", "label": "胸骨"},
            "bass": {"mode": "bone", "bone": "上半身2", "label": "胸骨"},
        },
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
        "T_L_pole_test": "TP_L",
        "I_L_pole_test": "I_L_pole",
        "M_L_pole_test": "M_L_pole",
        "R_L_pole_test": "R_L_pole",
        "P_L_pole_test": "P_L_pole",
        "T_R_test": "T_R",
        "I_R_test": "I_R",
        "M_R_test": "M_R",
        "R_R_test": "R_R",
        "P_R_test": "P_R",
        "T_R_pole_test": "TP_R",
        "I_R_pole_test": "I_R_pole",
        "M_R_pole_test": "M_R_pole",
        "R_R_pole_test": "R_R_pole",
        "P_R_pole_test": "P_R_pole",
    },
    "fallback_controls": {
        "F_L_test": {"short": "F_L", "parent": "performer_root",
                     "collection": "Controllers", "display": "CUBE"},
        "F_R_test": {"short": "F_R", "parent": "performer_root",
                     "collection": "Controllers", "display": "CUBE"},
        "FP_L_test": {"short": "FP_L", "parent": "performer_root",
                      "collection": "Controllers", "display": "CIRCLE"},
        "FP_R_test": {"short": "FP_R", "parent": "performer_root",
                      "collection": "Controllers", "display": "CIRCLE"},
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
