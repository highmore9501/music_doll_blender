# music_doll_blender / __init__.py
"""MusicDoll Blender —— 统一乐器插件（多乐器演奏者管理）

相当于 Unreal 的 MusicDoll 插件：一个插件管理所有乐器（FretDance / KeyRipple / …）。
- common/  公共模块（对应 MusicDollCommon）：演奏者命名空间、对象/集合创建、
           状态存取、动画通用、JSON 读写、统一属性、通用 UI。
- fret_dance/  FretDance 乐器模块（Phase 1 迁入）。
- key_ripple/  KeyRipple 乐器模块（Phase 2 迁入）。

演奏者模型：
- 演奏者实例 = Performers 根集合下的一个子 Collection（身份属性 md_* 存其上）；
- 各乐器特有状态/设置存演奏者骨骼（Armature）自定义属性；
- 演奏者根空物体 = <乐器缩写>_<演奏者名>（如 FD_Jeht / KR_Aki）。
"""

from .common import ui_utils
import bpy  # type: ignore
bl_info = {
    "name": "MusicDoll Blender",
    "author": "BigHippo78",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > MusicDoll",
    "description": "统一乐器插件：一个插件管理所有乐器演奏者（FretDance / KeyRipple / ...）",
    "category": "Animation",
}


def register():
    # 公共场景属性 + 统一主面板(MUSICDOLL_PT_main_panel) + 新建角色算子。
    # 父面板必须先于乐器子面板注册（bl_parent_id 校验），故放最前。
    ui_utils.register_scene_props()

    # 公共工具（所有乐器共用）
    from .common.tools import fix_finger_ik as common_fix_finger_ik
    common_fix_finger_ik.register()

    # 乐器模块注册
    from .fret_dance import ui as fret_dance_ui
    fret_dance_ui.register()
    from .key_ripple import ui as key_ripple_ui
    key_ripple_ui.register()


def unregister():
    # 乐器模块注销（与注册顺序相反）
    from .key_ripple import ui as key_ripple_ui
    key_ripple_ui.unregister()
    from .fret_dance import ui as fret_dance_ui
    fret_dance_ui.unregister()

    # 公共工具
    from .common.tools import fix_finger_ik as common_fix_finger_ik
    common_fix_finger_ik.unregister()

    ui_utils.unregister_scene_props()


if __name__ == "__main__":
    register()
