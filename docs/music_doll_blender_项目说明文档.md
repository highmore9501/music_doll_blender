# MusicDoll Blender 项目说明文档

> **中文** | [English](music_doll_blender_项目说明文档.en.md)

> 版本：v1.0
> 日期：2026-08
> 适用代码库：`h:\music_doll_blender`
> 本文档依据 `docs/` 目录下的施工文档与 `src/` 实际代码编写，是理解本项目架构、模块划分、数据模型与开发流程的入口文档。

---

## 目录

1. [项目概述](#1-项目概述)
2. [仓库结构](#2-仓库结构)
3. [核心架构：演奏者模型](#3-核心架构演奏者模型)
4. [公共模块 common/ 详解](#4-公共模块-common-详解)
5. [统一 UI 设计](#5-统一-ui-设计)
6. [工具体系](#6-工具体系)
7. [乐器模块详解](#7-乐器模块详解)
8. [数据文件格式汇总](#8-数据文件格式汇总)
9. [开发、部署与验证](#9-开发部署与验证)
10. [关键约定与注意事项](#10-关键约定与注意事项)
11. [新增乐器接入指南](#11-新增乐器接入指南)
12. [文档索引](#12-文档索引)
13. [附录：Unreal ↔ Blender 概念对照](#13-附录unreal--blender-概念对照)

---

## 1. 项目概述

### 1.1 它是什么

MusicDoll Blender 是一个面向 Blender（5.0+）的**统一乐器动画插件**：用一个插件管理所有乐器的演奏动画制作流程，一个 Blender 文件里可以同时放多个不同乐器的演奏者（吉他手、钢琴手、小提琴手……），彼此数据隔离、互不干扰。

它借鉴了 Unreal 侧同名插件 MusicDoll 的架构思路：**一个总框架负责公共部分，每种乐器作为其中一块，大家共用一套规则**。Unreal 侧是 `MusicDollCommon` + 各乐器子模块（`FretDanceUnreal` / `KeyRippleUnreal` / …），Blender 侧对应为 `common/` 公共模块 + 各乐器子包（`fret_dance` / `key_ripple` / …）。

### 1.2 为什么做

本项目的前身是**每个乐器各维护一套独立 Blender 插件**：

| 乐器 | Rust 项目 | 原 Blender 插件 |
| ---- | --------- | --------------- |
| FretDance（吉他） | `fretDance_rust` | `fret_dance_blender` |
| KeyRipple（钢琴） | `key_ripple_rust` | `key_ripple_blender` |
| StringFlow（小提琴） | `string_flow_rust` | `string_flow_blender` |
| ZhengDrift / HarpGlide / WindRise / BeatBloom | 各自 Rust 项目 | 各自 Blender 插件 |

这种"一乐器一插件"模式带来三个问题：

1. **重复代码严重**：每个插件都要实现"创建控制器 → 保存状态 → 生成动画 → 导入导出 → 管理多演奏者"这套流程；
2. **多乐器无法共存**：一个 Blender 文件想同时放吉他手和钢琴手时，两套插件互不相认，容易冲突；
3. **公共功能难以共享**：想给所有乐器加一个公共功能（如修正手指骨骼），每个插件都要各改一遍。

因此决定**把所有乐器收进一个插件**，由公共模块统一管理——这就是 MusicDoll Blender。

### 1.3 设计目标（源自施工文档）

1. 放弃"一个乐器一个插件"模式，改为一个插件管理所有乐器；
2. 内含公共模块（对应 MusicDollCommon），抽离跨乐器通用能力：对象/集合创建、状态存取、动画写入、shape key、导入导出、演奏者复制/迁移等；
3. 设计跨乐器统一的**演奏者模式**：所有乐器共用同一套"演奏者实例"数据模型，仅通过属性区分乐器类型；
4. **分阶段迁移**：初期合并 FretDance + KeyRipple，测试稳定后逐个合并其余乐器（现已全部并入）。

### 1.4 当前状态

- **bl_info**：版本 `0.1.0`，Blender `5.0.0`，作者 BigHippo78，分类 Animation，面板位置 `View3D > Sidebar > MusicDoll`；
- **已迁入 7 个乐器模块**：`fret_dance`（吉他，Phase 1）、`key_ripple`（钢琴，Phase 2）、`zheng_drift`（古筝，Phase 3）、`beat_bloom`（打击乐，Phase 4）、`harp_glide`（竖琴）、`wind_rise`（管乐）、`string_flow`（小提琴）；
- 各乐器施工状态：代码迁移与部署全部完成，Blender 实测由用户手动执行（见各移植施工报告）。

### 1.5 典型使用流程

1. 安装：把 `src\` 改名 `music_doll_blender` 放入 Blender 插件目录，或直接把 `src\` 压缩成 zip 拖入"偏好设置 → 插件"安装；
2. 启用 **MusicDoll Blender** 插件；
3. 在 3D 视图右侧侧边栏找到 **MusicDoll** 面板；
4. 在"角色选择器"里新建角色（名字 + 乐器类型 + 目标骨骼 + 乐器物体）；
5. 在对应乐器子面板点"Setup Objects"搭建控制器；
6. 摆姿势 → "Set/Load State" 存取状态 → 导出人物信息 → 选择动画文件 → 生成动画。

---

## 2. 仓库结构

```
music_doll_blender/
├── src/                          # 全部源代码（压缩此目录即可安装）
│   ├── __init__.py               # 插件入口：注册公共模块 + 各乐器模块
│   ├── common/                   # 公共模块（相当于 Unreal MusicDollCommon；无 __init__.py，命名空间包）
│   │   ├── performer_utils.py    # 演奏者命名空间（核心）
│   │   ├── instrument_base.py    # 统一属性键 / 乐器缩写前缀映射
│   │   ├── object_utils.py       # 集合/物体幂等创建
│   │   ├── state_io.py           # 状态存取（对象↔字典 / 骨骼自定义属性）
│   │   ├── io_utils.py           # JSON 读写 / Unreal 坐标转换
│   │   ├── animation_utils.py    # 动画通用工具（fcurve / shape key / driver）
│   │   ├── ui_utils.py           # 统一主面板 / 角色选择器 / 工具界面
│   │   └── tools/                # 公共工具
│   │       ├── __init__.py       # ToolDef / COMMON_TOOLS
│   │       ├── fix_finger_ik.py  # 修正手指骨骼（所有乐器共用）
│   │       └── bone_controller_mapping.py  # 骨骼/控制器映射
│   ├── fret_dance/               # FretDance 吉他模块（Phase 1）
│   ├── key_ripple/               # KeyRipple 钢琴模块（Phase 2）
│   ├── zheng_drift/              # ZhengDrift 古筝模块（Phase 3）
│   ├── beat_bloom/               # BeatBloom 打击乐模块（Phase 4）
│   ├── harp_glide/               # HarpGlide 竖琴模块
│   ├── wind_rise/                # WindRise 管乐模块
│   └── string_flow/              # StringFlow 小提琴模块
├── docs/                         # 项目说明文档（中/英，随仓库上传）；其余施工文档为内部记录（未上传）
├── music_doll_blender.zip        # 分发包（本地生成，未随仓库上传）
├── README.md                     # 项目介绍（中文）
├── README.en.md                  # 项目介绍（English）
└── .gitignore                    # 忽略 __pycache__/、docs/（除说明文档）、zip
```

### 2.1 每个乐器模块的标准结构

依据《乐器模块迁移工程指南》的标准骨架，`src/<乐器>/` 通常包含：

```
src/<instrument>/
├── __init__.py     # 模块说明（迁移自哪个源插件）
├── enums.py        # 状态枚举 + 物体类型（映射 common.object_utils 字符串）
├── config.py       # <Instrument>Config：命名表 + add_controllers / add_ext_drivers /
│                   #   特殊朝向与约束 / add_recorders / check_* / setup_all_objects /
│                   #   _organize_* / _get_addons_collection / 特殊 driver 注册
├── state.py        # 状态传输（控制器 ↔ 骨骼自定义属性）+ 状态特殊逻辑
├── io.py           # 导入/导出（JSON 键用短名；路径用 SCENE_INFO_PATH）
├── animation.py    # 动画生成（左右手 / 弦 / 特殊朝向 / 清关键帧保留 driver）
├── tools/
│   ├── __init__.py # INSTRUMENT_TOOLS（ToolDef）+ register/unregister
│   └── <tool>.py   # 乐器专属工具实现
└── ui.py           # 属性组 + 面板 + 算子 + rename/duplicate + register/unregister
```

> 结构说明：`config` 内聚"命名表 + 对象创建 + setup"；`state` / `io` / `animation` 各司其职（key_ripple / zheng_drift 采用此简化结构）。fret_dance 另拆了 `object_manager.py` / `base.py`（多重继承 `BaseState`），两种皆可，新迁移建议沿用简化结构。

---

## 3. 核心架构：演奏者模型

这是整个插件的基石，所有乐器共用同一套模型。设计参照 Unreal 侧：`AInstrumentBase`（Actor）= 演奏者实例，属性随实例保存。

### 3.1 演奏者实例 = Performers 根下的一个 Collection

`Performers` 是场景中的**顶层根集合**（演奏者注册表），其下**每个子集合就是一个演奏者实例**。

```
Performers/                          ← 顶层根集合（演奏者注册表）
└── <演奏者名>（Collection）         ← 演奏者实例（身份属性 md_* 存其上）
    ├── <乐器缩写>_<演奏者名>（Empty）← 演奏者根空物体（整体移动/缩放）
    ├── Body_<后缀>                  ← 骨骼 + Mesh
    ├── Instruments_<后缀>           ← 乐器物体
    └── addons_<后缀>                ← 各乐器的控制器/记录器
        ├── Controllers_<后缀>
        │   ├── controller_root（EMPTY；移动乐器再 + controller_root_offset）
        │   ├── <手/脚/特殊>_Controllers_<后缀> ……
        │   └── Bilinear_Helpers_<后缀>（如有）
        └── Recorders_<后缀>
            └── String_Positions_<后缀>（弦端点等物理位置标记，如有）
```

- **演奏者根空物体**命名 `<乐器缩写>_<演奏者名>`（如 `FD_Jeht` / `KR_Aki`），用于整体移动/缩放整个演奏者体系；创建时复制骨骼的 transform，把骨骼挂到根下后本地 transform 归零（从世界坐标观察身体不变）。
- **乐器不挂根**：由用户手动把乐器绑定到 `controller_root`（固定乐器）或 `controller_root_offset`（移动乐器）。

### 3.2 身份属性（md_*，存演奏者 Collection 上）

| 逻辑键 | 规范键 | 含义 | 对应 Unreal |
| ------ | ------ | ---- | ----------- |
| `instrument` | `md_instrument` | 乐器类型（`fret_dance` / `key_ripple` / …） | 类（子类） |
| `name` / `suffix` | `md_name` | 演奏者名字（ASCII，兼作命名空间后缀） | ActorLabel |
| `skeleton` | `md_skeleton` | 演奏者骨骼（Armature）名称 | SkeletalMeshActor |
| `instrument_obj` | `md_instrument_obj` | 乐器物体名称（Mesh/Empty） | 乐器模型 |
| `info_path` | `md_info_path` | 人物信息保存路径（导入/导出） | IOFilePath |
| `animation_path` | `md_animation_path` | 动画文件路径 | AnimationFilePath |

**关键约定**：

- **名字即后缀**：`md_name` 兼作命名空间后缀（如 `Jeht` → 对象后缀 `_Jeht`），不再有独立的 `md_suffix` 键；
- **旧键兼容回退**：老文件用 `performer_suffix` / `performer_name` / `instrument` / `target_skeleton` / `target_instrument`，读取时新键（`md_*`）优先、旧键回退（见 `common/instrument_base.py` 的 `LEGACY_KEYS`）；
- 切换演奏者时，按 `md_*` 自动联动目标骨骼/乐器，并从骨骼回填设置（无状态化）。

### 3.3 命名规范

1. **后缀化命名**：插件管理的对象/集合命名一律 `<短名>_<后缀>`（如 `H_L_Jd`、`Controllers_Jd`）。短名在前、后缀在后，手动操作时短名一眼可见，后缀只用来区分归属；
2. **后缀为空（`""`）** 表示兼容旧场景：不加后缀，行为与旧版一致；
3. **乐器缩写前缀**（演奏者根空物体命名用，定义在 `common/instrument_base.py` 的 `INSTRUMENT_PREFIX`）：

| 乐器类型 | 缩写 | 示例 |
| -------- | ---- | ---- |
| `fret_dance`（吉他） | FD | `FD_Jeht` |
| `string_flow`（小提琴） | SF | `SF_Lin` |
| `key_ripple`（钢琴） | KR | `KR_Aki` |
| `zheng_drift`（古筝） | ZD | `ZD_...` |
| `harp_glide`（竖琴） | HG | `HG_...` |
| `wind_rise`（管乐） | WR | `WR_...` |
| `beat_bloom`（鼓） | BB | `BB_...` |

未知乐器回退前缀 `MD`。新乐器接入只需在映射表补一行。

### 3.4 数据存储约定

| 数据 | 存储位置 |
| ---- | -------- |
| 演奏者身份（md_*） | 演奏者 Collection 自定义属性 |
| 各乐器特有状态/设置 | **演奏者骨骼（Armature）自定义属性**（JSON 字符串） |
| 物理位置标记（弦端点、品位置、键位点） | 场景对象（保留为物理参考点） |

**状态一律存骨骼，不生成记录器物体**——这是迁移工程的核心决策，避免了场景中出现大量多余物体（如 StringFlow 原版约 230 个状态记录器 sphere，迁移后全部改为骨骼 JSON）。

各乐器骨骼自定义属性键：

| 乐器 | 状态键 | 设置键 |
| ---- | ------ | ------ |
| fret_dance | `fret_dance_controller_data` | `fret_dance_instrument` / `fret_dance_use_vibrato_bar` |
| key_ripple | `key_ripple_state_data` | （随状态 JSON 存储） |
| zheng_drift | `zheng_drift_state_data` | `zheng_drift_bilinear_data`（四态辅助） |
| beat_bloom | `beat_bloom_state_data` | `beat_bloom_drumkit_config` |
| harp_glide | `harp_glide_state_data` | （config 节在状态 JSON 内） |
| wind_rise | `wind_rise_state_data` | （config 节在状态 JSON 内） |
| string_flow | `string_flow_state_data` | — |
| 公共演奏者设置 | `md_settings`（DEFAULT_SETTINGS_KEY） | — |

### 3.5 演奏者生命周期

- **新建角色**：`music_doll.create_performer` 算子（角色生成器）——弹窗填名字（仅 ASCII 字母数字）/乐器类型/骨骼/乐器物体 → `performer_utils.get_or_create_performer` 创建 Collection + `Body_` / `Instruments_` / `addons_` 三个骨架 + 改名归位对象 + 创建演奏者根空物体；
- **复制角色**：每个乐器提供 `duplicate_performer` 算子——`duplicate_collection_tree` 深拷贝集合（对象共享数据、自定义属性复制、**父级/约束器/modifier 引用按 obj_map 重映射**）→ `resuffix_performer` 重新后缀 → 收尾重建 ext driver + `_organize_performer_root`；
- **重命名角色**：每个乐器提供 `rename_performer` 算子——校验新名字 → `resuffix_performer` → 收尾同上；
- **旧场景迁移**（fret_dance）：`migrate_legacy` 算子把无后缀的旧场景迁移到当前演奏者体系。

### 3.6 复制/重命名的实现细节（performer_utils.py）

- `duplicate_collection_tree(src, parent)`：深拷贝集合树。对象用 `copy()`（共享数据，类似 Shift+D）；对象自定义属性一并复制（含骨骼上的状态数据/设置）；父级关系用全局 `obj_map` 重建（跨集合的父级同样生效）；约束器与 modifier 里的对象引用重映射为新副本；
- `resuffix_performer(collection, new_suffix, new_name)`：把整个演奏者集合（含 `.001` 复制品）统一重新后缀——去掉 Blender 追加的 `.001`、替换对象/集合名里的旧后缀、修复身份属性（md_name / md_skeleton / md_instrument_obj）。注意：ext 等 driver 需要调用方按新后缀重建。

---

## 4. 公共模块 common/ 详解

公共模块对应 Unreal 的 `MusicDollCommon`，是"所有乐器的地基"，不依赖任何乐器模块，可在 Blender 中独立加载。

### 4.1 instrument_base.py —— 统一属性键 / 乐器缩写

职责：统一属性键定义与兼容读取、乐器类型 → 缩写前缀映射。

- `INSTRUMENT_KEYS`：逻辑键名 → 规范键（`md_*`）映射；`suffix` 是 `name` 的别名（都读写 `md_name`）；
- `LEGACY_KEYS`：规范键 → 旧键回退表（`md_instrument` ← `instrument`、`md_name` ← `performer_name`、`md_skeleton` ← `target_skeleton`、`md_instrument_obj` ← `target_instrument`）；
- `INSTRUMENT_PREFIX`：乐器类型 → 缩写（FD/SF/KR/ZD/HG/WR/BB），未知回退 `MD`；
- `get_coll_attr` / `set_coll_attr` / `has_coll_attr`：演奏者 Collection 属性读写，新键优先、旧键回退。

### 4.2 performer_utils.py —— 演奏者命名空间（核心）

职责：演奏者注册表、命名转换、集合组织、复制/重命名、根空物体。是所有乐器共用的最大模块。

**命名转换**：

- `resolve(short, suffix)`：短名 → 完整对象/集合名（`resolve("H_L", "Jd") == "H_L_Jd"`；suffix 空则原样返回）；
- `strip_duplicate_suffix(name)`：去掉 Blender 追加的 `.001/.002...`；
- `performer_from_object(full_name)`：完整对象名 → `(后缀, 短名)`，按"已知后缀表"倒序 endswith 匹配，避免短名里的下划线误判；
- `suffix_from_object(obj)`：给定任意对象，向上找所属演奏者集合，返回后缀（Blender 5.0 起 Collection.parent 被移除，通过遍历 `bpy.data.collections` 反查父子关系）。

**演奏者注册表**：

- `PERFORMERS_ROOT = "Performers"` 顶层根集合；
- `get_or_create_root_collection()` / `get_or_create_collection(suffix, short_name, parent)`；
- `find_addons_collection(suffix)`：按名字查找 addons 目录（**不创建**；有后缀查 `addons_<后缀>`，无后缀查全局 `addons`）。乐器模块 setup 阶段用它做"先初始化角色"的前置校验；
- `list_performers(context)` / `get_performer(suffix)` / `has_performer(suffix)`：扫描 Performers 根下的子集合，返回 `PerformerInfo`（后缀/名字/乐器/集合/骨骼/乐器物体/路径）；
- `PerformerInfo`：dataclass，含 suffix / name / instrument / collection / target_skeleton / target_instrument / info_path / animation_path。

**新建角色整理**：

- `organize_performer_objects(collection, suffix, skeleton, instrument)`：把骨架/Mesh/乐器改名加后缀并移入 `Body_` / `Instruments_` 集合（幂等）；
- `get_or_create_performer(suffix, name, instrument, ...)`：创建/获取演奏者集合（含三个骨架），登记身份属性，创建根空物体。

**演奏者根空物体**：

- `get_performer_root_name(performer)`：`<乐器缩写>_<演奏者名>`；
- `get_or_create_performer_root(performer, collection)`：创建时复制骨骼的 transform；
- `organize_performer_root(performer)`：创建根并挂接骨骼（`parent_and_zero_local`，从世界观察不变）；**乐器不挂根**（用户手动绑定）；各乐器 setup 阶段用 `_organize_performer_root` 补充挂载 controller_root 等。

**复制与重命名**：`duplicate_collection_tree`（深拷贝 + 约束/修改器重映射）、`resuffix_performer`（重新后缀 + 修复身份属性）、`_swap_suffix_in_name`（名字替换工具）。

### 4.3 object_utils.py —— 集合/物体幂等创建

职责：所有乐器共用的集合创建、物体创建/更新、物体移动工具（命名由调用方负责加后缀）。

- `get_or_create_collection(name, parent_collection)`：已存在复用，否则创建并挂到指定父集合；
- `move_object_to_collection(obj, collection)` / `move_children(obj, dest_coll)`；
- `create_or_update_object(obj_name, obj_type, collection, rotation_mode, scale)`：幂等创建物体。支持类型：`cube` / `cone` / `sphere`（空球） / `circle`（空环，IK 极向量/pole 用） / `cone_empty` / `single_arrow`；未知类型回退 sphere 空物体；
- `create_or_update_empty(obj_name, collection)`；
- `parent_to(parent_obj, child_obj)`：挂父子（保持世界位置不变）；
- `zero_local_transform(obj)` / `parent_and_zero_local(parent, child)` / `copy_transform_from(src, dst)`：transform 工具。

### 4.4 state_io.py —— 状态存取

职责：所有乐器共用的状态存取（对应各乐器插件的 state_transfer / state_manager）。

- `get_true_transform_value(obj, transform_type)`：获取对象的**真实变换值**（处理约束器影响，走 evaluated depsgraph）；
- `copy_transfer_between_object_and_dict(obj, data_dict, direction, key)`：obj ↔ JSON dict 搬运。`direction="set"` 从 obj 读 loc/rot 写 dict；`direction="load"` 反向应用。`key` 可选，把数据键与场景对象名解耦（场景控件名带后缀，骨骼数据键用短名）；
- `get_state_data(skeleton, key, default)` / `set_state_data(skeleton, key, data)`：骨骼自定义属性上的 JSON 状态读写；
- `get_bone_attr` / `set_bone_attr`：任意标量/字符串属性读写；
- `load_settings` / `save_settings`：演奏者通用设置存骨骼 JSON 键 `md_settings`（可被乐器模块覆盖或沿用）。

### 4.5 io_utils.py —— JSON 读写 / Unreal 坐标转换

职责：所有乐器共用的 JSON 文件读写、扩展名处理、嵌套字典工具，以及 **Blender ↔ Unreal 坐标转换**。

- `nested_dict()`：递归嵌套 defaultdict；
- `ensure_extension(file_path, ext)` / `save_json` / `load_json`（不存在或解析失败返回 `{}`）；
- `dump_dict_to_json_str` / `load_dict_from_json_str`：dict ↔ JSON 字符串（存自定义属性用）；
- `to_unreal_position(pos)`：Blender 位置 → Unreal 位置，**Y 轴取反**：`[x, -y, z]`；
- `to_unreal_rotation(rot)`：Blender 四元数 `[w,x,y,z]` → Unreal：位置经反射 M=diag(1,-1,1) 时旋转应为 `R_u = M·R_b·M`，反射共轭同时翻转转轴并反号转角，故四元数变为 **`[w, -x, y, -z]`**（不是共轭 `(w,-x,-y,-z)`）。

> 各乐器"导出到 Unreal"按钮即 `for_unreal=True` 调用这两函数（坐标转换细节与 ×100 缩放的说明见第 8.2 节）。

### 4.6 animation_utils.py —— 动画通用工具

职责：所有乐器共用的动画写入与清理（对应各乐器插件的 make_animation 里的通用部分）。

- `collect_collection_objects(col, exclude_names, object_names)`：集合对象递归收集；
- `get_or_create_fcurve(datablock, data_path, index)`：在动画 action 中查找或创建 fcurve（**兼容 Blender 4.x 与 5.x**：5.0 起 Action 不再暴露 fcurves 集合，需用 `Action.fcurve_ensure_for_datablock()`）；
- `write_fcurve_points(fcurve, keyframes, clear_existing)`：批量写入 fcurve 关键帧点（比逐帧 frame_set + keyframe_insert 快得多；VECTOR 手柄 + BEZIER 插值）；
- `reset_shape_keys(obj, value)` / `clear_shape_key_animation(obj)`：shape key 工具；
- `backup_driver(driver)` / `restore_driver(new_driver, backup)`：driver 深度备份/恢复（清动画时保留驱动）；
- `clear_all_keyframe(collection_names, exclude_names, suffix)`：清除关键帧（按演奏者后缀过滤，多演奏者隔离）；
- `clear_all_keyframe_preserve_drivers(...)`：**清除关键帧但保留驱动器**（备份 → 清空 → 恢复），用于需要保留目标物体上驱动器的场景——迁移指南明确要求清动画时用此函数，逐对象 `animation_data_clear()` 会毁掉 ext / Middle_Hand 的 driver。

### 4.7 ui_utils.py —— 统一 UI / 主面板

职责：对应 Unreal MusicDollUI 的演奏者选择器。提供统一主面板与全部公共 UI 组件。

**场景公共属性**（`register_scene_props` 注册，前缀 `md_`）：

| 属性 | 含义 |
| ---- | ---- |
| `md_active_performer` | 当前演奏者（枚举） |
| `md_target_skeleton` | 目标骨骼（指针） |
| `md_target_instrument` | 目标乐器（指针） |
| `md_info_path` | 人物信息路径（导入/导出唯一路径来源） |
| `md_show_tools` | 工具区折叠 |
| `md_active_tool` | 当前选中工具 id |
| `md_show_performer_generator` | 角色生成器折叠 |
| `md_show_performer_ops` | 角色操作折叠 |

**关键函数**：

- `get_active_suffix` / `get_active_performer` / `active_instrument`：当前角色查询。注意 Blender 5.0 中文编码 bug：场景枚举可能残留坏字节抛 UnicodeDecodeError，读取时捕获并尝试自愈；
- `get_target_skeleton` / `get_target_instrument`：优先场景指针，其次选中对象/演奏者登记；
- `get_performer_items`：角色下拉项（扫描 Performers 根，跳过非 ASCII/bytes 名字）；
- `on_active_performer_update`：切换联动（填充骨骼/乐器/路径）；
- `on_target_skeleton_update`：选骨骼自动选中所属演奏者；
- `on_info_path_update`：编辑路径写回身份属性；
- `performer_of(obj)`：任意对象 → 所属演奏者（读 ID 属性，不受枚举编码问题影响）；
- `get_rename_target(context)`：定位要重命名/复制的角色（骨骼指针 → 乐器指针 → 下拉 → 选中对象，逐步降级）；
- `register_instrument` / `unregister_instrument` / `INSTRUMENT_UI`：乐器 UI 注册表（label / panel / rename_operator / duplicate_operator）；
- `get_instrument_items`：角色生成器的乐器下拉项（只列已注册乐器）。

**统一主面板 `MUSICDOLL_PT_main_panel`**（唯一顶级面板，三大块）：

1. **角色选择器**（常显）+ **角色生成器**（折叠，默认收起）；
2. **角色操作**（折叠，默认收起；含角色基础属性 + 复制/重命名按钮，按乐器接入）；
3. **乐器子面板**：由 Blender 按 `bl_parent_id` 自动绘制，各乐器 `poll` 过滤（`ui_utils.active_instrument(context) == "<乐器id>"`）。

**工具界面 `draw_tools(layout, scene, tools)`**：可折叠 + 下拉选择工具 + 按选中展开操作区。下拉菜单列出公共工具 + 乐器独有工具；用注入式上下文 + Menu 实现（`_CURRENT_TOOL_UI`），配合 `MUSICDOLL_OT_set_active_tool` 与 `MUSICDOLL_MT_tool_menu`。

**角色生成器算子 `MUSICDOLL_OT_create_performer`**：`music_doll.create_performer`。Blender 5.0 的 Operator 不支持 PointerProperty，因此骨骼/乐器物体复用场景级指针属性（在弹窗里直接编辑）。名字校验：仅 ASCII 字母数字且字母开头（拒绝中文）。

### 4.8 common/tools/ —— 公共工具

**ToolDef**（dataclass）：工具的元信息（id / label / operator / icon / 可选 draw 参数区）。`find_tool(tools, tool_id)` 按 id 查找。

**COMMON_TOOLS**（所有乐器下拉菜单都显示）：

| 工具 | id | operator | 说明 |
| ---- | -- | -------- | ---- |
| 修正手指骨骼 | `fix_finger_bones` | `music_doll.tool_fix_finger_bones` | 修正选中骨骼链的手指骨骼形状（拱形分布）。用法：先选参照物 + 骨架（活动对象），编辑模式选中骨骼链根骨骼后执行 |
| 骨骼/控制器映射 | `bone_controller_mapping` | （无单一按钮） | 骨骼 ↔ 控制器映射面板：添加/删除映射、一键同步控制器到骨骼位置（按层级深度）、映射导出/导入 JSON（`md_bcm_` 前缀属性，避免与独立插件冲突） |

每个乐器的工具列表 = `COMMON_TOOLS + INSTRUMENT_TOOLS`（`TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS`）。

---

## 5. 统一 UI 设计

### 5.1 面板层级

```
MusicDoll（bl_category，唯一顶级面板 MUSICDOLL_PT_main_panel）
├── 角色选择器（常显，下拉默认空）
├── 角色生成器（折叠，默认收起；新建角色按钮）
├── 角色操作（折叠，默认收起；基础属性 + 复制/重命名，按乐器接入）
└── 乐器子面板（按 md_instrument 只显示当前乐器一个）
    ├── FretDance   （FRET_DANCE_PT_main_panel）
    ├── KeyRipple   （KEYRIPPLE_PT_main_panel）
    ├── ZhengDrift  （ZHENG_PT_main_panel）
    ├── BeatBloom   （BEATBLOOM_PT_main_panel）
    ├── HarpGlide   （HARPGLIDE_PT_main_panel）
    ├── WindRise    （WINDRISE_PT_main_panel）
    └── StringFlow  （STRINGFLOW_PT_main_panel）
```

每个乐器子面板 `bl_parent_id = "MUSICDOLL_PT_main_panel"`、`bl_category = "MusicDoll"`，`poll` 用 `ui_utils.active_instrument(context) == "<id>"`。父面板必须先于乐器子面板注册（`bl_parent_id` 校验），注销严格逆序。

### 5.2 乐器子面板的通用结构

各乐器子面板布局大同小异，通常包含（顺序或有差异）：

1. **初始化**：乐器参数（如手指数、弦数）+ Check Status + Setup Objects 按钮；
2. **工具区**：`ui_utils.draw_tools(layout, scene, tools=TOOLS)`（公共 + 乐器独有）；
3. **状态选择**：左右手各自的 position/state 枚举下拉；
4. **设置与加载**：Set / Load 按钮（保存/加载当前状态到骨骼）；
5. **导入/导出**：Import / Export（路径用角色操作面板的"人物信息路径"）+ "导出到 Unreal"按钮；
6. **生成动画**：动画文件路径（乐器面板唯一 FILE_PATH）+ 左手/右手/弦/一键全部按钮。

### 5.3 无状态化设计

插件**不做全局缓存实例**（`_key_ripple_instance` 等已被移除）：每个算子按当前演奏者后缀构造 config，设置从骨骼读取（`load_settings`），面板只是编辑入口，提交时写回骨骼（`save_settings`）。切换演奏者时从骨骼回填面板。

---

## 6. 工具体系

工具是所有乐器共用的"小功能集合"，收在一个可折叠的下拉菜单里，默认收起，界面干净。

### 6.1 工具注册机制

```python
# common/tools/__init__.py
@dataclass
class ToolDef:
    id: str            # 唯一 id，如 "fix_finger_bones"
    label: str         # 显示名，如 "修正手指骨骼"
    operator: str      # 执行算子的 bl_idname，如 "music_doll.tool_fix_finger_bones"
    icon: str = "TOOL_SETTINGS"
    draw: Callable = None   # 可选参数区绘制函数 draw(layout, scene)
```

- 公共工具在 `common/tools/`（`COMMON_TOOLS`）；乐器独有工具在各乐器 `tools/__init__.py`（`INSTRUMENT_TOOLS`）；
- 每个乐器面板的 `TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS`，用 `ui_utils.draw_tools(layout, scene, tools=TOOLS)` 统一绘制；
- 工具参数用**场景级属性**（工具模块内注册，幂等 hasattr 守卫），不污染乐器 PropertyGroup；
- 工具生成的对象带演奏者后缀；
- `operator=""` 的工具由参数区自带按钮（如骨骼/控制器映射）。

### 6.2 乐器独有工具一览

| 乐器 | 工具 | operator | 参数 |
| ---- | ---- | -------- | ---- |
| fret_dance | 生成弦（shape key） | `music_doll.tool_fret_dance_create_string` | 弦序号 / 振幅（场景属性） |
| key_ripple | 为钢琴键创建 Shape Keys | `music_doll.tool_key_ripple_make_shape_keys` | 无（选中键执行） |
| zheng_drift | 生成弦 Shape Key / 线性分布记录器 | `music_doll.tool_zheng_*` | 弦序号 0~20 / 振幅比例 |
| beat_bloom | （无专属工具，仅公共工具） | — | — |
| harp_glide | 生成弦 Shape Key / 批量生成所有弦 / 线性分布弦位置 | `harp_glide.create_string_shape_key` 等 | 弦数 / 振幅 |
| wind_rise | 轴旋转工具 / 轴移动工具 | （参数区自带按钮） | — |
| string_flow | 一键创建琴弦 / 生成 ShapeKey | `music_doll.tool_string_flow_create_violin_string` 等 | 弦号 / 偏移比例 / 反序遍历品格 |

### 6.3 典型工具实现位置

- 公共：`common/tools/fix_finger_ik.py`、`common/tools/bone_controller_mapping.py`；
- fret_dance：`fret_dance/tools/strings.py`（`create_string_with_shape_keys`，选中起点→终点两对象生成弦与 0~20 品 shape key）、`fret_dance/tools/export_to_unreal.py`；
- key_ripple：`key_ripple/tools/make_shape_keys.py`（Basis + pressed shape keys）、`key_ripple/tools/export_to_unreal.py`；
- zheng_drift：`zheng_drift/tools/string_tools.py`（右手摇指 + 左手按弦 shape key、线性分布）、`zheng_drift/tools/export_to_unreal.py`；
- harp_glide：`harp_glide/tools/string_tools.py`（振动方向从骨骼 JSON 读）、`harp_glide/tools/export_to_unreal.py`；
- wind_rise：`wind_rise/tools/axis_rotation_tool.py`（Edit Mode 下以两物体位置定义旋转轴对选中顶点实时旋转）、`wind_rise/tools/export_to_unreal.py`；
- string_flow：`string_flow/tools/make_violin_string.py`（三点定平面生成琴弦 shape key）、`string_flow/tools/export_to_unreal.py`。

> 各乐器的"导出到 Unreal"均为 `(Operator, ExportHelper)` 类，弹出文件浏览器选择路径后调用 `io.export_*(..., for_unreal=True)`。
>
> 注意算子前缀：多数乐器用 `music_doll.<instrument>_*`（含工具算子 `music_doll.tool_<instrument>_*`）；**harp_glide 例外**，其算子保留 `harp_glide.*` 前缀（如 `harp_glide.save_hand_pose`、`harp_glide.export`）。

---

## 7. 乐器模块详解

以下为 7 个乐器模块的核心档案（控制器布局 / 状态模型 / 导入导出 / 动画 / 特有逻辑）。命名一律接演奏者后缀（`<短名>_<后缀>`），Rust 端消费的 JSON 键一律短名。

### 7.1 FretDance（吉他，`fret_dance/`）

**类型**：移动乐器（有 `controller_root_offset`，乐器随身体运动）。支持指弹吉他 / 电吉他 / 贝斯（`Instruments` 枚举 0/1/2）。

**控制器布局**：

- 左手：手掌 `H_L`、IK 枢轴 `HP_L`、拇指 `T_L`（归手掌类，不参与演奏）、手指 `I_L`/`M_L`/`R_L`/`P_L`；
- 右手：手掌 `H_R`、IK 枢轴 `HP_R`、拇指 `T_R` + 四指 `I_R`/`M_R`/`R_R`/`P_R`（右手大拇指参与演奏）；
- 指板位置标记：`Fret_P0` ~ `Fret_P4`（物理物体，用户可移动）；
- 控制器层级 → `controller_root_offset` → `controller_root`；手指 IK/pole、ext driver（有 palm 时 `2×手指 − 手掌`，无 palm 时 `2×手指`，LOCAL_SPACE，先清后建幂等）。

**状态模型**（存骨骼 `fret_dance_controller_data`）：

- 左手：`BasePositions(P0~P4) × LeftHandStates(NORMAL/OUTER/INNER/BARRE)`，含非法组合表 `invalid_combinations`（如 P0 不支持 INNER、P1 不支持 OUTER）；
- 右手：`RightHandStates(low/end/high + 可选 vibrato 的 release/up/down)`；
- 设置：`fret_dance_instrument` / `fret_dance_use_vibrato_bar`（电吉他颤音摇杆）。

**导入导出**（`io.py`）：JSON（文件名由用户选择，不带 `_unreal` 后缀；内容结构与 Unreal 侧一致，供 Rust 消费，**结构不能变**）：

- `NORMAL/OUTER/INNER/BARRE_LEFT_HAND_POSITIONS`：按状态分节的左手控制器；
- `LEFT_FINGER_POSITIONS`：指板位置（从物理物体读）；
- `RIGHT_HAND_POSITIONS`：右手控制器，recorder_name 由内部状态 + 控制器名计算（西班牙指法映射：`T_R→p`、`I_R→i`、`M_R→m`、`R_R→a`、`P_R→ch`；颤音 `Vibrato_*_H_R` 等）；
- `OTHER_SETTING`：`is_unreal` / `use_vibrato_bar`。

**动画**（`animation.py`）：左手 / 右手 / 弦动画 / controller_root 偏移（吉他偏移）/ 一键全部。读取动画 JSON（`[{frame, fingerInfos: {控制器名: {position, rotation}}}]`），fcurve 批量写入，四元数符号一致性处理。

**特有工具**：生成弦（shape key）。

**面板**：初始化（乐器类型 / 颤音开关 + Check/Setup + 迁移旧场景）、工具区、左右手状态选择、设置与加载、导入/导出、生成动画。

### 7.2 KeyRipple（钢琴，`key_ripple/`）

**类型**：固定乐器（无 `controller_root_offset`）。

**控制器布局**：

- 手指控制器：`0_L`~`(N-1)_L` + `N_R`~`(2N-1)_R`（`one_hand_finger_number` 每手手指数，默认 5）；
- 手掌/枢轴：`H_L` / `HP_L` / `H_R` / `HP_R`；ext（`2×手指` driver）+ pole；`Mid_Hand`（世界中点 driver）、`Head_Control`；
- 键盘基准点：`black_key` / `highest_white_key` / `lowest_white_key` / `lowest_white_key_end` / `normal_hand_expand_position` / `wide_expand_hand_position`（物理 Empty）。

**状态模型**（存骨骼 `key_ripple_state_data`，JSON 数组）：

- 维度：`key_type(white/black) × position_type(high/low/middle)`；
- 每状态条目：`{key_type, position_type, controllers: {短控制器名: {location, rotation}}}`；左手状态额外含 `Head_Control`；
- `set_state_data` 按 (key_type, position_type) 合并 controllers 而非替换。

**导入导出**（`io.py`）：`.avatar` 文件（Rust/Unreal 侧继续消费，格式兼容）：

- `config`：one_hand_finger_number / 七个位置参数 / min_key / max_key / hand_range / is_unreal；
- `finger_recorders.{left/right}_finger_recorders`、`hand_recorders.{left/right}_hand_recorders`、`target_points_recorders.head_position_recorders`：按 `{position_type}_{key_type}_{ctrl}` 命名；
- `key_board_positions`：键盘基准点。

**动画**（`animation.py`）：读动画 JSON（左右手 + 脚 + Head_Control 分节），批量写 fcurve。

**特有工具**：为钢琴键创建 shape keys。

**面板**：Initialization（手指数/键位参数 + Check/Setup）、工具区、左右手状态选择、Hand State Transfer（Set/Load）、Avatar I/O（Export/Import/导出到 Unreal）、Animation Generation。

### 7.3 ZhengDrift（古筝，`zheng_drift/`）

**类型**：固定乐器，21 弦。

**控制器布局**：

- 左右手各 7 主控：`H_L/HP_L/T_L/I_L/M_L/R_L/P_L`（右手对称）+ 各手指 `*_pole` 极向量 + `ext_*`（`ext = 2×手指` driver，LOCAL_SPACE）；
- 双脚：`F_L` / `F_R` + `F_L_pole` / `F_R_pole`；
- 特殊朝向：`Middle_Hand`（H_L/H_R 世界中点 driver，WORLD_SPACE）、`Look_At`（挂 Middle_Hand）、`Head_Control`（世界对象 + TrackTo Look_At）；
- 双线性辅助：`Middle_Hand_A~D` / `Head_Control_A~D`（四态驱动，`bilinear_map` 注册进 `bpy.app.driver_namespace`）；
- 弦位置标记：`s0head`~`s20head`、`s0end`~`s20end`、`s0mid`~`s20mid`（63 个物理参考点，不挂 controller_root，弦工具按 `.location` 取世界坐标）。

**状态模型**（存骨骼 `zheng_drift_state_data`，`zheng_drift_bilinear_data` 存四态辅助）：

- 左手：`action(Normal/Press) × position(far/middle/near)`；右手：`action(Normal/Tremolo) × position(far/middle/near)`；
- 结构：`{left_hand/right_hand: {action: {position: {控制器短名: {location, rotation}}}}}`；
- **四态检测**（A: 左 Normal 右 Tremolo far；B: 左 Press 右 Normal far；C: 左 Normal 右 Tremolo near；D: 左 Press 右 Normal near）：Save 时把 Middle_Hand / Head_Control 位置存进骨骼，Load 时恢复。

**导入导出**（`io.py`）：`.zheng_master` 标准姿势文件（JSON 键短名兼容 Rust）：

- `STRING_RECORDERS`：弦位置标记（对象）；
- `LEFT/RIGHT_HAND_RECORDERS`：左右手状态（骨骼，键如 `H_L_Normal_far`）；
- `FOOT_CONTROLLERS`：脚部控制器（对象）；`BILINEAR_HELPERS`：双线性辅助（骨骼）。

**动画**（`animation.py`）：左手 / 右手 / 弦振动 / 特殊朝向 target（Head_Control）/ 一键全部。动画配置 `.zhengdrift`（内含 performance / target / string 三个子文件 + 相对路径解析）。

**特有工具**：弦 shape key（右手摇指 / 左手按弦）、线性分布记录器。

**面板**：初始化（Check/Setup）、工具区、左右手状态选择（position + action）、设置与加载（含四态）、导入/导出标准姿势、生成动画。

### 7.4 BeatBloom（打击乐，`beat_bloom/`）

**类型**：固定乐器。控件保留为场景物体（基础控件 9 个 + 辅助控件；模块注释亦有"12 个控件"的提法，指可操作的控制器集合）；原记录器物体废止，状态存骨骼。

**控制器布局**：

- 基础控件 9 个：手掌 `H_L`/`H_R`、IK Pivot `HP_L`/`HP_R`、脚部 `F_L`/`F_R`、特殊朝向 `Middle_Hand`（实时计算中点）/`Look_At`（挂 Middle_Hand）/`Head_Control`（TrackTo）；
- 辅助控件（仅创建/驱动，**不参与 save/load/export/import 数据传递**）：左右手五指 `T/I/M/R/P_L/R` + ext（挂手掌）+ 各手指 pole（拇指 `TP_L/TP_R`，其余 `<手指>_pole`）、左右脚 pole `FP_L`/`FP_R`。

**状态模型**（存骨骼 `beat_bloom_state_data`，`beat_bloom_drumkit_config` 存鼓组配置）：

- 结构：`{<component_name>: {<state>: {<ctrl_short>: {location, rotation}}}, "rest": {...}, "mapping_helpers": {A/B/C/D: {Middle_Hand, Head_Control, H_L, H_R}}}`；
- 状态：`beat / ready / rest` 三态；
- 控制器保存范围由 `drivable_limbs` 决定：right_hand → H_R/HP_R + Head_Control；left_hand → H_L/HP_L + Head_Control；right_foot → F_R；left_foot → F_L。

**导入导出**（`io.py`）：`.drummer` 文件（兼容 Rust 扁平格式）：

- `RECORDER_INFO`：`<component>_<state>_<ctrl_short>` 扁平键；rest 映射为 `H_Rest_L` / `H_Rest_R` 等；
- `MAPPING_HELPERS`：`Middle_Hand_A/B/C/D`、`Head_Control_A/B/C/D`、`Left_Hand_A/B/C/D`、`Right_Hand_A/B/C/D`。

**动画**（`animation.py`）：读动画 JSON（left/right_hand + left/right_foot + head_control 分节），批量写 fcurve。

**特有工具**：无（仅公共工具）。

**面板**：DrumKit Config（Load DrumKit Config）、初始化（Setup Objects）、工具区、Set/Load State（component + state）、Mapping Helpers（A/B/C/D 槽位）、导出/导入 `.drummer`、动画（Execute Animation）。

### 7.5 HarpGlide（竖琴，`harp_glide/`）

**类型**：固定乐器（47 弦默认，可配置）。结构为 `HarpConfig` + `HarpObjectManager` + `HarpBaseState` 组合。

**控制器布局**：

- 身体：`Head`、`Shoulder_Harp`（挂 harp_pivot）；
- 左右手各 7 主控：`H_L/HP_L/T_L/I_L/M_L/R_L/P_L`（右手对称），**手指挂 H_L/H_R**（与 wind_rise 不同）、ext（`2×手指`，LOCAL_SPACE）+ pole；
- 脚部：`F_L`/`F_R` + `FP_L`/`FP_R`；
- 视线辅助：`Mid_Hand`（世界中点 driver，不挂 controller_root）、`Look_At`（挂 Mid_Hand）；
- 竖琴支点：`harp_pivot`（挂 controller_root）；
- 弦位置标记：`s{n}head` / `s{n}end`（物理 Empty，挂 harp_pivot，随竖琴整体移动）。

**状态模型**（存骨骼 `harp_glide_state_data`，含 config 节）：

- `config`：string_count / left_far / left_near / left_mid_far / left_mid_near / right_far / right_near；
- `pedal_positions`：`pedal_{D/C/B/E/F/G/A}_{state0~4}`（D/C/B 左脚，E/F/G/A 右脚；**含 harp_pivot 坐标系转换**：世界坐标 ↔ pivot 局部坐标）；
- `harp_pivot_states`：near/mid/far（竖琴倾斜）；
- `hand_poses`：left/right × far/near/attack/rest；
- `head_poses`：far/near/attack/rest；
- `foot_rest`：F_L / F_R。

**导入导出**（`io.py`）：`.harpist` 文件（Rust 端兼容的扁平记录器键名）：

- `STRING_RECORDERS`（对象）/ `PEDAL_POSITION_RECORDERS` / `HARP_PIVOT_RECORDERS` / `LEFT/RIGHT_HAND_RECORDERS`（展平 `H_L_far` 等）/ `HEAD_RECORDERS`（`Head_far`）/ `FOOT_REST_RECORDERS`（`F_rest_L` / `F_rest_R`）。

**动画**（`animation.py`）：竖琴动画（harp_pivot）、演奏动画（手/脚/头）、踏板 shape key、弦 shape key、一键全部（读 `.harpglide` report）。

**特有工具**：生成弦 Shape Key / 批量生成所有弦 / 线性分布弦位置（振动方向从骨骼 JSON `hand_poses.left.far/near` 读）。

**面板**：竖琴设置（弦数 + 六个位置参数 + 保存配置到骨骼）、初始化、工具区、状态设置（手部+头部姿势 / 踏板 / 竖琴倾斜 / 脚部休息）、数据文件 `.harpist`、生成动画。

### 7.6 WindRise（管乐，`wind_rise/`）

**类型**：移动乐器（有 `controller_root_offset`）。示例乐器类型：中式笛子 / 长笛 / 单簧管 / 萨克斯 / 竖笛 / 自定义。

**控制器布局**：

- 骨架：`controller_root`（挂演奏者根）→ `controller_root_offset`（乐器绑在此）；
- 左右手各 7 主控：`H_L/HP_L/T_L/I_L/M_L/R_L/P_L`（右手对称），**手指挂 controller_root_offset**、ext（`2×手指`，LOCAL_SPACE）+ pole；
- 脚部：`F_L`/`F_R` + `FP_L`/`FP_R`（挂演奏者根）；
- 头部：`Head_Control`（挂 controller_root）；呼吸：`Breath_Control`（挂演奏者根，存根）；
- 无弦/键位置标记 → 无需 Recorders 集合。

**状态模型**（存骨骼 `wind_rise_state_data`）——**按 MIDI 音高编号组织**：

- `config`：instrument_type / description / min_note / max_note / force_shape_keys（嘴唇）/ instrument_shape_keys / instrument_mesh_name；
- `note_info`：`[{note, name(如 C4), controllers: {H_L: {location, rotation}, ...}, character_shape_keys, instrument_shape_keys}]`；
- 每个音高保存 14 个手部控制器 + 嘴唇 Shape Key + 乐器 Shape Key；load 时先归零再按记录值设置（必须保留）。

**导入导出**（`io.py`）：`.wind` 文件（config + note_info，与骨骼 JSON 同构）；`.wind_rise` 汇总文件为动画输入（不是角色信息文件，独立路径属性）。

**动画**（`animation.py`）：左右手 / 人物 SK / 乐器 SK / 活动曲线（activity curve，写 `controller_root` 的 `activity_curve` 自定义属性 + `ActivityCurve` Empty 占位）；清动画用 `clear_all_keyframe_preserve_drivers`（保留 ext driver）。

**特有工具**：轴旋转工具、轴移动工具（Edit Mode 下以两物体位置定义旋转轴实时旋转选中顶点）。

**面板**：初始化（Setup Objects）、对象选择（人物 Mesh + 乐器）、人物/乐器 Shape Key 编辑器（折叠）、乐器说明、工具区、状态管理（当前音高 Save/Load）、数据文件 `.wind`（乐器类型/音域/导入导出）、生成动画。

### 7.7 StringFlow（小提琴，`string_flow/`）

**类型**：固定乐器（4 弦），左手手指数字命名（`1_L`~`N_L`，上限 10，默认 4）。

**控制器布局**：

- 左手手指：`1_L`~`N_L`；右手手指：`1_R`~`N_R`（**右手手指/拇指挂 Bow_Controller**——"手在弓上"结构，StringFlow 独有）；
- 手掌/枢轴/拇指：`H_L`/`HP_L`/`T_L`/`H_R`/`HP_R`/`T_R`；
- 其他控制器：`String_Touch_Point`（触弦点）、`Bow_Controller`（琴弓）；
- 脚部 IK / pole（仅创建，**不参与任何数据传递与计算**，与 controller_root 同级：**不挂 controller_root**，挂演奏者根/保持世界对象）：`F_L`/`F_R` + `FP_L`/`FP_R`（pole 空环）；
- ext / pole：`ext_{手指}`、`{手指}_pole`（空环）；
- **ext 约束**（driver，先清后建幂等）：左手 `ext = 2×手指`（H_L 局部空间，手指/手掌同为 H_L 子级，手掌即原点）；右手 `ext = 2×手指 − 手掌`（Bow_Controller 局部空间，手指与手掌 H_R 同为弓子级，确保 ext 位于"手掌→手指"延长线上；注释注明已取代早期两个 Copy Location 世界坐标约束的方案）；
- 物理位置标记（17 个，挂 controller_root）：`position_s{i}_f0/f12`、`mid_s{i}` / `f9_s{i}`（driver 中点）、`middle_fret_board_position`（**三点定平面第三点**，Rust 端与琴弦工具共用）。

**状态模型**（存骨骼 `string_flow_state_data`）：

- 左手：`string(0/3) × fret(1/9/12) × position(Normal/Inner/Outer)`，每个状态保存 H_L（位置+旋转）、HP_L、T_L、全部手指；
- 右手：`string(0~3) × position(near/far/pizzicato)`，保存 H_R（位置+旋转）、HP_R、T_R、全部手指、String_Touch_Point、Bow_Controller（**只存位置，旋转由指向约束实时决定，Rust 端不读**）；
- 坐标语义：存控制器相对 controller_root 的**局部坐标**（= 原版 violin 帧），**不要在保存时换算世界坐标**。

**导入导出**（`io.py`）：`.violinist` 文件（与 Rust Animator 消费格式**字节级兼容**）：

- 顶层键：`config`（one_hand_finger_number / string_number / 可选 is_unreal）+ 6 个状态记录器节 + `other_recorders`；
- 每条记录器：`{location, rotation_mode, rotation_quaternion}`（Rust 只读 location 与 rotation_quaternion，**必须保留四元数格式**）；`bow_position_*` 只写 location；
- JSON 键一律短名；`other_recorders` 中物理标记从对象读（缺失写 None），bow/stp 从骨骼读。

**动画**（`animation.py`）：左手 / 右手 / 弦（shape key `s{i}fret{k}`）/ 一键全部。动画 JSON 控制器名为短名 → `resolve(short, suffix)` 映射；弦动画 shape key 名在弦数据内部无需后缀。

**特有工具**：一键创建琴弦（选两个端点对象 → 圆柱 → 细分 80 段 → 三点定平面生成 shape key `s{n}fret{1..20}`）、生成 ShapeKey。

**面板**：初始化（手指数 / 弦数 + Check/Setup）、工具区、左右手状态选择、Hand State Transfer、Recorder Info I/O（导出/导入/导出到 Unreal）、生成动画。

---

## 8. 数据文件格式汇总

### 8.1 各乐器文件格式

| 乐器 | 人物/状态文件 | 动画输入文件 | 说明 |
| ---- | ------------- | ------------ | ---- |
| fret_dance | JSON（无扩展名，用户指定） | 面板 FILE_PATH 指向的动画 JSON | 内容结构与 Unreal 侧一致；文件名不带 `_unreal` |
| key_ripple | `.avatar` | 动画 JSON | Rust/Unreal 侧继续消费 |
| zheng_drift | `.zheng_master` | `.zhengdrift`（performance/target/string 三子文件） | 键短名兼容 Rust |
| beat_bloom | `.drummer` | 动画 JSON | 扁平键名 `component_state_ctrl` |
| harp_glide | `.harpist` | `.harpglide` report | 对外扁平键名，内部嵌套 JSON |
| wind_rise | `.wind` | `.wind_rise` 汇总文件 | config + note_info |
| string_flow | `.violinist` | `.string_flow`（左右手/弦三个动画文件路径） | Rust Animator 字节级兼容 |

**通用约定**：

- JSON 键一律**短名**（兼容 Rust 端消费），仅 Blender 内对象查找用带后缀名；
- 状态一律从**骨骼自定义属性**读取导出；物理位置标记从**对象**读取；
- 路径统一用 `ui_utils.SCENE_INFO_PATH`（角色操作面板"人物信息路径"），不再用 ImportHelper/ExportHelper（导出到 Unreal 除外）。

### 8.2 导出到 Unreal 的坐标转换

`common/io_utils.py` 提供统一转换：

- 位置：`to_unreal_position([x,y,z]) → [x, -y, z]`（Y 轴取反）；
- 旋转：`to_unreal_rotation([w,x,y,z]) → [w, -x, y, -z]`（反射共轭，`R_u = M·R_b·M`，M=diag(1,-1,1)）；
- 各乐器 `for_unreal=True` 时应用转换并置 `config.is_unreal = true`（部分乐器 Rust 端据此处理，如 StringFlow 的指板平面法线方向）；
- 普通导出为恒等变换、不写 `is_unreal`（缺省 false）。

> 注意：各工具类 docstring 中"坐标 ×100，Y 轴取反，旋转取共轭"的描述与当前 `io_utils.to_unreal_position/rotation` 的代码存在出入——**以代码为准**（当前实现只做 Y 轴取反与旋转反射共轭，无 ×100 缩放）。如后续需要 ×100 需在导出路径显式加入。

---

## 9. 开发、部署与验证

### 9.1 安装与部署

`src/` 即全部源代码，两种安装方式：

1. 把 `src\` 目录改名成 `music_doll_blender` 放进 Blender 的插件目录（如 `Blender\5.0\scripts\addons\`）；
2. 把 `src\` 目录压缩成 zip 拖进 Blender 的"偏好设置 → 插件"窗口自动安装（zip 内顶层目录需为 `music_doll_blender/`，否则改名为插件目录名）。

修改源码后重新安装即可；若插件已启用，需要在 Blender 中**禁用再启用插件或重启 Blender** 使改动生效。

### 9.2 验证流程

- **静态检查**：`python -m py_compile`（语法）+ Pylance（引用/类型）；`ui_utils.py` 的 `StringProperty` 报错是已知误报，忽略；
- **Blender 实测（用户手动执行）**：新建角色（乐器下拉选对应乐器）→ Setup → Check Status → 状态 Set/Load → 导入/导出 → 专属工具 → 动画生成；多角色复制/重命名验证隔离；
- **测试注意**：用副本 `.blend` 文件，避免破坏现有工作文件。

> 历史数据修复工具（如 Blender 5.0 中文编码导致的后缀乱码、骨骼状态键误带后缀等）属于本机私有脚本，不随仓库发布，本文档不作展开。

---

## 10. 关键约定与注意事项

### 10.1 全局硬约束（所有模块必须遵守）

1. **SaveState / LoadState 必须由用户手动触发**：任何模块都不应在代码中自动调用；
2. **SetupAllObjects 只负责创建/配置控制器，不能清空或重置已保存的状态数据**：初始化只补缺失键（Contains + Add / FindOrAdd），禁止"先 Empty 再填零值"；SaveState 同样不得整体清空状态数据。对应迁移指南的 setup_all_objects 契约："幂等，不重置已保存的状态/位置标记数据"；
3. **导出格式不可变**：各乐器的导出文件（fret_dance JSON / `.avatar` / `.violinist` / `.zheng_master` / `.drummer` / `.harpist` / `.wind`）是 Rust/Unreal 侧的消费接口，迁移时**结构必须保持兼容**，只能改内部存储位置，不能改导出内容；
4. **JSON 键用短名**：Rust 端消费的 JSON 键一律短名（`s0head`、`H_L_Normal_far`），场景内对象查找才用带后缀名；
5. **状态存骨骼、位置标记存对象**：状态不再生成记录器物体；物理位置标记保留为场景对象；
6. **清除关键帧必须保留 driver**：用 `animation_utils.clear_all_keyframe_preserve_drivers` 或自定义逐对象处理；逐对象 `animation_data_clear()` 会毁掉 ext / Middle_Hand 的 driver；
7. **坐标空间陷阱**：父级化后 `.location` 变局部坐标——中点类 driver 用 WORLD_SPACE，同父级相对量（`ext = 2×手指`）用 LOCAL_SPACE；
8. **Blender 5.0 特性**：`bpy.types.Collection` 无 `.parent`（通过遍历反查父子）；Operator 不支持 PointerProperty（复用场景级指针属性）；EnumProperty items 回调 default 用整数索引；注册保护用 RNA 名（`MUSIC_DOLL_OT_create_performer` 带下划线）；
9. **中文编码 bug**：Blender 5.0 场景枚举可能残留坏字节抛 UnicodeDecodeError，读取时捕获并自愈；枚举项跳过非 ASCII 名字；
10. **弃用工具不迁移**：MMD 相关（mmd2blender）、Daz Rig、波形生成、着色器脚本等未出现在插件界面上的工具一律不迁移。

### 10.2 迁移工程约定（新增乐器时）

见第 11 章《新增乐器接入指南》以及《乐器模块迁移工程指南》全文。核心速查：

| 坑 | 处理 |
| --- | ---- |
| 对象名没后缀 → 多角色污染 | 全链路 `resolve()`，命名表/动画/io/工具逐个查 |
| setup 直接 `["addons"]` → 角色未初始化崩溃 | `_get_addons_collection()` find-only + 前置校验 |
| 父级化后 driver 取到局部坐标 | 中点类用 WORLD_SPACE；同父级相对量用 LOCAL_SPACE |
| 状态生成记录器物体 → 场景混乱 | 状态一律存骨骼；仅物理位置标记保留对象 |
| 清除关键帧把 driver 毁了 | 用 `clear_all_keyframe_preserve_drivers` 或自定义逐对象清 |
| 导入导出用文件浏览器 | 改 `SCENE_INFO_PATH`，面板只留动画文件路径 |
| 工具参数塞进 PropertyGroup | 用场景级属性（工具模块内注册） |
| 复制/重命名后 ext driver / 根丢失 | 收尾 `add_ext_drivers` + `_organize_performer_root` |
| JSON 键带后缀 → Rust 端解析失败 | 键用短名，仅对象查找用后缀 |

### 10.3 演奏者切换联动（无状态化核心）

```
用户切换演奏者下拉
  → 读取该 Collection 的 md_instrument / md_skeleton / md_instrument_obj
  → 填充当前乐器的场景字段（目标骨骼 / 目标乐器 / 人物信息路径）
  → 从骨骼 load_settings 回填面板
  → 若乐器类型与当前面板不一致，切换/启用对应乐器子面板
```

---

## 11. 新增乐器接入指南

> 详细方法论见《乐器模块迁移工程指南》。以下为浓缩流程。

### 11.1 乐器档案（迁移前盘点，Q1~Q5）

迁移前必须回答 5 组问题（答案全部来自源码）：

| 问题 | 内容 |
| ---- | ---- |
| Q1 控件 | 生成哪些控件？层级关系？特定约束（driver/约束/父子）？乐器固定 or 移动？ |
| Q2 状态 | 有哪些状态？维度？每状态记录哪些控制器？非法组合？状态存哪里（一律骨骼）？ |
| Q3 导入导出 | 记录哪些信息？哪些是控件信息、哪些是设置信息？控件信息与状态有关吗？键名兼容性（短名）？ |
| Q4 专属工具 | 哪些是本乐器独有的工具？参数用场景级属性？生成的对象带后缀？ |
| Q5 额外关注点 | 动画输入格式？特殊朝向/target？多文件动画配置？不迁移/复用？坐标空间陷阱？幂等与重复运行？ |

### 11.2 统一约定（所有乐器必须遵守）

1. **后缀化命名**：对象/集合走 `performer_utils.resolve(short, suffix)`；addons 用 `_get_addons_collection()`（有后缀 find-only）；
2. **对象层级**：`addons_<后缀>/Controllers_<后缀>/controller_root`（固定）或 `controller_root_offset`（移动）；驱动类对象不挂根；状态不生成记录器物体；
3. **setup_all_objects 契约**：前置校验 addons 存在 → `_organize_body` → `_organize_instrument` → `add_controllers` → `add_ext_drivers` → `add_recorders` → `_organize_performer_root`；幂等、不重置已保存数据；
4. **通用路径/对象**：导入导出走 `ui_utils.SCENE_INFO_PATH`；骨骼/乐器走 `get_target_skeleton/get_target_instrument`；动画路径保留为乐器面板唯一 FILE_PATH；
5. **登记与命名**：乐器 id snake_case 登记进 `INSTRUMENT_PREFIX`（缩写前缀）+ `ui_utils.register_instrument`；算子 `music_doll.<instrument>_*`；面板 `bl_parent_id = "MUSICDOLL_PT_main_panel"`；
6. **工具**：`TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS`；`ui_utils.draw_tools` 统一绘制；
7. **动画**：fcurve 工具复用 `common.animation_utils`；清关键帧保留 driver。

### 11.3 标准迁移步骤（Step 0~12）

```
Step 0  盘点：通读源文件，填乐器档案 Q1~Q5，标注不迁移/复用/保留特殊逻辑
Step 1  骨架 + enums.py（状态枚举、ObjectType 映射）
Step 2  config.py：命名表 + obj_name/obj 走 resolve
Step 3  add_controllers（controller_root 层级 + 特殊朝向 + 约束/driver）+ add_ext_drivers
Step 4  add_recorders（只建物理位置标记）+ check_*
Step 5  setup_all_objects 前置校验 + _organize_body/instrument/performer_root
Step 6  state.py：状态存骨骼（复用 common.state_io）+ 状态特殊逻辑
Step 7  io.py：导入/导出（键短名、SCENE_INFO_PATH）
Step 8  animation.py：各动画 + 清除关键帧（保留 driver）
Step 9  tools/：专属工具（ToolDef + 场景参数 + register/unregister）
Step 10 ui.py：属性组 + 面板 + 全部算子 + rename/duplicate + register_instrument
Step 11 接线：src/__init__.py 追加 register/unregister（注册顺序：公共 → 各乐器；注销逆序）
Step 12 验证部署：py_compile + 打包安装 + 用户 Blender 实测
```

---

## 12. 文档索引

> 说明：随本仓库（git）发布的文档仅 **本文档（中/英）** 与根目录 `README.md` / `README.en.md`；以下施工文档为仓库内部记录，未随 git 上传。

`docs/` 目录下的内部施工文档：

| 文档 | 内容 |
| ---- | ---- |
| `music_doll_blender_施工文档.md` | 项目规划稿（v1.0，2026-08-07）：背景、Unreal 架构参照、统一数据模型、公共模块 API 设计、迁移方案、UI 设计、分阶段计划、测试计划、风险清单 |
| `乐器模块迁移工程指南.md` | 工程方法论文档：乐器档案 Q1~Q5、统一约定、标准模块骨架、12 步迁移流程、三个已完成乐器档案示例、常见坑速查 |
| `面板默认执行顺序改造施工记录.md` | 面板改为唯一顶级面板组装三大块的改造记录，含 Blender 5.0 三大坑（Operator 无 PointerProperty、EnumProperty 整数索引、RNA 名注册保护） |
| `fret_dance / key_ripple`（无单独文档） | 迁移方案见施工文档 §7 |
| `zheng_drift移植施工报告.md` | 古筝模块移植报告（含实际实现差异说明） |
| `beat_bloom移植施工计划.md` | 打击乐模块移植计划 |
| `harp_glide移植施工计划.md` | 竖琴模块移植计划 |
| `wind_rise移植施工计划.md` | 管乐模块移植计划 |
| `string_flow_blender移植施工计划.md` | 小提琴模块移植计划（含 Rust 端消费确认、层级/约束设计） |
| `music_doll_blender_项目说明文档.md` | 本文档（中文） |
| `music_doll_blender_项目说明文档.en.md` | 本文档（English） |

---

## 13. 附录：Unreal ↔ Blender 概念对照

| Unreal MusicDoll | MusicDoll Blender |
| ---------------- | ----------------- |
| `AInstrumentBase`（Actor） | `Performers` 根下的演奏者 Collection |
| 子类（`AFretDanceUnreal` 等） | Collection 上的 `md_instrument` 属性 |
| `SkeletalMeshActor` | `md_skeleton`（骨骼物体） |
| 乐器模型 | `md_instrument_obj`（Instruments 集合） |
| `IOFilePath` | `md_info_path` |
| `AnimationFilePath` | `md_animation_path` |
| Actor 自带 UPROPERTY（乐器特有） | 骨骼自定义属性（`<乐器>_*`） |
| `TActorIterator<AInstrumentBase>` | `common.performer_utils.list_performers()` |
| SComboBox 演奏者选择器 | `common.ui_utils` 演奏者下拉 |
| `MusicDollCommon` | `common/` |

---

*本文档结束。如有与代码不一致之处，以 `src/` 实际代码为准。*



