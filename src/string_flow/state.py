# string_flow/state.py
"""StringFlow 乐器模块 —— 状态传输（存演奏者骨骼自定义属性）

原版把状态存到约 230 个记录器物体（sphere）上（transfer_hand_state / transfer_finger_state
的对象间拷贝），移植后统一存骨骼 string_flow_state_data（与 key_ripple / zheng_drift 一致），
不再生成状态记录器物体。

骨骼 JSON 结构（数据键一律短名，无演奏者后缀）：
{
  "left_hand":  { "string_{i}": { "fret_{j}": { "<position>": { "<控制器短名>": {"location":[...],"rotation":[...]} } } } },
  "right_hand": { "string_{i}": { "<position>": { ... } } }
}
左手 position: Normal/Inner/Outer；右手 position: near/far/pizzicato。
右手状态含全部手指 + String_Touch_Point + Bow_Controller（只存位置；
Bow 旋转由指向约束实时决定，不再采集，Rust 端不读）。

坐标语义：保存的是控制器的局部坐标（相对 controller_root = 原版 violin 帧），
与原版记录器（recorder.location = controller.location）完全一致。
"""

import bpy  # type: ignore

from ..common import state_io as _sio

from .enums import HandType

# 骨骼自定义属性键
STATE_KEY = "string_flow_state_data"


def _get_state(skeleton) -> dict:
    return _sio.get_state_data(skeleton, STATE_KEY, {}) or {}


def _set_state(skeleton, data: dict) -> None:
    _sio.set_state_data(skeleton, STATE_KEY, data)


# ── 变换读取 / 应用（对齐原版 copy_transfer 语义） ──────────


def _location_of(obj) -> list:
    """对象局部位置（原版 recorder.location = controller.location，直接复制局部坐标）"""
    return [obj.location.x, obj.location.y, obj.location.z]


def _rotation_of(obj) -> list:
    """读取旋转四元数 [w,x,y,z]。

    控制器旋转属性即局部值；Bow 旋转已停采（不再有带约束的求值读取），
    无需 depsgraph 分支。
    """
    q = obj.rotation_quaternion
    return [q.w, q.x, q.y, q.z]


def _unlock(obj) -> None:
    """解锁对象的位置/旋转锁定（状态写入前调用，对齐原版 copy_transfer 的 unlock）"""
    if obj is None:
        return
    obj.lock_location[0] = False
    obj.lock_location[1] = False
    obj.lock_location[2] = False
    obj.lock_rotation[0] = False
    obj.lock_rotation[1] = False
    obj.lock_rotation[2] = False
    if hasattr(obj, 'lock_rotation_w'):
        obj.lock_rotation_w = False


def _apply_entry(obj, entry: dict) -> None:
    """把 {location, rotation} 应用到控制器（解锁后赋值）"""
    if obj is None:
        return
    _unlock(obj)
    loc = entry.get("location")
    if loc and len(loc) == 3:
        obj.location = (loc[0], loc[1], loc[2])
    rot = entry.get("rotation")
    if rot and len(rot) == 4:
        if obj.rotation_mode != "QUATERNION":
            obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = (rot[0], rot[1], rot[2], rot[3])


# ── 该手状态涉及的控制器清单 ────────────────────────────────

def _controller_shorts(config, hand: HandType) -> list:
    """返回该手状态涉及的控制器 (短名, 是否旋转, 是否求值旋转) 列表。

    左手：H_L(位置+旋转)、HP_L、T_L、全部手指 1~N_L；
    右手：H_R(位置+旋转)、HP_R、T_R、全部手指 1~N_R、
          String_Touch_Point、Bow_Controller(只存位置；旋转由指向约束实时决定)。
    """
    letter = 'L' if hand == HandType.LEFT else 'R'
    specs = [(f"H_{letter}", True, False),
             (f"HP_{letter}", False, False),
             (f"T_{letter}", False, False)]
    for n in range(1, config.one_hand_finger_number + 1):
        specs.append((f"{n}_{letter}", False, False))
    if hand == HandType.RIGHT:
        specs.append(("String_Touch_Point", False, False))
        specs.append(("Bow_Controller", False, False))
    return specs


# ── 保存 / 加载 ──────────────────────────────────────────────


def save_hand_state(config, skeleton, hand: HandType, position_type,
                    string_index: int, fret_index: int = None) -> None:
    """保存指定手 + 状态到骨骼（数据键 = 短名，无后缀）。

    :param hand: HandType.LEFT / HandType.RIGHT
    :param position_type: LeftHandPositionType / RightHandPositionType 枚举
    :param string_index: 弦索引（左手 0/3；右手 0~3）
    :param fret_index: 品格索引（1/9/12），仅左手
    """
    state = _get_state(skeleton)
    side_key = "left_hand" if hand == HandType.LEFT else "right_hand"
    pos_key = position_type.value
    string_key = f"string_{string_index}"

    side = state.setdefault(side_key, {})
    if hand == HandType.LEFT:
        slot = (side.setdefault(string_key, {})
                .setdefault(f"fret_{fret_index}", {})
                .setdefault(pos_key, {}))
    else:
        slot = side.setdefault(string_key, {}).setdefault(pos_key, {})

    entries = {}
    for short, with_rotation, _evaluated in _controller_shorts(config, hand):
        obj = config.obj(short)
        if obj is None:
            print(f"  ✗ 控制器 {config.obj_name(short)} 不存在，跳过")
            continue
        entry = {"location": _location_of(obj)}
        if with_rotation:
            entry["rotation"] = _rotation_of(obj)
        entries[short] = entry

    slot.update(entries)
    _set_state(skeleton, state)

    print(f"已保存 {hand.value}手 {pos_key} 状态 "
          f"(string={string_index}"
          + (f", fret={fret_index}" if hand == HandType.LEFT else "")
          + f"，{len(entries)} 个控制器) → 骨骼 {STATE_KEY}")

    print(f"已保存 {hand.value}手 {pos_key} 状态 "
          f"(string={string_index}"
          + (f", fret={fret_index}" if hand == HandType.LEFT else "")
          + f"，{len(entries)} 个控制器) → 骨骼 {STATE_KEY}")


def load_hand_state(config, skeleton, hand: HandType, position_type,
                    string_index: int, fret_index: int = None) -> None:
    """从骨骼读取状态并应用到控制器（数据键 = 短名，无后缀）。"""
    state = _get_state(skeleton)
    side_key = "left_hand" if hand == HandType.LEFT else "right_hand"
    pos_key = position_type.value
    string_key = f"string_{string_index}"

    side = state.get(side_key, {})
    if hand == HandType.LEFT:
        slot = (side.get(string_key, {})
                .get(f"fret_{fret_index}", {})
                .get(pos_key, {}))
    else:
        slot = side.get(string_key, {}).get(pos_key, {})

    if not slot:
        print(f"  • 未找到已保存的 {side_key}/{string_key}/{pos_key} 状态（请先 Set）")
        return

    success_count = 0
    for short, _with_rotation, _evaluated in _controller_shorts(config, hand):
        entry = slot.get(short)
        obj = config.obj(short)
        if entry is None or obj is None:
            continue
        _apply_entry(obj, entry)
        success_count += 1

    print(f"已加载 {hand.value}手 {pos_key} 状态 "
          f"(string={string_index}"
          + (f", fret={fret_index}" if hand == HandType.LEFT else "")
          + f"，{success_count}/{len(_controller_shorts(config, hand))} 个控制器)")
