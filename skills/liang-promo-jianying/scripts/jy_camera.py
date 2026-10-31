"""录屏运镜的换算：源画面矩形 → 剪映的 uniform_scale、position_x、position_y。

剪映的画面先按比例 fit 进画布（fit 系数 k），再乘 uniform_scale；位移单位是半个
画布宽或高，y 向上为正。源画面 SW×SH、画布 CW×CH 时，源点 p 落在屏幕上：
  X = CW/2 + s·k·(px − SW/2) + CW/2·tx
  Y = CH/2 + s·k·(py − SH/2) − CH/2·ty
让画布比例的矩形 R=(x,y,w,h)、中心 (cx,cy) 铺满画布：
  s = CW/(k·w)；tx = s·k·(SW/2 − cx)/(CW/2)；ty = s·k·(cy − SH/2)/(CH/2)
1920×1056 录屏放进 1920×1080 时 k=1，上下各 12 px 黑边已经包含在 SH/2=528 里，
不要再加一次。

剪映关键帧之间只有线性插值，ease-out 用 7 个预采样点近似（见 ease_to）。
"""

from __future__ import annotations

import math

import jy_readback


class Canvas:
    def __init__(self, canvas=(1920, 1080), source=(1920, 1080)):
        self.cw, self.ch = canvas
        self.sw, self.sh = source
        self.k = min(self.cw / self.sw, self.ch / self.sh)
        self.aspect = self.cw / self.ch

    def largest_fit(self, rect):
        """矩形内居中取最大的画布比例矩形。"""
        x, y, w, h = rect
        rw, rh = min(w, h * self.aspect), min(h, w / self.aspect)
        return [x + (w - rw) / 2, y + (h - rh) / 2, rw, rh]

    def camera_for_rect(self, rect):
        x, y, w, h = rect
        if not math.isclose(w / h, self.aspect, abs_tol=1e-6):
            raise ValueError(f"运镜框必须是画布比例 {self.cw}:{self.ch}：{rect}；需要时加 \"fit\": true")
        s = self.cw / (self.k * w)
        cx, cy = x + w / 2, y + h / 2
        return (s, s * self.k * (self.sw / 2 - cx) / (self.cw / 2), s * self.k * (cy - self.sh / 2) / (self.ch / 2))

    def project_point(self, point, camera):
        s, tx, ty = camera
        return [self.cw / 2 + s * self.k * (point[0] - self.sw / 2) + self.cw / 2 * tx,
                self.ch / 2 + s * self.k * (point[1] - self.sh / 2) - self.ch / 2 * ty]

    def box_on_canvas(self, rect, camera):
        x, y, w, h = rect
        a, b = self.project_point((x, y), camera), self.project_point((x + w, y + h), camera)
        return [a[0], a[1], b[0], b[1]]

    def check_rect(self, rect):
        """角点和中心的投影必须正好落在画布角点和中心，返回最大误差像素。"""
        cam = self.camera_for_rect(rect)
        x, y, w, h = rect
        actual = [self.project_point(p, cam) for p in ((x, y), (x + w / 2, y + h / 2), (x + w, y + h))]
        expected = [[0, 0], [self.cw / 2, self.ch / 2], [self.cw, self.ch]]
        return max(abs(a - b) for p, q in zip(actual, expected) for a, b in zip(p, q))


def sample(points: dict, frame):
    ordered = sorted(points.items())
    if frame <= ordered[0][0]:
        return ordered[0][1]
    for (a, va), (b, vb) in zip(ordered, ordered[1:]):
        if frame <= b:
            t = (frame - a) / (b - a)
            return tuple(x + (y - x) * t for x, y in zip(va, vb))
    return ordered[-1][1]


def ease_to(points: dict, start: int, end: int, value) -> None:
    """三次 ease-out，预采样 7 个点，end 帧到位。"""
    initial = sample(points, start)
    for p in (0, .125, .25, .5, .75, .875, 1):
        frame = round(start + (end - start) * p)
        t = (frame - start) / max(1, end - start)
        e = 1 - (1 - t) ** 3
        points[frame] = tuple(a + (b - a) * e for a, b in zip(initial, value))


def _value(op: dict, canvas: Canvas):
    if "cam" in op:
        return tuple(float(v) for v in op["cam"])
    rect = op["rect"]
    if op.get("fit"):
        rect = canvas.largest_fit(rect)
    return canvas.camera_for_rect(rect)


def build_points(ops: list[dict], start: int, canvas: Canvas) -> dict:
    """按顺序执行运镜操作，得到 {全片帧: (s, tx, ty)}。

    set   在 f 帧（缺省为镜头起点）设定取景：rect（画布比例；fit=true 时取框内最大的画布比例矩形）或 cam
    ease  from→to 帧 ease-out 推到 rect 或 cam
    hold  在 f 帧钉住当前值，后面的 set 才不会从更早的点线性滑过来
    punch 冲击推近：f 帧前 attack 帧推到 ×amount，再 release 帧回原取景。三个量同乘，取景中心不动
    pop   画中画节拍脉冲：常态是 cam×amount，在 f 帧弹回 cam。只缩放，不动位置
    """
    points: dict = {}
    for op in ops:
        kind = op["op"]
        if kind == "set":
            points[int(op.get("f", start))] = _value(op, canvas)
        elif kind == "ease":
            if not points:
                raise ValueError("ease 之前必须先 set")
            ease_to(points, int(op["from"]), int(op["to"]), _value(op, canvas))
        elif kind == "hold":
            points[int(op["f"])] = sample(points, int(op["f"]))
        elif kind == "punch":
            f, amount = int(op["f"]), float(op.get("amount", 1.03))
            original = sample(points, f)
            ease_to(points, f - int(op.get("attack", 4)), f, tuple(v * amount for v in original))
            ease_to(points, f, f + int(op.get("release", 8)), original)
        elif kind == "pop":
            f, amount = int(op["f"]), float(op.get("amount", .97))
            base = _value(op, canvas)
            low = (base[0] * amount, *base[1:])
            attack, release = int(op.get("attack", 4)), int(op.get("release", 5))
            points[f - attack] = low
            ease_to(points, f - attack, f, base)
            ease_to(points, f, f + release, low)
        else:
            raise ValueError(f"未知运镜操作：{kind}")
    if not points:
        raise ValueError("运镜至少要有一个 set")
    return points


def target_at(caption: dict, frame: int):
    """说明的目标框（源画面坐标）。keys 按 from 分段生效，用于页面滚动或切页。"""
    return jy_readback.target_at(caption.get("target"), frame)


def avoid_captions(cameras: dict, shots: list[dict], captions: list[dict], canvas: Canvas,
                   limit_px: float = 860) -> tuple[dict, list, dict]:
    """说明固定在下方时，只上移 position_y 让目标底边高于 limit_px；缩放和 x 不变，录屏底边不露出。

    每个镜头取所有说明需要的最大上移量整体平移，避免说明入场时画面突跳；做不到的帧单独记账。
    """
    result = dict(cameras)
    changes, checks, exceptions = [], [], []
    for shot in shots:
        ident, start, end = shot["id"], shot["start"], shot["end"]
        if ident not in cameras:
            continue
        relevant = []
        for cap in captions:
            if cap.get("slot", "bottom") != "bottom" or not cap.get("target"):
                continue
            for f in range(max(cap["start"], start), min(cap["end"], end)):
                rect = target_at(cap, f)
                camera = sample(cameras[ident], f)
                bottom = canvas.project_point((rect[0] + rect[2], rect[1] + rect[3]), camera)[1]
                relevant.append((f, cap["text"], rect, max(0, bottom - (limit_px - .1))))
        wanted = max((r[3] for r in relevant), default=0)
        if wanted > 1e-7:
            shifted, offsets = {}, {}
            for f in range(start, end + 1):
                camera = sample(cameras[ident], f)
                allowance = max(0, canvas.project_point((0, canvas.sh), camera)[1] - canvas.ch)
                delta = min(wanted, allowance)
                shifted[f] = (camera[0], camera[1], camera[2] + delta / (canvas.ch / 2))
                offsets[f] = delta
            result[ident] = shifted
            changes.append({"shot": ident, "requested_up_px": wanted,
                            "min_up_px": min(offsets.values()), "max_up_px": max(offsets.values()),
                            "scale_unchanged": True, "position_x_unchanged": True})
        for f, text, rect, _ in relevant:
            camera = sample(result[ident], f)
            raw_bottom = canvas.project_point((rect[0] + rect[2], rect[1] + rect[3]), camera)[1]
            edge = canvas.project_point((0, canvas.sh), camera)[1]
            row = {"frame": f, "shot": ident, "text": text, "target_bottom_px": raw_bottom,
                   "recording_bottom_px": edge, "pass": raw_bottom < limit_px and edge >= canvas.ch - 1e-6}
            checks.append(row)
            if not row["pass"]:
                exceptions.append(row)
    return result, changes, {"limit_target_bottom_px": limit_px, "checked_frames": len(checks),
                             "all_pass": not exceptions, "exceptions": exceptions}
