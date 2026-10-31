#!/usr/bin/env python3
"""从识别文字里只挑出每帧新出现的内容，读取时不用一遍遍看重复的界面。

用法：
  python3 novel_lines.py <识别文字文件或目录>... [--window 3] [--chrome-ratio 0.5] [--noise 词表文件]

规则：
  - 界面固定文字（菜单、侧边栏、页眉、浏览器标签）：同一个文字块出现在至少 3 段原片里，
    并且覆盖的原片占比、帧占比都不低于 --chrome-ratio，就当成界面文字去掉。
    去掉了哪些写在输出开头，去多了就调高 --chrome-ratio，漏了就用 --noise 补。
  - --noise 词表文件：每行一个文字块，额外去掉。
  - 每帧只打印和前 --window 帧相比新出现的行。

输入是 ocr.js 的输出格式：每帧以「== 帧文件名」开头，同一行的文字块用「 | 」连接。
"""

import argparse
import os
import re
import sys

FRAME_RE = re.compile(r"_t([\d.]+)\.jpg$")


def read_blocks(inputs):
    """返回 [(来源文件名, 帧名, [行])]，按输入顺序。"""
    files = []
    for item in inputs:
        item = os.path.expanduser(item)
        if os.path.isdir(item):
            files += sorted(
                os.path.join(item, n)
                for n in os.listdir(item)
                if n.endswith(".txt") and n != "识别失败.txt"
            )
        elif os.path.isfile(item):
            files.append(item)
        else:
            sys.exit(f"找不到识别文字：{item}")
    blocks = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        source = os.path.splitext(os.path.basename(path))[0]
        for part in re.split(r"^== ", text, flags=re.M)[1:]:
            name, _, body = part.partition("\n")
            blocks.append((source, name.strip(), [l for l in body.splitlines() if l.strip()]))
    return blocks


def segments(line):
    return [p.strip() for p in line.split(" | ") if p.strip()]


def main():
    ap = argparse.ArgumentParser(description="只挑出每帧新出现的文字")
    ap.add_argument("inputs", nargs="+", help="识别文字文件或目录")
    ap.add_argument("--window", type=int, default=3, help="和前几帧比，默认 3")
    ap.add_argument("--chrome-ratio", type=float, default=0.5, help="界面固定文字的覆盖占比门槛，默认 0.5")
    ap.add_argument("--noise", help="额外去掉的文字块，每行一个")
    args = ap.parse_args()

    blocks = read_blocks(args.inputs)
    if not blocks:
        sys.exit("识别文字里没有帧")

    clip_of = []
    for source, name, _ in blocks:
        clip_of.append((source, FRAME_RE.sub("", name)))
    clips = set(clip_of)

    frame_hits, clip_hits = {}, {}
    for (source, name, lines), clip in zip(blocks, clip_of):
        segs = {s for line in lines for s in segments(line)}
        for s in segs:
            frame_hits[s] = frame_hits.get(s, 0) + 1
            clip_hits.setdefault(s, set()).add(clip)

    chrome = set()
    if len(clips) >= 3:
        for s, n in frame_hits.items():
            c = len(clip_hits[s])
            if c >= 3 and c / len(clips) >= args.chrome_ratio and n / len(blocks) >= args.chrome_ratio:
                chrome.add(s)
    noise = set()
    if args.noise:
        with open(os.path.expanduser(args.noise), encoding="utf-8") as f:
            noise = {l.strip() for l in f if l.strip()}
    drop = chrome | noise

    print(f"# 共 {len(clips)} 段原片、{len(blocks)} 帧")
    if chrome:
        print("# 界面固定文字（已去掉）：" + "、".join(sorted(chrome)))
    else:
        print("# 界面固定文字：没有识别出来（原片少于 3 段，或界面差异大）")
    if noise:
        print(f"# 词表额外去掉 {len(noise)} 个文字块")

    prev_clip, history = None, []
    for (source, name, lines), clip in zip(blocks, clip_of):
        cleaned = []
        for line in lines:
            kept = [s for s in segments(line) if s not in drop]
            if kept:
                cleaned.append(" | ".join(kept))
        if clip != prev_clip:
            label = clip[0].replace("__", "/") if clip[1] in clip[0] else f"{clip[0]} / {clip[1]}"
            print(f"\n######## {label}")
            history, prev_clip = [], clip
        seen = set().union(*history) if history else set()
        new = [l for l in cleaned if l not in seen]
        m = FRAME_RE.search(name)
        t = m.group(1) if m else name
        print(f"--- t={t}s（新增 {len(new)} 行 / 共 {len(cleaned)} 行）")
        for l in new:
            print("  " + l)
        history = (history + [set(cleaned)])[-args.window:]


if __name__ == "__main__":
    main()
