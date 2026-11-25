#!/usr/bin/env python3
"""Structure check for one Skill folder. Standard library only.

Usage:
    python3 check_skill.py <skill-folder> [--max-lines 500]

Exit code 0 when there are no errors (warnings allowed), 1 otherwise.
This only checks structure. It says nothing about whether the Skill does its job.
"""
import argparse
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_MAX = 64
DESC_MAX = 1024
RESOURCE_DIRS = ("references", "scripts", "assets", "agents", "themes", "evals")
# Leftovers that mean a section was never finished. Only prose files are scanned.
UNFINISHED = ("TODO", "TBD", "FIXME", "待补充", "此处填写", "稍后补", "lorem ipsum")
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
CODE_SPAN = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^(```|~~~)")


def split_frontmatter(text):
    """Return (frontmatter_lines, body) or (None, text) when there is no frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    return None, text


def read_fields(fm_lines):
    """Read top-level `key: value` pairs. Handles quoted values and | or > blocks."""
    fields = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, value = m.group(1), m.group(2).strip()
        if value in ("|", ">", "|-", ">-", "|+", ">+") or value == "":
            block = []
            i += 1
            while i < len(fm_lines) and (fm_lines[i].startswith((" ", "\t")) or not fm_lines[i].strip()):
                block.append(fm_lines[i].strip())
                i += 1
            joiner = "\n" if value.startswith("|") else " "
            fields[key] = joiner.join(b for b in block if b).strip()
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
        i += 1
    return fields


def prose_lines(text):
    """Yield (line_number, line) outside fenced code blocks."""
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line.strip()):
            fenced = not fenced
            continue
        if not fenced:
            yield n, line


def looks_like_path(token):
    if any(ch in token for ch in "<>{}*$|") or " " in token:
        return False
    return "/" in token and token.split("/")[0] in RESOURCE_DIRS and "." in token.split("/")[-1]


def check(skill_dir, max_lines):
    errors, warnings = [], []
    root = skill_dir.resolve()
    skill_md = root / "SKILL.md"
    if not root.is_dir():
        return ["找不到这个文件夹：%s" % skill_dir], warnings
    if not skill_md.is_file():
        wrong = [p.name for p in root.iterdir() if p.name.lower().startswith("skill.md")]
        hint = "（看到 %s，文件名要正好是 SKILL.md）" % "、".join(wrong) if wrong else ""
        return ["文件夹里没有 SKILL.md%s" % hint], warnings

    text = skill_md.read_text(encoding="utf-8-sig")
    fm, body = split_frontmatter(text)
    if fm is None:
        errors.append("SKILL.md 开头没有用两行 --- 夹起来的那一段")
        fields = {}
    else:
        fields = read_fields(fm)

    name = fields.get("name", "")
    if not name:
        errors.append("缺 name")
    else:
        if not NAME_RE.match(name):
            errors.append("name 只能用小写字母、数字和连字符：%s" % name)
        if len(name) > NAME_MAX:
            errors.append("name 有 %d 个字符，上限 %d" % (len(name), NAME_MAX))
        if name != root.name:
            errors.append("name（%s）和文件夹名（%s）不一样" % (name, root.name))

    desc = fields.get("description", "")
    if not desc:
        errors.append("缺 description")
    else:
        if len(desc) > DESC_MAX:
            errors.append("description 有 %d 个字符，上限 %d" % (len(desc), DESC_MAX))
        elif len(desc) > 500:
            warnings.append("description 有 %d 个字符，偏长；目录放不下时会先被截短" % len(desc))
        if len(desc) < 20:
            warnings.append("description 只有 %d 个字符，多半没写清什么时候用" % len(desc))

    body_lines = body.count("\n") + 1 if body.strip() else 0
    if body_lines == 0:
        errors.append("SKILL.md 只有开头那一段，没有正文")
    elif body_lines > max_lines:
        warnings.append("正文 %d 行，超过 %d 行；看看有没有能挪进 references/ 的内容" % (body_lines, max_lines))

    md_files = [skill_md] + sorted(p for p in root.rglob("*.md") if p != skill_md and ".git" not in p.parts)
    mentioned = set()
    for md in md_files:
        rel_md = md.relative_to(root).as_posix()
        content = md.read_text(encoding="utf-8-sig", errors="replace")
        offset = 0
        if md == skill_md and fm is not None:
            content = body
            offset = len(fm) + 2
        for n, line in prose_lines(content):
            n += offset
            for word in UNFINISHED:
                if word.lower() in line.lower():
                    errors.append("%s 第 %d 行像是没写完：出现了「%s」" % (rel_md, n, word))
            targets = []
            for raw in MD_LINK.findall(line):
                target = raw.split("#")[0]
                if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                    continue
                targets.append((target, md.parent))
            for token in CODE_SPAN.findall(line):
                if looks_like_path(token):
                    targets.append((token, root))
            for target, base in targets:
                path = (base / target).resolve()
                if root != path and root not in path.parents:
                    errors.append("%s 第 %d 行引用了文件夹外面的文件：%s" % (rel_md, n, target))
                    continue
                if not path.exists():
                    errors.append("%s 第 %d 行引用的文件不存在：%s" % (rel_md, n, target))
                    continue
                mentioned.add(path)

    refs = root / "references"
    if refs.is_dir():
        for ref in sorted(p for p in refs.rglob("*") if p.is_file() and p.name != ".DS_Store"):
            if ref.resolve() not in mentioned:
                warnings.append("%s 没有被任何说明提到，Agent 不会知道什么时候去读它" % ref.relative_to(root).as_posix())

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="检查一个 Skill 文件夹的结构")
    parser.add_argument("skill_dir", help="Skill 文件夹的路径")
    parser.add_argument("--max-lines", type=int, default=500, help="正文行数的提醒线，默认 500")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    errors, warnings = check(Path(args.skill_dir), args.max_lines)
    for item in errors:
        print("错误  " + item)
    for item in warnings:
        print("提醒  " + item)
    if errors:
        print("结构检查没过：%d 处错误，%d 处提醒" % (len(errors), len(warnings)))
        return 1
    print("结构检查通过（%d 处提醒）。这只说明文件齐全，不说明它做得好不好。" % len(warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
