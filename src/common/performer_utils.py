# common/performer_utils.py
"""演奏者命名空间工具 —— 公共模块，所有乐器共用（对应 Unreal 的 AInstrumentBase 管理）

约定：
- 每个演奏者 = 一个「后缀」（namespace id，如 Jd）+ 一个演奏者 Collection（如 Jeht）。
- 插件管理的对象/集合命名一律 `<短名>_<后缀>`（如 `H_L_Jd`、`Controllers_Jd`）；
  短名在前、后缀在后，手动操作时短名一眼可见，后缀只用来区分归属。
- 后缀为空（""）表示兼容旧场景：不加后缀，行为与旧版一致。
- 演奏者身份属性（乐器类型/名称/骨骼/乐器/路径）统一存演奏者 Collection（md_* 键）；
- 各乐器特有的状态/设置数据存演奏者自己的骨骼（Armature）自定义属性。
- 演奏者根空物体命名：<乐器缩写>_<演奏者名>（如 FD_Jeht / KR_Aki），缩写见 instrument_base。

Collection 结构：
    Performers                     ← 顶层容器
    └── <演奏者名>                 ← 演奏者集合（md_* 身份属性）
        ├── <缩写>_<演奏者名>      ← 演奏者根空物体（整体移动/缩放）
        ├── Body_<后缀>            ← 骨骼 + Mesh
        ├── Instruments_<后缀>     ← 乐器物体
        └── addons_<后缀>
            ├── Controllers_<后缀>
            │   ├── Left_Hand_Controllers_<后缀>
            │   └── Right_Hand_Controllers_<后缀>
            └── Recorders_<后缀>
"""
from dataclasses import dataclass
import re

import bpy  # type: ignore

from . import instrument_base
from . import object_utils


# 顶层容器集合名
PERFORMERS_ROOT = "Performers"

# Blender 自动追加的重复名后缀（.001 / .002 ...）
_DUP_RE = re.compile(r"^(.*)\.\d+$")


@dataclass
class PerformerInfo:
    suffix: str  # 命名空间后缀，如 "Jd"
    name: str  # 显示名，可中文
    instrument: str  # 乐器类型，如 "fret_dance" / "key_ripple"
    collection: bpy.types.Collection  # 演奏者 Collection（身份载体）
    target_skeleton: bpy.types.Object | None  # 骨骼（状态/设置数据载体）
    target_instrument: bpy.types.Object | None  # 乐器物体（动画作用域）
    info_path: str = ""  # 人物信息保存路径（导入/导出）
    animation_path: str = ""  # 动画文件路径


# ── 命名转换 ──────────────────────────────────────────────────

def resolve(short: str, suffix: str) -> str:
    """短名 → 完整对象/集合名：resolve("H_L", "Jd") == "H_L_Jd"。

    suffix 为空时原样返回，兼容旧场景（无后缀）。
    """
    if not suffix:
        return short
    return f"{short}_{suffix}"


def strip_duplicate_suffix(name: str) -> str:
    """去掉 Blender 追加的 .001/.002... 后缀：'H_L_Jd.001' -> 'H_L_Jd'"""
    m = _DUP_RE.match(name)
    return m.group(1) if m else name


def performer_from_object(full_name: str) -> tuple[str, str] | None:
    """完整对象名 → (后缀, 短名)：performer_from_object('H_L_Jd') == ('Jd', 'H_L')。

    优先按「已知后缀表」endswith 匹配，避免把短名里的下划线（如 I_L）误判为后缀。
    找不到已知后缀时返回 None（视为 legacy / 未登记对象）。
    """
    base = strip_duplicate_suffix(full_name)
    # 后缀倒序匹配，避免较短后缀（如 Jd）误吞较长后缀
    for p in sorted(list_performers(), key=lambda x: len(x.suffix), reverse=True):
        suf = p.suffix
        if not suf:
            continue
        marker = "_" + suf
        if base.endswith(marker):
            return (suf, base[: -len(marker)])
    return None


def _ancestor_collections(coll: bpy.types.Collection):
    """向上遍历集合的祖先链（含自身），供 suffix_from_object 定位所属演奏者。

    Blender 5.0 起 Collection.parent 属性被移除（一个集合可挂在多个父集合下），
    只能通过遍历 bpy.data.collections 反查「children 中包含该集合」的父集合。
    """
    parents_of: dict[str, list[bpy.types.Collection]] = {}
    for c in bpy.data.collections:
        for child in c.children:
            parents_of.setdefault(child.name, []).append(c)
    stack = [coll]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur.name in seen:
            continue
        seen.add(cur.name)
        yield cur
        stack.extend(parents_of.get(cur.name, []))


def suffix_from_object(obj: bpy.types.Object) -> str | None:
    """给定任意对象，向上找所属演奏者集合，返回后缀（即「先按后缀定位归属」）。"""
    if obj is None:
        return None
    for coll in obj.users_collection:
        for cur in _ancestor_collections(coll):
            suf = instrument_base.get_coll_attr(cur, "suffix")
            if suf:
                return suf
    return None


# ── 演奏者注册表 ──────────────────────────────────────────────

def get_or_create_root_collection() -> bpy.types.Collection:
    if PERFORMERS_ROOT in bpy.data.collections:
        return bpy.data.collections[PERFORMERS_ROOT]
    root = bpy.data.collections.new(PERFORMERS_ROOT)
    if root.name not in [c.name for c in bpy.context.scene.collection.children]:
        bpy.context.scene.collection.children.link(root)
    return root


def get_or_create_collection(suffix: str, short_name: str,
                             parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    """后缀化集合名创建/查找：get_or_create_collection('Jd', 'Controllers') → 'Controllers_Jd'。

    parent 为空时挂到 Performers 根容器下。
    """
    full = resolve(short_name, suffix)
    if parent is None:
        parent = get_or_create_root_collection()
    return object_utils.get_or_create_collection(full, parent)


def find_addons_collection(suffix: str) -> bpy.types.Collection | None:
    """按名字查找本演奏者的 addons 目录（**不创建**）。

    - 有后缀：查 addons_<suffix>（角色初始化时创建）；
    - 无后缀：查全局 addons（兼容旧场景）。
    找不到返回 None。乐器模块 setup 阶段用它做「先初始化角色」的前置校验。
    """
    return bpy.data.collections.get(resolve("addons", suffix))


def _find_skeleton_in_collection(coll: bpy.types.Collection) -> bpy.types.Object | None:
    for obj in coll.objects:
        if obj.type == "ARMATURE":
            return obj
    for child in coll.children:
        obj = _find_skeleton_in_collection(child)
        if obj is not None:
            return obj
    return None


def _find_instrument_in_collection(coll: bpy.types.Collection) -> bpy.types.Object | None:
    """在演奏者集合的 Instruments_<后缀> 子集合里找乐器物体（MESH 或父级 EMPTY）"""
    for child in coll.children:
        if not child.name.startswith("Instruments_"):
            continue
        for obj in child.objects:
            if obj.type in ("MESH", "EMPTY"):
                return obj
        for sub in child.children:
            for obj in sub.objects:
                if obj.type in ("MESH", "EMPTY"):
                    return obj
    return None


def list_performers(context=None) -> list[PerformerInfo]:
    """扫描 Performers 集合下的子集合，按演奏者后缀生成列表。"""
    result: list[PerformerInfo] = []
    if PERFORMERS_ROOT not in bpy.data.collections:
        return result
    root = bpy.data.collections[PERFORMERS_ROOT]
    for coll in root.children:
        name = instrument_base.get_coll_attr(coll, "name") or coll.name
        if not name:
            continue
        skel = _find_skeleton_in_collection(coll)
        inst = _find_instrument_in_collection(coll)
        result.append(PerformerInfo(
            suffix=name,
            name=name,
            instrument=instrument_base.get_coll_attr(coll, "instrument") or "",
            collection=coll,
            target_skeleton=skel,
            target_instrument=inst,
            info_path=instrument_base.get_coll_attr(coll, "info_path") or "",
            animation_path=instrument_base.get_coll_attr(
                coll, "animation_path") or "",
        ))
    return result


def get_performer(suffix: str) -> PerformerInfo | None:
    for p in list_performers():
        if p.suffix == suffix:
            return p
    return None


def has_performer(suffix: str) -> bool:
    return get_performer(suffix) is not None


# ── 新建角色整理：改名加后缀 + 移入 Body_/Instruments_ ─────────

def _apply_suffix_to_object(obj: bpy.types.Object, suffix: str) -> None:
    """给对象名加后缀（幂等）：'Armature' -> 'Armature_Jd'；已带后缀则不动。"""
    if obj is None or not suffix:
        return
    base = strip_duplicate_suffix(obj.name)
    marker = "_" + suffix
    if base.endswith(marker):
        return
    obj.name = f"{base}_{suffix}"


def organize_performer_objects(collection: bpy.types.Collection, suffix: str,
                               skeleton: bpy.types.Object | None = None,
                               instrument: bpy.types.Object | None = None) -> None:
    """把新建角色的骨架/Mesh/乐器改名加后缀并移入 Body_/Instruments_ 集合。

    - 骨架（Armature）与其 Mesh 子级 → Body_<suffix>；
    - 乐器物体 → Instruments_<suffix>；
    - 统一按 <原名>_<suffix> 改名（幂等，已带后缀/已在目标集合的对象不重复处理）。
    """
    if not suffix:
        return
    body_coll = get_or_create_collection(suffix, "Body", parent=collection)
    inst_coll = get_or_create_collection(
        suffix, "Instruments", parent=collection)

    if skeleton is not None:
        _apply_suffix_to_object(skeleton, suffix)
        object_utils.move_object_to_collection(skeleton, body_coll)
        for child in list(skeleton.children):
            if child.type == "MESH":
                _apply_suffix_to_object(child, suffix)
                object_utils.move_object_to_collection(child, body_coll)
                if child.parent != skeleton:
                    child.parent = skeleton
    if instrument is not None:
        _apply_suffix_to_object(instrument, suffix)
        object_utils.move_object_to_collection(instrument, inst_coll)


def get_or_create_performer(suffix: str, name: str, instrument: str,
                            target_skeleton: bpy.types.Object | None = None,
                            target_instrument: bpy.types.Object | None = None,
                            info_path: str = "",
                            animation_path: str = "") -> PerformerInfo:
    """创建/获取演奏者集合（含 Body_<suffix> / Instruments_<suffix> 骨架），并登记身份属性。

    新建时会把骨架/Mesh/乐器改名加后缀并移入对应集合；
    若同后缀演奏者已存在，直接返回（不重复创建、不重复改名）。
    """
    existing = get_performer(suffix)
    if existing is not None:
        return existing

    # 名字即后缀：只存一份 md_name
    final_name = name or suffix

    root = get_or_create_root_collection()
    if final_name in bpy.data.collections:
        coll = bpy.data.collections[final_name]
    else:
        coll = bpy.data.collections.new(final_name)
    if coll.name not in [c.name for c in root.children]:
        root.children.link(coll)

    instrument_base.set_coll_attr(coll, "name", final_name)
    instrument_base.set_coll_attr(coll, "instrument", instrument)

    # 建 Body / Instruments / addons 三个骨架（addons 在角色创建时一并建好，
    # 各乐器的 setup 阶段只查找它、不再自行创建）
    get_or_create_collection(final_name, "Body", parent=coll)
    get_or_create_collection(final_name, "Instruments", parent=coll)
    get_or_create_collection(final_name, "addons", parent=coll)

    # 新建角色：把骨架/Mesh/乐器改名加后缀并移入对应集合（一步整理到位）
    organize_performer_objects(
        coll, final_name, target_skeleton, target_instrument)

    # 登记身份属性（在改名之后，记录新的对象名）
    if target_skeleton is not None:
        instrument_base.set_coll_attr(coll, "skeleton", target_skeleton.name)
    if target_instrument is not None:
        instrument_base.set_coll_attr(
            coll, "instrument_obj", target_instrument.name)
    if info_path:
        instrument_base.set_coll_attr(coll, "info_path", info_path)
    if animation_path:
        instrument_base.set_coll_attr(coll, "animation_path", animation_path)

    perf = PerformerInfo(
        suffix=final_name, name=final_name, instrument=instrument,
        collection=coll, target_skeleton=target_skeleton,
        target_instrument=target_instrument,
        info_path=info_path, animation_path=animation_path,
    )
    # 创建演奏者根空物体 <乐器缩写>_<名称> 并挂载骨骼/乐器（与复制角色一致）
    organize_performer_root(perf)
    return perf


# ── 演奏者根空物体（命名 <乐器缩写>_<演奏者名>）──────────────

def get_performer_root_name(performer: PerformerInfo) -> str:
    """演奏者根空物体名：<乐器缩写>_<演奏者名>（如 FD_Jeht / KR_Aki）。"""
    prefix = instrument_base.instrument_prefix(performer.instrument)
    return f"{prefix}_{performer.name}"


def get_or_create_performer_root(performer: PerformerInfo,
                                 collection: bpy.types.Collection | None = None) -> bpy.types.Object:
    """创建/获取演奏者根空物体（整体移动/缩放整个演奏者体系）。

    创建时复制骨骼的位置/旋转/缩放；已存在则保持原位。
    """
    root_name = get_performer_root_name(performer)
    root_obj = bpy.data.objects.get(root_name)
    if root_obj is None:
        root_obj = object_utils.create_or_update_empty(root_name, collection)
        if performer.target_skeleton is not None:
            object_utils.copy_transform_from(
                performer.target_skeleton, root_obj)
    return root_obj


def organize_performer_root(performer: PerformerInfo) -> bpy.types.Object | None:
    """创建/获取演奏者根空物体 <乐器缩写>_<名称>，并挂接身体（骨骼）为子级。

    - 根在创建时复制骨骼的 transform；把骨骼挂到根下后本地 transform 归零
      （从世界坐标观察身体不变），之后整体移动/缩放根即可带动身体。
    - **乐器不挂根**：由用户手动把乐器绑定到 controller_root（吉他挂
      controller_root_offset）。
    - 控制器根等乐器独有挂载由各乐器 setup 阶段的 `_organize_performer_root` 补充。
    幂等：重复调用无副作用。
    """
    if performer is None or not performer.name:
        return None
    root_obj = get_or_create_performer_root(performer, performer.collection)
    skeleton = performer.target_skeleton
    if skeleton is not None:
        object_utils.parent_and_zero_local(root_obj, skeleton)
    return root_obj


# ── 集合深拷贝（复制演奏者用）──────────────────────────────────

def duplicate_collection_tree(src: bpy.types.Collection,
                              parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    """深拷贝一个集合（含子集合与对象）。

    - 对象用 copy() 创建（共享数据，类似 Shift+D）；
    - 对象自定义属性一并复制（含骨骼上的状态数据/设置）；
    - 集合自定义属性不自动复制（调用方按需设置，如 performer_suffix 交给 resuffix）；
    - 父级关系用「全局 obj_map」重建：只要父级也在复制范围内，就指向新复制的副本，
      跨集合的父级同样生效（例如手掌 H_L 的父级 controller_root_offset 在不同集合里），
      不会残留指向原物体的父级导致层级被破坏；
    - 约束器里的对象引用重映射为新副本；
    - 新集合挂到 parent 下（默认 Performers 根）。
    """
    new_root = None
    obj_map: dict[bpy.types.Object, bpy.types.Object] = {}

    def _create_coll(coll: bpy.types.Collection, parent_coll: bpy.types.Collection | None):
        nonlocal new_root
        new_coll = bpy.data.collections.new(coll.name)
        if parent_coll is not None:
            parent_coll.children.link(new_coll)
        else:
            get_or_create_root_collection().children.link(new_coll)
        if new_root is None:
            new_root = new_coll
        # 拷贝本集合的直接对象（进入全局 obj_map）
        for obj in coll.objects:
            new_obj = obj.copy()
            # 兜底复制自定义属性（copy() 通常已复制 ID 属性）
            for key, value in obj.items():
                if key not in new_obj:
                    try:
                        new_obj[key] = value
                    except Exception:
                        pass
            new_coll.objects.link(new_obj)
            obj_map[obj] = new_obj
        # 递归子集合
        for child in coll.children:
            _create_coll(child, new_coll)

    _create_coll(src, parent)

    # 重建父级：全部复制完后统一处理，跨集合的父级也指向新副本
    for old, new in obj_map.items():
        if old.parent in obj_map:
            new.parent = obj_map[old.parent]

    # 重映射约束器：obj.copy() 不会更新约束里指向旧物体的引用
    _remap_constraints(obj_map)

    return new_root


def _remap_constraints(obj_map: dict[bpy.types.Object, bpy.types.Object]):
    """把复制后对象（含骨骼 pose bone）上约束器里指向源集合旧对象的引用替换为新副本。

    - 处理对象级约束（obj.constraints）与骨骼姿态约束（pose.bones[].constraints）；
    - 处理通用 `target` 字段，以及 ARMATURE 约束的 `targets[].target`；
    - 只替换在 obj_map 内的旧对象，其余引用保持不动。
    """
    def _remap_constraint(constraint):
        target = getattr(constraint, "target", None)
        if isinstance(target, bpy.types.Object) and target in obj_map:
            try:
                constraint.target = obj_map[target]
            except Exception:
                pass
        targets = getattr(constraint, "targets", None)
        if targets is not None:
            for t in targets:
                ref = getattr(t, "target", None)
                if isinstance(ref, bpy.types.Object) and ref in obj_map:
                    try:
                        t.target = obj_map[ref]
                    except Exception:
                        pass

    for new_obj in obj_map.values():
        for constraint in new_obj.constraints:
            _remap_constraint(constraint)
        if new_obj.type == 'ARMATURE':
            for pbone in new_obj.pose.bones:
                for constraint in pbone.constraints:
                    _remap_constraint(constraint)


# ── 重新后缀（复制/修复通用）──────────────────────────────────

def _iter_collections(coll: bpy.types.Collection):
    yield coll
    for child in coll.children:
        yield from _iter_collections(child)


def _iter_objects(coll: bpy.types.Collection):
    yield from coll.objects
    for child in coll.children:
        yield from _iter_objects(child)


def resuffix_performer(collection: bpy.types.Collection, new_suffix: str,
                       new_name: str | None = None) -> PerformerInfo:
    """把整个演奏者集合（含 .001 复制品）统一重新后缀为新后缀。

    - 去掉 Blender 追加的 .001；
    - 对象/集合名里的旧后缀替换为新后缀；
    - 修复演奏者身份属性（md_suffix / md_name / md_skeleton / md_instrument_obj）；
    - 返回新的 PerformerInfo。
    注意：ext 等 driver 需要调用方按新后缀重建。
    """
    old_suffix = instrument_base.get_coll_attr(collection, "suffix") or ""
    old_name = instrument_base.get_coll_attr(
        collection, "name") or collection.name
    if new_name is None:
        new_name = old_name

    # 1) 集合改名（跳过根集合，根集合最后单独改）
    child_collections = list(collection.children)
    for coll in child_collections:
        base = strip_duplicate_suffix(coll.name)
        coll.name = _swap_suffix_in_name(
            base, old_suffix, old_name, new_suffix, new_name)
    for coll in child_collections:
        _resuffix_nested_collections(
            coll, old_suffix, old_name, new_suffix, new_name)

    # 2) 对象改名
    for obj in _iter_objects(collection):
        base = strip_duplicate_suffix(obj.name)
        obj.name = _swap_suffix_in_name(
            base, old_suffix, old_name, new_suffix, new_name)

    # 3) 根集合改名 + 身份属性（名字即后缀，只写一份 md_name）
    collection.name = new_name
    instrument_base.set_coll_attr(collection, "name", new_name or new_suffix)
    instrument_base.set_coll_attr(
        collection, "instrument", instrument_base.get_coll_attr(collection, "instrument") or "")
    old_skel = instrument_base.get_coll_attr(collection, "skeleton") or ""
    if old_skel and old_skel in bpy.data.objects:
        instrument_base.set_coll_attr(collection, "skeleton", _swap_suffix_in_name(
            old_skel, old_suffix, old_name, new_suffix, new_name))
    elif old_skel:
        instrument_base.set_coll_attr(collection, "skeleton", old_skel)
    old_inst = instrument_base.get_coll_attr(
        collection, "instrument_obj") or ""
    if old_inst and old_inst in bpy.data.objects:
        instrument_base.set_coll_attr(collection, "instrument_obj", _swap_suffix_in_name(
            old_inst, old_suffix, old_name, new_suffix, new_name))
    elif old_inst:
        instrument_base.set_coll_attr(collection, "instrument_obj", old_inst)

    return PerformerInfo(
        suffix=new_name or new_suffix,
        name=new_name or new_suffix,
        instrument=instrument_base.get_coll_attr(
            collection, "instrument") or "",
        collection=collection,
        target_skeleton=_find_skeleton_in_collection(collection),
        target_instrument=_find_instrument_in_collection(collection),
        info_path=instrument_base.get_coll_attr(collection, "info_path") or "",
        animation_path=instrument_base.get_coll_attr(
            collection, "animation_path") or "",
    )


def _resuffix_nested_collections(coll: bpy.types.Collection, old_suffix: str,
                                 old_name: str, new_suffix: str, new_name: str):
    for child in coll.children:
        base = strip_duplicate_suffix(child.name)
        child.name = _swap_suffix_in_name(
            base, old_suffix, old_name, new_suffix, new_name)
        _resuffix_nested_collections(
            child, old_suffix, old_name, new_suffix, new_name)


def _swap_suffix_in_name(base: str, old_suffix: str, old_name: str,
                         new_suffix: str, new_name: str) -> str:
    """把名字里的旧后缀/旧演奏者名替换为新后缀/新名。"""
    if old_suffix:
        marker = "_" + old_suffix
        if base.endswith(marker):
            return base[: -len(marker)] + "_" + new_suffix
    if old_name and old_name != new_name and base.endswith("_" + old_name):
        return base[: -(len(old_name) + 1)] + "_" + new_name
    if old_name and old_name != new_name and base == old_name:
        return new_name
    # 无后缀的 legacy 对象：直接补新后缀
    if not new_suffix:
        return base
    return f"{base}_{new_suffix}"
