# beat_bloom/__init__.py
"""BeatBloom 乐器模块（迁移自 beat_bloom_rust/beat_bloom_addon）

打击乐动画生成插件。并入统一插件后：
- 命名接演奏者后缀（<短名>_<后缀>）；
- 控制器（12 个）保留为场景物体；
- 原记录器物体废止，状态存骨骼自定义属性 beat_bloom_state_data（JSON）；
- Drumkit 配置存骨骼自定义属性 beat_bloom_drumkit_config（JSON）；
- 无 Undo 系统、无 mmd2blender / MCH bones 工具。
"""
