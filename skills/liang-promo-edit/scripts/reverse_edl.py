#!/usr/bin/env python3
"""逆向剪辑表：成片每一秒对应哪段原片的哪一秒。复盘时用来量化「AI 选的镜头被留下了多少」。

用法：
  python3 reverse_edl.py <成片.mp4> --index <镜头索引目录> --out 逆向剪辑表.md [参数]

  --index   index_clips.py 的输出目录（候选画面和识别文字都从这里读）。候选也可以是 AI 粗剪的单镜头片段：
            对「粗剪」目录跑一遍 index_clips.py 即可
  --script  剪辑台本。给了就额外算镜头覆盖率：成片里对上原片的秒数，有多少落在台本选的区间里（前后放宽 --tolerance 秒，默认 4）
  --from / --to  只分析成片的这一段，例如去掉共用开场和结尾卡
  --every 1      每隔几秒取一帧；--work 抽帧和识别缓存目录（和 qa_export.py 同一格式，可以共用）
  --min-score    匹配分数下限，默认 0.35

做法：成片每帧去掉字幕区、右上章节标签区后识别出的文字，切成三字片段，按「罕见片段权重高」的方式
和候选画面比包含度，取最高分；再按时间连续性把相邻帧合成区间。片头、PPT、空白页这类原片里没有的画面标「未匹配」。
候选画面是稀疏取样的，对上的原片时间有几秒误差，只用来算覆盖率和用量，不当精确出入点。
"""

import argparse
import json
import math
import os
import sys

sys.dont_write_bytecode = True  # 不在 skill 目录里留 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
from qa_export import frames_and_ocr  # noqa: E402


def grams(text, n=3):
    t = C.norm_text(text)
    return {t[i:i + n] for i in range(max(len(t) - n + 1, 0))}


def keep_item(it):
    cy, cx = it["y"] + it["h"] / 2, it["x"] + it["w"] / 2
    if 0.82 <= cy <= 0.97 and 0.2 <= cx <= 0.8:
        return False
    if cy < 0.09 and it["x"] > 0.55:
        return False
    return cy <= 0.975


def load_candidates(index_dir):
    cands = []
    for name in sorted(os.listdir(index_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(index_dir, name), encoding="utf-8") as f:
            data = json.load(f)
        if "samples" not in data:
            continue
        for s in data["samples"]:
            if s.get("items"):
                g = grams(" ".join(it["t"] for it in s["items"]))
                if g:
                    cands.append({"clip": data["clip"], "t": s["t"], "grams": g})
    return cands


def main():
    ap = argparse.ArgumentParser(description="逆向剪辑表")
    ap.add_argument("video")
    ap.add_argument("--index", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--json")
    ap.add_argument("--script")
    ap.add_argument("--work")
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--from", dest="t_from", default="0")
    ap.add_argument("--to", dest="t_to")
    ap.add_argument("--min-score", type=float, default=0.35)
    ap.add_argument("--tolerance", type=float, default=4.0, help="台本区间前后放宽几秒，默认 4（索引大约每 4 秒取一帧）")
    args = ap.parse_args()

    cands = load_candidates(args.index)
    if not cands:
        sys.exit(f"{args.index} 里没有带识别文字的索引，先跑 index_clips.py（不要加 --no-ocr）")
    df = {}
    for c in cands:
        for g in c["grams"]:
            df[g] = df.get(g, 0) + 1
    N = len(cands)
    weight = {g: math.log((N + 1) / (n + 1)) + 0.05 for g, n in df.items()}
    inverted = {}
    for i, c in enumerate(cands):
        for g in c["grams"]:
            inverted.setdefault(g, []).append(i)

    video = os.path.abspath(os.path.expanduser(args.video))
    info = C.probe(video)
    out = os.path.abspath(os.path.expanduser(args.out))
    work = os.path.abspath(os.path.expanduser(args.work or C.default_work(out)))
    frames, errors = frames_and_ocr(video, info, work, args.every, False)
    t0 = C.parse_time(args.t_from)
    t1 = C.parse_time(args.t_to) if args.t_to else info["duration"]

    matches = []
    prev = None
    for t, _, items in frames:
        if not (t0 <= t <= t1):
            continue
        F = grams(" ".join(it["t"] for it in (items or []) if keep_item(it)))
        total = sum(weight.get(g, math.log(N + 1) + 0.05) for g in F)
        if len(F) < 5 or total <= 0:
            matches.append((t, None, 0.0))
            continue
        score = {}
        for g in F:
            for i in inverted.get(g, ()):
                score[i] = score.get(i, 0.0) + weight[g]
        best = max(score.items(), key=lambda kv: kv[1], default=(None, 0.0))
        s = best[1] / total
        pick = best[0]
        if pick is not None and prev is not None:
            # 分数接近时，优先接着上一帧的原片往后走，减少在相似页面之间来回跳
            pool = [i for i, sc in score.items() if sc >= 0.92 * best[1]
                    and cands[i]["clip"] == prev["clip"] and cands[i]["t"] >= prev["t"] - 1]
            if pool:
                pick = min(pool, key=lambda i: abs(cands[i]["t"] - prev["t"] - args.every))
                s = score[pick] / total
        chosen = cands[pick] if pick is not None and s >= args.min_score else None
        matches.append((t, chosen, s))
        prev = chosen or prev

    # 合成区间：同一段原片、原片时间大致往前走的相邻帧算一段
    segs = []
    for t, c, s in matches:
        clip = c["clip"] if c else None
        if segs and segs[-1]["clip"] == clip and (clip is None or c["t"] >= segs[-1]["raw"][0] - 3):
            seg = segs[-1]
            seg["end"] = t
            seg["scores"].append(s)
            if c:
                seg["raw"] = [min(seg["raw"][0], c["t"]), max(seg["raw"][1], c["t"])]
        else:
            segs.append({"start": t, "end": t, "clip": clip, "raw": [c["t"], c["t"]] if c else None, "scores": [s]})

    script_ranges = []
    if args.script:
        _, rows = C.pick_table(args.script, ["原片", "入点", "出点"])
        for row in rows:
            try:
                script_ranges.append((os.path.basename(row["原片"].strip().strip("`")),
                                      C.parse_time(row["入点"]) - args.tolerance,
                                      C.parse_time(row["出点"]) + args.tolerance))
            except (ValueError, KeyError):
                continue

    matched = [(t, c) for t, c, _ in matches if c]
    analyzed = len(matches)
    usage = {}
    for _, c in matched:
        usage[c["clip"]] = usage.get(c["clip"], 0) + args.every
    covered = clip_cov = None
    if script_ranges and matched:
        inside = sum(1 for _, c in matched
                     if any(os.path.basename(c["clip"]) == clip and a <= c["t"] <= b for clip, a, b in script_ranges))
        covered = inside / len(matched)
        script_clips = {clip for clip, _, _ in script_ranges}
        clip_cov = sum(1 for _, c in matched if os.path.basename(c["clip"]) in script_clips) / len(matched)

    md = ["# 逆向剪辑表", "",
          f"成片 {os.path.basename(video)}，分析 {C.fmt_time(t0, 0)}–{C.fmt_time(t1, 0)}，每 {args.every:g} 秒一帧，"
          f"共 {analyzed} 帧；对上原片 {len(matched)} 帧（{len(matched) / max(analyzed, 1):.0%}）。"
          "原片时间有几秒误差，只看用量和覆盖，不当精确出入点。", ""]
    if covered is not None:
        md += [f"**镜头覆盖率**：对上原片的画面里，{covered:.0%} 落在剪辑台本选的区间里（前后放宽 {args.tolerance:g} 秒）。"
               f"按原片算，{clip_cov:.0%} 的画面来自台本用到的原片。", ""]
    md += ["| 成片区间 | 原片 | 原片时间 | 平均分 |", "|---|---|---|---|"]
    for seg in segs:
        span = f"{C.fmt_time(seg['start'], 0)}–{C.fmt_time(seg['end'] + args.every, 0)}"
        if seg["clip"]:
            raw = f"{C.fmt_time(seg['raw'][0])}–{C.fmt_time(seg['raw'][1])}"
            md.append(f"| {span} | {seg['clip']} | {raw} | {sum(seg['scores']) / len(seg['scores']):.2f} |")
        else:
            md.append(f"| {span} | 未匹配 | | |")
    md += ["", "## 各段原片的用量", "", "| 原片 | 成片里用了 |", "|---|---|"]
    md += [f"| {k} | {v:.0f} 秒 |" for k, v in sorted(usage.items(), key=lambda kv: -kv[1])]
    if errors:
        md += ["", "识别失败：" + "；".join(errors[:3])]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"video": video, "analyzed": analyzed, "matched": len(matched), "coverage": covered,
                       "clip_coverage": clip_cov if covered is not None else None,
                       "usage": usage, "segments": [{k: v for k, v in s.items() if k != "scores"} for s in segs]},
                      f, ensure_ascii=False, indent=1)
    print(f"对上原片 {len(matched)}/{analyzed} 帧"
          + (f"，镜头覆盖率 {covered:.0%}" if covered is not None else "") + f"；写在 {out}")


if __name__ == "__main__":
    main()
