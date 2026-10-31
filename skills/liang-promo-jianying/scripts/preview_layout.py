#!/usr/bin/env python3
"""按草稿里真实的关键帧，离线合成说明出现时的画面，标出目标框，报告说明是否压住目标。

用法：python preview_layout.py <staging/草稿名> [--out 目录] [--frames 起,中,末]

- 每条说明在起点、中点、最后一帧各出一张图：主画面、画中画和边框、底衬、章节和说明的胶囊底、
  红框是说明要讲的那个目标。最后拼一张总览。
- 这是数学合成，不是剪映渲染：不模拟入场动画、转场、剪映的字距和背景留白。用来查几何位置
  和取景，人工看一眼「说明有没有盖住它要讲的数字或界面」。
- 报告 layout_report.json：每张图里说明框和目标框是否相交。
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import jy_common
import jy_readback as rb
from build_draft import hex_rgb


def frame_image(material: dict, segment: dict, time_us: int, fps: int, cache: Path) -> Image.Image:
    path = Path(material["path"])
    if material.get("type") == "photo" or path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        return Image.open(path).convert("RGBA")
    source = segment["source_timerange"]
    local = source["start"] + (time_us - segment["target_timerange"]["start"]) * segment.get("speed", 1)
    frame = max(0, jy_common.us2f(local, fps))
    token = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}:{frame}".encode()).hexdigest()[:16]
    target = cache / f"{token}.png"
    if not target.exists():
        jy_common.run([jy_common.ffmpeg_bin(), "-v", "error", "-nostdin", "-y", "-i", str(path),
                       "-vf", f"select=eq(n\\,{frame})", "-frames:v", "1", "-update", "1", str(target)])
    return Image.open(target).convert("RGBA")


def place(canvas: Image.Image, image: Image.Image, state: dict, alpha: float = 1.0) -> dict:
    box = rb.media_box({"width": image.width, "height": image.height}, state, canvas.size)
    w, h = max(1, round(image.width * box["sx"])), max(1, round(image.height * box["sy"]))
    layer = image.resize((w, h), Image.Resampling.BICUBIC)
    if alpha < 1:
        layer.putalpha(layer.getchannel("A").point(lambda a: round(a * alpha)))
    canvas.alpha_composite(layer, (round(box["left"]), round(box["top"])))
    return box


def active(segs: list, time_us: int) -> list:
    return [s for s in segs if rb.timerange(s)[0] <= time_us < rb.timerange(s)[1]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("draft_dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    draft_dir = args.draft_dir.resolve()
    content = jy_common.load_json(draft_dir / "draft_content.json")
    manifest = jy_common.load_json(draft_dir / "build_manifest.json")
    brand = jy_common.load_json(manifest["brand"])
    jy = brand["jianying"]
    fps, cw, ch = manifest["fps"], *manifest["canvas"]
    out = (args.out or draft_dir.parent / f"{draft_dir.name}_布局预览").resolve()
    cache = out / "源帧"
    cache.mkdir(parents=True, exist_ok=True)
    by_id = rb.materials_by_id(content)
    tracks = rb.tracks_by_name(content)
    names = dict(zip(manifest["track_keys"], manifest["tracks"]))
    segs = {k: sorted(tracks.get(n, {}).get("segments", []), key=lambda s: rb.timerange(s)[0]) for k, n in names.items()}
    font_path = manifest.get("font", {}).get("path") or jy_common.find_system_font(brand["fonts"]["system_ttc"])
    px = jy["caption"]["size"] * 10.8

    def font(size):
        return ImageFont.truetype(str(font_path), round(size), index=0) if font_path else ImageFont.load_default()

    rows, images = [], []
    for index, cap in enumerate(manifest["captions"]):
        a, b = cap["start_frame"], cap["end_frame"]
        for f in sorted({a, (a + b) // 2, b - 1}):
            t = jy_common.f2us(f, fps)
            img = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
            main_box = None
            for seg in active(segs.get("main", []), t):
                main_box = place(img, frame_image(by_id[seg["material_id"]], seg, t, fps, cache), rb.segment_state(seg, t))
            for key in ("pip", "pip_border", "scrim"):
                for seg in active(segs.get(key, []), t):
                    state = rb.segment_state(seg, t)
                    place(img, frame_image(by_id[seg["material_id"]], seg, t, fps, cache), state, state.get("alpha", 1))
            draw = ImageDraw.Draw(img)
            for seg in active(segs.get("chapter", []), t):
                rec = next(c for c in manifest["chapters"] if c["segment_id"] == seg["id"])
                text = rb.text_content(by_id[seg["material_id"]])
                size = jy["chapter"]["px"]
                w = draw.textlength(text, font=font(size))
                x, y = rec["position"]
                draw.rounded_rectangle((x - w / 2 - .6 * size, y - .8 * size, x + w / 2 + .6 * size, y + .8 * size),
                                       radius=.4 * size, fill=hex_rgb_255(jy["chapter"]["bg_color"], jy["chapter"]["bg_alpha"]))
                draw.text((x, y), text, font=font(size), fill=hex_rgb_255(jy["chapter"]["color"]), anchor="mm")
            x, y = cap["position"]
            w, h = cap["estimated_width_px"], cap["estimated_height_px"]
            cap_box = [x - w / 2, y - h / 2, x + w / 2, y + h / 2]
            draw.rounded_rectangle(cap_box, radius=h / 2 * jy["caption"]["round_radius"] * 2,
                                   fill=hex_rgb_255(jy["caption"]["bg_color"]))
            draw.text((x, y), cap["text"], font=font(px), fill=hex_rgb_255(jy["caption"]["text_color"]), anchor="mm")
            target_box, hit = None, False
            rect = rb.target_at(cap.get("target"), f)
            if rect and main_box:
                target_box = rb.project_rect(rect, main_box)
                hit = rb.intersects(cap_box, target_box)
                draw.rectangle(target_box, outline=(255, 64, 64, 255), width=4)
            draw.text((24, ch - 24), f"F{f}  {cap['text']}", font=font(28), fill=(255, 255, 255, 255), anchor="ls")
            name = out / f"{index + 1:02d}_F{f}.jpg"
            img.convert("RGB").save(name, quality=85)
            images.append(name)
            rows.append({"caption": cap["text"], "frame": f, "image": str(name), "caption_box": cap_box,
                         "target_box": target_box, "intersects": hit})
    if images:
        cols = 6
        thumbs = [Image.open(p).resize((320, 180)) for p in images]
        sheet = Image.new("RGB", (cols * 320, -(-len(thumbs) // cols) * 180))
        for i, im in enumerate(thumbs):
            sheet.paste(im, (i % cols * 320, i // cols * 180))
        sheet.save(out / "总览.jpg", quality=85)
    hits = [r for r in rows if r["intersects"]]
    jy_common.save_json(out / "layout_report.json", {"images": len(rows), "intersections": hits, "rows": rows})
    print(f"出图 {len(rows)} 张，说明框压住目标 {len(hits)} 处：{out}")
    for r in hits[:20]:
        print(f"  F{r['frame']} {r['caption']}")


def hex_rgb_255(value: str, alpha: float = 1.0) -> tuple:
    return tuple(round(v * 255) for v in hex_rgb(value)) + (round(alpha * 255),)


if __name__ == "__main__":
    main()
