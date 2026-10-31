#!/usr/bin/env python3
"""按 extract_frames.py 写的 index.json，批量识别抽出来的帧。

用法：
  python3 ocr_frames.py <抽帧输出目录> [--batch 25] [--force]

输出：
  <抽帧输出目录>/ocr/<原片相对路径，斜杠换成 __>.txt   每段原片一份，按时间顺序
  <抽帧输出目录>/ocr/识别失败.txt   每轮重写，记本轮失败的批次；没有失败写「无」

已有识别文字且帧数对得上的段落直接跳过，可以断点续跑；--force 全部重做。
只支持 macOS（osascript 调系统 Vision 框架）。
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OCR_JS = os.path.join(HERE, "ocr.js")


def ocr_batch(paths):
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", OCR_JS, *paths],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def main():
    ap = argparse.ArgumentParser(description="批量识别抽出来的帧")
    ap.add_argument("frames_dir", help="extract_frames.py 的输出目录")
    ap.add_argument("--batch", type=int, default=25, help="每次调用识别多少张，默认 25")
    ap.add_argument("--force", action="store_true", help="忽略已有结果，全部重做")
    args = ap.parse_args()

    if sys.platform != "darwin":
        sys.exit("文字识别只支持 macOS。其他系统请改为分批看图，或换用本机已有的识别工具。")

    root = os.path.abspath(os.path.expanduser(args.frames_dir))
    index_path = os.path.join(root, "index.json")
    if not os.path.exists(index_path):
        sys.exit(f"找不到 {index_path}，先运行 extract_frames.py")
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)

    out_dir = os.path.join(root, "ocr")
    os.makedirs(out_dir, exist_ok=True)
    done = skipped = 0
    failed, error_lines = [], []
    for rel, info in index.items():
        name = re.sub(r"[\\/]+", "__", os.path.splitext(rel)[0])
        out_path = os.path.join(out_dir, name + ".txt")
        frames = [os.path.join(root, info["dir"], fr) for fr in info["frames"]]
        if not args.force and os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                if sum(1 for line in f if line.startswith("== ")) == len(frames):
                    skipped += 1
                    continue
        chunks, errors = [], []
        for i in range(0, len(frames), args.batch):
            code, stdout, stderr = ocr_batch(frames[i:i + args.batch])
            if code != 0:
                errors.append(f"第 {i + 1} 帧起的一批失败：{stderr.strip()[:300]}")
                continue
            chunks.append(stdout.rstrip("\n"))
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(chunks) + "\n")
        if errors:
            failed.append(rel)
            error_lines += [f"{rel}：{e}" for e in errors]
        done += 1
        print(f"{rel}: {len(frames)} 帧{'，有失败' if errors else ''}", flush=True)

    with open(os.path.join(out_dir, "识别失败.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(error_lines) + "\n" if error_lines else "无\n")
    print(f"识别 {done} 段，跳过 {skipped} 段（已有结果），失败 {len(failed)} 段；结果在 {out_dir}")
    if failed:
        print("失败的段落：" + "、".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
