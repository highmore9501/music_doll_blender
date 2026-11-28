---
name: music-doll-assemble-in-unreal
description: 在 Unreal 里组装一个能被 MusicDoll 插件驱动、并且真的能出动画的演奏者：把导出的 fbx 拼成 BB_ 层级（人物/乐器/鼓槌/凳子、材质接 mmd 母材质），再从骨骼网格生成两套 Control Rig、绑进 Sequencer、初始化控件与骨骼控件映射、把已调好的乐手的图表搬过来，最后导入演奏者数据、生成一遍动画验收。当用户说「把这套 fbx 导进 UE 拼起来」「在 Unreal 里组装演奏者」「给某个角色接上 MusicDoll 的控制体系」「新乐手没控件 / 不会动 / 生不出动画」「把辛焱（或夜兰）那套 rig 抄给新角色」时使用。
---

# 在 Unreal 里组装 MusicDoll 演奏者

## 前置条件

- Unreal Engine 5.8（5.7 及以前 Control Rig 是老蓝图，流程一样，类名不同）。
- 工程已启用 MusicDoll 插件（`BeatBloomUnreal` / `KeyRippleUnreal` … 各乐器一个模块），
  并启用 `PythonScriptPlugin`（本工程的 `Content/Python/init_unreal.py` 会挂一个任务轮询器，见第 12 节）。
- 手上有 `music-doll-export-to-fbx` 导出的一批 fbx + `manifest.json`，以及该乐器的数据文件
  （鼓手是 `.drumkit` + `.drummer`，动画是 `.beatbloom` + 两个 `.animation`，见第 11 节）。
- 下文路径按本工程写（`/Game/MyCharacters/<角色>/`、`/Game/MusicInstructment/<乐器目录>/`），换工程按自己的目录规范改。

## 这套东西解决什么

Blender 导出的是一堆零件，UE 这边要做三件事：

1. **拼成一组**：`BB_<角色名>` 是乐器演员（`AInstrumentBase` 的派生类），下面挂人物骨骼网格、乐器骨骼网格、凳子、鼓槌；
2. **接上控制体系**：人物与乐器各一套 Control Rig，在 Sequencer 里绑好，初始化控件、填骨骼控件映射，
   再把已调好的同类乐手的图表搬过来——这样插件才能往里写动画；
3. **跑通一次生成**：导入演奏者数据、喂动画数据、生成关键帧，确认这套控制体系是真的能用。

层级结构（以鼓手为例）：

```
BB_<角色名>                    ← BeatBloomUnreal（乐器演员）
├─ <角色名>_Body               ← 人物骨骼网格（形态键 = 表情/口型）
│  ├─ <角色名>_Stick_L         ← 鼓槌，挂在手骨 socket 上
│  └─ <角色名>_Stick_R
├─ <角色名>_DrumKit            ← 鼓组骨骼网格（形态键 = 每个鼓/镲的敲击形变）
└─ <角色名>_Stool              ← 凳子（静态网格）
```

**直接子级（Body / DrumKit / Stool）的相对变换必须是单位变换**：位置 0、旋转 0、缩放 1。
摆位靠 `BB_` 自己，不要靠子级偏移。判断时读**相对变换**（`root_component` 的 `relative_location`），
不要读 `get_actor_location()`——那是世界坐标，子级挂在父级下面时它一定等于父级位置。

**新乐手一律组装在 `/Game/BigCollection` 里**。它是「元关卡」，保管所有乐手；要渲染时复制这个关卡、
只留需要的乐手，不要给每个新乐手单开一个关卡。

**Outliner 里所有乐手都放在一个叫 `players` 的目录下，而且是平铺的**（父级 `BB_<角色>` 和它的子物体、
以及鼓槌，全都在 `players` 这一层，不再分子目录）。装完记得归位：

```python
for actor in (beat_bloom, body_actor, kit_actor, stool_actor, stick_l, stick_r):
    actor.set_folder_path("players")
```

## 流程总表

| # | 做什么 | 界面位置 | 脚本 / 函数 |
|---|---|---|---|
| 1 | 填演奏者骨骼、乐器骨骼、乐器配置文件 | Properties 页的 Details | `assemble_performer.py` |
| 2 | 从两个骨骼网格生成 Control Rig 资产 | 右键网格 → Create Control Rig | `assemble_performer.py` |
| 3 | 把两组骨骼加进对应 Sequencer 并绑 Control Rig 轨道 | Sequencer「+ Track → Actor to Sequencer」+ 拖 rig | `bind_in_sequencer.py` |
| 4 | 在插件主界面选中这个 `BB_` 实例 | 插件面板顶部 | 按 label 找 actor（脚本里就是这么做的） |
| 5 | 初始化演奏者控件；初始化乐器控件 | Properties「Setup Drummer Control Rig」；Operations「Initialize DrumKit」 | `setup_control_rig.py` |
| 6 | B/C Mapping：初始化变量（会自动编译）、保存 | B/C Mapping「Initialize」 | `setup_control_rig.py` |
| 7 | 填骨骼控件映射表 | B/C Mapping 的表格（或直接写变量） | `fill_bone_mapping.py` |
| 8 | 同步控件位置 | B/C Mapping「Sync Bone Control Pairs」 | `fill_bone_mapping.py` |
| 9 | 搭演奏者控制系统（抄同类乐手的图表 + 换骨骼名） | Control Rig 编辑器里复制节点 | `copy_control_rig_graphs.py` |
| 10 | 搭乐器形变驱动（抄图表 + 换通道清单） | 同上 | `copy_control_rig_graphs.py` |
| 11 | 导入演奏者数据（Unreal 坐标的 `.drummer`） | 插件面板 Import Drummer Info | `import_and_generate.py` |
| 12 | 喂动画数据、生成关键帧 | 插件面板 Generate All Animation | `import_and_generate.py` |

Blender 侧还有一个前置活：**导出 Unreal 坐标的演奏者数据**（第 11 节），脚本 `export_drummer_unreal.py`。

插件里的入口多数是 `BlueprintCallable`，Python 能直接调：
`BeatBloomControlRigProcessor.setup_all_objects()`、`BeatBloomDrumKitProcessor.initialize_drum_kit()`、
`BeatBloomAnimationProcessor.generate_all_animation()`。
骨骼控件映射、导入导出这几套（`FBoneControlMappingUtility`、`A…::ImportRecorderInfo`）不是 UFUNCTION，
Python 调不到，所以 `MusicDollToolset` 模块里有一层 `MusicDollAssemblyTools`（11 个函数，见第 16 节）。

## 1–2. 零件拼装与两套 rig 资产

`scripts/assemble_performer.py` 做完全部：清掉同名旧 actor → 生成 `BB_` 与子物体 → 填引用 → 加载乐器配置
→ 从两个骨骼网格各生成一套 Control Rig 资产。

要点：

- **鼓槌挂 socket**：socket 相对变换必须是 0（导出时已经把那根骨的世界矩阵的逆乘进顶点坐标了）；
  静态网格组件先 `set_mobility(MOVABLE)` 再 attach，否则静默失败。
- **乐器配置要真的加载**：`DrumKitConfigPath` 只是属性，配置内容得调 `LoadDrumKitConfig`；
  加载不到时 `DrumKitConfig.Components` 是 0，第 5 步会直接报「先加载配置」。
- **路径惯例**：作者机器上数据文件在 `H:/beat_bloom_rust/asset/...`。换一台机器（比如渲染机没有 H 盘）时，
  先把文件拷过去、用本机绝对路径加载，加载完再把属性改回惯例路径——数据已经在 Actor 里序列化了，
  属性只当注释用。
- **rig 资产命名**：跟已有个乐手对齐，人物 `..._Drummer_CtrlRig`、乐器 `..._DrumKit_CtrlRig`。
  生成方式：`unreal.ControlRigBlueprintFactory.create_control_rig_from_skeletal_mesh_or_skeleton(mesh)`，
  再 `rename_asset` 到目标路径。
- 5.8 的工厂产出的是老的 `ControlRigBlueprint`（不是新的 runtime asset），与工程里现有乐手一致，图表复制才走得通。

## 3. Sequencer：一切初始化都从这里反查 rig

**插件的 rig 定位方式是「扫当前打开的序列里的 Control Rig 轨道，看绑的是哪个 Actor」**——
没有打开的序列、没有绑轨道，第 5 步之后全部报「找不到 rig」。所以这一步是硬前置。

```python
binding = unreal.MovieSceneSequenceExtensions.add_possessable(sequence, actor)
track = unreal.ControlRigSequencerLibrary.find_or_create_control_rig_track(
    world, sequence, rig.get_control_rig_class(), binding)     # 注意参数顺序
```

- 一个绑定对应一个演员；鼓手要加两条：人物骨骼（rig 根控件 `controller_root`）、鼓组（rig 根控件 `drumkit_control`）。
- 打开哪个序列：鼓手用 `/Game/我开始摇滚了`，钢琴 `/Game/双钢琴`，其余同理——用同乐器已经在演戏的那个序列，
  这样第 9 步能直接抄图，不用的绑定留着不影响。
- 保存后重开一次核对：绑定的名字应与骨骼 Actor 的 label 一致（`米娅_Body` / `米娅_DrumKit`）。

## 4–6. 初始化控件与映射变量

顺序不能换：**配置已加载 → 序列已绑 rig → 初始化控件 → 初始化乐器 → 建映射变量**。

- 演奏者控件：`assembly.setup_performer_control_rig(actor)`（内部走 `SetupAllObjects`），
  建 `base_root`→`controller_root` 一套控件，并在 rig 上加 `BoneControlPairMapping` 变量。
- 乐器控件：`assembly.initialize_instrument_control_rig(actor)`（鼓手走 `InitializeDrumKit`），
  给鼓组 rig 建每个鼓件的 `*_beat` 控件和同名 float 通道（形态键驱动就靠这些通道）。
- 映射变量：`assembly.init_bone_control_mapping(actor)`。**变量布局变化会顺带同步编译一次蓝图**
  （`FControlRigAssetHandle::CommitVariableChange` 里对老蓝图调了 `FKismetEditorUtilities::CompileBlueprint`），
  所以建完就能直接写值。手工在编辑器里做时对应「Initialize → 打开 Control Rig 编辑器 Compile → 保存」。
  如果绕开这个入口直接改蓝图变量（比如用 `BlueprintEditorLibrary` 自己加变量），记得自己补一次
  `unreal.BlueprintEditorLibrary.compile_blueprint(rig_asset)`，否则变量名在 `NewVariables` 里有、
  生成类上却找不到属性，写值会一直失败。

初始化完可以 `assembly.inspect_assembly(actor)` 看一眼：控件数（鼓手 46 个）、映射条目数、两套 rig 是否都解析到。

## 7–8. 骨骼控件映射表

映射表决定「哪个控件摆在哪个骨头的位置上」，是 IK 的前提。**不用逐行点界面，直接写变量**：

```python
pair = unreal.MusicDollBoneControlPairInfo()      # 注意不是 BoneControlPair（那是插件内部的）
pair.set_editor_property("bone_name", "左手首")
pair.set_editor_property("control_name", "H_L")
assembly.set_bone_control_mapping(actor, pairs)
assembly.sync_bone_control_mapping(actor)         # 同步到 14/14 才算成
```

- 真正要填的只有 14 条（其余控件由图表算）：`controller_root` / `H_L,R` / `I_L,R` / `M_L,R` / `R_L,R` / `P_L,R` /
  `F_L,R` / `Head_Control`。
- **现成模板从同类乐器、已在序列里绑着的那位乐手身上读**：`assembly.get_bone_control_mapping(那位)`。
  本工程鼓手位的模板是**夜兰**（`BB_夜兰` 才在「我开始摇滚了」里；辛焱的 rig 不在这个序列里，读不到）。
- **骨骼名要按命名风格换算**，不同模型不通用：

  | 模板（夜兰） | 米娅 | 规则 |
  |---|---|---|
  | `手首_L` | `左手首` | `_L/_R` 后缀 → `左/右` 前缀 |
  | `人指先_L` | `左人指３_tip` | `先` → `３_tip` |
  | `足首D_R` | `右足首D` | 同上 |
  | `上半身3` | `上半身2` | 米娅没有上半身3，就近落到上半身2 |
  | `親指先_L` | `左親指２_tip` | 同上 |

  脚本的做法是「先按规则生成候选名 → 到目标 rig 的骨头集合里查存在性 → 一个都查不到就报出来」，不要硬套。
- 同步成功的判据是**控件全局坐标 == 对应骨头的全局坐标**（脚本里会核对 H_L/H_R/F_L/Head_Control）。

## 9–10. 抄图表（控制系统的实体）

界面上是「选中源 rig 的所有节点 → 复制 → 粘到新 rig → 逐个改骨骼名」。脚本走同一条路的文本形态：

```python
text = source.get_controller().export_nodes_to_text(node_names, True)     # 整张图导出
target.get_controller().import_nodes_from_text(text, True)                # 整段导入
```

三步改造，缺一不可：

1. **导进来**：节点、连线、注释全过来了；米娅的 rig 图表原本是空的，导入后 82 个节点。
2. **换骨骼名**：骨骼引用在引脚默认值里，形如 `(Type=Bone,Name="手首_L")`。**文本替换不可靠**
   （折叠节点内部图表替换不到），正确做法是导完之后遍历所有图表的引脚改默认值：
   - `rig.get_all_models()` 拿到顶层图和每个 `CollapseNode_*_ContainedGraph`；
   - 每张图用 `root_controller.get_controller_for_graph(model)` 取自己的 controller；
   - 递归 `pin.get_sub_pins()`，找 `cpp_type` 是 `FRigElementKey`/`FCachedRigElement` 且默认值里带
     `Type=Bone` 的引脚，`set_pin_default_value(pin_path, 新值)`。
   本次实测：顶层 41 处 + 折叠图里 41 处，改完只剩 3 处 `None` 占位。
3. **补没有的骨头**：米娅没有 `stick_L/R` 骨头（鼓槌是挂 socket 的独立 Actor），那两处引用改指 `左手首/右手首`，
   鼓槌自然跟着手腕走；`上半身3`、`親指先` 按上表就近落。

鼓组（第 10 步）结构很小（3 个节点）：`向前解析` → `Apply Float Channels To Curves`，
通道清单在 `常量 RigElementKey` 节点的 `Value` 引脚里。**这份清单是源乐手自己的控件名，必须换成新乐手的**：

```python
value = "(" + ",".join('(Type=Control,Name="%s")' % name for name in beat_channels) + ")"
```

`beat_channels` 就是新鼓组 rig 层级里那些以 `_beat` 结尾的控件（米娅 11 个）。漏了这步，通道名对不上，
鼓组形变一个都不会动。

最后两个 rig 都 `compile_blueprint` + `save_asset`。

## 11. 数据文件

| 文件 | 内容 | 注意 |
|---|---|---|
| `<角色>_blender.drumkit` | 鼓件定义（name/components/limbs/special_actions） | 鼓件配置**可共享**：米娅和辛焱用同一套鼓组，文件里 `name` 写着「辛焱」是正常的，不要改 |
| `<角色>_unreal.drummer` | 各鼓件/状态下的记录器位姿（UE 坐标） | 由 Blender 侧 `export_drummer(..., for_unreal=True)` 生成；插件导入时**不做坐标换算**，给错版本位姿会整个歪掉 |
| `<角色>_<曲子>.beatbloom` | 动画数据的索引 | 只有两个字段：`animation_path`、`shape_key_animation_path`，都是**绝对路径** |
| `*.animation` | 真正的关键帧数据（人物 + 形态键） | 换机器时这两个文件要一起拷，否则生成动画时读不到数据、序列里一个键都不会有 |

**生成 Unreal 版的演奏者数据（Blender 侧）**：

```python
from music_doll_blender.beat_bloom.io import export_drummer
export_drummer(out_path, skeleton_object, drumkit_dict, for_unreal=True)
```

界面上对应「MusicDoll 面板 → 导出到 Unreal」那个按钮；`.blend` 里骨架的 `beat_bloom_state_data`
就是被导出的状态数据，所以只要那个模型装好了鼓组控件并记过状态，就能直接现导（`scripts/export_drummer_unreal.py`）。

`is_unreal` 的含义：位置 Y 取反、旋转取反射共轭。Rust 侧生成动画时也靠这个标志判断左右关系。

## 12. 生成动画（第 11–12 步的落地）

```python
assembly.import_performer_data(actor, drummer_path)          # 导入记录器位姿
actor.set_editor_property("animation_file_path", beatbloom)  # 动画数据索引
unreal.BeatBloomAnimationProcessor.generate_all_animation(actor)
```

判成功的办法：Control Rig 段落里的参数/通道/键数。米娅实测（猪猪侠那首，27 700 帧）：

| 绑定 | 参数 | 通道 | 键 |
|---|---|---|---|
| 米娅_Body | 46 | 406 | 62 490 |
| 米娅_DrumKit | 12 | 20 | 5 258 |
| 夜兰_drummer（对照） | 50 | 406 | 80 797 |

数键用 `section.get_parameter_names()` / `section.get_all_channels()` + `channel.get_num_keys()`
（`get_all_keyed_channels` 在 Python 里没有暴露）。

## 13. 怎么在远程 / 无桌面环境跑

渲染机（192.168.31.99）上没有可交互桌面，编辑器要带 `-nullrhi` 启动，否则 D3D 交换链创建直接 Fatal：

```bat
"F:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" ^
  "D:\KeyRipple\KeyRipple.uproject" -nullrhi -nosplash -nopause -log
```

编辑器启动时 `Content/Python/init_unreal.py` 会挂一个轮询器（`kr_agent_boot.py`），盯 `D:\kr_import\ue_jobs\*.py`，
执行完把结果写成 `out\<脚本名>.json`。本目录 `scripts/ue_job.ps1` 是客户端：
上传 → 原子 move 进任务目录 → scp 取回结果。用法：

```powershell
.\scripts\ue_job.ps1 -JobPath .\scripts\verify_performer.py
```

不用远程投递器时，这些脚本在编辑器 Python 控制台 / `-ExecutePythonScript=` 里一样能跑，改脚本顶部的 `CONFIG` 即可。

**收尾不要关编辑器**：干完活把编辑器留在运行状态（开着 BigCollection），作者会登录进去自己看效果。

### 让编辑器出现在作者的桌面上（会话问题）

这是这套流程里最容易白忙一场的地方，机制先讲清楚：

- 通过 SSH 登录，进程落在 **session 0（服务会话）**。从那里起的图形程序，作者在桌面上**看不到**；
  带 `-nullrhi` 的编辑器照样能跑逻辑、能接作业脚本，但它在作者那边等于不存在。
- 反过来，**从 session 0 也查不到别的会话的窗口**：`Get-Process UnrealEditor` 的 `MainWindowHandle` 恒为 0、
  `tasklist /V` 的窗口标题恒为「暂缺」。**别拿这两个信号判断「编辑器没起来」**——它在作者的 RDP 会话里好着呢。
- 要让编辑器落在作者的交互会话里：建一个带 `/it` 的计划任务再运行（`scripts/launch_editor_visible.ps1` 就是这套）：

  ```cmd
  schtasks /create /tn DSH_UnrealEditor /tr D:\kr_import\tools\_start_editor.cmd ^
      /sc once /st 23:59 /ru administrator /it /f
  schtasks /run /tn DSH_UnrealEditor
  ```

  实测这样起来的进程 `SessionId = 1`（作者的 RDP 会话），能看见、能操作。
  `schtasks` 的 `/tr` 遇到带空格的引号路径会被拆散（报「无效参数/选项 - 'Files\Epic'」），
  所以动作要写成一个小小的 `.cmd` 包装（纯 ASCII + CRLF），不要在 `/tr` 里直接塞带引号的 exe 路径。
- **停编辑器只按 PID 杀，不要 `taskkill /IM UnrealEditor.exe /F`**：那会把作者自己手动开着的那份一起杀掉
  （踩过：作者正在目检，我为了换 DLL 全杀，他的编辑器直接消失）。先 `tasklist` 看清哪个 PID 是自己的。
- **两台机同一工程只留一个编辑器**：一个在服务会话、一个在作者会话，会互相抢资产锁、抢同一份日志，
  排查时完全是噪声。要么就用作者开的那份，要么就关掉自己的再起作者的。

### 插件二进制的部署

改过插件 C++ 之后：**在本机编译，把产物拷到渲染机**（渲染机只当运行环境）：

```powershell
& "G:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" `
    KeyRippleEditor Win64 Development -project="H:\stage_1\KeyRipple\KeyRipple.uproject" -waitmutex
```

产物在 `H:\stage_1\KeyRipple\Plugins\MusicDoll\Binaries\Win64\UnrealEditor-MusicDoll*.dll`，
连同 `Binaries\Win64\UnrealEditor-KeyRipple.dll` 一起拷到渲染机同名目录（编辑器必须先关，否则 DLL 被占用）。

**两台机器的插件源码不一定同版**：本机 `H:\stage_1\KeyRipple` 可能是比渲染机 `D:\KeyRipple` 新的版本
（例如 BeatBloom 的「打法」字段只在新的这边）。**DLL 必须成套拷**：只换 MusicDollCommon/Toolset 而不换
`UnrealEditor-BeatBloomUnreal.dll`，类布局不一致，读出来的数字会变成垃圾（踩过：`RecorderTransforms.Num()`
读出 -257）。动手前先比一下 `BeatBloomUnreal.h` 这类头文件的哈希，确认两边同版；不同版就把整套插件 DLL 一起拷。

**内存注意**：这台机器只有 16 GB，UE 编辑器 5~6 GB + UBT 3.5 GB 就会触发内存杀进程。编译前把 Blender / 微信 /
达芬奇 / MSST 这类吃内存的进程关掉；编译失败先看日志里有没有 `Low on memory ... Kill threshold`。

## 14. 验收清单

`scripts/verify_performer.py` + `scripts/import_and_generate.py` 一次读全：

| 检查 | 期望（米娅实测） |
|---|---|
| 关卡树 | `BB_米娅` 下挂 Body / DrumKit / Stool；直接子级相对变换 0/0/1；两根鼓槌的 `socket` 分别是 `Stick_L/Stick_R`；这一组全在 Outliner 的 `players` 目录下 |
| 引用 | `SkeletalMeshActor` = 米娅_Body，`DrumKit` = 米娅_DrumKit，配置 10 个鼓件、165 个记录器 |
| 演奏者 rig | 651 骨头 / 46 控件 / 30 曲线 / 82 节点；变量 `BoneControlPairMapping` 存在 |
| 映射表 | 14 条，且 `H_L` 控件全局坐标 == `左手首` 骨头全局坐标 |
| 鼓组 rig | 2 骨头 / 12 控件 / 11 `_beat` 曲线 / 3 节点；常量节点清单是米娅自己的 11 个通道 |
| 序列 | `我开始摇滚了` 里有 `米娅_Body`、`米娅_DrumKit` 两个绑定，各有一条 Control Rig 轨道 |
| 图表骨骼引用 | 没有任何指向不存在骨头的引用（只剩 `None` 占位） |
| 生成结果 | 米娅_Body 62 490 键、米娅_DrumKit 5 258 键（量级与夜兰同曲对照） |

**能读到的都只是「结构对了」**：控件摆没摆对、手指 IK 好不好用、鼓组形变是否跟着敲、动画好不好看，
要进编辑器看、要播一遍——这一步由作者本人做。

## 15. 脚本

| 脚本 | 对应步骤 | 说明 |
|---|---|---|
| `assemble_performer.py` | 1–2 | 生成/重建 `BB_` 一组、填引用、加载配置、生成两套 rig |
| `bind_in_sequencer.py` | 3 | 加绑定 + 建 Control Rig 轨道 |
| `setup_control_rig.py` | 5–6 | 初始化演奏者控件、乐器控件、映射变量（含自动编译） |
| `fill_bone_mapping.py` | 7–8 | 从模板乐手读语义 → 换名 → 写表 → 同步 |
| `copy_control_rig_graphs.py` | 9–10 | 跑两趟：`MODE="import"` 搬图表 → `MODE="patch"` 递归改引脚 + 修鼓组通道清单 |
| `import_and_generate.py` | 11–12 | 导入演奏者数据 → 生成动画 → 量键数 |
| `export_drummer_unreal.py` | 前置（Blender） | 从 `.blend` 导出 `is_unreal=true` 的 `.drummer` |
| `verify_performer.py` | 验收 | 一次读全上面那张表 |
| `ue_job.ps1` | 运行 | 投递到远程常驻编辑器并取回结果 JSON |
| `launch_editor_visible.ps1` | 运行 | 用计划任务 `/it` 把编辑器起在作者的交互会话里（这样他才看得见） |
| `build_player.py` / `add_sockets.mjs` / `send_job.ps1` | 零件拼装的旧脚本 | 早期一次性脚本，仍可用 |

所有脚本顶部都有 `CONFIG`，角色名、资产路径、序列路径、模板乐手都在那里改。

## 16. 踩过的坑

1. **没有打开的序列 → 所有初始化都失败**：插件的 rig 定位靠扫描当前序列的 Control Rig 轨道，报错只会说「找不到 rig」。
2. **初始化后不编译就写映射变量 → 写不进去**：变量在蓝图上是「加了但没编译成属性」。工具集的 `InitBoneControlMapping`
   现在会同步编译；绕开它自己加变量时要自己补 `compile_blueprint`。
3. **结构体字段名在 Python 里是去掉 `b` 前缀的**：`bSuccess` → `success`、`bSequencerOpen` → `sequencer_open`。
   按 UE 里的原名取会抛 `has no attribute`，用 `getattr` 兜两种写法再判。
4. **文本替换改骨骼名不可靠**：折叠节点内部图表替换不到，必须按图表+引脚改默认值。
5. **`BoneControlPair`（插件内部结构）≠ `MusicDollBoneControlPairInfo`（工具集入参）**：传错类型报 `Cannot nativize`。
6. **鼓组的通道清单是「源乐手」的**：只抄节点不改清单，形变静默不动。
7. **辛焱的 rig 不在「我开始摇滚了」里**（只有夜兰在）：想抄模板先确认目标序列里到底绑着谁。
8. **数据文件路径跨机器失效**（渲染机没有 H 盘）：拷过去加载完再把属性改回惯例路径；
   `.beatbloom` 里的两个 `.animation` 路径也要一并处理，否则生成动画静默产出 0 个键。
9. **DLL 不能跨源码版本混装**：只换部分插件 DLL，类布局不一致会长出垃圾数字（-257 条记录器）。成套拷。
10. **子级变换要按相对变换判断**：`get_actor_location()` 是世界坐标，挂在父级下面时一定等于父级，
    看起来"没归零"其实是读错了对象。
11. **形态键 fbx 被当静态网格导**：没有蒙皮数据时形态键静默丢失，导入后一定要数 `morph_targets`。
12. **socket 会随重导人物网格一起消失**：重导后要重建 socket，否则鼓槌挂在空名字上（attach 仍返回 True）。
13. **`StaticMesh.materials` 在 Python 里 protected**：读材质槽要从 SkeletalMesh 读。
14. **编辑器必须 `-nullrhi` 才能在无桌面会话里跑**：否则初始化 D3D 交换链直接 Fatal；代价是没有视口截图。

## 17. 参照

- 导出那半边：`music-doll-export-to-fbx`（闸门、父级判定、烘焙、manifest 字段含义）
- Blender 里的控件与 `BB_` 空物体：`music-doll-instrument-controls`
- 插件工具集：`MusicDollToolset.MusicDollTools`（换数据文件 / 一键生成动画）+ `MusicDollToolset.MusicDollAssemblyTools`
  （装配用，11 个函数：`SetPerformerReferences` / `LoadPerformerConfig` / `SetupPerformerControlRig` /
  `InitializeInstrumentControlRig` / `InitBoneControlMapping` / `GetBoneControlMapping` / `SetBoneControlMapping` /
  `SyncBoneControlMapping` / `ExportPerformerData` / `ImportPerformerData` / `InspectAssembly`）
