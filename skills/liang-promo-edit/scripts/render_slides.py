#!/usr/bin/env python3
"""把 PPT 导出的状态图按旁白时长渲染成开头或结尾视频，同时出对齐的字幕和卡片亮起时间表。

痛点卡逐张亮起这类开头，不用再录 PPT 放映、手动对齐：每张状态图停到它那几句旁白念完，图与图之间叠化。

用法一，渲染：
  python3 render_slides.py <对照表.md> --out <开头.mp4> [参数]

用法二，从录好的放映视频里取状态图（没有逐张导出的状态图时用）：
  python3 render_slides.py --from-video <放映录屏.mp4> --states <状态图目录> [--crop x,y,w,h] [--dedupe]
  在录屏里找画面静止的时刻（卡片亮起、翻页之后停住的那一下），每个状态存一张图，
  再写一张「状态表.md」：状态图、亮起时间、识别出的文字，旁白一列空着。填好旁白就能直接当对照表渲染。
  - --crop：录屏里只有一部分是幻灯片时，按比例裁出幻灯片区域，例如 0,0.04,1,0.92。
  - --dedupe：同一套卡片放了好几遍时，和前面任何一个状态几乎一样的都去掉，只留第一次出现的。

对照表是一张 Markdown 表格，每行一个状态：
  | 状态图 | 旁白 | 最短停留 |
  |---|---|---|
  | 状态图/01_标题.png | 很多企业想用 AI／又不敢放心用 | 1.5 |
  | 状态图/02_第1张.png | 回答必须有据可依 | |
  - 状态图：PPT 每一步导出成一张图（同一页的不同动画状态各存一张），路径相对对照表所在目录。
  - 旁白：一句一行，用「／」隔开。可以空着，空着就按最短停留。
  - 最短停留：秒，可以空着，默认 1.5。

常用参数：
  --rate 5.7     每秒念几个字。不给就读校准记录「当前默认值」表里的「render_slides.py --rate」，读不到用 5.7
                 这是按字幕一句接一句、中间不留空档量出来的语速，所以 --lead、--gap 默认都是 0
  --tail 0.5     最后一个状态念完后再停几秒
  --fade 0.3     状态之间的叠化时长
  --size 1920x1080，--fps 30

输出：
  <开头.mp4>
  <开头>.srt               和视频对齐的字幕，导入剪映后批量文本朗读
  制作过程/<开头>_排时.md   每个状态的起止和对应旁白；想自己录 PPT 放映时，照这张表的时间点翻页
"""

import argparse
import os
import re
import sys

sys.dont_write_bytecode = True  # 不在 skill 目录里留 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
from index_clips import scene_series, static_runs  # noqa: E402
from make_subtitles import split_lines  # noqa: E402


def extract_states(args):
    """从放映录屏里取每个静止状态的一帧，写状态图和状态表。"""
    video = os.path.abspath(os.path.expanduser(args.from_video))
    info = C.probe(video)
    if not info:
        sys.exit(f"读不出录屏：{video}")
    out_dir = os.path.abspath(os.path.expanduser(args.states))
    os.makedirs(out_dir, exist_ok=True)
    series = scene_series(video)
    runs = static_runs(series, args.still, args.min_still)
    if not runs:
        sys.exit("录屏里没找到停住超过 --min-still 秒的画面，调小 --min-still 或 --still 再试")
    crop = ""
    if args.crop:
        x, y, w, h = [float(v) for v in re.split(r"[,，\s]+", args.crop.strip()) if v]
        crop = f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},"

    states, kept_thumbs, last_thumb, last_kept = [], [], None, False
    for a, b in runs:
        t = max(a, b - 0.2)
        thumb = C.gray_thumb(video, t)
        if last_thumb is not None and C.thumb_diff(thumb, last_thumb) < args.same:
            if last_kept:
                states[-1]["end"] = b  # 和紧挨着的上一段几乎一样：只是中间抖了一下，并成一个
            last_thumb = thumb
            continue
        last_thumb = thumb
        last_kept = not (args.dedupe and any(C.thumb_diff(thumb, k) < args.same for k in kept_thumbs))
        if last_kept:
            kept_thumbs.append(thumb)
            states.append({"start": a, "end": b, "t": t})

    paths = []
    for i, s in enumerate(states, 1):
        name = f"{i:02d}_t{s['start']:06.1f}.png"
        path = os.path.join(out_dir, name)
        C.run_ffmpeg(["-loglevel", "error", "-y", "-ss", f"{s['t']:.3f}", "-i", video, "-frames:v", "1",
                      "-vf", crop + "scale=trunc(iw/2)*2:trunc(ih/2)*2", path], check=True)
        s["file"] = name
        # 翻页闪屏：去掉录屏的黑边以后，95% 以上的像素都和中位数差不到 10 级亮度
        thumb = [v for v in (C.gray_thumb(path) or b"") if v >= 16]
        if thumb:
            med = sorted(thumb)[len(thumb) // 2]
            s["blank"] = sum(1 for v in thumb if abs(v - med) <= 10) / len(thumb) >= 0.95
        paths.append(path)
    texts = {}
    if sys.platform == "darwin" and not args.no_ocr:
        found, _ = C.ocr_images(paths)
        for name, items in found.items():
            lines = [line["t"] for line in C.group_lines(items) if C.count_chars(line["t"]) >= 2]
            texts[name] = "；".join(lines)[:60].replace("|", "\\|")

    md = ["# 状态表", "",
          f"从 {os.path.basename(video)} 里取出 {len(states)} 个静止状态。亮起时间是录屏里这个状态开始停住的时刻。"
          "删掉不要的行，给要用的行填上旁白，就能直接当对照表：",
          "", f"`python3 render_slides.py {os.path.join(out_dir, '状态表.md')} --out 开头.mp4`", "",
          "卡片高亮这类变化识别文字看不出来，以图为准。", "",
          "| 状态图 | 旁白 | 最短停留 | 亮起 | 停住 | 识别文字 |", "|---|---|---|---|---|---|"]
    for s in states:
        note = "（几乎是纯色画面，可能是翻页时的闪屏，看图确认后删掉）" if s.get("blank") else texts.get(s["file"], "")
        md.append(f"| {s['file']} |  |  | {C.fmt_time(s['start'])} | {s['end'] - s['start']:.1f} 秒 | {note} |")
    with open(os.path.join(out_dir, "状态表.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"取出 {len(states)} 个状态，状态表写在 {out_dir}/状态表.md")


def render(args):
    if args.rate is None:
        args.rate = C.calib_default("render_slides.py --rate", 5.7)
    _, rows = C.pick_table(args.cues, ["状态图"])
    if not rows:
        sys.exit("对照表里没找到含「状态图」列的表格")
    base = os.path.dirname(os.path.abspath(args.cues))
    out = os.path.abspath(os.path.expanduser(args.out))
    stem = os.path.splitext(os.path.basename(out))[0]
    proc = os.path.join(os.path.dirname(out), "制作过程")
    work = os.path.join(proc, f"{stem}_片段")
    os.makedirs(work, exist_ok=True)
    W, H = [int(x) for x in args.size.split("x")]

    states = []
    for i, row in enumerate(rows):
        img = row["状态图"].strip().strip("`")
        path = img if os.path.isabs(img) else os.path.join(base, img)
        if not os.path.exists(path):
            sys.exit(f"第 {i + 1} 行找不到状态图：{img}")
        lines = split_lines(row.get("旁白", ""))
        narr = sum(C.count_chars(t) / args.rate for _, t in lines) + args.gap * max(len(lines) - 1, 0)
        hold = float(row["最短停留"]) if row.get("最短停留", "").strip() else args.min_hold
        last = i + 1 == len(rows)
        fade_next = 0.0 if last else args.fade
        dur = max(hold, args.lead + narr + (args.tail if last else 0.0) + fade_next)
        img_stem = C.safe_name(os.path.splitext(os.path.basename(img))[0])
        name = img_stem if re.match(r"^\d+_", img_stem) else f"{i + 1:02d}_{img_stem}"
        states.append({"name": name,
                       "img": path, "lines": lines, "duration": round(dur, 3), "trans": "叠化" if i else "切"})

    for s in states:
        still = os.path.join(work, s["name"] + "_静帧.mp4")
        C.run_ffmpeg(["-loglevel", "error", "-y", "-loop", "1", "-t", f"{s['duration']:.3f}", "-i", s["img"],
                      "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                             f"setsar=1,format=yuv420p", "-r", str(args.fps), "-c:v", "libx264", "-preset", "veryfast",
                      "-crf", "18", still], check=True)
        s["file"] = still
    C.join_clips(states, out, os.path.join(work, "拼接"), size=args.size, fps=args.fps,
                 dissolve=args.fade, crf=18)

    subs, table = [], []
    for s, (a, b) in zip(states, C.timeline(states, args.fade)):
        t = a + args.lead
        for anchor, text in s["lines"]:
            start = a + anchor if anchor is not None else t
            end = start + C.count_chars(text) / args.rate
            subs.append((start, end, text))
            t = end + args.gap
        table.append((s["name"], a, b, "／".join(text for _, text in s["lines"])))
    with open(os.path.splitext(out)[0] + ".srt", "w", encoding="utf-8") as f:
        for i, (a, b, text) in enumerate(subs, 1):
            f.write(f"{i}\n{C.fmt_srt(a)} --> {C.fmt_srt(b)}\n{text}\n\n")
    md = [f"# {stem}排时", "", "想自己录 PPT 放映时，照「亮起」一列的时间点翻页或点出下一张卡。", "",
          "| 状态 | 亮起 | 结束 | 旁白 |", "|---|---|---|---|"]
    md += [f"| {n} | {C.fmt_time(a)} | {C.fmt_time(b)} | {t} |" for n, a, b, t in table]
    with open(os.path.join(proc, f"{stem}_排时.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    got = C.probe(out)
    print(f"{stem}：{len(states)} 个状态，{C.fmt_time(got['duration'] if got else 0)}，旁白 {len(subs)} 句，"
          f"按每秒 {args.rate:g} 字估")


def main():
    ap = argparse.ArgumentParser(description="状态图按旁白渲染成开头或结尾；或从放映录屏里取状态图")
    ap.add_argument("cues", nargs="?", help="对照表（Markdown）")
    ap.add_argument("--out", help="输出视频路径")
    ap.add_argument("--rate", type=float, default=None)
    # 开场语速为可调初始参数，使用前应按实际配音校准。
    ap.add_argument("--gap", type=float, default=0.0, help="句间停顿秒数，默认 0")
    ap.add_argument("--lead", type=float, default=0.0, help="每个状态亮起后多久开口，默认 0")
    ap.add_argument("--tail", type=float, default=0.5, help="最后一个状态念完后再停几秒，默认 0.5")
    ap.add_argument("--fade", type=float, default=0.3)
    ap.add_argument("--min-hold", type=float, default=1.5)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--from-video", help="放映录屏，从里面取状态图")
    ap.add_argument("--states", help="状态图输出目录（配 --from-video）")
    ap.add_argument("--crop", help="幻灯片在录屏里的区域，比例坐标 x,y,w,h")
    ap.add_argument("--dedupe", action="store_true", help="去掉和前面任何一个状态几乎一样的状态")
    ap.add_argument("--still", type=float, default=0.001, help="变化分数低于它算停住，默认 0.001")
    ap.add_argument("--min-still", type=float, default=0.6, help="停住超过几秒算一个状态，默认 0.6")
    ap.add_argument("--same", type=float, default=0.5, help="两个状态变化像素占比低于百分之几算同一个，默认 0.5")
    ap.add_argument("--no-ocr", action="store_true", help="状态表里不写识别文字")
    args = ap.parse_args()

    if args.from_video:
        if not args.states:
            sys.exit("--from-video 要配 --states 指定状态图目录")
        extract_states(args)
    else:
        if not args.cues or not args.out:
            sys.exit("渲染要给对照表和 --out；从录屏取状态图用 --from-video 加 --states")
        render(args)


if __name__ == "__main__":
    main()
