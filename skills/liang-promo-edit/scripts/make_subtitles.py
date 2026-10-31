#!/usr/bin/env python3
"""把台本里的旁白排进粗剪预览的时间轴，出 SRT 字幕、文本朗读稿和读音检查表，并报超长和空档。

用法：
  python3 make_subtitles.py --index <制作过程/粗剪索引.json> --out <本篇目录> [参数]

常用参数：
  --script 台本.md   旁白以台本为准（改了旁白不用重切粗剪）；不给就用切粗剪时记下的旁白
  --rate 4.7         配音每秒念几个字（只算发声）。不给就读校准记录「当前默认值」表里的
                     「make_subtitles.py --rate」，读不到用 4.7
  --gap 0.25         句间停顿秒数
  --lead 0.2         镜头开始后多久开口
  --max-line 14      一行超过几个字报警
  --cap 秒           全片时长上限；--fixed 秒 是粗剪以外的部分（例如开场 27 秒加结尾 12 秒）
  --offset 秒        字幕整体后移，例如粗剪接在开场后面时填开场时长
  --chapter 文字     章节标签，例如「3、组织管理」，写进包装清单

旁白写法：台本「旁白」列里一句一行，句与句之间用「／」隔开。句首写「@1.5 」表示这句在本镜头开始后 1.5 秒开口，
用来对齐卡片亮起或结果出现的时刻。字数口径：去掉空格和标点，英文字母、数字各算一个字，和校准记录一致。

输出：
  <本篇目录>/字幕.srt            导入剪映后对字幕轨批量「文本朗读」，配音和字幕一次对齐
  <本篇目录>/文本朗读稿.txt      一行一句，SRT 导不进去时粘贴用
  <本篇目录>/读音检查表.md        英文、缩写和数字，生成配音前逐个试听
  <本篇目录>/包装清单.md          章节标签、转场、放大备选、音效、身份切换，按预览片时间排
  <本篇目录>/制作过程/排时报告.md  每个镜头的旁白长度、超出和空档
退出码：有超出画面 0.3 秒以上的镜头时为 2，方便循环修改。
"""

import argparse
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # 不在 skill 目录里留 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

SPLIT_RE = re.compile(r"\s*[／/]\s*|<br\s*/?>")
ANCHOR_RE = re.compile(r"^@\s*([\d.:]+)\s+")
DIGITS = "零一二三四五六七八九"


def split_lines(cell):
    lines = []
    for part in SPLIT_RE.split(cell or ""):
        part = part.strip()
        if not part:
            continue
        anchor = None
        m = ANCHOR_RE.match(part)
        if m:
            anchor = C.parse_time(m.group(1))
            part = part[m.end():].strip()
        if part:
            lines.append((anchor, part))
    return lines


def reading_hint(token):
    if re.fullmatch(r"\d+", token):
        if len(token) == 1:
            return DIGITS[int(token)]
        return "确认按数值还是逐字读"
    if re.fullmatch(r"[A-Z]{2,6}", token):
        return " ".join(token)
    m = re.fullmatch(r"([A-Z][a-z]+)([A-Z]{2,})", token)
    if m:
        return f"{m.group(1)} {' '.join(m.group(2))}"
    return "试听确认"


def main():
    ap = argparse.ArgumentParser(description="旁白排时，出 SRT 和文本朗读稿")
    ap.add_argument("--index", required=True, help="build_roughcut.py 写的粗剪索引.json")
    ap.add_argument("--out", required=True, help="本篇目录")
    ap.add_argument("--script", help="剪辑台本，旁白以它为准")
    ap.add_argument("--rate", type=float, default=None)
    ap.add_argument("--gap", type=float, default=0.25)
    ap.add_argument("--lead", type=float, default=0.2)
    ap.add_argument("--max-line", type=int, default=14)
    ap.add_argument("--cap", type=float)
    ap.add_argument("--fixed", type=float, default=0.0)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--chapter", default="", help="章节标签文字")
    args = ap.parse_args()

    if args.rate is None:
        args.rate = C.calib_default("make_subtitles.py --rate", 4.7)
    with open(args.index, encoding="utf-8") as f:
        index = json.load(f)
    shots = index["shots"]
    if args.script:
        _, rows = C.pick_table(args.script, ["原片", "入点", "出点"])
        by_no = {}
        for n, row in enumerate(rows, 1):
            no = int(row["序号"]) if row.get("序号", "").strip().isdigit() else n
            by_no[no] = row.get("旁白", "")
        for s in shots:
            if s["no"] in by_no:
                s["旁白"] = by_no[s["no"]]

    subs, report, overflow = [], [], []
    cursor = 0.0
    for s in shots:
        a, b = s["preview_start"], s["preview_end"]
        cursor = max(cursor, a + args.lead)
        lines = split_lines(s.get("旁白", ""))
        first_start, last_end, notes = None, None, []
        for anchor, text in lines:
            start = a + anchor if anchor is not None else cursor
            if start < cursor - 0.05:
                notes.append(f"「{text[:8]}」的锚点早于上一句结束，顺延 {cursor - start:.1f} 秒")
                start = cursor
            dur = C.count_chars(text) / args.rate
            end = start + dur
            subs.append((start, end, text))
            first_start = start if first_start is None else first_start
            last_end = end
            cursor = end + args.gap
            if C.count_chars(text) > args.max_line:
                notes.append(f"「{text[:10]}…」{C.count_chars(text)} 字，超过 {args.max_line} 字，拆成两句")
        if lines:
            spill = last_end - b
            idle = b - last_end
            if spill > 0.3:
                notes.append(f"旁白超出画面 {spill:.1f} 秒：删字，或把出点往后挪")
                overflow.append(s["name"])
            elif idle > 1.5:
                notes.append(f"画面比旁白多 {idle:.1f} 秒：补一句，或把出点往前挪")
        elif b - a > 3:
            notes.append(f"没有旁白，画面 {b - a:.1f} 秒：确认是有意留白（例如等待叠化、结果停留）")
        need = (last_end - a + 0.3) if lines else 0.0
        report.append((s, len(lines), need, notes))

    out_dir = os.path.abspath(os.path.expanduser(args.out))
    proc = os.path.join(out_dir, "制作过程")
    os.makedirs(proc, exist_ok=True)
    with open(os.path.join(out_dir, "字幕.srt"), "w", encoding="utf-8") as f:
        for i, (a, b, text) in enumerate(subs, 1):
            f.write(f"{i}\n{C.fmt_srt(a + args.offset)} --> {C.fmt_srt(b + args.offset)}\n{text}\n\n")
    with open(os.path.join(out_dir, "文本朗读稿.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(text for _, _, text in subs) + "\n")

    tokens = {}
    for _, _, text in subs:
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9\-]*|\d+", text):
            tokens.setdefault(tok, text)
    with open(os.path.join(out_dir, "读音检查表.md"), "w", encoding="utf-8") as f:
        f.write("# 读音检查表\n\n生成配音前逐个试听。读错时，配音用右列的写法生成，生成后再把字幕改回原写法。\n\n")
        f.write("| 写法 | 出现在 | 建议读法 |\n|---|---|---|\n")
        for tok, text in tokens.items():
            f.write(f"| {tok} | {text[:20]} | {reading_hint(tok)} |\n")
        if not tokens:
            f.write("| 无 | | |\n")

    cue = ["# 包装清单", "",
           "时间按粗剪预览片算" + (f"，整体后移 {args.offset:g} 秒" if args.offset else "") + "。剪映里按这张表加转场、放大和音效。", ""]
    if args.chapter:
        cue += [f"**章节标签**：「{args.chapter}」，右上角，从第一个镜头开始到结尾卡之前一直保留。", ""]
    cue += ["| 时间 | 镜头 | 转场 | 身份 | 放大备选 | 音效 | 备注 |", "|---|---|---|---|---|---|---|"]
    last_role = None
    for s in shots:
        role = s.get("身份", "")
        switch = "切换：" + role if role and last_role and role != last_role else role
        last_role = role or last_role
        zoom = os.path.basename(s["zoom_file"]) if s.get("zoom_file") else ""
        cue.append(f"| {C.fmt_time(s['preview_start'] + args.offset)} | {s['name']} | {s.get('trans', '切')} | "
                   f"{switch} | {zoom} | {s.get('音效', '')} | |")
    with open(os.path.join(out_dir, "包装清单.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(cue) + "\n")

    total_pic = index.get("total", shots[-1]["preview_end"] if shots else 0)
    narr_end = subs[-1][1] if subs else 0.0
    est = max(total_pic, narr_end) + args.fixed
    chars = sum(C.count_chars(t) for _, _, t in subs)
    lines_md = ["# 排时报告", "",
                f"旁白 {len(subs)} 句、{chars} 字，按每秒 {args.rate} 字估算。粗剪 {C.fmt_time(total_pic)}，"
                f"旁白念完在 {C.fmt_time(narr_end)}，加上粗剪以外的 {args.fixed:.0f} 秒，全片约 {C.fmt_time(est)}"
                + (f"，上限 {C.fmt_time(args.cap, 0)}{'，超了' if est > args.cap else ''}" if args.cap else "") + "。", "",
                "| 镜头 | 画面起止 | 画面时长 | 旁白句数 | 旁白需要 | 提示 |", "|---|---|---|---|---|---|"]
    for s, n, need, notes in report:
        lines_md.append(f"| {s['name']} | {C.fmt_time(s['preview_start'])}–{C.fmt_time(s['preview_end'])} | "
                        f"{s['preview_end'] - s['preview_start']:.1f} | {n} | {need:.1f} | {'；'.join(notes)} |")
    with open(os.path.join(proc, "排时报告.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines_md) + "\n")

    print(f"{len(subs)} 句，{chars} 字；全片约 {C.fmt_time(est)}"
          + (f"（上限 {C.fmt_time(args.cap, 0)}）" if args.cap else ""))
    flagged = [(s["name"], notes) for s, _, _, notes in report if notes]
    for name, notes in flagged:
        print(f"  {name}：{'；'.join(notes)}")
    print(f"字幕写在 {out_dir}/字幕.srt，排时报告在 {proc}/排时报告.md")
    if overflow:
        sys.exit(2)


if __name__ == "__main__":
    main()
