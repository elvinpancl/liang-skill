#!/usr/bin/env python3
"""按剪辑台本切片，拼出粗剪。

每一行台本切成一个单镜头片段（去声音、统一 60 帧、可加速、可打码），按序号命名，直接拖进剪映。
另拼一条低清预览片，带叠化和闪黑，用来看节奏；字幕稿按预览片的时间轴排。

用法：
  python3 build_roughcut.py <剪辑台本.md> --src <原片根目录> --out <本篇目录> [参数]

台本表格的列（表头文字要一致，多余的列会被忽略）：
  必需：原片、入点、出点
  可选：序号、段落、身份、速度、转场、放大、打码、旁白、音效、备注
  - 入点、出点：原片里的时间，写「1:05.5」或「65.5」。
  - 速度：1、2、4，也可以写「2x」「2倍」。默认 1。
  - 转场：进入这一镜头的方式，「切」「叠化」「闪黑」。默认切。只做进预览片，单镜头片段保持干净。
  - 放大：「左上」「右上」「左下」「右下」「中心」「上半」「下半」「左半」「右半」，或「x,y,w,h」比例坐标。
          后面加「推」表示开头 0.5 秒推近。放大只输出到「粗剪/放大备选/」，不烧进主片段。
  - 打码：「x,y,w,h」比例坐标，多处用分号隔开；后面可加「@1:02-1:05」只在原片这段时间内打码。
          打码直接烧进主片段，避免漏到成片里。坐标可以从镜头索引的识别结果里抄。

输出：
  <本篇目录>/粗剪/NN_段落.mp4
  <本篇目录>/粗剪/放大备选/NN_段落_放大.mp4
  <本篇目录>/粗剪预览.mp4
  <本篇目录>/制作过程/粗剪索引.json   每段在预览片里的起止，字幕排时要用
"""

import argparse
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # 不在 skill 目录里留 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

REGIONS = {
    "左上": (0, 0, 0.5, 0.5), "右上": (0.5, 0, 0.5, 0.5), "左下": (0, 0.5, 0.5, 0.5),
    "右下": (0.5, 0.5, 0.5, 0.5), "中心": (0.25, 0.25, 0.5, 0.5), "上半": (0, 0, 1, 0.5),
    "下半": (0, 0.5, 1, 0.5), "左半": (0, 0, 0.5, 1), "右半": (0.5, 0, 0.5, 1),
}


def parse_speed(text):
    text = (text or "").strip().lower().replace("倍", "").replace("x", "").replace("×", "")
    if not text:
        return 1.0
    value = float(text)
    if value <= 0:
        raise ValueError("速度要大于 0")
    return value


def parse_rect(text):
    text = text.strip()
    if text in REGIONS:
        return REGIONS[text]
    parts = [float(x) for x in re.split(r"[,，\s]+", text) if x]
    if len(parts) != 4:
        raise ValueError(f"区域写法不对：{text}")
    x, y, w, h = parts
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1):
        raise ValueError(f"区域超出画面：{text}")
    return x, y, w, h


def parse_zoom(text):
    text = (text or "").strip()
    if not text:
        return None
    push = text.endswith("推")
    if push:
        text = text[:-1].strip()
    return parse_rect(text), push


def parse_masks(text):
    out = []
    for part in re.split(r"[;；]", text or ""):
        part = part.strip()
        if not part:
            continue
        window = None
        if "@" in part:
            part, w = part.split("@", 1)
            a, b = re.split(r"\s*[-–~]\s*", w.strip(), maxsplit=1)
            window = (C.parse_time(a), C.parse_time(b))
        out.append((parse_rect(part), window))
    return out


def crop_box(rect, W, H, max_zoom=3.0):
    """把区域扩成和画面同比例的裁切框，返回像素坐标 (cw, ch, cx, cy) 和放大倍数。"""
    x, y, w, h = rect
    aspect = W / H
    rw, rh = w * W, h * H
    if rw / rh > aspect:
        cw, ch = rw, rw / aspect
    else:
        cw, ch = rh * aspect, rh
    cw, ch = max(cw, W / max_zoom), max(ch, H / max_zoom)
    cw, ch = min(cw, W), min(ch, H)
    cx = min(max(x * W + rw / 2 - cw / 2, 0), W - cw)
    cy = min(max(y * H + rh / 2 - ch / 2, 0), H - ch)
    even = lambda v: int(v) // 2 * 2
    return even(cw), even(ch), even(cx), even(cy), W / cw


def mask_filters(masks, W, H, start, speed, label_in="base"):
    """在 [label_in] 上叠马赛克块，返回 (滤镜串, 输出标签)。时间窗口按原片时间给，换算到输出时间。"""
    if not masks:
        return [], label_in
    chains, cur = [], label_in
    for i, (rect, window) in enumerate(masks):
        x, y, w, h = rect
        px, py = int(x * W) // 2 * 2, int(y * H) // 2 * 2
        pw, ph = max(int(w * W) // 2 * 2, 8), max(int(h * H) // 2 * 2, 8)
        enable = ""
        if window:
            a, b = (window[0] - start) / speed, (window[1] - start) / speed
            enable = f":enable='between(t,{max(a, 0):.3f},{max(b, 0):.3f})'"
        chains.append(f"[{cur}]split[m{i}a][m{i}b]")
        # 马赛克：缩到 1/16 再用最近邻放大，任何尺寸的框都能用，字也认不出来
        sw, sh = max(2, pw // 16 // 2 * 2), max(2, ph // 16 // 2 * 2)
        chains.append(f"[m{i}b]crop={pw}:{ph}:{px}:{py},scale={sw}:{sh},scale={pw}:{ph}:flags=neighbor[m{i}c]")
        chains.append(f"[m{i}a][m{i}c]overlay={px}:{py}{enable}[m{i}o]")
        cur = f"m{i}o"
    return chains, cur


def encode(args_list):
    result = C.run_ffmpeg(["-loglevel", "error", "-y", *args_list])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-800:])


def main():
    ap = argparse.ArgumentParser(description="按剪辑台本切片，拼出粗剪")
    ap.add_argument("script", help="剪辑台本（Markdown 表格）")
    ap.add_argument("--src", action="append", default=[], help="原片根目录，可以给多个")
    ap.add_argument("--out", required=True, help="本篇目录")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--dissolve", type=float, default=0.5, help="叠化时长，默认 0.5 秒")
    ap.add_argument("--flash", type=float, default=0.15, help="闪黑单边时长，默认 0.15 秒")
    ap.add_argument("--preview-size", default="960x540")
    ap.add_argument("--no-preview", action="store_true", help="不拼预览片")
    ap.add_argument("--only", help="只重做这些序号，例如 3,5,8")
    args = ap.parse_args()

    header, rows = C.pick_table(args.script, ["原片", "入点", "出点"])
    if not rows:
        sys.exit("台本里没找到含「原片」「入点」「出点」三列的表格")
    out_dir = os.path.abspath(os.path.expanduser(args.out))
    clip_dir = os.path.join(out_dir, "粗剪")
    zoom_dir = os.path.join(clip_dir, "放大备选")
    proc_dir = os.path.join(out_dir, "制作过程")
    for d in (clip_dir, proc_dir):
        os.makedirs(d, exist_ok=True)
    srcs = [os.path.abspath(os.path.expanduser(s)) for s in args.src] or [os.path.dirname(os.path.abspath(args.script))]
    only = {int(x) for x in args.only.split(",")} if args.only else None

    shots, problems = [], []
    for n, row in enumerate(rows, 1):
        if not row.get("原片", "").strip():
            continue
        no = int(row["序号"]) if row.get("序号", "").strip().isdigit() else n
        src = row["原片"].strip().strip("`")
        path = src if os.path.isabs(src) else next((os.path.join(r, src) for r in srcs
                                                    if os.path.exists(os.path.join(r, src))), None)
        if not path or not os.path.exists(path):
            problems.append(f"第 {no} 行找不到原片：{src}")
            continue
        info = C.probe(path)
        try:
            t_in, t_out = C.parse_time(row["入点"]), C.parse_time(row["出点"])
            speed = parse_speed(row.get("速度"))
            zoom = parse_zoom(row.get("放大"))
            masks = parse_masks(row.get("打码"))
        except ValueError as e:
            problems.append(f"第 {no} 行：{e}")
            continue
        if not info or not (0 <= t_in < t_out <= info["duration"] + 0.05):
            dur = f"{info['duration']:.1f}" if info else "读不出"
            problems.append(f"第 {no} 行出入点不对：{row['入点']}–{row['出点']}，原片时长 {dur} 秒")
            continue
        trans = (row.get("转场") or "切").strip() or "切"
        if trans not in ("切", "叠化", "闪黑"):
            problems.append(f"第 {no} 行转场只能是切、叠化、闪黑：{trans}")
            continue
        name = f"{no:02d}_{C.safe_name(row.get('段落') or os.path.splitext(os.path.basename(src))[0])}"
        shots.append({"no": no, "name": name, "row": row, "src": path, "in": t_in,
                      "out": min(t_out, info["duration"]), "speed": speed, "zoom": zoom, "masks": masks,
                      "trans": trans, "W": info.get("width"), "H": info.get("height"),
                      "duration": round((min(t_out, info["duration"]) - t_in) / speed, 3)})
    if problems:
        sys.exit("台本有问题，先改再切：\n" + "\n".join(problems))
    if len({s["no"] for s in shots}) != len(shots):
        sys.exit("序号有重复")

    for s in shots:
        if only and s["no"] not in only:
            continue
        W, H = s["W"], s["H"]
        dur_src = s["out"] - s["in"]
        # 旧版 ffmpeg 的 fps 滤镜接在 setpts 后面会把加速吃掉，帧率改用输出参数 -r 统一
        base = f"[0:v]setpts=(PTS-STARTPTS)/{s['speed']},format=yuv420p[base]"
        chains, last = mask_filters(s["masks"], W, H, s["in"], s["speed"])
        graph = ";".join([base] + chains)
        out_path = os.path.join(clip_dir, s["name"] + ".mp4")
        encode(["-ss", f"{s['in']:.3f}", "-t", f"{dur_src:.3f}", "-i", s["src"], "-an",
                "-filter_complex", graph, "-map", f"[{last}]", "-r", str(args.fps), "-c:v", "libx264", "-preset", "veryfast",
                "-crf", str(args.crf), "-movflags", "+faststart", out_path])
        s["file"] = os.path.relpath(out_path, out_dir)
        if s["zoom"]:
            os.makedirs(zoom_dir, exist_ok=True)
            rect, push = s["zoom"]
            cw, ch, cx, cy, z = crop_box(rect, W, H)
            if push:
                frames = max(1, int(0.5 * args.fps))
                vf = (f"zoompan=z='if(lte(on,{frames}),1+({z:.4f}-1)*on/{frames},{z:.4f})'"
                      f":x='{cx}*(zoom-1)/({z:.4f}-1+0.0001)':y='{cy}*(zoom-1)/({z:.4f}-1+0.0001)'"
                      f":d=1:s={W}x{H}:fps={args.fps}")
            else:
                vf = f"crop={cw}:{ch}:{cx}:{cy},scale={W}:{H}"
            zoom_path = os.path.join(zoom_dir, s["name"] + "_放大.mp4")
            encode(["-i", out_path, "-an", "-vf", vf + ",format=yuv420p", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", str(args.crf), "-movflags", "+faststart", zoom_path])
            s["zoom_file"] = os.path.relpath(zoom_path, out_dir)
        print(f"{s['name']}: {s['duration']:.1f} 秒", flush=True)

    for s in shots:
        # 用 --only 只重做部分镜头时，其余镜头沿用已有的片段和放大备选
        if not s.get("zoom_file") and s["zoom"]:
            existing = os.path.join(zoom_dir, s["name"] + "_放大.mp4")
            if os.path.exists(existing):
                s["zoom_file"] = os.path.relpath(existing, out_dir)

    # 预览片时间轴：叠化让后一段提前 dissolve 秒开始
    for s, (a, b) in zip(shots, C.timeline(shots, args.dissolve)):
        s["preview_start"], s["preview_end"] = a, b
    total = shots[-1]["preview_end"] if shots else 0.0

    if not args.no_preview and shots:
        for s in shots:
            s["file"] = s.get("file") or os.path.join("粗剪", s["name"] + ".mp4")
        items = [{"file": os.path.join(out_dir, s["file"]), "duration": s["duration"], "trans": s["trans"],
                  "name": s["name"]} for s in shots]
        preview = os.path.join(out_dir, "粗剪预览.mp4")
        try:
            C.join_clips(items, preview, os.path.join(proc_dir, "预览片段"), size=args.preview_size,
                         dissolve=args.dissolve, flash=args.flash)
        except ValueError as e:
            sys.exit(str(e))
        got = C.probe(preview)
        print(f"预览片 {C.fmt_time(got['duration'] if got else 0)}，按台本算 {C.fmt_time(total)}")

    index = {"script": os.path.abspath(args.script), "fps": args.fps, "dissolve": args.dissolve, "total": round(total, 3),
             "shots": [{"no": s["no"], "name": s["name"], "段落": s["row"].get("段落", ""),
                        "身份": s["row"].get("身份", ""), "src": s["src"], "in": s["in"], "out": s["out"],
                        "speed": s["speed"], "trans": s["trans"], "duration": s["duration"],
                        "file": s.get("file") or os.path.join("粗剪", s["name"] + ".mp4"),
                        "zoom_file": s.get("zoom_file"), "preview_start": s["preview_start"],
                        "preview_end": s["preview_end"], "旁白": s["row"].get("旁白", ""),
                        "音效": s["row"].get("音效", "")} for s in shots]}
    with open(os.path.join(proc_dir, "粗剪索引.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"{len(shots)} 段，合计 {C.fmt_time(total)}；索引写在 {proc_dir}/粗剪索引.json")


if __name__ == "__main__":
    main()
