#!/usr/bin/env python3
"""生成一套合成测试素材和对应的 clips.json、draft_plan.json，给自测和剪映实机冒烟用。

用法：python make_fixture.py <目录> [--brand brand.json] [--font-mode default|system|library] [--name 草稿名]

素材全用 ffmpeg 合成（testsrc2、正弦音），不依赖任何真实项目：
- 录屏.mp4 1920×1056、5 秒：测按宽适配、运镜、打码、末帧定格
- 底片.mp4 1920×1080、2 秒：测烘焙段切分
- 画中画.mp4 860×488、4 秒：测画中画、边框、入场
- bgm.m4a 6 秒
覆盖：硬切和推近转场、set/ease/punch/pop 运镜、上下两种说明、章节、底衬、画中画边框。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import jy_common

HERE = Path(__file__).resolve().parent


def synth(out: Path, size: str, seconds: float, *, pattern: str = "testsrc2") -> None:
    jy_common.run([jy_common.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i",
                   f"{pattern}=size={size}:rate=30:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   "-preset", "ultrafast", str(out)])


def make(directory: Path, brand: Path, font_mode: str, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    src = directory / "源"
    src.mkdir(exist_ok=True)
    synth(src / "录屏.mp4", "1920x1056", 5)
    synth(src / "底片.mp4", "1920x1080", 2, pattern="smptehdbars")
    synth(src / "画中画.mp4", "860x488", 4, pattern="testsrc")
    jy_common.run([jy_common.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i",
                   "sine=frequency=440:duration=6", "-c:a", "aac", str(src / "bgm.m4a")])
    clips = {"fps": 30, "out_dir": "素材", "source_size": [1920, 1056],
             "clips": [{"id": "R1", "src": "源/录屏.mp4", "in_s": 0.5, "out_s": 2.5, "handles_s": 0.5,
                        "masks": [{"rect": [100, 100, 400, 60], "t": [0, 5], "reason": "自测打码"}]},
                       {"id": "P1", "src": "源/画中画.mp4", "in_s": 0, "out_s": 4, "handles_s": 0,
                        "source_size": [860, 488]}]}
    (directory / "clips.json").write_text(json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
    plan = {
        "schema": "liang-promo-jianying/plan-1", "name": name, "fps": 30, "canvas": [1920, 1080],
        "total_frames": 150, "brand": str(brand), "source_canvas": [1920, 1056], "font_mode": font_mode,
        "sanitize_manifest": "素材/sanitize_manifest.json", "segments_manifest": "素材/segments_manifest.json",
        "main": [
            {"id": "B1", "start": 0, "end": 30, "from_segment": "B1", "transition_out": {"name": "推近", "frames": 8}},
            {"id": "R1", "start": 30, "end": 120, "from_sanitized": "R1",
             "camera": [{"op": "set", "rect": [0, 0, 1920, 1056], "fit": True},
                        {"op": "ease", "from": 40, "to": 48, "rect": [960, 516, 960, 540]},
                        {"op": "punch", "f": 70}]},
            {"id": "B2", "start": 120, "end": 150, "from_segment": "B2"}],
        "pip": [{"id": "P1", "start": 90, "end": 150, "from_sanitized": "P1", "source_in": 10,
                 "camera": [{"op": "set", "cam": [0.4519, 0, 0.1296]},
                            {"op": "pop", "f": 104, "cam": [0.4519, 0, 0.1296]}],
                 "intro": {"name": "放大", "frames": 6}}],
        "chapters": [{"text": "01 自测章节", "start": 30, "end": 150}],
        "captions": [{"text": "下方说明", "start": 40, "end": 80, "slot": "bottom",
                      "target": {"rect": [1100, 600, 300, 80]}},
                     {"text": "上方说明", "start": 80, "end": 120, "slot": "top",
                      "target": {"keys": [{"from": 80, "rect": [1000, 800, 400, 100]},
                                          {"from": 100, "rect": [1000, 820, 400, 100]}]}}],
        "caption_avoid": {"enabled": True, "limit_bottom_px": 860},
        "bgm": {"path": "源/bgm.m4a", "volume": 1.0}}
    path = directory / "draft_plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--brand", type=Path, default=HERE.parent / "assets" / "brand.example.json")
    parser.add_argument("--font-mode", default="default", choices=["default", "system", "library"])
    parser.add_argument("--name", default="liang自测")
    args = parser.parse_args()
    print(make(args.directory.resolve(), args.brand.resolve(), args.font_mode, args.name))


if __name__ == "__main__":
    main()
