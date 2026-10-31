#!/usr/bin/env python3
"""把定稿排成公众号样式：输出带「复制到公众号」按钮的预览页，被复制的片段全部是行内样式。

用法：
  python3 render_wechat.py <稿件.md> [--theme default|card|主题.json] [--out 目录或文件.html] [--open] [--copy] [--no-embed]
  python3 render_wechat.py <稿件.md> --watch [--port 8765] [其他参数同上]
  python3 render_wechat.py --check-file <片段.html>

两套版式，由主题里的 layout 决定：
  - skew（默认）：蓝色斜块编号小节标题、橙色重点，见 themes/default.json。
  - card：编号在上、标题两行的小节标题，整段重点排成左侧色条的提示框，全文最后一段整段重点排成淡色收尾卡，
    列表合进一个底色框，正文前加一张标题卡，见 themes/card.json。主题只写 "layout": "card" 和要改的键也行。

--watch：起一个本机预览服务（127.0.0.1），稿件、主题或配图保存后重新排版，打开的页面自动刷新并停在原来的位置。
写到磁盘的预览页不带刷新脚本，照常可以转给别人。Ctrl+C 退出。

稿件写法：
  - 第一个非空行是「# 标题」时只当标题用，不进正文（公众号后台有单独的标题栏）。
  - 一行一段，空行可有可无。
  - 「## 小节名」排成编号小节标题，编号按出现顺序生成，标题自带的「01」「一、」「1.」会去掉。
    后面再出现的「# 标题」也按小节处理。
  - 「### 小标题」排成蓝色加粗短标题。
  - 「**整句**」排成橙色加粗重点，可以是整段，也可以是半句。
  - 单独一行的「![说明](地址)」：https 地址直接出图；本地路径（相对稿件所在目录）压缩后嵌进页面，
    宽度超过 1440 的缩到 1440，macOS 上不透明的图转 JPEG，复制时随正文一起带走。
    找不到文件或加了 --no-embed 时出占位框，粘贴后手动插图。
  - 「> 引用」连续几行合成一个引用块；「- 列表」每项转成带「·」的段落；「---」是一处空行。
  - 有小节时，第一个小节之前的段落是导语，行高 1.5 倍；其余正文行高 2 倍。

输入在「制作过程/」里时（例如标记稿），预览页默认写到上一级目录，文件名去掉「_标记稿」。
静态检查不过时退出码为 1。
"""

import argparse
import base64
import html
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME_DIR = os.path.join(SKILL_DIR, "themes")

# 小节标题自带的编号：「01 」「1. 」「一、」「02｜」。不碰「10 倍」「3.5 倍」「2026年」「三个月」这类正文
HEADING_NUM = re.compile(
    r"^(?:(?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*(?:[、:：|｜)）]|[.．](?!\d))\s*|0\d\s+)"
)
IMAGE_LINE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
BULLET = re.compile(r"[-*+]\s+")
RULE = re.compile(r"(?:-{3,}|\*{3,}|_{3,})")
STRONG = re.compile(r"\*\*(.+?)\*\*")
# 整段都是重点：「**……**」中间没有别的 **
WHOLE_STRONG = re.compile(r"\*\*((?:(?!\*\*).)+)\*\*")
# 小节编号的样式固定，检查时靠这个认出编号。斜块版式 24px、600 字重；卡片版式 12px 加粗、2px 字距
NUMBER_STYLE = "font-size:24px;font-weight:600;line-height:33px;letter-spacing:0;vertical-align:top;"
CARD_NUMBER_STYLE = "font-size:12px;font-weight:bold;letter-spacing:2px;line-height:1.6;"
# 预览页图宽最多 677px，Mac 的 2 倍屏要 1354 像素，取 1440。不能按公众号发给读者的 1080 来缩：
# 2026-10-23 缩到 1080 后，预览页在 Mac 上被放大 1.25 倍，用户反馈发糊。公众号收下以后会自己缩到 1080
MAX_IMAGE_WIDTH = 1440
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}

FORBIDDEN = [
    ("<style", "有 <style> 标签，复制时会丢"),
    ("<script", "有 <script>，公众号会清掉"),
    ("<link", "引用了外部样式表"),
    (" class=", "用了 class，复制后样式会丢"),
    (" id=", "用了 id，复制后样式会丢"),
    (":before", "用了伪元素"),
    (":after", "用了伪元素"),
    ("@import", "用了 @import"),
    ("position:fixed", "用了 position:fixed"),
    ("position: fixed", "用了 position:fixed"),
]


def theme_file(value):
    if not value or value == "default":
        return None
    return os.path.abspath(value if value.endswith(".json") else os.path.join(THEME_DIR, value + ".json"))


def load_theme(value):
    """默认主题打底；自定义主题换了 layout 时，先铺那套版式自带的主题，再盖自定义的键。"""
    def read(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    theme = read(os.path.join(THEME_DIR, "default.json"))
    path = theme_file(value)
    if path:
        custom = read(path)
        layout = custom.get("layout", theme["layout"])
        base = os.path.join(THEME_DIR, f"{layout}.json")
        if layout != theme["layout"] and os.path.isfile(base) and base != path:
            theme.update(read(base))
        theme.update(custom)
    return theme


def parse(text):
    """返回 (标题, 块列表)。块是 (类型, 内容...)，类型有 h2 sub p li quote img gap。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    title = None
    if i < len(lines) and re.match(r"#\s+", lines[i].strip()):
        title = lines[i].strip()[1:].strip()
        i += 1

    blocks = []
    quote = []
    for raw in lines[i:] + [""]:
        s = raw.strip()
        if s.startswith(">"):
            quote.append(s[1:].strip())
            continue
        if quote:
            blocks.append(("quote", [q for q in quote if q]))
            quote = []
        if not s:
            continue
        m = IMAGE_LINE.fullmatch(s)
        if s.startswith("### "):
            blocks.append(("sub", s[4:].strip()))
        elif s.startswith("## ") or s.startswith("# "):
            blocks.append(("h2", HEADING_NUM.sub("", s.lstrip("#").strip())))
        elif RULE.fullmatch(s):
            blocks.append(("gap",))
        elif m:
            blocks.append(("img", m.group(1).strip(), m.group(2).strip()))
        elif BULLET.match(s):
            blocks.append(("li", BULLET.sub("", s, count=1)))
        else:
            blocks.append(("p", s))
    return title, blocks


def inline(text, t):
    escaped = html.escape(text, quote=False)
    return STRONG.sub(
        lambda m: f'<span style="font-weight:bold;color:{t["accent"]};">{m.group(1)}</span>',
        escaped,
    )


def text_style(t):
    color = f'color:{t["text_color"]};' if t.get("text_color") else ""
    return f'font-size:{t["text_size"]};letter-spacing:{t["letter_spacing"]};{color}'


def para(text, t, lead):
    lh = t["lead_line_height"] if lead else t["line_height"]
    # 卡片版式的行高是倍数，区块上也写字号，行高才按正文字号算，不跟后台容器的 17px
    size = f'font-size:{t["text_size"]};' if t["layout"] == "card" else ""
    return (
        f'<section style="margin:0 {t["side_margin"]} {t["para_gap"]};{size}line-height:{lh};text-align:{t["text_align"]};">'
        f'<span style="{text_style(t)}">{inline(text, t)}</span></section>'
    )


def spacer(t):
    return (
        f'<section style="margin:0 0 {t["para_gap"]};line-height:{t["line_height"]};">'
        f'<span style="font-size:{t["text_size"]};"><br></span></section>'
    )


def heading(n, text, t):
    skew = t["heading_skew"]
    unskew = skew[1:] if skew.startswith("-") else "-" + skew
    block, bar = t["heading_block"], t["heading_bar"]
    # 后台清掉渐变时退回纯色底；清掉 transform 时退回直角色块，都还能读
    bar_bg = (
        f'background-color:{t["heading_bar_fallback"]};'
        f"background-image:linear-gradient({block},{block}),"
        f"linear-gradient(90deg,{bar} 0%,{bar} 30%,#FFFFFF 100%);"
        "background-size:64px 4px,100% 100%;background-repeat:no-repeat;background-position:0 0,0 0;"
    )
    return (
        f'<section style="margin:0 0 {t["para_gap"]};padding:0 10px 0 14px;">'
        f'<section style="display:flex;align-items:stretch;transform:skewX({skew});">'
        f'<section style="flex-shrink:0;padding:3px 14px 4px;line-height:33px;background-color:{block};">'
        f'<span style="display:inline-block;transform:skewX({unskew});{NUMBER_STYLE}color:{t["heading_number"]};">{n:02d}</span>'
        "</section>"
        f'<section style="flex:1;min-width:0;padding:12px 10px 6px 14px;line-height:22px;{bar_bg}">'
        f'<span style="display:inline-block;vertical-align:top;transform:skewX({unskew});font-size:18px;font-weight:bold;'
        f'line-height:22px;letter-spacing:0;color:{t["heading_text"]};">{html.escape(text, quote=False)}</span>'
        "</section></section></section>"
    )


def subheading(text, t):
    return (
        f'<section style="margin:0 {t["side_margin"]} {t["para_gap"]};line-height:1.6em;">'
        f'<span style="font-size:{t["subheading_size"]};font-weight:bold;letter-spacing:{t["letter_spacing"]};'
        f'color:{t["heading_text"]};">{html.escape(text, quote=False)}</span></section>'
    )


def quote_block(lines, t):
    body = "<br>".join(inline(q, t) for q in lines)
    return (
        f'<section style="margin:0 {t["side_margin"]} {t["para_gap"]};padding:10px 14px;'
        f'border-left:3px solid {t["quote_border"]};background-color:{t["quote_bg"]};line-height:1.8em;text-align:justify;">'
        f'<span style="font-size:15px;letter-spacing:{t["letter_spacing"]};color:{t["quote_text"]};">{body}</span></section>'
    )


# 卡片版式的组件。尺寸照参考文章实测（references/样式规格.md「卡片版式」），颜色走主题


def split_line(text):
    """在最靠近中间的「，」后断成两行；没有逗号时第二行为空。"""
    spots = [i for i, ch in enumerate(text) if ch == "，" and i < len(text) - 1]
    if not spots:
        return text, ""
    i = min(spots, key=lambda i: abs(i + 1 - len(text) / 2))
    return text[: i + 1], text[i + 1:]


def title_card(title, t):
    """正文前的标题卡：浅色渐变底，标题每个分句一行，最后一句用强调色，下面一段短色条。"""
    esc = lambda s: html.escape(s, quote=False)
    clauses = [c for c in re.split(r"(?<=，)", title) if c]
    title_html = esc(title)
    if len(clauses) > 1:
        title_html = "<br>".join(esc(c) for c in clauses[:-1]) + f'<br><span style="color:{t["accent"]};">{esc(clauses[-1])}</span>'

    label = ""
    if t.get("title_card_label"):
        label = (
            f'<section style="margin:0 0 16px;font-size:12px;line-height:1.6;"><span style="font-size:12px;font-weight:bold;'
            f'letter-spacing:2px;color:{t["accent"]};">{esc(t["title_card_label"])}</span></section>'
        )
    top, mid = t["title_card_top"], t["title_card_mid"]
    return (
        f'<section style="margin:0 {t["side_margin"]} 30px;padding:28px 20px 26px;border-radius:4px;line-height:1.45;text-align:left;'
        f'background-color:{mid};background-image:linear-gradient({top} 0%,{mid} 60%,#FFFFFF 100%);">'
        f"{label}"
        f'<section style="margin:0;font-size:24px;line-height:1.45;"><span style="font-size:24px;font-weight:bold;letter-spacing:0.5px;'
        f'color:{t["heading_text"]};">{title_html}</span></section>'
        f'<section style="margin:18px 0 0;width:36px;height:3px;border-radius:2px;background-color:{t["accent"]};'
        'font-size:0;line-height:0;"><br></section></section>'
    )


def card_heading(n, text, t):
    """编号一行，标题在逗号处断两行，后一行用强调色。"""
    first, second = split_line(html.escape(text, quote=False))
    lines = f'<section style="margin:0;line-height:1.45;"><span style="color:{t["heading_text"]};">{first}</span></section>'
    if second:
        lines += f'<section style="margin:0;line-height:1.45;"><span style="color:{t["accent"]};">{second}</span></section>'
    return (
        f'<section style="margin:44px {t["side_margin"]} 16px;line-height:1.45;text-align:left;">'
        f'<section style="margin:0 0 8px;font-size:12px;line-height:1.6;"><span style="{CARD_NUMBER_STYLE}color:{t["accent"]};">{n:02d}</span></section>'
        f'<section style="margin:0;font-size:{t["heading_size"]};font-weight:bold;letter-spacing:0.5px;line-height:1.45;">{lines}</section>'
        "</section>"
    )


def callout(text, t):
    """整段重点：浅色底、左侧色条、黑色加粗。"""
    return (
        f'<section style="margin:6px {t["side_margin"]} 24px;padding:16px 18px;background-color:{t["callout_bg"]};'
        f'border-left:3px solid {t["accent"]};border-radius:0 10px 10px 0;font-size:15px;line-height:1.8;text-align:left;">'
        f'<span style="font-size:15px;font-weight:bold;letter-spacing:0.5px;color:{t["heading_text"]};">{inline(text, t)}</span></section>'
    )


def ending_card(text, t):
    """全文最后一段整段重点：和提示框同一种淡色底、强调色字居中，不带左侧色条；在逗号处断行，窄屏上只在标点处折行。
    2026-10-22 起用户嫌参考文章的强调色实底白字太重，改成淡色。"""
    first, second = split_line(html.escape(text, quote=False))
    body = f"{first}<br>{second}" if second else first
    return (
        f'<section style="margin:10px {t["side_margin"]} 28px;padding:26px 20px;background-color:{t["callout_bg"]};'
        'border-radius:14px;font-size:16px;line-height:1.9;text-align:center;word-break:keep-all;overflow-wrap:break-word;">'
        f'<span style="font-size:16px;font-weight:bold;letter-spacing:1px;color:{t["accent"]};">{body}</span></section>'
    )


def bullet_box(items, t):
    """连续的列表项合进一个底色框，每项前面一个强调色的「▸」。"""
    rows = "".join(
        f'<section style="margin:0 0 10px;padding-left:16px;text-indent:-16px;font-size:14px;line-height:1.75;">'
        f'<span style="font-size:11px;color:{t["accent"]};">▸&nbsp;&nbsp;</span>'
        f'<span style="font-size:14px;letter-spacing:0.5px;color:{t["text_color"]};">{inline(x, t)}</span></section>'
        for x in items
    )
    return (
        f'<section style="margin:4px {t["side_margin"]} 24px;padding:16px 18px 6px;background-color:{t["box_bg"]};'
        f'border-radius:12px;font-size:14px;line-height:1.75;text-align:left;">{rows}</section>'
    )


def note_box(lines, t):
    """引用：底色框，14px 正文色。"""
    body = "<br>".join(inline(q, t) for q in lines)
    return (
        f'<section style="margin:4px {t["side_margin"]} 24px;padding:14px 18px;background-color:{t["box_bg"]};'
        'border-radius:12px;font-size:14px;line-height:1.8;text-align:left;">'
        f'<span style="font-size:14px;letter-spacing:0.5px;color:{t["text_color"]};">{body}</span></section>'
    )


def load_image(path):
    """本地图片转成 data URI。macOS 上用 sips 把宽度缩到 MAX_IMAGE_WIDTH，格式不变；GIF 原样保留。
    PNG 不转 JPEG：公众号发给读者时还要再压一遍（浏览器里是有损 WebP，JPEG 原图链接约质量 80），
    先转一道 JPEG 等于多压一次，深色界面截图里的字会发糊。"""
    ext = os.path.splitext(path)[1].lower()
    mime = MIME.get(ext)
    if not mime:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        data_path = path
        if ext != ".gif" and shutil.which("sips"):
            info = subprocess.run(["sips", "-g", "pixelWidth", path], capture_output=True, text=True).stdout
            m = re.search(r"pixelWidth:\s*(\d+)", info)
            if m and int(m.group(1)) > MAX_IMAGE_WIDTH:
                out = os.path.join(tmp, "img" + ext)
                cmd = ["sips", "--resampleWidth", str(MAX_IMAGE_WIDTH)]
                if mime == "image/jpeg":
                    cmd += ["-s", "formatOptions", "92"]
                cmd += [path, "--out", out]
                if subprocess.run(cmd, capture_output=True).returncode == 0 and os.path.isfile(out):
                    data_path = out
        with open(data_path, "rb") as f:
            data = f.read()
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def image(alt, src, t, data_uri=None):
    if data_uri or re.match(r"https?://", src):
        return (
            f'<section style="margin:0 {t["side_margin"]} {t["para_gap"]};line-height:0;font-size:0;text-align:center;">'
            f'<img src="{html.escape(data_uri or src)}" alt="{html.escape(alt)}" style="display:block;width:100%;height:auto;"></section>'
        )
    label = f"【此处插入图片】{alt}（{os.path.basename(src)}）" if alt else f"【此处插入图片】{os.path.basename(src)}"
    return (
        f'<section style="margin:0 {t["side_margin"]} {t["para_gap"]};padding:28px 12px;'
        f'border:1px dashed {t["placeholder_border"]};background-color:{t["placeholder_bg"]};line-height:1.6em;text-align:center;">'
        f'<span style="font-size:14px;letter-spacing:0;color:{t["placeholder_text"]};">{html.escape(label, quote=False)}</span></section>'
    )


def render(blocks, t, base_dir=".", embed=True, title=None):
    card = t["layout"] == "card"
    has_sections = any(b[0] == "h2" for b in blocks)
    lead = has_sections
    last_para = max((i for i, b in enumerate(blocks) if b[0] == "p"), default=-1)
    out = [title_card(title, t)] if card and title and t.get("title_card") else []
    stats = {"sections": 0, "paragraphs": 0, "highlighted": 0, "embedded": [], "missing": [],
             "placeholders": [], "remote_images": [], "title_card": bool(out)}
    i = 0
    while i < len(blocks):
        b = blocks[i]
        kind = b[0]
        i += 1
        if kind == "h2":
            stats["sections"] += 1
            lead = False
            if card:
                out.append(card_heading(stats["sections"], b[1], t))
                continue
            if out:
                out.append(spacer(t))
            out.append(heading(stats["sections"], b[1], t))
        elif kind == "li" and card:
            items = [b[1]]
            while i < len(blocks) and blocks[i][0] == "li":
                items.append(blocks[i][1])
                i += 1
            stats["paragraphs"] += len(items)
            stats["highlighted"] += sum(1 for x in items if STRONG.search(x))
            out.append(bullet_box(items, t))
        elif kind in ("p", "li"):
            text = b[1] if kind == "p" else "· " + b[1]
            stats["paragraphs"] += 1
            if STRONG.search(text):
                stats["highlighted"] += 1
            whole = WHOLE_STRONG.fullmatch(text) if card else None
            if whole and i - 1 == last_para:
                out.append(ending_card(whole.group(1), t))
            elif whole:
                out.append(callout(whole.group(1), t))
            else:
                out.append(para(text, t, lead))
        elif kind == "sub":
            out.append(subheading(b[1], t))
        elif kind == "quote":
            out.append(note_box(b[1], t) if card else quote_block(b[1], t))
        elif kind == "img":
            alt, src = b[1], b[2]
            data_uri = None
            if re.match(r"https?://", src):
                stats["remote_images"].append((alt, src))
            else:
                local = os.path.join(base_dir, unquote(src))
                if not os.path.isfile(local):
                    stats["missing"].append((alt, src))
                elif embed:
                    data_uri = load_image(local)
                (stats["embedded"] if data_uri else stats["placeholders"]).append((alt, src))
            out.append(image(alt, src, t, data_uri))
        elif kind == "gap":
            out.append(spacer(t))
    return "\n".join(out), stats


def check_fragment(fragment):
    """片段的静态检查，返回错误列表。片段按 render 的约定一块一行。"""
    errors = []
    low = fragment.lower()
    for pattern, message in FORBIDDEN:
        if pattern in low:
            errors.append(message)
    for m in re.finditer(r"<(section|span|img)(\s[^>]*)?>", fragment):
        if 'style="' not in (m.group(2) or ""):
            errors.append(f"缺行内样式：{m.group(0)[:60]}")
    for m in re.finditer(r'<img[^>]*?src="([^"]*)"', fragment):
        if not re.match(r"https?://|data:image/", m.group(1)):
            errors.append(f"图片既不是公网地址也没嵌入，粘贴后会丢：{m.group(1)}")
    for n, line in enumerate(fragment.splitlines(), 1):
        if not line.startswith("<section"):
            continue
        if "<img" in line:
            if "width:100%" not in line:
                errors.append(f"第 {n} 块图片没有通栏宽度")
        elif "font-size" not in line or "line-height" not in line:
            errors.append(f"第 {n} 块缺字号或行高，粘贴后会跟着后台默认走")
    plain = re.sub(r"<[^>]+>", "", fragment)
    if "**" in plain:
        errors.append("有没配对的 **，重点标记没转成样式")
    number_style = "(?:" + re.escape(NUMBER_STYLE) + "|" + re.escape(CARD_NUMBER_STYLE) + ")"
    numbers = [int(x) for x in re.findall(number_style + r'[^"]*">(\d+)</span>', fragment)]
    if numbers != list(range(1, len(numbers) + 1)):
        errors.append(f"小节编号不连续：{numbers}")
    return errors


def plain_text(fragment):
    text = re.sub(r"<br>", "\n", fragment)
    text = re.sub(r"</section>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\n{2,}", "\n\n", text).strip() + "\n"


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  /* 宽度照公众号网页版（2026-10-22 实测）：正文栏最宽 677px 居中，两侧留 20px；手机上同样的规则得到 350px 宽的正文。
     网页版两侧是白的，用户要求用色块把正文栏衬出来，两侧用微信界面的底灰 #EDEDED（weui 的 BG-0） */
  body {{ margin: 0; background: #EDEDED; font-family: -apple-system, "PingFang SC", sans-serif; }}
  .bar {{ position: sticky; top: 0; z-index: 1; background: #FFFFFF; border-bottom: 1px solid #E5E6EB; padding: 12px 20px; }}
  .row {{ max-width: 677px; margin: 0 auto; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }}
  .row strong {{ flex: 1 1 240px; min-width: 0; font-size: 15px; color: #1D2129; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .btns {{ display: flex; gap: 12px; }}
  button {{ border: 0; border-radius: 6px; padding: 9px 18px; background: #07C160; color: #FFFFFF; font-size: 15px; cursor: pointer; }}
  button.ghost {{ background: #FFFFFF; color: #07C160; box-shadow: inset 0 0 0 1px #07C160; }}
  .hint {{ max-width: 677px; margin: 8px auto 0; font-size: 13px; line-height: 1.6; color: #4E5969; }}
  .page {{ max-width: 677px; margin: 0 auto; padding: 0 20px; background: #FFFFFF; min-height: 100vh; }}
  .page h1 {{ margin: 0; padding: 24px 0 8px; font-size: 22px; line-height: 1.4; color: rgba(0,0,0,0.9); }}
  .page .meta {{ padding: 0 0 20px; font-size: 15px; color: rgba(0,0,0,0.3); }}
  @media (max-width: 600px) {{ .btns {{ flex: 1 1 100%; }} button {{ flex: 1; padding: 9px 12px; }} }}
</style>
</head>
<body>
<div class="bar">
  <div class="row"><strong>{title}</strong><div class="btns"><button id="copy-title" class="ghost" type="button">① 复制标题</button><button id="copy" type="button">② 复制正文到公众号</button></div></div>
  <div class="hint" id="status">{hint}</div>
</div>
<div class="page">
  <h1>{title}</h1>
  <div class="meta">预览（标题和这一行不会被复制）</div>
  <div id="wx" style="padding:0 0 48px;font-size:17px;line-height:1.6;color:rgba(0,0,0,0.9);text-align:justify;word-wrap:break-word;font-family:'PingFang SC',system-ui,-apple-system,'Helvetica Neue','Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif;">
{fragment}
  </div>
</div>
<script>
const TITLE = {title_json};
const wx = document.getElementById("wx");
// 被复制的片段就是 #wx 里的内容，不另存一份，嵌入图片时页面体积不翻倍
const FRAGMENT = wx.innerHTML.trim();
const status = document.getElementById("status");
// 发布的人可能用 Windows，提示里的快捷键按系统写
const MOD = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "Cmd" : "Ctrl";
function report(ok) {{
  status.textContent = ok
    ? `正文已复制。在后台正文区粘贴（${{MOD}}+V），图片都显示出来以后再保存。图清不清楚以手机预览为准。`
    : `自动复制没成功，正文已经替你选中了：直接按 ${{MOD}}+C 复制，再去后台粘贴。`;
}}
function textCopy(text) {{
  const area = document.createElement("textarea");
  area.value = text;
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
  area.remove();
  return ok;
}}
document.getElementById("copy-title").addEventListener("click", async () => {{
  let ok = true;
  try {{ await navigator.clipboard.writeText(TITLE); }} catch (e) {{ ok = textCopy(TITLE); }}
  status.textContent = ok
    ? "标题已复制，粘到后台的标题栏，再点 ② 复制正文。"
    : "标题复制没成功，手动选中上面的标题复制。";
}});
function selectionCopy() {{
  const range = document.createRange();
  range.selectNodeContents(wx);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  let ok = false;
  try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
  // 没复制成功就留着选区，让人手动复制；自己按全选会把顶栏和预览标题一起选进去
  if (ok) sel.removeAllRanges();
  return ok;
}}
document.getElementById("copy").addEventListener("click", async () => {{
  try {{
    await navigator.clipboard.write([new ClipboardItem({{
      "text/html": new Blob(['<meta charset="utf-8">' + FRAGMENT], {{ type: "text/html" }}),
      "text/plain": new Blob([wx.innerText], {{ type: "text/plain" }}),
    }})]);
    report(true);
  }} catch (e) {{
    report(selectionCopy());
  }}
}});
</script>
</body>
</html>
"""

JXA_COPY = r"""
ObjC.import("AppKit");
function run(argv) {
  const read = (p) => $.NSString.stringWithContentsOfFileEncodingError(p, $.NSUTF8StringEncoding, null);
  const htmlText = read(argv[0]);
  const plain = read(argv[1]);
  const pb = $.NSPasteboard.generalPasteboard;
  pb.clearContents;
  pb.setStringForType(htmlText, $.NSPasteboardTypeHTML);
  pb.setStringForType(plain, $.NSPasteboardTypeString);
  const back = pb.stringForType($.NSPasteboardTypeHTML);
  return back.isEqualToString(htmlText) ? "ok" : "mismatch";
}
"""


def copy_to_clipboard(fragment):
    """macOS：把片段以 HTML 类型写进剪贴板并回读核对。"""
    if sys.platform != "darwin":
        return "skip：只支持 macOS，请用预览页的按钮复制"
    with tempfile.TemporaryDirectory() as tmp:
        html_path = os.path.join(tmp, "fragment.html")
        text_path = os.path.join(tmp, "fragment.txt")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write('<meta charset="utf-8">' + fragment)
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(plain_text(fragment))
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", JXA_COPY, html_path, text_path],
            capture_output=True, text=True,
        )
    return result.stdout.strip() or result.stderr.strip()


def output_path(src, out):
    src_dir = os.path.dirname(os.path.abspath(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    if stem.endswith("_标记稿"):
        stem = stem[: -len("_标记稿")]
    if out and out.endswith(".html"):
        return os.path.abspath(out)
    if out:
        target_dir = os.path.abspath(out)
    elif os.path.basename(src_dir) == "制作过程":
        target_dir = os.path.dirname(src_dir)
    else:
        target_dir = src_dir
    return os.path.join(target_dir, f"{stem}_公众号排版.html")


def build(args):
    """排一遍版并写出预览页，返回结果，不打印。"""
    theme = load_theme(args.theme)
    with open(args.draft, encoding="utf-8") as f:
        parsed_title, blocks = parse(f.read())
    title = parsed_title or os.path.splitext(os.path.basename(args.draft))[0].replace("_标记稿", "")
    base_dir = os.path.dirname(os.path.abspath(args.draft))
    fragment, stats = render(blocks, theme, base_dir, embed=not args.no_embed, title=parsed_title)

    pictures = f"图片 {len(stats['embedded']) + len(stats['remote_images'])} 张已带上"
    if stats["placeholders"]:
        pictures += f"，{len(stats['placeholders'])} 处占位要手动插图"
    hint = (
        f"{stats['sections']} 个小节 · 重点 {stats['highlighted']} 段 · {pictures}。"
        "先点 ① 把标题粘到后台标题栏，再点 ② 把正文粘到正文区。"
    )
    page = PAGE.format(
        title=html.escape(title),
        hint=html.escape(hint),
        fragment=fragment,
        title_json=json.dumps(title, ensure_ascii=False).replace("</", "<\\/"),
    )
    path = output_path(args.draft, args.out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    # 实时预览要盯的文件：稿件、主题、本地配图（找不到的也盯，放进去就重排）
    local = [os.path.join(base_dir, unquote(src)) for _, src in stats["embedded"] + stats["placeholders"] + stats["missing"]]
    inputs = [os.path.abspath(args.draft)] + [p for p in [theme_file(args.theme)] if p] + local
    return {"title": title, "fragment": fragment, "stats": stats, "page": page, "path": path,
            "errors": check_fragment(fragment), "inputs": inputs}


def report(result):
    title, stats, path, errors = result["title"], result["stats"], result["path"], result["errors"]
    ratio = stats["highlighted"] / stats["paragraphs"] if stats["paragraphs"] else 0
    print(f"预览页：{path}")
    if stats["title_card"]:
        print(f"标题：{title}（填到后台标题栏；正文开头另有一张标题卡）")
    else:
        print(f"标题：{title}（不进正文，填到后台标题栏）")
    print(f"小节 {stats['sections']} 个 · 段落 {stats['paragraphs']} 段 · 重点 {stats['highlighted']} 段（{ratio:.0%}）")
    if stats["embedded"]:
        print(f"嵌入图片 {len(stats['embedded'])} 张，页面 {os.path.getsize(path) / 1024 / 1024:.1f} MB")
    if stats["missing"]:
        print(f"找不到的图片 {len(stats['missing'])} 张（路径相对稿件所在目录）：")
        for alt, src in stats["missing"]:
            print(f"  - {src}")
    if stats["placeholders"]:
        print(f"图片占位 {len(stats['placeholders'])} 处，粘贴后手动插图：")
        for alt, src in stats["placeholders"]:
            print(f"  - {alt or '（无说明）'}（{src}）")
    if stats["remote_images"]:
        print(f"外链图片 {len(stats['remote_images'])} 张，后台转存失败时手动上传：")
        for alt, src in stats["remote_images"]:
            print(f"  - {src}")
    if stats["paragraphs"] and stats["highlighted"] == 0:
        print("提示：稿里没有 ** 重点标记，先按 SKILL.md Phase 2 挑重点句")
    elif ratio > 0.3:
        print("提示：重点段落超过三成，橙色会失去强调作用")
    for e in errors:
        print(f"✗ {e}")
    print("静态检查：" + ("通过" if not errors else f"{len(errors)} 处问题"))


LIVE_SCRIPT = """<script>
// 实时预览：每秒问一次版本号，变了就记下滚动位置再刷新。只有 --watch 送出的页面带这段，写到磁盘的预览页没有
(() => {
  const KEY = "wx-live-scroll";
  const SEEN = "__SEEN__";
  window.addEventListener("load", () => {
    try {
      const y = sessionStorage.getItem(KEY);
      if (y !== null) { sessionStorage.removeItem(KEY); window.scrollTo(0, Number(y)); }
    } catch (e) {}
  });
  document.getElementById("status").textContent += " 实时预览中：稿件、主题或配图保存后自动刷新。";
  setInterval(async () => {
    try {
      const v = await (await fetch("/__version", { cache: "no-store" })).text();
      if (v !== SEEN) {
        try { sessionStorage.setItem(KEY, String(window.scrollY)); } catch (e) {}
        location.reload();
      }
    } catch (e) {}
  }, 1000);
})();
</script>
"""


def watch(args):
    """本机预览服务：稿件、主题、配图一保存就重排，打开的页面自动刷新。"""
    sys.stdout.reconfigure(line_buffering=True)
    state = {"page": b"", "version": 0}

    def publish(result):
        state["version"] += 1
        live = LIVE_SCRIPT.replace("__SEEN__", str(state["version"]))
        state["page"] = result["page"].replace("</body>", live + "</body>").encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            route = self.path.split("?")[0]
            if route == "/__version":
                body, kind = str(state["version"]).encode(), "text/plain"
            elif route in ("/", "/index.html"):
                body, kind = state["page"], "text/html"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    def stamp(paths):
        return [os.stat(p).st_mtime_ns if os.path.exists(p) else None for p in paths]

    result = build(args)
    report(result)
    publish(result)
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:  # 端口被占（比如另一篇也在实时预览），换一个空闲的
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"实时预览：{url}（Ctrl+C 退出）")
    if args.copy and not result["errors"]:
        print(f"剪贴板：{copy_to_clipboard(result['fragment'])}（只在启动时写一次，之后用页面上的按钮复制）")
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", url], check=False)

    inputs, seen = result["inputs"], stamp(result["inputs"])
    try:
        while True:
            time.sleep(0.3)
            if stamp(inputs) == seen:
                continue
            time.sleep(0.2)  # 编辑器保存可能分几步写完，稍等再读
            seen = stamp(inputs)
            try:
                result = build(args)
            except Exception as e:  # 存到一半的稿子或主题可能读不了，页面留着上一版，下次保存再排
                print(f"{time.strftime('%H:%M:%S')} ✗ 重排失败，页面保持上一版：{e}")
                continue
            publish(result)
            inputs, seen = result["inputs"], stamp(result["inputs"])
            verdict = "静态检查：通过" if not result["errors"] else "✗ " + "；".join(result["errors"])
            print(f"{time.strftime('%H:%M:%S')} 已重排，页面会自动刷新。{verdict}")
    except KeyboardInterrupt:
        server.shutdown()
    return 0


def main():
    ap = argparse.ArgumentParser(description="把定稿排成公众号样式")
    ap.add_argument("draft", nargs="?", help="稿件 Markdown 或纯文本")
    ap.add_argument("--theme", default="default", help="主题名（themes/ 下的文件名）或主题 JSON 路径")
    ap.add_argument("--out", help="输出目录或 .html 文件路径")
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开预览页")
    ap.add_argument("--copy", action="store_true", help="macOS：直接把片段写进剪贴板")
    ap.add_argument("--no-embed", action="store_true", help="本地图片不嵌入，出占位框")
    ap.add_argument("--watch", action="store_true", help="起本机预览服务，保存后自动重排、页面自动刷新")
    ap.add_argument("--port", type=int, default=8765, help="--watch 的端口，被占时自动换一个")
    ap.add_argument("--check-file", help="只检查一个片段 HTML 文件")
    args = ap.parse_args()

    if args.check_file:
        with open(args.check_file, encoding="utf-8") as f:
            errors = check_fragment(f.read())
        for e in errors:
            print(f"✗ {e}")
        print("静态检查：" + ("通过" if not errors else f"{len(errors)} 处问题"))
        return 1 if errors else 0
    if not args.draft:
        ap.error("需要稿件路径，或用 --check-file")
    if args.watch:
        return watch(args)

    result = build(args)
    report(result)
    if result["errors"]:
        return 1
    if args.copy:
        print(f"剪贴板：{copy_to_clipboard(result['fragment'])}")
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", result["path"]], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
