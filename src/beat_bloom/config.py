# beat_bloom/config.py
"""BeatBloom 乐器模块 —— 配置与控件创建

9 个控件：手掌 × 2、IK Pivot × 2、脚部 × 2、
特殊朝向（Middle_Hand / Look_At / Head_Control）× 3。
所有控件名带演奏者后缀（<短名>_<suffix>），通过 obj_name / obj 方法访问。
"""

import json

import bpy  # type: ignore

from ..common import performer_utils as _pu
from ..common import object_utils

from .enums import LIMB_CONTROLLERS


# 骨骼自定义属性键
DRUMKIT_KEY = "beat_bloom_drumkit_config"


class BeatBloomConfig:
    """BeatBloom 配置：命名表 + 控件创建 + setup（多演奏者命名空间）"""

    def __init__(self, performer_suffix: str = "",
                 target_skeleton=None):
        self.suffix: str = performer_suffix
        self.target_skeleton = target_skeleton
        self.instruments_name: str = "beat_bloom"

        self.hand_controllers = {
            "left_hand_controller":          "H_L",
            "right_hand_controller":         "H_R",
            "left_hand_ik_pivot":            "HP_L",
            "right_hand_ik_pivot":           "HP_R",
        }

        self.foot_controllers = {
            "left_foot_controller":          "F_L",
            "right_foot_controller":         "F_R",
        }

        # Middle_Hand 不挂根（用实时计算中点驱动位置），Look_At 挂 Middle_Hand，Head_Control 挂 TrackTo
        self.special_controllers = {
            "middle_hand":  "Middle_Hand",
            "look_at":      "Look_At",
            "head_control": "Head_Control",
        }

    # ── 命名辅助 ─────────────────────────────────────────────────

    def obj_name(self, short: str) -> str:
        """短名 → 完整对象名（带演奏者后缀）"""
        return _pu.resolve(short, self.suffix)

    def obj(self, short: str):
        """按短名取对象（带演奏者后缀）"""
        return bpy.data.objects.get(self.obj_name(short))

    def limb_controller_shorts(self, limb: str) -> list[str]:
        """肢体名 → 该肢体的控制器短名列表"""
        return LIMB_CONTROLLERS.get(limb, [])

    # ── Drumkit 配置读取 ─────────────────────────────────────────

    def drumkit_config(self) -> dict | None:
        """从骨骼自定义属性读取 drumkit 配置，返回 dict；缺失返回 None"""
        if self.target_skeleton is None:
            return None
        raw = self.target_skeleton.get(DRUMKIT_KEY)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_drumkit_config(self, drumkit_dict: dict) -> None:
        """将 drumkit 配置序列化写入骨骼自定义属性"""
        if self.target_skeleton is None:
            return
        self.target_skeleton[DRUMKIT_KEY] = json.dumps(
            drumkit_dict, ensure_ascii=False)

    # ── 控件创建 ─────────────────────────────────────────────────

    def setup_all_objects(self) -> None:
        """创建/更新 12 个控件并完成集合层级和特殊约束设置"""
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        addons_coll = performer_utils_find_addons(self.suffix)
        if addons_coll is None:
            print("[ERROR] 未找到 addons 目录，请先新建角色（初始化角色）。")
            return

        controllers_coll = object_utils.get_or_create_collection(
            _pu.resolve("Controllers", self.suffix), addons_coll)

        hand_coll = object_utils.get_or_create_collection(
            _pu.resolve("Hand_Controllers", self.suffix), controllers_coll)
        foot_coll = object_utils.get_or_create_collection(
            _pu.resolve("Foot_Controllers", self.suffix), controllers_coll)
        special_coll = object_utils.get_or_create_collection(
            _pu.resolve("Special_Controllers", self.suffix), controllers_coll)

        for short in self.hand_controllers.values():
            object_utils.create_or_update_object(
                self.obj_name(short), "cube", hand_coll)

        for short in self.foot_controllers.values():
            object_utils.create_or_update_object(
                self.obj_name(short), "cube", foot_coll)

        for short in self.special_controllers.values():
            object_utils.create_or_update_object(
                self.obj_name(short), "cube", special_coll)

        self._setup_special_constraints()
        print("✓ BeatBloom 控件已就绪")

    def _setup_special_constraints(self) -> None:
        """设置 Look_At 父子关系 + Head_Control TrackTo 约束"""
        middle = self.obj("Middle_Hand")
        look_at = self.obj("Look_At")
        head = self.obj("Head_Control")

        if not all([middle, look_at, head]):
            print("  ✗ 找不到特殊控制器对象，跳过约束设置")
            return

        # Look_At 挂到 Middle_Hand 下
        if look_at.parent != middle:
            look_at.parent = middle

        # Head_Control 清除旧约束并添加 TrackTo
        for c in list(head.constraints):
            head.constraints.remove(c)
        track = head.constraints.new('TRACK_TO')
        track.name = "Track_Look_At"
        track.target = look_at
        track.track_axis = 'TRACK_Z'
        track.up_axis = 'UP_Y'
        print("  ✓ 特殊朝向控制器约束已设置")


def performer_utils_find_addons(suffix: str):
    """获取演奏者的 addons 集合（无后缀时回退到全局 addons）"""
    if suffix:
        return _pu.find_addons_collection(suffix)
    return object_utils.get_or_create_collection("addons")
