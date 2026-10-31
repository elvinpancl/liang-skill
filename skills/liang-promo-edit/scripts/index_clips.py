#!/usr/bin/env python3
"""给录屏原片做镜头索引：页面切换点、静止段、等待段、打字段，以及每段新出现的文字。

写剪辑台本时按这份索引挑镜头、定出入点，不用再从头拖原片。

用法：
  python3 index_clips.py <原片目录或文件>... --out <索引目录> [参数]

常用参数：
  --big 0.08        画面变化分数超过它算切换（页面跳转、弹窗），默认 0.08
  --static 0.0015   变化分数低于它算没动，默认 0.0015
  --min-static 1.5  连续没动超过几秒算静止段，默认 1.5
  --every 4         一段画面里每隔几秒识别一次文字，默认 4
  --delay 0.8       切换后延迟几秒再取帧，等页面加载完，默认 0.8
  --jobs 2          同时跑几批文字识别，默认 2
  --top 0.075       画面顶部这个比例以内算浏览器标签栏和地址栏，不计入新出现的文字
  --no-ocr          只算画面变化，不识别文字
  --keep-frames     保留抽出的帧（默认识别完就删）

输出：
  <索引目录>/<原片相对路径>.json   每段原片一份，含变化曲线摘要、分段和每次识别的文字（带坐标）
  <索引目录>/镜头索引.md            给人看的总表：每段的起止、标记、新出现的文字、建议保留区间

判定规则（都是线索，写台本时以画面为准）：
  - 切换：10 帧/秒下变化分数 ≥ --big。
  - 静止：连续低于 --static 超过 --min-static 秒。
  - 打字：识别到输入法候选栏，「1.xx 2.xx 3.xx」这种连续编号。
  - 等待：识别到「正在」「处理中」「执行中」「生成中」「加载中」这类字样。
  - 新出现的文字：同一段原片里第一次出现、又不是菜单这类反复出现的文字。
"""

import argparse
import json
import os
import re
import sys
import tempfile

sys.dont_write_bytecode = True  # 不在 skill 目录里留 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

INDEX_VERSION = 4
WAIT_RE = re.compile(r"正在|处理中|执行中|生成中|加载中|排队|解析中|上传中|分析中|思考中|编排中|请稍候"
                     r"|Loading|Processing|Running|Thinking|Pending", re.I)


def find_videos(inputs):
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
                if os.path.splitext(name)[1].lower() in C.VIDEO_EXTS and not name.startswith("."):
                    path = os.path.join(root, name)
                    found.append((os.path.relpath(path, base), path))
    seen, unique = set(), []
    for rel, path in found:
        if rel not in seen:
            seen.add(rel)
            unique.append((rel, path))
    return unique


def scene_series(path):
    """10 帧/秒、320 宽下的逐帧变化分数，返回 [(秒, 分数)]。"""
    log = C.run_ffmpeg(["-i", path, "-an", "-vf",
                        "fps=10,scale=320:-2,select='gte(scene,0)',metadata=print", "-f", "null", "-"]).stderr
    times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", log)]
    scores = [float(x) for x in re.findall(r"lavfi\.scene_score=([\d.]+)", log)]
    return list(zip(times, scores))


def static_runs(series, low, min_len):
    runs, start = [], None
    for t, s in series:
        if s < low:
            if start is None:
                start = t
        else:
            if start is not None and t - start >= min_len:
                runs.append((start, t))
            start = None
    if start is not None and series and series[-1][0] - start >= min_len:
        runs.append((start, series[-1][0]))
    return runs


def change_points(series, big, merge=0.5):
    pts = []
    for t, s in series:
        if s >= big and (not pts or t - pts[-1] > merge):
            pts.append(t)
    return pts


def intervals(duration, cuts, statics, peaks=()):
    """把整段原片切成交替的「动作段」和「静止段」，动作段再按切换点细分。

    两段静止之间的空隙也算动作（点一下就跳页这种瞬间变化）；但空隙不到 0.3 秒、又没有明显变化
    （分数都低于 0.01）的，当作同一段静止，避免鼠标抖动拆出一堆碎段。
    """
    merged = []
    for a, b in statics:
        if merged:
            gap_a, gap_b = merged[-1][1], a
            if gap_b - gap_a < 0.3 and not any(gap_a - 0.15 <= t <= gap_b + 0.15 for t in peaks):
                merged[-1][1] = b
                continue
        merged.append([a, b])
    raw, pos = [], 0.0
    for a, b in merged:
        if a - pos > 0.05:
            raw.append(["动作", pos, a])
        raw.append(["静止", a, b])
        pos = b
    if duration - pos > 0.05:
        raw.append(["动作", pos, duration])
    elif raw:
        raw[-1][2] = duration
    out = []
    for kind, a, b in raw:
        if kind == "动作":
            edges = [a] + [c for c in cuts if a + 0.3 < c < b - 0.3] + [b]
            out += [["动作", x, y] for x, y in zip(edges, edges[1:])]
        else:
            out.append([kind, a, b])
    return out


def sample_times(duration, spans, every, delay):
    """动作段取开头、中间每隔 every 秒、结束后画面稳定时各一帧；静止段取中间一帧。"""
    times = []
    for i, (kind, a, b) in enumerate(spans):
        if kind == "静止":
            times.append((a + b) / 2)
            continue
        if b - a > 1.0:
            times.append(a + 0.3)
        t = a + every
        while t < b - 0.5:
            times.append(t)
            t += every
        nxt_end = spans[i + 1][2] if i + 1 < len(spans) else duration
        times.append(min(b + delay, nxt_end - 0.1, duration - 0.1))
    times = sorted(t for t in times if 0 <= t < duration)
    kept = []
    for t in times:
        if not kept or t - kept[-1] >= 0.6:
            kept.append(round(t, 2))
    return kept


def main():
    ap = argparse.ArgumentParser(description="给录屏原片做镜头索引")
    ap.add_argument("inputs", nargs="+", help="原片目录或文件")
    ap.add_argument("--out", required=True, help="索引输出目录")
    ap.add_argument("--big", type=float, default=0.08)
    ap.add_argument("--static", type=float, default=0.0015)
    ap.add_argument("--min-static", type=float, default=1.5)
    ap.add_argument("--every", type=float, default=4.0)
    ap.add_argument("--delay", type=float, default=0.8)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--top", type=float, default=0.075, help="画面顶部多高以内算浏览器标签栏和地址栏，默认 0.075")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()

    if not args.no_ocr and sys.platform != "darwin":
        print("文字识别只支持 macOS，改为只算画面变化。", file=sys.stderr)
        args.no_ocr = True
    out_root = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out_root, exist_ok=True)
    videos = find_videos(args.inputs)
    if not videos:
        sys.exit("没有找到原片（支持 mp4、mov、m4v、mkv、webm、avi）")

    scanner = None
    scan_path = C.find_sibling("liang-promo-footage", "scripts/scan_sensitive.py")
    if scan_path:
        scanner = C.load_module(scan_path, "scan_sensitive")

    clips = []
    for rel, path in videos:
        info = C.probe(path)
        if not info:
            print(f"{rel}: 读不出时长，跳过", file=sys.stderr)
            continue
        json_path = os.path.join(out_root, re.sub(r"[\\/]+", "__", os.path.splitext(rel)[0]) + ".json")
        cached = None
        if os.path.exists(json_path):
            with open(json_path, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("version") != INDEX_VERSION or abs(cached.get("duration", -1) - info["duration"]) > 0.05:
                cached = None
        series = scene_series(path) if not cached else None
        if cached:
            cuts, statics, samples = cached["cuts"], [tuple(x) for x in cached["static"]], cached["samples"]
        else:
            cuts = change_points(series, args.big)
            statics = static_runs(series, args.static, args.min_static)
            peaks = [t for t, sc in series if sc >= 0.01]
            spans = intervals(info["duration"], cuts, statics, peaks)
            samples = [{"t": t} for t in sample_times(info["duration"], spans, args.every, args.delay)]
        clips.append({"rel": rel, "path": path, "info": info, "json": json_path, "cuts": cuts,
                      "static": statics, "samples": samples,
                      "series_peaks": cached["series_peaks"] if cached else
                      [(round(t, 1), round(s, 4)) for t, s in series if s >= 0.01]})
        print(f"{rel}: {info['duration']:.0f} 秒，{len(cuts)} 个切换点，静止 "
              f"{sum(b - a for a, b in statics):.0f} 秒，取 {len(samples)} 帧", flush=True)

    if not args.no_ocr:
        tmp_root = tempfile.mkdtemp(prefix="liang_index_")
        for clip in clips:
            todo = [s for s in clip["samples"] if "items" not in s]
            if not todo:
                continue
            fdir = os.path.join(tmp_root, C.safe_name(os.path.splitext(clip["rel"])[0], 40))
            os.makedirs(fdir, exist_ok=True)
            paths = []
            for s in todo:
                name = f"t{s['t']:07.2f}.jpg"
                fp = os.path.join(fdir, name)
                if C.extract_frame(clip["path"], s["t"], fp):
                    paths.append(fp)
                    s["_file"] = name
            found, errors = C.ocr_images(paths, jobs=args.jobs)
            for s in todo:
                if s.get("_file") in found:
                    s["items"] = found[s.pop("_file")]
            for e in errors:
                print(f"{clip['rel']}: {e}", file=sys.stderr)
            if args.keep_frames:
                keep_dir = os.path.join(out_root, "frames", C.safe_name(os.path.splitext(clip["rel"])[0], 40))
                os.makedirs(keep_dir, exist_ok=True)
                for fp in paths:
                    os.replace(fp, os.path.join(keep_dir, os.path.basename(fp)))
            else:
                for fp in paths:
                    if os.path.exists(fp):
                        os.remove(fp)
            print(f"{clip['rel']}: 识别 {len(paths)} 帧", flush=True)
        try:
            os.rmdir(tmp_root)
        except OSError:
            pass

    # 反复出现的文字（菜单、侧边栏、浏览器标签）当作界面固定文字，不算新出现
    def line_keys(sample):
        return {C.norm_text(line["t"]) for line in C.group_lines(sample.get("items") or [])
                if len(C.norm_text(line["t"])) >= 2}

    clip_presence = {}
    for clip in clips:
        seen = set()
        for s in clip["samples"]:
            seen |= line_keys(s)
        for k in seen:
            clip_presence[k] = clip_presence.get(k, 0) + 1
    global_chrome = {k for k, n in clip_presence.items() if len(clips) >= 3 and n >= max(3, 0.5 * len(clips))}

    total_static = total_wait = total_typing = 0.0
    md = []
    for clip in clips:
        samples = clip["samples"]
        counts = {}
        for s in samples:
            for k in line_keys(s):
                counts[k] = counts.get(k, 0) + 1
        chrome = global_chrome | {k for k, n in counts.items() if len(samples) >= 5 and n >= 0.7 * len(samples)}
        seen = set()
        for s in samples:
            lines = [line for line in C.group_lines(s.get("items") or [])]
            joined = " ".join(line["t"] for line in lines)
            s["typing"] = bool(C.IME_RE.search(joined))
            s["wait"] = bool(WAIT_RE.search(joined))
            new = []
            for line in lines:
                key = C.norm_text(line["t"])
                # 顶部的浏览器标签栏和地址栏、太短的碎片，不算新出现的内容
                if line["cy"] >= args.top and len(key) >= 4 and key not in chrome and key not in seen:
                    new.append(line["t"])
                seen.add(key)
            s["new"] = new
            if scanner is not None and joined:
                cats = [cat for cat, pat in scanner.MUST if pat.search("\n".join(line["t"] for line in lines))]
                s["sensitive"] = cats
                s["mask_boxes"] = [[round(max(it["x"] - 0.01, 0), 3), round(max(it["y"] - 0.01, 0), 3),
                                    round(min(it["w"] + 0.02, 1), 3), round(min(it["h"] + 0.02, 1), 3)]
                                   for it in (s.get("items") or [])
                                   if any(pat.search(it["t"]) for _, pat in scanner.MUST)]

        dur = clip["info"]["duration"]
        spans = intervals(dur, clip["cuts"], clip["static"], [t for t, _ in clip["series_peaks"]])
        segments = []
        for i, (kind, a, b) in enumerate(spans):
            if kind == "静止":
                total_static += b - a
                if i > 0:
                    continue
                # 片子一开头就是静止画面：作为起始状态单列一行
                nxt_static, flag_end, settle_end = 0.0, b, min(b, a + 2.0)
            elif i == len(spans) - 1 and b - a < 0.3:
                continue  # 片尾停录前的一下抖动，不单列
            else:
                nxt = spans[i + 1] if i + 1 < len(spans) and spans[i + 1][0] == "静止" else None
                nxt_static = nxt[2] - nxt[1] if nxt else 0.0
                flag_end = nxt[2] if nxt else b
                settle_end = b + min(2.0, nxt_static)
            inside = [s for s in samples if a - 0.05 <= s["t"] <= flag_end + 0.05]
            typing = any(s.get("typing") for s in inside)
            wait = any(s.get("wait") for s in inside)
            sens = sorted({c for s in inside for c in s.get("sensitive", [])})
            boxes = []
            for smp in inside:
                for box in smp.get("mask_boxes", []):
                    if not any(abs(box[0] - o[0]) < 0.02 and abs(box[1] - o[1]) < 0.02 for o in boxes):
                        boxes.append(box)
            new_lines = [x for s in inside for x in s.get("new", [])]
            segments.append({"no": len(segments) + 1, "kind": "起始" if kind == "静止" else "动作",
                             "start": round(a, 2), "end": round(b, 2),
                             "static_after": round(nxt_static, 1), "typing": typing, "wait": wait,
                             "sensitive": sens, "mask_boxes": boxes[:6], "keep": [round(a, 1), round(settle_end, 1)],
                             "new": new_lines[:12]})
            span = flag_end - a
            total_wait += span if wait else 0
            total_typing += span if typing else 0
        clip["segments"] = segments

        data = {"version": INDEX_VERSION, "clip": clip["rel"], "path": clip["path"], "duration": dur,
                "size": f"{clip['info'].get('width')}x{clip['info'].get('height')}",
                "fps": clip["info"].get("fps"), "cuts": clip["cuts"], "static": clip["static"],
                "series_peaks": clip["series_peaks"], "segments": segments, "samples": samples}
        os.makedirs(os.path.dirname(clip["json"]), exist_ok=True)
        with open(clip["json"], "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

        md.append(f"## {clip['rel']}")
        md.append("")
        md.append(f"时长 {C.fmt_time(dur)}，{data['size']}，{len(segments)} 个动作段，静止合计 "
                  f"{sum(b - a for a, b in clip['static']):.0f} 秒。")
        md.append("")
        md.append("| 段 | 动作起止 | 时长 | 之后静止 | 标记 | 新出现的文字 | 建议保留 |")
        md.append("|---|---|---|---|---|---|---|")
        for s in segments:
            marks = ["起始画面"] if s.get("kind") == "起始" else []
            if s["wait"]:
                marks.append("等待")
            if s["typing"]:
                marks.append("打字")
            if s["sensitive"]:
                where = "；".join(",".join(f"{v:.2f}" for v in b) for b in s["mask_boxes"][:3])
                marks.append("要打码：" + "、".join(s["sensitive"]) + (f"（{where}）" if where else ""))
            text = "；".join(x[:28] for x in s["new"][:3]).replace("|", "\\|")
            after = f"{s['static_after']:.0f} 秒" if s["static_after"] >= 1 else ""
            md.append(f"| {s['no']} | {C.fmt_time(s['start'])}–{C.fmt_time(s['end'])} | "
                      f"{s['end'] - s['start']:.1f} | {after} | {'，'.join(marks)} | {text} | "
                      f"{C.fmt_time(s['keep'][0])}–{C.fmt_time(s['keep'][1])} |")
        md.append("")

    total = sum(c["info"]["duration"] for c in clips)
    head = ["# 镜头索引", "",
            f"共 {len(clips)} 段原片，合计 {total / 60:.1f} 分钟。静止约 {total_static / 60:.1f} 分钟，"
            f"带等待字样的段约 {total_wait / 60:.1f} 分钟，带打字的段约 {total_typing / 60:.1f} 分钟，"
            "粗剪时这些都可以剪掉或加速。", "",
            "每个动作段的「建议保留」是动作本身加上画面稳定后的 2 秒，后面的静止段可以剪掉或叠化跳过。"
            "这只是起点，写台本时按画面调。"
            "标了要打码的段，台本里写进打码列，粗剪时裁掉或在剪映里遮挡。", ""]
    with open(os.path.join(out_root, "镜头索引.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(head + md) + "\n")
    print(f"索引写在 {out_root}/镜头索引.md")


if __name__ == "__main__":
    main()
