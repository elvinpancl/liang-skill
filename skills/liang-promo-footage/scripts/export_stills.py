#!/usr/bin/env python3
"""按清单从原片导出配图，再用文字识别核对每张图里有没有期望的关键词。

用法：
  python3 export_stills.py <清单文件> --src <原片根目录> --out <输出目录> [--ffmpeg ffmpeg] [--no-ocr]

清单每行一张图，# 开头是注释：
  名称|原片相对路径|时间|期望关键词
时间写秒（178、178.5）或 分:秒（2:58）、时:分:秒（0:02:58）。期望关键词可以空着。

输出：
  <输出目录>/<名称>.jpg       原尺寸整帧
  <输出目录>/stills_ocr.txt   全部配图的识别文字，给 scan_sensitive.py 扫打码项

ffmpeg 关闭了标准输入，清单再长也不会出现文件名和时间点错位。
关键词没对上的图会列出来，通常前后挪一两秒重导就行。
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OCR_JS = os.path.join(HERE, "ocr.js")


def parse_time(text):
    text = text.strip()
    if ":" in text:
        seconds = 0.0
        for part in text.split(":"):
            seconds = seconds * 60 + float(part)
        return seconds
    return float(text)


def read_list(path):
    rows = []
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        for no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                sys.exit(f"清单第 {no} 行少字段，应为 名称|原片相对路径|时间|期望关键词：{line}")
            name, clip, when = parts[:3]
            keyword = parts[3] if len(parts) > 3 else ""
            try:
                seconds = parse_time(when)
            except ValueError:
                sys.exit(f"清单第 {no} 行时间写法不对：{when}")
            rows.append((name, clip, seconds, keyword))
    return rows


def squash(text):
    return re.sub(r"\s+", "", text.replace(" | ", ""))


def main():
    ap = argparse.ArgumentParser(description="按清单导出配图并核对关键词")
    ap.add_argument("list_file", help="配图清单")
    ap.add_argument("--src", required=True, help="原片根目录，清单里的原片路径相对于它")
    ap.add_argument("--out", required=True, help="配图输出目录")
    ap.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg 可执行文件路径")
    ap.add_argument("--no-ocr", action="store_true", help="只导出，不识别核对")
    args = ap.parse_args()

    rows = read_list(args.list_file)
    src_root = os.path.abspath(os.path.expanduser(args.src))
    out_dir = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out_dir, exist_ok=True)

    status = {}
    exported = []
    for name, clip, seconds, keyword in rows:
        src = os.path.join(src_root, clip)
        target = os.path.join(out_dir, name + ".jpg")
        if not os.path.exists(src):
            status[name] = ("原片不存在", clip)
            continue
        result = subprocess.run(
            [args.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
             "-ss", f"{seconds:.2f}", "-i", src, "-frames:v", "1", "-q:v", "2", target],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
        )
        if result.returncode != 0 or not os.path.exists(target):
            status[name] = ("导出失败", result.stderr.strip()[:200])
            continue
        exported.append((name, target, keyword))
        status[name] = ("已导出", "")

    can_ocr = not args.no_ocr and sys.platform == "darwin"
    if exported and can_ocr:
        texts = {}
        chunks = []
        for i in range(0, len(exported), 25):
            batch = exported[i:i + 25]
            result = subprocess.run(
                ["osascript", "-l", "JavaScript", OCR_JS, *[t for _, t, _ in batch]],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
            )
            if result.returncode != 0:
                for name, _, _ in batch:
                    status[name] = ("识别失败", result.stderr.strip()[:200])
                continue
            chunks.append(result.stdout.rstrip("\n"))
            for part in re.split(r"^== ", result.stdout, flags=re.M)[1:]:
                fname, _, body = part.partition("\n")
                texts[os.path.splitext(fname.strip())[0]] = body
        with open(os.path.join(out_dir, "stills_ocr.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(chunks) + "\n")
        for name, _, keyword in exported:
            if status[name][0] != "已导出":
                continue
            if not keyword:
                status[name] = ("已导出", "没写期望关键词，未核对")
            elif squash(keyword) in squash(texts.get(name, "")):
                status[name] = ("核对通过", keyword)
            else:
                status[name] = ("关键词没对上", keyword)
    elif exported and not args.no_ocr:
        print("非 macOS，跳过识别核对，请人工看图确认", file=sys.stderr)

    bad = 0
    print("| 图 | 状态 | 说明 |")
    print("|---|---|---|")
    for name, _, _, _ in rows:
        state, note = status[name]
        if state not in ("已导出", "核对通过"):
            bad += 1
        print(f"| {name} | {state} | {note} |")
    print(f"\n共 {len(rows)} 张，有问题 {bad} 张；配图在 {out_dir}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
