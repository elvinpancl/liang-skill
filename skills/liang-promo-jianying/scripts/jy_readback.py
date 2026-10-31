"""回读明文 draft_content.json：片段时间、关键帧插值、文字内容、素材在画布上的投影。

verify_draft.py 和 preview_layout.py 共用。只支持线性关键帧，遇到曲线或旋转直接报错，
不猜。
"""

from __future__ import annotations

import json


def timerange(segment: dict) -> tuple[int, int]:
    r = segment["target_timerange"]
    return r["start"], r["start"] + r["duration"]


def text_content(material: dict) -> str:
    content = material.get("content", "")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return content
    return content.get("text", "") if isinstance(content, dict) else ""


def text_style(material: dict) -> dict:
    try:
        return json.loads(material.get("content", "{}")).get("styles", [{}])[0]
    except json.JSONDecodeError:
        return {}


def keyframe_signature(segment: dict) -> dict:
    """关键帧 id 每次生成都不同，比较时忽略 id，只看属性、偏移、曲线和值。"""
    return {g["property_type"]: [{k: v for k, v in p.items() if k != "id"} for p in g.get("keyframe_list", [])]
            for g in segment.get("common_keyframes", [])}


def _interpolate(points: list[tuple], t: float):
    points = sorted(points)
    if t <= points[0][0]:
        return points[0][1]
    for (a, va), (b, vb) in zip(points, points[1:]):
        if t <= b:
            return va + (vb - va) * (t - a) / (b - a)
    return points[-1][1]


def segment_state(segment: dict, time_us: int) -> dict:
    clip = segment.get("clip") or {}
    scale = clip.get("scale", {"x": 1, "y": 1})
    transform = clip.get("transform", {"x": 0, "y": 0})
    state = {"sx": scale["x"], "sy": scale["y"], "tx": transform["x"], "ty": transform["y"],
             "rotation": clip.get("rotation", 0), "alpha": clip.get("alpha", 1)}
    key_map = {"KFTypeScaleX": "sx", "KFTypeScaleY": "sy", "KFTypePositionX": "tx", "KFTypePositionY": "ty",
               "KFTypeRotation": "rotation", "KFTypeAlpha": "alpha"}
    local = time_us - segment["target_timerange"]["start"]
    props = set()
    for group in segment.get("common_keyframes", []):
        prop = group["property_type"]
        if prop not in key_map or not group.get("keyframe_list"):
            continue
        if any(k.get("curveType", "Line") != "Line" for k in group["keyframe_list"]):
            raise ValueError("发现非线性关键帧曲线，回读只支持线性")
        state[key_map[prop]] = _interpolate([(k["time_offset"], k["values"][0]) for k in group["keyframe_list"]], local)
        props.add(prop)
    # uniform_scale 只写 ScaleX，打开等比时 Y 跟着 X；clip.scale 是基值，关键帧直接替换它。
    if segment.get("uniform_scale", {}).get("on") and "KFTypeScaleX" in props and "KFTypeScaleY" not in props:
        state["sy"] = state["sx"]
    if abs(state["rotation"]) > 1e-8:
        raise ValueError("片段带旋转，回读不支持")
    return state


def media_box(material: dict, state: dict, canvas: tuple[int, int]) -> dict:
    """素材先等比 fit 进画布，再乘缩放、按半画布单位位移（y 向上为正）。"""
    cw, ch = canvas
    w, h = material.get("width") or cw, material.get("height") or ch
    fit = min(cw / w, ch / h)
    sx, sy = fit * state["sx"], fit * state["sy"]
    left = cw / 2 * (1 + state["tx"]) - w * sx / 2
    top = ch / 2 * (1 - state["ty"]) - h * sy / 2
    return {"left": left, "top": top, "sx": sx, "sy": sy, "w": w, "h": h, "bottom": top + h * sy}


def project_rect(rect, box: dict) -> list[float]:
    """源素材像素矩形 → 画布上的 [x0, y0, x1, y1]。"""
    x, y, w, h = rect
    return [box["left"] + x * box["sx"], box["top"] + y * box["sy"],
            box["left"] + (x + w) * box["sx"], box["top"] + (y + h) * box["sy"]]


def intersects(a, b) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def materials_by_id(content: dict) -> dict:
    return {m["id"]: m for group in content.get("materials", {}).values() if isinstance(group, list)
            for m in group if isinstance(m, dict) and "id" in m}


def tracks_by_name(content: dict) -> dict:
    return {t.get("name"): t for t in content.get("tracks", [])}


def target_at(target: dict | None, frame: int):
    if not target:
        return None
    if "keys" in target:
        keys = sorted(target["keys"], key=lambda k: k["from"])
        current = keys[0]["rect"]
        for key in keys:
            if frame >= key["from"]:
                current = key["rect"]
        return current
    return target["rect"]
