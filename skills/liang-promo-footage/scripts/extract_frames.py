#!/usr/bin/env python3
"""按画面变化给录屏原片抽关键帧。

用法：
  python3 extract_frames.py <原片目录或文件>... --out <输出目录> [参数]
  python3 extract_frames.py <原片目录或文件>... --list      # 只盘点时长和分辨率

取帧规则：
  - 第一帧（0.5 秒）和最后一帧（结尾前 0.3 秒）总是保留。
  - 画面变化点往后延 --delay 秒再取，等界面加载完。
  - 相邻两帧至少隔 --gap 秒；最后一帧离前一帧太近时，用最后一帧替换前一帧。
  - 两帧之间超过 --fill 秒没有变化就均匀补帧，补的帧离下一帧至少 4 秒。

输出：
  <输出目录>/<原片所在目录名>/<原片名>_t0000.0.jpg
  <输出目录>/index.json  {原片相对路径: {path, duration, width, height, scenes, dir, frames}}

时长和分辨率从 ffmpeg -i 的输出里读，不依赖 ffprobe。所有 ffmpeg 调用都关闭标准输入，
放进 shell 循环里也不会吃掉后面的输入行。
"""

import argparse
import json
import os
import re
import subprocess
import sys

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def find_videos(inputs):
    """返回 [(相对路径, 绝对路径)]。目录输入时相对路径带上目录自己的名字。"""
    found = []
    for item in inputs:
        item = os.path.abspath(os.path.expanduser(item))
        if os.path.isfile(item):
            found.append((os.path.basename(item), item))
            continue
        if not os.path.isdir(item):
            sys.exit(f"找不到原片：{item}")
        base = os.path.dirname(item.rstrip(os.sep))
        for root, dirs, files in os.walk(item):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                if os.path.splitext(name)[1].lower() in VIDEO_EXTS and not name.startswith("."):
                    path = os.path.join(root, name)
                    found.append((os.path.relpath(path, base), path))
    seen = set()
    unique = []
    for rel, path in found:
        if rel not in seen:
            seen.add(rel)
            unique.append((rel, path))
    return unique


def run_ffmpeg(ffmpeg, args):
    return subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )


def probe(ffmpeg, path):
    info = run_ffmpeg(ffmpeg, ["-i", path]).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    if not m:
        return None
    h, mi, s = m.groups()
    duration = int(h) * 3600 + int(mi) * 60 + float(s)
    size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    width, height = (int(size.group(1)), int(size.group(2))) if size else (None, None)
    return duration, width, height


def pick_times(duration, scenes, gap, delay, fill):
    cands = [0.5] + [min(t + delay, duration - 0.3) for t in scenes] + [max(duration - 0.3, 0.5)]
    kept = []
    for t in sorted(cands):
        if not kept or t - kept[-1] >= gap:
            kept.append(t)
        elif t == cands[-1]:
            kept[-1] = t
    filled = [kept[0]]
    for t in kept[1:]:
        prev = filled[-1]
        n = int((t - prev) // fill)
        for i in range(1, n + 1):
            x = prev + (t - prev) * i / (n + 1)
            if t - x >= 4:
                filled.append(x)
        filled.append(t)
    return filled


def main():
    ap = argparse.ArgumentParser(description="按画面变化给录屏原片抽关键帧")
    ap.add_argument("inputs", nargs="+", help="原片目录或文件")
    ap.add_argument("--out", help="输出目录")
    ap.add_argument("--list", action="store_true", help="只盘点时长和分辨率，不抽帧")
    ap.add_argument("--threshold", type=float, default=0.08, help="画面变化阈值，默认 0.08")
    ap.add_argument("--gap", type=float, default=6.0, help="相邻两帧最小间隔秒数，默认 6")
    ap.add_argument("--delay", type=float, default=1.0, help="变化后延迟取帧秒数，默认 1")
    ap.add_argument("--fill", type=float, default=15.0, help="超过多少秒没变化就补帧，默认 15")
    ap.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg 可执行文件路径")
    args = ap.parse_args()

    videos = find_videos(args.inputs)
    if not videos:
        sys.exit("没有找到原片（支持 mp4、mov、m4v、mkv、webm、avi）")

    if args.list:
        print("| 原片 | 时长 | 分辨率 |")
        print("|---|---|---|")
        total = 0.0
        for rel, path in videos:
            p = probe(args.ffmpeg, path)
            if not p:
                print(f"| {rel} | 读不出 | |")
                continue
            duration, width, height = p
            total += duration
            size = f"{width}×{height}" if width else "未知"
            print(f"| {rel} | {int(duration // 60)}:{duration % 60:04.1f} | {size} |")
        print(f"\n共 {len(videos)} 段，合计 {total / 60:.1f} 分钟")
        return

    if not args.out:
        sys.exit("抽帧需要 --out 输出目录")
    out_root = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out_root, exist_ok=True)

    index = {}
    used = {}
    for rel, path in videos:
        p = probe(args.ffmpeg, path)
        if not p:
            print(f"{rel}: 读不出时长，跳过", file=sys.stderr)
            continue
        duration, width, height = p
        log = run_ffmpeg(
            args.ffmpeg,
            ["-i", path, "-vf", f"select='gt(scene,{args.threshold})',showinfo", "-vsync", "vfr", "-f", "null", "-"],
        ).stderr
        scenes = [float(x) for x in re.findall(r"pts_time:([\d.]+)", log)]
        times = pick_times(duration, scenes, args.gap, args.delay, args.fill)

        sub = os.path.dirname(rel)
        out_dir = os.path.join(out_root, sub)
        os.makedirs(out_dir, exist_ok=True)
        stem = re.sub(r"[^\w\-]+", "_", os.path.splitext(os.path.basename(rel))[0])[:30]
        key = (sub, stem)
        used[key] = used.get(key, 0) + 1
        if used[key] > 1:
            stem = f"{stem}_{used[key]}"

        frames = []
        for t in times:
            name = f"{stem}_t{t:06.1f}.jpg"
            result = run_ffmpeg(
                args.ffmpeg,
                ["-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-q:v", "3", os.path.join(out_dir, name)],
            )
            if result.returncode != 0:
                print(f"{rel}: {t:.1f}s 导出失败 {result.stderr.strip()[:200]}", file=sys.stderr)
                continue
            frames.append(name)
        index[rel] = {
            "path": path,
            "duration": round(duration, 1),
            "width": width,
            "height": height,
            "scenes": len(scenes),
            "dir": sub,
            "frames": frames,
        }
        print(f"{rel}: {duration:.0f}s，{len(scenes)} 个变化点，取 {len(frames)} 帧", flush=True)

    with open(os.path.join(out_root, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"共 {len(index)} 段，{sum(len(v['frames']) for v in index.values())} 帧，索引写在 {out_root}/index.json")


if __name__ == "__main__":
    main()
