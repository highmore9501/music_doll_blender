# zheng_drift/__init__.py
"""ZhengDrift 乐器模块（迁移自 zheng_drift_rust/zheng_blender_addon）

古筝（21 弦）动画生成插件。并入统一插件后：
- 命名接演奏者后缀（<短名>_<后缀>）；
- 集合/物体创建改调 common.object_utils / performer_utils；
- 导入/导出标准姿势用角色模块的「人物信息路径」（SCENE_INFO_PATH）；
- 保留 zheng 独有逻辑：bilinear_map 双线性映射、特殊朝向控制器、
  双脚控制器、21 弦、弦 shape key 工具、线性分布工具。
"""
