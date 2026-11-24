---
name: music-doll-instrument-controls
description: 给已经用 music-doll-rig 改造过的演奏者安装 MusicDoll 乐器控件（MusicDoll 初始化 → 乐器 setup all objects → 先把 controller_root 跟到人物颈骨/胸骨/指定锚点 → 再把实际控件的位置/旋转对齐到 test 控件 → 替换人物约束里的 test 引用 → 验收并清理）。内置 StringFlow 提琴、KeyRipple 钢琴、ZhengDrift 古筝、BeatBloom 架子鼓、FretDance 吉他、BellowsPulse 手风琴适配器。当用户说「让这个模型演奏某种 MusicDoll 乐器」「给米娅装一套小提琴/钢琴/古筝/架子鼓/吉他/手风琴控件」「把 test 控件换成真正的乐器控件」时使用。
---

# MusicDoll 乐器控件安装

## 这套东西解决什么

`music-doll-rig` 改造完骨架后，会在人物手上、脚上留一套**临时 test 控件**
（`H_L_test` / `H_R_test` / `HP_*_test` / `T_I_M_R_P_*_test` / `F_*_test` / `FP_*_test`）。
它们只是用来验收骨架的：IK、手掌复制旋转、极向量都指向它们，位置就是骨骼 rest 位置。

MusicDoll 的乐器模块（小提琴 = `string_flow`）在 `setup_all_objects` 时会生成**自己的一整套实际控件**
（`H_L` / `HP_L` / `1_L`…`4_L` / `pole_1_L` / `TP_L` / `F_L` / `FP_L` / `Bow_Controller` …），
刚建出来时全部堆在原点。要让人物真正被这套控件驱动，必须：

1. **MusicDoll 初始化**：登记演奏者、骨骼、乐器，建立命名空间；
2. **setup all objects**：让乐器模块生成完整控件体系；
3. **对齐**：把每个实际控件摆到它要替换的 test 控件的位置与旋转上；
4. **替换**：进人物骨架的约束器，把 `target` / `pole_target` 里的 test 控件换成实际控件；
5. **验收**：对齐误差、rest 网格、极向量、同一动作下 test 与实际是否给出同一姿态；
6. **清理**：删除 test 控件，另存新文件。

判断清楚映射之后，这五步是确定性的；难的是**知道哪个 test 对应哪个实际控件**，以及
不要破坏乐器模块自己的层级、驱动和极向量设计。

## 什么时候别用它

- 文件没有经过 `music-doll-rig`（没有 test 控件、`MusicDoll_Rig_Progress` 不是 DONE）——先做骨骼改造；
- 文件里有多套骨架 / 多套演奏者——先用 `--armature` 指定，别让脚本自己猜；
- 只想看骨架、不动文件——这不是本 skill 的活；
- 乐器模块本身还没 `setup_all_objects` 或控件命名表变了——先核对模块源码，再改映射表。

## 前置条件

1. **插件已安装并启用**：`music_doll_blender`。装的是哪份代码很重要——改过 `src/` 后要
   `python scripts/make_zip.py` 同步到插件目录，再在 Blender 里禁用/启用插件（或重启）。
   无头运行用 `bpy.ops.preferences.addon_enable(module="music_doll_blender")`，脚本里已经做了。
2. **演奏者名字**：只能用英文字母和数字、且以字母开头（`Mia` / `Player01`）。
   这个名字同时是对象后缀，初始化后骨架会变成 `米娅-星彩_arm_Mia`、Mesh 变成 `米娅-星彩_mesh_Mia`。
3. **乐器物体可选**：文件里没有小提琴琴体时，只装控件体系，`md_instrument_obj` 留空；
   以后导入琴体再 `--instrument-object` 重跑，或手动把琴体绑到 `controller_root`。
4. **test 控件完整**：至少 28 个（手 8 + 手指 20）。
5. **不要在原始 rig 文件上直接改**：脚本默认另存 `<原名>_<乐器>.blend`。

## 流程

```
输入：rig 改造完成的 .blend + 演奏者名 + 乐器类型 [+ 乐器物体]
  1. 初始化演奏者         → Performers/<名字>、Body_<名字>、Instruments_<名字>、addons_<名字>
  2. 乐器 setup_all_objects → Controllers_<名字> 下的整套实际控件、ext 驱动、极向量
  3. 先对齐 controller_root → 吉他/手风琴跟胸骨、小提琴/中提琴跟颈骨、大提琴/竖琴用指定锚点
  4. 实际控件对齐 test      → 位置 + 旋转（保留控件自身缩放）
  5. 替换人物约束引用       → target / pole_target / 驱动 / 修改器 / 父级
  6. 验收 → 删除 test → 另存
```

### 1. MusicDoll 初始化

对应 UI 的「角色选择器 → 新建角色（初始化角色）」，实际调用：

```python
from music_doll_blender.common import performer_utils
performer = performer_utils.get_or_create_performer(
    performer_name, performer_name, instrument_id,
    target_skeleton=armature, target_instrument=instrument_object)
```

它会：

- 在 `Performers` 下建 `<名字>` 集合，写入 `md_name` / `md_instrument` / `md_skeleton`；
- 建 `Body_<名字>`、`Instruments_<名字>`、`addons_<名字>`；
- 把骨架和它的 Mesh 改名为 `<原名>_<名字>` 并归到 `Body_<名字>`；
- 建演奏者根空物体 `<乐器缩写>_<名字>`（小提琴是 `SF_Mia`），骨架挂到它下面；
- 已存在同名字演奏者时直接沿用（幂等），但会检查乐器是否一致。

### 2. setup all objects

```python
from music_doll_blender.string_flow.config import StringFlowConfig
config = StringFlowConfig(
    performer_suffix=performer.name,
    target_skeleton=performer.target_skeleton,
    target_instrument=performer.target_instrument,
    performer_name=performer.name,
    instrument_type="violin")
config.setup_all_objects()
```

小提琴生成的主要控件：

| 类别 | 控件 | 备注 |
|---|---|---|
| 手掌 / 手肘极向量 | `H_L` `H_R` `HP_L` `HP_R` | `HP_*` 是肘部极向量 |
| 左手手指 | `1_L`…`4_L`、`T_L` | `1`=食指、`2`=中指、`3`=无名指、`4`=小指 |
| 右手手指 | `1_R`…`4_R`、`T_R` | 与 `H_R` 一起挂在 `Bow_Controller` 下 |
| 手指极向量 | `pole_1_L`…`pole_4_L`、`TP_L`（右手同理） | 挂在 `ext_*` 下 |
| 脚 IK / 膝盖极向量 | `F_L` `F_R` `FP_L` `FP_R` | StringFlow 里「仅创建，不参与数据传递」 |
| 乐器根 / 弓 / 触弦点 | `controller_root` `Bow_Controller` `String_Touch_Point` | 固定乐器根 |
| ext 辅助控件 | `ext_1_L`…`ext_T_R` | 位置由 driver 推、+X 由 Damped Track 指向手掌 |

**刚建出来的实际控件全在原点**（`create_or_update_object` 用 `location=(0,0,0)`），
所以第 4 步必须逐个摆。

### 3. 先对齐 controller_root（所有其它控件对齐的前置条件）

`controller_root` 是乐器控件的父坐标系：`H_L` / `H_R` / `HP_*` / 手指 / `Bow_Controller` 都挂在它下面。
它没定下来就摆子控件，等于在错的坐标系里摆；它如果摆完子控件之后再动，整套控件会跟着平移/旋转，
前面的对齐全部作废。所以**这一步必须排在第 4 步之前**。

按乐器的规则：

| 乐器 | `controller_root` 对齐到 | 方式 |
|---|---|---|
| 吉他（FretDance）/ 手风琴（BellowsPulse） | 胸骨（MMD 常用 `上半身2`） | Copy Location + Copy Rotation |
| 小提琴 / 中提琴（StringFlow） | 颈骨（MMD 常用 `首`） | Copy Location + Copy Rotation |
| 大提琴（StringFlow `cello`） | 使用者指定的**尾钉位置** | 必须先给 `--anchor-object` 或 `--anchor-position`，否则中止 |
| 竖琴（HarpGlide） | 使用者指定的**支点位置** | 同上 |
| 其它乐器 | 无要求 | 保持原位，不动 |

为什么不能省：

- 乐器控件不是独立存在的，它们以 `controller_root` 为父级；根节点在原点还是在颈骨，决定了子控件
  的本地坐标，也决定了人物转头/弯腰时乐器跟不跟。
- 如果先摆子控件、再给根节点加跟随约束，根节点会带着所有子控件一起跳到颈骨/胸骨，
  原来对齐到 test 的世界位置就全丢了。
- 对齐后 `controller_root` 已不在原点，子控件的本地坐标会变；第 4 步按**世界位置**对齐，
  所以最终仍会落在 test 控件的位置上。

实现细节：

- 约束用 `COPY_LOCATION` + `COPY_ROTATION`，`owner_space='WORLD'`、`target_space='WORLD'`、
  `mix_mode='REPLACE'`；
- Copy Location 默认取骨骼 **head**（`head_tail=0`）；Copy Rotation 取骨骼朝向。
  如果某个乐器要以颈骨末端（下巴）为根，把 `head_tail` 改成 1，或直接用一根位于下巴的辅助骨；
- 手风琴模块的 setup 会先建目标留空的 `COPY_LOCATION`/`COPY_ROTATION`（见 `bellows_pulse/config.py`
  的 `CONTROL_CONSTRAINTS`），安装脚本应**填目标**，不要重复建；
- 目标骨骼名不是所有模型都一样：米娅是 `首`（胸骨用 `上半身2`）；`--follow-bone` 可覆盖；
  找不到时脚本会列出含 `首` / `neck` / `上半身` / `胸` / `chest` 的候选；
- 对齐后必须验证 `controller_root.matrix_world == armature.matrix_world @ pose_bone.matrix`；
  米娅实测误差 `0.000000000 m / 0.000000000°`；
- 大提琴/竖琴没有锚点时必须**直接报错停下**——不要猜尾钉/支点，猜错整个乐器会飘到错误的位置。

验证跟随是否真的生效：把颈骨转 5°，`controller_root` 的旋转也应转约 5°；把颈骨转 15°，
`H_L` 这类子控件应明显跟着走（米娅实测 `H_L` 移动 0.122 m）。如果根节点不动，就是约束没接上。

### 4. 实际控件对齐 test 控件

规则只有一句：**位置和旋转抄 test，缩放保留实际控件自己的**。

- 实际控件的类型/缩放因乐器而异：StringFlow 是 `primitive_cube_add(size=0.2, scale=0.1)`
  的 MESH（世界缩放 0.1）；钢琴、FretDance 等是 EMPTY 显示体（scale 1.0，手指 ext 可能是 0.7）。
  test 控件是空物体、缩放 1.0。直接 `matrix_world = test.matrix_world` 会覆盖实际控件自己的缩放
  （StringFlow 会放大 10 倍），必须拆成 loc/rot 后按实际控件自己的 scale 重新组合。
  不要按“一定是 0.1 方块”去写死检查，先看该乐器模块创建的是什么类型。
- **按父级深度从浅到深摆**，每摆完一层 `view_layer.update()`：
  `H_L`/`H_R`/`HP_*` 先摆，再摆手指，最后摆极向量。
  父级还没更新就摆子级，子级拿到的是旧的父矩阵，位置会错。
- **极向量最后摆**：`pole_*` 挂在 `ext_*` 下，而 `ext` 的位置是 driver（`ext = 2×手指`，
  右手是 `2×手指 − 手掌`）+ Damped Track 指向手掌。必须等手指摆好、驱动算完，
  再把 pole 的世界位置对到 test pole；否则 driver 一更新就把 pole 推走。
- 极向量只关心**位置**（IK 的 pole target 不用朝向），但为了统一，旋转也一起抄。

### 5. 替换人物约束引用

人物骨架上的 `MD_*` 约束是 rig skill 加的：

| 约束 | 目标 | 极向量 |
|---|---|---|
| `MD_IK_arm.L/R` | `H_*_test` | `HP_*_test` |
| `MD_Rot_arm.L/R` | `H_*_test` | — |
| `MD_IK_leg.L/R` | `F_*_test` | `FP_*_test` |
| `MD_Rot_leg.L/R` | `F_*_test` | — |
| `MD_IK_index/middle/ring/pinky/thumb.L/R` | `I/M/R/P/T_*_test` | `I/M/R/P/T_*_pole_test` |

替换时要扫**所有引用**，不只 `constraint.target`：

- `constraint.target` 和 `constraint.pole_target`（极向量最容易漏）；
- 物体约束、修改器 `object`/`target`、驱动变量 `variable.targets[].id`、对象父级；
- **test 控件自己之间的父子关系不要算“残留引用”**（`I_L_test.parent == H_L_test`）。
  它们马上要被删除；扫描时跳过 test 对象本身，否则会误报。

替换后 `MD_IK_arm.L` 的目标应是 `H_L_Mia`、极向量 `HP_L_Mia`；
`MD_IK_index.L` 的目标 `1_L_Mia`、极向量 `pole_1_L_Mia`。

### 6. 验收与清理

安装脚本里的硬判据：

| 项目 | 判据 | Mia 实测 |
|---|---|---|
| controller_root 对齐 | 与颈骨/胸骨矩阵一致；骨骼转 5°，根节点也转 ~5° | 0 m / 0°；4.99997° |
| 控件对齐 | 位移 ≤ 1e-5 m、旋转 ≤ 0.01° | 1.34e-7 m / 0° |
| rest 网格 | 替换前后 ≤ 1e-5 m | 1.74e-6 m |
| 残留引用 | 0 处 | 0 |
| 极向量 | 与关节弯曲方向夹角 ≤ 2° | 6 条链全 0° |
| 动作等价 | 同一动作 test 与实际逐骨对比 | 手臂 1.17 µm、手掌 1.28 µm、腿 1.17 µm；手指 0.98 mm / 3.18°（见下） |

**为什么动作验收用「test 与实际逐骨对比」，而不是「目标点误差」**：

- MMD 骨架的 `左ひざ` 等骨上常带 `use_ik_limit_x/y/z = True`（MMD 的 IK 角度限制）。
  把 `F_L` 前移 10 cm，脚踝只走 9 cm、留 1 cm 余量——这是**骨骼自身的限制**，
  不是控件替换错了。test 控件驱动时同样只走 9 cm。
- 所以正确的判据是：同一动作分别由 test 和实际控件驱动，**逐骨姿态必须一致**。
  这样连极向量、IK 限制、复制旋转都一起验证了。
- **不要为了追求“精确到达”去清掉 `use_ik_limit_*`**；那是改骨架，不是本 skill 的职责。

**手指的 1 mm / 3.18° 是设计差异，不是错误**：

- test 体系的极向量是静止的（挂在 `H_*_test` 下，不跟手指）；
- 实际体系的极向量挂在 `ext` 下，`ext = 2×手指`，手指一动极向量就跟着动（实测 1 cm 手指动作，
  极向量移动 2 cm）；
- 因此弯曲平面会有毫米/几度级差异。位置差仍要求 ≤2 mm（Mia 实测 0.98 mm），
  这是可以接受的；不要为了让它“完全一致”去改 `ext`/pole 的层级。

**清理**：确认没有残留引用后，删除 28 个 test 空物体；保留 `MusicDoll_Rig_Progress`，
另写 `MusicDoll_Instrument_Progress` 文本块记录本次安装。默认删除，`--keep-test` 可保留。

## 小提琴映射表（rig skill test → StringFlow 实际）

| test 控件 | 实际控件短名 | 说明 |
|---|---|---|
| `H_L_test` / `H_R_test` | `H_L` / `H_R` | 手掌 |
| `HP_L_test` / `HP_R_test` | `HP_L` / `HP_R` | 手肘极向量 |
| `F_L_test` / `F_R_test` | `F_L` / `F_R` | 脚 IK |
| `FP_L_test` / `FP_R_test` | `FP_L` / `FP_R` | 膝盖极向量 |
| `I_L_test` / `I_R_test` | `1_L` / `1_R` | 食指 |
| `M_L_test` / `M_R_test` | `2_L` / `2_R` | 中指 |
| `R_L_test` / `R_R_test` | `3_L` / `3_R` | 无名指 |
| `P_L_test` / `P_R_test` | `4_L` / `4_R` | 小指 |
| `T_L_test` / `T_R_test` | `T_L` / `T_R` | 拇指 |
| `I_*_pole_test` | `pole_1_*` | 食指极向量 |
| `M_*_pole_test` | `pole_2_*` | 中指极向量 |
| `R_*_pole_test` | `pole_3_*` | 无名指极向量 |
| `P_*_pole_test` | `pole_4_*` | 小指极向量 |
| `T_*_pole_test` | `TP_*` | 拇指极向量 |

数字顺序由 StringFlow 的指法表决定：`1=食指、2=中指、3=无名指、4=小指`，
不要按“从左到右”想当然。

## 用手势记住小提琴的层级

```
SF_Mia
├── 米娅-星彩_arm_Mia
├── controller_root_Mia
│   ├── H_L_Mia → 1_L…4_L、T_L、ext_*_L → pole_*_L / TP_L
│   ├── HP_L_Mia、HP_R_Mia
│   ├── Bow_Controller_Mia → H_R_Mia、1_R…4_R、T_R、ext_*_R → pole_*_R / TP_R
│   └── String_Touch_Point_Mia
├── F_L_Mia、F_R_Mia、FP_L_Mia、FP_R_Mia
└── Instruments_Mia（琴体放这里）
```

两个容易踩的点：

1. **右手不是“手带着手指”**：右手手指和 `H_R` 是 `Bow_Controller` 的兄弟。
   拉弓时动的是 `Bow_Controller`，只动 `H_R` 手指不会跟——这是小提琴“手在弓上”的设计。
   所以动作等价验收不拿 `H_R` 单独平移去和 test 比（test 的手指挂在 `H_R_test` 下，层级不同）。
2. **左手是“手带着手指”**：`1_L`…`4_L`、`T_L` 都在 `H_L` 下，和 test 层级一致，
   所以左手可以完整地做 test/实际逐骨对比。

## 已内置的乐器适配器

`adapters/` 下按乐器放外部适配器；脚本用 `--adapter-file` 加载，不需要改安装脚本。

| 乐器 | `--instrument` | 适配器 | `controller_root` |
|---|---|---|---|
| 钢琴 | `key_ripple` | `adapters/key_ripple.py` | 无要求，保持原位 |
| 古筝 | `zheng_drift` | `adapters/zheng_drift.py` | 无要求，保持原位 |
| 架子鼓 | `beat_bloom` | `adapters/beat_bloom.py` | 无要求，保持原位 |
| 吉他 | `fret_dance` | `adapters/fret_dance.py` | 胸骨 `上半身2`；`--variant finger_style/electric/bass`；模块没有脚控件，用 `fallback_controls` 补 |
| 手风琴 | `bellows_pulse` | `adapters/bellows_pulse.py` | 胸骨 `上半身2`；setup 已建目标留空的约束 |
| 小提琴 / 中提琴 | `string_flow` | 内置（`--variant violin`） | 颈骨 `首` |
| 大提琴 | `string_flow` | 内置（`--variant cello`） | 必须给尾钉锚点 |
| 竖琴 | `harp_glide` | 尚未实测 | 必须给支点锚点 |

外部适配器最小结构：

```python
ADAPTER = {
    "instrument": "key_ripple",
    "controller_root": {"default": {"mode": "none"}},
    "test_to_short": {"H_L_test": "H_L", ...},
    "behavior_samples": [...],
    # 可选：config_module / config_class / config_kwargs，
    # 或 def build_config(performer, variant) 返回 config 实例
    # 可选：fallback_controls，给模块没生成的 test 对照项补空物体
}
```

## 命令

### 安装

```powershell
& "D:\Program Files\Blender Foundation\Blender 5.0\blender.exe" -b --factory-startup `
  -P "H:\music_doll_blender\skills\music-doll-instrument-controls\scripts\install_instrument_controls.py" -- `
  --file "H:\music_doll_blender\temp\rig_work\mia\米娅-星彩.blend" `
  --performer Mia `
  --instrument key_ripple `
  --adapter-file "H:\music_doll_blender\skills\music-doll-instrument-controls\adapters\key_ripple.py" `
  --out "H:\music_doll_blender\temp\rig_work\mia\instruments\key_ripple\米娅-星彩_钢琴.blend" `
  --report "install_report.json"
```

常用参数：

- `--adapter-file`：外部乐器适配器；非 `string_flow` 乐器必填。
- `--variant violin|viola|cello`：StringFlow 的变体；默认 `violin`。`cello` 走「必须指定尾钉」的规则。
- `--follow-bone 首`：覆盖 `controller_root` 跟随的骨骼；小提琴默认 `首`，吉他/手风琴默认 `上半身2`。
- `--anchor-object 空物体名` / `--anchor-position "x,y,z"`：大提琴尾钉 / 竖琴支点；两者都不给时脚本直接报错。
- `--instrument-object 琴体物体名`：文件里已有小提琴 Mesh 时传入；没有就省略。
- `--armature 骨架名`：文件里不止一套骨架时必填。
- `--keep-test`：保留 test 控件（默认删）。
- `--skip-pose-check`：跳过动作等价采样（只做对齐/rest 网格/残留检查；调试用）。
- `--out`：默认在输入文件旁生成 `<原名>_string_flow.blend`；不允许覆盖输入文件。

### 独立验收（test 删除后也能跑）

```powershell
& "D:\Program Files\Blender Foundation\Blender 5.0\blender.exe" -b --factory-startup `
  -P "H:\music_doll_blender\skills\music-doll-instrument-controls\scripts\verify_instrument_controls.py" -- `
  --file "H:\music_doll_blender\temp\rig_work\mia\米娅-星彩_小提琴.blend" `
  --performer Mia --instrument string_flow --variant violin `
  --reference "H:\music_doll_blender\temp\rig_work\mia\米娅-星彩.blend" `
  --report "violin_verify_report.json"
```

非 StringFlow 乐器再加 `--adapter-file`，与安装时同一份适配器。

`--reference` 给 rig 改造原件时，会把最终 rest 网格与原件逐顶点对照（Mia 实测 1.68 µm）。
`--allow-test` 允许 test 控件仍在（只检查它们没被引用，不判失败）。

## 扩展到其他乐器

脚本按「通用流程 + 每种乐器一张映射表」组织；新增乐器只改
`INSTRUMENT_ADAPTERS`（在 `install_instrument_controls.py` 顶部）：

```python
"key_ripple": {
    "config_module": "music_doll_blender.key_ripple.config",
    "config_class": "KeyRippleConfig",
    "config_kwargs": {},
    "controller_root": {
        "default": {"mode": "none"},   # 钢琴类对根节点无要求；吉他/手风琴填 bone
    },
    "test_to_short": {"H_L_test": "H_L", ...},
    "behavior_samples": [...],
}
```

要确认的事：

0. **controller_root 规则**：吉他/手风琴 `{"mode":"bone","bone":"上半身2"}`；小提琴/中提琴
   `{"mode":"bone","bone":"首"}`；大提琴/竖琴 `{"mode":"anchor_required"}`；其它 `{"mode":"none"}`。
   有变体的乐器用 `"variants": {...}` 分开；
1. **实际控件短名**：读该模块的 `add_controllers()` / 命名表，不要猜；
2. **父子关系**：尤其手指是否挂在手掌下、极向量是否挂在 ext 下；
3. **驱动的控件**：被 driver/约束驱动的控件（ext、pole）不能当成普通目标直接摆，
   要等驱动算完再摆；
4. **多乐器 / 多手**：手风琴这类左右键区、多个乐器槽的，映射表要按侧别拆开；
   第一版不要硬套小提琴的 1:1 表；
5. **动作样本**：选 2~4 个不会撞 IK 限制的动作（抬手、转手掌、手指内收、抬腿），
   先跑 `--skip-pose-check` 看对齐，再开动作验收。

当前只实测了 `string_flow / violin`。`cello` 的 `anchor_required` 分支和参数已经接好，
但大提琴的控件映射、动作样本还没实测；竖琴（`harp_glide`）同理。第一次做这两类时，
先 `--skip-pose-check` 核对控件是否齐全、锚点是否正确，再补动作样本。

## 常见问题

**Q：初始化报「名字只能使用英文字母和数字」**
A：`create_performer` 的硬限制；换 `Mia` / `Miya` 这类 ASCII 名字，不要用中文。

**Q：setup 成功，但实际控件都在原点**
A：正常。`create_or_update_object` 只建不摆；第 4 步负责摆。

**Q：对齐后控件变成巨大的方块**
A：把 test 的完整 `matrix_world` 抄过去了，缩放 1.0 覆盖了实际控件自己的缩放（StringFlow 的 0.1 会变成 1.0）。
只抄 loc/rot，scale 用实际控件原来的；钢琴/吉他等 EMPTY 显示体本身是 1.0，不要拿“0.1”去套所有乐器。

**Q：极向量摆完又被推走**
A：`pole_*` 的父级 `ext_*` 有 driver + Damped Track。先摆手指、`view_layer.update()`，
再摆 pole；顺序反了就会被驱动覆盖。

**Q：转头/弯腰时乐器不跟，或 controller_root 还在原点**
A：第 3 步没做，或约束没接上。`controller_root` 必须有 `COPY_LOCATION` + `COPY_ROTATION`，
目标 = 骨架，subtarget = `首`（小提琴）/ `上半身2`（吉他、手风琴），WORLD/WORLD。
先做这一步，再摆其它控件；反过来做会把已对齐的控件整体带偏。

**Q：大提琴/竖琴为什么脚本直接报错**
A：尾钉/支点没有默认值。必须先给 `--anchor-object` 或 `--anchor-position "x,y,z"`，
否则 `controller_root` 没有依据，后面的控件对齐不能做。

**Q：非 StringFlow 乐器怎么跑**
A：用 `--instrument <id> --adapter-file adapters/<id>.py`。安装和验收要用同一份适配器；
适配器里的 `instrument` 必须与 `--instrument` 一致。

**Q：吉他为什么多出 F_L_Mia / FP_L_Mia**
A：吉他模块不生成脚控件，但腿 IK 仍需要目标；适配器的 `fallback_controls` 在 test 脚控件原位
补了空物体，腿约束改指它们。这是正常的，不是多建的垃圾。

**Q：手风琴的 left_bone / right_bone 要不要接**
A：不要。它们是键区骨骼跟随器，目标取决于使用者自己的键区骨骼；安装脚本只处理 controller_root
和 28 个 test 对照项，不应把 left_bone/right_bone 的目标乱填。

**Q：手风琴为什么没有键区记录器**
A：模块只有在骨骼已保存乐器属性时才建 `lb*/kbd_*/rb*` 记录器。先跑一次安装得到控件，
在面板保存设置后再点一次「设置所有对象」；重复 setup 不会重置已摆好的记录器，也不会重复建约束。

**Q：古筝整体移动/缩放后膝盖朝向不对**
A：古筝的脚极向量 `F_L_pole/F_R_pole` 没有父级，不跟 `ZD_Mia` 根走。整体挪人/缩放时要么手动挪 pole，
要么先把它们挂到合适父级；静置演奏不受影响。

**Q：verify PASS 是不是所有乐器专属对象都查过了**
A：不是。通用 verify 只断言 28 项映射、根节点跟随、极向量、动作等价和 rest 网格。
手风琴的 `left_bone/right_bone`、古筝的脚 pole、架子鼓的头部链等模块额外对象，要按各乐器小节人工抽查。

**Q：架子鼓 setup 报 dependency cycle**
A：这是 beat_bloom 模块自身 `Head_Control` / `Look_At` 的循环，验收仍能通过；记录即可，
不要为了消警告去改模块或删对象。

**Q：手指根部的极向量在对齐后仍和 test 不完全一致**
A：rest 下应完全一致（Mia 1.34e-7 m）。如果差很多，检查是不是把 pole 摆在了 `ext` 更新之前。

**Q：替换完约束目标里还有 `_test`**
A：漏了 `pole_target`，或者漏了驱动/修改器里的引用。脚本的 `find_remaining_test_references`
会把这些都列出来；test 控件之间的父子关系不算。

**Q：腿部 IK 到不了目标**
A：先看 `use_ik_limit_*`；MMD 骨骼限制会让大位移留余量。test 控件也一样到不了，
用「test vs 实际逐骨对比」判定，不要清限制。

**Q：右手只动 H_R，手指不跟**
A：小提琴右手手指挂在 `Bow_Controller`，不是 `H_R` 下；拉弓要动 `Bow_Controller`。

**Q：能不能在原始 rig 文件上直接跑**
A：不要。脚本默认另存；原始 rig 文件留着做对照和回退。

## 本机现状（2026-11-24）

米娅的 6 个乐器版本都已用同一套脚本生成并独立验收（`instruments/<乐器>/verify_report.json`）：

| 乐器 | 文件 | `controller_root` | 验收 |
|---|---|---|---|
| 小提琴 | `violin_work/米娅-星彩_小提琴.blend` | 颈骨 `首` | PASS |
| 钢琴 | `instruments/key_ripple/米娅-星彩_钢琴.blend` | 无要求 | PASS |
| 古筝 | `instruments/zheng_drift/米娅-星彩_古筝.blend` | 无要求 | PASS |
| 架子鼓 | `instruments/beat_bloom/米娅-星彩_架子鼓.blend` | 无要求 | PASS |
| 吉他 | `instruments/fret_dance/米娅-星彩_吉他.blend` | 胸骨 `上半身2` | PASS |
| 手风琴 | `instruments/bellows_pulse/米娅-星彩_手风琴.blend` | 胸骨 `上半身2` | PASS |

各版本共同结果：28 个实际控件齐全、0 个 test 残留、6 条极向量链 0°、rest 网格对原件 2.8~3.3 µm；
动作等价手臂/手掌/腿约 1~2 µm，手指约 0.98 mm / 3.18°（实际极向量随手指的设计差异）。

乐器的特殊点：

- **吉他**：模块不生成脚控件，适配器用 `fallback_controls` 在 `F_L_test/F_R_test/FP_L_test/FP_R_test`
  原位补 `F_L/F_R/FP_L/FP_R` 空物体，腿 IK 目标改指这些控件；`controller_root_offset` 保留。
  `--variant finger_style|electric|bass` 会切换 `Instruments` 枚举，不再静默忽略。
  fallback 挂在 `FD_<名字>` 演奏者根、`Controllers_<名字>` 集合，`F_*` 显示 CUBE、`FP_*` 显示 CIRCLE。
- **手风琴**：setup 已建目标留空的 Copy Location/Copy Rotation，安装时填目标；`left_bone/right_bone`
  的目标保持为空（由使用者按自己的键区骨骼接），不要误接。
  注意：模块只在骨骼已保存乐器属性时才建键区记录器；本次输入没有属性，所以只有控件。
  要进引擎，需在面板保存一次设置再点一次「设置所有对象」（可重复跑，约束按类型去重，记录器不重置位置）。
  另外，给 `left_bone` 接目标会让手掌整体位移（只读实验实测 1.141 m），接线后必须重摆手。
- **架子鼓**：setup 会报 `Head_Control` / `Look_At` 的 dependency cycle 警告，这是模块自身行为，
  验收仍通过。模块还有 `stick_L/R`、`Head_Control/Head_Forward/Middle_Hand/Look_At` 等非 28 项控件；
  其中 `Head_Control` 默认停在原点，GUI 录 state 前要把它摆到头部。鼓组物体本身需要 GUI load_drumkit，
  安装脚本只建控件。
- **钢琴**：手指编号是 0..4 = 小指→拇指、5..9 = 拇指→小指，映射表按这个顺序，不能按 `T/I/M/R/P` 直译
  （子代理用 `MD_IK_thumb/index/pinky` 的解剖骨名交叉验证过）；实际控件是 EMPTY，不是提琴的 0.1 MESH。
- **古筝**：拇指极向量是 `TP_L/TP_R`，脚极向量是 `F_L_pole/F_R_pole`；`Middle_Hand/Look_At/Head_Control`
  是模块自带的世界对象，不属于 28 个替换项。脚极向量 `F_*_pole` **没有父级**（模块设计），
  整体平移/缩放古筝根时它们不跟，膝盖朝向可能歪；静置演奏无影响，整体挪人/缩放时要留意。

独立验收只覆盖 28 项映射、根节点跟随、极向量和动作等价；乐器模块自己的额外对象（手风琴跟随器、
古筝脚 pole、架子鼓头部链等）不在 verify 的通用断言里，需要按上面各乐器小节人工抽查。

### 小提琴细节

- 输入：`H:\music_doll_blender\temp\rig_work\mia\米娅-星彩.blend`（rig skill 改造完成，650 骨，28 个 test 控件）
- 输出：`H:\music_doll_blender\temp\rig_work\mia\violin_work\米娅-星彩_小提琴.blend`
- 演奏者：`Mia`，乐器：`string_flow`，变体：`violin`，骨架：`米娅-星彩_arm_Mia`
- `controller_root`：`COPY_LOCATION` + `COPY_ROTATION` 跟随 `首`，误差 `0.0 m / 0.0°`；
  颈骨转 5° 时根节点转 `4.99997°`，颈骨转 15° 时 `H_L` 移动 `0.122 m`
- 控件：28 个实际控件；约束/驱动引用替换 32 处；test 控件已删除
- 对齐：1.34e-7 m / 0°；rest 网格：1.74e-6 m（安装时）/ 1.68e-6 m（对原件）
- 动作等价：手臂 1.17e-6 m、手掌 1.28e-6 m、腿 1.17e-6 m、手指 9.81e-4 m / 3.18°（极向量随手指的设计差异）
- 极向量：6 条链全部 0°
- 未做：小提琴琴体 Mesh 尚未登记（`md_instrument_obj` 为空），需要时导入琴体再 `--instrument-object`；
  实际演奏动画 / `.violinist` 导出不在本 skill 范围内。
- 视觉：只用 Workbench 做了 sanity 抽查；最终观感请作者在 GUI 里确认。

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/install_instrument_controls.py` | 初始化 + setup + controller_root 对齐 + 控件对齐 + 替换 + 验收 + 删 test + 另存 |
| `scripts/verify_instrument_controls.py` | 独立验收：controller_root 跟随、控件齐全、无 test 残留、极向量、动作响应、rest 网格对照 |
| `adapters/key_ripple.py` / `beat_bloom.py` / `fret_dance.py` / `bellows_pulse.py` / `zheng_drift.py` | 各乐器的 test→实际映射、controller_root 规则、动作样本、fallback 控件 |

两个脚本都支持 `--help`；核心判据和实测数字在本文件里，脚本只负责执行。
