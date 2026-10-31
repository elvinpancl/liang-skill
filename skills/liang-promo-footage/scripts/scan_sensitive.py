#!/usr/bin/env python3
"""扫配图（或任意帧）的识别文字，列出发布前要打码的图。

用法：
  python3 scan_sensitive.py <识别文字文件或目录>... [--out 打码清单.md]

必须打码：API 密钥（sk-、ak_、Bearer、ghp_、xoxb-、AKIA 等常见前缀）、邮箱、手机号、
身份证号、本机用户路径（/Users/名字、/home/名字、C:\\Users\\名字、面包屑里的 Users > 名字）。
可选打码：编号（UUID，常见于租户 ID、应用 ID）、网址（接口地址可能是内网或私有服务）。

输出里敏感值只露前 4 位。识别文字可能漏字、错字，扫描结果只是线索：
被标出的图逐张看图确认，没被标出的图发布前也要整体过一眼。
"""

import argparse
import os
import re
import sys

MUST = [
    ("API 密钥", re.compile(r"\b(?:sk-|ak_|ghp_|gho_|xox[bpa]-)\S{2,}|\bAKIA[0-9A-Z]{12,}|Bearer\s+\S{2,}")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")),
    ("手机号", re.compile(r"(?<![\d])1[3-9]\d[ \-]?\d{4}[ \-]?\d{4}(?![\d])|(?<![\d])1[3-9]\d\*{4}\d{4}(?![\d])")),
    ("身份证号", re.compile(r"(?<![\dA-Za-z])\d{17}[\dXx](?![\dA-Za-z])")),
    ("本机用户路径", re.compile(r"/(?:Users|home)/[^/\s|>》＞]+|[A-Za-z]:\\Users\\[^\\\s|]+|Users\s*[>》＞]\s*[^\s>》＞|]+")),
]
OPTIONAL = [
    ("编号（UUID）", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    ("网址", re.compile(r"https?://[^\s|'\"，。]+")),
]


def read_blocks(inputs):
    files = []
    for item in inputs:
        item = os.path.expanduser(item)
        if os.path.isdir(item):
            files += sorted(os.path.join(item, n) for n in os.listdir(item) if n.endswith(".txt"))
        elif os.path.isfile(item):
            files.append(item)
        else:
            sys.exit(f"找不到识别文字：{item}")
    blocks = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for part in re.split(r"^== ", text, flags=re.M)[1:]:
            name, _, body = part.partition("\n")
            blocks.append((name.strip(), body))
    return blocks


def mask(value):
    value = value.strip()
    return value[:4] + "****"


def main():
    ap = argparse.ArgumentParser(description="扫识别文字里的打码项")
    ap.add_argument("inputs", nargs="+", help="识别文字文件或目录")
    ap.add_argument("--out", help="把打码清单写成 Markdown 文件")
    args = ap.parse_args()

    blocks = read_blocks(args.inputs)
    rows = []
    by_cat = {}
    for name, body in blocks:
        for level, patterns in (("必须", MUST), ("可选", OPTIONAL)):
            for cat, pattern in patterns:
                hits = []
                for m in pattern.finditer(body):
                    masked = mask(m.group(0))
                    if masked not in hits:
                        hits.append(masked)
                if hits:
                    rows.append((name, level, cat, len(hits), "、".join(hits[:3])))
                    by_cat.setdefault((level, cat), []).append(name)

    lines = ["# 打码清单（自动扫描，只是线索）", ""]
    lines.append("识别文字可能漏字、错字。被标出的图逐张看图确认；没被标出的图，发布前也要整体过一眼。")
    lines.append("")
    if not rows:
        lines.append(f"扫了 {len(blocks)} 张，没有扫出打码项。")
    else:
        for level in ("必须", "可选"):
            cats = [(c, names) for (lv, c), names in by_cat.items() if lv == level]
            if not cats:
                continue
            lines.append(f"**{level}打码**：")
            for cat, names in cats:
                lines.append(f"- {cat}：{'、'.join(os.path.splitext(n)[0] for n in names)}")
            lines.append("")
        lines.append("| 图 | 级别 | 类别 | 处数 | 片段（已遮挡） |")
        lines.append("|---|---|---|---|---|")
        for name, level, cat, count, sample in rows:
            lines.append(f"| {name} | {level} | {cat} | {count} | {sample} |")
    report = "\n".join(lines) + "\n"

    if args.out:
        with open(os.path.expanduser(args.out), "w", encoding="utf-8") as f:
            f.write(report)
    summary = [f"扫了 {len(blocks)} 张"]
    for (level, cat), names in by_cat.items():
        summary.append(f"{level}·{cat}：{'、'.join(os.path.splitext(n)[0] for n in names)}")
    print("\n".join(summary))
    if args.out:
        print(f"打码清单写在 {args.out}")


if __name__ == "__main__":
    main()
