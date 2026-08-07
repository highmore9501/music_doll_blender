# common/instrument_base.py
"""乐器基类 / 统一属性定义 —— 公共模块（对应 Unreal 的 AInstrumentBase）

所有乐器共用的演奏者身份属性（存在演奏者 Collection 上），以及
乐器类型 → 缩写前缀的映射（演奏者根空物体命名用）。

约定：
- 规范键：md_*（存演奏者 Collection 上）；
- 旧键兼容：老文件（FretDance 已用 performer_suffix 等）读取时回退；
- 演奏者根空物体命名：<乐器缩写>_<演奏者名>（如 FD_Jeht / KR_Aki）。
"""

# ── 统一属性键（演奏者 Collection 上）──────────────────────────

# 逻辑键名 → 规范键（md_*）
INSTRUMENT_KEYS = {
    "instrument": "md_instrument",
    "name": "md_name",
    "suffix": "md_suffix",
    "skeleton": "md_skeleton",
    "instrument_obj": "md_instrument_obj",
    "info_path": "md_info_path",
    "animation_path": "md_animation_path",
}

# 规范键（md_*）→ 旧键（兼容回退读取）
LEGACY_KEYS = {
    "md_instrument": "instrument",
    "md_suffix": "performer_suffix",
    "md_name": "performer_name",
    "md_skeleton": "target_skeleton",
    "md_instrument_obj": "target_instrument",
}

# ── 乐器类型 → 缩写前缀（根空物体命名）────────────────────────

INSTRUMENT_PREFIX = {
    "fret_dance": "FD",
    "string_flow": "SF",
    "key_ripple": "KR",
    "zheng_drift": "ZD",
    "harp_glide": "HG",
    "wind_rise": "WR",
    "beat_bloom": "BB",
}

# 未知乐器回退前缀
FALLBACK_PREFIX = "MD"


def instrument_prefix(instrument: str) -> str:
    """乐器类型 → 缩写前缀；未知乐器回退 'MD'。"""
    return INSTRUMENT_PREFIX.get(instrument, FALLBACK_PREFIX)


def canonical_key(key: str) -> str:
    """逻辑键名 → 规范键名（md_*）；已带 md_ 前缀或未知则原样返回。"""
    return INSTRUMENT_KEYS.get(key, key)


def legacy_key(key: str) -> str | None:
    """规范键（md_*）→ 旧键；无旧键返回 None。"""
    return LEGACY_KEYS.get(key)


# ── 演奏者 Collection 属性读写（新键优先，旧键回退）───────────

def get_coll_attr(coll, key: str):
    """按逻辑键读取演奏者 Collection 属性；新键（md_*）优先，旧键回退。"""
    canon = canonical_key(key)
    if canon in coll:
        return coll[canon]
    legacy = legacy_key(canon)
    if legacy and legacy in coll:
        return coll[legacy]
    return None


def set_coll_attr(coll, key: str, value) -> None:
    """按逻辑键写入演奏者 Collection 属性（写规范键 md_*）。"""
    coll[canonical_key(key)] = value


def has_coll_attr(coll, key: str) -> bool:
    """判断演奏者 Collection 是否含某逻辑键（新键或旧键）。"""
    canon = canonical_key(key)
    if canon in coll:
        return True
    legacy = legacy_key(canon)
    return bool(legacy and legacy in coll)
