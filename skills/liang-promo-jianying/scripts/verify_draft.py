#!/usr/bin/env python3
"""回读 staging 草稿的明文 draft_content.json，逐项对照计划和品牌包。

用法：python verify_draft.py <staging/草稿名> [--out 报告.json]

检查：总长与帧率、轨道顺序、主画面首尾相接且切点等于计划、源区间不变速、运镜关键帧覆盖整段且是线性、
转场位置与种类、说明（文字、时间、至少 N 帧、同屏一条、固定位置、字号颜色底色、入场动画）、
章节、底衬只在录屏段且跟说明同进同出、画中画与边框严格对齐、BGM 覆盖全片、字体路径、素材都在、
说明是否压住目标（逐帧按真实关键帧投影）。

结构通过不等于剪映里视觉通过；字体留白、转场观感仍要在剪映里看一遍。
退出码：0 通过；1 有失败项。避让做不到但已在 build_manifest 里记账的帧算警告，不算失败。
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from pyJianYingDraft import IntroType, TextIntro, TransitionType

import jy_common
import jy_readback as rb
from build_draft import hex_rgb


def verify(draft_dir: Path) -> dict:
    content = jy_common.load_json(draft_dir / "draft_content.json")
    manifest = jy_common.load_json(draft_dir / "build_manifest.json")
    plan = jy_common.load_json(manifest["plan"])
    brand = jy_common.load_json(manifest["brand"])
    jy = brand["jianying"]
    fps, total = manifest["fps"], manifest["total_frames"]
    canvas = tuple(manifest["canvas"])
    failures, warnings = [], []

    def check(ok, label):
        if not ok:
            failures.append(label)

    def us(f):
        return jy_common.f2us(f, fps)

    def frames(seg):
        return tuple(jy_common.us2f(t, fps) for t in rb.timerange(seg))

    check(content.get("duration") == us(total), f"总时长不是 {total} 帧的精确微秒边界")
    check(content.get("fps") == fps, f"帧率不是 {fps}")
    cfg = content.get("canvas_config", {})
    check((cfg.get("width"), cfg.get("height")) == canvas, "画布尺寸不符")
    names = [t.get("name") for t in content.get("tracks", [])]
    check(names == manifest["tracks"], f"轨道顺序不符：{names}")
    tracks = rb.tracks_by_name(content)
    for index, (key, name) in enumerate(zip(manifest["track_keys"], manifest["tracks"])):
        kind = "audio" if key == "bgm" else "text" if key in ("chapter", "caption") or key.startswith("overlay_text:") else "video"
        check(tracks.get(name, {}).get("type") == kind, f"轨道类型错误：{name}")
        for seg in tracks.get(name, {}).get("segments", []):
            check(seg.get("render_index") == index, f"渲染层级不符：{name}")
    by_id = rb.materials_by_id(content)
    for group, items in content.get("materials", {}).items():
        if isinstance(items, list):
            for m in items:
                if isinstance(m, dict) and m.get("path"):
                    check(Path(m["path"]).exists(), f"素材文件缺失：{m['path']}")

    # 主画面
    main_name = manifest["tracks"][manifest["track_keys"].index("main")]
    main = sorted(tracks[main_name]["segments"], key=lambda s: rb.timerange(s)[0])
    cursor = 0
    for seg in main:
        a, b = rb.timerange(seg)
        check(a == cursor and b > a, f"主画面不连续：{seg['id']}")
        cursor = b
    check(cursor == us(total), "主画面没有铺到全片末尾")
    plan_bounds = [(m["id"], m["start"], m["end"]) for m in plan["main"]]
    check([(s["id"], s["start_frame"], s["end_frame"]) for s in manifest["shots"]] == plan_bounds,
          "主画面镜头边界和计划不一致")
    actual = {s["id"]: s for s in main}
    for shot in manifest["shots"]:
        for part in shot["segments"]:
            seg = actual.get(part["id"])
            check(seg is not None, f"清单里的片段不在草稿里：{shot['id']}")
            if not seg:
                continue
            check(rb.timerange(seg) == (us(part["start_frame"]), us(part["end_frame"])), f"片段边界不符：{shot['id']}")
            first, count = part["source_start_frame"], part["source_frames"]
            check(seg.get("source_timerange") == {"start": us(first), "duration": us(first + count) - us(first)},
                  f"源区间不符：{shot['id']}")
            dur = seg["target_timerange"]["duration"]
            check(abs(seg.get("speed", 1) - seg["source_timerange"]["duration"] / dur) < 1e-12 and
                  abs(seg["source_timerange"]["duration"] - dur) <= 1, f"源视频被变速：{shot['id']}")
            check(seg.get("volume") == 0, f"主画面带声音：{shot['id']}")
            check(Path(by_id[seg["material_id"]]["path"]).resolve() == Path(part["path"]).resolve(),
                  f"素材路径和清单不符：{shot['id']}")
            if shot["camera"]:
                groups = rb.keyframe_signature(seg)
                need = {"KFTypeScaleX", "KFTypePositionX", "KFTypePositionY"}
                check(need.issubset(groups), f"录屏缺运镜关键帧：{shot['id']}")
                for prop in need & set(groups):
                    offsets = [k["time_offset"] for k in groups[prop]]
                    check(offsets and offsets[0] == 0 and offsets[-1] == dur and offsets == sorted(set(offsets)),
                          f"关键帧没覆盖整段或乱序：{shot['id']}/{prop}")
                    check(all(k.get("curveType") == "Line" for k in groups[prop]), f"关键帧不是线性：{shot['id']}")

    # 转场
    expected_trans = {m["end"]: m["transition_out"]["name"] for m in plan["main"] if m.get("transition_out")}
    trans_by_id = {m["id"]: m for m in content.get("materials", {}).get("transitions", [])}
    observed = {}
    for seg in main:
        for ref in seg.get("extra_material_refs", []):
            if ref in trans_by_id:
                tr, cut = trans_by_id[ref], frames(seg)[1]
                observed[cut] = tr.get("name")
                value = TransitionType[tr["name"]].value
                check(tr.get("effect_id") == value.effect_id and tr.get("resource_id") == value.resource_id,
                      f"转场资源不匹配：{cut}/{tr['name']}")
    check(observed == expected_trans, f"转场和计划不符：实际 {observed}，计划 {expected_trans}")
    check(len(observed) == len(trans_by_id), "有没挂在主画面上的转场")

    anims = {m["id"]: m for m in content.get("materials", {}).get("material_animations", [])}

    def intro(seg):
        return [a for ref in seg.get("extra_material_refs", []) for a in anims.get(ref, {}).get("animations", [])
                if a.get("type") == "in"]

    # 说明
    cap = jy["caption"]
    px = cap["size"] * 10.8
    min_frames = int(cap.get("min_frames", 36))
    cap_name = manifest["tracks"][manifest["track_keys"].index("caption")] if "caption" in manifest["track_keys"] else None
    caption_segs = sorted(tracks.get(cap_name, {}).get("segments", []), key=lambda s: rb.timerange(s)[0])
    plan_caps = plan.get("captions", [])
    check([(rb.text_content(by_id[s["material_id"]]), *frames(s)) for s in caption_segs] ==
          [(c["text"], c["start"], c["end"]) for c in plan_caps], "说明文字或时间和计划不一致")
    previous = 0
    for seg, record in zip(caption_segs, manifest["captions"]):
        text = rb.text_content(by_id[seg["material_id"]])
        a, b = frames(seg)
        check(b - a >= min_frames, f"说明不足 {min_frames} 帧：{text}（{b - a} 帧）")
        check(rb.timerange(seg)[0] >= previous, f"说明同屏重叠：{text}")
        previous = rb.timerange(seg)[1]
        state = rb.segment_state(seg, rb.timerange(seg)[0])
        x, y = canvas[0] / 2 * (1 + state["tx"]), canvas[1] / 2 * (1 - state["ty"])
        check(abs(x - record["position"][0]) < 1e-6 and abs(y - record["position"][1]) < 1e-6,
              f"说明位置不是 {record['position']}：{text}")
        mat = by_id[seg["material_id"]]
        style = rb.text_style(mat)
        check(abs(style.get("size", 0) - cap["size"]) < 1e-8, f"说明字号不是 {cap['size']}：{text}")
        rgb = style.get("fill", {}).get("content", {}).get("solid", {}).get("color", [])
        check(len(rgb) == 3 and all(abs(p - q) < 1e-8 for p, q in zip(rgb, hex_rgb(cap["text_color"]))),
              f"说明文字颜色不符：{text}")
        check(mat.get("background_color", "").upper() == cap["bg_color"].upper() and
              abs(mat.get("background_height", -1) - cap["bg_height"]) < 1e-8 and
              abs(mat.get("background_width", -1) - cap["bg_width"]) < 1e-8 and
              abs(mat.get("background_round_radius", 0) - cap["round_radius"]) < .05, f"说明底色样式不符：{text}")
        if cap.get("intro"):
            found = intro(seg)
            value = TextIntro[cap["intro"]].value
            check(len(found) == 1 and found[0].get("name") == value.title and
                  found[0].get("duration") == us(cap.get("intro_frames", 6)), f"说明入场动画不符：{text}")

    # 说明压没压住目标：按草稿里真实的关键帧逐帧投影
    limit = float(plan.get("caption_avoid", {}).get("limit_bottom_px", 860))
    declared = {(e["text"], e["frame"]) for e in manifest.get("caption_clearance", {}).get("exceptions", [])}
    clearance = []
    for record in manifest["captions"]:
        if not record.get("target"):
            continue
        worst, checked = -math.inf, 0
        for f in range(record["start_frame"], record["end_frame"]):
            rect = rb.target_at(record["target"], f)
            live = [s for s in main if rb.timerange(s)[0] <= us(f) < rb.timerange(s)[1]]
            if len(live) != 1:
                continue
            seg = live[0]
            shot = next(s for s in manifest["shots"] if any(p["id"] == seg["id"] for p in s["segments"]))
            if not shot["camera"]:
                continue
            box = rb.media_box(by_id[seg["material_id"]], rb.segment_state(seg, us(f)), canvas)
            target = rb.project_rect(rect, box)
            checked += 1
            if record["slot"] == "bottom":
                worst = max(worst, target[3])
                if target[3] >= limit:
                    (warnings if (record["text"], f) in declared else failures).append(
                        f"说明压住目标：{record['text']} F{f} 目标底边 {target[3]:.1f}px ≥ {limit:.0f}")
                if box["bottom"] < canvas[1] - .002:
                    failures.append(f"录屏下边缘露出画面：{record['text']} F{f}")
            else:
                cy, h = record["position"][1], record["estimated_height_px"]
                if target[1] < cy + h / 2:
                    failures.append(f"上方说明压住目标：{record['text']} F{f}")
        clearance.append({"text": record["text"], "frames_checked": checked, "max_target_bottom_px": worst})

    # 章节
    ch = jy["chapter"]
    if "chapter" in manifest["track_keys"]:
        segs = sorted(tracks[manifest["tracks"][manifest["track_keys"].index("chapter")]]["segments"],
                      key=lambda s: rb.timerange(s)[0])
        check([(rb.text_content(by_id[s["material_id"]]), *frames(s)) for s in segs] ==
              [(c["text"], c["start"], c["end"]) for c in plan.get("chapters", [])], "章节文字或时间和计划不一致")
        for s in segs:
            mat, text = by_id[s["material_id"]], rb.text_content(by_id[s["material_id"]])
            style = rb.text_style(mat)
            rgb = style.get("fill", {}).get("content", {}).get("solid", {}).get("color", [])
            check(abs(style.get("size", 0) * 10.8 - ch["px"]) < 1e-8, f"章节字号不符：{text}")
            check(len(rgb) == 3 and all(abs(p - q) < 1e-8 for p, q in zip(rgb, hex_rgb(ch["color"]))),
                  f"章节颜色不符：{text}")
            check(mat.get("background_color", "").upper() == ch["bg_color"].upper(), f"章节底色不符：{text}")

    # 底衬：恰好等于「说明 ∩ 垫底衬的镜头」，前后按整条说明淡入淡出
    fade = int(jy["lower_third_scrim"].get("fade_frames", 4))
    if "scrim" in manifest["track_keys"]:
        segs = sorted(tracks[manifest["tracks"][manifest["track_keys"].index("scrim")]]["segments"],
                      key=lambda s: rb.timerange(s)[0])
        expected = sorted((max(c["start"], s["start_frame"]), min(c["end"], s["end_frame"]), c["start"], c["end"])
                          for c in plan_caps for s in manifest["shots"]
                          if s["scrim"] and max(c["start"], s["start_frame"]) < min(c["end"], s["end_frame"]))
        check([frames(s) for s in segs] == [e[:2] for e in expected], "底衬时间不等于说明与录屏段的交集")
        for seg, (a, b, ca, cb) in zip(segs, expected):
            keys = [(k["time_offset"], k["values"][0]) for k in rb.keyframe_signature(seg).get("KFTypeAlpha", [])]
            want = [(us(f) - us(a), max(0, min(1, (f - ca) / fade, (cb - f) / fade)))
                    for f in sorted({a, b} | {f for f in (ca + fade, cb - fade) if a < f < b})]
            check(keys == want, f"底衬淡入淡出不符：F{a}–{b}")

    # 画中画与边框
    if manifest["pip"]:
        pip_track = tracks[manifest["tracks"][manifest["track_keys"].index("pip")]]
        border_track = tracks.get(manifest["tracks"][manifest["track_keys"].index("pip_border")], {}) \
            if "pip_border" in manifest["track_keys"] else {}
        pip_by_id = {s["id"]: s for s in pip_track["segments"]}
        border_by_id = {s["id"]: s for s in border_track.get("segments", [])}
        for row, entry in zip(manifest["pip"], plan["pip"]):
            seg = pip_by_id.get(row["segment_id"])
            check(seg is not None, f"画中画片段缺失：{row['id']}")
            if not seg:
                continue
            check(frames(seg) == (entry["start"], entry["end"]), f"画中画时间不符：{row['id']}")
            src = seg["source_timerange"]
            check(jy_common.us2f(src["start"], fps) == row["source_start_frame"], f"画中画源入点不符：{row['id']}")
            check(seg.get("volume") == 0, f"画中画带声音：{row['id']}")
            if entry.get("intro"):
                check(len(intro(seg)) == 1, f"画中画入场动画缺失：{row['id']}")
            else:
                check(not intro(seg), f"画中画不该有入场动画：{row['id']}")
            if row["border_segment_id"]:
                border = border_by_id.get(row["border_segment_id"])
                check(border is not None, f"边框缺失：{row['id']}")
                if border:
                    check(rb.timerange(border) == rb.timerange(seg), f"边框和视频时间不一致：{row['id']}")
                    check(rb.keyframe_signature(border) == rb.keyframe_signature(seg), f"边框和视频关键帧不一致：{row['id']}")
                    check(border.get("clip") == seg.get("clip"), f"边框和视频基础变换不一致：{row['id']}")
                    vm, bm = by_id[seg["material_id"]], by_id[border["material_id"]]
                    check((vm.get("width"), vm.get("height")) == (bm.get("width"), bm.get("height")),
                          f"边框尺寸和视频不同：{row['id']}")

    # BGM 与字体
    if plan.get("bgm"):
        bgm = tracks[manifest["tracks"][manifest["track_keys"].index("bgm")]]["segments"]
        check(len(bgm) == 1 and rb.timerange(bgm[0]) == (0, us(total)), "BGM 没覆盖全片")
    font = manifest.get("font", {})
    if font.get("mode") == "system":
        for m in content.get("materials", {}).get("texts", []):
            check(m.get("font_path") == font["path"], f"文字没指向系统字体：{rb.text_content(m)}")
        check(Path(font["path"]).is_file(), f"系统字体不存在：{font['path']}")

    # 品牌图层：每段都在、时间对、文字内容对
    seg_by_id = {seg["id"]: seg for t in content.get("tracks", []) for seg in t.get("segments", [])}
    for row in manifest.get("overlays", []):
        seg = seg_by_id.get(row["segment_id"])
        check(seg is not None, f"品牌图层缺片段：{row['id']}")
        if seg is not None:
            check(frames(seg) == (row["start_frame"], row["end_frame"]), f"品牌图层时间不符：{row['id']}")
            if row["kind"] == "text":
                check(rb.text_content(by_id[row["material_id"]]) == row["text"], f"品牌图层文字不符：{row['id']}")

    return {"draft_dir": str(draft_dir), "surrogate": manifest.get("surrogate"), "pass": not failures,
            "failures": failures, "warnings": warnings, "caption_clearance": clearance,
            "counts": {"shots": len(manifest["shots"]), "main_segments": len(main), "captions": len(caption_segs),
                       "chapters": len(manifest["chapters"]), "pip": len(manifest["pip"]), "transitions": len(observed),
                       "overlays": len(manifest.get("overlays", []))}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("draft_dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = verify(args.draft_dir.resolve())
    out = args.out or args.draft_dir / "verify_report.json"
    jy_common.save_json(out, report)
    c = report["counts"]
    print(f"{'通过' if report['pass'] else '未通过'}：{c['shots']} 个镜头 / {c['main_segments']} 个主轨片段 / "
          f"{c['captions']} 条说明 / {c['chapters']} 条章节 / {c['pip']} 段画中画 / {c['transitions']} 个转场"
          + ("（替身素材）" if report["surrogate"] else ""))
    for item in report["failures"][:30]:
        print("  失败：" + item)
    if report["warnings"]:
        print(f"  警告 {len(report['warnings'])} 条（已记账的避让例外），见 {out}")
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
