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
- **Import / export data**: export the prepared pose data to files — piano `.avatar`, guzheng `.zheng_master`, drums `.drummer`, harp `.harpist`, wind `.wind`, violin `.violinist`, accordion `.accordion`, guitar `.json` — for our other toolchains (Rust / Unreal), and import data prepared elsewhere;
- **Generate animation**: read motion data files and keyframe the controllers and instrument parts directly in Blender;
- **Provide tools**: every instrument ships with utility tools — "Fix Finger Bones" is shared by all instruments, "Create Guitar Strings" is guitar-only, "Make Piano Key Shape Keys" is piano-only. Tools live in a collapsible dropdown, hidden by default, so the UI stays clean.

## Supported instruments

The instruments were merged in phases; 8 are currently included:

| Instrument | Prefix | Type | Data suffix | Notes |
| ---------- | ------ | ---- | ---- | ----- |
| FretDance (Guitar) | FD | Carried | `.json` | Three setups: fingerstyle guitar, electric guitar, bass. Left-hand fretting, right-hand plucking, vibrato bar on electric |
| KeyRipple (Piano) | KR | Stationary | `.avatar` | Two-hand playing, black & white keys, high and low positions; key-press shape keys baked separately |
| ZhengDrift (GuZheng) | ZD | Stationary | `.zheng_master` | 21 strings; left/right hand states, feet, bilinear mapping, dedicated orientation controllers |
| BeatBloom (Percussion) | BB | Stationary | `.drummer` | Drum-kit driven by configuration; left/right hands and feet plus head orientation |
| HarpGlide (Harp) | HG | Stationary | `.harpist` | String count configurable (47 by default), double-row strings supported; pedals, harp tilt, hand and head poses |
| WindRise (Wind) | WR | Carried | `.wind` | Chinese dizi, flute, clarinet, saxophone, recorder — or type your own instrument name. States keyed by midi note |
| StringFlow (Violin) | SF | Stationary | `.violinist` | Violin / viola / cello; 4 strings, numbered fingers, "hand on bow" rig, three-point-plane string tool |
| BellowsPulse (Accordion) | BP | Stationary | `.accordion` | Right-hand keyboard or bayan buttons plus left-hand Stradella; two key-zone pivots, bellows pivot, bellows open/closed pose sampling, step-by-step settings panel |

"Carried" means the performer takes the instrument along (guitar, wind); "stationary" means the instrument stays put and the performer goes to it (piano, guzheng, drums and the like).

All instruments share the same common framework (performer management, state storage, animation writing, import/export, tool system).

## Usage

1. **Install**: rename `src\` to `music_doll_blender` and drop it into Blender's add-ons directory (e.g. `Blender\5.0\scripts\addons\`); or zip `src\` and drag it into "Preferences → Add-ons";
2. Find and enable **MusicDoll Blender** in "Preferences → Add-ons";
3. Open the **MusicDoll** panel in the right sidebar of the 3D viewport;
4. In the "Performer Selector", create a new performer (name + instrument type + skeleton + instrument object);
5. Click **Setup Objects** in the instrument's sub-panel, then you can save/load states, import/export data, and generate animation.

The top of the panel is the shared "Performer Selector / Performer Ops" area used by all instruments; below it, only the sub-panel matching the current performer's instrument is shown, plus a collapsible "Tools" dropdown.

After changing `src/`, run `build.bat` in the repository root to regenerate `music_doll_blender.zip` (top-level folder `music_doll_blender`, no `__pycache__`).

## Skills for agents

The add-on panel is for people: click a button, pose a hand, save a state. Turning a raw model into a performer that can play in Unreal leaves a lot of work outside that panel — working out which bone is which, checking whether the axes point the right way, measuring alignment error, comparing meshes vertex by vertex to prove nothing broke. That work needs on-the-spot judgement plus a pile of numeric checks, so we packaged it into skills: the agent runs the scripts headless inside Blender (`blender -b`) and you read the report.

| Skill | Covers | What it does today |
| ----- | ------ | ------ |
| `music-doll-rig` | Skeleton rework | Sets scene units to 0.01 m, scales skeleton and meshes 100× and applies the scale; then identifies bone chains, builds MCH master bones, aligns the Z axis of arms / fingers / legs to the shared convention, adds the 3% arch, IK and copy-rotation; finally a waist→chest→neck IK with a head-orientation control chain. Three assertion groups verify it, and progress is written back into a text block so whoever takes over can continue |
| `music-doll-instrument-controls` | Instrument controls | MusicDoll init → instrument setup all objects → make `controller_root` follow the neck bone, chest bone or a given anchor → align real controls to the test controls → repoint the performer's constraints → add the upper-body chain for instruments that ship a head control → verify and clean up. Adapters are bundled for piano, guzheng, drums, guitar, accordion and violin |
| `music-doll-export-to-fbx` | Export for Unreal | Passes a "units 0.01 m + armature at origin" gate, sorts every mesh into skeletal mesh / shape-key part / plain part, resolves its real parent (world origin or a specific bone), bakes it into the matching export space, writes one fbx per part, and records where each fbx belongs in `manifest.json`. Finally it imports the batch back into Blender and verifies vertex by vertex |

The full chain looks like this, and every step has its own acceptance checks — if one fails you shouldn't move on:

```
raw model (MMD / Daz / game rip)
  │  music-doll-rig
  ▼
reworked skeleton + test controls (progress block DONE)
  │  music-doll-instrument-controls
  ▼
playable performer .blend (instrument controls + upper-body / head chain)
  │  music-doll-export-to-fbx
  ▼
a set of fbx + manifest.json  ──▶  Unreal (assemble the performer from the manifest)
```

The last step, assembling the performer inside Unreal, is still being built.

The skill packages live under `skills/` in this repository — one folder per skill, holding `SKILL.md` (criteria, measured numbers, pitfalls, full commands) plus a `scripts/` directory. To use them, link the folder into your agent's skills directory (`~/.dsh/skills/` on this machine); a symlink is the easiest, since the agent then picks up repository changes automatically.

Scripts run headless, for example to just inspect a skeleton:

```powershell
blender -b --factory-startup -P skills/music-doll-rig/scripts/rig_analyze.py -- <model.blend> --armature <armature name>
```

Each `SKILL.md` documents the full parameter list and acceptance criteria.

The set is still evolving. Where it stands now:

- `music-doll-rig` runs end to end on four MMD models from different sources, with all 14 chain assertion groups passing;
- `music-doll-instrument-controls` has been installed and independently verified on six instrument versions of the same performer (Mia);
- `music-doll-export-to-fbx` exported 5 fbx from the drum file and passed all 92 verification items on re-import;
- Not yet tested: control-rig skeletons (`Skirk`), Rigify skeletons, and control installation for cello and harp.

## Repository layout

```
music_doll_blender/
├── src/                # All source code (zip this directory to install in Blender)
│   ├── __init__.py     # Add-on entry point: registers common + instrument modules
│   ├── common/         # Common framework: rules and tools shared by all instruments
│   │   └── tools/      # Shared tools (fix finger bones, bone/controller mapping, axis transform)
│   ├── fret_dance/     # Guitar module (Phase 1)
│   ├── key_ripple/     # Piano module (Phase 2)
│   ├── zheng_drift/    # GuZheng module (Phase 3)
│   ├── beat_bloom/     # Percussion module (Phase 4)
│   ├── harp_glide/     # Harp module
│   ├── wind_rise/      # Wind module
│   ├── string_flow/    # Violin module
│   └── bellows_pulse/  # Accordion module (Rust side: bellows_pulse_rust)
├── skills/             # Agent skills (see the section above)
│   ├── music-doll-rig/
│   ├── music-doll-instrument-controls/
│   └── music-doll-export-to-fbx/
├── docs/plans/         # Working plans (kept locally, not tracked)
├── build.bat           # Packaging: src/ → music_doll_blender.zip
└── music_doll_blender.zip  # Distribution package (built locally)
```

- **common/** is the foundation for all instruments: performer recognition, collection/object management, state read/write, animation writing and import/export are all implemented here once and reused by every instrument;
- **fret_dance/ … bellows_pulse/** are instrument modules that only hold instrument-specific logic: controller layouts, state semantics, export formats, and dedicated tools.

## Documentation

- The three `SKILL.md` files under `skills/` are the most complete technical documentation right now: criteria, measured numbers, failure cases and pitfalls;
- The long-form project documentation (architecture, module breakdown, data model, development workflow) and working plans live in `temp/` and `docs/plans/` on this machine and are not tracked.

## Who is it for

It mainly serves our own music-performance-animation pipeline, but anyone making instrument animation is welcome to reference or use it. If you just want to put a performance animation on a character quickly, building controllers, posing and generating animation with it is quite convenient. If you also plan to take performers into Unreal, the criteria and pitfalls in the agent skills are worth borrowing.
