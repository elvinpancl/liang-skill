#!/usr/bin/env python3
"""分块读完整篇来源，并自动记下读到哪里（全文阅读凭证）。

用法：
  read_source.py --id Q001 --part 1          读第 1 块（带原始行号），自动登记
  read_source.py --id Q001 --info            只看总块数和已读块，不输出正文
  read_source.py --id Q001 --lines 120-180   回看某段（不登记）
  read_source.py --ids Q038,Q039,Q040 --pack 短稿合批：一次输出能放进 --chars 的几篇完整短稿，逐篇登记；
                                              没放下的再跑同一条命令

docx 先用 macOS textutil 转成纯文本缓存到 <运行目录>/来源文本/，行号以缓存为准。
每块按行切、约 --chars 字（默认 10000，留在 Claude Code 与 Codex 单次输出上限以内，免得被转存成文件再多读几次），块与块之间重叠 --overlap 行（默认 15），
避免一段问答被切断。读完全部块后阅读记录里 complete=true。
--pack 只收一块就能读完的短稿；超过一块的来源跳过并提示改用 --part。每多调用一次工具，整份上下文就重发一次，
所以短稿要合在一起读。
"""
import argparse, hashlib, subprocess, sys
from datetime import datetime
from pathlib import Path
from common import ROOT, dump_json, load_json, resolve_run


def source_text(run, item):
    p = Path(item["path"])
    p = p if p.is_absolute() else (ROOT / p).resolve()
    if p.suffix.lower() == ".docx":
        cache = run / "来源文本" / f"{item['id']}.txt"
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["textutil", "-convert", "txt", "-output", str(cache), str(p)], check=True)
        return p, cache.read_text(encoding="utf-8")
    return p, p.read_text(encoding="utf-8", errors="replace")


def split_parts(lines, chars, overlap):
    parts, start = [], 0
    while start < len(lines):
        size, end = 0, start
        while end < len(lines) and (size < chars or end == start):
            size += len(lines[end]) + 1
            end += 1
        parts.append((start, end))
        if end >= len(lines):
            break
        start = max(end - overlap, start + 1)
    return parts


def open_record(run, item, path, lines, parts, text, chars):
    rec_path = run / "阅读记录" / f"{item['id']}.json"
    rec = load_json(rec_path, {})
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if rec.get("sha256") not in (None, sha) or rec.get("part_chars") not in (None, chars):
        rec = {}  # 来源变了，或分块大小变了（块号对不上），旧记录作废
    rec.update(id=item["id"], path=item["path"], sha256=sha, total_lines=len(lines), total_parts=len(parts),
               chars=len(text), part_chars=chars)
    rec.setdefault("parts_read", [])
    return rec_path, rec


def mark_read(rec_path, rec, part_no):
    if part_no not in rec["parts_read"]:
        rec["parts_read"].append(part_no)
    rec["complete"] = sorted(rec["parts_read"]) == list(range(1, rec["total_parts"] + 1))
    rec["updated_at"] = datetime.now().astimezone().isoformat()
    dump_json(rec_path, rec)


def cmd_pack(run, items, args):
    room, done, left, too_long, full = args.chars, [], [], [], False
    for qid, item in items:
        path, text = source_text(run, item)
        lines = text.split("\n")
        parts = split_parts(lines, args.chars, args.overlap)
        rec_path, rec = open_record(run, item, path, lines, parts, text, args.chars)
        if rec.get("complete"):
            continue
        if len(parts) > 1:
            too_long.append(qid)
            continue
        if full or (done and len(text) > room):
            full = True
            left.append(qid)
            continue
        print(f"〔{qid} 全文｜L1-{len(lines)}｜{item['path']}〕")
        for n, line in enumerate(lines, 1):
            print(f"{n}\t{line}")
        mark_read(rec_path, rec, 1)
        done.append(qid)
        room -= len(text)
    tail = [f"本次读完 {'、'.join(done)}" if done else "本次没有读到新的短稿"]
    if left:
        tail.append(f"还剩 {'、'.join(left)}，再跑同一条命令")
    if too_long:
        tail.append(f"{'、'.join(too_long)} 超过一块，改用 --id 编号 --part N 分块读")
    if not left and not too_long:
        tail.append("这批短稿已全部登记读完")
    print("〔" + "；".join(tail) + "〕")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run"); ap.add_argument("--id"); ap.add_argument("--ids", help="逗号分隔的多个编号，配合 --pack")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--part", type=int); g.add_argument("--info", action="store_true"); g.add_argument("--lines")
    g.add_argument("--pack", action="store_true")
    ap.add_argument("--chars", type=int, default=10000); ap.add_argument("--overlap", type=int, default=15)
    args = ap.parse_args()

    run = resolve_run(args.run)
    q = load_json(run / "来源队列.json", {"items": []})
    by_id = {i["id"]: i for i in q["items"]}
    wanted = [x.strip() for x in (args.ids or args.id or "").split(",") if x.strip()]
    if not wanted:
        print("要给 --id 或 --ids")
        return 1
    missing = [x for x in wanted if x not in by_id]
    if missing:
        print(f"队列里没有 {'、'.join(missing)}")
        return 1
    if args.pack:
        return cmd_pack(run, [(x, by_id[x]) for x in wanted], args)
    if len(wanted) > 1:
        print("多个编号只能配合 --pack；长稿用 --id 编号 --part N 逐块读")
        return 1

    item = by_id[wanted[0]]
    path, text = source_text(run, item)
    lines = text.split("\n")
    parts = split_parts(lines, args.chars, args.overlap)
    rec_path, rec = open_record(run, item, path, lines, parts, text, args.chars)

    if args.info:
        print(f"{item['id']}｜{len(lines)} 行｜{len(text)} 字｜{len(parts)} 块｜已读 {sorted(rec['parts_read'])}")
        return 0
    if args.lines:
        a, b = (int(x) for x in args.lines.split("-"))
        for n in range(max(a, 1), min(b, len(lines)) + 1):
            print(f"{n}\t{lines[n-1]}")
        return 0

    if not 1 <= args.part <= len(parts):
        print(f"块号超出范围：共 {len(parts)} 块")
        return 1
    a, b = parts[args.part - 1]
    print(f"〔{item['id']} 第 {args.part}/{len(parts)} 块｜L{a+1}-{b}｜{item['path']}〕")
    for n in range(a, b):
        print(f"{n+1}\t{lines[n]}")
    mark_read(rec_path, rec, args.part)
    left = len(parts) - len(rec["parts_read"])
    print(f"〔已登记；{'全文读完' if rec['complete'] else f'还剩 {left} 块'}〕")
    return 0


if __name__ == "__main__":
    sys.exit(main())
