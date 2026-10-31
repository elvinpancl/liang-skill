#!/usr/bin/env python3
"""Deterministic, bar-aligned stereo edit with duration-preserving crossfades.

用法：python cut_music.py PLAN.json
PLAN 里的路径都相对于 PLAN 所在目录。例：
{
  "src": "../bgm_original.mp3", "grid_file": "../accents.json",
  "output": "bgm_A.mp3", "crossfade_ms": 50, "headroom_db": 1.0,
  "segments": [{"start": 0, "end": 52}, {"start": 141, "end": "EOF"}]
}

The 50 ms crossfade ENDS at the nominal downbeat. The incoming pre-roll handle
is mixed into the outgoing tail; incoming sample start stays at the cut. Unlike
ordinary overlap concatenation, this never shortens the edit or shifts its grid.
No time stretch, dynamics processing, per-segment normalization, or extra fade.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import shutil
import tempfile

sys.dont_write_bytecode = True
CACHE = Path(os.environ.get("LIANG_BEAT_CACHE", Path(tempfile.gettempdir()) / "liang-promo-beat-cache"))
for key, value in {
    "PYTHONDONTWRITEBYTECODE": "1",
    "NUMBA_CACHE_DIR": str(CACHE / "numba"),
    "MPLCONFIGDIR": str(CACHE / "matplotlib"),
}.items():
    os.environ[key] = value
for directory in [CACHE, CACHE / "numba", CACHE / "matplotlib"]:
    directory.mkdir(parents=True, exist_ok=True)
BASE = Path.cwd()  # run() 里改成 PLAN 所在目录，清单里的路径相对它写

import librosa
import numpy as np
import soundfile as sf

FFMPEG = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg"
FPS = 30


def safe_path(value: str | Path, base: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def relative(path: Path, base: Path | None = None) -> str:
    return os.path.relpath(path, base or BASE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while data := handle.read(1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False) + "\n", encoding="utf-8")


def rounded_sample(t: float, sr: int) -> int:
    return int(math.floor(t * sr + 0.5))


def frame(t: float) -> int:
    return int(math.floor(t * FPS + 0.5))


def frame_count(samples: int, sr: int) -> int:
    """Exclusive file end: include even a partly occupied final video frame."""
    return (samples * FPS + sr - 1) // sr


def peak_stats(audio: np.ndarray) -> dict:
    absolute = np.abs(audio)
    peak = float(absolute.max(initial=0))
    return {
        "sample_peak": peak,
        "sample_peak_dbfs": float(20 * np.log10(max(peak, 1e-12))),
        "samples_at_or_above_full_scale": int(np.count_nonzero(absolute >= 1)),
        "samples_above_full_scale": int(np.count_nonzero(absolute > 1)),
    }


def decode(path: Path) -> tuple[np.ndarray, int]:
    # libsndfile reads the MP3 gapless header, and keeps samples > 0 dBFS as floats.
    try:
        audio, sr = sf.read(path, dtype="float64", always_2d=True)
    except (sf.LibsndfileError, RuntimeError):
        proc = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a:0",
             "-c:a", "pcm_f32le", "-f", "wav", "pipe:1"],
            check=True, capture_output=True,
        )
        audio, sr = sf.read(io.BytesIO(proc.stdout), dtype="float64", always_2d=True)
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError("解码音频为空或包含无效样本")
    return audio, int(sr)


def snap_boundary(value: float | str, grid: dict, sr: int, count: int) -> dict:
    duration = count / sr
    if isinstance(value, str):
        if value.upper() != "EOF":
            raise ValueError(f"不支持的边界：{value!r}")
        return {"requested": value, "grid_t": duration, "t": duration,
                "sample": count, "frame": frame_count(count, sr), "kind": "EOF",
                "delta_ms": 0.0, "sample_quantization_ms": 0.0,
                "downbeat_k": None, "beat_index": None}
    value = float(value)
    if not math.isfinite(value) or value < 0 or value > duration + 0.5 / sr:
        raise ValueError(f"边界超出原曲范围：{value}")
    if value <= 0.5 / sr or abs(value - duration) <= 0.5 / sr:
        result = snap_boundary("EOF", grid, sr, count)
        if value <= 0.5 / sr:
            result.update(grid_t=0.0, t=0.0, sample=0, frame=0, kind="BOF")
        result["requested"] = value
        result["delta_ms"] = (result["t"] - value) * 1000
        return result
    t0, period = float(grid["t0"]), float(grid["beat_period"])
    phase = int(grid["downbeat_phase"])
    origin, bar_period = t0 + phase * period, 4 * period
    minimum = math.ceil((0 - origin) / bar_period)
    maximum = math.floor((duration - origin) / bar_period)
    k = min(maximum, max(minimum, math.floor((value - origin) / bar_period + 0.5)))
    ideal = origin + k * bar_period
    sample = rounded_sample(ideal, sr)
    actual = sample / sr
    return {"requested": value, "grid_t": ideal, "t": actual,
            "sample": sample, "frame": frame(actual), "kind": "downbeat",
            "delta_ms": (actual - value) * 1000,
            "sample_quantization_ms": (actual - ideal) * 1000,
            "downbeat_k": int(k), "beat_index": int(phase + 4 * k)}


def window_features(audio: np.ndarray, sr: int) -> dict:
    mono = audio.mean(axis=1)
    rms = math.sqrt(float(np.mean(np.square(audio))))
    magnitude = np.abs(librosa.stft(mono, n_fft=4096, hop_length=1024, center=False))
    chroma = librosa.feature.chroma_stft(S=magnitude ** 2, sr=sr, n_fft=4096,
                                        hop_length=1024, tuning=0.0).mean(axis=1)
    centroid = librosa.feature.spectral_centroid(S=magnitude, sr=sr,
                                                n_fft=4096).mean()
    return {"rms_dbfs": float(20 * np.log10(max(rms, 1e-12))),
            "chroma": chroma.tolist(), "centroid_hz": float(centroid),
            "sample_count": len(audio), "duration_sec": len(audio) / sr}


def splice_metrics(audio: np.ndarray, sr: int, left_end: int,
                   right_start: int, bar_samples: int) -> dict:
    left_start, right_end = left_end - bar_samples, right_start + bar_samples
    if left_start < 0 or right_end > len(audio):
        raise ValueError("接口无法取得前后各完整 1 小节的源音频")
    before = window_features(audio[left_start:left_end], sr)
    after = window_features(audio[right_start:right_end], sr)
    a, b = np.asarray(before["chroma"]), np.asarray(after["chroma"])
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    cosine = float(np.dot(a, b) / denominator) if denominator > 1e-12 else None
    delta_rms = after["rms_dbfs"] - before["rms_dbfs"]
    delta_centroid = after["centroid_hz"] - before["centroid_hz"]
    flags = []
    if abs(delta_rms) > 3:
        flags.append("响度变化超过 3 dB")
    if cosine is not None and cosine < 0.7:
        flags.append("色度余弦低于 0.70")
    if abs(delta_centroid) > 1000:
        flags.append("质心变化超过 1000 Hz")
    return {
        "before_source_window": [left_start / sr, left_end / sr],
        "after_source_window": [right_start / sr, right_end / sr],
        "before": before, "after": after,
        "rms_delta_db_after_minus_before": float(delta_rms),
        "rms_delta_db_abs": float(abs(delta_rms)),
        "chroma_cosine": cosine,
        "centroid_delta_hz_after_minus_before": float(delta_centroid),
        "centroid_delta_hz_abs": float(abs(delta_centroid)),
        "review_flags": flags,
    }


def encode(audio: np.ndarray, sr: int, path: Path, gain_db: float) -> None:
    gain = 10 ** (gain_db / 20)
    data = np.asarray(audio * gain, dtype="<f4")
    command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-f", "f32le", "-ar", str(sr), "-ac", str(audio.shape[1]),
               "-i", "pipe:0", "-map_metadata", "-1", "-c:a", "libmp3lame",
               "-b:a", "192k", "-write_xing", "1", "-id3v2_version", "3", str(path)]
    subprocess.run(command, input=data.tobytes(), capture_output=True, check=True)


def render_markdown(report: dict) -> str:
    source, out = report["source"], report["output"]
    gain = report["level_management"]
    lines = ["# 音乐剪辑接口报告", "",
             f"原曲：`{source['path']}`；输出：`{out['path']}`。",
             f"输出有效音频时长 **{out['duration_sec']:.6f} 秒**，"
             f"{out['sample_rate']} Hz、{out['channels']} 声道、192 kbps MP3，"
             f"30 帧/秒下共 {out['video_frame_count_ceil']} 帧。", "",
             "## 边界与交叉淡化", "",
             "内部边界吸附到原曲小节第一拍；首尾保留 0 和 EOF。源采样边界取最近采样点，"
             "内部切点帧号为秒数 × 30 后取最近帧；原曲 EOF 和输出最终终点向上取整为排他帧号，"
             "保留最后不足一整帧的音频，与逐帧 CSV 行数一致。音频本身不先量化到视频帧。",
             f"使用 {report['crossfade_ms']:.3f} 毫秒等功率交叉淡化（实际 "
             f"{report['crossfade_samples']} 个样本）。过渡全部发生在名义切点之前："
             "前段尾部与后段切入点之前的预卷素材（handle）混合，后段第一拍保持在名义切点。"
             "因此总时长等于各保留片段时长之和，后段拍网格不会因交叠提前。"
             "连续的原曲片段直接延续，不施加等功率叠加。", "",
             "| 段 | 原曲范围（秒，排他终点） | 原曲帧 | 输出范围（秒，排他终点） | 输出帧 |",
             "|---|---:|---:|---:|---:|"]
    for seg in report["segments"]:
        label = seg["label"].replace("|", "／")
        lines.append(f"| {seg['index']} {label} | {seg['source_start_t']:.6f}–"
                     f"{seg['source_end_t']:.6f} | {seg['source_start_frame']}–"
                     f"{seg['source_end_frame']} | {seg['output_start_t']:.6f}–"
                     f"{seg['output_end_t']:.6f} | {seg['output_start_frame']}–"
                     f"{seg['output_end_frame']} |")
    lines += ["", "## 接口指标", "",
              "指标使用切出前、切入后各完整 1 小节的原曲。响度采用全部声道样本的整体 RMS"
              "（dBFS），色度和质心使用声道平均后的频谱；差值均为「后 − 前」。"
              "统一增益不改变响度差、色度相似度或质心差。", "",
              "| 接口 | 输出秒 / 帧 | 源切出 → 切入（秒） | 前 / 后 RMS dBFS | 响度差 dB | 色度余弦 | 质心差 Hz |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for item in report["interfaces"]:
        m = item["source_metrics"]
        cosine = f"{m['chroma_cosine']:.4f}" if m["chroma_cosine"] is not None else "无定义"
        lines.append(f"| {item['index']} | {item['output_t']:.6f} / {item['output_frame']} | "
                     f"{item['source_out_t']:.6f} → {item['source_in_t']:.6f} | "
                     f"{m['before']['rms_dbfs']:.3f} / {m['after']['rms_dbfs']:.3f} | "
                     f"{m['rms_delta_db_after_minus_before']:+.3f} | {cosine} | "
                     f"{m['centroid_delta_hz_after_minus_before']:+.2f} |")
    lines += [""]
    lines.append("小节从网格 k=0 对应的第 1 小节开始计数；下表切出小节号指排他切出边界所在小节，"
                 "该小节未包含在前段中。4／8 小节乐句起点按 k 可被 4／8 整除标注，"
                 "这是规则分组参考，不单凭网格断言乐句语义。")
    lines += ["", "| 接口 | 源切出小节 / 4／8 小节组起点 | 源切入小节 / 4／8 小节组起点 | 接口性质 |",
              "|---|---|---|---|"]
    for item in report["interfaces"]:
        alignment = item["phrase_alignment"]
        def phrase_label(side: str) -> str:
            eight = alignment[f"{side}_is_8bar_phrase_start"]
            four = alignment[f"{side}_is_4bar_phrase_start"]
            return "4／8 小节起点" if eight else ("4 小节起点" if four else "非 4／8 小节起点")
        nature = "人工跳接" if item["crossfade_applied"] else "原曲连续延续"
        lines.append(f"| {item['index']} | 第 {item['source_out_bar']} 小节；{phrase_label('out')} | "
                     f"第 {item['source_in_bar']} 小节；{phrase_label('in')} | {nature} |")
    lines += [""]
    for item in report["interfaces"]:
        flags = "；".join(item["source_metrics"]["review_flags"]) or "未触发粗筛提示"
        lines.append(f"- 接口 {item['index']}：{flags}。输出切点距理论小节第一拍 "
                     f"{item['output_downbeat_error_ms']:+.4f} 毫秒。")
        if not item["crossfade_applied"]:
            lines.append("  这是原曲连续延续，未做人工跳接或交叉淡化；两侧响度／频谱变化为原曲自带的结构变化。")
        elif item["phrase_alignment"]["exception_to_phrase_preference"]:
            alignment = item["phrase_alignment"]
            lines.append("  本接口是「尽量放在 4／8 小节乐句边界」的例外：仍严格落在小节第一拍。")
            if not alignment["in_is_4bar_phrase_start"]:
                lines.append(f"  切入请求 {item['requested_source_in_t']} 秒吸附到最近下拍 k="
                             f"{item['source_in_downbeat_k']}（第 {item['source_in_bar']} 小节），"
                             f"从该处保留到下一 4 小节组起点之前的 {alignment['incoming_bars_to_next_4bar_start']} 小节。")
        if item["crossfade_applied"]:
            h = item["incoming_handle"]
            lines.append(f"  预卷取自原曲 {h['source_start_t']:.6f}–{h['source_end_t']:.6f} 秒"
                         f"（帧 {h['source_start_frame']}–{h['source_end_frame']}），混合到输出 "
                         f"{h['output_start_t']:.6f}–{h['output_end_t']:.6f} 秒"
                         f"（帧 {h['output_start_frame']}–{h['output_end_frame']}）。")
    lines += ["", "编码回读后，在实际输出接口两侧各 1 小节复测（包含交叉淡化和统一增益）：", "",
              "| 接口 | 前 / 后 RMS dBFS | 响度差 dB | 色度余弦 | 质心差 Hz |",
              "|---|---:|---:|---:|---:|"]
    for item in report["interfaces"]:
        m = item["encoded_output_metrics"]
        cosine = f"{m['chroma_cosine']:.4f}" if m["chroma_cosine"] is not None else "无定义"
        lines.append(f"| {item['index']} | {m['before']['rms_dbfs']:.3f} / {m['after']['rms_dbfs']:.3f} | "
                     f"{m['rms_delta_db_after_minus_before']:+.3f} | {cosine} | "
                     f"{m['centroid_delta_hz_after_minus_before']:+.2f} |")
    lines += ["", "这些阈值只用于接口复核提示，不能单独证明听感自然；色度相似也不等同于乐句语义连续。",
              "", "## 峰值、结尾与复现", "",
              f"- 原曲解码样本峰值 {source['peak']['sample_peak_dbfs']:+.3f} dBFS；"
              f"混合后、增益前为 {gain['before_gain']['sample_peak_dbfs']:+.3f} dBFS。",
              f"- 全片使用同一个固定增益 **{gain['applied_gain_db']:+.4f} dB**，"
              f"编码后解码样本峰值为 **{out['peak']['sample_peak_dbfs']:+.4f} dBFS**，"
              f"超过满幅的样本数为 {out['peak']['samples_above_full_scale']}。",
              "- 未使用限制器、逐段响度归一化或额外淡出；保留原曲末尾的完整渐弱／余音，"
              "整体增益均匀作用于首尾。样本峰值检查不等于过采样真峰值认证。",
              f"- 源文件 SHA-256：`{source['sha256']}`。处理前后哈希一致。",
              f"- 输出 SHA-256：`{out['sha256']}`。", "",
              "复跑使用同一 Python 环境、原曲和网格。输入方案的相对路径以方案所在目录为基准；"
              "`snapped_plan.json` 可直接作为脚本输入。详细采样点、理论边界、吸附量、预卷范围和"
              "编码复测记录见 `splice_report.json`。", ""]
    return "\n".join(lines)


def run(plan_path: Path) -> dict:
    global BASE
    plan_path = safe_path(plan_path, Path.cwd())
    BASE = plan_path.parent
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    src = safe_path(plan["src"], plan_path.parent)
    grid_path = safe_path(plan["grid_file"], plan_path.parent)
    output = safe_path(plan["output"], plan_path.parent)
    if output.suffix.lower() != ".mp3":
        raise ValueError("output 必须是 .mp3 文件")
    if output in {src, grid_path, plan_path}:
        raise ValueError("输出不得覆盖输入文件")
    grid = json.loads(grid_path.read_text(encoding="utf-8"))["grid"]
    if float(grid["beat_period"]) <= 0 or int(grid["downbeat_phase"]) not in range(4):
        raise ValueError("网格必须具有正拍长和 0–3 的 4/4 小节相位")
    crossfade_ms = float(plan.get("crossfade_ms", 50))
    headroom_db = float(plan.get("headroom_db", 1.0))
    if not 30 <= crossfade_ms <= 80:
        raise ValueError("交叉淡化必须在 30–80 毫秒之间")
    if not 1 <= headroom_db <= 12:
        raise ValueError("headroom_db 必须在 1–12 dB 之间")
    source_hash = sha256(src)
    audio, sr = decode(src)
    crossfade_samples = rounded_sample(crossfade_ms / 1000, sr)
    bar_samples = rounded_sample(4 * float(grid["beat_period"]), sr)
    segments, chunks, cursor = [], [], 0
    for index, item in enumerate(plan["segments"], 1):
        start = snap_boundary(item["start"], grid, sr, len(audio))
        end = snap_boundary(item["end"], grid, sr, len(audio))
        count = end["sample"] - start["sample"]
        if count <= crossfade_samples:
            raise ValueError(f"第 {index} 段吸附后长度不足")
        chunks.append(audio[start["sample"]:end["sample"]])
        segments.append({
            "index": index, "label": str(item.get("label", "")),
            "start_boundary": start, "end_boundary": end,
            "source_start_t": start["t"], "source_end_t": end["t"],
            "source_start_sample": start["sample"], "source_end_sample": end["sample"],
            "source_start_frame": start["frame"], "source_end_frame": end["frame"],
            "output_start_sample": cursor, "output_end_sample": cursor + count,
            "output_start_t": cursor / sr, "output_end_t": (cursor + count) / sr,
            "output_start_frame": frame(cursor / sr),
            "output_end_frame": frame((cursor + count) / sr),
        })
        cursor += count
    if not chunks:
        raise ValueError("segments 不能为空")
    if segments[0]["source_start_sample"] != 0 or segments[-1]["source_end_sample"] != len(audio):
        raise ValueError("本任务必须保留原曲开头 0 和完整结尾 EOF")
    segments[-1]["output_end_frame"] = frame_count(cursor, sr)
    mixed = np.concatenate(chunks, axis=0)
    interfaces = []
    theta = np.linspace(0, np.pi / 2, crossfade_samples, endpoint=True)[:, None]
    fade_out, fade_in = np.cos(theta), np.sin(theta)
    period = float(grid["beat_period"])
    downbeat_origin = float(grid["t0"]) + int(grid["downbeat_phase"]) * period
    for index, (left, right) in enumerate(zip(segments, segments[1:]), 1):
        source_out, source_in = left["source_end_sample"], right["source_start_sample"]
        position = right["output_start_sample"]
        if left["end_boundary"]["kind"] != "downbeat" or right["start_boundary"]["kind"] != "downbeat":
            raise ValueError("内部接口两侧必须都是小节第一拍")
        continuous = source_out == source_in
        handle = None
        outgoing_tail = None
        if not continuous:
            if source_in < crossfade_samples:
                raise ValueError("切入点前预卷素材不足")
            mixed[position-crossfade_samples:position] = (
                mixed[position-crossfade_samples:position] * fade_out
                + audio[source_in-crossfade_samples:source_in] * fade_in
            )
            handle = {
                "source_start_sample": source_in-crossfade_samples, "source_end_sample": source_in,
                "source_start_t": (source_in-crossfade_samples)/sr, "source_end_t": source_in/sr,
                "source_start_frame": frame((source_in-crossfade_samples)/sr),
                "source_end_frame": frame(source_in/sr),
                "output_start_sample": position-crossfade_samples, "output_end_sample": position,
                "output_start_t": (position-crossfade_samples)/sr, "output_end_t": position/sr,
                "output_start_frame": frame((position-crossfade_samples)/sr),
                "output_end_frame": frame(position/sr),
            }
            outgoing_tail = {
                "source_start_sample": source_out-crossfade_samples, "source_end_sample": source_out,
                "source_start_t": (source_out-crossfade_samples)/sr, "source_end_t": source_out/sr,
                "source_start_frame": frame((source_out-crossfade_samples)/sr),
                "source_end_frame": frame(source_out/sr),
                "output_start_t": (position-crossfade_samples)/sr, "output_end_t": position/sr,
                "output_start_sample": position-crossfade_samples, "output_end_sample": position,
                "output_start_frame": frame((position-crossfade_samples)/sr),
                "output_end_frame": frame(position/sr),
            }
        # For the requested edits BOF is retained, so each cut must stay on the
        # original projected grid. The signed error is only sample quantization.
        out_t = position/sr
        grid_k = round((out_t-downbeat_origin)/(4*period))
        projected_downbeat = downbeat_origin + grid_k*4*period
        out_k = left["end_boundary"]["downbeat_k"]
        in_k = right["start_boundary"]["downbeat_k"]
        interfaces.append({
            "index": index, "output_t": out_t, "output_sample": position,
            "output_frame": frame(out_t), "source_out_t": source_out/sr,
            "source_in_t": source_in/sr, "source_out_frame": frame(source_out/sr),
            "source_in_frame": frame(source_in/sr),
            "output_downbeat_error_ms": (out_t-projected_downbeat)*1000,
            "source_out_downbeat_k": out_k,
            "source_in_downbeat_k": in_k,
            "source_out_bar": out_k + 1, "source_in_bar": in_k + 1,
            "requested_source_out_t": left["end_boundary"]["requested"],
            "requested_source_in_t": right["start_boundary"]["requested"],
            "phrase_alignment": {
                "out_is_4bar_phrase_start": out_k % 4 == 0,
                "out_is_8bar_phrase_start": out_k % 8 == 0,
                "in_is_4bar_phrase_start": in_k % 4 == 0,
                "in_is_8bar_phrase_start": in_k % 8 == 0,
                "incoming_bars_to_next_4bar_start": (-in_k) % 4,
                "exception_to_phrase_preference": not continuous and (out_k % 4 != 0 or in_k % 4 != 0),
                "basis": "小节编号=k+1；k=0 为首个规则分组起点，k%4=0／k%8=0 为 4／8 小节组起点",
            },
            "crossfade_applied": not continuous,
            "crossfade_mode": "pre_cut_incoming_handle" if not continuous else "continuous_source",
            "incoming_handle": handle,
            "outgoing_tail": outgoing_tail,
            "source_metrics": splice_metrics(audio, sr, source_out, source_in, bar_samples),
        })
    peak = peak_stats(mixed)
    gain_db = min(0.0, -headroom_db - peak["sample_peak_dbfs"])
    output.parent.mkdir(parents=True, exist_ok=True)
    attempts = []
    for attempt in range(4):
        encode(mixed, sr, output, gain_db)
        decoded, decoded_sr = decode(output)
        encoded_peak = peak_stats(decoded)
        attempts.append({"attempt": attempt+1, "gain_db": gain_db,
                         "decoded_peak": encoded_peak})
        if decoded_sr != sr or decoded.shape != mixed.shape:
            raise RuntimeError(f"编码回读采样规格或时长变化：{mixed.shape}@{sr} → "
                               f"{decoded.shape}@{decoded_sr}")
        excess = encoded_peak["sample_peak_dbfs"] + headroom_db
        if excess <= 1e-4:
            break
        gain_db -= excess + 0.05
    else:
        raise RuntimeError("四次统一衰减后仍未满足编码后峰值余量")
    for item in interfaces:
        position = item["output_sample"]
        measured = splice_metrics(decoded, sr, position, position, bar_samples)
        measured["before_output_window"] = measured.pop("before_source_window")
        measured["after_output_window"] = measured.pop("after_source_window")
        item["encoded_output_metrics"] = measured
    if sha256(src) != source_hash:
        raise RuntimeError("源文件哈希发生改变")
    report = {
        "schema_version": 1,
        "fps": FPS,
        "frame_convention": "内部边界取最近帧；源 EOF 和输出最终排他终点向上取整，保留最后部分帧",
        "plan": relative(plan_path), "plan_sha256": sha256(plan_path),
        "grid_file": relative(grid_path), "grid_sha256": sha256(grid_path),
        "grid": {key: grid[key] for key in ["bpm", "t0", "beat_period", "downbeat_phase"]},
        "crossfade_ms": crossfade_ms, "crossfade_samples": crossfade_samples,
        "crossfade_duration_actual_ms": crossfade_samples/sr*1000,
        "source": {"path": relative(src), "sha256": source_hash, "sample_rate": sr,
                   "channels": audio.shape[1], "sample_count": len(audio),
                   "duration_sec": len(audio)/sr, "peak": peak_stats(audio)},
        "output": {"path": relative(output), "sha256": sha256(output), "sample_rate": sr,
                   "channels": mixed.shape[1], "sample_count": len(mixed),
                   "duration_sec": len(mixed)/sr, "video_frame_count_ceil": frame_count(len(mixed), sr),
                   "bitrate_bps": 192000, "peak": encoded_peak},
        "segments": segments, "interfaces": interfaces,
        "level_management": {"mode": "constant_global_gain_no_limiter_no_extra_fade",
                             "required_headroom_db": headroom_db,
                             "applied_gain_db": gain_db, "before_gain": peak,
                             "pcm_after_gain": peak_stats(mixed*10**(gain_db/20)),
                             "encoding_attempts": attempts},
        "source_read_only_verified": True,
        "end_tail_retained": segments[-1]["source_end_sample"] == len(audio),
        "start_retained": segments[0]["source_start_sample"] == 0,
        "versions": {"numpy": np.__version__, "librosa": librosa.__version__,
                     "soundfile": sf.__version__, "python": sys.version.split()[0]},
    }
    snapped = {
        "src": relative(src, output.parent), "grid_file": relative(grid_path, output.parent),
        "output": output.name, "crossfade_ms": crossfade_ms, "headroom_db": headroom_db,
        "segments": [{"start": s["start_boundary"]["grid_t"],
                      "end": "EOF" if s["end_boundary"]["kind"] == "EOF" else s["end_boundary"]["grid_t"],
                      "label": s["label"]} for s in segments],
        "notes": "边界吸附后方案；切点前预卷交叉淡化不改变名义时长。",
    }
    write_json(output.parent / "snapped_plan.json", snapped)
    write_json(output.parent / "splice_report.json", report)
    (output.parent / "splice_report.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"output": relative(output), "duration_sec": len(mixed)/sr,
                      "gain_db": gain_db, "encoded_peak_dbfs": encoded_peak["sample_peak_dbfs"],
                      "interfaces": len(interfaces)}, ensure_ascii=False))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    run(args.plan)


if __name__ == "__main__":
    main()
