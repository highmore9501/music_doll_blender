# common/tools/fix_finger_ik.py
"""公共工具 —— 修正手指骨骼（迁移自 fret_dance_blender/tools/fix_finger_ik.py）

所有乐器共用的工具：修正选中骨骼链的手指骨骼形状，形成拱形分布。
提供纯函数 modify_finger_bones() 与执行算子 music_doll.tool_fix_finger_bones。
"""
from mathutils import Matrix, Vector  # type: ignore
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


def align_bone_z_to_plane(bone, plane_normal, ref_pos):
    """将单根骨骼的 Z 轴对齐到修正平面内，并指向参照物体。

    原理（Blender 骨骼局部坐标系）：
    - Y 轴是骨骼自身方向（head -> tail），由端点位置决定，无法改变；
    - 要同时满足「Z 轴在修正平面内」和「Z 轴垂直于 Y 轴」，
      唯一的候选方向是 平面法线 × Y轴：
      它既垂直于平面法线（落在平面内），又垂直于 Y 轴；
    - 用 Z · (参照物 - 骨骼头) 的符号决定朝向，使其指向参照物体一侧；
    - 右手系补全 X 轴：X = Y × Z（Blender 骨骼为右手系，X × Y = Z）。

    应用方式：
    - 直接写 EditBone.matrix（4x4 可写矩阵）：
      第 0/1/2 列分别为 X/Y/Z 轴，第 3 列（translation）为骨骼头位置；
      Blender 写入时会保持骨骼长度不变、以第 3 列为 head、
      由第 1 列重算方向并反算 roll，因此位置不变、旋转精确生效。
    """
    head = Vector(bone.head)
    tail = Vector(bone.tail)

    y_axis = tail - head
    length = y_axis.length
    if length < 1e-6:
        return  # 零长度骨骼，跳过
    y_axis /= length

    # 平面内且垂直于骨骼方向的方向（修正平面法线 × Y轴）
    z_axis = plane_normal.cross(y_axis)
    if z_axis.length < 1e-6:
        # 理论上骨骼落在平面内时方向 ⊥ 法线不会为零，此处为防御处理
        return
    z_axis.normalize()

    # 让 Z 轴指向参照物体一侧
    to_ref = Vector(ref_pos) - head
    if z_axis.dot(to_ref) < 0.0:
        z_axis = -z_axis

    # 右手系补全 X 轴
    x_axis = y_axis.cross(z_axis)
    x_axis.normalize()

    # 构建 4x4 矩阵：列 0/1/2 为 X/Y/Z 轴，translation 为骨骼头位置
    mat = Matrix.Identity(4)
    for i in range(3):
        mat.col[0][i] = x_axis[i]
        mat.col[1][i] = y_axis[i]
        mat.col[2][i] = z_axis[i]
    mat.translation = head

    bone.matrix = mat


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

    # 参照物体位置换算到骨架（armature）空间，与骨骼端点的坐标系保持一致
    ref_pos = armature_obj.matrix_world.inverted() @ ref_obj.matrix_world.translation

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

    # ── 旋转优化：让每根骨骼的 Z 轴落在修正平面内，并指向参照物体 ──
    print("\n开始对齐骨骼 Z 轴...")
    for bone in bone_chain:
        align_bone_z_to_plane(bone, plane_normal, ref_pos)
        z_axis = bone.matrix.col[2][:3]
        print(
            f"骨骼 {bone.name}: Z轴 = ({z_axis[0]:.4f}, {z_axis[1]:.4f}, {z_axis[2]:.4f})")
    print("骨骼 Z 轴对齐完成！")

    print("\n" + "=" * 50)
    print("骨骼修正完成！")
    print("所有骨骼端点已移动到平面上，并形成拱形分布")
    print("每根骨骼的 Z 轴已对齐到修正平面内，并指向参照物体")
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
            from .. import i18n
            T = i18n.T
            modify_finger_bones()
            self.report({'INFO'}, T("手指骨骼修正完成"))
        except Exception as e:
            self.report({'ERROR'}, T("修正失败: ") + str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


def register():
    bpy.utils.register_class(MUSICDOLL_OT_tool_fix_finger_bones)
    from .. import i18n
    i18n.bl_label_set(MUSICDOLL_OT_tool_fix_finger_bones, "修正手指骨骼")


def unregister():
    bpy.utils.unregister_class(MUSICDOLL_OT_tool_fix_finger_bones)
