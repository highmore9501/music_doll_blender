# bellows_pulse/__init__.py
"""BellowsPulse（手风琴）乐器模块

配套 Rust 仓库：`H:\\bellows_pulse_rust`（midi → 指法 → 动画）。
本模块负责 Blender 侧的两件事：

- **控件**：双手（手掌 / 五指 / ext / 极向量 / 手部 IK 枢轴）、双脚、
  左右键区枢轴 `pivot_left` / `pivot_right`、键区位置记录器、
  风箱极向 `accordion_pivot`、朝向链 `Mid_Hand → Look_At → Head_Control`；
- **属性**：分步填写的乐器属性面板（右手键盘/按钮、音域、排数、键数…），
  连同左右手各一份基准手型，存到演奏者骨骼的自定义属性上。

手风琴的键区是**会动**的：记录器全部挂在枢轴下、记局部坐标；
风箱形变由引擎侧（Blender 约束 / Unreal IK）驱动，本模块只提供 pole target 控件。
"""
