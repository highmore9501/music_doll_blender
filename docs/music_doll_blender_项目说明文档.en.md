# MusicDoll Blender Project Documentation

> [中文](music_doll_blender_项目说明文档.md) | **English**

> Version: v1.0
> Date: 2026-08
> Codebase: `h:\music_doll_blender`
> This document is written based on the construction docs in `docs/` and the actual code in `src/`. It is the entry point for understanding this project's architecture, module breakdown, data model and development workflow.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Layout](#2-repository-layout)
3. [Core Architecture: The Performer Model](#3-core-architecture-the-performer-model)
4. [The Common Module (`common/`) in Detail](#4-the-common-module-common-in-detail)
5. [Unified UI Design](#5-unified-ui-design)
6. [The Tool System](#6-the-tool-system)
7. [Instrument Modules in Detail](#7-instrument-modules-in-detail)
8. [Data File Formats Summary](#8-data-file-formats-summary)
9. [Development, Deployment and Verification](#9-development-deployment-and-verification)
10. [Key Conventions and Caveats](#10-key-conventions-and-caveats)
11. [Guide for Adding a New Instrument](#11-guide-for-adding-a-new-instrument)
12. [Documentation Index](#12-documentation-index)
13. [Appendix: Unreal ↔ Blender Concept Mapping](#13-appendix-unreal--blender-concept-mapping)

---

## 1. Project Overview

### 1.1 What it is

MusicDoll Blender is a **unified instrument-animation add-on for Blender (5.0+)**. One add-on manages the whole performance-animation pipeline for every instrument, and a single Blender file can hold multiple performers of *different* instruments (guitarist, pianist, violinist…) with fully isolated data.

It borrows the architecture of the identically-named Unreal plugin MusicDoll: **one framework owns the common parts, each instrument plugs in as one module, and everyone shares the same rules**. On the Unreal side that is `MusicDollCommon` + instrument sub-modules (`FretDanceUnreal` / `KeyRippleUnreal` / …); on the Blender side it maps to the `common/` module + instrument packages (`fret_dance` / `key_ripple` / …).

### 1.2 Why it exists

The project's predecessor was a **separate Blender add-on per instrument**:

| Instrument | Rust project | Original Blender add-on |
| ---------- | ------------ | ----------------------- |
| FretDance (guitar) | `fretDance_rust` | `fret_dance_blender` |
| KeyRipple (piano) | `key_ripple_rust` | `key_ripple_blender` |
| StringFlow (violin) | `string_flow_rust` | `string_flow_blender` |
| ZhengDrift / HarpGlide / WindRise / BeatBloom | their own Rust projects | their own Blender add-ons |

The "one instrument, one add-on" model caused three problems:

1. **Heavy code duplication**: every add-on re-implemented "create controllers → save states → generate animation → import/export → manage multiple performers";
2. **No coexistence**: putting a guitarist and a pianist in one Blender file was painful — the two add-ons didn't know about each other;
3. **No shared features**: adding a common feature (like Fix Finger Bones) meant editing every add-on.

So the decision was made to **fold every instrument into one add-on**, managed by a common module — that is MusicDoll Blender.

### 1.3 Design goals (from the construction doc)

1. Abandon "one instrument, one add-on" and manage all instruments from a single add-on;
2. Include a common module (the equivalent of MusicDollCommon) extracting cross-instrument capabilities: object/collection creation, state storage, animation writing, shape keys, import/export, performer duplication/migration;
3. Design a **unified performer model** shared by all instruments, distinguished only by attributes;
4. **Migrate in phases**: start with FretDance + KeyRipple, then merge the rest one by one once stable (now all merged).

### 1.4 Current status

- **bl_info**: version `0.1.0`, Blender `5.0.0`, author BigHippo78, category Animation, panel at `View3D > Sidebar > MusicDoll`;
- **7 instrument modules merged**: `fret_dance` (guitar, Phase 1), `key_ripple` (piano, Phase 2), `zheng_drift` (guZheng, Phase 3), `beat_bloom` (percussion, Phase 4), `harp_glide` (harp), `wind_rise` (wind), `string_flow` (violin);
- Build status: code migration and deployment are complete; Blender runtime testing is performed manually by the user (see each instrument's build report).

### 1.5 Typical workflow

1. **Install**: rename `src\` to `music_doll_blender` and put it in Blender's add-ons directory, or zip `src\` and drag it into "Preferences → Add-ons";
2. Enable the **MusicDoll Blender** add-on;
3. Find the **MusicDoll** panel in the right sidebar of the 3D viewport;
4. In the "Performer Selector", create a performer (name + instrument type + target skeleton + instrument object);
5. Click **Setup Objects** in the instrument sub-panel to build the controllers;
6. Pose → "Set/Load State" → export performer info → choose an animation file → generate animation.

---

## 2. Repository Layout

```
music_doll_blender/
├── src/                          # All source code (zip this directory to install)
│   ├── __init__.py               # Add-on entry: registers common + instrument modules
│   ├── common/                   # Common module (Unreal MusicDollCommon equivalent; namespace package, no __init__.py)
│   │   ├── performer_utils.py    # Performer namespace (core)
│   │   ├── instrument_base.py    # Unified attribute keys / instrument prefix mapping
│   │   ├── object_utils.py       # Idempotent collection/object creation
│   │   ├── state_io.py           # State storage (object↔dict / bone custom properties)
│   │   ├── io_utils.py           # JSON I/O / Unreal coordinate conversion
│   │   ├── animation_utils.py    # Animation utilities (fcurve / shape key / driver)
│   │   ├── ui_utils.py           # Unified main panel / performer selector / tool UI
│   │   └── tools/                # Shared tools
│   │       ├── __init__.py       # ToolDef / COMMON_TOOLS
│   │       ├── fix_finger_ik.py  # Fix finger bones (shared by all instruments)
│   │       └── bone_controller_mapping.py  # Bone/controller mapping
│   ├── fret_dance/               # FretDance guitar module (Phase 1)
│   ├── key_ripple/               # KeyRipple piano module (Phase 2)
│   ├── zheng_drift/              # ZhengDrift guZheng module (Phase 3)
│   ├── beat_bloom/               # BeatBloom percussion module (Phase 4)
│   ├── harp_glide/               # HarpGlide harp module
│   ├── wind_rise/                # WindRise wind module
│   └── string_flow/              # StringFlow violin module
├── docs/                         # Project documentation (EN/CN, shipped with the repo); other construction docs are internal records (not uploaded)
├── music_doll_blender.zip        # Distribution package (built locally, not uploaded to the repo)
├── README.md                     # Project intro (Chinese)
├── README.en.md                  # Project intro (English)
└── .gitignore                    # Ignores __pycache__/, docs/ (except the project docs), zip
```

### 2.1 Standard structure of an instrument module

Per the standard skeleton in *Instrument Module Migration Engineering Guide*, `src/<instrument>/` usually contains:

```
src/<instrument>/
├── __init__.py     # Module docstring (which source add-on it was migrated from)
├── enums.py        # State enums + object types (mapped to common.object_utils strings)
├── config.py       # <Instrument>Config: naming tables + add_controllers / add_ext_drivers /
│                   #   special orientations & constraints / add_recorders / check_* / setup_all_objects /
│                   #   _organize_* / _get_addons_collection / special driver registration
├── state.py        # State transfer (controllers ↔ bone custom properties) + state-specific logic
├── io.py           # Import/export (JSON keys use short names; paths use SCENE_INFO_PATH)
├── animation.py    # Animation generation (left/right hand / strings / special orientation / clear keyframes keeping drivers)
├── tools/
│   ├── __init__.py # INSTRUMENT_TOOLS (ToolDef) + register/unregister
│   └── <tool>.py   # Instrument-specific tool implementation
└── ui.py           # PropertyGroup + panel + operators + rename/duplicate + register/unregister
```

> Structure note: `config` owns "naming tables + object creation + setup"; `state` / `io` / `animation` each have their own responsibility (this simplified structure is used by key_ripple / zheng_drift). fret_dance additionally splits out `object_manager.py` / `base.py` (multiple inheritance via `BaseState`); both styles are fine, but new migrations are advised to follow the simplified structure.

---

## 3. Core Architecture: The Performer Model

This is the foundation of the whole add-on; every instrument shares the same model. It mirrors the Unreal side: `AInstrumentBase` (Actor) = performer instance, with attributes saved on the instance.

### 3.1 A performer instance = a Collection under the Performers root

`Performers` is the **top-level root collection** (performer registry) in the scene; **each of its child collections is one performer instance**.

```
Performers/                          ← top-level root collection (performer registry)
└── <Performer Name> (Collection)   ← performer instance (md_* identity attributes live here)
    ├── <Instrument Prefix>_<Performer Name> (Empty) ← performer root empty (move/scale the whole performer)
    ├── Body_<suffix>               ← skeleton + mesh
    ├── Instruments_<suffix>        ← instrument objects
    └── addons_<suffix>             ← each instrument's controllers/recorders
        ├── Controllers_<suffix>
        │   ├── controller_root (EMPTY; moving instruments add controller_root_offset)
        │   ├── <hand/foot/special>_Controllers_<suffix> ……
        │   └── Bilinear_Helpers_<suffix> (if any)
        └── Recorders_<suffix>
            └── String_Positions_<suffix> (physical position markers such as string endpoints, if any)
```

- The **performer root empty** is named `<Instrument Prefix>_<Performer Name>` (e.g. `FD_Jeht` / `KR_Aki`) and is used to move/scale the whole performer; on creation it copies the skeleton's transform, then parents the skeleton under it and zeroes the local transform (the body appears unchanged from world space).
- The **instrument is not parented to the root**: the user manually binds it to `controller_root` (fixed instruments) or `controller_root_offset` (moving instruments).

### 3.2 Identity attributes (`md_*`, stored on the performer Collection)

| Logical key | Canonical key | Meaning | Unreal equivalent |
| ----------- | ------------- | ------- | ----------------- |
| `instrument` | `md_instrument` | Instrument type (`fret_dance` / `key_ripple` / …) | Class (subclass) |
| `name` / `suffix` | `md_name` | Performer name (ASCII; doubles as the namespace suffix) | ActorLabel |
| `skeleton` | `md_skeleton` | Performer skeleton (Armature) name | SkeletalMeshActor |
| `instrument_obj` | `md_instrument_obj` | Instrument object name (Mesh/Empty) | Instrument mesh |
| `info_path` | `md_info_path` | Performer info save path (import/export) | IOFilePath |
| `animation_path` | `md_animation_path` | Animation file path | AnimationFilePath |

**Key conventions**:

- **Name is the suffix**: `md_name` doubles as the namespace suffix (e.g. `Jeht` → object suffix `_Jeht`); there is no separate `md_suffix` key;
- **Legacy key fallback**: old files used `performer_suffix` / `performer_name` / `instrument` / `target_skeleton` / `target_instrument`; reads prefer `md_*` and fall back to the legacy keys (see `LEGACY_KEYS` in `common/instrument_base.py`);
- Switching performers auto-links the target skeleton/instrument from `md_*` and re-fills settings from the skeleton (stateless design).

### 3.3 Naming conventions

1. **Suffix-based naming**: all add-on-managed objects/collections are named `<short>_<suffix>` (e.g. `H_L_Jd`, `Controllers_Jd`). The short name comes first for easy recognition; the suffix only distinguishes ownership;
2. **Empty suffix (`""`)** means legacy-scene compatibility: no suffix is added, behaving like the old versions;
3. **Instrument prefix** (used for the performer root empty; defined in `INSTRUMENT_PREFIX` in `common/instrument_base.py`):

| Instrument type | Prefix | Example |
| --------------- | ------ | ------- |
| `fret_dance` (guitar) | FD | `FD_Jeht` |
| `string_flow` (violin) | SF | `SF_Lin` |
| `key_ripple` (piano) | KR | `KR_Aki` |
| `zheng_drift` (guZheng) | ZD | `ZD_...` |
| `harp_glide` (harp) | HG | `HG_...` |
| `wind_rise` (wind) | WR | `WR_...` |
| `beat_bloom` (drums) | BB | `BB_...` |

Unknown instruments fall back to the prefix `MD`. Adding a new instrument only requires one extra row in the mapping table.

### 3.4 Data storage conventions

| Data | Storage location |
| ---- | ---------------- |
| Performer identity (`md_*`) | Performer Collection custom properties |
| Instrument-specific states/settings | **Performer skeleton (Armature) custom properties** (JSON strings) |
| Physical position markers (string endpoints, fret positions, key points) | Scene objects (kept as physical reference points) |

**States are always stored on the skeleton — no recorder objects are generated** — this is the core decision of the migration engineering, avoiding dozens/hundreds of extra objects in the scene (e.g. StringFlow originally created ~230 state-recorder spheres; after migration all became skeleton JSON).

Bone custom-property keys per instrument:

| Instrument | State key | Settings key |
| ---------- | --------- | ------------ |
| fret_dance | `fret_dance_controller_data` | `fret_dance_instrument` / `fret_dance_use_vibrato_bar` |
| key_ripple | `key_ripple_state_data` | (stored within the state JSON) |
| zheng_drift | `zheng_drift_state_data` | `zheng_drift_bilinear_data` (four-state helpers) |
| beat_bloom | `beat_bloom_state_data` | `beat_bloom_drumkit_config` |
| harp_glide | `harp_glide_state_data` | (config section inside the state JSON) |
| wind_rise | `wind_rise_state_data` | (config section inside the state JSON) |
| string_flow | `string_flow_state_data` | — |
| Shared performer settings | `md_settings` (DEFAULT_SETTINGS_KEY) | — |

### 3.5 Performer lifecycle

- **Create performer**: `music_doll.create_performer` operator (performer generator) — dialog for name (ASCII letters/digits only) / instrument type / skeleton / instrument object → `performer_utils.get_or_create_performer` creates the Collection + `Body_` / `Instruments_` / `addons_` skeletons, renames and moves objects, and creates the performer root empty;
- **Duplicate performer**: each instrument provides a `duplicate_performer` operator — `duplicate_collection_tree` deep-copies the collection (objects share data, custom properties copied, **parent/constraint/modifier references remapped via obj_map**) → `resuffix_performer` re-suffixes → finally rebuilds ext drivers + `_organize_performer_root`;
- **Rename performer**: each instrument provides a `rename_performer` operator — validates the new name → `resuffix_performer` → same final steps;
- **Legacy migration** (fret_dance): the `migrate_legacy` operator migrates a non-suffixed legacy scene into the current performer system.

### 3.6 Duplicate/rename implementation details (`performer_utils.py`)

- `duplicate_collection_tree(src, parent)`: deep-copies the collection tree. Objects use `copy()` (shared data, like Shift+D); object custom properties are copied too (including skeleton state data/settings); parenting is rebuilt via a global `obj_map` (cross-collection parents work too); constraint and modifier object references are remapped to the new copies;
- `resuffix_performer(collection, new_suffix, new_name)`: re-suffixes the whole performer collection (including `.001` duplicates) — strips Blender's appended `.001`, replaces the old suffix in object/collection names, fixes identity attributes (md_name / md_skeleton / md_instrument_obj). Note: drivers such as ext must be rebuilt by the caller for the new suffix.

---

## 4. The Common Module (`common/`) in Detail

The common module corresponds to Unreal's `MusicDollCommon`. It is the "foundation for all instruments", does not depend on any instrument module, and can be loaded standalone in Blender.

### 4.1 instrument_base.py — unified attribute keys / instrument prefixes

Responsibility: unified attribute-key definitions with compatible reads, and instrument-type → prefix mapping.

- `INSTRUMENT_KEYS`: logical key → canonical key (`md_*`) mapping; `suffix` is an alias of `name` (both read/write `md_name`);
- `LEGACY_KEYS`: canonical key → legacy key fallback table (`md_instrument` ← `instrument`, `md_name` ← `performer_name`, `md_skeleton` ← `target_skeleton`, `md_instrument_obj` ← `target_instrument`);
- `INSTRUMENT_PREFIX`: instrument type → prefix (FD/SF/KR/ZD/HG/WR/BB), unknown falls back to `MD`;
- `get_coll_attr` / `set_coll_attr` / `has_coll_attr`: performer Collection attribute read/write, new keys first with legacy fallback.

### 4.2 performer_utils.py — the performer namespace (core)

Responsibility: performer registry, name conversion, collection organization, duplicate/rename, root empty. It is the largest module shared by all instruments.

**Name conversion**:

- `resolve(short, suffix)`: short name → full object/collection name (`resolve("H_L", "Jd") == "H_L_Jd"`; empty suffix returns it unchanged);
- `strip_duplicate_suffix(name)`: strips Blender's appended `.001/.002...`;
- `performer_from_object(full_name)`: full object name → `(suffix, short)`, matched by known suffixes in reverse-length order via endswith to avoid misreading underscores inside short names;
- `suffix_from_object(obj)`: for any object, walks up to find the owner performer collection and returns its suffix (since Blender 5.0 removed `Collection.parent`, parent-child relations are reverse-looked-up by scanning `bpy.data.collections`).

**Performer registry**:

- `PERFORMERS_ROOT = "Performers"` top-level root collection;
- `get_or_create_root_collection()` / `get_or_create_collection(suffix, short_name, parent)`;
- `find_addons_collection(suffix)`: looks up the addons directory by name (**does not create**; suffixed → `addons_<suffix>`, unsuffixed → global `addons`). Instrument `setup` uses it as the "character initialized first" precondition check;
- `list_performers(context)` / `get_performer(suffix)` / `has_performer(suffix)`: scan Performers children, returning `PerformerInfo` (suffix/name/instrument/collection/skeleton/instrument object/paths);
- `PerformerInfo`: a dataclass with suffix / name / instrument / collection / target_skeleton / target_instrument / info_path / animation_path.

**New-performer organization**:

- `organize_performer_objects(collection, suffix, skeleton, instrument)`: renames the skeleton/mesh/instrument with the suffix and moves them into `Body_` / `Instruments_` (idempotent);
- `get_or_create_performer(suffix, name, instrument, ...)`: creates/gets the performer collection (with the three skeletons), registers identity attributes, creates the root empty.

**Performer root empty**:

- `get_performer_root_name(performer)`: `<Instrument Prefix>_<Performer Name>`;
- `get_or_create_performer_root(performer, collection)`: copies the skeleton's transform on creation;
- `organize_performer_root(performer)`: creates the root and parents the skeleton (`parent_and_zero_local`, unchanged from world space); **the instrument is not parented** (bound manually by the user); each instrument's setup adds controller_root etc. via its own `_organize_performer_root`.

**Duplicate & rename**: `duplicate_collection_tree` (deep copy + constraint/modifier remap), `resuffix_performer` (re-suffix + fix identity), `_swap_suffix_in_name` (name replacement utility).

### 4.3 object_utils.py — idempotent collection/object creation

Responsibility: collection creation, object create/update, object moving shared by all instruments (naming with suffixes is left to the caller).

- `get_or_create_collection(name, parent_collection)`: reuse if it exists, otherwise create and link under the given parent;
- `move_object_to_collection(obj, collection)` / `move_children(obj, dest_coll)`;
- `create_or_update_object(obj_name, obj_type, collection, rotation_mode, scale)`: idempotent object creation. Supported types: `cube` / `cone` / `sphere` (empty sphere) / `circle` (empty ring, for IK poles) / `cone_empty` / `single_arrow`; unknown types fall back to a sphere empty;
- `create_or_update_empty(obj_name, collection)`;
- `parent_to(parent_obj, child_obj)`: parents (keeping world position);
- `zero_local_transform(obj)` / `parent_and_zero_local(parent, child)` / `copy_transform_from(src, dst)`: transform utilities.

### 4.4 state_io.py — state storage

Responsibility: state storage shared by all instruments (the equivalent of each add-on's state_transfer / state_manager).

- `get_true_transform_value(obj, transform_type)`: reads the object's **true transform** (handles constraint influence via the evaluated depsgraph);
- `copy_transfer_between_object_and_dict(obj, data_dict, direction, key)`: obj ↔ JSON dict transfer. `direction="set"` reads loc/rot from obj into the dict; `direction="load"` applies the reverse. `key` is optional and decouples data keys from scene object names (scene controls carry suffixes; bone data keys use short names);
- `get_state_data(skeleton, key, default)` / `set_state_data(skeleton, key, data)`: JSON state read/write on bone custom properties;
- `get_bone_attr` / `set_bone_attr`: any scalar/string attribute read/write;
- `load_settings` / `save_settings`: shared performer settings stored under the skeleton JSON key `md_settings` (instruments may override or reuse).

### 4.5 io_utils.py — JSON I/O / Unreal coordinate conversion

Responsibility: JSON file read/write, extension handling, nested-dict utilities shared by all instruments, and the **Blender ↔ Unreal coordinate conversion**.

- `nested_dict()`: recursive nested defaultdict;
- `ensure_extension(file_path, ext)` / `save_json` / `load_json` (returns `{}` if missing or unparseable);
- `dump_dict_to_json_str` / `load_dict_from_json_str`: dict ↔ JSON string (for custom properties);
- `to_unreal_position(pos)`: Blender position → Unreal position, **Y-axis negated**: `[x, -y, z]`;
- `to_unreal_rotation(rot)`: Blender quaternion `[w,x,y,z]` → Unreal: under the reflection M=diag(1,-1,1) the rotation must be `R_u = M·R_b·M`; the reflection-conjugate flips the axis and negates the angle, so the quaternion becomes **`[w, -x, y, -z]`** (not the conjugate `(w,-x,-y,-z)`).

> Each instrument's "Export to Unreal" button calls these functions with `for_unreal=True` (see §8.2 for coordinate conversion details and the ×100 scale note).

### 4.6 animation_utils.py — animation utilities

Responsibility: animation writing and clearing shared by all instruments (the common part of each add-on's make_animation).

- `collect_collection_objects(col, exclude_names, object_names)`: recursively collect object names in a collection;
- `get_or_create_fcurve(datablock, data_path, index)`: find or create an fcurve in an animation action (**compatible with Blender 4.x and 5.x**: since 5.0 Action no longer exposes `fcurves` directly; `Action.fcurve_ensure_for_datablock()` is used instead);
- `write_fcurve_points(fcurve, keyframes, clear_existing)`: batch-write fcurve keyframe points (much faster than per-frame `frame_set` + `keyframe_insert`; VECTOR handles + BEZIER interpolation);
- `reset_shape_keys(obj, value)` / `clear_shape_key_animation(obj)`: shape-key utilities;
- `backup_driver(driver)` / `restore_driver(new_driver, backup)`: deep driver backup/restore (keep drivers when clearing animation);
- `clear_all_keyframe(collection_names, exclude_names, suffix)`: clear keyframes (filtered by performer suffix for multi-performer isolation);
- `clear_all_keyframe_preserve_drivers(...)`: **clear keyframes but preserve drivers** (backup → clear → restore), for scenes that need to keep drivers on target objects — the migration guide explicitly requires this when clearing animation, since per-object `animation_data_clear()` destroys ext / Middle_Hand drivers.

### 4.7 ui_utils.py — unified UI / main panel

Responsibility: the Unreal MusicDollUI performer-selector equivalent. Provides the unified main panel and all shared UI components.

**Scene public properties** (registered by `register_scene_props`, prefix `md_`):

| Property | Meaning |
| -------- | ------- |
| `md_active_performer` | Current performer (enum) |
| `md_target_skeleton` | Target skeleton (pointer) |
| `md_target_instrument` | Target instrument (pointer) |
| `md_info_path` | Performer info path (the single source for import/export paths) |
| `md_show_tools` | Tools section collapsed |
| `md_active_tool` | Currently selected tool id |
| `md_show_performer_generator` | Performer generator collapsed |
| `md_show_performer_ops` | Performer ops collapsed |

**Key functions**:

- `get_active_suffix` / `get_active_performer` / `active_instrument`: current-performer queries. Note the Blender 5.0 CJK encoding bug: scene enums may carry corrupted bytes and raise UnicodeDecodeError; reads catch it and try to self-heal;
- `get_target_skeleton` / `get_target_instrument`: scene pointer first, then selected objects / performer registry;
- `get_performer_items`: dropdown items (scans Performers root; skips non-ASCII/bytes names);
- `on_active_performer_update`: switch linkage (fills skeleton/instrument/path);
- `on_target_skeleton_update`: selecting a skeleton auto-selects its owner performer;
- `on_info_path_update`: editing the path writes back to the identity attribute;
- `performer_of(obj)`: any object → its owner performer (reads ID properties, immune to the enum encoding issue);
- `get_rename_target(context)`: locates the performer to rename/duplicate (skeleton pointer → instrument pointer → dropdown → selected object, degrading gracefully);
- `register_instrument` / `unregister_instrument` / `INSTRUMENT_UI`: instrument UI registry (label / panel / rename_operator / duplicate_operator);
- `get_instrument_items`: instrument dropdown items for the performer generator (only registered instruments).

**Unified main panel `MUSICDOLL_PT_main_panel`** (the only top-level panel, three blocks):

1. **Performer selector** (always visible) + **performer generator** (collapsed by default);
2. **Performer ops** (collapsed by default; basic info + duplicate/rename buttons, wired per instrument);
3. **Instrument sub-panel**: drawn automatically by Blender via `bl_parent_id`; each instrument's `poll` filters (`ui_utils.active_instrument(context) == "<instrument id>"`).

**Tool UI `draw_tools(layout, scene, tools)`**: collapsible + dropdown to pick a tool + expands the picked tool's parameter area. The dropdown lists shared tools + instrument-specific tools; implemented with an injected context + Menu (`_CURRENT_TOOL_UI`) together with `MUSICDOLL_OT_set_active_tool` and `MUSICDOLL_MT_tool_menu`.

**Performer generator operator `MUSICDOLL_OT_create_performer`**: `music_doll.create_performer`. Because Blender 5.0 operators do not support PointerProperty, the skeleton/instrument objects reuse the scene-level pointer properties (edited directly in the dialog). Name validation: ASCII alphanumeric starting with a letter (CJK rejected).

### 4.8 common/tools/ — shared tools

**ToolDef** (dataclass): a tool's metadata (id / label / operator / icon / optional draw parameter area). `find_tool(tools, tool_id)` looks up by id.

**COMMON_TOOLS** (shown in every instrument's dropdown):

| Tool | id | operator | Notes |
| ---- | -- | -------- | ----- |
| Fix Finger Bones | `fix_finger_bones` | `music_doll.tool_fix_finger_bones` | Fixes the finger-bone shape of a selected bone chain (arc-like distribution). Usage: select a reference object + the armature (active object), then in edit mode select the chain's root bone and execute |
| Bone/Controller Mapping | `bone_controller_mapping` | (no single button) | Bone ↔ controller mapping panel: add/remove mappings, one-click sync controllers to bone positions (by hierarchy depth), export/import the mapping JSON (`md_bcm_`-prefixed properties to avoid conflicts with the standalone add-on) |

Each instrument's tool list = `COMMON_TOOLS + INSTRUMENT_TOOLS` (`TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS`).

---

## 5. Unified UI Design

### 5.1 Panel hierarchy

```
MusicDoll (bl_category, the only top-level panel MUSICDOLL_PT_main_panel)
├── Performer Selector (always visible; dropdown empty by default)
├── Performer Generator (collapsed by default; Create Performer button)
├── Performer Ops (collapsed by default; basic info + duplicate/rename, wired per instrument)
└── Instrument sub-panel (only the current instrument's one is shown, per md_instrument)
    ├── FretDance   (FRET_DANCE_PT_main_panel)
    ├── KeyRipple   (KEYRIPPLE_PT_main_panel)
    ├── ZhengDrift  (ZHENG_PT_main_panel)
    ├── BeatBloom   (BEATBLOOM_PT_main_panel)
    ├── HarpGlide   (HARPGLIDE_PT_main_panel)
    ├── WindRise    (WINDRISE_PT_main_panel)
    └── StringFlow  (STRINGFLOW_PT_main_panel)
```

Every instrument sub-panel has `bl_parent_id = "MUSICDOLL_PT_main_panel"`, `bl_category = "MusicDoll"`, and `poll = ui_utils.active_instrument(context) == "<id>"`. The parent panel must be registered before the instrument sub-panels (`bl_parent_id` validation); unregistration is strictly reverse-order.

### 5.2 Common structure of an instrument sub-panel

Instrument sub-panels are broadly similar and usually contain (order may vary):

1. **Initialization**: instrument parameters (finger count, string count, etc.) + Check Status + Setup Objects buttons;
2. **Tools area**: `ui_utils.draw_tools(layout, scene, tools=TOOLS)` (shared + instrument-specific);
3. **State selection**: left/right hand position/state enum dropdowns;
4. **Set / Load**: buttons that save/load the current state to/from the skeleton;
5. **Import/Export**: Import / Export (path from the "Performer Info Path" in the performer-ops panel) + "Export to Unreal" button;
6. **Generate animation**: animation file path (the instrument panel's single FILE_PATH) + left/right hand / strings / generate-all buttons.

### 5.3 Stateless design

The add-on keeps **no global cached instances** (`_key_ripple_instance` and similar were removed): every operator builds its config from the current performer suffix, settings are read from the skeleton (`load_settings`), and the panel is only an editing surface that writes back to the skeleton on commit (`save_settings`). Switching performers re-fills the panel from the skeleton.

---

## 6. The Tool System

Tools are the "small shared feature set" of every instrument, collected in a collapsible dropdown, hidden by default, keeping the UI clean.

### 6.1 Tool registration mechanism

```python
# common/tools/__init__.py
@dataclass
class ToolDef:
    id: str            # unique id, e.g. "fix_finger_bones"
    label: str         # display name, e.g. "Fix Finger Bones"
    operator: str      # executing operator's bl_idname, e.g. "music_doll.tool_fix_finger_bones"
    icon: str = "TOOL_SETTINGS"
    draw: Callable = None   # optional parameter-area draw function draw(layout, scene)
```

- Shared tools live in `common/tools/` (`COMMON_TOOLS`); instrument-specific tools live in each instrument's `tools/__init__.py` (`INSTRUMENT_TOOLS`);
- Each instrument panel uses `TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS`, drawn uniformly via `ui_utils.draw_tools(layout, scene, tools=TOOLS)`;
- Tool parameters use **scene-level properties** (registered inside the tool module, guarded idempotently by hasattr), so they do not pollute the instrument PropertyGroup;
- Objects created by tools carry the performer suffix;
- Tools with `operator=""` provide their own buttons inside the parameter area (e.g. bone/controller mapping).

### 6.2 Instrument-specific tools overview

| Instrument | Tool | operator | Parameters |
| ---------- | ---- | -------- | ---------- |
| fret_dance | Create Strings (shape keys) | `music_doll.tool_fret_dance_create_string` | string index / amplitude (scene props) |
| key_ripple | Create Shape Keys for Piano Keys | `music_doll.tool_key_ripple_make_shape_keys` | none (run on selected keys) |
| zheng_drift | Create String Shape Keys / Linear-Distribute Recorders | `music_doll.tool_zheng_*` | string index 0–20 / amplitude ratio |
| beat_bloom | (no instrument-specific tools; shared tools only) | — | — |
| harp_glide | Create String Shape Key / Batch-Create All Strings / Linear-Distribute String Positions | `harp_glide.create_string_shape_key` etc. | string count / amplitude |
| wind_rise | Axis-Rotation Tool / Axis-Move Tool | (buttons inside the parameter area) | — |
| string_flow | Create Violin String / Generate ShapeKeys | `music_doll.tool_string_flow_create_violin_string` etc. | string index / offset ratio / reverse-fret order |

### 6.3 Typical tool implementation locations

- Shared: `common/tools/fix_finger_ik.py`, `common/tools/bone_controller_mapping.py`;
- fret_dance: `fret_dance/tools/strings.py` (`create_string_with_shape_keys`, select start→end objects to build the string with 0–20 fret shape keys), `fret_dance/tools/export_to_unreal.py`;
- key_ripple: `key_ripple/tools/make_shape_keys.py` (Basis + pressed shape keys), `key_ripple/tools/export_to_unreal.py`;
- zheng_drift: `zheng_drift/tools/string_tools.py` (right-hand tremolo + left-hand pressing shape keys, linear distribution), `zheng_drift/tools/export_to_unreal.py`;
- harp_glide: `harp_glide/tools/string_tools.py` (vibration direction read from the skeleton JSON), `harp_glide/tools/export_to_unreal.py`;
- wind_rise: `wind_rise/tools/axis_rotation_tool.py` (in Edit Mode, define a rotation axis from two objects' positions and rotate selected vertices in real time), `wind_rise/tools/export_to_unreal.py`;
- string_flow: `string_flow/tools/make_violin_string.py` (three-point-plane string shape keys), `string_flow/tools/export_to_unreal.py`.

> Each instrument's "Export to Unreal" is an `(Operator, ExportHelper)` class that opens a file browser and calls `io.export_*(..., for_unreal=True)`.
>
> Note the operator prefix: most instruments use `music_doll.<instrument>_*` (and tool operators `music_doll.tool_<instrument>_*`); **harp_glide is the exception**, keeping the `harp_glide.*` prefix (e.g. `harp_glide.save_hand_pose`, `harp_glide.export`).

---

## 7. Instrument Modules in Detail

The following are the core profiles of the 7 instrument modules (controller layout / state model / import-export / animation / specific logic). Naming always carries the performer suffix (`<short>_<suffix>`); JSON keys consumed by the Rust side are always short names.

### 7.1 FretDance (guitar, `fret_dance/`)

**Type**: moving instrument (has `controller_root_offset`; the instrument moves with the body). Supports fingerstyle guitar / electric guitar / bass (`Instruments` enum 0/1/2).

**Controller layout**:

- Left hand: palm `H_L`, IK pivot `HP_L`, thumb `T_L` (grouped with the palm; not used for playing), fingers `I_L`/`M_L`/`R_L`/`P_L`;
- Right hand: palm `H_R`, IK pivot `HP_R`, thumb `T_R` + fingers `I_R`/`M_R`/`R_R`/`P_R` (the right thumb does play);
- Fret-position markers: `Fret_P0`–`Fret_P4` (physical objects, user-movable);
- Hierarchy: controllers → `controller_root_offset` → `controller_root`; finger IK/poles, ext driver (`2×finger − palm` when a palm is present, `2×finger` otherwise; LOCAL_SPACE; cleared-then-rebuilt idempotently).

**State model** (stored on the skeleton, key `fret_dance_controller_data`):

- Left hand: `BasePositions(P0–P4) × LeftHandStates(NORMAL/OUTER/INNER/BARRE)`, with an `invalid_combinations` table (e.g. P0 doesn't allow INNER, P1 doesn't allow OUTER);
- Right hand: `RightHandStates(low/end/high + optional vibrato release/up/down)`;
- Settings: `fret_dance_instrument` / `fret_dance_use_vibrato_bar` (electric-guitar vibrato bar).

**Import/export** (`io.py`): JSON (filename chosen by the user, without the `_unreal` suffix; content structure matches the Unreal side and is consumed by Rust — **the structure must not change**):

- `NORMAL/OUTER/INNER/BARRE_LEFT_HAND_POSITIONS`: left-hand controllers grouped by state;
- `LEFT_FINGER_POSITIONS`: fret positions (read from physical objects);
- `RIGHT_HAND_POSITIONS`: right-hand controllers; recorder names are computed from internal state + controller name (Spanish fingering mapping: `T_R→p`, `I_R→i`, `M_R→m`, `R_R→a`, `P_R→ch`; vibrato `Vibrato_*_H_R` etc.);
- `OTHER_SETTING`: `is_unreal` / `use_vibrato_bar`.

**Animation** (`animation.py`): left hand / right hand / string animation / controller-root offset (guitar offset) / generate all. Reads animation JSON (`[{frame, fingerInfos: {controller name: {position, rotation}}}]`), batch-writes fcurves, with quaternion sign-consistency handling.

**Specific tools**: Create Strings (shape keys).

**Panel**: initialization (instrument type / vibrato toggle + Check/Setup + migrate legacy scene), tools area, left/right-hand state selection, set & load, import/export, generate animation.

### 7.2 KeyRipple (piano, `key_ripple/`)

**Type**: fixed instrument (no `controller_root_offset`).

**Controller layout**:

- Finger controllers: `0_L`–`(N-1)_L` + `N_R`–`(2N-1)_R` (`one_hand_finger_number` fingers per hand, default 5);
- Palm/pivots: `H_L` / `HP_L` / `H_R` / `HP_R`; ext (`2×finger` driver) + poles; `Mid_Hand` (world-midpoint driver), `Head_Control`;
- Keyboard reference points: `black_key` / `highest_white_key` / `lowest_white_key` / `lowest_white_key_end` / `normal_hand_expand_position` / `wide_expand_hand_position` (physical Empties).

**State model** (stored on the skeleton, key `key_ripple_state_data`, a JSON array):

- Dimensions: `key_type(white/black) × position_type(high/low/middle)`;
- Each state entry: `{key_type, position_type, controllers: {short controller name: {location, rotation}}}`; left-hand states additionally include `Head_Control`;
- `set_state_data` merges controllers by (key_type, position_type) rather than replacing.

**Import/export** (`io.py`): `.avatar` file (still consumed by the Rust/Unreal side; format compatible):

- `config`: one_hand_finger_number / seven position parameters / min_key / max_key / hand_range / is_unreal;
- `finger_recorders.{left/right}_finger_recorders`, `hand_recorders.{left/right}_hand_recorders`, `target_points_recorders.head_position_recorders`: named `{position_type}_{key_type}_{ctrl}`;
- `key_board_positions`: keyboard reference points.

**Animation** (`animation.py`): reads animation JSON (left/right hand + feet + head_control sections), batch-writes fcurves.

**Specific tools**: create shape keys for piano keys.

**Panel**: Initialization (finger count/keyboard params + Check/Setup), tools area, left/right-hand state selection, Hand State Transfer (Set/Load), Avatar I/O (Export/Import/Export to Unreal), Animation Generation.

### 7.3 ZhengDrift (guZheng, `zheng_drift/`)

**Type**: fixed instrument, 21 strings.

**Controller layout**:

- 7 main controllers per hand: `H_L/HP_L/T_L/I_L/M_L/R_L/P_L` (right symmetric) + per-finger `*_pole` poles + `ext_*` (`ext = 2×finger` driver, LOCAL_SPACE);
- Feet: `F_L` / `F_R` + `F_L_pole` / `F_R_pole`;
- Special orientation: `Middle_Hand` (world-midpoint driver of H_L/H_R, WORLD_SPACE), `Look_At` (parented to Middle_Hand), `Head_Control` (world object + TrackTo Look_At);
- Bilinear helpers: `Middle_Hand_A~D` / `Head_Control_A~D` (four-state drivers; `bilinear_map` registered into `bpy.app.driver_namespace`);
- String-position markers: `s0head`–`s20head`, `s0end`–`s20end`, `s0mid`–`s20mid` (63 physical reference points, not parented to controller_root; string tools read world `.location`).

**State model** (stored on the skeleton, key `zheng_drift_state_data`; `zheng_drift_bilinear_data` holds the four-state helpers):

- Left hand: `action(Normal/Press) × position(far/middle/near)`; right hand: `action(Normal/Tremolo) × position(far/middle/near)`;
- Structure: `{left_hand/right_hand: {action: {position: {short controller name: {location, rotation}}}}}`;
- **Four-state detection** (A: left Normal + right Tremolo far; B: left Press + right Normal far; C: left Normal + right Tremolo near; D: left Press + right Normal near): on Save, Middle_Hand / Head_Control positions are stored on the skeleton; on Load they are restored.

**Import/export** (`io.py`): `.zheng_master` standard-pose file (short JSON keys compatible with Rust):

- `STRING_RECORDERS`: string-position markers (objects);
- `LEFT/RIGHT_HAND_RECORDERS`: left/right-hand states (skeleton; keys like `H_L_Normal_far`);
- `FOOT_CONTROLLERS`: foot controllers (objects); `BILINEAR_HELPERS`: bilinear helpers (skeleton).

**Animation** (`animation.py`): left hand / right hand / string vibration / special-orientation target (Head_Control) / generate all. Animation config `.zhengdrift` (contains performance / target / string sub-files + relative path resolution).

**Specific tools**: string shape keys (right-hand tremolo / left-hand pressing), linear-distribute recorders.

**Panel**: initialization (Check/Setup), tools area, left/right-hand state selection (position + action), set & load (incl. four states), import/export standard poses, generate animation.

### 7.4 BeatBloom (percussion, `beat_bloom/`)

**Type**: fixed instrument. Controls remain as scene objects (9 base controls + helpers; the module comments also mention "12 controls" for the operable controller set); the original recorder objects are abolished; states live on the skeleton.

**Controller layout**:

- 9 base controls: palms `H_L`/`H_R`, IK pivots `HP_L`/`HP_R`, feet `F_L`/`F_R`, special orientation `Middle_Hand` (real-time midpoint)/`Look_At` (parented to Middle_Hand)/`Head_Control` (TrackTo);
- Helper controls (created/driven only, **not participating in save/load/export/import data flow**): five fingers per hand `T/I/M/R/P_L/R` + ext (parented to palm) + per-finger poles (thumb `TP_L/TP_R`, others `<finger>_pole`), foot poles `FP_L`/`FP_R`.

**State model** (stored on the skeleton, key `beat_bloom_state_data`; `beat_bloom_drumkit_config` holds the drumkit config):

- Structure: `{<component_name>: {<state>: {<ctrl_short>: {location, rotation}}}, "rest": {...}, "mapping_helpers": {A/B/C/D: {Middle_Hand, Head_Control, H_L, H_R}}}`;
- States: `beat / ready / rest`;
- The controllers saved per component are decided by `drivable_limbs`: right_hand → H_R/HP_R + Head_Control; left_hand → H_L/HP_L + Head_Control; right_foot → F_R; left_foot → F_L.

**Import/export** (`io.py`): `.drummer` file (Rust-compatible flat format):

- `RECORDER_INFO`: flat keys `<component>_<state>_<ctrl_short>`; rest maps to `H_Rest_L` / `H_Rest_R` etc.;
- `MAPPING_HELPERS`: `Middle_Hand_A/B/C/D`, `Head_Control_A/B/C/D`, `Left_Hand_A/B/C/D`, `Right_Hand_A/B/C/D`.

**Animation** (`animation.py`): reads animation JSON (left/right_hand + left/right_foot + head_control sections), batch-writes fcurves.

**Specific tools**: none (shared tools only).

**Panel**: DrumKit Config (Load DrumKit Config), initialization (Setup Objects), tools area, Set/Load State (component + state), Mapping Helpers (A/B/C/D slots), export/import `.drummer`, animation (Execute Animation).

### 7.5 HarpGlide (harp, `harp_glide/`)

**Type**: fixed instrument (47 strings by default, configurable). Structured as `HarpConfig` + `HarpObjectManager` + `HarpBaseState`.

**Controller layout**:

- Body: `Head`, `Shoulder_Harp` (parented to harp_pivot);
- 7 main controllers per hand: `H_L/HP_L/T_L/I_L/M_L/R_L/P_L` (right symmetric), **fingers parented to H_L/H_R** (unlike wind_rise), ext (`2×finger`, LOCAL_SPACE) + poles;
- Feet: `F_L`/`F_R` + `FP_L`/`FP_R`;
- Sight helpers: `Mid_Hand` (world-midpoint driver, not parented to controller_root), `Look_At` (parented to Mid_Hand);
- Harp pivot: `harp_pivot` (parented to controller_root);
- String-position markers: `s{n}head` / `s{n}end` (physical Empties, parented to harp_pivot, moving with the harp).

**State model** (stored on the skeleton, key `harp_glide_state_data`, includes a config section):

- `config`: string_count / left_far / left_near / left_mid_far / left_mid_near / right_far / right_near;
- `pedal_positions`: `pedal_{D/C/B/E/F/G/A}_{state0~4}` (D/C/B left foot, E/F/G/A right foot; **includes harp_pivot coordinate conversion**: world ↔ pivot local);
- `harp_pivot_states`: near/mid/far (harp tilt);
- `hand_poses`: left/right × far/near/attack/rest;
- `head_poses`: far/near/attack/rest;
- `foot_rest`: F_L / F_R.

**Import/export** (`io.py`): `.harpist` file (Rust-compatible flat recorder keys):

- `STRING_RECORDERS` (objects) / `PEDAL_POSITION_RECORDERS` / `HARP_PIVOT_RECORDERS` / `LEFT/RIGHT_HAND_RECORDERS` (flattened `H_L_far` etc.) / `HEAD_RECORDERS` (`Head_far`) / `FOOT_REST_RECORDERS` (`F_rest_L` / `F_rest_R`).

**Animation** (`animation.py`): harp animation (harp_pivot), performance animation (hands/feet/head), pedal shape keys, string shape keys, generate all (reads a `.harpglide` report).

**Specific tools**: create string shape keys / batch-create all strings / linear-distribute string positions (vibration direction read from the skeleton JSON `hand_poses.left.far/near`).

**Panel**: harp settings (string count + six position params + save config to skeleton), initialization, tools area, state settings (hand+head poses / pedals / harp tilt / foot rest), data file `.harpist`, generate animation.

### 7.6 WindRise (wind, `wind_rise/`)

**Type**: moving instrument (has `controller_root_offset`). Example instrument types: Chinese dizi / flute / clarinet / saxophone / recorder / custom.

**Controller layout**:

- Hierarchy: `controller_root` (parented to the performer root) → `controller_root_offset` (the instrument binds here);
- 7 main controllers per hand: `H_L/HP_L/T_L/I_L/M_L/R_L/P_L` (right symmetric), **fingers parented to controller_root_offset**, ext (`2×finger`, LOCAL_SPACE) + poles;
- Feet: `F_L`/`F_R` + `FP_L`/`FP_R` (parented to the performer root);
- Head: `Head_Control` (parented to controller_root); breathing: `Breath_Control` (parented to the performer root, a stub);
- No string/key position markers → no Recorders collection needed.

**State model** (stored on the skeleton, key `wind_rise_state_data`) — **organized by MIDI note number**:

- `config`: instrument_type / description / min_note / max_note / force_shape_keys (lips) / instrument_shape_keys / instrument_mesh_name;
- `note_info`: `[{note, name (e.g. C4), controllers: {H_L: {location, rotation}, ...}, character_shape_keys, instrument_shape_keys}]`;
- Each note saves 14 hand controllers + lip shape keys + instrument shape keys; on load, shape keys are first zeroed then set to the recorded values (this behavior must be kept).

**Import/export** (`io.py`): `.wind` file (config + note_info, isomorphic with the skeleton JSON); the `.wind_rise` manifest is the animation input (not a performer-info file; it has its own path property).

**Animation** (`animation.py`): left/right hands / character SK / instrument SK / activity curve (written to `controller_root`'s `activity_curve` custom property + an `ActivityCurve` Empty placeholder); clearing animation uses `clear_all_keyframe_preserve_drivers` (keeps ext drivers).

**Specific tools**: axis-rotation tool, axis-move tool (in Edit Mode, define a rotation axis from two objects' positions and rotate selected vertices in real time).

**Panel**: initialization (Setup Objects), object selection (character mesh + instrument), character/instrument Shape Key editors (collapsible), instrument description, tools area, state management (current-note Save/Load), data file `.wind` (instrument type / note range / import-export), generate animation.

### 7.7 StringFlow (violin, `string_flow/`)

**Type**: fixed instrument (4 strings), left-hand fingers numbered (`1_L`–`N_L`, max 10, default 4).

**Controller layout**:

- Left-hand fingers: `1_L`–`N_L`; right-hand fingers: `1_R`–`N_R` (**right fingers/thumb parented to Bow_Controller** — the "hand on bow" rig, unique to StringFlow);
- Palms/pivots/thumbs: `H_L`/`HP_L`/`T_L`/`H_R`/`HP_R`/`T_R`;
- Other controllers: `String_Touch_Point`, `Bow_Controller`;
- Feet IK / poles (creation only, **not part of any data transfer or computation**, at the same level as `controller_root` — **not parented to it**, but to the performer root / kept as world objects): `F_L`/`F_R` + `FP_L`/`FP_R` (poles are empty rings);
- ext / poles: `ext_{finger}`, `{finger}_pole` (empty rings);
- **ext constraints** (drivers, cleared-then-rebuilt idempotently): left hand `ext = 2×finger` (H_L local space — finger and palm are both H_L children, so the palm is the origin); right hand `ext = 2×finger − palm` (Bow_Controller local space — finger and palm H_R are both bow children, keeping ext on the "palm → finger" extension line; the code comments note this replaced the earlier two-Copy-Location-world-constraint scheme);
- Physical position markers (17, parented to controller_root): `position_s{i}_f0/f12`, `mid_s{i}` / `f9_s{i}` (midpoint drivers), `middle_fret_board_position` (**the third point of the three-point plane**, shared by the Rust side and the string tool).

**State model** (stored on the skeleton, key `string_flow_state_data`):

- Left hand: `string(0/3) × fret(1/9/12) × position(Normal/Inner/Outer)`; each state saves H_L (location+rotation), HP_L, T_L, and all fingers;
- Right hand: `string(0–3) × position(near/far/pizzicato)`; saves H_R (location+rotation), HP_R, T_R, all fingers, String_Touch_Point, Bow_Controller (**location only — its rotation is decided in real time by the aim constraint and is not read by Rust**);
- Coordinate semantics: save the controllers' **local coordinates relative to controller_root** (= the original violin frame); **do not convert to world coordinates when saving**.

**Import/export** (`io.py`): `.violinist` file (**byte-level compatible** with the Rust Animator's consumed format):

- Top-level keys: `config` (one_hand_finger_number / string_number / optional is_unreal) + 6 state-recorder sections + `other_recorders`;
- Each recorder entry: `{location, rotation_mode, rotation_quaternion}` (Rust reads only location and rotation_quaternion — **the quaternion format must be kept**); `bow_position_*` writes location only;
- JSON keys are all short names; in `other_recorders`, physical markers are read from objects (None if missing), bow/stp from the skeleton.

**Animation** (`animation.py`): left hand / right hand / strings (shape keys `s{i}fret{k}`) / generate all. Animation JSON controller names are short names → mapped via `resolve(short, suffix)`; string-animation shape-key names need no suffix (they live inside the string data).

**Specific tools**: create violin string (select two endpoint objects → cylinder → 80-segment subdivision → three-point-plane shape keys `s{n}fret{1..20}`), generate ShapeKeys.

**Panel**: initialization (finger count / string count + Check/Setup), tools area, left/right-hand state selection, Hand State Transfer, Recorder Info I/O (export/import/export to Unreal), generate animation.

---

## 8. Data File Formats Summary

### 8.1 Per-instrument file formats

| Instrument | Performer/state file | Animation input file | Notes |
| ---------- | -------------------- | -------------------- | ----- |
| fret_dance | JSON (no extension, user-specified) | animation JSON pointed to by the panel FILE_PATH | content structure matches the Unreal side; filename carries no `_unreal` |
| key_ripple | `.avatar` | animation JSON | still consumed by the Rust/Unreal side |
| zheng_drift | `.zheng_master` | `.zhengdrift` (performance/target/string sub-files) | short keys compatible with Rust |
| beat_bloom | `.drummer` | animation JSON | flat keys `component_state_ctrl` |
| harp_glide | `.harpist` | `.harpglide` report | flat external keys; nested internal JSON |
| wind_rise | `.wind` | `.wind_rise` manifest | config + note_info |
| string_flow | `.violinist` | `.string_flow` (paths to three animation files: left/right hand, strings) | byte-level compatible with the Rust Animator |

**Common conventions**:

- JSON keys are always **short names** (consumed by the Rust side); only in-Blender object lookups use suffixed names;
- States are always **exported from bone custom properties**; physical position markers are read **from objects**;
- Paths uniformly use `ui_utils.SCENE_INFO_PATH` (the "Performer Info Path" in the performer-ops panel); ImportHelper/ExportHelper are no longer used (except "Export to Unreal").

### 8.2 Coordinate conversion for Export to Unreal

`common/io_utils.py` provides the unified conversion:

- Position: `to_unreal_position([x,y,z]) → [x, -y, z]` (Y-axis negation);
- Rotation: `to_unreal_rotation([w,x,y,z]) → [w, -x, y, -z]` (reflection conjugate, `R_u = M·R_b·M`, M=diag(1,-1,1));
- With `for_unreal=True`, each instrument applies the conversion and sets `config.is_unreal = true` (some Rust sides rely on it, e.g. StringFlow's fretboard-plane normal direction);
- Plain export is the identity transform and does not write `is_unreal` (defaults to false).

> Note: some tool docstrings mention "scale ×100, Y-axis negation, rotation conjugate", which differs from the current `io_utils.to_unreal_position/rotation` code — **the code wins** (the current implementation only does Y-axis negation and the rotation reflection-conjugate; there is no ×100 scale). If ×100 is ever needed it must be added explicitly on the export path.

---

## 9. Development, Deployment and Verification

### 9.1 Installation & deployment

`src/` is the entire source code. Two ways to install:

1. Rename `src\` to `music_doll_blender` and put it in Blender's add-ons directory (e.g. `Blender\5.0\scripts\addons\`);
2. Zip the `src\` directory and drag it into "Preferences → Add-ons" (the zip's top-level directory must be `music_doll_blender/`, otherwise rename it to the add-on folder name).

After modifying the source, reinstall; if the add-on is already enabled, **disable and re-enable it in Blender (or restart Blender)** for the changes to take effect.

### 9.2 Verification workflow

- **Static checks**: `python -m py_compile` (syntax) + Pylance (references/types); the `StringProperty` error in `ui_utils.py` is a known false positive — ignore it;
- **Blender runtime testing (performed manually by the user)**: create a performer (pick the instrument in the dropdown) → Setup → Check Status → state Set/Load → import/export → specific tools → generate animation; duplicate/rename performers to verify isolation;
- **Testing note**: use a copy of the `.blend` file to avoid damaging working files.

> Historical-data repair tools (e.g. suffix corruption from the Blender 5.0 CJK encoding bug, bone state keys wrongly carrying suffixes) are private local scripts and are not shipped with this repository; this document does not cover them.

---

## 10. Key Conventions and Caveats

### 10.1 Global hard constraints (all modules must obey)

1. **SaveState / LoadState must be triggered manually by the user**: no module may call them automatically in code;
2. **SetupAllObjects only creates/configures controllers and must not clear or reset saved state data**: initialization only fills missing keys (Contains+Add / FindOrAdd); "clear first, then fill with zeros" is forbidden; SaveState likewise must not wipe the whole state. This matches the migration guide's setup_all_objects contract: "idempotent; do not reset saved state/position-marker data";
3. **Export formats are frozen**: each instrument's export file (fret_dance JSON / `.avatar` / `.violinist` / `.zheng_master` / `.drummer` / `.harpist` / `.wind`) is the Rust/Unreal consumption interface; migrations must keep the structure compatible — only internal storage locations may change, never the exported content;
4. **JSON keys use short names**: keys consumed by Rust are always short (`s0head`, `H_L_Normal_far`); only in-scene object lookups use suffixed names;
5. **States live on the skeleton, markers live on objects**: no recorder objects for states; physical position markers stay as scene objects;
6. **Clearing keyframes must preserve drivers**: use `animation_utils.clear_all_keyframe_preserve_drivers` or a custom per-object approach; per-object `animation_data_clear()` destroys ext / Middle_Hand drivers;
7. **Coordinate-space traps**: after parenting, `.location` becomes local — midpoint-type drivers use WORLD_SPACE, same-parent relative quantities (`ext = 2×finger`) use LOCAL_SPACE;
8. **Blender 5.0 specifics**: `bpy.types.Collection` has no `.parent` (reverse-lookup instead); operators do not support PointerProperty (reuse scene-level pointer properties); EnumProperty items callbacks need an integer default index; registration guards must use the RNA name (`MUSIC_DOLL_OT_create_performer`, with an underscore);
9. **CJK encoding bug**: Blender 5.0 scene enums may carry corrupted bytes and raise UnicodeDecodeError; reads catch it and self-heal; enum items skip non-ASCII names;
10. **Deprecated tools are not migrated**: MMD-related (mmd2blender), Daz Rig, wave generation, shader scripts, etc. that never appeared in the add-on UI are not migrated.

### 10.2 Migration-engineering conventions (when adding an instrument)

See chapter 11 and the *Instrument Module Migration Engineering Guide* in full. Quick reference:

| Pitfall | Fix |
| ------- | --- |
| Object names without suffix → multi-performer pollution | `resolve()` everywhere; check naming tables/animation/io/tools one by one |
| setup directly does `["addons"]` → crash when character not initialized | `_get_addons_collection()` find-only + precondition check |
| Driver reads local coords after parenting | midpoint types WORLD_SPACE; same-parent relative quantities LOCAL_SPACE |
| States as recorder objects → scene clutter | states always on the skeleton; only physical markers stay as objects |
| Clearing keyframes destroys drivers | `clear_all_keyframe_preserve_drivers` or custom per-object clearing |
| Import/export via file browser | switch to `SCENE_INFO_PATH`; the panel keeps only the animation file path |
| Tool parameters stuffed into PropertyGroup | use scene-level properties (registered inside the tool module) |
| ext drivers / root lost after duplicate/rename | finish with `add_ext_drivers` + `_organize_performer_root` |
| JSON keys carry suffixes → Rust parsing fails | short keys; suffixes only for object lookups |

### 10.3 Performer switch linkage (core of the stateless design)

```
User switches the performer dropdown
  → read the Collection's md_instrument / md_skeleton / md_instrument_obj
  → fill the current instrument's scene fields (target skeleton / target instrument / performer info path)
  → re-fill the panel from load_settings(skeleton)
  → if the instrument type differs from the current panel, switch/enable the matching instrument sub-panel
```

---

## 11. Guide for Adding a New Instrument

> Full methodology: see the *Instrument Module Migration Engineering Guide*. Condensed flow below.

### 11.1 The instrument profile (pre-migration inventory, Q1–Q5)

Answer 5 groups of questions before migrating (answers must come from the source code):

| Question | Content |
| -------- | ------- |
| Q1 Controls | Which controls? Hierarchy? Specific constraints (drivers/constraints/parenting)? Fixed or moving instrument? |
| Q2 States | Which states? Dimensions? Which controllers per state? Invalid combinations? Where do states live (always the skeleton)? |
| Q3 Import/Export | What is recorded? Control info vs settings info? Is control info state-related? Key-name compatibility (short names)? |
| Q4 Specific tools | Which instrument-specific tools? Scene-level parameters? Do created objects carry suffixes? |
| Q5 Extra concerns | Animation input format? Special orientation/target? Multi-file animation config? Not-migrated/reused? Coordinate-space traps? Idempotency & re-runs? |

### 11.2 Unified conventions (mandatory for every instrument)

1. **Suffix-based naming**: objects/collections via `performer_utils.resolve(short, suffix)`; addons via `_get_addons_collection()` (find-only when suffixed);
2. **Object hierarchy**: `addons_<suffix>/Controllers_<suffix>/controller_root` (fixed) or `controller_root_offset` (moving); driver-driven objects are not parented to the root; no recorder objects for states;
3. **setup_all_objects contract**: precondition-check addons exists → `_organize_body` → `_organize_instrument` → `add_controllers` → `add_ext_drivers` → `add_recorders` → `_organize_performer_root`; idempotent, does not reset saved data;
4. **Shared paths/objects**: import/export via `ui_utils.SCENE_INFO_PATH`; skeleton/instrument via `get_target_skeleton/get_target_instrument`; keep the animation path as the instrument panel's single FILE_PATH;
5. **Registration & naming**: snake_case instrument id registered in `INSTRUMENT_PREFIX` (prefix) + `ui_utils.register_instrument`; operators `music_doll.<instrument>_*`; panel `bl_parent_id = "MUSICDOLL_PT_main_panel"`;
6. **Tools**: `TOOLS = COMMON_TOOLS + INSTRUMENT_TOOLS`; drawn via `ui_utils.draw_tools`;
7. **Animation**: reuse `common.animation_utils` fcurve tools; preserve drivers when clearing keyframes.

### 11.3 Standard migration steps (Step 0–12)

```
Step 0  Inventory: read all sources, fill the instrument profile Q1–Q5, mark not-migrated/reused/kept-special logic
Step 1  Skeleton + enums.py (state enums, ObjectType mapping)
Step 2  config.py: naming tables + obj_name/obj via resolve
Step 3  add_controllers (controller_root hierarchy + special orientation + constraints/drivers) + add_ext_drivers
Step 4  add_recorders (physical position markers only) + check_*
Step 5  setup_all_objects precondition + _organize_body/instrument/performer_root
Step 6  state.py: states on the skeleton (reuse common.state_io) + state-specific logic
Step 7  io.py: import/export (short keys, SCENE_INFO_PATH)
Step 8  animation.py: each animation + clear keyframes keeping drivers
Step 9  tools/: specific tools (ToolDef + scene params + register/unregister)
Step 10 ui.py: PropertyGroup + panel + all operators + rename/duplicate + register_instrument
Step 11 Wiring: append register/unregister in src/__init__.py (register: common → instruments; unregister: reverse)
Step 12 Verify & deploy: py_compile + package & install + user Blender testing
```

---

## 12. Documentation Index

> Note: the only documents shipped with this repository (git) are **this document (EN/CN)** and the root `README.md` / `README.en.md`; the construction docs below are internal records of the repository and are not uploaded to git.

The internal construction docs in `docs/`:

| Doc | Content |
| --- | ------- |
| `music_doll_blender_施工文档.md` | Project planning draft (v1.0, 2026-08-07): background, Unreal architecture reference, unified data model, common-module API design, migration plans, UI design, phased plan, test plan, risk list (Chinese) |
| `乐器模块迁移工程指南.md` | Engineering methodology: instrument profile Q1–Q5, unified conventions, standard module skeleton, 12-step migration flow, three completed instrument examples, pitfall quick reference (Chinese) |
| `面板默认执行顺序改造施工记录.md` | Record of the panel rework into a single top-level panel with three blocks, incl. the three Blender 5.0 pitfalls (Chinese) |
| `fret_dance / key_ripple` (no separate docs) | migration plan is in the construction doc §7 |
| `zheng_drift移植施工报告.md` | guZheng module build report incl. implementation differences (Chinese) |
| `beat_bloom移植施工计划.md` | percussion module migration plan (Chinese) |
| `harp_glide移植施工计划.md` | harp module migration plan (Chinese) |
| `wind_rise移植施工计划.md` | wind module migration plan (Chinese) |
| `string_flow_blender移植施工计划.md` | violin module migration plan incl. Rust-side consumption confirmation, hierarchy/constraint design (Chinese) |
| `music_doll_blender_项目说明文档.md` | This document (Chinese) |
| `music_doll_blender_项目说明文档.en.md` | This document (English) |

---

## 13. Appendix: Unreal ↔ Blender Concept Mapping

| Unreal MusicDoll | MusicDoll Blender |
| ---------------- | ----------------- |
| `AInstrumentBase` (Actor) | a performer Collection under the `Performers` root |
| Subclasses (`AFretDanceUnreal` etc.) | the `md_instrument` attribute on the Collection |
| `SkeletalMeshActor` | `md_skeleton` (skeleton object) |
| Instrument mesh | `md_instrument_obj` (Instruments collection) |
| `IOFilePath` | `md_info_path` |
| `AnimationFilePath` | `md_animation_path` |
| Actor's own UPROPERTY (instrument-specific) | bone custom properties (`<instrument>_*`) |
| `TActorIterator<AInstrumentBase>` | `common.performer_utils.list_performers()` |
| SComboBox performer selector | the `common.ui_utils` performer dropdown |
| `MusicDollCommon` | `common/` |

---

*End of document. If anything disagrees with the code, the `src/` code is authoritative.*



