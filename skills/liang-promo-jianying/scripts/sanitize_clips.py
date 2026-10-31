#!/usr/bin/env python3
"""按计划切取录屏片段，把敏感区域打码烧进去，两头留余量；从不修改原片。

用法：python sanitize_clips.py <clips.json> [--jobs 2] [--force]

clips.json（相对路径都相对于这个文件所在目录）：
{
  "fps": 30,
  "out_dir": "素材",
  "source_size": [1920, 1056],          # 可选，给了就校验原片尺寸；单个 clip 也可以写自己的 source_size
  "shots": "../取证/shots.json",         # 可选，liang-promo-beat 取证产物；clip 带 "shot" 时取它的 sensitive
  "mask": {"sigma": 32, "steps": 3, "dark": 0.35},
  "global_masks": [{"rect": [0,42,1920,46], "reason": "地址栏", "clips": ["08","09"]}],
  "clips": [
    {"id": "01", "src": "原片/01.mp4", "in_s": 0.0, "out_s": 3.4, "handles_s": 1.0, "shot": "01",
     "masks": [{"rect": [x,y,w,h], "t": [a,b], "reason": "..."}],
     "crop": {"rect": [x,y,w,h], "scale_to": [860,488], "name": "生成视频_16_待替换原片"}}
  ]
}

- 时间都是原片秒数，区间左闭右开；打码时间也是原片秒数。
- 打码做法：强高斯模糊 + 约 35% 暗色，读起来是「被模糊的文字」，不是黑色色块，原文不可辨认。
- 输出 <out_dir>/录屏_<id>_已打码.mp4；有 crop 时另出裁切放大版（用 lanczos），草稿里引用裁切版。
- 清单 <out_dir>/sanitize_manifest.json：story_frames 是计划要用的帧数，story_last_frame_in_output
  是最后一帧在输出里的帧号。草稿只用 story_frames，不够时在这一帧定格，不往余量里多播。
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jy_common


def time_str(value: float) -> str:
    return f"{value:.9f}".rstrip("0").rstrip(".") or "0"


def collect_masks(clip: dict, shots: dict, global_masks: list, start_s: float, end_s: float) -> list[dict]:
    raw = [dict(m, kind="plan") for m in clip.get("masks", [])]
    if clip.get("shot") and clip["shot"] in shots:
        for m in shots[clip["shot"]].get("sensitive", []):
            raw.append({"rect": m["rect"], "t": m["t_range"], "reason": m.get("reason", ""), "kind": "shots"})
    for g in global_masks:
        if clip["id"] in g.get("clips", []) or clip.get("shot") in g.get("clips", []):
            raw.append({"rect": g["rect"], "t": g.get("t", [start_s, end_s]), "reason": g.get("reason", ""),
                        "kind": "global"})
    result = []
    for m in raw:
        a, b = max(start_s, m["t"][0]), min(end_s, m["t"][1])
        if a < b:
            result.append({"kind": m["kind"], "reason": m.get("reason", ""), "rect": [int(v) for v in m["rect"]],
                           "source_t": m["t"], "output_t": [a - start_s, b - start_s],
                           "check_output_s": (a + b) / 2 - start_s})
    return result


def drop_covered(masks: list[dict]) -> list[dict]:
    """去掉被更大矩形在整个时段完全盖住的规则；原规则仍全部写进清单。"""
    chosen = []
    for i, m in enumerate(masks):
        x, y, w, h = m["rect"]
        a, b = m["output_t"]
        covered = False
        for j, o in enumerate(masks):
            if i == j:
                continue
            ox, oy, ow, oh = o["rect"]
            oa, ob = o["output_t"]
            if ox <= x and oy <= y and ox + ow >= x + w and oy + oh >= y + h and oa <= a and ob >= b:
                if (ox, oy, ow, oh, oa, ob) != (x, y, w, h, a, b) or j > i:
                    covered = True
                    break
        if not covered:
            chosen.append(m)
    return chosen


def filter_graph(start_frame: int, end_frame: int, masks: list[dict], recipe: dict) -> str:
    lines = [f"[0:v]trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS,setsar=1[v0]"]
    for i, m in enumerate(masks):
        x, y, w, h = m["rect"]
        a, b = m["output_t"]
        # 转成 yuv444p 再裁，避免 4:2:0 把奇数坐标取偶，打码框逐像素落在标注位置。
        lines += [f"[v{i}]split=2[keep{i}][region{i}]",
                  f"[region{i}]format=yuv444p,crop={w}:{h}:{x}:{y},"
                  f"gblur=sigma={recipe['sigma']}:steps={recipe['steps']},"
                  f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{recipe['dark']}:t=fill[blur{i}]",
                  f"[keep{i}][blur{i}]overlay=x={x}:y={y}:format=yuv444:"
                  f"enable='gte(t,{time_str(a)})*lt(t,{time_str(b)})'[v{i + 1}]"]
    lines.append(f"[v{len(masks)}]format=yuv420p[out]")
    return ";\n".join(lines)


def encode(args: list[str], target: Path, fps: int) -> None:
    pending = target.with_name(target.stem + ".partial.mp4")
    jy_common.run([jy_common.ffmpeg_bin(), "-y", "-hide_banner", "-nostdin", "-loglevel", "error", *args,
                   "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-threads", "2",
                   "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(pending)])
    pending.replace(target)


def process(clip: dict, ctx: dict) -> dict:
    fps, base, out_dir = ctx["fps"], ctx["base"], ctx["out_dir"]
    source = jy_common.resolve(base, clip["src"])
    info = jy_common.probe_video(source)
    size = clip.get("source_size", ctx["source_size"])
    if size and [info["width"], info["height"]] != list(size):
        raise RuntimeError(f"原片尺寸和计划不符，坐标要重新核对：{source} {info}")
    if abs(info["fps"] - fps) > 1e-3:
        raise RuntimeError(f"原片帧率不是 {fps}：{source} {info['fps']}")
    if clip["out_s"] > info["frames"] / fps + 1e-6:
        raise ValueError(f"出点超出原片：{clip['id']}")
    handles = float(clip.get("handles_s", 1.0))
    start_frame = max(0, round(clip["in_s"] * fps) - round(handles * fps))
    end_frame = min(info["frames"], round(clip["out_s"] * fps) + round(handles * fps))
    start_s, end_s = start_frame / fps, end_frame / fps
    masks = collect_masks(clip, ctx["shots"], ctx["global_masks"], start_s, end_s)
    rendered = drop_covered(masks)
    full = (out_dir / f"录屏_{clip['id']}_已打码.mp4").resolve()
    crop = clip.get("crop")
    output = (out_dir / f"{crop['name']}.mp4").resolve() if crop else full
    fingerprint = {"source_sha256": jy_common.sha256(source), "script_sha256": ctx["script_sha"],
                   "clip": clip, "shots_sha256": ctx["shots_sha"], "mask": ctx["recipe"]}
    old = ctx["old"].get(clip["id"], {})
    hit = not ctx["force"] and old.get("fingerprint") == fingerprint and full.exists() and output.exists()
    if not hit:
        graph = ctx["graph_dir"] / f"{clip['id']}.ffgraph"
        graph.write_text(filter_graph(start_frame, end_frame, rendered, ctx["recipe"]), encoding="utf-8")
        encode(["-threads", "2", "-i", str(source), "-filter_complex_threads", "1",
                "-filter_complex_script", str(graph), "-map", "[out]"], full, fps)
        if crop:
            x, y, w, h = crop["rect"]
            sw, sh = crop.get("scale_to", [w, h])
            encode(["-threads", "2", "-i", str(full), "-vf",
                    f"format=yuv444p,crop={w}:{h}:{x}:{y},scale={sw}:{sh}:flags=lanczos,setsar=1"], output, fps)
    out_info = jy_common.probe_video(output)
    expected = end_frame - start_frame
    if out_info["frames"] != expected or out_info["audio_streams"]:
        raise AssertionError(f"输出帧数或音轨不符：{clip['id']} {out_info}，预期 {expected} 帧无音轨")
    source_in = round(clip["in_s"] * fps) - start_frame
    story = round(clip["out_s"] * fps) - round(clip["in_s"] * fps)
    print(f"{'复用' if hit else '完成'} {clip['id']}：{expected} 帧，原片 {start_s:.3f}–{end_s:.3f}s，"
          f"打码 {len(rendered)} 处", flush=True)
    return {"id": clip["id"], "path": str(output), "sanitized_full_path": str(full), "source": str(source),
            "source_start_frame": start_frame, "source_end_frame": end_frame,
            "source_in_frames": source_in, "story_frames": story,
            "story_last_frame_in_output": source_in + story - 1, "frames": out_info["frames"],
            "width": out_info["width"], "height": out_info["height"], "crop": crop,
            "masks": masks, "rendered_mask_count": len(rendered), "fingerprint": fingerprint,
            "output_sha256": jy_common.sha256(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--force", action="store_true", help="忽略缓存全部重做")
    args = parser.parse_args()
    plan_path = args.plan.resolve()
    plan = jy_common.load_json(plan_path)
    base = plan_path.parent
    out_dir = jy_common.resolve(base, plan.get("out_dir", "素材"))
    out_dir.mkdir(parents=True, exist_ok=True)
    graph_dir = out_dir / "制作过程" / "打码滤镜"
    graph_dir.mkdir(parents=True, exist_ok=True)
    shots_path = jy_common.resolve(base, plan.get("shots"))
    shots = {s["clip"]: s for s in jy_common.load_json(shots_path)} if shots_path else {}
    manifest_path = out_dir / "sanitize_manifest.json"
    old = {c["id"]: c for c in jy_common.load_json(manifest_path).get("clips", [])} if manifest_path.exists() else {}
    ctx = {"fps": int(plan.get("fps", 30)), "base": base, "out_dir": out_dir, "graph_dir": graph_dir,
           "source_size": plan.get("source_size"), "shots": shots, "global_masks": plan.get("global_masks", []),
           "recipe": {"sigma": 32, "steps": 3, "dark": .35, **plan.get("mask", {})}, "old": old,
           "force": args.force, "script_sha": jy_common.sha256(__file__),
           "shots_sha": jy_common.sha256(shots_path) if shots_path else None}
    with ThreadPoolExecutor(max_workers=max(1, min(4, args.jobs))) as pool:
        clips = list(pool.map(lambda c: process(c, ctx), plan["clips"]))
    jy_common.save_json(manifest_path, {"schema": "liang-promo-jianying/sanitize-1", "fps": ctx["fps"],
                                        "mask_recipe": ctx["recipe"], "clips": clips})
    print(f"清单：{manifest_path}")


if __name__ == "__main__":
    main()
