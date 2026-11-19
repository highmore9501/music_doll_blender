# -*- coding: utf-8 -*-
"""删掉手指的测试控制器（`T/I/M/R/P_<侧>_test`、`*_pole_test`），让下一次 rig_apply 按新口径重摆。

会先清掉引用它们的 IK（那些 IK 也要由 rig_apply 重建）；真控制器（不带 `_test`）不动。

用法：blender -b --factory-startup -P reset_finger_tests.py -- <file.blend> [--say-only]
"""
import re
import sys

import bpy

PATTERN = re.compile(r"^(T|I|M|R|P)_[LR]_(pole_)?test$")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        print(__doc__)
        return
    file_path = argv[0]
    say_only = "--say-only" in argv
    try:
        bpy.ops.wm.open_mainfile(filepath=file_path, load_ui=False)
    except RuntimeError as error:
        print("open warning: %s" % str(error).splitlines()[0][:160])

    doomed = [obj for obj in bpy.data.objects if obj.type == "EMPTY" and PATTERN.match(obj.name)]
    names = set(obj.name for obj in doomed)
    print("要删的测试控制器：%s" % (", ".join(sorted(names)) or "无"))

    armature_object = next((obj for obj in bpy.data.objects if obj.type == "ARMATURE"), None)
    stale = 0
    if armature_object is not None:
        for pose_bone in armature_object.pose.bones:
            for constraint in list(pose_bone.constraints):
                target_name = getattr(getattr(constraint, "target", None), "name", None)
                pole_name = getattr(getattr(constraint, "pole_target", None), "name", None)
                if target_name in names or pole_name in names:
                    stale += 1
                    if not say_only:
                        pose_bone.constraints.remove(constraint)
    print("引用了它们的约束：%d 条%s" % (stale, "（只报告）" if say_only else "（已删，等待重建）"))

    if say_only or not doomed:
        return
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)
    try:
        bpy.ops.wm.save_mainfile()
    except RuntimeError as error:
        message = str(error).splitlines()[0] if str(error) else ""
        print("存盘时 Blender 报了一条错（文件已写出，多半是缺贴图）：%s" % message)
    print("已保存：%s" % bpy.data.filepath)


if __name__ == "__main__":
    main()
