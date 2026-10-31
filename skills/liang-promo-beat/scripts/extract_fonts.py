#!/usr/bin/env python3
"""从系统字体集（ttc）里按品牌包取出各个字形，存成独立 ttf，给 HyperFrames 工程和剪映字宽估算用。

用法：python extract_fonts.py --brand <brand.json> --out <工程>/assets/fonts [--ttc 字体文件]
文件名按 <字体族>-<字形名>.ttf，例如 LTH-Demibold.ttf、LTH-Heavy.ttf；品牌包字形写了 hf_file 时用它。
需要 fontTools。字体是商用字体时，只在本机工程里用，不随 skill 或草稿外发。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont


def find(name: str) -> Path | None:
    hits = []
    for root in (Path("/System/Library/AssetsV2"), Path("/Library/Fonts"), Path.home() / "Library/Fonts",
                 Path("/System/Library/Fonts")):
        if root.is_dir():
            hits += [p for p in root.rglob(name) if "Subsets" not in p.parts]
    return max(hits, key=lambda p: p.stat().st_size) if hits else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brand", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ttc", type=Path)
    args = ap.parse_args()
    brand = json.loads(args.brand.read_text(encoding="utf-8"))
    source = args.ttc or find(brand["fonts"]["system_ttc"])
    if not source:
        raise SystemExit(f"找不到 {brand['fonts']['system_ttc']}；用 --ttc 指定")
    args.out.mkdir(parents=True, exist_ok=True)
    collection = TTCollection(str(source)) if source.suffix.lower() == ".ttc" else None
    for key, face in brand["fonts"]["faces"].items():
        name = face.get("hf_file") or f"{brand['fonts']['family']}-{key[0].upper() + key[1:]}.ttf"
        font = collection.fonts[face["ttc_index"]] if collection else TTFont(str(source))
        font.save(str(args.out / name))
        print(f"{name}：取自 {source.name} 第 {face['ttc_index']} 个字形")


if __name__ == "__main__":
    main()
