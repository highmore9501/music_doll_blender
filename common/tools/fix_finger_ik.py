# common/tools/fix_finger_ik.py
"""公共工具 —— 修正手指骨骼（迁移自 fret_dance_blender/tools/fix_finger_ik.py）

所有乐器共用的工具：修正选中骨骼链的手指骨骼形状，形成拱形分布。
提供纯函数 modify_finger_bones() 与执行算子 music_doll.tool_fix_finger_bones。
"""
from mathutils import Vector  # type: ignore
import bpy  # type: ignore
import math


def is_point_on_line(point, line_start, line_end, tolerance=0.001):
    """判断点是否在直线上"""
    p = Vector(point)
    a = Vector(line_start)
    b = Vector(line_end)

    ab = b - a
    ap = p - a

    cross = ab.cross(ap)
    if cross.length > tolerance:
        return False

    dot = ap.dot(ab)
    if dot < 0 or dot > ab.length_squared:
        return False

    return True


def calculate_plane_normal(start_pos, end_pos, ref_pos):
    """计算平面的法线向量"""
    line_vec = Vector((end_pos[0] - start_pos[0],
                       end_pos[1] - start_pos[1],
                       end_pos[2] - start_pos[2]))

    ref_vec = Vector((ref_pos[0] - start_pos[0],
                      ref_pos[1] - start_pos[1],
                      ref_pos[2] - start_pos[2]))

    normal = line_vec.cross(ref_vec)
    if normal.length < 0.0001:
        print("警告: 参照物体在直线上，无法形成平面")
        return None

    return normal.normalized()


def project_point_to_line(point, line_start, line_end):
    """将点投影到直线上，返回投影点和参数t"""
    p = Vector(point)
    a = Vector(line_start)
    b = Vector(line_end)

    ab = b - a
    ap = p - a
    t = (ap.dot(ab)) / (ab.dot(ab)) if ab.length > 0 else 0
    t = max(0, min(1, t))

    projection = a + ab * t
    return [projection.x, projection.y, projection.z], t


def get_bone_chain(start_bone):
    """获取从起始骨骼到末端骨骼的骨骼链"""
    chain = [start_bone]
    current = start_bone

    while True:
        children = [
            child for child in current.children if child.use_deform == start_bone.use_deform]

        if len(children) > 1:
            print(f"警告: 骨骼 {current.name} 有多个子骨骼，存在分支结构")
            return None

        if len(children) == 0:
            break

        current = children[0]
        chain.append(current)

    return chain


def modify_finger_bones():
    """Blender版手指骨骼修正函数

    使用说明：
    1. 在Object模式下，先选择参照物体，再选择骨架对象（作为活动对象）
    2. 进入Edit模式
    3. 选择要修正的手指根骨骼
    4. 运行此函数
    """
    print("=" * 50)
    print("开始执行手指骨骼修正脚本")
    print("=" * 50)

    if len(bpy.context.selected_objects) < 2:
        print("错误: 请先选择一个参照物体和一个骨架对象")
        return

    selected_objects = bpy.context.selected_objects
    armature_obj = bpy.context.active_object

    if armature_obj.type != 'ARMATURE':
        print("错误: 请确保活动对象是骨架")
        return

    ref_obj = None
    for obj in selected_objects:
        if obj != armature_obj and obj.type != 'ARMATURE':
            ref_obj = obj
            break

    if not ref_obj:
        print("错误: 请先选择一个参照物体")
        return

    if bpy.context.mode != 'EDIT_ARMATURE':
        bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = armature_obj.data.edit_bones

    selected_bones = [bone for bone in edit_bones if bone.select]
    if len(selected_bones) != 1:
        print("错误: 请只选择一个根骨骼")
        return

    start_bone = selected_bones[0]

    bone_chain = get_bone_chain(start_bone)
    if not bone_chain:
        return

    if len(bone_chain) < 3:
        print("错误: 骨骼链需要至少3个骨骼（起点、中间点、终点）")
        return

    print(f"骨骼链: {[bone.name for bone in bone_chain]}")
    print(f"骨骼数量: {len(bone_chain)}")

    start_pos = start_bone.head[:]
    end_pos = bone_chain[-1].tail[:]
    ref_pos = ref_obj.location[:]

    if is_point_on_line(ref_pos, start_pos, end_pos):
        print("警告: 参照物体在直线上，请将参照物体放置在直线外")
        return

    line_length = math.sqrt(
        (end_pos[0] - start_pos[0])**2 +
        (end_pos[1] - start_pos[1])**2 +
        (end_pos[2] - start_pos[2])**2
    )

    print(f"直线长度: {line_length:.4f}")

    plane_normal = calculate_plane_normal(start_pos, end_pos, ref_pos)
    if not plane_normal:
        return

    points_to_process = []

    points_to_process.append({
        'bone': start_bone,
        'point_type': 'tail',
        'original_pos': start_bone.tail[:]
    })

    middle_bones = bone_chain[1:-1]
    for bone in middle_bones:
        points_to_process.append({
            'bone': bone,
            'point_type': 'head',
            'original_pos': bone.head[:]
        })
        points_to_process.append({
            'bone': bone,
            'point_type': 'tail',
            'original_pos': bone.tail[:]
        })

    points_to_process.append({
        'bone': bone_chain[-1],
        'point_type': 'head',
        'original_pos': bone_chain[-1].head[:]
    })

    for point_data in points_to_process:
        bone = point_data['bone']
        point_type = point_data['point_type']
        original_pos = point_data['original_pos']

        projection, t = project_point_to_line(original_pos, start_pos, end_pos)

        max_offset = 0.03 * line_length
        offset_factor = math.sin(t * math.pi)
        offset_distance = max_offset * offset_factor

        print(
            f"骨骼 {bone.name} ({point_type}): t={t:.3f}, 偏移系数={offset_factor:.3f}, 偏移距离={offset_distance:.4f}")

        ref_vec = Vector((ref_pos[0] - projection[0],
                         ref_pos[1] - projection[1],
                         ref_pos[2] - projection[2]))

        dot_product = ref_vec.dot(plane_normal)
        plane_vec = ref_vec - plane_normal * dot_product

        if plane_vec.length > 0.0001:
            plane_dir = plane_vec.normalized()
        else:
            line_dir = Vector((end_pos[0] - start_pos[0],
                              end_pos[1] - start_pos[1],
                              end_pos[2] - start_pos[2])).normalized()
            plane_dir = plane_normal.cross(line_dir)

        new_pos = [
            projection[0] + plane_dir.x * offset_distance,
            projection[1] + plane_dir.y * offset_distance,
            projection[2] + plane_dir.z * offset_distance
        ]

        if point_type == 'head':
            bone.head = Vector(new_pos)
        elif point_type == 'tail':
            bone.tail = Vector(new_pos)

        print(f"  原始位置: {original_pos}")
        print(f"  投影位置: {projection}")
        print(f"  新位置: {new_pos}")

    print("\n" + "=" * 50)
    print("骨骼修正完成！")
    print("所有骨骼端点已移动到平面上，并形成拱形分布")
    print("=" * 50)


# ── 执行算子 ──────────────────────────────────────────────────

class MUSICDOLL_OT_tool_fix_finger_bones(bpy.types.Operator):
    """修正手指骨骼"""
    bl_idname = "music_doll.tool_fix_finger_bones"
    bl_label = "修正手指骨骼"
    bl_description = "修正选中骨骼链的手指骨骼形状"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            modify_finger_bones()
            self.report({'INFO'}, "手指骨骼修正完成")
        except Exception as e:
            self.report({'ERROR'}, f"修正失败: {str(e)}")
            return {'CANCELLED'}
        return {'FINISHED'}


def register():
    bpy.utils.register_class(MUSICDOLL_OT_tool_fix_finger_bones)


def unregister():
    bpy.utils.unregister_class(MUSICDOLL_OT_tool_fix_finger_bones)
