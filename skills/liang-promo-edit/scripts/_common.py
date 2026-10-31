"""liang-promo-edit 各脚本共用的小工具。

ffmpeg 调用和时长探测（不依赖 ffprobe）、时间格式、带坐标的文字识别、台本表格解析、字数统计。
只用标准库。各脚本用 sys.path.insert 引入本文件，所以用 python3 -I 运行也能找到。
"""

import importlib.util
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OCR_JS = os.path.join(HERE, "ocr_boxes.js")
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}

# 统计字数时去掉的空白和标点。英文字母、数字各算一个字，和校准记录里的口径一致。
_PUNCT = r"[\s，。、；：？！,.!?;:「」『』“”\"'‘’（）()\[\]【】《》<>·\-—…/／|｜~～]"

# 输入法候选栏：「1.手机 2.收集 3.说……」这种连续编号
IME_RE = re.compile(r"1[.．]\s*\S{1,8}.{0,16}?2[.．]\s*\S{1,8}.{0,16}?3[.．]")


def ffmpeg_bin():
    return os.environ.get("LIANG_FFMPEG", "ffmpeg")


def run_ffmpeg(args, check=False):
    """所有 ffmpeg 调用都关闭标准输入，放进 shell 循环里也不会吃掉后面的输入行。"""
    result = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-nostdin", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-1200:])
    return result


def probe(path):
    """从 ffmpeg -i 的输出读时长、分辨率、帧率、视频编码、有没有声音。读不出返回 None。"""
    info = run_ffmpeg(["-i", path]).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    if not m:
        return None
    h, mi, s = m.groups()
    out = {"duration": int(h) * 3600 + int(mi) * 60 + float(s), "audio": "Audio:" in info}
    video = re.search(r"Video: (\w+)(.*)", info)
    if video:
        out["vcodec"] = video.group(1)
        rest = video.group(2)
        size = re.search(r"[ ,](\d{2,5})x(\d{2,5})[ ,\[]", rest + " ")
        if size:
            out["width"], out["height"] = int(size.group(1)), int(size.group(2))
        fps = re.search(r"([\d.]+) fps", rest)
        if fps:
            out["fps"] = float(fps.group(1))
    return out


def parse_time(value):
    """「65.5」「1:05.5」「0:01:05.5」都转成秒。"""
    text = str(value).strip().replace("：", ":")
    if not text:
        raise ValueError("空的时间")
    parts = text.split(":")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


def fmt_time(seconds, decimals=1):
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60)
    width = 3 + decimals if decimals else 2
    return f"{int(m)}:{s:0{width}.{decimals}f}"


def fmt_srt(seconds):
    ms = int(round(max(0.0, seconds) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def merge_ranges(values, gap=1.0):
    """把一串秒数合并成区间，相邻值间隔不超过 gap 的算一段。"""
    out = []
    for v in sorted(set(values)):
        if out and v - out[-1][1] <= gap:
            out[-1][1] = v
        else:
            out.append([v, v])
    return out


def fmt_ranges(ranges):
    parts = []
    for a, b in ranges:
        parts.append(fmt_time(a, 0) if b - a < 0.5 else f"{fmt_time(a, 0)}–{fmt_time(b, 0)}")
    return "、".join(parts)


def count_chars(text):
    return len(re.sub(_PUNCT, "", text or ""))


def norm_text(text):
    return re.sub(_PUNCT, "", text or "")


def find_sibling(skill, relpath):
    """找同一安装根目录下兄弟 skill 的文件，再找 Claude 和 Codex 的安装目录。"""
    candidates = [
        os.path.join(HERE, "..", "..", skill, relpath),
        os.path.expanduser(os.path.join("~/.claude/skills", skill, relpath)),
        os.path.expanduser(os.path.join("~/.codex/skills", skill, relpath)),
    ]
    for path in candidates:
        if os.path.exists(path):
            return os.path.abspath(path)
    return None


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract_frame(src, t, out_path, width=None):
    vf = ["-vf", f"scale={width}:-2"] if width else []
    result = run_ffmpeg(["-loglevel", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", src,
                         "-frames:v", "1", *vf, "-q:v", "2", out_path])
    return result.returncode == 0 and os.path.exists(out_path)


def ocr_images(paths, batch=20, jobs=2):
    """批量识别，返回 ({文件名: [文字块]}, [错误])。只支持 macOS。jobs 是同时跑的批数。"""
    from concurrent.futures import ThreadPoolExecutor

    def one(i):
        chunk = paths[i:i + batch]
        return i, subprocess.run(
            ["osascript", "-l", "JavaScript", OCR_JS, *chunk],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
        )

    found, errors = {}, []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = list(pool.map(one, range(0, len(paths), batch)))
    for i, result in results:
        if result.returncode != 0:
            errors.append(f"第 {i + 1} 张起的一批失败：{result.stderr.strip()[:300]}")
            continue
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"识别结果解析失败：{line[:120]}")
                continue
            found[obj["file"]] = obj["items"]
    return found, errors


def group_lines(items, ytol=0.012):
    """把文字块按纵坐标归成行，行内从左到右。返回 [{t, x, y, w, h, cx, cy}]。"""
    blocks = sorted(items, key=lambda it: (it["y"] + it["h"] / 2, it["x"]))
    lines = []
    for it in blocks:
        cy = it["y"] + it["h"] / 2
        if lines and abs(lines[-1]["_cy"] - cy) <= max(ytol, it["h"] / 2):
            lines[-1]["_items"].append(it)
        else:
            lines.append({"_cy": cy, "_items": [it]})
    out = []
    for line in lines:
        its = sorted(line["_items"], key=lambda it: it["x"])
        x0 = min(it["x"] for it in its)
        y0 = min(it["y"] for it in its)
        x1 = max(it["x"] + it["w"] for it in its)
        y1 = max(it["y"] + it["h"] for it in its)
        out.append({"t": " | ".join(it["t"] for it in its), "x": x0, "y": y0, "w": x1 - x0,
                    "h": y1 - y0, "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2})
    return out


def parse_md_tables(path):
    """解析 Markdown 文件里的所有表格，返回 [(表头, [行字典])]。单元格里的 \\| 当作字面竖线。"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    tables, i = [], 0
    while i < len(lines):
        line = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if line.startswith("|") and re.match(r"^\|?\s*:?-{2,}", nxt):
            header = _split_row(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = _split_row(lines[i].strip())
                cells += [""] * (len(header) - len(cells))
                rows.append(dict(zip(header, cells)))
                i += 1
            tables.append((header, rows))
        else:
            i += 1
    return tables


def _split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells = re.split(r"(?<!\\)\|", line)
    return [c.strip().replace("\\|", "|") for c in cells]


def pick_table(path, required):
    for header, rows in parse_md_tables(path):
        if all(col in header for col in required):
            return header, rows
    return None, []


def safe_name(text, limit=24):
    text = re.sub(r"[\\/:*?\"<>|\s]+", "_", text.strip())
    return text[:limit].strip("_") or "片段"


def join_clips(items, out_path, work_dir, size="960x540", fps=30, dissolve=0.5, flash=0.15, crf=23):
    """把片段按顺序接起来，支持叠化和闪黑。

    items：[{"file": 路径, "duration": 秒, "trans": "切"|"叠化"|"闪黑", "name": 名字}]，trans 是进入这一段的方式。
    做法是逐段渲染小片段再无损拼接，旧版 ffmpeg 也稳：叠化用 blend 混合前一段的尾和后一段的头，闪黑用淡入淡出。
    返回成片路径；某段太短放不下叠化时抛 ValueError。
    """
    pw, ph = [int(x) for x in size.split("x")]
    D, fl = dissolve, flash
    norm = (f"fps={fps},scale={pw}:{ph}:force_original_aspect_ratio=decrease,"
            f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p")
    enc = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-r", str(fps)]
    os.makedirs(work_dir, exist_ok=True)
    for old in os.listdir(work_dir):
        os.remove(os.path.join(work_dir, old))

    def run(args):
        result = run_ffmpeg(["-loglevel", "error", "-y", *args])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip()[-800:])

    pieces = []
    for i, it in enumerate(items):
        d = it["duration"]
        head = it.get("trans") == "叠化" and i > 0
        tail = i + 1 < len(items) and items[i + 1].get("trans") == "叠化"
        if (head + tail) * D >= d - 0.05:
            raise ValueError(f"{it.get('name', i)} 只有 {d:.2f} 秒，放不下叠化，改成切或加长这段")
        if head:
            prev = items[i - 1]
            x_path = os.path.join(work_dir, f"{len(pieces):03d}_叠化.mp4")
            run(["-ss", f"{prev['duration'] - D:.3f}", "-i", prev["file"], "-i", it["file"], "-filter_complex",
                 f"[0:v]{norm},trim=0:{D:.3f},setpts=PTS-STARTPTS[a];"
                 f"[1:v]{norm},trim=0:{D:.3f},setpts=PTS-STARTPTS[b];"
                 f"[a][b]blend=all_expr='A*(1-T/{D})+B*(T/{D})',trim=0:{D:.3f}[v]",
                 "-map", "[v]", *enc, x_path])
            pieces.append(x_path)
        b0, b1 = (D if head else 0.0), (d - D if tail else d)
        vf = f"{norm},trim={b0:.3f}:{b1:.3f},setpts=PTS-STARTPTS"
        if it.get("trans") == "闪黑" and i > 0:
            vf += f",fade=t=in:st=0:d={fl}"
        if i + 1 < len(items) and items[i + 1].get("trans") == "闪黑":
            vf += f",fade=t=out:st={max(b1 - b0 - fl, 0):.3f}:d={fl}"
        body = os.path.join(work_dir, f"{len(pieces):03d}_{safe_name(str(it.get('name', i)))}.mp4")
        run(["-i", it["file"], "-vf", vf, *enc, body])
        pieces.append(body)
    list_path = os.path.join(work_dir, "片段清单.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in pieces:
            f.write("file '" + p.replace("'", "'\\''") + "'\n")
    run(["-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", "-movflags", "+faststart", out_path])
    return out_path


def timeline(items, dissolve=0.5):
    """按 join_clips 的接法算每段在成片里的起止。叠化让后一段提前 dissolve 秒开始。"""
    pos, out = 0.0, []
    for i, it in enumerate(items):
        if i and it.get("trans") == "叠化":
            pos -= dissolve
        out.append((round(pos, 3), round(pos + it["duration"], 3)))
        pos += it["duration"]
    return out


def default_work(out_path, name="发布前检查"):
    """抽帧和识别缓存的默认位置：报告旁边的 制作过程/<name>；报告本身就在 制作过程 里时不再套一层。"""
    base = os.path.dirname(os.path.abspath(os.path.expanduser(out_path)))
    if os.path.basename(base) == "制作过程":
        return os.path.join(base, name)
    return os.path.join(base, "制作过程", name)


CALIB_PATH = os.path.join(HERE, "..", "references", "校准记录_脱敏版.md")


def calib_default(param, fallback):
    """从 references/校准记录_脱敏版.md 的「当前默认值」表里读一个数，读不到就用 fallback。

    param 写参数列里的原文，例如「make_subtitles.py --rate」；值取「值」列里的第一个数。
    这样复盘时只改校准记录，脚本的默认值就跟着变。
    """
    if not os.path.exists(CALIB_PATH):
        return fallback
    for header, rows in parse_md_tables(CALIB_PATH):
        if "参数" not in header or "值" not in header:
            continue
        for row in rows:
            if param in row["参数"].replace("`", ""):
                m = re.search(r"-?\d+(?:\.\d+)?", row["值"])
                if m:
                    return float(m.group(0))
    return fallback


def gray_thumb(path, t=None, size=(128, 72)):
    """取一帧缩成灰度小图，返回字节串，用来比两张画面像不像。path 可以是图片或视频（视频要给 t）。"""
    args = ["-loglevel", "error"]
    if t is not None:
        args += ["-ss", f"{max(0.0, t):.3f}"]
    args += ["-i", path, "-frames:v", "1", "-vf", f"scale={size[0]}:{size[1]},format=gray",
             "-f", "rawvideo", "-"]
    result = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostdin", *args],
                            stdin=subprocess.DEVNULL, capture_output=True)
    data = result.stdout
    return data if len(data) == size[0] * size[1] else None


def thumb_diff(a, b, level=16):
    """两张灰度小图里，亮度差超过 level 的像素占百分之几（0–100）。

    只亮了一张卡片这种局部变化，平均差很小，但变化像素的占比能看出来；压缩噪点很少超过 level。
    """
    if not a or not b or len(a) != len(b):
        return 100.0
    return 100.0 * sum(1 for x, y in zip(a, b) if abs(x - y) > level) / len(a)
