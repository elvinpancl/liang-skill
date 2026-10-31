#!/usr/bin/env python3
"""聚焦框清晰度检查：每个聚焦框按它的放大倍数用 lanczos 放到 1920×1080，和原生裁区比拉普拉斯方差，标出放大后发虚的框。

用法：python zoom_check.py <shots.json> --clips <原片目录> [--out 目录] [--max-zoom 2.2] [--soft 0.25]

shots.json 每条：{"clip": "08", "focus": [{"label": "...", "rect": [x,y,w,h], "representative_time": 1.0}], ...}
原片按「<clip>_*.mp4」在 --clips 目录里找。
- zoom = 1920 / 框宽，超过 --max-zoom（默认 2.2）直接报出：录屏放太大会糊，框要放大到倍数以内且仍包住目标。
- 放大后方差 / 原生方差 < --soft（默认 0.25）标为偏糊，交给人看 zoom_check/ 里的图决定换框还是缩小倍数。
低分辨率素材不宜直接放大全屏，可采用卡片模式或更换源素材。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import laplace


def ffmpeg() -> str:
    found = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not found:
        raise SystemExit("找不到 ffmpeg")
    return found


def sharp(im: Image.Image) -> float:
    a = np.asarray(im.convert("L"), dtype=np.float64)
    return float(np.var(laplace(a, mode="reflect")[2:-2, 2:-2]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shots", type=Path)
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--max-zoom", type=float, default=2.2)
    ap.add_argument("--soft", type=float, default=.25)
    args = ap.parse_args()
    out = (args.out or args.shots.parent / "zoom_check").resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for shot in json.loads(args.shots.read_text(encoding="utf-8")):
        matches = sorted(args.clips.glob(f"{shot['clip']}_*.mp4"))
        if len(matches) != 1:
            rows.append({"clip": shot["clip"], "problem": f"原片匹配到 {len(matches)} 个文件"})
            continue
        for i, focus in enumerate(shot.get("focus", [])):
            x, y, w, h = (int(round(v)) for v in focus["rect"])
            t = focus.get("representative_time", (focus.get("t_range") or [shot.get("in", 0)])[0])
            frame = out / f"{shot['clip']}_F{i + 1}_原帧.png"
            subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(matches[0]),
                            "-frames:v", "1", str(frame)], check=True)
            big = out / f"{shot['clip']}_F{i + 1}_放大.png"
            subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(frame),
                            "-vf", f"crop={w}:{h}:{x}:{y},scale=1920:1080:flags=lanczos", "-frames:v", "1", str(big)],
                           check=True)
            native = sharp(Image.open(frame).crop((x, y, x + w, y + h)))
            ratio = sharp(Image.open(big)) / native if native else None
            zoom = 1920 / w
            rows.append({"clip": shot["clip"], "focus": i + 1, "label": focus.get("label", ""), "rect": [x, y, w, h],
                         "time": t, "zoom": round(zoom, 3), "too_big": zoom > args.max_zoom + 1e-9,
                         "sharpness_ratio": None if ratio is None else round(ratio, 3),
                         "soft": ratio is not None and ratio < args.soft, "image": str(big)})
    (out / "zoom_check.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    flagged = [r for r in rows if r.get("too_big") or r.get("soft") or r.get("problem")]
    print(f"聚焦框 {sum('focus' in r for r in rows)} 个，要看的 {len(flagged)} 个：{out}")
    for r in flagged:
        why = r.get("problem") or ("放大超过上限" if r["too_big"] else "") + ("偏糊" if r.get("soft") else "")
        print(f"  {r['clip']} F{r.get('focus', '')} {r.get('label', '')}：{why}（zoom {r.get('zoom')}）")


if __name__ == "__main__":
    main()
