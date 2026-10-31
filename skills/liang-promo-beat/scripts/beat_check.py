#!/usr/bin/env python3
"""卡点回测：连续解码成片，按相邻帧差找画面变化峰，对照故事板锚点，看切点是不是落在该落的那一帧。

用法：python beat_check.py <成片.mp4> --anchors anchors.json [--out-dir 目录] [--fps 30] [--audio]

anchors.json：
{"sections": [["F1", 0, 222], ["F2", 222, 665]],
 "anchors": [{"frame": 42, "kind": "S", "desc": "切入「写下来」整词砸入"},
             {"frame": 250, "kind": "R", "desc": "推到故事输入框"}]}
- S：切点、转场、闪光、砸字这类全画面突变，必须在 ±1 帧内找到独立的帧差峰，否则失败。
- R：运镜落位、卡片停靠、文字出现这类局部变化，帧差证明不了，列出来人工看锚点拼图。
- N：只抽帧看，不计通过。

方法：
- 帧差 D[f] = 第 f−1 帧和第 f 帧在 480×270 下的 RGB 平均绝对差。
- 先在全片独立找峰（幅度 ≥ 0.006，左右 15 帧内显著度 ≥ 0.003），找峰时不看故事板。
- 每个 S 锚点在 ±16 帧窗口里取最强峰；相邻 S 锚点不足 32 帧时，窗口在中点切开，一个峰不会替两个锚点作证。
- 最强峰离锚点超过 1 帧、峰是一段长平台、或窗口里有同样强（≥95%）的另一个峰，都算失败。
输出：卡点回测.md、beat_check.json、frame_diffs.csv、每段一张锚点拼图。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

METRIC = (480, 270)
RADIUS = 16
MIN_AMPLITUDE, MIN_PROMINENCE = 0.006, 0.003


def ffmpeg() -> str:
    import os
    found = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("找不到 ffmpeg")
    return found


def find_font() -> str | None:
    for name in ("Lantinghei.ttc", "STHeiti Medium.ttc", "PingFang.ttc", "Arial Unicode.ttf"):
        for root in (Path("/System/Library/AssetsV2"), Path("/System/Library/Fonts"), Path("/Library/Fonts")):
            hits = [p for p in root.rglob(name) if "Subsets" not in p.parts] if root.is_dir() else []
            if hits:
                return str(max(hits, key=lambda p: p.stat().st_size))
    return None


def decode(video: Path, keep: set[int]) -> tuple[list[float | None], dict[int, Image.Image], tuple[int, int]]:
    probe = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(video)], capture_output=True, text=True).stderr
    line = next((l for l in probe.splitlines() if "Video:" in l), "")
    import re
    m = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
    if not m:
        raise RuntimeError("读不出视频尺寸")
    w, h = int(m[1]), int(m[2])
    proc = subprocess.Popen([ffmpeg(), "-nostdin", "-v", "error", "-i", str(video), "-map", "0:v:0", "-an",
                             "-vsync", "passthrough", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                            stdout=subprocess.PIPE)
    size, diffs, pictures, previous, n = w * h * 3, [], {}, None, 0
    while True:
        raw = proc.stdout.read(size)
        if not raw:
            break
        if len(raw) != size:
            raise RuntimeError("最后一帧数据不完整")
        image = Image.frombytes("RGB", (w, h), raw)
        rgb = np.asarray(image.resize(METRIC, Image.Resampling.BOX), dtype=np.float32) / 255.0
        diffs.append(None if previous is None else float(np.abs(rgb - previous).mean()))
        previous = rgb
        if n in keep:
            pictures[n] = image.resize((480, 270), Image.Resampling.LANCZOS)
        n += 1
    if proc.wait():
        raise RuntimeError("ffmpeg 解码失败")
    return diffs, pictures, (w, h)


def detect_peaks(values: list[float | None]) -> list[dict]:
    arr = np.array([0.0 if v is None else v for v in values], dtype=float)
    peaks, i = [], 1
    while i < len(arr) - 1:
        end = i
        while end + 1 < len(arr) and abs(arr[end + 1] - arr[i]) < 1e-9:
            end += 1
        if end + 1 < len(arr) and arr[i] > arr[i - 1] and arr[end] > arr[end + 1]:
            left, right = arr[max(1, i - 15):i], arr[end + 1:min(len(arr), end + 16)]
            if len(right):
                base = max(float(left.min()) if len(left) else 0.0, float(right.min()))
                prominence = float(arr[i] - base)
                if arr[i] >= MIN_AMPLITUDE and prominence >= MIN_PROMINENCE:
                    peaks.append({"frame": i, "diff": float(arr[i]), "prominence": prominence, "plateau_end": end})
        i = end + 1
    return peaks


def match(peaks: list[dict], target: int, targets: list[int], last: int) -> dict:
    index = targets.index(target)
    lo, hi = max(1, target - RADIUS), min(last, target + RADIUS)
    if index:
        lo = max(lo, (targets[index - 1] + target) // 2 + 1)
    if index + 1 < len(targets):
        hi = min(hi, (target + targets[index + 1]) // 2)
    cands = sorted((p for p in peaks if lo <= p["frame"] <= hi), key=lambda p: (-p["diff"], -p["prominence"], p["frame"]))
    if not cands:
        return {"status": "失败", "observed": None, "error": None, "window": [lo, hi], "reason": "窗口里没有显著的画面变化峰"}
    best = cands[0]
    ambiguous = [p for p in cands[1:] if abs(p["frame"] - target) > 1 and p["diff"] >= best["diff"] * .95]
    ok = abs(best["frame"] - target) <= 1 and abs(best["plateau_end"] - target) <= 1 and not ambiguous
    return {"status": "通过" if ok else "失败", "observed": best["frame"], "error": best["frame"] - target, "window": [lo, hi],
            "reason": "最强峰在 ±1 帧内" if ok else "最强峰偏离超过 1 帧、峰平台太宽，或有同样强的另一个峰"}


def sheets(pictures: dict, anchors: list[dict], sections: list, out: Path) -> list[str]:
    font_path = find_font()
    font = ImageFont.truetype(font_path, 21) if font_path else ImageFont.load_default()
    files = []
    for name, start, end in sections:
        rows = [a for a in anchors if start <= a["frame"] < end and a["frame"] in pictures]
        if not rows:
            continue
        cols, tw, th = 4, 480, 310
        sheet = Image.new("RGB", (cols * tw, math.ceil(len(rows) / cols) * th), "#0b0a09")
        draw = ImageDraw.Draw(sheet)
        for i, a in enumerate(rows):
            x, y = i % cols * tw, i // cols * th
            sheet.paste(pictures[a["frame"]], (x, y))
            mark = {"通过": "#7ee787", "失败": "#ff7a5c"}.get(a.get("status"), "#ffd98e")
            draw.text((x + 8, y + 276), f"F{a['frame']} {a['kind']} {a.get('status', '')} {a['desc']}"[:34], fill=mark, font=font)
        path = out / f"锚点帧_{name}.jpg"
        sheet.save(path, quality=86)
        files.append(str(path))
    return files


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--anchors", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--frames", type=int, help="期望总帧数")
    args = ap.parse_args()
    spec = json.loads(args.anchors.read_text(encoding="utf-8"))
    anchors = [dict(a) for a in spec["anchors"]]
    out = (args.out_dir or args.video.parent).resolve()
    out.mkdir(parents=True, exist_ok=True)
    diffs, pictures, size = decode(args.video.resolve(), {a["frame"] for a in anchors})
    total = len(diffs)
    sections = spec.get("sections") or [["全片", 0, total]]
    peaks = detect_peaks(diffs)
    strict = sorted({a["frame"] for a in anchors if a["kind"] == "S"})
    for a in anchors:
        if a["kind"] == "S":
            a.update(match(peaks, a["frame"], strict, total - 2))
        elif a["kind"] == "R":
            near = sorted((p for p in peaks if abs(p["frame"] - a["frame"]) <= RADIUS), key=lambda p: -p["diff"])[:3]
            a.update(status="人工看", nearby_peaks=near)
        else:
            a.update(status="抽样")
    files = sheets(pictures, anchors, sections, out)
    with (out / "frame_diffs.csv").open("w", newline="") as h:
        w = csv.writer(h)
        w.writerow(["frame", "diff", "peak"])
        peak_frames = {p["frame"] for p in peaks}
        for i, d in enumerate(diffs):
            w.writerow([i, "" if d is None else f"{d:.6f}", int(i in peak_frames)])
    passed = sum(a.get("status") == "通过" for a in anchors)
    failed = [a for a in anchors if a.get("status") == "失败"]
    problems = []
    if args.frames and total != args.frames:
        problems.append(f"解码得到 {total} 帧，期望 {args.frames} 帧")
    result = {"video": str(args.video), "size": size, "frames": total, "strict": len(strict), "passed": passed,
              "failed": len(failed), "problems": problems, "anchors": anchors, "sheets": files}
    (out / "beat_check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# 卡点回测\n", f"成片：`{args.video.name}`，{total} 帧。严格切点 {len(strict)} 个，通过 {passed} 个，失败 {len(failed)} 个。\n"]
    lines += [f"- {p}" for p in problems]
    lines += ["\n| 帧 | 类型 | 动作 | 实测峰 | 误差帧 | 结果 |", "|---:|---|---|---:|---:|---|"]
    for a in anchors:
        observed = "" if a.get("observed") is None else a["observed"]
        error = "" if a.get("error") is None else f"{a['error']:+d}"
        lines.append(f"| {a['frame']} | {a['kind']} | {a['desc']} | {observed} | {error} | {a['status']} |")
    lines.append("\n「人工看」的锚点在锚点拼图里逐张核对：运镜落位、停靠、文字出现，帧差证明不了。")
    (out / "卡点回测.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"严格切点 {len(strict)} 个：通过 {passed}，失败 {len(failed)}" + (f"；{'；'.join(problems)}" if problems else ""))
    for a in failed:
        print(f"  F{a['frame']} {a['desc']}：实测 {a['observed']}，误差 {a['error']}")
    raise SystemExit(1 if failed or problems else 0)


if __name__ == "__main__":
    main()
