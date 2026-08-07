# key_ripple/ui.py
"""KeyRipple 乐器模块 —— 面板与算子（迁移自 key_ripple_blender/__init__.py）

- 去掉全局缓存实例，改为无状态化：配置从骨骼读取、面板为编辑入口（提交时写回骨骼）；
- 公共演奏者选择/骨骼/乐器/路径改调 common.ui_utils；
- 工具下拉 = 公共工具 + KeyRipple 独有工具。
"""

import os

import bpy  # type: ignore
from bpy.types import Panel, Operator, PropertyGroup  # type: ignore
from bpy.props import (  # type: ignore
    IntProperty,
    StringProperty,
    PointerProperty,
    EnumProperty,
)

from ..common import ui_utils
from ..common import performer_utils
from ..common.tools import COMMON_TOOLS
from .config import KeyRipple, HandType, KeyType, PositionType
from .state import save_state, load_state
from .io import export_avatar, import_avatar
from .animation import make_animation_from_keyripple
from .tools import INSTRUMENT_TOOLS


# 该乐器的工具列表 = 公共工具 + 乐器独有工具
TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS

# 配置存骨骼的自定义属性键
_CONFIG_KEY = "key_ripple_config"


# ── 配置读取/写回（无状态化） ────────────────────────────────

def _load_config_from_skeleton(skeleton) -> dict:
    """从骨骼读取 KeyRipple 初始化配置（缺省用默认值）"""
    defaults = {
        "one_hand_finger_number": 5,
        "leftest_position": 28,
        "left_position": 40,
        "middle_left_position": 52,
        "middle_right_position": 76,
        "right_position": 88,
        "rightest_position": 100,
        "min_key": 21,
        "max_key": 108,
        "hand_range": 12,
    }
    if skeleton is None:
        return defaults
    data = skeleton.get(_CONFIG_KEY)
    if not data:
        return defaults
    import json
    try:
        stored = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return defaults
    merged = dict(defaults)
    merged.update({k: v for k, v in stored.items() if k in defaults})
    return merged


def _save_config_to_skeleton(skeleton, config: dict) -> None:
    """把 KeyRipple 初始化配置写回骨骼"""
    if skeleton is None:
        return
    import json
    skeleton[_CONFIG_KEY] = json.dumps(config, ensure_ascii=False)


def _get_key_ripple(props, suffix="", skeleton=None):
    """按面板/骨骼构造 KeyRipple 实例（无状态：配置可从骨骼读取）"""
    config = _load_config_from_skeleton(skeleton)
    return KeyRipple(
        config["one_hand_finger_number"],
        config["leftest_position"],
        config["left_position"],
        config["middle_left_position"],
        config["middle_right_position"],
        config["right_position"],
        config["rightest_position"],
        config["min_key"],
        config["max_key"],
        config["hand_range"],
        performer_suffix=suffix,
        target_skeleton=skeleton,
    )


# ── 演奏者/骨骼辅助 ──────────────────────────────────────────

def _get_active_suffix(context):
    """当前演奏者后缀：公共下拉框选中优先，其次公共后缀输入框"""
    scene = context.scene
    active = getattr(scene, ui_utils.SCENE_ACTIVE_PERFORMER, "")
    if active:
        return active
    return getattr(scene, "md_performer_suffix", "")


def _get_active_skeleton(context):
    """当前目标骨骼：优先公共场景指针，其次选中的 ARMATURE"""
    scene = context.scene
    skel = ui_utils.get_target_skeleton(context)
    if skel:
        return skel
    for obj in context.selected_objects:
        if obj is not None and obj.type == "ARMATURE":
            return obj
    return None


def _get_active_instrument(context):
    """当前目标乐器：优先公共场景指针，其次当前演奏者登记的乐器"""
    scene = context.scene
    inst = ui_utils.get_target_instrument(context)
    if inst:
        return inst
    suffix = _get_active_suffix(context)
    if suffix:
        p = performer_utils.get_performer(suffix)
        if p is not None and p.target_instrument is not None:
            return p.target_instrument
    return None


def _sync_config_from_skeleton(context):
    """把骨骼上的配置回填到面板属性（无状态化）"""
    scene = context.scene
    skel = _get_active_skeleton(context)
    props = scene.keyripple_props
    config = _load_config_from_skeleton(skel)
    for key, value in config.items():
        if hasattr(props, key):
            setattr(props, key, value)


# ── 属性组 ────────────────────────────────────────────────────

class KeyRippleProperties(PropertyGroup):
    """KeyRipple 面板属性（编辑入口；提交时写回骨骼）"""
    __annotations__ = {
        "one_hand_finger_number": IntProperty(
            name="Finger Number", description="Number of fingers per hand",
            default=5, min=1, max=10),
        "leftest_position": IntProperty(
            name="Leftest Position", description="Leftmost position",
            default=28, min=0),
        "left_position": IntProperty(
            name="Left Position", description="Left position",
            default=40, min=0),
        "middle_left_position": IntProperty(
            name="Middle Left Position", description="Middle left position",
            default=52, min=0),
        "middle_right_position": IntProperty(
            name="Middle Right Position", description="Middle right position",
            default=76, min=0),
        "right_position": IntProperty(
            name="Right Position", description="Right position",
            default=88, min=0),
        "rightest_position": IntProperty(
            name="Rightest Position", description="Rightmost position",
            default=100, min=0),
        "min_key": IntProperty(
            name="Min Key", description="Lowest key on the piano",
            default=21, min=0),
        "max_key": IntProperty(
            name="Max Key", description="Highest key on the piano",
            default=108, min=0),
        "hand_range": IntProperty(
            name="Hand Range", description="the range of hand",
            default=12, min=10),

        # 左手状态
        "left_hand_key_type": EnumProperty(
            name="Left Hand Key Type", description="Key type for left hand",
            items=[('WHITE', "White Key", "White key"),
                   ('BLACK', "Black Key", "Black key")],
            default='WHITE'),
        "left_hand_position_type": EnumProperty(
            name="Left Hand Position Type", description="Position type for left hand",
            items=[('HIGH', "High", "High position"),
                   ('LOW', "Low", "Low position"),
                   ('MIDDLE', "Middle", "Middle position")],
            default='HIGH'),

        # 右手状态
        "right_hand_key_type": EnumProperty(
            name="Right Hand Key Type", description="Key type for right hand",
            items=[('WHITE', "White Key", "White key"),
                   ('BLACK', "Black Key", "Black key")],
            default='WHITE'),
        "right_hand_position_type": EnumProperty(
            name="Right Hand Position Type", description="Position type for right hand",
            items=[('HIGH', "High", "High position"),
                   ('LOW', "Low", "Low position"),
                   ('MIDDLE', "Middle", "Middle position")],
            default='HIGH'),

        # 键盘物体（钢琴键动画目标）
        "keyboard_object": PointerProperty(
            name="键盘物体",
            description="场景中代表键盘的物体（用于钢琴键动画）",
            type=bpy.types.Object,
            poll=lambda self, obj: obj is not None and obj.type == "MESH"),

        # 导入导出文件路径
        "io_file_path": StringProperty(
            name="File Path",
            description="Path for import/export avatar data",
            default="", subtype='FILE_PATH'),

        # .keyripple文件路径
        "keyripple_file_path": StringProperty(
            name="KeyRipple File",
            description="Path to .keyripple file",
            default="", subtype='FILE_PATH'),
    }


# ── 算子 ──────────────────────────────────────────────────────

class KEYRIPPLE_OT_check_status(Operator):
    bl_idname = "music_doll.key_ripple_check_status"
    bl_label = "Check Objects Status"
    bl_description = "Check the status of all KeyRipple objects"

    def execute(self, context):
        skel = _get_active_skeleton(context)
        key_ripple = _get_key_ripple(
            context.scene.keyripple_props, suffix=_get_active_suffix(context),
            skeleton=skel)
        key_ripple.check_objects_status()
        return {'FINISHED'}


class KEYRIPPLE_OT_setup_objects(Operator):
    bl_idname = "music_doll.key_ripple_setup_objects"
    bl_label = "Setup All Objects"
    bl_description = "Create all KeyRipple controllers"

    def execute(self, context):
        scene = context.scene
        skel = _get_active_skeleton(context)
        suffix = _get_active_suffix(context)
        # 无状态化：面板是编辑入口，提交时把配置写回骨骼
        props = scene.keyripple_props
        config = {
            "one_hand_finger_number": props.one_hand_finger_number,
            "leftest_position": props.leftest_position,
            "left_position": props.left_position,
            "middle_left_position": props.middle_left_position,
            "middle_right_position": props.middle_right_position,
            "right_position": props.right_position,
            "rightest_position": props.rightest_position,
            "min_key": props.min_key,
            "max_key": props.max_key,
            "hand_range": props.hand_range,
        }
        _save_config_to_skeleton(skel, config)
        key_ripple = _get_key_ripple(
            props, suffix=suffix, skeleton=skel)
        key_ripple.setup_all_objects()
        return {'FINISHED'}


class KEYRIPPLE_OT_save_state(Operator):
    bl_idname = "music_doll.key_ripple_save_state"
    bl_label = "Save State"
    bl_description = "Save all controller states to performer skeleton custom properties"

    def execute(self, context):
        props = context.scene.keyripple_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        key_ripple = _get_key_ripple(
            props, suffix=_get_active_suffix(context), skeleton=skel)

        left_key_type = KeyType.WHITE if props.left_hand_key_type == 'WHITE' else KeyType.BLACK
        left_position_type = PositionType.HIGH if props.left_hand_position_type == 'HIGH' else \
            PositionType.LOW if props.left_hand_position_type == 'LOW' else PositionType.MIDDLE
        right_key_type = KeyType.WHITE if props.right_hand_key_type == 'WHITE' else KeyType.BLACK
        right_position_type = PositionType.HIGH if props.right_hand_position_type == 'HIGH' else \
            PositionType.LOW if props.right_hand_position_type == 'LOW' else PositionType.MIDDLE

        save_state(key_ripple, skel, HandType.LEFT,
                   left_key_type, left_position_type)
        save_state(key_ripple, skel, HandType.RIGHT,
                   right_key_type, right_position_type)

        self.report(
            {"INFO"}, f"状态已保存: 左{left_position_type.value}/{left_key_type.value} 右{right_position_type.value}/{right_key_type.value}")
        return {'FINISHED'}


class KEYRIPPLE_OT_load_state(Operator):
    bl_idname = "music_doll.key_ripple_load_state"
    bl_label = "Load State"
    bl_description = "Load hand states from performer skeleton custom properties"

    def execute(self, context):
        props = context.scene.keyripple_props
        skel = _get_active_skeleton(context)
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        key_ripple = _get_key_ripple(
            props, suffix=_get_active_suffix(context), skeleton=skel)

        left_key_type = KeyType.WHITE if props.left_hand_key_type == 'WHITE' else KeyType.BLACK
        left_position_type = PositionType.HIGH if props.left_hand_position_type == 'HIGH' else \
            PositionType.LOW if props.left_hand_position_type == 'LOW' else PositionType.MIDDLE
        right_key_type = KeyType.WHITE if props.right_hand_key_type == 'WHITE' else KeyType.BLACK
        right_position_type = PositionType.HIGH if props.right_hand_position_type == 'HIGH' else \
            PositionType.LOW if props.right_hand_position_type == 'LOW' else PositionType.MIDDLE

        try:
            load_state(key_ripple, skel, HandType.LEFT,
                       left_key_type, left_position_type)
            load_state(key_ripple, skel, HandType.RIGHT,
                       right_key_type, right_position_type)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        self.report(
            {"INFO"}, f"状态已加载: 左{left_position_type.value}/{left_key_type.value} 右{right_position_type.value}/{right_key_type.value}")
        return {'FINISHED'}


class KEYRIPPLE_OT_export_avatar(Operator):
    bl_idname = "music_doll.key_ripple_export_avatar"
    bl_label = "Export Avatar"
    bl_description = "Export all state data to .avatar file"

    def execute(self, context):
        props = context.scene.keyripple_props
        skel = _get_active_skeleton(context)
        if not props.io_file_path:
            self.report({'ERROR'}, "Please select file path")
            return {'CANCELLED'}
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        key_ripple = _get_key_ripple(
            props, suffix=_get_active_suffix(context), skeleton=skel)

        file_path = props.io_file_path
        export_avatar(file_path, key_ripple, skel)
        self.report(
            {'INFO'}, f"Avatar exported successfully to {file_path}")
        return {'FINISHED'}


class KEYRIPPLE_OT_import_avatar(Operator):
    bl_idname = "music_doll.key_ripple_import_avatar"
    bl_label = "Import Avatar"
    bl_description = "Import all state data from .avatar file"

    def execute(self, context):
        props = context.scene.keyripple_props
        skel = _get_active_skeleton(context)
        if not props.io_file_path:
            self.report({'ERROR'}, "Please select file path")
            return {'CANCELLED'}
        if skel is None:
            self.report({'ERROR'}, "请先选择目标骨骼")
            return {'CANCELLED'}
        key_ripple = _get_key_ripple(
            props, suffix=_get_active_suffix(context), skeleton=skel)

        file_path = props.io_file_path
        success = import_avatar(file_path, key_ripple, skel)
        if success:
            self.report(
                {'INFO'}, f"Avatar imported successfully from {file_path}")
            return {'FINISHED'}
        else:
            self.report(
                {'ERROR'}, f"Failed to import avatar from {file_path}")
            return {'CANCELLED'}


class KEYRIPPLE_OT_generate_animation(Operator):
    bl_idname = "music_doll.key_ripple_generate_animation"
    bl_label = "Generate Animation"
    bl_description = "Generate animation from .keyripple file"

    def execute(self, context):
        props = context.scene.keyripple_props
        suffix = _get_active_suffix(context)

        if not props.keyripple_file_path:
            self.report({'ERROR'}, "Please select .keyripple file")
            return {'CANCELLED'}

        file_path = props.keyripple_file_path
        if not file_path.endswith('.keyripple'):
            self.report({'ERROR'}, "Selected file is not a .keyripple file")
            return {'CANCELLED'}

        if not os.path.exists(file_path):
            self.report({'ERROR'}, f"File not found: {file_path}")
            return {'CANCELLED'}

        keyboard_obj_name = props.keyboard_object.name if props.keyboard_object else 'keyboard'

        try:
            make_animation_from_keyripple(
                file_path, keyboard_obj_name, suffix=suffix)
            self.report(
                {'INFO'}, f"Animation generated successfully from {file_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to generate animation: {str(e)}")
            return {'CANCELLED'}


# ── 面板 ──────────────────────────────────────────────────────

class KEYRIPPLE_PT_main_panel(Panel):
    bl_label = "KeyRipple"
    bl_idname = "KEYRIPPLE_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MusicDoll"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.keyripple_props

        # 公共演奏者选择区
        ui_utils.draw_performer_selector(layout, scene)

        # 初始化区
        box = layout.box()
        box.label(text="Initialization", icon='SETTINGS')
        col = box.column(align=True)
        col.prop(props, "one_hand_finger_number")
        col.prop(props, "leftest_position")
        col.prop(props, "left_position")
        col.prop(props, "middle_left_position")
        col.prop(props, "middle_right_position")
        col.prop(props, "right_position")
        col.prop(props, "rightest_position")
        col.prop(props, "min_key")
        col.prop(props, "max_key")
        col.prop(props, "hand_range")

        row = box.row(align=True)
        row.operator("music_doll.key_ripple_check_status")
        row.operator("music_doll.key_ripple_setup_objects")

        # 工具区（公共工具 + KeyRipple 独有工具）
        ui_utils.draw_tools(layout, scene, tools=TOOLS)

        # 左手状态选择区
        box = layout.box()
        box.label(text="Left Hand State", icon='TRIA_LEFT')
        box.prop(props, "left_hand_key_type")
        box.prop(props, "left_hand_position_type")

        # 右手状态选择区
        box = layout.box()
        box.label(text="Right Hand State", icon='TRIA_RIGHT')
        box.prop(props, "right_hand_key_type")
        box.prop(props, "right_hand_position_type")

        # 信息记录/加载区
        box = layout.box()
        box.label(text="Hand State Transfer", icon='FILE_REFRESH')
        box.prop(props, "keyboard_object", text="键盘")
        row = box.row(align=True)
        row.operator("music_doll.key_ripple_save_state",
                     text="Set", icon='IMPORT')
        row.operator("music_doll.key_ripple_load_state",
                     text="Load", icon='EXPORT')

        # 全部信息导入导出区
        box = layout.box()
        box.label(text="Avatar I/O", icon='FILE')
        box.prop(props, "io_file_path", text="")
        row = box.row(align=True)
        row.operator("music_doll.key_ripple_export_avatar",
                     text="Export", icon='EXPORT')
        row.operator("music_doll.key_ripple_import_avatar",
                     text="Import", icon='IMPORT')

        # 动画生成区
        box = layout.box()
        box.label(text="Animation Generation", icon='PLAY')
        box.prop(props, "keyripple_file_path", text="")
        row = box.row(align=True)
        row.operator("music_doll.key_ripple_generate_animation",
                     text="Generate Animation", icon='PLAY')


# ── 注册/注销 ──────────────────────────────────────────────────

def register():
    bpy.utils.register_class(KeyRippleProperties)
    bpy.types.Scene.keyripple_props = PointerProperty(type=KeyRippleProperties)

    bpy.utils.register_class(KEYRIPPLE_OT_check_status)
    bpy.utils.register_class(KEYRIPPLE_OT_setup_objects)
    bpy.utils.register_class(KEYRIPPLE_OT_save_state)
    bpy.utils.register_class(KEYRIPPLE_OT_load_state)
    bpy.utils.register_class(KEYRIPPLE_OT_export_avatar)
    bpy.utils.register_class(KEYRIPPLE_OT_import_avatar)
    bpy.utils.register_class(KEYRIPPLE_OT_generate_animation)
    bpy.utils.register_class(KEYRIPPLE_PT_main_panel)

    # 注册本乐器工具模块（执行算子）
    from .tools import register as register_tools
    register_tools()


def unregister():
    from .tools import unregister as unregister_tools
    unregister_tools()

    bpy.utils.unregister_class(KEYRIPPLE_PT_main_panel)
    bpy.utils.unregister_class(KEYRIPPLE_OT_generate_animation)
    bpy.utils.unregister_class(KEYRIPPLE_OT_import_avatar)
    bpy.utils.unregister_class(KEYRIPPLE_OT_export_avatar)
    bpy.utils.unregister_class(KEYRIPPLE_OT_load_state)
    bpy.utils.unregister_class(KEYRIPPLE_OT_save_state)
    bpy.utils.unregister_class(KEYRIPPLE_OT_setup_objects)
    bpy.utils.unregister_class(KEYRIPPLE_OT_check_status)

    del bpy.types.Scene.keyripple_props
    bpy.utils.unregister_class(KeyRippleProperties)
