#!/usr/bin/env python3
"""从整片底片按全片帧号切出烘焙段（3D 动效、开场、片尾这类剪映做不出来的段落）。

用法：
  python cut_segments.py --plate 底片/plate.mp4 --seg E1_开场:0:222 --seg E6_片尾:1773:2216 \
      [--segments segs.json] [--out-dir 素材] [--fps 30] [--size 1920x1080] [--total 2216] [--surrogate]

- 区间左闭右开。trim 按解码帧号切，不用关键帧流复制，也不用浮点秒定位；每段重新编码，再完整解码计帧核对。
- segs.json 是 [{"id": "E1", "name": "E1_开场", "start": 0, "end": 222}, ...]，和 --seg 二选一或合用。
- --surrogate 表示用旧成片当替身做流程自测：文件名带「_替身流程自测」，清单标 surrogate，
  build_draft 会继续标记，jy_install 拒绝安装。
- 清单写到 <out-dir>/segments_manifest.json。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import jy_common


def parse_seg(text: str) -> dict:
    name, start, end = text.rsplit(":", 2)
    return {"id": name.split("_", 1)[0], "name": name, "start": int(start), "end": int(end)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plate", required=True, type=Path)
    parser.add_argument("--seg", action="append", default=[], help="名字:起帧:止帧")
    parser.add_argument("--segments", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("素材"))
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--size", default="1920x1080")
    parser.add_argument("--total", type=int, help="底片应有的总帧数")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--surrogate", action="store_true")
    args = parser.parse_args()
    segments = [parse_seg(s) for s in args.seg]
    if args.segments:
        segments += jy_common.load_json(args.segments)
    if not segments:
        parser.error("至少给一段：--seg 或 --segments")
    plate = args.plate.resolve()
    width, height = (int(v) for v in args.size.lower().split("x"))
    probe = jy_common.probe_video(plate)
    if (probe["width"], probe["height"]) != (width, height) or abs(probe["fps"] - args.fps) > 1e-3:
        raise RuntimeError(f"底片规格不符：期望 {width}×{height} {args.fps} fps，实际 {probe}")
    if args.total and probe["frames"] != args.total:
        raise RuntimeError(f"底片帧数 {probe['frames']}，期望 {args.total}")
    if probe["audio_streams"] and not args.surrogate:
        raise RuntimeError("正式底片不该带音轨；BGM 在剪映里单独一轨")
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_替身流程自测" if args.surrogate else ""
    manifest = {"schema": "liang-promo-jianying/segments-1", "created_at": datetime.now(timezone.utc).isoformat(),
                "fps": args.fps, "surrogate": args.surrogate,
                "plate": {"path": str(plate), "sha256": jy_common.sha256(plate), "probe": probe}, "segments": []}
    for seg in segments:
        start, end = int(seg["start"]), int(seg["end"])
        if not 0 <= start < end <= probe["frames"]:
            raise ValueError(f"区间越界：{seg}")
        output = out_dir / f"{seg['name']}{suffix}.mp4"
        pending = output.with_name(output.stem + ".pending.mp4")
        jy_common.run([jy_common.ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                       "-i", str(plate), "-map", "0:v:0", "-an", "-sn", "-dn",
                       "-vf", f"trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS",
                       "-frames:v", str(end - start), "-r", str(args.fps), "-vsync", "cfr",
                       "-c:v", "libx264", "-preset", "fast", "-crf", str(args.crf),
                       "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(pending)])
        result = jy_common.probe_video(pending)
        if (result["frames"], result["width"], result["height"]) != (end - start, width, height):
            raise RuntimeError(f"{seg['name']} 切段核验失败：期望 {end - start} 帧，实际 {result}")
        pending.replace(output)
        manifest["segments"].append({"id": seg["id"], "name": seg["name"], "path": str(output),
                                     "start_frame": start, "end_frame": end, "frames": end - start,
                                     "sha256": jy_common.sha256(output)})
        print(f"{seg['name']}：[{start},{end}) = {end - start} 帧，已完整解码核对", flush=True)
    jy_common.save_json(out_dir / "segments_manifest.json", manifest)


if __name__ == "__main__":
    main()
