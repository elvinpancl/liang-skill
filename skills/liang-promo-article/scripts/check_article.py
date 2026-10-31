#!/usr/bin/env python3
"""品宣文章自检：字数、配图、标点、套话、格式、中英文空格、人称。

用法：
  python3 check_article.py <文章.md>... [--third-person] [--allow-term 专名1,专名2] [--forbid 词1,词2] [--max-hits 20]

规则：
  - 第一行的「# 标题」不算正文；以「![」开头的行是配图，按文章所在目录检查文件在不在。
  - 「」里是 AI 原话或界面原文，保留原样，不参与下面的检查。
  - 硬伤（出现一处，退出码就是 1）：
      冒号、破折号、双引号（网址里的冒号不算）
      套话（默认表见 DEFAULT_FORBID，--forbid 追加）
      小标题、列表、加粗
      中英文、数字和汉字之间缺空格（--allow-term 放行字母和汉字连写的专名，比如「小B家电」）
      缺图
      加 --third-person 时，「」以外出现我、我们、你、你们、咱
  - 字数是正文去掉空白以后的字符数，包括「」里的原话。
"""

import argparse
import os
import re
import sys
from urllib.parse import unquote

DEFAULT_FORBID = [
    "说白了", "本质上", "换句话说", "意味着", "不可否认", "综上所述",
    "值得注意的是", "不难发现", "让我们", "首先", "其次", "总的来说",
]
CJK = "一-鿿"


def hollow_quotes(text):
    """把「」里的内容清空，只留括号，嵌套的也清掉。"""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"「[^「」]*」", "「」", text)
    return text


def context(text, start, end, width=12):
    return text[max(0, start - width):end + width].replace("\n", " ")


def check(path, args):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    title = lines[0] if lines and lines[0].startswith("# ") else None
    rest = lines[1:] if title else lines
    images = []
    body_lines = []
    for line in rest:
        if line.lstrip().startswith("!["):
            m = re.search(r"\]\((.+?)\)", line)
            if m:
                images.append(m.group(1).strip())
        else:
            body_lines.append(line)
    body = "\n".join(body_lines)
    outside = hollow_quotes(body)

    base = os.path.dirname(os.path.abspath(path))
    missing = [
        p for p in images
        if not re.match(r"https?://", p) and not os.path.exists(os.path.join(base, unquote(p)))
    ]

    spacing_text = outside
    for term in args.allow_term:
        spacing_text = spacing_text.replace(term, "「」")
    forbid = DEFAULT_FORBID + args.forbid

    rules = [
        ("冒号", re.sub(r"https?://\S+", "", outside), r"[：:]"),
        ("破折号", outside, r"——|—"),
        ("双引号", outside, r"[“”\"]"),
        ("套话", outside, "|".join(map(re.escape, forbid))),
        ("加粗", outside, r"\*\*|__"),
        ("中英文缺空格", spacing_text, rf"[{CJK}][A-Za-z0-9]|[A-Za-z0-9][{CJK}]"),
    ]
    if args.third_person:
        rules.append(("「」外的人称", outside, r"我们|(?<!自)我|你们|你|咱们|咱"))

    hits = {}
    for name, text, pattern in rules:
        found = [(m.group(0), context(text, m.start(), m.end())) for m in re.finditer(pattern, text)]
        if found:
            hits[name] = found
    heading = [l for l in body_lines if re.match(r"\s*#{1,6}\s", l)]
    listing = [l for l in body_lines if re.match(r"\s*(?:[-*+]\s|\d+[.)]\s|\d+、|[（(]\d+[）)])", l)]
    if heading:
        hits["小标题"] = [(l.strip()[:20], "") for l in heading]
    if listing:
        hits["列表"] = [(l.strip()[:20], "") for l in listing]
    if missing:
        hits["缺图"] = [(p, "") for p in missing]

    chars = len(re.sub(r"\s", "", body))
    total = sum(len(v) for v in hits.values())
    name = os.path.basename(path)
    print(f"{name} | 字数 {chars} | 配图 {len(images)}，缺 {len(missing)} | 硬伤 {total}")
    for category, found in hits.items():
        shown = []
        for word, ctx in found[:args.max_hits]:
            shown.append(f"「{word}」…{ctx}…" if ctx else f"{word}")
        more = f"（另有 {len(found) - args.max_hits} 处）" if len(found) > args.max_hits else ""
        print(f"  {category} {len(found)} 处：" + "；".join(shown) + more)
    return total


def main():
    ap = argparse.ArgumentParser(description="品宣文章自检")
    ap.add_argument("articles", nargs="+", help="文章 Markdown 文件")
    ap.add_argument("--third-person", action="store_true", help="品宣模式：检查「」以外的第一、第二人称")
    ap.add_argument("--allow-term", default="", help="放行的专名，逗号分隔，例如 小B家电")
    ap.add_argument("--forbid", default="", help="追加的套话，逗号分隔")
    ap.add_argument("--max-hits", type=int, default=20, help="每类最多列几处，默认 20")
    args = ap.parse_args()
    args.allow_term = [t for t in args.allow_term.split(",") if t]
    args.forbid = [t for t in args.forbid.split(",") if t]

    bad = 0
    for path in args.articles:
        if not os.path.exists(path):
            print(f"{path} | 文件不存在")
            bad += 1
            continue
        bad += check(path, args)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
