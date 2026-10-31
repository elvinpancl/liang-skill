#!/usr/bin/env python3
"""复盘：拿 AI 起草的旁白和成片字幕比，算沿用、改写、新写的比例，再算语速、时长和剪映编辑时长。

用法：
  python3 retro_compare.py --ai <AI 旁白> --final <成片字幕> [参数]

  --ai     AI 起草的旁白，可以是剪辑台本（读「旁白」列）、字幕.srt、文本朗读稿.txt，
           或带「**口播**」段落的配音稿 Markdown
  --final  剪映导出的成片字幕，srt 带时间，txt 不带时间（只算文字）
  --skip-until 文字   成片字幕从开头起，到第一句含这段文字的句子为止都跳过，用来去掉各篇共用的开场
  --skip-lines N      或者直接跳过前 N 句
  --video  成片视频，用来读时长
  --draft  剪映工程目录（读 draft_settings 里的累计编辑时长）。工程是复制出来的，时长含复制前的部分
  --out    写 Markdown 报告；--json 再写一份机器可读的结果，方便追加校准记录

判定口径（和校准记录一致）：
  每句成片字幕去掉空格和标点，和 AI 全文比对，只数不短于 3 个字的相同片段。
  覆盖 ≥80% 算沿用，40–80% 算改写，其余算新写。比例按字数算。
"""

import argparse
import difflib
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # 不在 skill 目录里留 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
from make_subtitles import split_lines  # noqa: E402


def read_srt(path):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        times = next((l for l in lines if "-->" in l), None)
        if not times:
            continue
        a, b = [x.strip().replace(",", ".") for x in times.split("-->")]
        body = " ".join(l for l in lines if "-->" not in l and not re.fullmatch(r"\d+", l.strip()))
        out.append((C.parse_time(a), C.parse_time(b), body.strip()))
    return out


def load_ai(path):
    if path.lower().endswith(".srt"):
        return [t for _, _, t in read_srt(path)]
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    if path.lower().endswith(".md"):
        _, rows = C.pick_table(path, ["旁白"])
        if rows:
            return [t for row in rows for _, t in split_lines(row.get("旁白", ""))]
        blocks = re.findall(r"\*\*口播\*\*\s*\n(.*?)(?=\n\*\*|\n## |\Z)", text, re.S)
        if blocks:
            return [l.strip() for b in blocks for l in re.split(r"[\n。！？]", b) if l.strip()]
    return [l.strip() for l in text.splitlines() if l.strip()]


def classify(lines, reference):
    ref = C.norm_text("".join(reference))
    rows = []
    for line in lines:
        n = C.norm_text(line)
        if not n:
            continue
        sm = difflib.SequenceMatcher(None, n, ref, autojunk=False)
        matched = sum(b.size for b in sm.get_matching_blocks() if b.size >= 3)
        r = matched / len(n)
        rows.append((line, len(n), r, "沿用" if r >= 0.8 else "改写" if r >= 0.4 else "新写"))
    return rows


def main():
    ap = argparse.ArgumentParser(description="复盘：AI 旁白和成片字幕对比")
    ap.add_argument("--ai", required=True)
    ap.add_argument("--final", required=True)
    ap.add_argument("--skip-until")
    ap.add_argument("--skip-lines", type=int, default=0)
    ap.add_argument("--video")
    ap.add_argument("--draft")
    ap.add_argument("--label", default="", help="报告标题里的篇名")
    ap.add_argument("--out")
    ap.add_argument("--json")
    args = ap.parse_args()

    if args.final.lower().endswith(".srt"):
        final = read_srt(args.final)
    else:
        with open(args.final, encoding="utf-8-sig") as f:
            final = [(None, None, l.strip()) for l in f if l.strip()]
    skip = args.skip_lines
    if args.skip_until:
        hit = next((i for i, (_, _, t) in enumerate(final[:40]) if args.skip_until in t), None)
        if hit is None:
            sys.exit(f"成片字幕前 40 句里没有「{args.skip_until}」")
        skip = hit + 1
    opening, body = final[:skip], final[skip:]
    ai = load_ai(args.ai)
    rows = classify([t for _, _, t in body], ai)
    total = sum(n for _, n, _, _ in rows) or 1
    share = {k: sum(n for _, n, _, c in rows if c == k) / total for k in ("沿用", "改写", "新写")}
    ai_chars = len(C.norm_text("".join(ai)))
    dropped = [(t, r) for t, n, r, c in classify(ai, [t for _, _, t in body]) if c == "新写"]

    result = {"label": args.label, "ai_chars": ai_chars, "final_chars": total, "final_lines": len(rows),
              "share": {k: round(v, 3) for k, v in share.items()},
              "chars_change": round(total / ai_chars - 1, 3) if ai_chars else None,
              "avg_line_chars": round(total / max(len(rows), 1), 1)}
    timed = [x for x in body if x[0] is not None]
    if timed:
        voiced = sum(b - a for a, b, _ in timed)
        span = timed[-1][1] - timed[0][0]
        result["rate_voiced"] = round(total / voiced, 2) if voiced else None
        result["rate_timeline"] = round(total / span, 2) if span else None
        result["avg_line_seconds"] = round(voiced / len(timed), 2)
        gaps = [(timed[i][0] - timed[i - 1][1], timed[i - 1][1]) for i in range(1, len(timed))]
        result["gaps_over_1_5"] = [[round(t, 1), round(g, 1)] for g, t in gaps if g > 1.5]
        if opening and opening[0][0] is not None:
            oc = sum(C.count_chars(t) for _, _, t in opening)
            result["opening_rate"] = round(oc / (opening[-1][1] - opening[0][0]), 2)
            result["opening_seconds"] = round(opening[-1][1] - opening[0][0], 1)
    if args.video:
        info = C.probe(args.video)
        result["video_seconds"] = round(info["duration"], 1) if info else None
    if args.draft:
        path = os.path.join(args.draft, "draft_settings")
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                m = re.search(r"real_edit_seconds=(\d+)", f.read())
            if m:
                result["edit_hours"] = round(int(m.group(1)) / 3600, 1)

    print(f"{args.label or os.path.basename(args.final)}：正文 {len(rows)} 句 {total} 字，"
          f"沿用 {share['沿用']:.0%}，改写 {share['改写']:.0%}，新写 {share['新写']:.0%}；"
          f"AI 稿 {ai_chars} 字，成片字数变化 {result['chars_change']:+.0%}" if ai_chars else "")
    if "rate_timeline" in result:
        print(f"  语速：按时间轴 {result['rate_timeline']} 字/秒，发声时 {result['rate_voiced']} 字/秒，"
              f"每句 {result['avg_line_chars']} 字、{result['avg_line_seconds']} 秒")

    if args.out:
        md = [f"# 复盘数据{('：' + args.label) if args.label else ''}", "",
              f"- AI 旁白：{os.path.basename(args.ai)}，{ai_chars} 字",
              f"- 成片字幕：{os.path.basename(args.final)}，正文 {len(rows)} 句、{total} 字"
              f"（跳过开头 {skip} 句共用开场）",
              f"- 沿用 {share['沿用']:.0%}，改写 {share['改写']:.0%}，新写 {share['新写']:.0%}（按字数）",
              f"- 成片字数比 AI 稿 {result['chars_change']:+.0%}" if ai_chars else "- AI 稿为空"]
        if "rate_timeline" in result:
            md.append(f"- 语速：按时间轴 {result['rate_timeline']} 字/秒，只算发声 {result['rate_voiced']} 字/秒；"
                      f"每句平均 {result['avg_line_chars']} 字、{result['avg_line_seconds']} 秒")
            if "opening_rate" in result:
                md.append(f"- 开场 {result['opening_seconds']} 秒，语速 {result['opening_rate']} 字/秒")
        if result.get("video_seconds"):
            md.append(f"- 成片时长 {C.fmt_time(result['video_seconds'])}")
        if result.get("edit_hours") is not None:
            md.append(f"- 剪映累计编辑 {result['edit_hours']} 小时（复制出来的工程含复制前的时长）")
        md += ["", "## 新写的句子", ""]
        md += [f"- {t}" for t, _, _, c in rows if c == "新写"] or ["- 无"]
        md += ["", "## 改写的句子", ""]
        md += [f"- {t}（覆盖 {r:.0%}）" for t, _, r, c in rows if c == "改写"] or ["- 无"]
        md += ["", "## AI 稿里被删掉的句子", ""]
        md += [f"- {t}" for t, _ in dropped] or ["- 无"]
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
    if args.json:
        result["new_lines"] = [t for t, _, _, c in rows if c == "新写"]
        result["dropped_ai_lines"] = [t for t, _ in dropped]
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
