# string_flow/__init__.py
"""StringFlow 乐器模块（小提琴）—— 迁移自 h:\\string_flow_rust\\string_flow_blender

本模块把独立插件 StringFlow 迁入统一插件 music_doll_blender，对齐多演奏者体系：

- 对象/集合命名全部带演奏者后缀（<短名>_<后缀>）；
- 状态从「记录器物体对象间拷贝」改为「存演奏者骨骼自定义属性 string_flow_state_data」
  （不再生成约 230 个状态记录器物体，只保留物理位置标记）；
- controller_root 替代原版硬编码的 "violin" 父级（固定乐器，无 controller_root_offset）；
- 右手手指挂 Bow_Controller（小提琴「手在弓上」结构，保留）；
- 右手 ext 用 Copy Location 约束、左手 ext 用 driver（保留）；
- .violinist 导入导出结构与 Rust 端完全兼容，另提供「导出到 Unreal」（Y 取反 + 旋转反射共轭）。
"""
