#!/usr/bin/env python3
"""把 analyze_frames.py 的 accents.json 精简成工程用的 timing.json：小节起始帧、重音、段落。

用法：python make_timing.py <accents.json> <工程>/data/timing.json
帧号从 0 起，段落是 [start_frame, end_frame)；秒换帧用 floor(t*fps+0.5)，不重算节拍网格。
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    data = json.loads(src.read_text(encoding="utf-8"))
    fps = data["audio"]["fps"]
    q = lambda t: math.floor(t * fps + .5)
    timing = {
        "fps": fps, "duration_frames": data["audio"]["frames"],
        "audio_duration_seconds": data["audio"]["duration"],
        "frame_semantics": "zero-based; sections are [start_frame,end_frame); seconds quantized with floor(t*fps+0.5)",
        "bars": [q(b["start_t"]) for b in data["bars"]],
        "accents": [{k: a[k] for k in ("frame", "level", "bar", "beat_in_bar")} for a in data["accents"]],
        "sections": [{k: s[k] for k in ("start_frame", "end_frame", "label")} for s in data["sections"]],
        "grid": {k: data["grid"][k] for k in ("bpm", "t0", "beat_period") if k in data["grid"]},
        "source": str(src), "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(timing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    levels = {lv: sum(a["level"] == lv for a in timing["accents"]) for lv in ("heavy", "medium", "light")}
    print(f"{timing['duration_frames']} 帧，{len(timing['bars'])} 个小节，重音 {levels}，{len(timing['sections'])} 段 → {out}")


if __name__ == "__main__":
    main()
