# common/state_io.py
"""状态存取 —— 公共模块（对应各乐器插件的 state_transfer / state_manager）

提供所有乐器共用的：
- 对象 ↔ 字典 的变换搬运（处理约束器影响 / 旋转模式）；
- 骨骼自定义属性上的 JSON 状态读写；
- 面板 ↔ 骨骼 的演奏者设置同步（无状态化核心）。
"""

import bpy  # type: ignore
from mathutils import Quaternion  # type: ignore

from . import io_utils


# ── 对象真实变换值（处理约束器影响）──────────────────────────

def get_true_transform_value(obj, transform_type):
    """获取对象的真实变换值，处理约束器影响。

    :param obj: Blender 对象
    :param transform_type: 'location' 或 'rotation'
    :return: 变换值（location: Vector；rotation: Quaternion）
    """
    if not obj.constraints or len(obj.constraints) == 0:
        if transform_type == "location":
            return obj.location.copy()
        elif transform_type == "rotation":
            if obj.rotation_mode != "QUATERNION":
                original_rotation_mode = obj.rotation_mode
                obj.rotation_mode = "QUATERNION"
                result = obj.rotation_quaternion.copy()
                obj.rotation_mode = original_rotation_mode
                return result
            else:
                return obj.rotation_quaternion.copy()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    matrix_world = eval_obj.matrix_world

    if transform_type == "location":
        return matrix_world.translation.copy()
    elif transform_type == "rotation":
        return matrix_world.to_quaternion()
    return None


def _unlock_object_location(obj):
    obj.lock_location[0] = False
    obj.lock_location[1] = False
    obj.lock_location[2] = False


def _unlock_object_rotation(obj):
    obj.lock_rotation[0] = False
    obj.lock_rotation[1] = False
    obj.lock_rotation[2] = False


def copy_transfer_between_object_and_dict(obj, data_dict: dict,
                                          direction: str = "set",
                                          key: str | None = None) -> None:
    """obj ↔ JSON dict 之间的数据搬运。

    direction="set": 从 obj 读取 loc/rot → 写入 data_dict[key or obj.name]
    direction="load": 从 data_dict[key or obj.name] 读取 loc/rot → 应用到 obj

    key 可选，用于把数据键与场景对象名解耦：场景控件名带演奏者后缀（obj.name），
    但骨骼/avatar 数据键用不带后缀的短名（key=短名），保证不同演奏者数据结构一致。
    """
    data_key = key if key is not None else obj.name
    if direction == "set":
        true_loc = get_true_transform_value(obj, "location")
        true_rot = get_true_transform_value(obj, "rotation")
        data_dict[data_key] = {
            "location": [true_loc.x, true_loc.y, true_loc.z],
            "rotation": [true_rot.w, true_rot.x, true_rot.y, true_rot.z],
        }
    elif direction == "load":
        entry = data_dict.get(data_key)
        if entry is None:
            return
        loc = entry.get("location")
        rot = entry.get("rotation")
        if loc and len(loc) == 3:
            _unlock_object_location(obj)
            obj.location = (loc[0], loc[1], loc[2])
        if rot and len(rot) == 4:
            _unlock_object_rotation(obj)
            if obj.rotation_mode == "QUATERNION":
                obj.rotation_quaternion = (rot[0], rot[1], rot[2], rot[3])
            else:
                obj.rotation_euler = Quaternion(
                    (rot[0], rot[1], rot[2], rot[3])).to_euler(obj.rotation_mode)


# ── 骨骼自定义属性上的 JSON 状态读写 ──────────────────────────

def get_state_data(skeleton: bpy.types.Object | None, key: str,
                   default=None) -> dict | None:
    """从骨骼自定义属性读取 JSON 数据（key 为属性名，如 'fret_dance_controller_data'）。"""
    if skeleton is None:
        return default
    raw = skeleton.get(key)
    data = io_utils.load_dict_from_json_str(raw)
    return data if data else default


def set_state_data(skeleton: bpy.types.Object | None, key: str,
                   data: dict) -> None:
    """把 dict 写入骨骼自定义属性（JSON 字符串）。"""
    if skeleton is None:
        return
    skeleton[key] = io_utils.dump_dict_to_json_str(data)


def get_bone_attr(skeleton: bpy.types.Object | None, key: str,
                  default=None):
    """读取骨骼自定义属性（任意标量/字符串，非 JSON）。"""
    if skeleton is None:
        return default
    return skeleton.get(key, default)


def set_bone_attr(skeleton: bpy.types.Object | None, key: str, value) -> None:
    """写入骨骼自定义属性（任意标量/字符串）。"""
    if skeleton is None:
        return
    skeleton[key] = value


# ── 演奏者设置同步（无状态化核心）─────────────────────────────

# 演奏者通用设置存骨骼的 JSON 键名（可被乐器模块覆盖或沿用）
DEFAULT_SETTINGS_KEY = "md_settings"


def load_settings(skeleton: bpy.types.Object | None,
                  key: str = DEFAULT_SETTINGS_KEY) -> dict:
    """从骨骼读取演奏者设置 dict（无该键时返回 {}）。"""
    if skeleton is None:
        return {}
    raw = skeleton.get(key)
    return io_utils.load_dict_from_json_str(raw)


def save_settings(skeleton: bpy.types.Object | None,
                  settings: dict, key: str = DEFAULT_SETTINGS_KEY) -> None:
    """把演奏者设置 dict 写回骨骼。"""
    if skeleton is None:
        return
    skeleton[key] = io_utils.dump_dict_to_json_str(settings)
