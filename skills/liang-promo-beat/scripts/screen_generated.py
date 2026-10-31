#!/usr/bin/env python3
"""AI 生成视频进片前的筛查：找出镜头切换，按镜头每 N 帧拼图给人逐张看，选好的取段检查离镜头边界够不够远。

用法：
  python screen_generated.py <视频> [--crop x,y,w,h] [--out-dir 目录] [--every 3]
  python screen_generated.py <视频> --crop ... --segments 62:90,101:142,280:321   # 再核对选好的取段

- 硬切判定：裁区灰度相邻帧差均值 ≥ 30（0–255）且 ffmpeg scene 分数 ≥ 0.3，两个独立检测同时越线才算。
  只换色相、亮度几乎不变的切换，灰度帧差会不够；彩色帧差 ≥ 30 而没判成硬切的帧列为「疑似切点」，要人看边界拼图确认。
  （不用 scene 分数做这一步：同一处换色，ffmpeg 6.1 给 0.22，2018 版给 0.96，随版本变。）
- 输出：生成视频筛查.json、逐帧差与场景分数 CSV、镜头边界拼图（每个切点前后 3 帧）、每个镜头每 N 帧一张拼图；
  给了 --segments 时再出重剪每 N 帧拼图。
- 判断标准（来自一次卡点展示片：55 秒处两只手交接戒指时手指互相穿过，用户要求「一定不要再出现」）：
  手部交互、物体贴脸、多人肢体接触的镜头一律不用；只用干净镜头；取段离镜头边界至少 2 帧；切点落在拍点上。
  脚本只负责找边界和出图，能不能用由人（或你）逐张看拼图决定，结论写进 JSON 的 shots[].usable。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 30


def ffmpeg() -> str:
    found = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("找不到 ffmpeg")
    return found


def call(argv, **kw):
    proc = subprocess.run(argv, capture_output=True, **kw)
    if proc.returncode:
        err = proc.stderr.decode(errors="replace") if isinstance(proc.stderr, bytes) else proc.stderr
        raise RuntimeError(f"命令失败：{argv}\n{err[-3000:]}")
    return proc


def size_of(path: Path) -> tuple[int, int]:
    # ffmpeg -i 不给输出文件时退出码非 0，所以不用 call()
    probe = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    line = next(l for l in probe.splitlines() if "Video:" in l)
    m = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
    return int(m[1]), int(m[2])


def decode(path: Path, crop, size=None, gray=False) -> np.ndarray:
    filters = ["format=yuv444p"]
    if crop:
        x, y, w, h = crop
        filters.append(f"crop={w}:{h}:{x}:{y}")
    if size:
        filters.append(f"scale={size[0]}:{size[1]}:flags=lanczos")
    filters.append("format=gray" if gray else "format=rgb24")
    raw = call([ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf", ",".join(filters),
                "-an", "-f", "rawvideo", "-"]).stdout
    w, h = size or (crop[2:] if crop else size_of(path))
    return np.frombuffer(raw, np.uint8).reshape((-1, h, w) if gray else (-1, h, w, 3))


def font():
    for name in ("Lantinghei.ttc", "STHeiti Medium.ttc", "PingFang.ttc"):
        for root in (Path("/System/Library/AssetsV2"), Path("/System/Library/Fonts")):
            hits = [p for p in root.rglob(name) if "Subsets" not in p.parts] if root.is_dir() else []
            if hits:
                return ImageFont.truetype(str(max(hits, key=lambda p: p.stat().st_size)), 17)
    return ImageFont.load_default()


def sheet(frames: np.ndarray, refs: list[tuple[int, str]], path: Path, heading: str, cols: int = 6) -> str:
    tw, th = 258, 146
    cw, chh = tw + 12, th + 42
    rows = (len(refs) + cols - 1) // cols
    im = Image.new("RGB", (cols * cw + 12, rows * chh + 54), "#0b0a09")
    d, f = ImageDraw.Draw(im), font()
    d.text((12, 10), heading, fill="#ffd98e", font=f)
    for i, (frame, label) in enumerate(refs):
        x, y = 12 + i % cols * cw, 44 + i // cols * chh
        im.paste(Image.fromarray(frames[frame]).resize((tw, th), Image.Resampling.LANCZOS), (x, y))
        d.text((x, y + th + 4), label, fill="#f6f0e6", font=f)
    im.save(path, quality=92)
    return str(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--crop", help="x,y,w,h：生成视频只占录屏一部分时，只看这个区域")
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--diff", type=float, default=30)
    ap.add_argument("--scene", type=float, default=.3)
    ap.add_argument("--segments", help="起:止,起:止（源帧，左闭右开），核对选好的取段")
    ap.add_argument("--margin", type=int, default=2)
    args = ap.parse_args()
    video = args.video.resolve()
    crop = [int(v) for v in args.crop.split(",")] if args.crop else None
    out = (args.out_dir or video.parent / f"{video.stem}_筛查").resolve()
    out.mkdir(parents=True, exist_ok=True)
    gray = decode(video, crop, gray=True)
    diffs = np.r_[0., np.abs(gray[1:].astype(np.float32) - gray[:-1].astype(np.float32)).mean(axis=(1, 2))]
    vf = (f"format=yuv444p,crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}," if crop else "") + "select='gte(scene,0)',metadata=print"
    log = call([ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "info", "-i", str(video), "-vf", vf, "-an", "-f", "null", "-"],
               text=True).stderr
    scores, pending = {}, None
    for line in log.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            pending = round(float(m[1]) * FPS)
        m = re.search(r"lavfi.scene_score=([0-9.]+)", line)
        if m and pending is not None:
            scores[pending] = float(m[1])
    total = len(gray)
    cuts = [i for i in range(1, total) if diffs[i] >= args.diff and scores.get(i, 0) >= args.scene]
    rgb = decode(video, crop, size=(430, 244))
    color = np.r_[0., np.abs(rgb[1:].astype(np.float32) - rgb[:-1].astype(np.float32)).mean(axis=(1, 2, 3))]
    maybe = [i for i in range(1, total) if i not in cuts and color[i] >= args.diff]
    bounds = [0, *cuts, total]
    shots = [{"id": chr(65 + i) if i < 26 else f"S{i}", "start_frame": a, "end_frame": b, "usable": None, "note": ""}
             for i, (a, b) in enumerate(zip(bounds, bounds[1:]))]
    with (out / "逐帧差与场景分数.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["frame", "seconds", "luma_diff", "color_diff", "scene_score", "is_cut"])
        for i in range(total):
            w.writerow([i, f"{i / FPS:.6f}", f"{diffs[i]:.4f}", f"{color[i]:.4f}", scores.get(i, 0), int(i in cuts)])
    sheets = []
    if cuts or maybe:
        refs = [(b + k, f"切点 {b} | 帧 {b + k}") for b in cuts for k in range(-3, 3) if 0 <= b + k < total]
        refs += [(b + k, f"疑似 {b} | 帧 {b + k}") for b in maybe for k in range(-3, 3) if 0 <= b + k < total]
        sheets.append(sheet(rgb, refs, out / "镜头边界拼图.jpg", "每行一个切点，切点帧属于新镜头"))
    for s in shots:
        refs = [(i, f"{s['id']} | 帧 {i} | {i / FPS:.2f}s") for i in range(s["start_frame"], s["end_frame"], args.every)]
        sheets.append(sheet(rgb, refs, out / f"镜头{s['id']}_每{args.every}帧.jpg",
                            f"镜头 {s['id']} [{s['start_frame']},{s['end_frame']})：逐张看手部、贴脸、肢体穿插"))
    result = {"video": str(video), "crop": crop, "fps": FPS, "frames": total, "cuts": cuts, "maybe_cuts": maybe, "shots": shots,
              "thresholds": {"luma_diff": args.diff, "scene": args.scene}, "sheets": sheets,
              "rule": "手部交互、物体贴脸、多人肢体接触的镜头不用；取段离镜头边界至少 2 帧；切点落在拍点上"}
    problems = []
    if args.segments:
        picks = []
        for part in args.segments.split(","):
            a, b = (int(v) for v in part.split(":"))
            shot = next((s for s in shots if s["start_frame"] <= a < s["end_frame"]), None)
            ok = shot is not None and b <= shot["end_frame"] and a - shot["start_frame"] >= args.margin \
                and shot["end_frame"] - b >= args.margin
            if not ok:
                problems.append(f"取段 [{a},{b}) 跨了镜头边界或离边界不足 {args.margin} 帧")
            picks.append({"start": a, "end": b, "shot": shot["id"] if shot else None, "ok": ok})
        edited = np.concatenate([rgb[p["start"]:p["end"]] for p in picks])
        index = [i for p in picks for i in range(p["start"], p["end"])]
        refs = [(i, f"成片第 {i} 帧 | 源 {index[i]}") for i in range(0, len(edited), args.every)]
        sheets.append(sheet(edited, refs, out / f"重剪每{args.every}帧.jpg", f"选好的取段拼起来，每 {args.every} 帧一张"))
        result["segments"] = picks
    result["problems"] = problems
    (out / "生成视频筛查.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{total} 帧，硬切 {cuts}；{len(shots)} 个镜头：" +
          "，".join(f"{s['id']}[{s['start_frame']},{s['end_frame']})" for s in shots))
    if maybe:
        print(f"疑似切点 {maybe}（色相变了、亮度没怎么变），看镜头边界拼图确认，是切点就把取段避开")
    print(f"拼图 {len(sheets)} 张：{out}")
    for p in problems:
        print("  问题：" + p)
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
