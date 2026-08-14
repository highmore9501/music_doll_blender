# MusicDoll Blender

> [中文](README.md) | **English**

A Blender animation add-on that helps you attach musical-instrument performance animations to characters.

## How it came to be

We used to maintain a separate Blender add-on for each instrument: a guitar add-on, a piano add-on, a violin add-on, and so on.

That worked at first, but problems kept piling up:

- Every add-on re-implemented the same pipeline — "create controllers, save states, generate animations, import/export" — with heavy code duplication;
- When you wanted two performers of *different* instruments in one Blender file, the two add-ons didn't know about each other and often conflicted;
- Adding a shared feature across all instruments (e.g. fixing finger bones) meant editing every add-on separately.

So we changed course: **put every instrument into one add-on** and let it manage everything. That add-on is MusicDoll Blender.

It borrows the architecture of our identically-named Unreal plugin (MusicDoll): one framework owns the common parts, each instrument plugs in as one module, and everyone shares the same rules.

## What it does

In short, MusicDoll Blender lets you:

- **Manage performers**: keep several performers in one Blender file — guitarists, pianists, violinists — and switch between them from a dropdown. The add-on remembers each person's skeleton, instrument and file paths;
- **Build controllers**: with a character and instrument selected, one click creates the whole set of control objects with correct hierarchy and parenting. Repeating the click is harmless;
- **Save / load states**: store each pose (e.g. left hand fretting a position, right hand plucking a string) on the character's skeleton and load it back anytime for fine-tuning;
- **Import / export data**: export the prepared pose data to files (`.avatar`, `.violinist`, `.zheng_master`, `.drummer`, `.harpist`, `.wind`, …) for our other toolchains (Rust / Unreal), and import data prepared elsewhere;
- **Generate animation**: read motion data files and keyframe the controllers and instrument parts directly in Blender;
- **Provide tools**: every instrument ships with utility tools — "Fix Finger Bones" is shared by all instruments, "Create Guitar Strings" is guitar-only, "Make Piano Key Shape Keys" is piano-only. Tools live in a collapsible dropdown, hidden by default, so the UI stays clean.

## Supported instruments

The instruments were merged in phases; 7 are currently included:

| Instrument | Prefix | Type | Notes |
| ---------- | ------ | ---- | ----- |
| FretDance (Guitar) | FD | Moving | Fingerstyle / electric guitar / bass; left-hand fretting, right-hand plucking, vibrato bar |
| KeyRipple (Piano) | KR | Fixed | Two-hand playing; black & white keys, high/low positions |
| ZhengDrift (GuZheng) | ZD | Fixed | 21 strings; left/right hand states, feet, bilinear mapping, special orientation controllers |
| BeatBloom (Percussion) | BB | Fixed | Drumkit-driven; left/right hands & feet plus head orientation |
| HarpGlide (Harp) | HG | Fixed | 47 strings (configurable); pedals, harp tilt, hand & head poses |
| WindRise (Wind) | WR | Moving | Chinese dizi / flute / clarinet / saxophone etc.; states keyed by MIDI note |
| StringFlow (Violin) | SF | Fixed | 4 strings; numbered fingers, "hand on bow" rig, three-point-plane string tool |

All instruments share the same common framework (performer management, state storage, animation writing, import/export, tool system).

## Usage

1. **Install**: rename `src\` to `music_doll_blender` and drop it into Blender's add-ons directory (e.g. `Blender\5.0\scripts\addons\`); or zip `src\` and drag it into "Preferences → Add-ons";
2. Find and enable **MusicDoll Blender** in "Preferences → Add-ons";
3. Open the **MusicDoll** panel in the right sidebar of the 3D viewport;
4. In the "Performer Selector", create a new performer (name + instrument type + skeleton + instrument object);
5. Click **Setup Objects** in the instrument's sub-panel, then you can save/load states, import/export data, and generate animation.

The top of the panel is the shared "Performer Selector / Performer Ops" area used by all instruments; below it, only the sub-panel matching the current performer's instrument is shown, plus a collapsible "Tools" dropdown.

## Repository layout

```
music_doll_blender/
├── src/             # All source code (zip this directory to install in Blender)
│   ├── __init__.py  # Add-on entry point: registers common + instrument modules
│   ├── common/      # Common framework: rules and tools shared by all instruments
│   │   └── tools/   # Shared tools (Fix Finger Bones, Bone/Controller Mapping)
│   ├── fret_dance/  # Guitar module (Phase 1)
│   ├── key_ripple/  # Piano module (Phase 2)
│   ├── zheng_drift/ # GuZheng module (Phase 3)
│   ├── beat_bloom/  # Percussion module (Phase 4)
│   ├── harp_glide/  # Harp module
│   ├── wind_rise/   # Wind module
│   └── string_flow/ # Violin module
├── docs/            # Project documentation (EN/CN)
└── music_doll_blender.zip  # Distribution package (built locally)
```

- **common/** is the foundation for all instruments: performer recognition, collection/object management, state read/write, animation writing and import/export are all implemented here once and reused by every instrument;
- **fret_dance/ … string_flow/** are instrument modules that only hold instrument-specific logic: controller layouts, state semantics, export formats, and dedicated tools.

## Documentation

- [MusicDoll Blender Project Documentation (English)](docs/music_doll_blender_项目说明文档.en.md) — full explanation of architecture, module breakdown, data model and development workflow;
- [MusicDoll Blender 项目说明文档（中文）](docs/music_doll_blender_项目说明文档.md);
- The construction docs under `docs/` record design decisions, migration plans and build reports (see chapter 12 index in the project documentation).

## Who is it for

It mainly serves our own music-performance-animation pipeline, but anyone making instrument animation is welcome to reference or use it. If you just want to put a performance animation on a character quickly, building controllers, posing and generating animation with it is quite convenient.
