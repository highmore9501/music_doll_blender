# bellows_pulse/__init__.py
"""BellowsPulse（手风琴）乐器模块

配套 Rust 仓库：`H:\\bellows_pulse_rust`（midi → 指法 → 动画）。
本模块负责 Blender 侧的三件事：

- **控件**：双手（手掌 / 五指 / ext / 极向量 / 手部 IK 枢轴）、双脚、
  左右键区枢轴 `pivot_left` / `pivot_right`、键区位置记录器、
  键区骨骼跟随器 `left_bone` / `right_bone`、键区网格挂点
  `left_bone_root` / `right_bone_root`、背带 Hook 目标 `hand_back`、
  风箱极向 `accordion_pivot`；
- **属性**：分步填写的乐器属性面板（右手键盘/按钮、音域、排数、键数…），
  连同左右手各一份基准手型，存到演奏者骨骼的自定义属性上；
- **数据往返**：`.accordion` 导出 / 导入（`io.py`），把乐器属性、键区记录器的局部坐标、
  左右手基准手型写成 Rust 指法阶段读的那份配置，再读回来。

手风琴的键区是**会动**的：记录器按左右分别挂在两个键区骨骼跟随器下、记局部坐标；
风箱形变由引擎侧（Blender 约束 / Unreal IK）驱动，本模块只提供 pole target 控件。
"""
