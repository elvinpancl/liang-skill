#!/usr/bin/env python3
"""打码抽检拼图：每个打码区在它生效时段的中点抽一帧，裁出打码框（四周多留一点），拼成图给人逐张看。

用法：python mask_sheet.py <素材>/sanitize_manifest.json [--out 打码抽检.jpg] [--pad 24]
看什么：框里的字是不是完全认不出来；框有没有因为页面滚动盖偏，露出半行字。
打码是烧进素材的，草稿交付前必须看过这张图。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import jy_common


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--pad", type=int, default=24)
    args = ap.parse_args()
    data = jy_common.load_json(args.manifest)
    out = (args.out or args.manifest.parent / "打码抽检.jpg").resolve()
    tmp = out.parent / "制作过程" / "打码抽检帧"
    tmp.mkdir(parents=True, exist_ok=True)
    font_path = jy_common.find_system_font("Lantinghei.ttc") or jy_common.find_system_font("STHeiti Medium.ttc")
    font = ImageFont.truetype(str(font_path), 18) if font_path else ImageFont.load_default()
    tiles = []
    for clip in data["clips"]:
        source = clip.get("sanitized_full_path") or clip["path"]
        for i, mask in enumerate(clip.get("masks", [])):
            t = mask.get("check_output_s")
            if t is None:  # 这条规则的时段和取用区间不相交，素材里没有它
                continue
            frame = tmp / f"{clip['id']}_{i}.png"
            jy_common.run([jy_common.ffmpeg_bin(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", source,
                           "-frames:v", "1", str(frame)])
            im = Image.open(frame).convert("RGB")
            x, y, w, h = mask["rect"]
            box = (max(0, x - args.pad), max(0, y - args.pad), min(im.width, x + w + args.pad), min(im.height, y + h + args.pad))
            crop = im.crop(box)
            crop.thumbnail((560, 220))
            tiles.append((crop, f"{clip['id']} #{i + 1} {t:.2f}s {mask.get('reason', '')}"[:40]))
    if not tiles:
        print("清单里没有打码区")
        return
    cols, tw, th = 3, 580, 260
    sheet = Image.new("RGB", (cols * tw, -(-len(tiles) // cols) * th), "#0b0a09")
    draw = ImageDraw.Draw(sheet)
    for k, (crop, label) in enumerate(tiles):
        x, y = k % cols * tw + 10, k // cols * th + 8
        sheet.paste(crop, (x, y))
        draw.text((x, y + 226), label, fill="#ffd98e", font=font)
    sheet.save(out, quality=90)
    print(f"打码区 {len(tiles)} 处：{out}")


if __name__ == "__main__":
    main()
