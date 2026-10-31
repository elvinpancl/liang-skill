#!/usr/bin/env python3
"""成片发布前检查：逐秒抽帧识别，扫出要打码的画面，检查字幕写法和技术参数。

用法：
  python3 qa_export.py <成片.mp4>... --out 发布前检查.md [参数]

常用参数：
  --work DIR        抽帧和识别结果放哪，默认在报告旁边的「制作过程/发布前检查」（报告本身在制作过程里时就是同级的「发布前检查」）。可以断点续跑
  --subs FILE       字幕文件（剪映导出的 srt 或 txt）。不给时找成片旁边同名的 .srt、.txt；
                    再没有就用画面底部识别出的字幕
  --cap 秒          时长上限，超过就报
  --term 写法       产品名的标准写法，可以给多次。字幕里同一个名字出现多种写法就报，例如「Agent OS」和「AgentOS」混用
  --glossary FILE   错字表，每行「正确写法|错误写法1|错误写法2」
  --banned FILE     禁用词，每行一个；不给就用内置的几条套话
  --max-line N      字幕一行超过 N 字就报，默认 16
  --every 秒        每隔几秒取一帧，默认 1
  --keep-frames     保留抽出的帧。默认识别完就删帧，只留识别结果，重跑时不再重复识别
  --strict          有必须处理的项时退出码为 1

必须打码的规则复用 liang-promo-footage 的 scan_sensitive.py：API 密钥、邮箱、手机号、身份证号、本机用户路径。
输出里敏感值只露前 4 位。识别会漏字、错字，报告只是线索：标出来的时间点逐个看画面确认，
没标出来的画面发布前也要整体过一眼。只支持 macOS（文字识别调系统 Vision）。
"""

import argparse
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # 不在 skill 目录里留 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

DEFAULT_BANNED = ["说白了", "本质上", "换句话说", "意味着", "不可否认", "综上所述", "值得注意的是", "不难发现"]


def load_scanner():
    path = C.find_sibling("liang-promo-footage", "scripts/scan_sensitive.py")
    if not path:
        sys.exit("找不到 liang-promo-footage/scripts/scan_sensitive.py。打码规则复用它，请先安装 liang-promo-footage。")
    return C.load_module(path, "scan_sensitive")


def frames_and_ocr(video, info, work, every, keep):
    stem = os.path.splitext(os.path.basename(video))[0]
    fdir = os.path.join(work, C.safe_name(stem, 40), "frames")
    os.makedirs(fdir, exist_ok=True)
    expected = int(info["duration"] // every) + 1
    names = sorted(n for n in os.listdir(fdir) if n.endswith(".jpg"))
    if abs(len(names) - expected) > 1:
        for n in names:
            os.remove(os.path.join(fdir, n))
        C.run_ffmpeg(["-loglevel", "error", "-y", "-i", video, "-vf", f"fps=1/{every}", "-q:v", "2",
                      os.path.join(fdir, "s%05d.jpg")], check=True)
        names = sorted(n for n in os.listdir(fdir) if n.endswith(".jpg"))
    ocr_path = os.path.join(work, C.safe_name(stem, 40), "ocr.jsonl")
    ocr = {}
    if os.path.exists(ocr_path):
        with open(ocr_path, encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                ocr[obj["file"]] = obj["items"]
    todo = [os.path.join(fdir, n) for n in names if n not in ocr]
    errors = []
    if todo:
        found, errors = C.ocr_images(todo)
        ocr.update(found)
        with open(ocr_path, "w", encoding="utf-8") as f:
            for n in names:
                if n in ocr:
                    f.write(json.dumps({"file": n, "items": ocr[n]}, ensure_ascii=False) + "\n")
    frames = []
    for n in names:
        idx = int(re.search(r"(\d+)", n).group(1))
        frames.append(((idx - 1) * every, n, ocr.get(n)))
    if not keep and not errors and all(n in ocr for n in names):
        for n in names:
            os.remove(os.path.join(fdir, n))
    return frames, errors


def read_subs(path):
    """读剪映导出的 srt 或 txt，返回 [(秒或 None, 文字)]。"""
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    if path.lower().endswith(".srt"):
        out = []
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [l for l in block.splitlines() if l.strip()]
            m = next((re.match(r"(\d+:\d+:\d+[,.]\d+)\s*-->", l) for l in lines if "-->" in l), None)
            if not m:
                continue
            h, mi, s = m.group(1).replace(",", ".").split(":")
            t = int(h) * 3600 + int(mi) * 60 + float(s)
            body = [l for l in lines if "-->" not in l and not re.fullmatch(r"\d+", l.strip())]
            out.append((t, " ".join(body).strip()))
        return out
    return [(None, l.strip()) for l in text.splitlines() if l.strip()]


def subs_from_ocr(frames, zone):
    out, last = [], None
    for t, _, items in frames:
        if not items:
            continue
        sub = [it for it in items if zone[0] <= it["y"] + it["h"] / 2 <= zone[1]
               and 0.2 <= it["x"] + it["w"] / 2 <= 0.8 and it["w"] < 0.8]
        text = " ".join(it["t"] for it in sorted(sub, key=lambda it: it["x"])).strip()
        if text and text != last:
            out.append((t, text))
        last = text or None
    return out


def term_regex(term):
    pieces = [re.escape(ch) for ch in term if not ch.isspace()]
    return re.compile(r"\s*".join(pieces), re.I)


def check_video(video, args, scanner, banned, glossary):
    info = C.probe(video)
    if not info:
        return {"video": video, "error": "读不出时长，跳过"}
    frames, ocr_errors = frames_and_ocr(video, info, args.work, args.every, args.keep_frames)

    must, optional, ime = {}, {}, []
    for t, name, items in frames:
        if items is None:
            continue
        text = "\n".join(line["t"] for line in C.group_lines(items))
        for level, patterns, bucket in (("必须", scanner.MUST, must), ("可选", scanner.OPTIONAL, optional)):
            for cat, pattern in patterns:
                hits = [scanner.mask(m.group(0)) for m in pattern.finditer(text)]
                if hits:
                    entry = bucket.setdefault(cat, {"times": [], "samples": []})
                    entry["times"].append(t)
                    for h in hits:
                        if h not in entry["samples"]:
                            entry["samples"].append(h)
        if C.IME_RE.search(text.replace("\n", " ")):
            ime.append(t)

    subs_path = args.subs
    if not subs_path:
        base = os.path.splitext(video)[0]
        subs_path = next((base + ext for ext in (".srt", ".txt") if os.path.exists(base + ext)), None)
    if subs_path:
        subs, subs_source = read_subs(subs_path), f"字幕文件 {os.path.basename(subs_path)}"
    else:
        subs, subs_source = subs_from_ocr(frames, args.sub_zone), "画面底部识别出的字幕"

    def when(t):
        return C.fmt_time(t, 0) if t is not None else "无时间"

    term_issues = []
    for term in args.term or []:
        rx = term_regex(term)
        forms = {}
        for t, line in subs:
            for m in rx.finditer(line):
                forms.setdefault(m.group(0), []).append(when(t))
        if len(forms) > 1:
            detail = "；".join(f"「{k}」{len(v)} 处（{'、'.join(v[:4])}）" for k, v in forms.items())
            term_issues.append(f"「{term}」有 {len(forms)} 种写法：{detail}")
    typo_issues = []
    for right, wrongs in glossary:
        for wrong in wrongs:
            spots = [when(t) for t, line in subs if wrong in line]
            if spots:
                typo_issues.append(f"「{wrong}」应为「{right}」：{'、'.join(spots[:6])}")
    banned_issues = []
    for word in banned:
        spots = [when(t) for t, line in subs if word in line]
        if spots:
            banned_issues.append(f"「{word}」：{'、'.join(spots[:6])}")
    def redact(text):
        for _, pattern in scanner.MUST + scanner.OPTIONAL:
            text = pattern.sub(lambda m: scanner.mask(m.group(0)), text)
        return text

    long_lines = [(when(t), redact(line)) for t, line in subs if C.count_chars(line) > args.max_line]

    tech = {"duration": info["duration"], "size": f"{info.get('width')}×{info.get('height')}",
            "fps": info.get("fps"), "vcodec": info.get("vcodec"), "audio": info["audio"]}
    if info["audio"]:
        loud = C.run_ffmpeg(["-i", video, "-map", "0:a:0", "-af", "ebur128", "-f", "null", "-"]).stderr
        m = re.findall(r"I:\s+(-?[\d.]+) LUFS", loud)
        tech["lufs"] = float(m[-1]) if m else None
        sil = C.run_ffmpeg(["-i", video, "-map", "0:a:0", "-af", "silencedetect=noise=-45dB:d=1.5",
                            "-f", "null", "-"]).stderr
        starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", sil)]
        ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", sil)]
        tech["silence"] = list(zip(starts, ends + [info["duration"]] * (len(starts) - len(ends))))
    blk = C.run_ffmpeg(["-i", video, "-vf", "scale=320:-2,blackdetect=d=0.3:pix_th=0.10", "-an",
                        "-f", "null", "-"]).stderr
    tech["black"] = [(float(a), float(b)) for a, b in
                     re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", blk)]

    return {"video": video, "info": info, "frames": len(frames), "ocr_errors": ocr_errors,
            "must": must, "optional": optional, "ime": ime, "subs_source": subs_source,
            "subs_count": len(subs), "term_issues": term_issues, "typo_issues": typo_issues,
            "banned_issues": banned_issues, "long_lines": long_lines, "tech": tech}


def render(results, args):
    lines = ["# 发布前检查", ""]
    lines.append("逐秒抽帧识别的结果只是线索。标出来的时间点逐个看画面确认；没标出来的画面，发布前也要整体过一眼。"
                 "敏感值只露前 4 位。")
    lines.append("")
    lines.append("| 成片 | 时长 | 必须处理 | 建议处理 |")
    lines.append("|---|---|---|---|")
    for r in results:
        if "error" in r:
            lines.append(f"| {os.path.basename(r['video'])} | 读不出 | | |")
            continue
        must_n = sum(len(C.merge_ranges(v["times"], gap=args.every * 2)) for v in r["must"].values())
        sugg = len(r["optional"]) + bool(r["ime"]) + len(r["term_issues"]) + len(r["typo_issues"]) \
            + len(r["banned_issues"]) + bool(r["long_lines"])
        over = args.cap and r["info"]["duration"] > args.cap
        lines.append(f"| {os.path.basename(r['video'])} | {C.fmt_time(r['info']['duration'], 1)}"
                     f"{'（超上限）' if over else ''} | {must_n} 段 | {sugg} 项 |")
    lines.append("")
    for r in results:
        if "error" in r:
            continue
        lines.append(f"## {os.path.basename(r['video'])}")
        lines.append("")
        lines.append("**必须处理（打码或裁掉）**")
        lines.append("")
        if r["must"]:
            lines.append("| 类别 | 时间段 | 片段（已遮挡） |")
            lines.append("|---|---|---|")
            for cat, v in r["must"].items():
                rng = C.merge_ranges(v["times"], gap=args.every * 2)
                lines.append(f"| {cat} | {C.fmt_ranges(rng)} | {'、'.join(v['samples'][:4])} |")
        else:
            lines.append("没有扫出必须打码的画面。")
        lines.append("")
        sugg = []
        for cat, v in r["optional"].items():
            rng = C.merge_ranges(v["times"], gap=args.every * 2)
            sugg.append(f"可选打码·{cat}：{C.fmt_ranges(rng)}")
        if r["ime"]:
            sugg.append(f"输入法候选栏露出：{C.fmt_ranges(C.merge_ranges(r['ime'], gap=args.every * 2))}")
        sugg += [f"产品名写法不统一：{x}" for x in r["term_issues"]]
        sugg += [f"错字：{x}" for x in r["typo_issues"]]
        sugg += [f"禁用词：{x}" for x in r["banned_issues"]]
        if r["long_lines"]:
            sample = "；".join(f"{t}「{line}」" for t, line in r["long_lines"][:5])
            sugg.append(f"字幕超过 {args.max_line} 字的行有 {len(r['long_lines'])} 条：{sample}")
        lines.append("**建议处理**")
        lines.append("")
        lines += [f"- {s}" for s in sugg] or ["- 无"]
        lines.append("")
        t = r["tech"]
        lines.append("**技术参数**")
        lines.append("")
        lines.append("| 项目 | 结果 |")
        lines.append("|---|---|")
        cap = f"，上限 {C.fmt_time(args.cap, 0)}" if args.cap else ""
        lines.append(f"| 时长 | {C.fmt_time(t['duration'], 1)}{cap} |")
        lines.append(f"| 分辨率、帧率、编码 | {t['size']}，{t['fps']} 帧，{t['vcodec']} |")
        if t["audio"]:
            lufs = f"{t['lufs']} LUFS" if t.get("lufs") is not None else "读不出"
            lines.append(f"| 整体响度 | {lufs} |")
            sil = "、".join(f"{C.fmt_time(a, 1)}–{C.fmt_time(b, 1)}" for a, b in t["silence"]) or "无"
            lines.append(f"| 1.5 秒以上的静音 | {sil} |")
        else:
            lines.append("| 声音 | 没有音轨 |")
        black = "、".join(f"{C.fmt_time(a, 1)}–{C.fmt_time(b, 1)}" for a, b in t["black"]) or "无"
        lines.append(f"| 0.3 秒以上的黑场 | {black} |")
        lines.append(f"| 字幕来源 | {r['subs_source']}，{r['subs_count']} 条 |")
        lines.append(f"| 识别帧数 | {r['frames']} |")
        if r["ocr_errors"]:
            lines.append(f"| 识别失败 | {'；'.join(r['ocr_errors'][:3])} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="成片发布前检查")
    ap.add_argument("videos", nargs="+", help="剪映导出的成片")
    ap.add_argument("--out", required=True, help="报告路径（Markdown）")
    ap.add_argument("--work", help="抽帧和识别结果目录")
    ap.add_argument("--subs", help="字幕文件，只给一条成片时使用")
    ap.add_argument("--cap", type=float, help="时长上限（秒）")
    ap.add_argument("--term", action="append", help="产品名的标准写法，可以给多次")
    ap.add_argument("--glossary", help="错字表，每行「正确写法|错误写法1|错误写法2」")
    ap.add_argument("--banned", help="禁用词文件，每行一个")
    ap.add_argument("--max-line", type=int, default=16, help="字幕每行字数上限，默认 16")
    ap.add_argument("--every", type=float, default=1.0, help="每隔几秒取一帧，默认 1")
    ap.add_argument("--sub-zone", default="0.82,0.97", help="画面里字幕所在的纵向范围，默认 0.82,0.97")
    ap.add_argument("--keep-frames", action="store_true", help="保留抽出的帧")
    ap.add_argument("--strict", action="store_true", help="有必须处理的项时退出码为 1")
    args = ap.parse_args()

    if sys.platform != "darwin":
        sys.exit("文字识别只支持 macOS。")
    if args.subs and len(args.videos) > 1:
        sys.exit("--subs 只能配一条成片；多条成片请把字幕放在成片旁边，用同名的 .srt 或 .txt。")
    args.sub_zone = tuple(float(x) for x in args.sub_zone.split(","))
    out = os.path.abspath(os.path.expanduser(args.out))
    args.work = os.path.abspath(os.path.expanduser(args.work or C.default_work(out)))
    os.makedirs(args.work, exist_ok=True)

    scanner = load_scanner()
    banned = DEFAULT_BANNED
    if args.banned:
        with open(args.banned, encoding="utf-8") as f:
            banned = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    glossary = []
    if args.glossary:
        with open(args.glossary, encoding="utf-8") as f:
            for l in f:
                parts = [p.strip() for p in l.strip().split("|") if p.strip()]
                if len(parts) >= 2 and not parts[0].startswith("#"):
                    glossary.append((parts[0], parts[1:]))

    results = []
    for video in args.videos:
        video = os.path.abspath(os.path.expanduser(video))
        print(f"检查 {os.path.basename(video)} …", flush=True)
        results.append(check_video(video, args, scanner, banned, glossary))
    report = render(results, args)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    must_total = 0
    for r in results:
        if "error" in r:
            print(f"{os.path.basename(r['video'])}：{r['error']}")
            continue
        n = sum(len(v["times"]) for v in r["must"].values())
        must_total += n
        cats = "、".join(r["must"]) or "无"
        print(f"{os.path.basename(r['video'])}：必须处理 {cats}")
    print(f"报告写在 {out}")
    if args.strict and must_total:
        sys.exit(1)


if __name__ == "__main__":
    main()
