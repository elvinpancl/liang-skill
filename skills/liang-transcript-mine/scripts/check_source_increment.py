#!/usr/bin/env python3
"""只读扫描配置的逐字稿，与 TSV 哈希基线比较；不会提交处理状态。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from common import CONFIG, KB, ROOT, STATE_DIR, die, rel


def scan(required):
    patterns = CONFIG.get("source_patterns")
    if not isinstance(patterns, list) or not patterns or not all(isinstance(x, str) and x for x in patterns):
        die("请配置非空 source_patterns 列表，只包含需要处理的原始逐字稿 glob。")
    files = set()
    for pattern in patterns:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            die("source_patterns 必须是知识库内的相对 glob，不能包含 ..。")
        for p in KB.glob(pattern):
            # 不跟随软链，避免把知识库外或别的工作区的数据带入队列。
            if p.is_symlink() or any(x.is_symlink() for x in p.parents if x != KB):
                continue
            if p.is_file() and p.resolve().is_relative_to(KB) and p.suffix.lower() in (".md", ".txt", ".docx"):
                files.add(p.resolve())
    baseline = {}
    baseline_path = STATE_DIR / "processed_source_hashes.tsv"
    if baseline_path.exists():
        with baseline_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            needed = {"relative_path", "sha256", "extractor_version"}
            if not needed.issubset(reader.fieldnames or []):
                die("哈希基线缺少 relative_path、sha256 或 extractor_version 列；请显式迁移，不能默默重新处理。")
            for row in reader:
                baseline[row["relative_path"]] = row
    result = {"new": [], "changed": [], "stale": [], "unchanged": []}
    for p in sorted(files):
        key = rel(p)
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        old = baseline.get(key)
        status = "new" if old is None else "changed" if old["sha256"] != sha else "stale" if old["extractor_version"] != required else "unchanged"
        result[status].append(key)
    result["scanned"] = len(files)
    result["extractor_version"] = required
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require", required=True)
    args = parser.parse_args()
    print(json.dumps(scan(args.require), ensure_ascii=False))


if __name__ == "__main__":
    main()
