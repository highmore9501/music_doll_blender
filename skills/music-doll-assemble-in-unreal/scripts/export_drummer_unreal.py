"""Blender 侧：从演奏者 .blend 导出 Unreal 坐标的演奏者数据文件（鼓手是 .drummer）。

Unreal 版 = Blender 版再做一次坐标系变换（位置 Y 取反、旋转取反射共轭）+ `is_unreal: true`，
所以它能直接从 .blend 里现导，不需要先有 Blender 版文件。

跑法（无头）：
    blender -b -P export_drummer_unreal.py
或在 Blender 里 Text Editor 里直接跑。
"""

import json
import os

import bpy

# ============================== CONFIG ==============================
BLEND = r"E:\BaiduNetdiskDownload\3D Asset\演奏者\drum\米娅-星彩_架子鼓.blend"
DRUMKIT = r"H:\beat_bloom_rust\asset\drum_kit\米娅_blender.drumkit"
UNREAL_OUT = r"H:\beat_bloom_rust\asset\avatar\米娅_unreal.drummer"
BLENDER_OUT = r"H:\beat_bloom_rust\asset\avatar\米娅_blender.drummer"   # 顺带出一份对照，可留空
STATE_PROP = "beat_bloom_state_data"
# ====================================================================

if bpy.data.filepath != BLEND:
    bpy.ops.wm.open_mainfile(filepath=BLEND)

from music_doll_blender.beat_bloom.io import export_drummer  # noqa: E402

with open(DRUMKIT, "rb") as handle:
    drumkit_data = json.loads(handle.read().decode("utf-8"))

candidates = [item for item in bpy.data.objects
              if item.type == "ARMATURE" and item.get(STATE_PROP)]
if not candidates:
    raise RuntimeError("这个 .blend 里没有带 %s 的骨架：先在该模型上装好 MusicDoll 鼓组控件并记录状态"
                       % STATE_PROP)
skeleton = candidates[0]

export_drummer(UNREAL_OUT, skeleton, drumkit_data, for_unreal=True)
if BLENDER_OUT:
    export_drummer(BLENDER_OUT, skeleton, drumkit_data, for_unreal=False)


def summarize(path):
    with open(path, "rb") as handle:
        data = json.loads(handle.read().decode("utf-8"))
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "is_unreal": data.get("is_unreal"),
        "recorders": len(data.get("RECORDER_INFO", {})),
        "helpers": len(data.get("MAPPING_HELPERS", {})),
        "other_controllers": len(data.get("OTHER_CONTROLLERS", {})),
    }


print("HEADLESS " + json.dumps({
    "skeleton": skeleton.name,
    "unreal": summarize(UNREAL_OUT),
    "blender": summarize(BLENDER_OUT) if BLENDER_OUT else None,
}, ensure_ascii=False))
