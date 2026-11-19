# 原始模型形态普查（阶段 1 产物）

普查对象：`E:\BaiduNetdiskDownload\Blender原神角色模型 …\T0001-56款原神角色3D模型` 下已解压的
**39 个角色 `.blend`**（不含武器/道具/动作库；zip 里未解压的同型号未计入）。
工具：`rig_survey.py` + `rig_analyze.py`（只读）。中间数据是 `temp/rig_work/` 下的 `survey_raw.json` / `analyze_raw.json`
（`temp/` 可能被清理，需要时用同一批文件重跑一遍即可复现）。

## 规模

| 项目 | 数量 |
|---|---|
| 文件 | 39 |
| 骨架条目 | 71 |
| 一个文件里有 3 套骨架 | 15 个文件 |
| 一个文件里有 2 套骨架 | 3 个文件 |
| 一个文件里 1 套骨架 | 20 个文件 |
| 手臂三段之间夹着扭转/辅助骨（必须造 MCH） | 46 |
| 已经做过 MCH | 7 |
| 带 `_dummy_` / `_shadow_` 影子链 | 28 |
| 带扭转骨（`捩` / `twist`） | 33 |
| 带指尖叶骨 | 37 |
| 已经有 IK 约束 | 36 |

命名体系：

- MMD 日文：32
- 英文：18
- Rigify：16
- 控制器骨架：3
- 认不出：2

## 认链结果

| 检查 | 通过 |
|---|---|
| 手臂三段认全 | 69 / 71 |
| 腿三段认全 | 68 / 71 |
| 五指认全 | 69 / 71 |

没认全的：

- `卡齐娜.blend` / `卡齐娜_arm`：no usable hand: candidates 下半身, 腰 are all midline/unpaired (best named hand has 0 finger chain(s))
- `七七.blend` / `七七_arm.001`：leg.L: candidate thigh 下半身 looks like a body root; thigh missing?；leg.L: candidate shin 腰キャンセル.L looks like a body root; shin missing?；leg.R: candidate thigh 下半身 looks like a body root; thigh missing?；leg.R: candidate shin 腰キャンセル.R looks like a body root; shin missing?
- `Skirk.blend` / `rig_C`：R: upper arm unresolved: picked c_traj (its name is not upper_arm-like)；L: upper arm unresolved: picked c_traj (its name is not upper_arm-like)
- `Skirk.blend` / `Tongue_rig.001`：no hand candidate and no bone named like a hand
- `Skirk_-_Norinde_3.6.blend` / `SkirkRig`：R: upper arm unresolved: picked c_traj (its name is not upper_arm-like)；L: upper arm unresolved: picked c_traj (its name is not upper_arm-like)
- `Skirk_-_Norinde_4.4.blend` / `SkirkRig`：R: upper arm unresolved: picked c_traj (its name is not upper_arm-like)；L: upper arm unresolved: picked c_traj (its name is not upper_arm-like)

## 逐文件

`arm/leg/手指` = 三段与五指是否认全；`夹骨` = 三段之间夹着扭转/辅助骨（要造 MCH）；
`绑定网格` = 这套骨架驱动的网格数（判断该改哪一套的硬依据）。

| 文件 | 骨架 | 骨数 | 命名 | 绑定网格 | arm | leg | 手指 | 夹骨 | 已 MCH | 影子链 |
|---|---|---|---|---|---|---|---|---|---|---|
| Skirk.blend | Tongue_rig.001 | 4 | 认不出 | 1 | ✗ | ✗ | ✗ | 否 | 否 | 无 |
| Skirk.blend | rig_C | 559 | 控制器骨架 | 23 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| Skirk_-_Norinde_3.6.blend | SkirkRig | 601 | 控制器骨架 | 16 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| Skirk_-_Norinde_4.4.blend | SkirkRig | 601 | 控制器骨架 | 16 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 【芙宁娜_荒】.blend | 【芙宁娜 荒】_arm | 431 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 【芙宁娜】.blend | 【芙宁娜】_arm | 507 | 英文 | 1 | ✓ | ✓ | ✓ | 否 | 是 | 有 |
| 七七.blend | 七七_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 是 | 无 |
| 七七.blend | 七七_arm | 258 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 七七.blend | 七七_arm.001 | 252 | MMD 日文 | 1 | ✓ | ✗ | ✓ | 否 | 否 | 有 |
| 丘丘人.blend | 丘丘人_Rig | 408 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 丘丘人.blend | 丘丘人_arm | 210 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 丘丘人.blend | 丘丘人_arm.001 | 210 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 云堇.blend | 云堇_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 云堇.blend | 云堇_arm | 597 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 云堇.blend | 云堇_arm.001 | 597 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 仆人.blend | 仆人_arm | 494 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 优菈.blend | 优菈_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 优菈.blend | 优菈_arm | 253 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 优菈.blend | 优菈_arm.001 | 253 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 凯亚.blend | 凯亚_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 凯亚.blend | 凯亚_arm | 365 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 凯亚.blend | 凯亚_arm.001 | 365 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 卡齐娜.blend | 卡齐娜_arm | 231 | 认不出 | 1 | ✗ | ✗ | ✗ | 否 | 否 | 有 |
| 基尼奇.blend | 基尼奇_arm | 348 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 多莉.blend | 多莉_arm | 226 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 夜兰(Apose骨骼版).blend | 夜兰_arm | 406 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 夜兰(骨骼控制器版).blend | 夜兰_arm | 406 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 夜兰(骨骼控制器版).blend | 夜兰_arm_Rig | 738 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 是 | 无 |
| 奇怪的丘丘人.blend | 奇怪的丘丘人_Rig | 408 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 奇怪的丘丘人.blend | 奇怪的丘丘人_arm | 230 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 奇怪的丘丘人.blend | 奇怪的丘丘人_arm.001 | 230 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 希诺宁.blend | 希诺宁_arm | 337 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 林尼.blend | 林尼_arm | 338 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 温迪.blend | 温迪_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 温迪.blend | 温迪_arm | 403 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 温迪.blend | 温迪_arm.001 | 403 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 玛薇卡.blend | 玛薇卡_arm | 277 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 琳妮特.blend | 琳妮特_arm | 577 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 琴.blend | 琴_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 琴.blend | 琴_arm | 213 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 琴.blend | 琴_arm.001 | 213 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 瑶瑶.blend | 瑶瑶_arm | 295 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 甘雨.blend | 甘雨_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 是 | 无 |
| 甘雨.blend | 甘雨_arm | 315 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 甘雨.blend | 甘雨_arm.001 | 315 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 神里绫华-花时来信.blend | 神里绫华_arm | 437 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 纳西妲.blend | 纳西妲_arm | 488 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 胡桃.blend | 胡桃_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 胡桃.blend | 胡桃_arm | 294 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 胡桃.blend | 胡桃_arm.001 | 294 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 芭芭拉.blend | 芭芭拉_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 芭芭拉.blend | 芭芭拉_arm | 330 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 芭芭拉.blend | 芭芭拉_arm.001 | 330 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 茜特拉莉.blend | 茜特拉莉_arm | 383 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 否 | 否 | 有 |
| 荒泷一斗.blend | 荒泷一斗_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 荒泷一斗.blend | 荒泷一斗_arm | 362 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 荒泷一斗.blend | 荒泷一斗_arm.001 | 362 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 荧.blend | 荧_arm | 334 | 英文 | 0 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 荧.blend | 荧_arm.001 | 334 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 莱欧斯利.blend | 莱欧斯利_arm | 341 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 菲谢尔-极夜真梦.blend | 菲谢尔-极夜真梦_arm | 340 | 英文 | 1 | ✓ | ✓ | ✓ | 否 | 是 | 无 |
| 辛焱.blend | 辛焱1.0_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 是 | 无 |
| 辛焱.blend | 辛焱1.0_arm | 260 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 辛焱.blend | 辛焱1.0_arm.001 | 260 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 达达利亚.blend | 达达利亚_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 是 | 无 |
| 达达利亚.blend | 达达利亚_arm | 229 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 达达利亚.blend | 达达利亚_arm.001 | 229 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 迪卢克-殷红终夜.blend | 迪卢克-殷红终夜_arm | 391 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 有 |
| 钟离.blend | 钟离_Rig | 409 | Rigify | 0 | ✓ | ✓ | ✓ | 否 | 否 | 无 |
| 钟离.blend | 钟离_arm | 301 | 英文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |
| 钟离.blend | 钟离_arm.001 | 301 | MMD 日文 | 1 | ✓ | ✓ | ✓ | 是 | 否 | 无 |

## 从 .pmx 进 Blender 的配方（实测可用）

只有 `.pmx` 的模型要先导入成 `.blend`。Blender **4.5** + 官方扩展 `bl_ext.blender_org.mmd_tools`：

```python
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.mmd_tools")
bpy.ops.mmd_tools.import_model(
    filepath=pmx_path,
    types={"MESH", "ARMATURE", "MORPHS"},   # 物理/显示框先不带，改造用不到
    scale=0.08,                            # MMD 单位 → 米
    clean_model=True,
    fix_bone_order=True,
    fix_ik_links=False,
    apply_bone_fixed_axis=False,
    rename_bones=True,
    dictionary="DISABLED",                 # 关键：保留日文骨名，模型间才好对照
)
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
```

实测：云堇.pmx → 597 根骨，日文骨名齐全，`rig_analyze.py` 能直接认链（手臂/腿/五指全对）。
注意 `dictionary` 若设成英文，骨名会变成 `Arm_L` / `Elbow_L` / `Wrist_L`（本项目材料里
已经有「英文命名版 + 日文命名版 + Rigify 版」三套并存的文件，见上表）。
