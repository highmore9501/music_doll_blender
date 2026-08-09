# common/tools/bone_controller_mapping.py
"""公共工具 —— 骨骼/控制器映射（迁移自 harp_glide_rust/bone_controller_mapping_addon）

通用工具：把骨架中的骨骼与场景中的控制器物体建立映射，支持：
- 添加/删除映射项（骨骼 → 控制器）；
- 一键同步控制器到骨骼位置（按层级深度从浅到深，避免嵌套层级问题）；
- 映射导出/导入 JSON 配置文件。

所有乐器共用（出现在各乐器工具下拉菜单中）。
场景属性使用 md_bcm_ 前缀，避免与独立安装的同类插件冲突。
"""

import os
import json

import bpy  # type: ignore
from bpy.props import (  # type: ignore
    StringProperty, IntProperty, CollectionProperty, BoolProperty,
)
from bpy.types import PropertyGroup, Operator  # type: ignore

from .. import ui_utils


# ── 场景属性名（md_bcm_ 前缀，避免与独立插件冲突）───────────────

SCENE_MAPPING = "md_bcm_bone_controller_mapping"
SCENE_FILE_PATH = "md_bcm_mapping_file_path"
SCENE_SHOW = "md_bcm_show_bone_mapping"


# ============================================================================
# 数据结构定义
# ============================================================================

class BoneControllerMappingItem(PropertyGroup):
    """骨骼-控制器映射项"""
    bone_name: StringProperty(
        name="骨骼",
        description="选中的骨骼名称",
        default=""
    )
    controller_name: StringProperty(
        name="控制器",
        description="对应的控制器物体名称",
        default=""
    )


# ============================================================================
# 核心工具函数
# ============================================================================

def get_controller_depth(controller_obj):
    """计算控制器的父级链深度

    Args:
        controller_obj: Blender控制器物体对象

    Returns:
        int: 层级深度（根节点为0）
    """
    depth = 0
    current = controller_obj
    while current.parent:
        depth += 1
        current = current.parent
    return depth


def export_mapping_to_json(mapping_collection, file_path):
    """将映射集合导出为简单JSON格式

    Args:
        mapping_collection: 映射项集合
        file_path: 输出文件路径

    Raises:
        Exception: 文件写入失败时抛出异常
    """
    mapping_dict = {}
    for item in mapping_collection:
        if item.bone_name and item.controller_name:
            mapping_dict[item.bone_name] = item.controller_name

    dir_name = os.path.dirname(file_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(mapping_dict, f, indent=4, ensure_ascii=False)


def import_mapping_from_json(file_path, mapping_collection):
    """从JSON文件导入映射并填充到集合

    Args:
        file_path: 输入文件路径
        mapping_collection: 目标映射集合

    Raises:
        FileNotFoundError: 文件不存在时抛出
        json.JSONDecodeError: JSON格式错误时抛出
        Exception: 其他错误时抛出
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"找不到文件：{file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        mapping_dict = json.load(f)

    # 清空现有映射
    mapping_collection.clear()

    # 添加新映射项
    for bone_name, controller_name in mapping_dict.items():
        item = mapping_collection.add()
        item.bone_name = bone_name
        item.controller_name = controller_name


def sync_controllers_to_bones(armature_obj, mapping_collection):
    """按层级顺序将控制器匹配到对应骨骼的完整变换（位置/旋转/缩放），修复嵌套层级问题"""
    if not armature_obj or armature_obj.type != 'ARMATURE':
        raise Exception("未选择有效的骨架对象")

    # 收集所有需要同步的映射项
    valid_mappings = []
    for item in mapping_collection:
        if not item.bone_name or not item.controller_name:
            continue

        if item.bone_name not in armature_obj.data.bones:
            raise Exception(f"骨骼 '{item.bone_name}' 不存在于骨架中")

        controller_obj = bpy.data.objects.get(item.controller_name)
        if not controller_obj:
            raise Exception(f"控制器 '{item.controller_name}' 不存在于场景中")

        # 获取骨骼的完整变换矩阵（在骨架本地空间）
        pose_bone = armature_obj.pose.bones[item.bone_name]
        # 骨骼世界矩阵 = 骨架世界矩阵 × 骨骼姿势矩阵（包含位置/旋转/缩放）
        bone_world_mat = armature_obj.matrix_world @ pose_bone.matrix

        valid_mappings.append({
            'item': item,
            'controller': controller_obj,
            'bone_world_mat': bone_world_mat,
            'depth': get_controller_depth(controller_obj)
        })

    if not valid_mappings:
        raise Exception("没有有效的映射项需要同步")

    # 按深度排序（从浅到深，确保父级先更新）
    valid_mappings.sort(key=lambda x: x['depth'])

    # 依次更新每个控制器
    for mapping in valid_mappings:
        controller_obj = mapping['controller']
        bone_world_mat = mapping['bone_world_mat']

        # 计算目标本地变换矩阵
        if controller_obj.parent:
            # 将骨骼世界矩阵转换到父级本地空间
            parent_inv = controller_obj.parent.matrix_world.inverted()
            local_mat = parent_inv @ bone_world_mat
        else:
            # 无父级：直接使用骨骼世界矩阵
            local_mat = bone_world_mat

        # 应用完整变换（位置/旋转/缩放）
        controller_obj.matrix_basis = local_mat

        # 立即更新场景，使子级能获取到父级最新的 matrix_world
        bpy.context.view_layer.update()


# ============================================================================
# UI绘制函数
# ============================================================================

def draw_bone_controller_mapping_panel(layout, scene, prefix="md_bcm_"):
    """绘制骨骼控制器映射面板（工具参数区）

    Args:
        layout: Blender布局对象
        scene: 当前场景
        prefix: 属性名前缀（默认为 "md_bcm_"，避免与其他插件冲突）
    """
    # 可折叠区域
    row = layout.row(align=True)
    show_prop = f"{prefix}show_bone_mapping"
    row.prop(scene, show_prop,
             icon="TRIA_DOWN" if getattr(
                 scene, show_prop, False) else "TRIA_RIGHT",
             icon_only=True, emboss=False)
    row.label(text="骨骼/控制器映射", icon='BONE_DATA')

    if not getattr(scene, show_prop, False):
        return

    mapping_box = layout.box()

    # 使用提示（骨骼自动取当前演奏者的目标骨骼，无需手动选择）
    hint = mapping_box.column(align=True)
    hint.label(
        text="提示：自动使用当前演奏者的目标骨骼；添加映射（骨骼 → 控制器）后同步/导出",
        icon="INFO")

    # 当前演奏者骨骼（公共场景指针，无手动选择器）
    skel = getattr(scene, ui_utils.SCENE_TARGET_SKELETON, None)
    if skel is None or skel.type != 'ARMATURE':
        hint.label(
            text="警告：请先在「角色选择器」中选中演奏者并设置目标骨骼",
            icon="ERROR")

    # 操作按钮行
    btn_row = mapping_box.row(align=True)
    btn_row.operator("music_doll.tool_bcm_add_mapping_entry",
                     text="添加", icon='ADD')
    btn_row.operator("music_doll.tool_bcm_sync_controllers",
                     text="同步", icon='FILE_REFRESH')

    # 文件路径和操作
    file_prop = f"{prefix}mapping_file_path"
    file_row = mapping_box.row(align=True)
    file_row.prop(scene, file_prop, text="")
    file_row.operator("music_doll.tool_bcm_browse_file",
                      text="", icon='FILEBROWSER')
    file_row.operator("music_doll.tool_bcm_export_mapping",
                      text="导出", icon='EXPORT')
    file_row.operator("music_doll.tool_bcm_import_mapping",
                      text="导入", icon='IMPORT')

    # 映射表区域
    mapping_prop = f"{prefix}bone_controller_mapping"
    mapping_collection = getattr(scene, mapping_prop, None)

    if not mapping_collection:
        mapping_box.label(text="未初始化映射集合", icon='ERROR')
        return

    for i, item in enumerate(mapping_collection):
        row = mapping_box.row(align=True)

        # 骨骼下拉菜单（动态生成，自动取当前演奏者骨骼）
        if skel is not None and skel.type == 'ARMATURE':
            row.prop_search(item, "bone_name", skel.data, "bones", text="")
        else:
            row.prop(item, "bone_name", text="骨骼")

        # 控制器名称输入（使用prop_search从场景对象中选择）
        row.prop_search(item, "controller_name", bpy.data, "objects", text="")

        # 删除按钮
        op = row.operator("music_doll.tool_bcm_remove_mapping_entry",
                          text="", icon='X')
        op.index = i


def draw(layout, scene):
    """ToolDef 参数区绘制：完整的骨骼/控制器映射面板"""
    draw_bone_controller_mapping_panel(layout, scene)


# ============================================================================
# 操作符
# ============================================================================

class MUSICDOLL_OT_tool_bcm_add_mapping_entry(Operator):
    """添加映射项"""
    bl_idname = "music_doll.tool_bcm_add_mapping_entry"
    bl_label = "添加映射项"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        getattr(scene, SCENE_MAPPING).add()
        return {'FINISHED'}


class MUSICDOLL_OT_tool_bcm_remove_mapping_entry(Operator):
    """删除映射项"""
    bl_idname = "music_doll.tool_bcm_remove_mapping_entry"
    bl_label = "删除映射项"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        scene = context.scene
        collection = getattr(scene, SCENE_MAPPING)
        if 0 <= self.index < len(collection):
            collection.remove(self.index)
        return {'FINISHED'}


class MUSICDOLL_OT_tool_bcm_browse_file(Operator):
    """浏览映射文件（可在文件名栏输入不存在的文件名来新建）"""
    bl_idname = "music_doll.tool_bcm_browse_file"
    bl_label = "浏览文件"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def invoke(self, context, event):
        # 预填当前路径，方便用户在文件名栏中修改为新文件名
        current = getattr(context.scene, SCENE_FILE_PATH, "")
        self.filepath = current if current else "mapping.json"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        setattr(context.scene, SCENE_FILE_PATH, self.filepath)
        return {'FINISHED'}


class MUSICDOLL_OT_tool_bcm_export_mapping(Operator):
    """导出映射到JSON（使用上方路径框中的路径）"""
    bl_idname = "music_doll.tool_bcm_export_mapping"
    bl_label = "导出映射"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        file_path = getattr(scene, SCENE_FILE_PATH, "")

        if not file_path:
            self.report({'ERROR'}, "请先在路径框中填写或浏览选择文件路径")
            return {'CANCELLED'}

        try:
            export_mapping_to_json(
                getattr(scene, SCENE_MAPPING), file_path)
            self.report({'INFO'}, f"映射已导出：{file_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"导出失败：{e}")
            return {'CANCELLED'}


class MUSICDOLL_OT_tool_bcm_import_mapping(Operator):
    """从JSON导入映射（使用上方路径框中的路径）"""
    bl_idname = "music_doll.tool_bcm_import_mapping"
    bl_label = "导入映射"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        file_path = getattr(scene, SCENE_FILE_PATH, "")

        if not file_path:
            self.report({'ERROR'}, "请先在路径框中填写或浏览选择文件路径")
            return {'CANCELLED'}

        try:
            import_mapping_from_json(
                file_path, getattr(scene, SCENE_MAPPING))
            self.report({'INFO'}, f"映射已导入：{file_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"导入失败：{e}")
            return {'CANCELLED'}


class MUSICDOLL_OT_tool_bcm_sync_controllers(Operator):
    """同步控制器到骨骼位置"""
    bl_idname = "music_doll.tool_bcm_sync_controllers"
    bl_label = "同步控制器"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        try:
            skel = ui_utils.get_target_skeleton(context)
            sync_controllers_to_bones(skel, getattr(scene, SCENE_MAPPING))
            self.report({'INFO'}, "控制器同步完成")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"同步失败：{e}")
            return {'CANCELLED'}


# ============================================================================
# 注册 / 注销
# ============================================================================

classes = (
    BoneControllerMappingItem,
    MUSICDOLL_OT_tool_bcm_add_mapping_entry,
    MUSICDOLL_OT_tool_bcm_remove_mapping_entry,
    MUSICDOLL_OT_tool_bcm_browse_file,
    MUSICDOLL_OT_tool_bcm_export_mapping,
    MUSICDOLL_OT_tool_bcm_import_mapping,
    MUSICDOLL_OT_tool_bcm_sync_controllers,
)


def register():
    """注册本工具的类与场景属性（幂等：脚本重载时不会重复注册）。"""
    # 先注册 PropertyGroup，再注册其余类（CollectionProperty 依赖它）
    for cls in classes:
        bpy.utils.register_class(cls)

    # 场景属性（幂等：已存在则跳过，避免脚本重载报错）
    if not hasattr(bpy.types.Scene, SCENE_MAPPING):
        setattr(bpy.types.Scene, SCENE_MAPPING, CollectionProperty(
            name="骨骼控制器映射",
            description="骨骼与控制器的映射关系列表",
            type=BoneControllerMappingItem
        ))
    if not hasattr(bpy.types.Scene, SCENE_FILE_PATH):
        setattr(bpy.types.Scene, SCENE_FILE_PATH, StringProperty(
            name="映射文件路径",
            description="JSON映射文件的保存/加载路径",
            subtype='FILE_PATH'
        ))
    if not hasattr(bpy.types.Scene, SCENE_SHOW):
        setattr(bpy.types.Scene, SCENE_SHOW, BoolProperty(
            name="显示骨骼映射",
            description="展开/折叠骨骼控制器映射模块",
            default=False
        ))


def unregister():
    """注销场景属性与类（幂等，逆序）。"""
    # 顺带清理旧版本可能残留的 md_bcm_armature（已移除手动骨架选择）
    for name in (SCENE_SHOW, SCENE_FILE_PATH, SCENE_MAPPING, "md_bcm_armature"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
