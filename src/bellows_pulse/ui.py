# bellows_pulse/ui.py
"""BellowsPulse 乐器模块 —— 面板与算子

面板按「一步步填写」组织：

    ① 右手键区类型   → ② 右键区范围 → ③ 左键区范围 → ④ 键区物体 → ⑤ 保存

每一步下面的「→」行是**算出来的结果**（键数、音域、每排数量、每排功能），
让填写的人当场看出对不对；校验不通过时保存按钮直接拒绝。

无状态化：面板属性是编辑入口，数据源是演奏者骨骼上的 `bellows_pulse_settings`；
切换角色时从骨骼回填一次（不每帧覆盖，免得擦掉正在输入的值），
后续导出与动画一律读骨骼里已保存的值。
"""

import bpy  # type: ignore
from bpy.types import Panel, Operator, PropertyGroup  # type: ignore
from bpy.props import (  # type: ignore
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from ..common import ui_utils
from ..common import performer_utils
from ..common import instrument_base
from ..common import i18n
from ..common.tools import COMMON_TOOLS

from . import state
from .config import BellowsConfig
from .enums import (
    RIGHT_LAYOUT_BUTTONS,
    RIGHT_LAYOUT_KEYBOARD,
    keyboard_key_count,
    left_row_labels,
    note_range_text,
    right_button_count,
    right_button_pitch_range,
    right_row_key_counts,
)
from .tools import INSTRUMENT_TOOLS

T = i18n.T
bl_label_set = i18n.bl_label_set

#: 工具下拉 = 公共工具 + 本乐器独有工具（本轮独有工具为空）
TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS

#: 场景上的属性组名
_PROPS_ATTR = "md_bp_props"

#: 面板 ↔ 骨骼同步标记：(角色名, 骨骼名)。变了才从骨骼回填面板。
_SYNC_MARKER: dict = {"key": None}

#: 基准手型算子的左右手参数
_HAND_ITEMS = [('L', "左手", ""), ('R', "右手", "")]


# ── 当前演奏者 / 骨骼 / 乐器 ─────────────────────────────────

def _get_active_suffix(context) -> str:
    """当前角色名字（后缀已与名字合并）"""
    try:
        return ui_utils.get_active_suffix(context.scene)
    except Exception:
        return ""


def _get_active_skeleton(context):
    """当前目标骨骼：优先公共场景指针，其次选中的 ARMATURE"""
    skeleton = ui_utils.get_target_skeleton(context)
    if skeleton is not None:
        return skeleton
    for obj in context.selected_objects:
        if obj is not None and obj.type == "ARMATURE":
            return obj
    return None


def _get_active_instrument(context):
    """当前目标乐器（= 右键区 mesh）：优先公共场景指针，其次演奏者登记"""
    instrument = ui_utils.get_target_instrument(context)
    if instrument is not None:
        return instrument
    suffix = _get_active_suffix(context)
    if suffix:
        performer = performer_utils.get_performer(suffix)
        if performer is not None and performer.target_instrument is not None:
            return performer.target_instrument
    return None


def _get_config(context, suffix=None, skeleton=None) -> BellowsConfig:
    """按面板/骨骼构造配置（无状态：设置从骨骼读取，不缓存在场景里）"""
    return BellowsConfig(
        performer_suffix=_get_active_suffix(context) if suffix is None else suffix,
        target_skeleton=_get_active_skeleton(context) if skeleton is None else skeleton,
        target_instrument=_get_active_instrument(context),
    )


# ── 面板属性 ↔ 骨骼设置 ──────────────────────────────────────

def _props_to_settings(props, suffix: str = "") -> dict:
    """面板值 → 设置 dict（与导出用的结构一致）"""
    return {
        "version": 1,
        "right": {
            "layout": (RIGHT_LAYOUT_KEYBOARD if props.right_layout == 'KEYBOARD'
                       else RIGHT_LAYOUT_BUTTONS),
            "min_note": int(props.right_keyboard_min_note),
            "max_note": int(props.right_keyboard_max_note),
            "anchor_note": int(props.right_button_anchor_note),
            "first_row_keys": int(props.right_button_first_row_keys),
            "stagger": round(float(props.right_stagger), 4),
        },
        "left": {
            "rows": int(props.left_rows),
            "keys_per_row": int(props.left_keys_per_row),
            "first_main_bass": int(props.left_first_main_bass),
            "stagger": round(float(props.left_stagger), 4),
        },
        "left_instrument": state.short_name_of_object(
            props.left_instrument_obj, suffix),
    }


def _settings_to_props(props, settings: dict, suffix: str = "") -> None:
    """设置 dict → 面板值（切换角色 / 从骨骼重读时用）"""
    right = settings.get("right") or {}
    left = settings.get("left") or {}
    props.right_layout = ('BUTTONS' if right.get("layout") == RIGHT_LAYOUT_BUTTONS
                          else 'KEYBOARD')
    props.right_keyboard_min_note = int(right.get("min_note", 48))
    props.right_keyboard_max_note = int(right.get("max_note", 84))
    props.right_button_anchor_note = int(right.get("anchor_note", 48))
    props.right_button_first_row_keys = int(right.get("first_row_keys", 14))
    props.right_stagger = float(right.get("stagger", 0.5))
    props.left_rows = int(left.get("rows", 6))
    props.left_keys_per_row = int(left.get("keys_per_row", 20))
    props.left_first_main_bass = int(left.get("first_main_bass", 36))
    props.left_stagger = float(left.get("stagger", 0.5))
    props.left_instrument_obj = state.resolve_left_instrument(
        settings.get("left_instrument", ""), suffix)


def _sync_settings_from_skeleton(context, force: bool = False) -> None:
    """切换角色 / 骨骼时，从骨骼回填一次面板属性。

    同一角色下不每帧回填：否则会把正在输入的值擦掉。
    """
    skeleton = _get_active_skeleton(context)
    suffix = _get_active_suffix(context)
    marker = (suffix, skeleton.name if skeleton is not None else "")
    if not force and _SYNC_MARKER.get("key") == marker:
        return
    _SYNC_MARKER["key"] = marker
    props = getattr(context.scene, _PROPS_ATTR)
    _settings_to_props(props, state.load_settings(skeleton), suffix)


def _settings_dirty(context) -> bool:
    """面板值与骨骼里已保存的值是否不一致"""
    skeleton = _get_active_skeleton(context)
    if not state.has_settings(skeleton):
        return True
    stored = state.load_settings(skeleton)
    current = _props_to_settings(
        getattr(context.scene, _PROPS_ATTR), _get_active_suffix(context))
    return not state.settings_equal(stored, current)


def _write_left_instrument(context, settings: dict) -> None:
    """把左键区短名记到演奏者集合上（和公共的 md_instrument_obj 同一层）"""
    performer = performer_utils.get_performer(_get_active_suffix(context))
    if performer is None:
        return
    performer.collection["md_left_instrument"] = settings.get("left_instrument", "")


def _rebuild_after_copy(new_suffix: str, skeleton, report) -> None:
    """复制 / 重命名后的收尾：重建 ext 驱动、朝向链、演奏者根。

    `performer_utils.duplicate_collection_tree` 只重映射**约束器**与 **modifier**
    里的对象引用，**不重映射 driver**：副本的 Mid_Hand driver 还指着原角色的手。
    所以整条朝向链必须清掉重建，ext 的位置驱动同理。
    """
    try:
        config = BellowsConfig(performer_suffix=new_suffix,
                               target_skeleton=skeleton)
        config.add_ext_drivers()
        config._setup_special_controllers()
        config._organize_performer_root()
    except Exception as error:
        report({'WARNING'}, T("复制完成，但重建驱动与朝向链失败: %s") % str(error))
    _SYNC_MARKER["key"] = None


# ── 属性组 ────────────────────────────────────────────────────

class BellowsPulseProperties(PropertyGroup):
    """BellowsPulse 面板属性（编辑入口；数据源是演奏者骨骼）"""
    __annotations__ = {
        # ① 右手键区类型
        "right_layout": EnumProperty(
            name=T("右手键区类型"),
            description=T("手风琴右手是键盘还是按钮"),
            items=[('KEYBOARD', T("键盘"), T("钢琴式半音键盘")),
                   ('BUTTONS', T("按钮"), T("巴扬按钮键区（固定 5 排）"))],
            default='KEYBOARD'),

        # ② 右键区范围
        "right_keyboard_min_note": IntProperty(
            name=T("最低音"), description=T("右手键盘最低音的 midi 音高"),
            default=48, min=0, max=127),
        "right_keyboard_max_note": IntProperty(
            name=T("最高音"), description=T("右手键盘最高音的 midi 音高"),
            default=84, min=0, max=127),
        "right_button_anchor_note": IntProperty(
            name=T("第 3 排最低音"),
            description=T("右手按钮第 3 排（中间排）最低音的 midi 音高"),
            default=48, min=0, max=127),
        "right_button_first_row_keys": IntProperty(
            name=T("第 1/3/5 排按钮数"),
            description=T("第 2/4 排比这个数少一颗"),
            default=14, min=2, max=40),
        "right_stagger": FloatProperty(
            name=T("错排量"),
            description=T("相邻两排的横向错开量（钮距；带符号，左右手可能相反）"),
            default=0.5, min=-1.0, max=1.0, precision=3),

        # ③ 左键区范围
        "left_rows": IntProperty(
            name=T("排数"), description=T("左手按钮排数（3~6）"),
            default=6, min=3, max=6),
        "left_first_main_bass": IntProperty(
            name=T("第 2 排最低音"),
            description=T("左手第 2 排（主低音排）最低那颗按钮的 midi 音高"),
            default=36, min=0, max=127),
        "left_keys_per_row": IntProperty(
            name=T("每排按钮数"), description=T("左手每一排的按钮数量"),
            default=20, min=1, max=40),
        "left_stagger": FloatProperty(
            name=T("错排量"),
            description=T("相邻两排的横向错开量（钮距；带符号，左右手可能相反）"),
            default=0.5, min=-1.0, max=1.0, precision=3),

        # ④ 键区物体（右键区就是公共的「目标乐器」，这里只登记左键区）
        "left_instrument_obj": PointerProperty(
            name=T("左键区网格"),
            description=T("左键区（低音按钮区）的网格对象"),
            type=bpy.types.Object,
            poll=lambda self, obj: obj is not None and obj.type == 'MESH'),
    }


# ── 算子：控件与检查 ──────────────────────────────────────────

class BELLOWS_PULSE_OT_setup_objects(Operator):
    """创建/刷新手风琴控件与键区记录器（幂等）"""
    bl_idname = "music_doll.bellows_pulse_setup_objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        config = _get_config(context)
        if not config.setup_all_objects():
            self.report(
                {'ERROR'},
                T("设置失败：未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）"))
            return {'CANCELLED'}
        self.report({'INFO'}, T("控件已就绪，详见控制台"))
        return {'FINISHED'}


class BELLOWS_PULSE_OT_check_status(Operator):
    """检查控制器与键区记录器是否齐全"""
    bl_idname = "music_doll.bellows_pulse_check_status"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        skeleton = _get_active_skeleton(context)
        settings = (state.load_settings(skeleton)
                    if state.has_settings(skeleton) else None)
        _get_config(context).check_all_objects(settings)
        self.report({'INFO'}, T("Check complete. See console for details."))
        return {'FINISHED'}


# ── 算子：乐器属性保存 / 重读 ─────────────────────────────────

class BELLOWS_PULSE_OT_save_settings(Operator):
    """校验并保存乐器属性到演奏者骨骼"""
    bl_idname = "music_doll.bellows_pulse_save_settings"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        skeleton = _get_active_skeleton(context)
        if skeleton is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}

        suffix = _get_active_suffix(context)
        settings = _props_to_settings(
            getattr(context.scene, _PROPS_ATTR), suffix)

        errors = state.validate_settings(settings)
        if errors:
            message_key, message_args = errors[0]
            self.report({'ERROR'},
                        T(message_key) % message_args if message_args
                        else T(message_key))
            return {'CANCELLED'}

        if not state.save_settings(skeleton, settings):
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}
        _write_left_instrument(context, settings)
        _SYNC_MARKER["key"] = (suffix, skeleton.name)

        self.report({'INFO'}, T("乐器属性已保存到骨骼 %s") % skeleton.name)
        return {'FINISHED'}


class BELLOWS_PULSE_OT_reload_settings(Operator):
    """从骨骼重新读取乐器属性（放弃面板上未保存的修改）"""
    bl_idname = "music_doll.bellows_pulse_reload_settings"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _sync_settings_from_skeleton(context, force=True)
        self.report({'INFO'}, T("已从骨骼重新读取乐器属性"))
        return {'FINISHED'}


# ── 算子：基准手型（动画用）──────────────────────────────────

class BELLOWS_PULSE_OT_save_reference_hand(Operator):
    """把当前一只手的控制器位姿存成基准手型"""
    bl_idname = "music_doll.bellows_pulse_save_reference_hand"
    bl_options = {'REGISTER', 'UNDO'}
    __annotations__ = {
        "hand": EnumProperty(items=_HAND_ITEMS, default='L'),
    }

    def execute(self, context):
        skeleton = _get_active_skeleton(context)
        if skeleton is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}

        config = _get_config(context, skeleton=skeleton)
        count = state.save_reference_hand(config, skeleton, self.hand)
        if count <= 0:
            self.report(
                {'ERROR'}, T("没有找到这只手的控制器，请先「设置所有对象」"))
            return {'CANCELLED'}

        hand_label = T("左手") if self.hand == 'L' else T("右手")
        self.report({'INFO'}, T("基准手型已保存：%s（%d 个控制器）")
                    % (hand_label, count))
        return {'FINISHED'}


class BELLOWS_PULSE_OT_load_reference_hand(Operator):
    """把骨骼里保存的基准手型应用到一只手的控制器"""
    bl_idname = "music_doll.bellows_pulse_load_reference_hand"
    bl_options = {'REGISTER', 'UNDO'}
    __annotations__ = {
        "hand": EnumProperty(items=_HAND_ITEMS, default='L'),
    }

    def execute(self, context):
        skeleton = _get_active_skeleton(context)
        if skeleton is None:
            self.report({'ERROR'}, T("请先选择目标骨骼"))
            return {'CANCELLED'}

        config = _get_config(context, skeleton=skeleton)
        try:
            count = state.load_reference_hand(config, skeleton, self.hand)
        except ValueError:
            self.report(
                {'ERROR'}, T("骨骼上还没有这只手的基准手型，请先保存"))
            return {'CANCELLED'}

        hand_label = T("左手") if self.hand == 'L' else T("右手")
        self.report({'INFO'}, T("基准手型已加载：%s（%d 个控制器）")
                    % (hand_label, count))
        return {'FINISHED'}


# ── 算子：复制 / 重命名角色 ──────────────────────────────────

class BELLOWS_PULSE_OT_duplicate_performer(Operator):
    """复制当前角色，生成一个新角色（输入新名字）"""
    bl_idname = "music_doll.bellows_pulse_duplicate_performer"
    bl_label = T("复制角色")
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(default="", name=T("新名字"))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        suffix = _get_active_suffix(context)
        if not suffix:
            self.report({'ERROR'}, T("请先在下拉框选中要复制的角色"))
            return {'CANCELLED'}
        source = performer_utils.get_performer(suffix)
        if source is None:
            self.report(
                {'ERROR'}, T("找不到已登记的角色 %s（请先初始化该角色）") % suffix)
            return {'CANCELLED'}

        new_name = (self.new_name or "").strip()
        if not new_name:
            self.report({'ERROR'}, T("请输入新名字"))
            return {'CANCELLED'}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report(
                {'ERROR'}, T("名字只能使用英文字母和数字（如 Ayaka / Player01），不能包含中文"))
            return {'CANCELLED'}
        if performer_utils.has_performer(new_name):
            self.report({'ERROR'}, T("已存在名字 %s，请换一个") % new_name)
            return {'CANCELLED'}

        try:
            duplicated = performer_utils.duplicate_collection_tree(
                source.collection)
        except Exception as error:
            self.report({'ERROR'}, T("复制集合失败: %s") % str(error))
            return {'CANCELLED'}
        if duplicated is None:
            self.report({'ERROR'}, T("复制集合失败（未能生成副本）"))
            return {'CANCELLED'}

        # 补上源名字/乐器元信息，让 resuffix 知道要替换什么
        instrument_base.set_coll_attr(duplicated, "name", source.name)
        instrument_base.set_coll_attr(
            duplicated, "instrument", source.instrument)

        new_performer = performer_utils.resuffix_performer(
            duplicated, new_name, new_name=new_name)

        _rebuild_after_copy(new_name, new_performer.target_skeleton, self.report)
        self.report({'INFO'}, T("已复制角色为 %s") % new_name)
        return {'FINISHED'}


class BELLOWS_PULSE_OT_rename_performer(Operator):
    """重命名当前角色：原地改名字（名字即命名空间后缀），不生成新角色"""
    bl_idname = "music_doll.bellows_pulse_rename_performer"
    bl_label = T("重命名当前角色")
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(default="", name=T("新名字"))

    def invoke(self, context, event):
        source = ui_utils.get_rename_target(context)
        # 旧值非 ASCII（如被 Blender 中文编码问题弄乱）时不预填，让用户重新输入
        if source is not None and source.name and source.name.isascii():
            self.new_name = source.name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        scene = context.scene
        source = ui_utils.get_rename_target(context)
        if source is None:
            self.report(
                {'ERROR'}, T("找不到当前角色（请先在下拉框选中，或指定其骨骼/乐器）"))
            return {'CANCELLED'}

        new_name = (self.new_name or "").strip()
        if not new_name:
            self.report({'ERROR'}, T("请输入新名字"))
            return {'CANCELLED'}
        if not (new_name.isascii() and new_name.isalnum() and new_name[0].isalpha()):
            self.report(
                {'ERROR'}, T("名字只能使用英文字母和数字（如 Ayaka / Player01），不能包含中文"))
            return {'CANCELLED'}
        if new_name == source.name:
            self.report({'ERROR'}, T("新名字与当前相同（%s），无需重命名") % new_name)
            return {'CANCELLED'}
        if performer_utils.has_performer(new_name):
            self.report({'ERROR'}, T("已存在名字 %s，请换一个") % new_name)
            return {'CANCELLED'}

        try:
            new_performer = performer_utils.resuffix_performer(
                source.collection, new_name, new_name=new_name)
        except Exception as error:
            self.report({'ERROR'}, T("重命名失败: %s") % str(error))
            return {'CANCELLED'}

        _rebuild_after_copy(new_name, new_performer.target_skeleton, self.report)

        # 把当前角色切到新名字
        try:
            setattr(scene, ui_utils.SCENE_ACTIVE_PERFORMER, new_name)
        except Exception:
            pass

        self.report({'INFO'}, T("已将角色重命名为 %s") % new_name)
        return {'FINISHED'}


# ── 面板 ──────────────────────────────────────────────────────

class BELLOWS_PULSE_PT_main_panel(Panel):
    """BellowsPulse 乐器子面板（挂在 MusicDoll 统一主面板下，按乐器类型显示）"""
    bl_label = T("BellowsPulse")
    bl_idname = "BELLOWS_PULSE_PT_main_panel"
    bl_parent_id = "MUSICDOLL_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MusicDoll"

    @classmethod
    def poll(cls, context):
        return ui_utils.active_instrument(context) == "bellows_pulse"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = getattr(scene, _PROPS_ATTR)
        _sync_settings_from_skeleton(context)

        skeleton = _get_active_skeleton(context)
        suffix = _get_active_suffix(context)
        settings = _props_to_settings(props, suffix)

        self._draw_right_layout(layout, props)
        self._draw_right_range(layout, props)
        self._draw_left_range(layout, props)
        self._draw_key_zone_objects(layout, context, props)
        self._draw_save(layout, context, skeleton, settings)

        # 控件与记录器
        box = layout.box()
        box.label(text=T("控件与记录器"), icon='TOOL_SETTINGS')
        row = box.row(align=True)
        row.operator("music_doll.bellows_pulse_setup_objects",
                     text=T("设置所有对象"), icon='OBJECT_DATA')
        row.operator("music_doll.bellows_pulse_check_status",
                     text=T("检查状态"), icon='CHECKMARK')
        box.label(text=T("记录器按已保存的右手类型创建：键盘 4 + 左 3，或按钮 6 + 左 3"),
                  icon='INFO')
        box.label(text=T("切换右手类型后请重新「设置所有对象」，另一套记录器会被删除"))

        # 工具（公共工具 + 本乐器独有工具）
        ui_utils.draw_tools(layout, scene, tools=TOOLS)

        self._draw_reference_hand(layout, skeleton)

    # ── ① 右手键区类型 ──
    def _draw_right_layout(self, layout, props):
        box = layout.box()
        box.label(text=T("① 右手键区类型"), icon='TRIA_RIGHT')
        box.row().prop(props, "right_layout", expand=True)

    # ── ② 右键区范围 ──
    def _draw_right_range(self, layout, props):
        box = layout.box()
        box.label(text=T("② 右键区范围"), icon='TRIA_RIGHT')

        if props.right_layout == 'KEYBOARD':
            column = box.column(align=True)
            column.prop(props, "right_keyboard_min_note")
            column.prop(props, "right_keyboard_max_note")

            key_count = keyboard_key_count(
                props.right_keyboard_min_note, props.right_keyboard_max_note)
            range_text = note_range_text(
                props.right_keyboard_min_note, props.right_keyboard_max_note)
            box.label(text=T("→ %d 个键，%s") % (key_count, range_text),
                      icon='INFO')
            return

        column = box.column(align=True)
        column.prop(props, "right_button_anchor_note")
        column.prop(props, "right_button_first_row_keys")
        column.prop(props, "right_stagger")

        first_row_keys = int(props.right_button_first_row_keys)
        counts = right_row_key_counts(first_row_keys)
        box.label(
            text=T("→ 每排 %s，共 %d 颗")
            % (" / ".join(str(count) for count in counts),
               right_button_count(first_row_keys)),
            icon='INFO')
        lowest_note, highest_note = right_button_pitch_range(
            props.right_button_anchor_note, first_row_keys)
        box.label(
            text=T("→ 音域 %s（第 1 排最低音到第 3 排最高音）")
            % note_range_text(lowest_note, highest_note),
            icon='INFO')

    # ── ③ 左键区范围 ──
    def _draw_left_range(self, layout, props):
        box = layout.box()
        box.label(text=T("③ 左键区范围"), icon='TRIA_RIGHT')
        column = box.column(align=True)
        column.prop(props, "left_rows")
        column.prop(props, "left_first_main_bass")
        column.prop(props, "left_keys_per_row")
        column.prop(props, "left_stagger")

        total_count = int(props.left_rows) * int(props.left_keys_per_row)
        row_text = "、".join(
            f"{row_index} {T(row_label)}"
            for row_index, row_label in enumerate(left_row_labels(props.left_rows), start=1))
        box.label(text=T("→ %d 颗按钮；每排：%s") % (total_count, row_text),
                  icon='INFO')

    # ── ④ 键区物体 ──
    def _draw_key_zone_objects(self, layout, context, props):
        box = layout.box()
        box.label(text=T("④ 键区物体"), icon='TRIA_RIGHT')
        column = box.column(align=True)
        instrument = _get_active_instrument(context)
        instrument_name = instrument.name if instrument is not None else T("（未设置）")
        column.label(text=f"{T('右键区（= 目标乐器）')}: {instrument_name}")
        column.prop(props, "left_instrument_obj", text=T("左键区网格"))

    # ── ⑤ 保存 ──
    def _draw_save(self, layout, context, skeleton, settings):
        box = layout.box()
        box.label(text=T("⑤ 保存"), icon='TRIA_RIGHT')
        row = box.row(align=True)
        row.operator("music_doll.bellows_pulse_save_settings",
                     text=T("保存乐器属性到骨骼"), icon='IMPORT')
        row.operator("music_doll.bellows_pulse_reload_settings",
                     text=T("从骨骼重新读取"), icon='FILE_REFRESH')

        errors = state.validate_settings(settings)
        for message_key, message_args in errors[:3]:
            box.label(text=T(message_key) % message_args if message_args
                      else T(message_key), icon='ERROR')

        if not state.has_settings(skeleton):
            box.label(text=T("状态：骨骼上还没有保存过设置"), icon='INFO')
        elif _settings_dirty(context):
            box.label(text=T("状态：有未保存的修改"), icon='ERROR')
        else:
            box.label(text=T("状态：已保存"), icon='CHECKMARK')

    # ── 基准手型 ──
    def _draw_reference_hand(self, layout, skeleton):
        box = layout.box()
        box.label(text=T("基准手型（动画用）"), icon='ARMATURE_DATA')
        for hand, hand_label in (("L", T("左手")), ("R", T("右手"))):
            row = box.row(align=True)
            row.label(text=hand_label)
            save_op = row.operator(
                "music_doll.bellows_pulse_save_reference_hand", text=T("保存"))
            save_op.hand = hand
            load_op = row.operator(
                "music_doll.bellows_pulse_load_reference_hand", text=T("加载"))
            load_op.hand = hand
            if state.reference_hand_saved(skeleton, hand):
                row.label(text=T("已保存"), icon='CHECKMARK')
            else:
                row.label(text=T("未保存"), icon='INFO')
        box.label(text=T("手掌存位置 + 旋转，五指存位置；ext 与朝向链由驱动/约束决定"),
                  icon='INFO')


# ── 注册 / 注销 ──────────────────────────────────────────────

_CLASSES = (
    BELLOWS_PULSE_OT_setup_objects,
    BELLOWS_PULSE_OT_check_status,
    BELLOWS_PULSE_OT_save_settings,
    BELLOWS_PULSE_OT_reload_settings,
    BELLOWS_PULSE_OT_save_reference_hand,
    BELLOWS_PULSE_OT_load_reference_hand,
    BELLOWS_PULSE_OT_duplicate_performer,
    BELLOWS_PULSE_OT_rename_performer,
    BELLOWS_PULSE_PT_main_panel,
)

#: 注册前用 bl_label_set 写入的翻译标签（必须早于 register_class）
_CLASS_LABELS = {
    BELLOWS_PULSE_OT_setup_objects: "设置所有对象",
    BELLOWS_PULSE_OT_check_status: "检查状态",
    BELLOWS_PULSE_OT_save_settings: "保存乐器属性到骨骼",
    BELLOWS_PULSE_OT_reload_settings: "从骨骼重新读取",
    BELLOWS_PULSE_OT_save_reference_hand: "保存基准手型",
    BELLOWS_PULSE_OT_load_reference_hand: "加载基准手型",
    BELLOWS_PULSE_OT_duplicate_performer: "复制角色",
    BELLOWS_PULSE_OT_rename_performer: "重命名当前角色",
    BELLOWS_PULSE_PT_main_panel: "BellowsPulse",
}


def register():
    bpy.utils.register_class(BellowsPulseProperties)
    setattr(bpy.types.Scene, _PROPS_ATTR,
            PointerProperty(type=BellowsPulseProperties))

    for operator_class in _CLASSES:
        label_key = _CLASS_LABELS.get(operator_class)
        if label_key:
            bl_label_set(operator_class, label_key)
        bpy.utils.register_class(operator_class)

    # 注册本乐器工具模块（本轮没有独有算子，只接通下拉）
    from .tools import register as register_tools
    register_tools()

    # 登记本乐器 UI（角色生成器下拉 + 角色操作器接入）
    ui_utils.register_instrument(
        "bellows_pulse", T("BellowsPulse 手风琴"), BELLOWS_PULSE_PT_main_panel,
        rename_operator="music_doll.bellows_pulse_rename_performer",
        duplicate_operator="music_doll.bellows_pulse_duplicate_performer")


def unregister():
    from .tools import unregister as unregister_tools
    unregister_tools()

    ui_utils.unregister_instrument("bellows_pulse")

    for operator_class in reversed(_CLASSES):
        bpy.utils.unregister_class(operator_class)

    if hasattr(bpy.types.Scene, _PROPS_ATTR):
        delattr(bpy.types.Scene, _PROPS_ATTR)
    bpy.utils.unregister_class(BellowsPulseProperties)

    _SYNC_MARKER["key"] = None
