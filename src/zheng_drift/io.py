# zheng_drift/io.py
"""ZhengDrift 乐器模块 —— .zheng_master 标准姿势导入导出
（迁移自 zheng_blender_addon/zheng_recorders.py）

格式保持兼容（Rust 端继续消费）：JSON 键一律用**短名**（如 s0head / H_L_Normal_far），
仅 Blender 内对象查找用带演奏者后缀的完整名。

- STRING_RECORDERS：弦位置标记（对象，物理参考点）；
- LEFT/RIGHT_HAND_RECORDERS：左右手状态（存演奏者骨骼自定义属性，见 state.py）；
- FOOT_CONTROLLERS / BILINEAR_HELPERS：脚部与双线性辅助控制器（对象）。
"""

import json
import os
import re
from collections import defaultdict

import bpy  # type: ignore

from ..common import state_io as _sio

from .state import STATE_KEY


def _nested_dict():
    return defaultdict(_nested_dict)


def _short_of(config, full: str) -> str:
    """完整对象名 → 短名（去掉演奏者后缀）"""
    if config.suffix:
        marker = "_" + config.suffix
        if full.endswith(marker):
            return full[: -len(marker)]
    return full


def _valid_controller_shorts(config, hand: str) -> set[str]:
    """返回指定手的有效控制器短名集合（排除手指极向量）"""
    controllers = (config.left_hand_controllers if hand == "left"
                   else config.right_hand_controllers)
    shorts = set()
    for key, short in controllers.items():
        if key.endswith("_pole") and "_ik_pivot" not in key:
            continue
        shorts.add(short)
    return shorts


def export_recorder_info(file_path: str, config, skeleton) -> None:
    """导出所有记录器的位置和旋转信息到 .zheng_master JSON 文件。

    - 弦位置标记从对象读；
    - 左右手状态从骨骼自定义属性读（见 state.py）；
    - 脚部/双线性辅助控制器从对象读。
    """
    print("\n开始导出记录器信息...")
    print(f"目标文件：{file_path}")

    result = _nested_dict()

    # 弦位置记录器（对象，物理参考点）
    string_count = 0
    for recorder_key, recorder_name in config.string_recorders.items():
        full = config.obj_name(recorder_name)
        if full in bpy.data.objects:
            obj = bpy.data.objects[full]
            result['STRING_RECORDERS'][recorder_name] = {
                'location': list(obj.location),
                'rotation': list(obj.rotation_quaternion),
            }
            string_count += 1

    # 左手/右手状态记录器（从骨骼读取；键 = 短名_动作_位置）
    state = _sio.get_state_data(skeleton, STATE_KEY, {}) or {}
    left_hand_count = 0
    right_hand_count = 0
    for hand_key, section in (("left_hand", "LEFT_HAND_RECORDERS"),
                              ("right_hand", "RIGHT_HAND_RECORDERS")):
        side = state.get(hand_key, {})
        for action_str, positions in side.items():
            for pos_str, controllers in positions.items():
                for full, ctrl_data in controllers.items():
                    short = _short_of(config, full)
                    if not short:
                        continue
                    recorder_name = f"{short}_{action_str}_{pos_str}"
                    result[section][recorder_name] = {
                        "location": ctrl_data.get("location", [0, 0, 0]),
                        "rotation": ctrl_data.get("rotation", [1, 0, 0, 0]),
                    }
                    if hand_key == "left_hand":
                        left_hand_count += 1
                    else:
                        right_hand_count += 1

    # 脚部控制器
    foot_count = 0
    for controller_key, controller_name in config.foot_controllers.items():
        full = config.obj_name(controller_name)
        if full in bpy.data.objects:
            obj = bpy.data.objects[full]
            result['FOOT_CONTROLLERS'][controller_name]['location'] = list(
                obj.location)
            result['FOOT_CONTROLLERS'][controller_name]['rotation'] = list(
                obj.rotation_quaternion)
            foot_count += 1

    # 双线性映射辅助控制器（只导出位置）
    bilinear_count = 0
    for helper_key, helper_name in config.bilinear_helpers.items():
        full = config.obj_name(helper_name)
        if full in bpy.data.objects:
            obj = bpy.data.objects[full]
            result['BILINEAR_HELPERS'][helper_name] = {
                'location': list(obj.location)
            }
            bilinear_count += 1

    # 标记数据来源为 Blender
    result['is_blender'] = True

    # 写入文件
    data = json.dumps(result, indent=4)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(data)

    total_count = string_count + left_hand_count + \
        right_hand_count + foot_count + bilinear_count
    print("\n" + "=" * 60)
    print("✓ 记录器信息导出成功!")
    print("=" * 60)
    print(f" • 弦位置记录器：{string_count} 个")
    print(f" • 左手状态记录器：{left_hand_count} 个")
    print(f" • 右手状态记录器：{right_hand_count} 个")
    print(f" • 脚部控制器：{foot_count} 个")
    print(f" • 双线性映射辅助控制器：{bilinear_count} 个")
    print(f" • 总计：{total_count} 个对象")
    print(f"  • 文件路径：{file_path}")
    print("=" * 60)


def import_recorder_info(file_path: str, config, skeleton) -> None:
    """从 .zheng_master JSON 文件导入记录器信息。

    - 弦位置标记写回对象；
    - 左右手状态写入骨骼自定义属性（之后用 Load 应用到控制器）；
    - 脚部/双线性辅助控制器写回对象。
    """
    print("\n开始导入记录器信息...")
    print(f"源文件：{file_path}")

    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"找不到文件：{file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        loaded_count = 0

        # 弦位置记录器（对象，物理参考点）
        string_loaded = 0
        if 'STRING_RECORDERS' in data:
            for recorder_name, location_data in data['STRING_RECORDERS'].items():
                if recorder_name in config.string_recorders.values():
                    full = config.obj_name(recorder_name)
                    if full in bpy.data.objects:
                        obj = bpy.data.objects[full]
                        obj.location = location_data['location']
                        if 'rotation' in location_data:
                            obj.rotation_quaternion = location_data['rotation']
                        string_loaded += 1
        loaded_count += string_loaded

        # 左手/右手状态记录器（写入骨骼自定义属性；键 = 短名_动作_位置）
        pattern = re.compile(
            r"^(.*)_(Normal|Press|Tremolo)_(far|middle|near)$")
        state = _sio.get_state_data(skeleton, STATE_KEY, {}) or {}
        left_hand_loaded = 0
        right_hand_loaded = 0
        for hand_key, section, valid_shorts in (
                ("left_hand", "LEFT_HAND_RECORDERS",
                 _valid_controller_shorts(config, "left")),
                ("right_hand", "RIGHT_HAND_RECORDERS",
                 _valid_controller_shorts(config, "right"))):
            if section not in data:
                continue
            for recorder_name, pose_data in data[section].items():
                m = pattern.match(recorder_name)
                if not m:
                    continue
                short, action_str, pos_str = m.group(1), m.group(2), m.group(3)
                if short not in valid_shorts:
                    continue
                entry = {
                    "location": pose_data.get("location", [0, 0, 0]),
                    "rotation": pose_data.get("rotation", [1, 0, 0, 0]),
                }
                (state.setdefault(hand_key, {})
                 .setdefault(action_str, {})
                 .setdefault(pos_str, {})[short]) = entry
                if hand_key == "left_hand":
                    left_hand_loaded += 1
                else:
                    right_hand_loaded += 1
        _sio.set_state_data(skeleton, STATE_KEY, state)
        loaded_count += left_hand_loaded + right_hand_loaded

        # 脚部控制器
        foot_loaded = 0
        if 'FOOT_CONTROLLERS' in data:
            for controller_name, controller_data in data['FOOT_CONTROLLERS'].items():
                if controller_name in config.foot_controllers.values():
                    full = config.obj_name(controller_name)
                    if full in bpy.data.objects:
                        obj = bpy.data.objects[full]
                        obj.location = controller_data['location']
                        if 'rotation' in controller_data:
                            obj.rotation_quaternion = controller_data['rotation']
                        foot_loaded += 1
        loaded_count += foot_loaded

        # 双线性映射辅助控制器（只导入位置）
        bilinear_loaded = 0
        if 'BILINEAR_HELPERS' in data:
            for helper_name, helper_data in data['BILINEAR_HELPERS'].items():
                if helper_name in config.bilinear_helpers.values():
                    full = config.obj_name(helper_name)
                    if full in bpy.data.objects:
                        obj = bpy.data.objects[full]
                        obj.location = helper_data['location']
                        bilinear_loaded += 1
        loaded_count += bilinear_loaded

        print("\n" + "=" * 60)
        print("✓ 记录器信息导入成功!")
        print("=" * 60)
        print(f" • 弦位置记录器：{string_loaded} 个")
        print(f" • 左手状态记录器：{left_hand_loaded} 个")
        print(f" • 右手状态记录器：{right_hand_loaded} 个")
        print(f" • 脚部控制器：{foot_loaded} 个")
        print(f" • 双线性映射辅助控制器：{bilinear_loaded} 个")
        print(f" • 总计：{loaded_count} 个对象")
        print(f"  • 文件路径：{file_path}")
        print("=" * 60)

    except FileNotFoundError as e:
        print(f"\n✗ 错误：{e}")
    except json.JSONDecodeError as e:
        print(f"\n✗ JSON 格式错误：{e}")
    except Exception as e:
        print(f"\n✗ 导入过程中发生错误：{e}")
        import traceback
        traceback.print_exc()
