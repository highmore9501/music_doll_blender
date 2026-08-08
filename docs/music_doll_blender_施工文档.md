# MusicDoll Blender 施工文档

> 版本：v1.0（规划稿）
> 日期：2026-08-07
> 状态：待评审

---

## 1. 背景与目标

### 1.1 背景

目前每个乐器项目都维护一套**独立的 Blender 插件**，各自实现"创建控制器 → 保存状态 → 生成动画 → 导出"的完整流程：

| 乐器                                            | Rust 项目             | Blender 插件           |
| ----------------------------------------------- | --------------------- | ---------------------- |
| FretDance（吉他）                               | `g:\fretDance_rust`   | `fret_dance_blender/`  |
| KeyRipple（钢琴）                               | `h:\key_ripple_rust`  | `key_ripple_blender/`  |
| StringFlow（提琴）                              | `h:\string_flow_rust` | `string_flow_blender/` |
| 其他（ZhengDrift/HarpGlide/WindRise/BeatBloom） | …                     | …                      |

每套插件之间存在大量**重复代码**（集合/物体创建、状态存取、动画写入、导入导出、多演奏者管理），但各自为政、互不相通。这与 Unreal 侧 `MusicDoll` 插件的架构形成鲜明对比：

- **Unreal**：一个 `MusicDoll` 插件，`MusicDollCommon` 提供公共基类 `AInstrumentBase` 与通用工具，各乐器（`FretDanceUnreal`/`KeyRippleUnreal`/`StringFlowUnreal`…）只是它的子类模块。场景中一个 Actor 即一个演奏者实例，插件启动后扫描场景即可切换。
- **Blender**：目前一个乐器一个插件，无统一实例概念。

### 1.2 目标

1. **放弃"一个乐器一个插件"的模式**，改为像 Unreal 一样，用**一个 Blender 插件（music doll blender）管理所有乐器**。
2. 该插件内含一个**公共模块（相当于 MusicDollCommon）**，抽离跨乐器的通用能力（对象/集合创建、状态存取、动画写入、shape key、导入导出、演奏者复制/迁移等）。
3. 设计一套**跨乐器统一的演奏者模式**：所有乐器共用同一套"演奏者实例"数据模型，仅通过属性区分乐器类型。
4. **分阶段迁移**：初期只合并 **FretDance** 与 **KeyRipple** 两个插件；测试稳定后再逐个合并其余乐器。

### 1.3 关键决策（已与用户确认）

| 决策         | 结论                                                                                                                              |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| 新项目路径   | `h:\music_doll_blender`                                                                                                           |
| 统一基础     | **沿用 FretDance 已实现的多演奏者机制**（后缀命名、数据存骨骼、`Performers` 根集合、`FD_` 根物体、复制/迁移算子），提炼进公共模块 |
| 文档落点     | 新建项目内 `docs/` 目录                                                                                                           |
| 初期合并范围 | 仅 FretDance + KeyRipple，测试通过后再扩展                                                                                        |

---

## 2. Unreal MusicDoll 架构参照

### 2.1 模块划分（`h:\stage_1\KeyRipple\Plugins\MusicDoll\Source\`）

```
MusicDoll/
└── Source/
    ├── MusicDollCommon/     ← 公共模块
    │   ├── Public/
    │   │   ├── InstrumentBase.h            # 演奏者统一基类
    │   │   ├── InstrumentAnimationUtility.h# 动画工具
    │   │   ├── InstrumentMorphTargetUtility.h
    │   │   ├── InstrumentControlRigUtility.h
    │   │   ├── InstrumentMaterialUtility.h
    │   │   ├── BoneControlMappingUtility.h
    │   │   ├── ControlInitTransformUtility.h
    │   │   ├── ControlRigCreationUtility.h
    │   │   ├── LipSyncUtility.h
    │   │   ├── Baking/                     # 烘焙任务
    │   │   └── UI/
    │   └── Private/
    ├── FretDanceUnreal/     ← 乐器子模块（吉他）
    ├── KeyRippleUnreal/     ← 乐器子模块（钢琴）
    ├── StringFlowUnreal/    ← 乐器子模块（提琴）
    ├── WindRiseUnreal/      ← 乐器子模块
    ├── ZhengDriftUnreal/    ← 乐器子模块
    ├── HarpGlideUnreal/     ← 乐器子模块
    ├── BeatBloomUnreal/     ← 乐器子模块
    ├── SingerUnreal/        ← 人声子模块
    └── MusicDollUI/         ← 统一 UI（演奏者选择器）
```

### 2.2 核心抽象：`AInstrumentBase`

```cpp
UCLASS(Abstract, Blueprintable)
class MUSICDOLLCOMMON_API AInstrumentBase : public AActor {
    // 演奏者骨骼
    ASkeletalMeshActor* SkeletalMeshActor;
    // IO 文件路径（人物信息保存路径）
    FString IOFilePath;
    // 动画文件路径
    FString AnimationFilePath;
};
```

- 所有乐器类（`AFretDanceUnreal` 等）继承 `AInstrumentBase`；
- 乐器特有的配置/状态（如吉他弦数、钢琴键位）作为子类的额外 UPROPERTY；
- **演奏者实例 = 场景中的一个 Actor**，属性随 Actor 保存。

### 2.3 演奏者切换（`MusicDollUI`）

```cpp
// 遍历场景中所有 AInstrumentBase 派生实例
for (TActorIterator<AInstrumentBase> It(GWorld); It; ++It) {
    SceneActors.Add(TWeakObjectPtr<AInstrumentBase>(*It));
}
// 填入 SComboBox，选中后 Cast<AInstrumentBase> 读取属性
```

**关键点**：演奏者基础信息（骨骼/乐器/路径/类型）保存在**实例本体**上，扫描"世界中所有基类实例"即可枚举出所有演奏者，无需硬编码。

---

## 3. 现状分析（两个待合并插件）

### 3.1 FretDance 插件（`g:\fretDance_rust\fret_dance_blender\`）

**文件清单**：

| 文件                        | 职责                                                                                                                                                                        |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py`               | 插件入口：场景属性、面板、算子注册；多演奏者下拉/后缀/目标骨骼/乐器                                                                                                         |
| `performer_utils.py`        | 演奏者命名空间核心：`resolve`（后缀解析）、`Performers` 根集合、`list_performers`、`get_or_create_performer`、`resuffix_performer`、`duplicate_collection_tree`、约束重映射 |
| `controller_config.py`      | 控制器/记录器命名配置（`obj_name`/`obj` 后缀解析）                                                                                                                          |
| `blender_object_manager.py` | 物体管理：`setup_all_objects`（幂等）、`check_objects_status`、Body/Instruments/addons 集合组织、`FD_` 根物体、`migrate_legacy_to_suffix`                                   |
| `base_states.py`            | `BaseState`：当前演奏者状态上下文（后缀/骨骼/乐器）                                                                                                                         |
| `state_transfer.py`         | 状态存取：控制器 ↔ 骨骼自定义属性；`load_settings`/`save_settings`（无状态化）                                                                                              |
| `io_manager.py`             | 导出/导入 JSON（内容结构与 Unreal 侧一致；导出文件名**不带** `_unreal` 后缀，供 Rust 消费；结构不能变）                                                                     |
| `make_animation.py`         | 动画生成：左手/右手/弦/全部；fcurve 批量写入、shape key、driver 备份恢复                                                                                                    |
| `enums.py`                  | 枚举（乐器类型、位置、左右手状态）                                                                                                                                          |
| `tools/moveString.py`       | 弦创建与 shape key 工具                                                                                                                                                     |
| `migrate_to_suffix.py`      | 已弃用的独立迁移脚本（功能已并入插件按钮）                                                                                                                                  |

**已具备的多演奏者能力（将作为统一基础提炼）**：

- 后缀命名规范 `<短名>_<后缀>`（后缀为空 = 旧场景兼容）；
- `Performers` 顶层根集合 = 演奏者注册表；
- 演奏者 Collection 上存元信息：`performer_suffix` / `performer_name` / `instrument` / `target_skeleton` / `target_instrument`；
- 状态数据与设置存**骨骼（Armature）自定义属性**（无状态化）；
- `FD_<名>` 根空物体：整体系移动/缩放（创建时复制骨骼 TRS）；
- `duplicate_performer`（深拷贝 + 重新后缀 + 约束重映射）、`migrate_legacy`（旧场景迁移）。

### 3.2 KeyRipple 插件（`h:\key_ripple_rust\key_ripple_blender\`）

**文件清单**：

| 文件                               | 职责                                                                                                                                                                               |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py`                      | 插件入口：`KeyRippleProperties` 属性组、面板、算子（setup/check/save/load/export/import/generate）                                                                                 |
| `key_ripple_config.py`             | `KeyRipple` 配置类：`add_controllers`、`setup_all_objects`、`check_objects_status`、`create_or_update_object`、`add_finger_pole_targets`、`add_ext_drivers`、`add_mid_hand_driver` |
| `tools/state_manager.py`           | 状态存取：控制器 ↔ **Mesh 自定义属性**（`keyripple_state_data`）                                                                                                                   |
| `tools/avatar_io.py`               | `.avatar` 文件导入导出（配置 + 状态）                                                                                                                                              |
| `make_animation/make_animation.py` | 动画生成：钢琴键 shape key 动画、fcurve 批量写入、driver 备份恢复                                                                                                                  |
| `tools/mmd2blender.py` 等          | MMD 初始化、shape key、波形等杂项工具（**已弃用，不迁移**，见 §3.4）                                                                                                               |

**与 FretDance 的主要差异**：

1. 状态存在 **Mesh** 上（`keyripple_state_data`），而 FretDance 已统一到**骨骼**上 —— 合并时需按新规范迁移到骨骼；
2. **无多演奏者机制**：命名无后缀、无 `Performers` 根集合、无演奏者选择器；
3. 使用全局缓存实例 `_key_ripple_instance`（非无状态化），需改为从演奏者/骨骼读取设置。

### 3.4 弃用工具清单（不迁移）

以下工具**不再迁移进新插件**，直接在旧插件里废弃：

| 工具 / 脚本                                       | 说明                     |
| ------------------------------------------------- | ------------------------ |
| `tools/mmd2blender.py` 等                         | MMD 相关初始化脚本       |
| Daz Rig 相关脚本                                  | Daz 角色绑定相关         |
| `add_wave` / `generate_wave`                      | 波形生成脚本             |
| `add_emission_mix_shader`                         | 自发光混合着色器脚本     |
| `make_camera_cycle`                               | 摄像机循环脚本           |
| `remove_unused_mat` / `remove_constraints` 等杂项 | 未出现在插件界面上的工具 |

> **通用规则**：旧插件中**没有出现在插件界面（面板/算子按钮）上的工具脚本，一律不迁移**。只迁移用户实际操作中会触达的能力（创建控制器、保存/加载状态、导入导出、生成动画、演奏者管理）。

### 3.3 共性能力清单（应提取为公共模块）

| #   | 能力                                | FretDance 现状                                        | KeyRipple 现状                                                | 提取目标                                       |
| --- | ----------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------- | ---------------------------------------------- |
| 1   | 集合/物体幂等创建                   | `get_or_create_collection`、`create_or_update_object` | 同（在 config 类里）                                          | `common/object_utils.py`                       |
| 2   | 演奏者命名空间                      | `performer_utils.py`（完整）                          | 无                                                            | `common/performer_utils.py`                    |
| 3   | 状态存取（对象 ↔ 字典）             | `state_transfer.py`                                   | `state_manager.py`（`copy_transfer_between_object_and_dict`） | `common/state_io.py`                           |
| 4   | 导入导出 JSON                       | `io_manager.py`                                       | `avatar_io.py`                                                | `common/io_utils.py`（通用读写）+ 各乐器格式层 |
| 5   | 动画写入（fcurve/shape key/driver） | `make_animation.py`                                   | `make_animation.py`                                           | `common/animation_utils.py`                    |
| 6   | 播放者根/复制/迁移                  | 已实现                                                | 无                                                            | `common/performer_utils.py`                    |
| 7   | 演奏者切换 UI                       | 已实现（`fret_dance_active_performer`）               | 无                                                            | `common/ui_utils.py`（通用下拉 + 乐器过滤）    |
| 8   | 状态同步（面板 ↔ 骨骼）             | 已实现                                                | 无（用全局缓存）                                              | `common/state_io.py` + 各乐器接入              |

---

## 4. 统一数据模型设计

### 4.1 演奏者实例 = 一个 Collection

沿用 FretDance 已确定的方案：**`Performers` 根集合下的每个子集合，就是一个演奏者实例**（等价于 Unreal 的场景中一个 `AInstrumentBase` Actor）。

```
Performers/                          ← 顶层根集合（演奏者注册表）
└── <演奏者名>（Collection）         ← 演奏者实例
    ├── <乐器缩写>_<演奏者名>（Empty）← 演奏者根空物体（整体移动/缩放）
    ├── Body_<后缀>                  ← 骨骼 + Mesh
    ├── Instruments_<后缀>           ← 乐器物体
    └── addons_<后缀>                ← 各乐器的控制器/记录器
        ├── Controllers_<后缀>
        └── Recorders_<后缀>
```

### 4.2 统一属性键（存在演奏者 Collection 上）

以下属性**每一个乐器都必须有**，用于识别和切换演奏者实例（对应 `AInstrumentBase` 的字段）：

| 属性键              | 含义                                                      | 对应 Unreal         |
| ------------------- | --------------------------------------------------------- | ------------------- |
| `md_instrument`     | 乐器类型：`fret_dance` / `key_ripple` / `string_flow` / … | 类（子类）          |
| `md_name`           | 演奏者显示名（可中文）                                    | ActorLabel          |
| `md_suffix`         | 命名空间后缀（对象命名用）                                | —                   |
| `md_skeleton`       | 演奏者骨骼（Armature）名称                                | `SkeletalMeshActor` |
| `md_instrument_obj` | 乐器物体名称（Mesh/Empty）                                | 乐器模型            |
| `md_info_path`      | 人物信息保存路径（导入/导出）                             | `IOFilePath`        |
| `md_animation_path` | 动画文件路径                                              | `AnimationFilePath` |

> **兼容策略**：老文件（FretDance 已用 `performer_suffix`/`performer_name`/`instrument`/`target_skeleton`/`target_instrument`）读取时做别名兼容：优先读 `md_*`，缺失则回退旧键。

### 4.3 各乐器特有数据（存骨骼自定义属性）

每个乐器不同的信息（如各状态下的记录器数据、乐器特有设置）统一保存在**演奏者骨骼（Armature）的自定义属性**上，互不干扰：

| 乐器      | 骨骼自定义属性                                                                                   |
| --------- | ------------------------------------------------------------------------------------------------ |
| FretDance | `fret_dance_controller_data`（状态 JSON）、`fret_dance_instrument`、`fret_dance_use_vibrato_bar` |
| KeyRipple | `key_ripple_state_data`（状态 JSON）、`key_ripple_config`（键位/手指数等设置）                   |

> 命名约定：`<乐器>_*` 前缀。合并 KeyRipple 时需把原有 Mesh 上的 `keyripple_state_data` 迁移到骨骼上（提供一次性迁移算子）。

### 4.4 命名规范（沿用 FretDance 约定）

- 对象/集合命名一律 `<短名>_<后缀>`（如 `H_L_Jd`、`Controllers_Jd`）；
- 短名在前、后缀在后，便于手动操作时一眼识别；
- 后缀为空（`""`）表示旧场景兼容模式。

### 4.5 乐器缩写前缀（演奏者根空物体命名）

演奏者根空物体的命名是 **`<乐器缩写>_<演奏者名>`**，其中 `<乐器缩写>` 是乐器类型的大写缩写（不是固定 `FD_`）：

| 乐器类型（`md_instrument`） | 缩写前缀 | 示例      |
| --------------------------- | -------- | --------- |
| `fret_dance`（吉他）        | `FD`     | `FD_Jeht` |
| `string_flow`（小提琴）     | `SF`     | `SF_Lin`  |
| `key_ripple`（钢琴）        | `KR`     | `KR_Aki`  |
| `zheng_drift`（古筝）       | `ZD`     | `ZD_...`  |
| `harp_glide`（竖琴）        | `HG`     | `HG_...`  |
| `wind_rise`（管乐）         | `WR`     | `WR_...`  |
| `beat_bloom`（鼓）          | `BB`     | `BB_...`  |

> - 缩写定义放在 `common/instrument_base.py`（`INSTRUMENT_PREFIX` 映射），公共层按 `md_instrument` 查表得到前缀，不再硬编码 `FD`；
> - 新乐器接入时只需在映射表补一行。

### 4.6 命名空间短名

各乐器在对象命名中的**短名**（控制器/记录器/集合短名）保持各乐器原有约定，公共层只负责把它们和 `<后缀>` 拼接，不关心短名具体含义。

---

## 5. 项目结构设计

### 5.1 顶层结构

```
h:\music_doll_blender\
├── src\                          # 全部源代码（压缩此目录即可安装）
│   ├── __init__.py               # 插件入口：注册公共 + 已合并乐器模块
│   ├── common\                   # 公共模块（相当于 MusicDollCommon）
│   │   ├── performer_utils.py    # 演奏者命名空间（从 FretDance 提炼）
│   │   ├── object_utils.py       # 集合/物体幂等创建
│   │   ├── state_io.py           # 状态存取（对象 ↔ 字典 / 骨骼属性）
│   │   ├── animation_utils.py    # 动画通用（fcurve/shape key/driver/clear）
│   │   ├── io_utils.py           # JSON 通用读写
│   │   ├── instrument_base.py    # 乐器基类（统一属性定义/兼容读取）
│   │   └── ui_utils.py           # 通用 UI 组件（演奏者选择器、乐器过滤）
│   ├── fret_dance\               # FretDance 乐器模块（迁移自 fret_dance_blender）
│   │   ├── __init__.py
│   │   ├── config.py             # 控制器/记录器命名配置
│   │   ├── object_manager.py     # setup / check / 弦工具
│   │   ├── state.py              # 状态存取（乐器特有）
│   │   ├── io.py                 # 导入导出（JSON；文件名不带 _unreal，内容结构与 Unreal 侧一致）
│   │   ├── animation.py          # 左手/右手/弦动画
│   │   └── ui.py                 # FretDance 面板与算子
│   └── key_ripple\               # KeyRipple 乐器模块（迁移自 key_ripple_blender）
│       ├── __init__.py
│       ├── config.py             # KeyRipple 配置
│       ├── object_manager.py     # setup / check
│       ├── state.py              # 状态存取（键盘状态）
│       ├── io.py                 # .avatar 导入导出
│       ├── animation.py          # 钢琴动画
│       └── ui.py                 # KeyRipple 面板与算子
├── docs\                         # 施工文档
│   └── music_doll_blender_施工文档.md
└── README.md
```

### 5.2 插件注册策略（`__init__.py`）

```python
# 伪代码：公共模块始终注册；乐器模块按开关/导入情况注册
from . import common
from .fret_dance import ui as fret_dance_ui
from .key_ripple import ui as key_ripple_ui
```

- 公共模块（`common`）始终加载；
- 每个乐器模块作为独立子包，按需导入并注册；
- 主面板含一个**演奏者选择器**（所有乐器共用）+ 按当前演奏者乐器类型显示对应的**乐器子面板**。

---

## 6. 公共模块 API 设计（`common/`）

### 6.1 `performer_utils.py`（从 FretDance 提炼，做通用化改造）

```python
PERFORMERS_ROOT = "Performers"          # 顶层根集合名

def resolve(short: str, suffix: str) -> str: ...
def strip_duplicate_suffix(name: str) -> str: ...
def suffix_from_object(obj) -> str | None: ...

# 演奏者实例 = Performers 根下的子集合
def list_performers() -> list[PerformerInfo]: ...     # 扫描全部（含 md_instrument）
def get_performer(suffix: str) -> PerformerInfo | None: ...
def has_performer(suffix: str) -> bool: ...
def get_or_create_performer(suffix, name, instrument, target_skeleton=None,
                            target_instrument=None) -> PerformerInfo: ...

# 集合/物体工具（从 object_manager 提炼）
def get_or_create_collection(suffix, short_name, parent=None) -> Collection: ...
def get_or_create_root_collection() -> Collection: ...

# 演奏者级操作
def resuffix_performer(collection, new_suffix, new_name=None) -> PerformerInfo: ...
def duplicate_collection_tree(src, parent=None) -> Collection: ...   # 含约束重映射
def _remap_constraints(obj_map) -> None: ...

# 数据载体约定：状态/设置存骨骼
# 演奏者根空物体命名：<乐器缩写>_<演奏者名>（如 FD_Jeht / KR_Aki），前缀由 instrument_base 查表
def get_performer_root_name(performer) -> str: ...
def organize_performer_root(state) -> None: ...   # 创建/整理根空物体，复制骨骼 TRS，挂接骨骼/控制器根/乐器
def save_settings(skeleton, instrument, use_vibrato_bar): ...
def load_settings(skeleton) -> dict: ...
```

**通用化点**：

- `instrument` 参数由 `str` 明确为乐器类型标识（`fret_dance` / `key_ripple` / …）；
- 统一属性键兼容读取（`md_*` ↔ 旧键）；
- `PerformerInfo` 增加 `info_path` / `animation_path` 字段（默认空）；
- **根空物体不再硬编码 `FD_`**，改为按 `md_instrument` 查表得到 `<乐器缩写>_<演奏者名>`（见 §6.6）。

### 6.2 `object_utils.py`

```python
def create_or_update_object(name, obj_type="cube", collection=None,
                            rotation_mode='QUATERNION', scale=1.0) -> Object: ...
def get_or_create_collection(name, parent_collection=None) -> Collection: ...
def move_object_to_collection(obj, coll) -> None: ...
def move_children(obj, dest_coll) -> None: ...
def create_or_update_empty(name, collection=None) -> Object: ...
```

### 6.3 `state_io.py`

```python
# 对象 ↔ 字典 的通用搬运（处理约束器影响 / 旋转模式）
def get_true_transform_value(obj, transform_type) -> ...: ...
def copy_transfer_between_object_and_dict(obj, data_dict, direction="set"): ...

# 骨骼自定义属性上的状态 JSON 存取
def get_state_data(skeleton, key: str) -> dict | None: ...
def set_state_data(skeleton, key: str, data: dict) -> None: ...

# 面板 ↔ 骨骼 设置同步（无状态化核心）
def load_settings(skeleton) -> dict: ...
def save_settings(skeleton, settings: dict) -> None: ...
```

### 6.4 `animation_utils.py`

```python
# fcurve 批量写入（性能优化：预解析 + 批量写 keyframe_points）
def get_or_create_fcurve(datablock, data_path, index=0): ...
def write_fcurve_points(fcurve, keyframes, clear_existing=True): ...

# shape key 工具
def reset_shape_keys(obj, value=0.0): ...
def clear_shape_key_animation(obj): ...

# driver 备份/恢复（clear 动画时保留驱动）
def backup_driver(driver): ...
def restore_driver(new_driver, backup): ...

# 清动画（多演奏者：按后缀过滤）
def clear_all_keyframe(collection_names=None, exclude_names=None,
                       suffix="", instrument=None): ...

# 批量打关键帧（每帧写入 location/rotation/scale）
def animate_transform(obj, keyframes, ...): ...
```

### 6.5 `io_utils.py`

```python
def save_json(file_path: str, data: dict) -> None: ...
def load_json(file_path: str) -> dict: ...
def ensure_extension(file_path: str, ext: str) -> str: ...
def nested_dict(): ...          # defaultdict 嵌套
```

### 6.6 `instrument_base.py`（统一属性定义与兼容读取）

```python
INSTRUMENT_KEYS = {
    "instrument": "md_instrument",
    "name": "md_name",
    "suffix": "md_suffix",
    "skeleton": "md_skeleton",
    "instrument_obj": "md_instrument_obj",
    "info_path": "md_info_path",
    "animation_path": "md_animation_path",
}
# 旧键 → 新键 的兼容回退表
LEGACY_KEYS = {
    "md_instrument": "instrument",
    "md_suffix": "performer_suffix",
    "md_name": "performer_name",
    "md_skeleton": "target_skeleton",
    "md_instrument_obj": "target_instrument",
}

def get_coll_attr(coll, key): ...   # 新键优先，旧键回退
def set_coll_attr(coll, key, value): ...  # 写新键
def build_performer_info(coll) -> PerformerInfo: ...

# 乐器类型 → 缩写前缀 映射（根空物体命名用，新增乐器时在此补一行）
INSTRUMENT_PREFIX = {
    "fret_dance": "FD",
    "string_flow": "SF",
    "key_ripple": "KR",
    "zheng_drift": "ZD",
    "harp_glide": "HG",
    "wind_rise": "WR",
    "beat_bloom": "BB",
}
def instrument_prefix(instrument: str) -> str: ...   # 未知乐器回退 "MD"
```

### 6.7 `ui_utils.py`（通用演奏者选择器）

```python
def get_performer_items(self, context, instrument_filter=None): ...
    # 扫描 Performers 根，列出全部（或按乐器类型过滤）
def on_active_performer_update(self, context): ...
    # 切换：按 md_instrument 联动目标骨骼/乐器 + 从骨骼回填设置
def draw_performer_selector(layout, scene): ...
def draw_instrument_subpanel(layout, scene, instrument): ...
```

**切换逻辑（对应 Unreal `OnActorComboSelectionChanged`）**：

```
用户切换演奏者下拉
  → 读取该 Collection 的 md_instrument / md_skeleton / md_instrument_obj
  → 填充当前乐器的场景字段（目标骨骼 / 目标乐器）
  → 从骨骼 load_settings 回填面板（无状态化）
  → 若乐器类型与当前面板不一致，切换/启用对应乐器子面板
```

---

## 7. 乐器模块迁移方案

### 7.1 FretDance 迁移（`fret_dance/`）

迁移方式：**原插件文件整体搬入**，仅将公共能力改调 `common/`，保持导出格式与 Rust 兼容。

| 原文件                      | 新位置                         | 改动                                                                                                                                  |
| --------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| `performer_utils.py`        | `common/performer_utils.py`    | 通用化（属性键兼容、instrument 类型化）                                                                                               |
| `controller_config.py`      | `fret_dance/config.py`         | 改调 `common.performer_utils.resolve`                                                                                                 |
| `blender_object_manager.py` | `fret_dance/object_manager.py` | 集合/物体创建改调 `common.object_utils`；根空物体命名改 `<乐器缩写>_<名>`（FD）；保留 `setup_all_objects`/`check_objects_status`/迁移 |
| `base_states.py`            | `fret_dance/base.py`           | 构造改调 `common`                                                                                                                     |
| `state_transfer.py`         | `fret_dance/state.py`          | 通用搬运用 `common.state_io`                                                                                                          |
| `io_manager.py`             | `fret_dance/io.py`             | 通用读写用 `common.io_utils`；导出 JSON 内容结构**不变**（文件名不带 `_unreal`）                                                      |
| `make_animation.py`         | `fret_dance/animation.py`      | fcurve/shape key/driver 用 `common.animation_utils`                                                                                   |
| `enums.py`                  | `fret_dance/enums.py`          | 保留                                                                                                                                  |
| `tools/moveString.py`       | `fret_dance/strings.py`        | 保留                                                                                                                                  |
| `__init__.py`（面板/算子）  | `fret_dance/ui.py`             | 演奏者选择器改调 `common.ui_utils`；场景属性改挂 `md_*` 统一键                                                                        |

**验收**：与现有 FretDance 插件行为一致，导出 JSON 内容结构与旧版字节级一致（文件名不带 `_unreal`）。

### 7.2 KeyRipple 迁移（`key_ripple/`）

| 原文件                             | 新位置                    | 改动                                                                              |
| ---------------------------------- | ------------------------- | --------------------------------------------------------------------------------- |
| `key_ripple_config.py`             | `key_ripple/config.py`    | 集合/物体创建改调 `common.object_utils`；命名接后缀                               |
| `__init__.py`（属性/面板/算子）    | `key_ripple/ui.py`        | 演奏者选择器改调 `common.ui_utils`；属性改挂骨骼（无状态化）                      |
| `tools/state_manager.py`           | `key_ripple/state.py`     | 状态改存**骨骼** `key_ripple_state_data`（原 Mesh）；通用搬运用 `common.state_io` |
| `tools/avatar_io.py`               | `key_ripple/io.py`        | 通用读写用 `common.io_utils`；`.avatar` 格式不变                                  |
| `make_animation/make_animation.py` | `key_ripple/animation.py` | 通用动画用 `common.animation_utils`                                               |

> **KeyRipple 的 `tools/mmd2blender.py`、Daz Rig、`add_wave` 等弃用工具不迁移**（见 §3.4），只迁移界面上的功能。

**KeyRipple 特有改动**：

1. **命名加后缀**：所有对象/集合 `create_or_update_object`/`get_or_create_collection` 自动加 `<短名>_<后缀>`；
2. **状态迁骨骼**：提供一次性算子把旧 Mesh 上的 `keyripple_state_data` 迁移到骨骼；
3. **无状态化**：去掉全局缓存 `_key_ripple_instance`，参数从骨骼 `key_ripple_config` 读取（面板为编辑入口，提交时写回骨骼）；
4. **导出格式**：`.avatar` 文件结构保持兼容（Rust/Unreal 侧继续消费）。

---

## 8. UI 设计

### 8.1 主面板布局

```
┌─ MusicDoll ────────────────────────────┐
│ 演奏者: [Jeht (fret_dance) ▼] [刷新]   │  ← 通用选择器（扫描 Performers 根）
│ 乐器类型: FretDance                    │  ← 只读，来自 md_instrument
│ 目标骨骼: [Armature_Jeht ○]            │
│ 目标乐器: [Guitar ○]                   │
│ 人物信息路径: [........] [导入][导出]  │  ← md_info_path
│ 动画文件路径: [........] [生成动画]    │  ← md_animation_path
├────────────────────────────────────────┤
│ [FretDance 设置]  [KeyRipple 设置]     │  ← 按当前乐器类型高亮对应子面板
│   （按 md_instrument 自动切换）        │
└────────────────────────────────────────┘
```

- 演奏者下拉为**公共组件**：列出 `Performers` 根下所有已登记演奏者（带乐器类型标签）；
- 切换后按 `md_instrument` 自动填充目标骨骼/乐器、回填设置、切换子面板。

### 8.2 面板注册

- 每个乐器模块提供 `PANEL_ID`、`instrument_id`（如 `"fret_dance"`）、`draw(context, layout)`；
- 主面板用 `enum` 在乐器间切换，同一时刻只显示一个乐器子面板；
- 公共的"演奏者/骨骼/乐器/路径"区域固定显示在顶部。

### 8.3 工具界面（Tool 下拉菜单）设计

每个乐器都有一个**工具下拉菜单**（可折叠，默认收起，当前工具为空）：

- 选中某工具后才显示该工具的操作界面；
- 下拉菜单同时列出**所有公共工具** + **该乐器独有工具**；
- 通过统一设计在不同乐器之间共享公共工具，界面简洁（不默认展开所有工具）。

```
┌─ 工具 ────────────────────────────────┐
│ [▼ 折叠] 工具: [（无）        ▼]     │  ← 默认收起/当前为空
│                                        │
│ （选中"修正手指骨骼"后展开）          │
│ ┌─ 修正手指骨骼 ──────────────────┐  │
│ │ [修正手指骨骼]  (按钮执行)       │  │
│ └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

**工具注册机制**：

```python
# common/tools/__init__.py
@dataclass
class ToolDef:
    id: str            # 唯一 id，如 "fix_finger_bones"
    label: str         # 显示名，如 "修正手指骨骼"
    operator: str      # 执行算子的 bl_idname，如 "music_doll.tool_fix_finger_bones"
    icon: str = "TOOL_SETTINGS"
    # 可选：绘制参数区（如弦序号/振幅），签名 draw(layout, context, scene)

COMMON_TOOLS: list[ToolDef] = [...]   # 公共工具（所有乐器共用）
```

**工具归类（已与用户确认）**：

| 工具                         | 归类         | 存放位置                              | 说明                     |
| ---------------------------- | ------------ | ------------------------------------- | ------------------------ |
| 修正手指骨骼                 | **公共**     | `common/tools/fix_finger_ik.py`       | 所有乐器共用             |
| 生成弦（FretDance）          | **乐器独有** | `fret_dance/tools/strings.py`         | 带弦序号/振幅参数        |
| make shape keys（KeyRipple） | **乐器独有** | `key_ripple/tools/make_shape_keys.py` | 钢琴键 pressed shape key |
| mmd2blender 等               | 不迁移       | —                                     | 用户明确弃用             |

**每个乐器模块的接入**：

```python
# 某乐器 ui.py
from ..common.tools import COMMON_TOOLS
from .tools import INSTRUMENT_TOOLS   # 该乐器独有工具列表
TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS
```

- 工具下拉 = 公共工具 + 乐器工具合并；
- 用场景属性 `md_active_tool`（字符串）记录当前选中工具 id；
- 工具界面由 `common/ui_utils.draw_tools(layout, scene, tools)` 统一绘制：折叠 + 下拉 + 按选中工具展开其操作区。

---

## 9. 分阶段实施计划

### Phase 0：项目骨架 + 公共模块

- [ ] 创建 `h:\music_doll_blender` 目录结构与 `bl_info` 入口；
- [ ] 从 FretDance 搬运并通用化 `common/performer_utils.py`（属性键兼容、`md_*` 统一键、`PerformerInfo` 加路径字段）；
- [ ] 提炼 `common/object_utils.py`（集合/物体幂等创建）；
- [ ] 提炼 `common/state_io.py`（对象 ↔ 字典、骨骼设置读写）；
- [ ] 提炼 `common/animation_utils.py`（fcurve/shape key/driver/clear）；
- [ ] 提炼 `common/io_utils.py`（JSON 读写）；
- [ ] 编写 `common/instrument_base.py`（统一属性定义/兼容读取）；
- [ ] 编写 `common/ui_utils.py`（通用演奏者选择器 + 乐器过滤）；
- [ ] 编译检查全部公共模块（`py_compile`）。

**验收**：`common` 模块可在 Blender 中独立加载，提供统一的演奏者枚举/切换 API，不依赖任何乐器模块。

### Phase 1：FretDance 迁入（乐器模块 1）

- [ ] 按 7.1 表迁移 FretDance 全部文件到 `fret_dance/`；
- [ ] 面板/算子改调 `common.ui_utils` 演奏者选择器；
- [ ] 场景属性统一为 `md_*` 键（兼容旧键读取）；
- [ ] `py_compile` 全绿；
- [ ] 用户 Blender 实测：初始化演奏者、保存/加载状态、导出 JSON 与旧版内容一致（文件名不带 `_unreal`）、`FD_` 根移动/缩放、复制演奏者、旧场景迁移。

**验收**：FretDance 全部功能在合并插件内可用，导出格式不变。

### Phase 2：KeyRipple 迁入（乐器模块 2）

- [ ] 按 7.2 表迁移 KeyRipple 全部文件到 `key_ripple/`；
- [ ] 命名接后缀；状态迁骨骼（含一次性迁移算子）；
- [ ] 去掉全局缓存，改无状态化（从骨骼读配置）；
- [ ] 接入 `common.ui_utils` 演奏者选择器；
- [ ] `py_compile` 全绿；
- [ ] 用户 Blender 实测：键盘控制器创建、save/load、`.avatar` 导入导出与旧版一致、钢琴动画生成。

**验收**：KeyRipple 全部功能在合并插件内可用，`.avatar` 格式不变。

### Phase 3：双乐器共存联调

- [ ] 同一 `.blend` 文件内创建 FretDance + KeyRipple 两个演奏者；
- [ ] 通过演奏者下拉在两个乐器演奏者间切换，验证字段/设置联动；
- [ ] 验证后缀命名互不干扰（`H_L_Jd` vs `H_L_Kp` 等）；
- [ ] 验证状态互不串场（各自存各自骨骼属性）。

**验收**：单文件多乐器多演奏者共存，切换正确、数据隔离。

### Phase 4：文档收尾 + 后续乐器接入指南

- [ ] 更新本施工文档为"已完成"状态；
- [ ] 编写"新增乐器接入指南"（如何把 StringFlow 等插件迁入）。

**验收**：文档可指导后续乐器（StringFlow/ZhengDrift/HarpGlide/WindRise/BeatBloom）逐个迁入。

---

## 10. 测试计划

> 注意：Blender 运行时测试由**用户手动**在 Blender 5.0 执行；AI 侧只做 `py_compile` 语法检查 + Pylance 静态检查。

| 用例                    | 步骤                                | 期望                                                                   |
| ----------------------- | ----------------------------------- | ---------------------------------------------------------------------- |
| 公共模块加载            | 安装插件并启用                      | 无报错，主面板出现演奏者选择器                                         |
| FretDance 初始化        | 选骨骼/乐器 → 设置所有对象          | `Body_`/`Instruments_`/`addons_`/`FD_<名>` 根正确生成（缩写=乐器前缀） |
| FretDance 导出          | 保存状态 → 导出 JSON                | 内容与旧版字节级一致（文件名不带 `_unreal`）                           |
| FretDance 复制          | 复制演奏者 → 检查约束/父级/`FD_` 根 | 新演奏者约束指向新控件，层级完整                                       |
| KeyRipple 初始化        | 选骨骼/键盘 → 设置所有对象          | 控制器带后缀正确生成，根物体为 `KR_<名>`                               |
| KeyRipple 导出          | 保存状态 → 导出 `.avatar`           | 与旧版格式一致                                                         |
| 多演奏者切换            | 创建两个乐器演奏者 → 下拉切换       | 字段/设置联动正确，数据隔离，根物体各用各缩写                          |
| 旧场景迁移（FretDance） | 用迁移按钮迁移无后缀场景            | 全部对象归位 + 后缀 + `FD_` 根                                         |

---

## 11. 风险与注意事项

1. **导出格式不可变**：FretDance 的导出 JSON（内容结构与 Unreal 侧一致，但文件名**不带** `_unreal`）与 KeyRipple 的 `.avatar` 是 Rust/Unreal 侧的消费接口，迁移时**结构必须保持兼容**，只能改内部存储位置，不能改导出内容；导出文件名由用户选择，不强制带 `_unreal`。
2. **状态存储位置变更（KeyRipple）**：Mesh → 骨骼的迁移需要一次性算子，且旧 `.blend` 文件需手动触发迁移。
3. **属性键迁移（FretDance）**：`performer_suffix` 等旧键 → `md_*` 新键，需要兼容读取，避免破坏已存在的 `.blend` 文件。
4. **插件 ID/命名冲突**：合并后需统一 `bl_idname` 前缀（如 `music_doll.*`），避免与旧插件共存时冲突；建议用户先卸载旧插件。
5. **Blender 版本**：以 Blender 5.0 为准（`bpy.types.Collection` 无 `.parent`、`collection.users` 是整数等 Blender 5.0 特性已在 FretDance 多演奏者实现中验证过）。
6. **非破坏性验证**：测试前用副本 `.blend` 文件，避免破坏现有工作文件。
7. **用户手动测试**：所有运行时验证由用户执行，AI 负责代码迁移与静态检查。

---

## 12. 附：Unreal ↔ Blender 概念对照表

| Unreal MusicDoll                  | MusicDoll Blender                          |
| --------------------------------- | ------------------------------------------ |
| `AInstrumentBase`（Actor）        | `Performers` 根下的演奏者 Collection       |
| 子类（`AFretDanceUnreal` 等）     | Collection 上的 `md_instrument` 属性       |
| `SkeletalMeshActor`               | `md_skeleton`（骨骼物体）                  |
| 乐器模型                          | `md_instrument_obj`（Instruments 集合）    |
| `IOFilePath`                      | `md_info_path`                             |
| `AnimationFilePath`               | `md_animation_path`                        |
| Actor 自带 UPROPERTY（乐器特有）  | 骨骼自定义属性（`<乐器>_*`）               |
| `TActorIterator<AInstrumentBase>` | `common.performer_utils.list_performers()` |
| `SComboBox` 演奏者选择器          | `common.ui_utils` 演奏者下拉               |
| `MusicDollCommon`                 | `common/`                                  |
