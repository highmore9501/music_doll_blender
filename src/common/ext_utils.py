# common/ext_utils.py
"""ext 辅助控件通用构建 —— 公共模块

所有乐器的 ext 辅助控件都是同一件事：「位置落在手掌 → 手指的延长线上、+X 轴恒指向手掌」，
统一由 `add_ext_driver(config, hand, finger, palm, hand_is_parent)` 负责创建（先清后建，幂等）。
各乐器模块只提供命名解析 `obj_name(short)`，并用两个参数**显式**说明该手指的位置基准：

- `hand_is_parent=True`：手掌就是该手指的父级 → 手掌即 ext 局部空间的原点，`ext = 2 × 手指`；
- `hand_is_parent=False` + `palm='H_<hand>'`：手掌不是该手指的父级（手指与手掌同挂在
  某个父级下，手掌不在局部原点）→ `ext = 2 × 手指 − 手掌`；
- `palm=None`：该手指不做手掌减法（例如 FretDance 电吉他食指挂在大拇指 `T_R` 下，
  与手掌的局部空间不一致，只能以自己父级的原点为基准）→ `ext = 2 × 手指`。

**例外**：某手指干脆不用 ext 控件时（FretDance 电吉他食指与实际演奏用的大拇指几乎重合，
运行时直接借用大拇指的 `ext_T_R`），该手指改调 `clear_ext_driver(...)`——不挂 driver、
不挂约束，并把上一次可能残留的清干净。

**一律不看场景层级**：父级只是 ext 的坐标空间，不等于手掌。FretDance 电吉他右手的食指
就挂在拇指下，按父级猜「谁是大拇指 / 手掌」必然猜错，所以基准由调用方声明。
朝向约束的目标也固定取该手的**手掌控制器** `H_<hand>`，同样不从父级推导。

命名约定（Blender 与 Unreal 端一致，7 个乐器模块共用）：

- 手指短名 `<finger>_<hand>`（如 `T_L` / `I_L` / `1_L` / `0_L`）
- 手掌短名 `H_<hand>`
- ext 短名 `ext_<finger>_<hand>`
"""

import bpy  # type: ignore


#: ext 辅助控件「指向手掌」的 Damped Track 约束名（视口/大纲里便于辨认）
EXT_TRACK_CONSTRAINT_NAME = "Damped_Track_Palm"


# ── 约束器：ext 辅助控件 +X 轴指向手掌 ────────────────────────

def ensure_damped_track(obj, target_obj, track_axis: str = "TRACK_X",
                        name: str = EXT_TRACK_CONSTRAINT_NAME):
    """幂等添加/刷新 Damped Track 约束：让 obj 的 track_axis 轴恒指向 target_obj。

    - 先清后建：按类型清掉已有的 DAMPED_TRACK（避免重复 Setup 叠加约束，也兼容约束名
      被 Blender 追加 .001 的情况），其余类型的约束（如 Copy Location）保持不动；
    - Damped Track 没有 owner/target 空间选项（方向在 owner 与 target 的共同空间里算，
      不受父级影响），所以 ext 与手掌是否同父（挂手掌 / 挂 Bow_Controller /
      挂 controller_root_offset）都成立；
    - track_axis 显式赋值：Blender 新建 Damped Track 时的默认轴是 TRACK_Y，
      不依赖版本默认值；
    - 只锁指向轴，roll 由对象自身旋转按最短路径决定，用户在视口旋转 ext 仍可调
      pole 绕手指轴的方向。

    :param obj: 承载约束的对象（ext 辅助控件）
    :param target_obj: 指向目标（手掌控制器 H_L / H_R）
    :param track_axis: 对齐到目标的轴，默认 'TRACK_X'
    :param name: 约束名
    :return: 新建的约束对象；obj / target_obj 为空时返回 None
    """
    if obj is None or target_obj is None:
        return None

    for existing_constraint in list(obj.constraints):
        if existing_constraint.type == "DAMPED_TRACK":
            obj.constraints.remove(existing_constraint)

    damped_track = obj.constraints.new("DAMPED_TRACK")
    damped_track.name = name
    damped_track.target = target_obj
    damped_track.track_axis = track_axis
    return damped_track


# ── ext 辅助控件：位置驱动 + 指向手掌约束 ─────────────────────

def clear_ext_location_drivers(ext_obj) -> None:
    """清掉 ext 控件上已有的 location 驱动（XYZ 三条），保证可重复运行。"""
    if ext_obj is None or not ext_obj.animation_data:
        return
    if not ext_obj.animation_data.drivers:
        return
    for axis_index in range(3):
        fcurve = ext_obj.animation_data.drivers.find("location", index=axis_index)
        if fcurve:
            ext_obj.animation_data.drivers.remove(fcurve)


def add_ext_driver(config, hand: str, finger: str, palm: str | None = None,
                   hand_is_parent: bool = True) -> bool:
    """为 `ext_<finger>_<hand>` 添加位置 driver 与「+X 轴指向手掌」约束（幂等）。

    - 位置：driver `ext = 2 × 手指`（手掌即局部原点 / 不做手掌减法）或
      `ext = 2 × 手指 − 手掌`，XYZ 各一条，变量取 LOCAL_SPACE，让 ext 落在
      「手掌 → 手指」的延长线上（落在手指外侧、距手掌 2 倍处）；
    - 朝向：Damped Track 约束让 ext 的 +X 轴恒指向该手的手掌控制器 `H_<hand>`，
      于是 ext 的另外两轴恒与手指轴垂直——挂在 ext 局部 (0, 0, 1) 的 pole
      （IK 极向量）不会退化到手指轴上；
    - 先清后建：location 驱动与 DAMPED_TRACK 约束都先清再建，重复 Setup 不叠加。

    :param config: 乐器配置对象，需提供 `obj_name(short) -> 完整对象名`
    :param hand: 手别，'L' / 'R'
    :param finger: 手指短名主体（'T'/'I'/'M'/'R'/'P'，数字手指名的乐器传 '0'~'N'）
    :param palm: 位置驱动里要减掉的手掌短名（'H_L' / 'H_R'）；None 表示不做手掌减法。
                 只在 `hand_is_parent=False` 时参与计算，由调用方显式给出（不看层级）
    :param hand_is_parent: 手掌是否就是该手指的父级（调用方显式给出，不从场景层级推导）：
                 True  → 手掌即 ext 局部空间的原点，`ext = 2 × 手指`；
                 False → `ext = 2 × 手指 − 手掌`（需要 palm；palm 为 None 时退回 `2 × 手指`）
    :return: 是否完成（手指 / ext 控件缺失时打印原因并返回 False）
    """
    finger_short = f"{finger}_{hand}"
    palm_short = f"H_{hand}"
    ext_short = f"ext_{finger_short}"

    finger_name = config.obj_name(finger_short)
    palm_name = config.obj_name(palm_short)
    ext_name = config.obj_name(ext_short)

    finger_obj = bpy.data.objects.get(finger_name)
    if finger_obj is None:
        print(f"  • 手指控制器 {finger_name} 不存在，跳过 ext 驱动")
        return False
    ext_obj = bpy.data.objects.get(ext_name)
    if ext_obj is None:
        print(f"  • ext 控件 {ext_name} 不存在，跳过 ext 驱动")
        return False

    # 手掌减法：手掌不是手指的父级、且调用方给了手掌时才减
    subtract_palm = False
    palm_obj = None
    if palm is not None and not hand_is_parent:
        palm_name = config.obj_name(palm)
        palm_obj = bpy.data.objects.get(palm_name)
        if palm_obj is None:
            print(f"  • 手掌控制器 {palm_name} 不存在，位置驱动退回 2 × 手指")
        else:
            subtract_palm = True

    clear_ext_location_drivers(ext_obj)

    for axis_index, axis_char in enumerate(["X", "Y", "Z"]):
        driver = ext_obj.driver_add("location", axis_index).driver
        driver.type = "SCRIPTED"

        finger_variable = driver.variables.new()
        finger_variable.name = "finger"
        finger_variable.type = "TRANSFORMS"
        finger_target = finger_variable.targets[0]
        finger_target.id = finger_obj
        finger_target.transform_type = f"LOC_{axis_char}"
        finger_target.transform_space = "LOCAL_SPACE"

        if subtract_palm:
            palm_variable = driver.variables.new()
            palm_variable.name = "palm"
            palm_variable.type = "TRANSFORMS"
            palm_target = palm_variable.targets[0]
            palm_target.id = palm_obj
            palm_target.transform_type = f"LOC_{axis_char}"
            palm_target.transform_space = "LOCAL_SPACE"
            driver.expression = "2 * finger - palm"
        else:
            driver.expression = "2 * finger"

    expression_text = (f"2×{finger_short} − {palm}" if subtract_palm
                       else f"2×{finger_short}")

    # 朝向约束目标固定是该手的手掌控制器（不从父级 / palm 参数推导）
    aim_obj = bpy.data.objects.get(palm_name)
    damped_track = ensure_damped_track(ext_obj, aim_obj)
    if damped_track is not None:
        print(f"  ✓ {ext_short}: ext = {expression_text} + 约束 +X 轴指向 {palm_short}")
    else:
        print(f"  ✓ {ext_short}: ext = {expression_text}"
              f"（手掌 {palm_name} 不存在，未加指向约束）")
    return True


def clear_ext_driver(config, hand: str, finger: str) -> bool:
    """清掉 `ext_<finger>_<hand>` 上的位置驱动与「指向手掌」约束（幂等）。

    用于「该手指不驱动 ext」的例外情况：FretDance 电吉他右手食指与实际演奏用的
    大拇指几乎重合，运行时直接借用大拇指的 `ext_T_R`，所以那一路 ext 控件干脆不创建
    （见 fret_dance 的 add_finger_ext_and_poles）。本函数用来清掉旧版本场景可能残留的
    location 驱动与 DAMPED_TRACK，保证重复 Setup、切换乐器类型（电吉他 ↔ 指弹）后
    状态确定：残留被清干净，切回指弹模式时 add_ext_driver 又能正常重新建驱动。

    注意：pole 的归属由乐器模块自己处理（FretDance 把 `I_R_pole` 改挂到借用的
    `ext_T_R` 下），本函数只管 ext 控件自己的驱动与约束。

    :param config: 乐器配置对象，需提供 `obj_name(short) -> 完整对象名`
    :param hand: 手别，'L' / 'R'
    :param finger: 手指短名主体
    :return: 是否处理了该 ext 控件（不存在时返回 False）
    """
    ext_short = f"ext_{finger}_{hand}"
    ext_obj = bpy.data.objects.get(config.obj_name(ext_short))
    if ext_obj is None:
        print(f"  • ext 控件 {config.obj_name(ext_short)} 不存在，跳过清理")
        return False

    clear_ext_location_drivers(ext_obj)
    for existing_constraint in list(ext_obj.constraints):
        if existing_constraint.type == "DAMPED_TRACK":
            ext_obj.constraints.remove(existing_constraint)
    print(f"  ✓ {ext_short}: 例外不驱动（不挂 driver / 约束）")
    return True
