# -*- coding: utf-8 -*-
"""MusicDoll 骨架改造 —— 进度文本块 `MusicDoll_Rig_Progress` 的读 / 写。

每个改造过的 .blend 里留一个文本块，下一个接手的人（或 agent）先读它：
没有 = 没改造过；status 不是 DONE 就按表接着干，不要从头再来。

块的结构（见方案 §5.4）：

    MusicDoll Rig Progress

    <<< AUTO:BEGIN >>>
    target   : armature "沙中净水1_arm"
    updated  : 2026-11-17T18:40  by rig_apply.py
    status   : IN PROGRESS          (IN PROGRESS | DONE | NEEDS HUMAN)
    ...
    legend   : x=done   -=not applicable   ?=unchecked   !=needs human
    part        hier zaxis arch ik copyrot twist leaf   notes
    arm.L       x    x     x    x  x       x     -      MCH_腕.L + MCH_ひじ.L created
    <<< AUTO:END >>>

    Notes（自由填写，脚本不动）

AUTO 段由脚本整段重写；段外文字（人写的 Notes、待办）脚本永远不动。
单独运行（不加载改造流程）也能用：

    blender -b <file.blend> -P rig_progress.py -- --print
    blender -b <file.blend> -P rig_progress.py -- --status DONE --save
"""
import datetime
import sys

import bpy

TEXT_BLOCK_NAME = "MusicDoll_Rig_Progress"
TITLE_LINE = "MusicDoll Rig Progress"
AUTO_BEGIN = "<<< AUTO:BEGIN >>>"
AUTO_END = "<<< AUTO:END >>>"

PART_COLUMNS = ("hier", "zaxis", "arch", "ik", "copyrot", "twist", "leaf")
MARK_LEGEND = "legend   : x=done   -=not applicable   ?=unchecked   !=needs human"
VALID_MARKS = "x-?!"
DEFAULT_NOTES = (
    "Notes (free text, never touched by scripts)\n"
    "- \n"
    "Next\n"
    "- \n"
)


# ── 文本块 ──────────────────────────────────────────────────────────────
def get_text_block(armature_object, create=False):
    """取骨架所属文件里的进度文本块（没有就按需新建）。"""
    text = bpy.data.texts.get(TEXT_BLOCK_NAME)
    if text is None and create:
        text = bpy.data.texts.new(TEXT_BLOCK_NAME)
        text.write(DEFAULT_NOTES)
    return text


def split_auto_section(body):
    """把文本块切成 (AUTO 段之前, AUTO 段内容, AUTO 段之后)。

    没有 AUTO 段时：整段算"之后"（人写的旧内容一律保留，脚本只往后追加）。
    """
    begin = body.find(AUTO_BEGIN)
    end = body.find(AUTO_END)
    if begin < 0 or end < 0 or end < begin:
        return body, None, ""
    before = body[:begin]
    auto = body[begin + len(AUTO_BEGIN):end]
    after = body[end + len(AUTO_END):]
    return before, auto, after


def parse_auto_section(auto_text):
    """解析 AUTO 段：返回 {header: dict, rows: list}。"""
    header = {}
    rows = []
    in_table = False
    for raw_line in auto_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith("part "):
            in_table = True
            continue
        if not in_table:
            if ":" in line:
                key, value = line.split(":", 1)
                header[key.strip()] = value.strip()
            continue
        tokens = line.split()
        if len(tokens) < 1:
            continue
        row = {"part": tokens[0]}
        for column_index, column in enumerate(PART_COLUMNS):
            row[column] = tokens[column_index + 1] if column_index + 1 < len(tokens) else "?"
        row["notes"] = " ".join(tokens[1 + len(PART_COLUMNS):])
        rows.append(row)
    return {"header": header, "rows": rows}


def read(armature_object):
    """读进度：返回 dict（found / header / rows / notes）。没有文本块时 found=False。"""
    text = get_text_block(armature_object, create=False)
    if text is None:
        return {"found": False, "header": {}, "rows": [], "notes": ""}
    before, auto, after = split_auto_section(text.as_string())
    parsed = parse_auto_section(auto or "")
    return {
        "found": True,
        "header": parsed["header"],
        "rows": parsed["rows"],
        "notes": (before + after).strip(),
        "raw": text.as_string(),
    }


def format_auto_section(header, rows):
    """把 header 与 rows 排版成 AUTO 段正文（不含 BEGIN/END 标记）。"""
    lines = []
    order = ("target", "updated", "status", "front", "note")
    for key in order:
        if header.get(key):
            lines.append("%-9s: %s" % (key, header[key]))
    for key, value in header.items():
        if key in order or not value:
            continue
        # legend 由 MARK_LEGEND 统一写一次；读回来的 header 里也有一份，跳过免得每存一次多一行
        if key == "legend":
            continue
        lines.append("%-9s: %s" % (key, value))
    lines.append("")
    lines.append(MARK_LEGEND)
    column_width = 8
    header_line = "%-12s" % "part" + "".join("%-*s" % (column_width, column) for column in PART_COLUMNS) + "notes"
    lines.append(header_line.rstrip())
    for row in rows:
        line = "%-12s" % row["part"]
        line += "".join("%-*s" % (column_width, row.get(column, "?")) for column in PART_COLUMNS)
        line += row.get("notes", "")
        lines.append(line.rstrip())
    return "\n".join(lines) + "\n"


def write(armature_object, target, status, rows, tool, front=None, note=None, extra_header=None):
    """整段重写 AUTO 段，段外文字（人写的 Notes）原样保留。返回写好的完整文本。"""
    text = get_text_block(armature_object, create=True)
    body = text.as_string()
    before, _auto, after = split_auto_section(body)
    header = {
        "target": target,
        "updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "status": status,
    }
    if front is not None:
        header["front"] = "(%.3f, %.3f, %.3f)" % (front[0], front[1], front[2])
    if note:
        header["note"] = note
    if extra_header:
        header.update(extra_header)
    auto_text = format_auto_section(header, rows)

    human_text = (before + after).strip("\n")
    for title in (TITLE_LINE,):
        if human_text.startswith(title):
            human_text = human_text[len(title):].strip("\n")
    if not human_text.strip():
        human_text = DEFAULT_NOTES.strip("\n")
    full_text = "%s\n\n%s\n%s\n%s\n\n%s\n" % (TITLE_LINE, AUTO_BEGIN, auto_text.rstrip("\n"), AUTO_END, human_text)
    text.clear()
    text.write(full_text)
    return full_text


def make_row(part, hier="-", zaxis="-", arch="-", ik="-", copyrot="-", twist="-", leaf="-", notes=""):
    return {
        "part": part, "hier": hier, "zaxis": zaxis, "arch": arch, "ik": ik,
        "copyrot": copyrot, "twist": twist, "leaf": leaf, "notes": notes,
    }


def merge_rows(existing_rows, new_rows):
    """按 part 覆盖：新跑出来的行替换同名旧行，其余旧行保留（别的链的记录不丢）。"""
    merged = {row["part"]: row for row in existing_rows}
    for row in new_rows:
        merged[row["part"]] = row
    order = [row["part"] for row in existing_rows]
    for row in new_rows:
        if row["part"] not in order:
            order.append(row["part"])
    return [merged[part] for part in order]


# ── 单独运行 ────────────────────────────────────────────────────────────
def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {"print": False, "status": None, "save": False, "file": None}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--print":
            options["print"] = True
        elif token == "--save":
            options["save"] = True
        elif token == "--status":
            index += 1
            options["status"] = argv[index]
        else:
            options["file"] = token
        index += 1
    return options


def _main():
    options = _parse_args()
    if options["file"]:
        try:
            bpy.ops.wm.open_mainfile(filepath=options["file"], load_ui=False)
        except RuntimeError as error:
            print("open warning: %s" % str(error).splitlines()[0][:160])
    armature_object = next((obj for obj in bpy.data.objects if obj.type == "ARMATURE"), None)
    if armature_object is None:
        print("no armature")
        return
    progress = read(armature_object)
    if options["status"]:
        write(armature_object, progress["header"].get("target", 'armature "%s"' % armature_object.name),
              options["status"], progress["rows"], "rig_progress.py",
              note=progress["header"].get("note"))
        progress = read(armature_object)
    if options["print"] or not options["status"]:
        print(progress.get("raw") or "(no %s text block)" % TEXT_BLOCK_NAME)
    if options["save"]:
        bpy.ops.wm.save_mainfile()
        print("saved %s" % bpy.data.filepath)


if __name__ == "__main__":
    _main()
