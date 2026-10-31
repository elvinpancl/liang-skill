#!/usr/bin/env python3
"""按 draft_plan.json 生成可编辑的剪映草稿。只写 staging，不安装，不碰任何已有草稿。

用法：python build_draft.py <draft_plan.json> [--name 草稿名] [--allow-surrogate]

计划格式见 ../references/draft_plan_脱敏版.md。产出：
  <staging>/<草稿名>/draft_content.json 等 pyJianYingDraft 明文草稿
  <staging>/<草稿名>/build_manifest.json   给 verify_draft.py 和 preview_layout.py 用的清单
同名 staging 已存在时，旧的整体移进计划目录的 .trash/（日期前缀），不覆盖。

样式（说明、章节、底衬、画中画边框、字体）全部从计划里 brand 指向的 brand.json 读；
计划里只放这条片子自己的东西：镜头、运镜、转场、说明文字和时间。
计划里的 overlays（品牌图层）把 logo、品牌字这类原本要烘焙进底片的东西做成剪映原生的图片和文字，
每层一条轨道，叠在主画面和画中画之上、底衬和说明之下，位置、缩放、透明度用关键帧。
"""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime
from pathlib import Path

import pyJianYingDraft as draft
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pyJianYingDraft import (ClipSettings, FontType, IntroType, KeyframeProperty, OutroType, TextBackground,
                             TextBorder, TextIntro, TextOutro, TextShadow, TextStyle, Timerange, TransitionType)

import jy_camera
import jy_common
import jy_fonts

TRACK_KEYS = ("main", "pip", "pip_border", "overlays", "scrim", "chapter", "caption", "bgm")  # overlays 展开成每层一条轨
DEFAULT_TRACK_NAMES = {"main": "主画面", "pip": "画中画", "pip_border": "画中画边框", "scrim": "字幕底衬",
                       "chapter": "文字-章节", "caption": "文字-说明", "bgm": "BGM"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def sample_points(points: dict, frame):
    """关键帧线性插值（剪映关键帧之间就是线性）。"""
    ordered = sorted(points.items())
    if frame <= ordered[0][0]:
        return ordered[0][1]
    for (a, va), (b, vb) in zip(ordered, ordered[1:]):
        if frame <= b:
            t = (frame - a) / (b - a)
            return tuple(x + (y - x) * t for x, y in zip(va, vb))
    return ordered[-1][1]


class Builder:
    def __init__(self, plan_path: Path, name: str | None, allow_surrogate: bool):
        self.plan_path = plan_path.resolve()
        self.base = self.plan_path.parent
        self.plan = jy_common.load_json(self.plan_path)
        self.name = name or self.plan["name"]
        if not self.name or self.name in (".", "..") or "/" in self.name or "\\" in self.name:
            raise ValueError("草稿名必须是单个目录名")
        self.fps = int(self.plan.get("fps", 30))
        self.cw, self.ch = self.plan.get("canvas", [1920, 1080])
        self.total = int(self.plan["total_frames"])
        self.canvas = jy_camera.Canvas((self.cw, self.ch), tuple(self.plan.get("source_canvas", [self.cw, self.ch])))
        self.brand_path = jy_common.resolve(self.base, self.plan["brand"])
        self.brand = jy_common.load_json(self.brand_path)
        self.jy = self.brand["jianying"]
        self.tracks = {**DEFAULT_TRACK_NAMES, **self.plan.get("track_names", {})}
        self.sanitized = self._manifest("sanitize_manifest", "clips")
        self.segments = self._manifest("segments_manifest", "segments")
        self.surrogate = bool(self.segments.pop("__surrogate__", False))
        if self.surrogate and not allow_surrogate:
            raise RuntimeError("烘焙段是替身素材，只能流程自测：加 --allow-surrogate，且不能安装")
        self.generated = jy_common.resolve(self.base, self.plan.get("generated_dir", "素材/生成"))
        self.generated.mkdir(parents=True, exist_ok=True)
        self.materials: dict[str, draft.VideoMaterial] = {}
        self.probe_cache: dict[str, dict] = {}

    # ---------- 输入 ----------
    def _manifest(self, key: str, field: str) -> dict:
        path = jy_common.resolve(self.base, self.plan.get(key))
        if not path:
            return {}
        data = jy_common.load_json(path)
        out = {item["id"]: item for item in data[field]}
        if data.get("surrogate"):
            out["__surrogate__"] = True
        return out

    def f2us(self, frame) -> int:
        return jy_common.f2us(frame, self.fps)

    def timerange(self, start, end) -> Timerange:
        return Timerange(self.f2us(start), self.f2us(end) - self.f2us(start))

    def media(self, entry: dict) -> dict:
        """统一成 path / source_in / live（可播帧数）/ frames / freeze_frame。"""
        if "from_sanitized" in entry:
            rec = self.sanitized[entry["from_sanitized"]]
            info = {"path": rec["path"], "source_in": rec["source_in_frames"], "live": rec["story_frames"],
                    "frames": rec["frames"], "freeze_frame": rec["story_last_frame_in_output"],
                    "size": (rec["width"], rec["height"])}
        elif "from_segment" in entry:
            rec = self.segments[entry["from_segment"]]
            info = {"path": rec["path"], "source_in": 0, "live": rec["frames"], "frames": rec["frames"],
                    "freeze_frame": rec["frames"] - 1, "size": (self.cw, self.ch)}
        else:
            path = str(jy_common.resolve(self.base, entry["media"]))
            if Path(path).suffix.lower() in IMAGE_SUFFIXES:
                info = {"path": path, "source_in": 0, "live": None, "frames": None, "freeze_frame": None,
                        "size": jy_common.image_size(path)}
            else:
                probe = self.probe_cache.setdefault(path, jy_common.probe_video(path))
                info = {"path": path, "source_in": 0, "live": None, "frames": probe["frames"],
                        "freeze_frame": None, "size": (probe["width"], probe["height"])}
        if "source_in" in entry:
            info["source_in"] = int(entry["source_in"])
        if info["frames"] is not None:
            if info["live"] is None or "source_in" in entry:
                info["live"] = info["frames"] - info["source_in"]
            if "live_frames" in entry:
                info["live"] = int(entry["live_frames"])
            info["freeze_frame"] = info["source_in"] + info["live"] - 1
        return info

    def material(self, path: str, frames: int | None) -> draft.VideoMaterial:
        """同一文件共用一个素材：剪映里「替换素材」会让引用它的所有片段一起换。"""
        if path not in self.materials:
            mat = draft.VideoMaterial(path)
            if frames is not None:
                mat.duration = self.f2us(frames)
            self.materials[path] = mat
        return self.materials[path]

    def camera(self, value, start: int):
        if value is None:
            return None
        ops = self.plan.get("cameras", {})[value] if isinstance(value, str) else value
        return jy_camera.build_points(ops, start, self.canvas)

    # ---------- 生成的辅助素材 ----------
    def make_scrims(self) -> dict:
        cfg = self.jy["lower_third_scrim"]
        r, g, b = (int(v * 255) for v in hex_rgb(self.brand["colors"]["bg"]))
        alpha = float(cfg["to_rgba"].rsplit(",", 1)[1].rstrip(")"))
        start = int(cfg["from_y"])
        shade = Image.new("RGBA", (self.cw, self.ch), (r, g, b, 0))
        draw = ImageDraw.Draw(shade)
        for y in range(start, self.ch):
            draw.line((0, y, self.cw - 1, y), fill=(r, g, b, round(255 * alpha * (y - start) / (self.ch - 1 - start))))
        bottom, top = self.generated / "字幕底衬_下方渐暗.png", self.generated / "字幕底衬_上方渐暗.png"
        shade.save(bottom)
        shade.transpose(Image.FLIP_TOP_BOTTOM).save(top)
        return {"bottom": bottom, "top": top}

    def make_border(self, size: tuple[int, int]) -> Path:
        cfg = self.jy["pip_border"]
        w, h = size
        line = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        color = tuple(int(v * 255) for v in hex_rgb(cfg["color"])) + (255,)
        lw = int(cfg["line_px"])
        ImageDraw.Draw(line).rounded_rectangle((lw, lw, w - 1 - lw, h - 1 - lw), radius=int(cfg["radius_px"]),
                                               outline=color, width=lw)
        glow = line.filter(ImageFilter.GaussianBlur(float(cfg["glow_blur"])))
        glow.putalpha(glow.getchannel("A").point(lambda a: round(a * float(cfg["glow_alpha"]))))
        path = self.generated / f"画中画边框_{w}x{h}.png"
        Image.alpha_composite(glow, line).save(path)
        return path

    def freeze_png(self, path: str, frame: int, ident: str) -> Path:
        """定格帧取自已打码素材，不能回原片取，否则敏感文字会在定格段重新出现。"""
        target = self.generated / "定格" / f"{ident}_源帧{frame}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        jy_common.run([jy_common.ffmpeg_bin(), "-v", "error", "-y", "-i", path, "-vf", f"select=eq(n\\,{frame})",
                       "-frames:v", "1", "-update", "1", str(target)])
        if not target.exists():
            raise RuntimeError(f"没能抽出定格帧：{path}:{frame}")
        return target

    # ---------- 文字 ----------
    def font_setup(self) -> dict:
        mode = self.plan.get("font_mode", self.jy.get("font_mode", "default"))
        info = {"mode": mode, "path": None, "native": None}
        if mode == "system":
            path = self.plan.get("font_path") or jy_common.find_system_font(self.brand["fonts"]["system_ttc"])
            if not path or not Path(path).is_file():
                raise RuntimeError(f"找不到系统字体 {self.brand['fonts']['system_ttc']}；可在计划里写 font_path，或改 library 模式")
            info["path"] = str(path)
        elif mode == "library":
            name = self.jy["library_fallback"]
            if not hasattr(FontType, name):
                raise ValueError(f"FontType 里没有 {name}")
            info["native"] = getattr(FontType, name)
        elif mode != "default":
            raise ValueError("font_mode 只能是 system、library 或 default")
        self.measure_font = info["path"]
        return info

    def text_width(self, text: str, px: float) -> float:
        # 剪映按 ttc 第 0 个字形渲染，宽度也按第 0 个量；量不了时按全角估。
        if self.measure_font:
            return float(ImageFont.truetype(self.measure_font, px, index=0).getlength(text))
        return len(text) * px

    def text(self, script, text, start, end, *, kind, xy, font) -> draft.TextSegment:
        style = self.jy[kind]
        px = style["size"] * 10.8 if kind == "caption" else style["px"]
        color = style["text_color"] if kind == "caption" else style["color"]
        seg = draft.TextSegment(
            text, self.timerange(start, end), font=font,
            style=TextStyle(size=px / 10.8, bold=False, color=hex_rgb(color), align=1, auto_wrapping=False,
                            max_line_width=self.jy["caption"].get("max_width_px", 1100) / self.cw),
            clip_settings=ClipSettings(transform_x=(xy[0] - self.cw / 2) / (self.cw / 2),
                                       transform_y=(self.ch / 2 - xy[1]) / (self.ch / 2)),
            background=TextBackground(color=style["bg_color"], alpha=float(style.get("bg_alpha", 1)),
                                      round_radius=float(style["round_radius"]), height=float(style["bg_height"]),
                                      width=float(style["bg_width"])))
        if kind == "caption" and style.get("intro"):
            seg.add_animation(getattr(TextIntro, style["intro"]), duration=self.f2us(style.get("intro_frames", 6)))
        script.add_segment(seg, self.tracks[kind])
        return seg

    # ---------- 品牌图层 ----------
    @staticmethod
    def overlay_points(keys: list[dict]) -> dict:
        """关键帧 → {帧: (x, y, size, alpha)}。size 是图片显示高度或文字缩放倍数；key 带 ease: out 时按三次 ease-out 预采样 7 点，ease: inout 按三次慢进慢出预采样 11 点。"""
        points = {}
        prev = None
        for key in sorted(keys, key=lambda k: k["f"]):
            value = (float(key["x"]), float(key["y"]), float(key.get("h", key.get("scale", 1))), float(key.get("alpha", 1)))
            ease = key.get("ease")
            if prev is not None and ease in ("out", "inout") and key["f"] - prev[0] > 1:
                a, va = prev
                span = key["f"] - a
                for p in ((.125, .25, .5, .75, .875) if ease == "out" else (.1, .2, .3, .4, .5, .6, .7, .8, .9)):
                    frame = round(a + span * p)
                    t = (frame - a) / span
                    e = 1 - (1 - t) ** 3 if ease == "out" else (4 * t ** 3 if t < .5 else 1 - (-2 * t + 2) ** 3 / 2)
                    points[frame] = tuple(x + (y - x) * e for x, y in zip(va, value))
            points[key["f"]] = value
            prev = (key["f"], value)
        return points

    def overlay_segment(self, item: dict, kind: str, font):
        start, end = int(item["start"]), int(item["end"])
        points = self.overlay_points(item["keys"])

        def jy_values(v):
            x, y, size, alpha = v
            tx, ty = (x - self.cw / 2) / (self.cw / 2), (self.ch / 2 - y) / (self.ch / 2)
            if kind == "image":
                iw, ih = jy_common.image_size(str(jy_common.resolve(self.base, item["media"])))
                scale = size / (ih * min(self.cw / iw, self.ch / ih))
            else:
                scale = size
            return scale, tx, ty, alpha

        first = jy_values(sample_points(points, start))
        clip = ClipSettings(scale_x=first[0], scale_y=first[0], transform_x=first[1], transform_y=first[2], alpha=first[3])
        if kind == "image":
            mat = self.material(str(jy_common.resolve(self.base, item["media"])), None)
            seg = draft.VideoSegment(mat, self.timerange(start, end), clip_settings=clip, volume=0)
        else:
            seg = draft.TextSegment(
                item["text"], self.timerange(start, end), font=font,
                style=TextStyle(size=float(item["px"]) / 10.8, bold=bool(item.get("bold", False)),
                                color=hex_rgb(item.get("color", self.brand["colors"]["text"])), align=1,
                                letter_spacing=int(item.get("letter_spacing", 0)), auto_wrapping=False,
                                max_line_width=1.0),
                clip_settings=clip,
                # 可选阴影、描边：旁白字幕压在录屏上时用，参数和剪映文本面板一致
                shadow=TextShadow(alpha=float(item["shadow"].get("alpha", .8)), color=hex_rgb(item["shadow"].get("color", "#000000")),
                                  diffuse=float(item["shadow"].get("diffuse", 15)), distance=float(item["shadow"].get("distance", 3)),
                                  angle=float(item["shadow"].get("angle", -45))) if item.get("shadow") else None,
                border=TextBorder(alpha=float(item["border"].get("alpha", 1)), color=hex_rgb(item["border"].get("color", "#000000")),
                                  width=float(item["border"].get("width", 20))) if item.get("border") else None)
        frames = sorted({start, end} | {f for f in points if start < f < end})
        if len(points) > 1:
            for frame in frames:
                offset = self.f2us(frame) - self.f2us(start)
                scale, tx, ty, alpha = jy_values(sample_points(points, frame))
                for prop, value in ((KeyframeProperty.uniform_scale, scale), (KeyframeProperty.position_x, tx),
                                    (KeyframeProperty.position_y, ty), (KeyframeProperty.alpha, alpha)):
                    seg.add_keyframe(prop, offset, float(value))
        for slot, table in (("intro", TextIntro if kind == "text" else IntroType),
                            ("outro", TextOutro if kind == "text" else OutroType)):
            if item.get(slot):
                seg.add_animation(getattr(table, item[slot]["name"]), duration=self.f2us(item[slot].get("frames", 8)))
        return seg

    # ---------- 运镜写入 ----------
    def add_camera(self, segment, points: dict, start: int, end: int) -> None:
        frames = sorted({start, end} | {f for f in points if start < f < end})
        initial = jy_camera.sample(points, start)
        segment.clip_settings.scale_x = segment.clip_settings.scale_y = initial[0]
        segment.clip_settings.transform_x, segment.clip_settings.transform_y = initial[1:]
        for frame in frames:
            # 偏移是相对片段起点的精确微秒，不能 f2us(frame-start) 再取整。
            offset = self.f2us(frame) - self.f2us(start)
            for prop, value in zip((KeyframeProperty.uniform_scale, KeyframeProperty.position_x,
                                    KeyframeProperty.position_y), jy_camera.sample(points, frame)):
                segment.add_keyframe(prop, offset, float(value))

    # ---------- 主流程 ----------
    def build(self) -> Path:
        plan, jy = self.plan, self.jy
        main_plan = plan["main"]
        bounds = [(m["start"], m["end"]) for m in main_plan]
        if bounds[0][0] != 0 or bounds[-1][1] != self.total or any(a[1] != b[0] for a, b in zip(bounds, bounds[1:])):
            raise ValueError(f"主画面必须从 0 首尾相接到 {self.total}：{bounds}")
        font = self.font_setup()
        cameras = {m["id"]: self.camera(m.get("camera"), m["start"]) for m in main_plan if m.get("camera")}
        coordinate_checks = []
        for ops in [m.get("camera") for m in main_plan] + list(plan.get("cameras", {}).values()):
            if isinstance(ops, list):
                for op in ops:
                    if "rect" in op:
                        rect = self.canvas.largest_fit(op["rect"]) if op.get("fit") else op["rect"]
                        err = self.canvas.check_rect(rect)
                        if err > 1e-6:
                            raise AssertionError(f"坐标换算失败：{rect}")
                        x, y, w, h = rect
                        if x < -.5 or y < -.5 or x + w > self.canvas.sw + .5 or y + h > self.canvas.sh + .5:
                            raise ValueError(f"运镜框越出源画面 {self.canvas.sw}×{self.canvas.sh}，会露出黑边：{rect}")
                        coordinate_checks.append({"rect": rect, "max_error_px": err})
        captions = plan.get("captions", [])
        avoid = plan.get("caption_avoid", {"enabled": True, "limit_bottom_px": 860})
        adjustments, clearance = [], {"enabled": False}
        if avoid.get("enabled", True) and cameras:
            cameras, adjustments, clearance = jy_camera.avoid_captions(
                cameras, [m for m in main_plan if m["id"] in cameras], captions, self.canvas,
                float(avoid.get("limit_bottom_px", 860)))
        used = {"main": True, "pip": bool(plan.get("pip")), "pip_border": any(p.get("border", True) for p in plan.get("pip", [])),
                "scrim": bool(captions) and any(m.get("scrim", bool(m.get("camera"))) for m in main_plan),
                "chapter": bool(plan.get("chapters")), "caption": bool(captions), "bgm": bool(plan.get("bgm")),
                "overlays": bool(plan.get("overlays"))}
        track_order = []
        for k in TRACK_KEYS:
            if k == "overlays":
                for i, layer in enumerate(plan.get("overlays", [])):
                    key = f"overlay_{layer['kind']}:{i}"
                    self.tracks[key] = layer["name"]
                    track_order.append(key)
            elif used[k]:
                track_order.append(k)
        work = jy_common.resolve(self.base, plan.get("staging", "staging")) / ".builds" / uuid.uuid4().hex
        work.mkdir(parents=True)
        script = draft.DraftFolder(str(work)).create_draft(self.name, self.cw, self.ch, fps=self.fps)
        kinds = {"bgm": draft.TrackType.audio, "chapter": draft.TrackType.text, "caption": draft.TrackType.text}
        for key in track_order:
            kind = draft.TrackType.text if key.startswith("overlay_text:") else kinds.get(key, draft.TrackType.video)
            script.append_track(draft.TrackSpec(kind, name=self.tracks[key]))
        manifest = {"schema": "liang-promo-jianying/build-1", "name": self.name, "fps": self.fps,
                    "canvas": [self.cw, self.ch], "source_canvas": [self.canvas.sw, self.canvas.sh],
                    "total_frames": self.total, "duration_us": self.f2us(self.total), "surrogate": self.surrogate,
                    "plan": str(self.plan_path), "plan_sha256": jy_common.sha256(self.plan_path),
                    "brand": str(self.brand_path), "tracks": [self.tracks[k] for k in track_order],
                    "track_keys": track_order, "shots": [], "transitions": [], "pip": [], "chapters": [],
                    "captions": [], "scrims": [], "overlays": [], "coordinate_checks": coordinate_checks,
                    "camera_adjustments": adjustments, "caption_clearance": clearance,
                    "cameras": {k: sorted([f, *v] for f, v in pts.items()) for k, pts in cameras.items()}}

        # 主画面：每个逻辑镜头一段；素材不够时尾部接一张已打码的末帧定格。
        for entry in main_plan:
            ident, start, end = entry["id"], entry["start"], entry["end"]
            info = self.media(entry)
            parts = []
            if info["frames"] is None:
                parts.append(("image", info["path"], start, end, 0, None))
            else:
                live = min(end - start, info["live"])
                if live <= 0:
                    raise ValueError(f"{ident} 没有可用帧")
                parts.append(("video", info["path"], start, start + live, info["source_in"], info["frames"]))
                if live < end - start:
                    png = self.freeze_png(info["path"], info["freeze_frame"], ident)
                    parts.append(("freeze", str(png), start + live, end, 0, None))
            shot = {"id": ident, "start_frame": start, "end_frame": end, "camera": ident in cameras,
                    "scrim": bool(entry.get("scrim", ident in cameras)), "segments": []}
            for kind, path, a, b, source_start, frames in parts:
                mat = self.material(path, frames)
                seg = draft.VideoSegment(mat, self.timerange(a, b),
                                         source_timerange=self.timerange(source_start, source_start + b - a), volume=0)
                if ident in cameras:
                    self.add_camera(seg, cameras[ident], a, b)
                trans = entry.get("transition_out")
                if b == end and trans:
                    transition = getattr(TransitionType, trans["name"])
                    seg.add_transition(transition, duration=self.f2us(trans.get("frames", 8)))
                    manifest["transitions"].append({"cut_frame": end, "name": trans["name"],
                                                    "frames": trans.get("frames", 8), "segment_id": seg.segment_id,
                                                    "is_vip": getattr(transition.value, "is_vip", False)})
                script.add_segment(seg, self.tracks["main"])
                shot["segments"].append({"id": seg.segment_id, "kind": kind, "start_frame": a, "end_frame": b,
                                         "path": path, "source_start_frame": source_start, "source_frames": b - a,
                                         "material_id": mat.material_id})
            manifest["shots"].append(shot)

        # 画中画和边框：边框和视频同尺寸、同关键帧、同入场，严格对齐。
        borders = {}
        for entry in plan.get("pip", []):
            info = self.media(entry)
            a, b, source = entry["start"], entry["end"], info["source_in"]
            if source + (b - a) > info["frames"]:
                raise ValueError(f"画中画 {entry['id']} 源区间超出素材")
            mat = self.material(info["path"], info["frames"])
            seg = draft.VideoSegment(mat, self.timerange(a, b), source_timerange=self.timerange(source, source + b - a),
                                     volume=0)
            points = self.camera(entry.get("camera"), a)
            row = {"id": entry["id"], "start_frame": a, "end_frame": b, "source_start_frame": source,
                   "source_frames": b - a, "path": info["path"], "segment_id": seg.segment_id,
                   "material_id": mat.material_id, "border_segment_id": None,
                   "camera": sorted([f, *v] for f, v in points.items()) if points else None}
            border = None
            if entry.get("border", True):
                size = tuple(info["size"])
                if size not in borders:
                    borders[size] = draft.VideoMaterial(str(self.make_border(size)))
                border = draft.VideoSegment(borders[size], self.timerange(a, b), volume=0)
                row["border_segment_id"] = border.segment_id
            for target in [seg] + ([border] if border else []):
                if points:
                    self.add_camera(target, points, a, b)
                if entry.get("intro"):
                    target.add_animation(getattr(IntroType, entry["intro"]["name"]),
                                         duration=self.f2us(entry["intro"].get("frames", 6)))
            script.add_segment(seg, self.tracks["pip"])
            if border:
                script.add_segment(border, self.tracks["pip_border"])
            manifest["pip"].append(row)

        # 章节：左上角，暗底亮金字。
        text_ids = []

        # 品牌图层：每层一条轨，图片或文字，同一层里的片段不能重叠。
        for i, layer in enumerate(plan.get("overlays", [])):
            key = f"overlay_{layer['kind']}:{i}"
            last = -1
            for item in sorted(layer["items"], key=lambda it: it["start"]):
                if item["start"] < last:
                    raise ValueError(f"品牌图层「{layer['name']}」里的片段重叠：{item['id']}")
                last = item["end"]
                seg = self.overlay_segment(item, layer["kind"], font["native"])
                script.add_segment(seg, self.tracks[key])
                if layer["kind"] == "text":
                    text_ids.append(seg.material_id)
                manifest["overlays"].append({"id": item["id"], "layer": layer["name"], "kind": layer["kind"],
                                             "start_frame": item["start"], "end_frame": item["end"],
                                             "segment_id": seg.segment_id, "material_id": seg.material_id,
                                             "text": item.get("text"), "media": item.get("media")})
        ch = jy["chapter"]
        for item in plan.get("chapters", []):
            width = self.text_width(item["text"], ch["px"]) + 2 * float(ch["bg_width"]) * ch["px"]
            xy = (ch.get("left_px", 56) + width / 2, ch.get("center_y_px", 66))
            seg = self.text(script, item["text"], item["start"], item["end"], kind="chapter", xy=xy, font=font["native"])
            text_ids.append(seg.material_id)
            manifest["chapters"].append({"text": item["text"], "start_frame": item["start"], "end_frame": item["end"],
                                         "segment_id": seg.segment_id, "material_id": seg.material_id, "position": list(xy)})

        # 说明：固定位置、品牌色胶囊底；录屏段垫底衬。
        cap = jy["caption"]
        px = cap["size"] * 10.8
        scrim_paths = self.make_scrims() if used["scrim"] else {}
        scrim_mats = {slot: draft.VideoMaterial(str(p)) for slot, p in scrim_paths.items()}
        fade = int(jy["lower_third_scrim"].get("fade_frames", 4))
        for item in captions:
            slot = item.get("slot", "bottom")
            xy = tuple(item.get("xy") or (self.cw / 2, cap["center_y_px"] if slot == "bottom" else cap["top_center_y_px"]))
            width = self.text_width(item["text"], px) + 2 * float(cap["bg_width"]) * px
            if width > cap.get("max_width_px", 1100):
                raise ValueError(f"说明太长（约 {width:.0f}px）：{item['text']}")
            seg = self.text(script, item["text"], item["start"], item["end"], kind="caption", xy=xy, font=font["native"])
            text_ids.append(seg.material_id)
            manifest["captions"].append({
                "text": item["text"], "start_frame": item["start"], "end_frame": item["end"], "slot": slot,
                "position": list(xy), "estimated_width_px": width, "estimated_height_px": 1.2 * px,
                "segment_id": seg.segment_id, "material_id": seg.material_id, "target": item.get("target")})
            for shot in manifest["shots"]:
                if not shot["scrim"]:
                    continue
                first, last = max(item["start"], shot["start_frame"]), min(item["end"], shot["end_frame"])
                if first >= last:
                    continue
                shade = draft.VideoSegment(scrim_mats[slot], self.timerange(first, last), volume=0)
                s0, e0 = item["start"], item["end"]

                def alpha(f, s0=s0, e0=e0):
                    return max(0, min(1, (f - s0) / fade, (e0 - f) / fade))
                # 说明跨镜头时按整条说明的淡入淡出包络截取，切点上不会多闪一下。
                for f in sorted({first, last} | {f for f in (s0 + fade, e0 - fade) if first < f < last}):
                    shade.add_keyframe(KeyframeProperty.alpha, self.f2us(f) - self.f2us(first), alpha(f))
                script.add_segment(shade, self.tracks["scrim"])
                manifest["scrims"].append({"segment_id": shade.segment_id, "caption_segment_id": seg.segment_id,
                                           "shot": shot["id"], "start_frame": first, "end_frame": last, "slot": slot})

        if plan.get("bgm"):
            bgm_path = str(jy_common.resolve(self.base, plan["bgm"]["path"]))
            bgm = draft.AudioMaterial(bgm_path)
            if bgm.duration < self.f2us(self.total):
                raise RuntimeError(f"BGM 不够 {self.total} 帧：{bgm.duration} 微秒")
            script.add_segment(draft.AudioSegment(bgm, self.timerange(0, self.total),
                                                  volume=float(plan["bgm"].get("volume", 1.0))), self.tracks["bgm"])
            manifest["bgm"] = {"path": bgm_path, "duration_us": bgm.duration}
        for track in script.tracks.values():
            track.segments.sort(key=lambda s: s.target_timerange.start)
        script.save()
        content = work / self.name / "draft_content.json"
        if font["mode"] == "system" and text_ids:
            title = jy.get("system_font_title", Path(font["path"]).stem)
            font["patched"] = jy_fonts.patch_text_fonts(content, {mid: (font["path"], title) for mid in text_ids})
        manifest["font"] = {k: v for k, v in font.items() if k != "native"}
        manifest["draft_content_sha256"] = jy_common.sha256(content)
        jy_common.save_json(work / self.name / "build_manifest.json", manifest)
        final = work.parent.parent / self.name
        if final.exists():
            stamp = datetime.now()
            trash = self.base / ".trash" / f"{stamp:%Y-%m-%d}_{self.name}_{stamp:%H%M%S}"
            trash.parent.mkdir(exist_ok=True)
            final.rename(trash)
            print(f"旧 staging 移到：{trash}")
        (work / self.name).rename(final)
        work.rmdir()
        print(f"已生成：{final}\n主画面 {len(manifest['shots'])} 个镜头 / "
              f"{sum(len(s['segments']) for s in manifest['shots'])} 个片段；画中画 {len(manifest['pip'])} 段；"
              f"说明 {len(manifest['captions'])} 条；章节 {len(manifest['chapters'])} 条；品牌图层 {len(manifest['overlays'])} 段；转场 {len(manifest['transitions'])} 个"
              + ("；替身素材，只能自测" if self.surrogate else ""))
        if clearance.get("exceptions"):
            print(f"说明避让有 {len(clearance['exceptions'])} 帧做不到，见 build_manifest.json 的 caption_clearance")
        return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--allow-surrogate", action="store_true", help="只用于流程自测，生成的草稿不能安装")
    args = parser.parse_args()
    Builder(args.plan, args.name, args.allow_surrogate).build()


if __name__ == "__main__":
    main()
