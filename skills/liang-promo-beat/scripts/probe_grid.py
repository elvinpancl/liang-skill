#!/usr/bin/env python3
"""Auxiliary high-resolution beat-grid probe; primary frame CSV stays at 30 fps.

All thresholds are fixed before fitting; no residual-based anchor deletion occurs.
analyze_frames.py 会 import 这里的 analyze_grid；也能单独运行：python probe_grid.py <音频> -o probe_grid.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import find_peaks


def _ls(indices, times):
    indices = np.asarray(indices, dtype=float)
    times = np.asarray(times, dtype=float)
    T, t0 = np.linalg.lstsq(np.column_stack([indices, np.ones(len(indices))]), times, rcond=None)[0]
    residual = times - (t0 + T * indices)
    return float(T), float(t0), residual


def _match(times, t0, T, duration, window=0.055):
    # One independently detected local maximum per predicted beat, chosen by
    # nearest distance. A fixed 55 ms search window is not a 15 ms acceptance gate.
    count = int(np.floor((duration - t0) / T)) + 1
    indices, matched, missing = [], [], []
    for k in range(max(0, count)):
        pred = t0 + k * T
        lo, hi = np.searchsorted(times, [pred - window, pred + window])
        if hi > lo:
            j = lo + int(np.argmin(np.abs(times[lo:hi] - pred)))
            indices.append(k)
            matched.append(float(times[j]))
        else:
            missing.append(k)
    return np.asarray(indices), np.asarray(matched), missing, count


def _refine(times, t0, T, duration):
    for _ in range(3):
        ids, ts, missing, count = _match(times, t0, T, duration)
        if len(ids) < 8:
            return None
        T, t0, _ = _ls(ids, ts)
    # Keep the earliest nonnegative grid beat as index 0.
    shift = int(np.floor(t0 / T))
    t0 -= shift * T
    ids, ts, missing, count = _match(times, t0, T, duration)
    T, t0, res = _ls(ids, ts)
    return T, t0, ids, ts, missing, count, res


def _metrics(refined, low_times, low_strength, duration):
    T, t0, ids, ts, missing, count, res = refined
    kick_ids = np.rint((low_times - t0) / T).astype(int)
    kick_res = low_times - (t0 + kick_ids * T)
    # Low-frequency flux has later attack maxima than broadband flux. 35 ms
    # tolerance is predeclared and applies equally to all tempo candidates.
    good = (np.abs(kick_res) <= 0.035) & (kick_ids >= 0) & (kick_ids < count)
    recall = float(np.mean(good)) if len(good) else 0.0
    precision = float(len(np.unique(kick_ids[good])) / max(count, 1))
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    match = len(ids) / max(count, 1)
    slope = float(np.polyfit(ts, res, 1)[0]) if len(ts) > 1 else 0.0
    half = ts < duration / 2
    holdout = None
    if np.sum(half) >= 8 and np.sum(~half) >= 8:
        train_T, train_t0, _ = _ls(ids[half], ts[half])
        test_res = ts[~half] - (train_t0 + train_T * ids[~half])
        holdout = {
            "first_half_fit_bpm": 60 / train_T,
            "second_half_mean_signed_ms": float(np.mean(test_res) * 1000),
            "second_half_max_abs_ms": float(np.max(np.abs(test_res)) * 1000),
            "period_difference_full_duration_ms": float((train_T - T) * duration / T * 1000),
        }
    return {
        "bpm": 60 / T, "t0": t0, "beat_period": T,
        "grid_beats": count, "visible_matched_beats": len(ids),
        "beats_without_qualifying_transient": len(missing),
        "unmatched_grid_beats": len(missing),
        "anchors_removed_by_residual_threshold": 0,
        "match": match,
        "mean_abs_ms": float(np.mean(np.abs(res)) * 1000),
        "residual_ms_max": float(np.max(np.abs(res)) * 1000),
        "drift_ms_per_second": slope * 1000,
        "drift_total_ms": slope * duration * 1000,
        "drift_note": "全曲最小二乘后残差斜率接近零属拟合性质；另列前半训练、后半验证指标。",
        "holdout": holdout,
        "strong_low_onsets": len(low_times),
        "kick_integer_recall": recall,
        "kick_weighted_integer_recall": float(np.sum(low_strength[good]) / max(np.sum(low_strength), 1e-12)),
        "kick_grid_coverage": precision,
        "kick_f1": f1,
        "selection_score": f1 * match,
        "missing_beat_indices": [int(k) for k in missing],
    }


def analyze_grid(y, sr):
    """Return {'grid': dict, 'diagnostics': dict}; no file writes or downloads."""
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 2:
        y = y.mean(axis=1)
    duration = len(y) / sr
    primary_hop = round(sr / 30)
    tempo, tracked = librosa.beat.beat_track(
        y=y, sr=sr, hop_length=primary_hop, tightness=400, units="time"
    )
    if len(tracked) < 8:
        raise ValueError("Too few tracked beats for a reliable grid")
    raw_T, raw_t0, raw_res = _ls(np.arange(len(tracked)), tracked)

    # This deliberately supplements, never replaces, the requested hop=1470 CSV.
    aux_hop, n_fft = 128, 1024
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=aux_hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    flux = np.diff(S[freqs >= 20], axis=1, prepend=S[freqs >= 20, :1])
    np.maximum(flux, 0, out=flux)
    full = flux.sum(axis=0)
    del flux
    full /= max(float(full.max()), 1e-12)
    low_mask = (freqs >= 20) & (freqs < 200)
    flux = np.diff(S[low_mask], axis=1, prepend=S[low_mask, :1])
    np.maximum(flux, 0, out=flux)
    low = flux.sum(axis=0)
    low /= max(float(low.max()), 1e-12)
    low_energy = np.square(S[low_mask]).sum(axis=0)
    del S, flux
    dt = aux_hop / sr
    pp, _ = find_peaks(full, height=0.08, prominence=0.03, distance=max(1, round(0.02 / dt)))
    ll, _ = find_peaks(low, height=0.50, prominence=0.20, distance=max(1, round(0.09 / dt)))
    peak_times = pp * dt
    low_times, low_strength = ll * dt, low[ll]

    # First resolve a possibly half-speed tracker output.
    initial = []
    for mult in [0.5, 1.0, 2.0]:
        T = raw_T / mult
        if not 35 <= 60 / T <= 300:
            continue
        origins = [raw_t0 % T]
        if mult == 0.5:
            origins.append((raw_t0 + raw_T) % T)
        for origin in origins:
            fitted = _refine(peak_times, origin, T, duration)
            if fitted:
                initial.append((_metrics(fitted, low_times, low_strength, duration), fitted))
    winner = max(initial, key=lambda item: item[0]["selection_score"])
    win_T, win_t0 = winner[1][:2]

    # Required 0.5x / 1x / 2x comparison is relative to the selected metre, so it
    # remains meaningful even when the raw tracker itself chooses half speed.
    candidates = []
    for mult in [0.5, 1.0, 2.0]:
        T = win_T / mult
        origins = [win_t0 % T]
        if mult == 0.5:
            origins.append((win_t0 + win_T) % T)
        fitted_options = []
        for origin in origins:
            fitted = _refine(peak_times, origin, T, duration)
            if fitted:
                metrics = _metrics(fitted, low_times, low_strength, duration)
                fitted_options.append((metrics, fitted))
        best = max(fitted_options, key=lambda item: item[0]["selection_score"])
        best[0]["factor"] = mult
        candidates.append(best)
    selected = max(candidates, key=lambda item: item[0]["selection_score"])
    metrics, fitted = selected
    T, t0, ids, ts, missing, count, res = fitted

    # The task's downbeat definition: among four beat phases, choose the largest
    # mean low-frequency energy over the first 90 ms of each beat.
    phase_energy = []
    for phase in range(4):
        values = []
        for beat in range(phase, count, 4):
            a = max(0, round((t0 + beat * T) / dt))
            b = min(len(low_energy), round((t0 + beat * T + 0.09) / dt))
            if b > a:
                values.append(float(low_energy[a:b].mean()))
        phase_energy.append(float(np.mean(values)) if values else 0.0)
    phase = int(np.argmax(phase_energy))
    basis = (
        "30 fps beat_track 先作最小二乘初值；辅助 FFT1024/hop128 正向频谱通量定位"
        "独立瞬态，固定 ±55 ms 窗逐拍取最近峰，再作等距最小二乘。"
        "不按残差阈值删除锚点。候选速度按强低频整数拍召回率与网格覆盖率的 F1"
        "乘宽频主拍命中率选择；4/4 下拍取各相位拍后 90 ms 的平均低频能量最大者。"
    )
    grid = {
        "bpm": 60 / T, "t0": t0, "beat_period": T,
        "residual_ms_max": metrics["residual_ms_max"],
        "residual_ms_mean_abs": metrics["mean_abs_ms"],
        "downbeat_phase": phase, "beats_per_bar": 4,
        "downbeat_phase_energy": phase_energy,
        "basis": basis,
        "phase_definition": "居中 FFT 窗的宽频正向频谱通量峰时刻；不是波形峰值。首拍原始攻击前沿约 24–27 ms，可与该相位核对。",
        "auxiliary_hop": aux_hop, "auxiliary_resolution_ms": dt * 1000,
        "primary_frame_hop": primary_hop,
        "grid_beats": count, "visible_matched_beats": len(ids),
        "beats_without_qualifying_transient": len(missing),
        "segments": [{"start_t": 0.0, "end_t": duration, "bpm": 60 / T,
                      "t0": t0, "beat_period": T,
                      "residual_ms_max": metrics["residual_ms_max"],
                      "anchor_count": len(ids)}],
    }
    diagnostics = {
        "duration_sec": duration,
        "raw_tracker_30fps": {
            "tempo_scalar": float(np.atleast_1d(tempo)[0]),
            "bpm_lstsq": 60 / raw_T, "beat_period": raw_T, "t0": raw_t0,
            "beat_count": len(tracked), "hop": primary_hop,
            "residual_ms_max": float(np.max(np.abs(raw_res)) * 1000),
            "residual_ms_mean_abs": float(np.mean(np.abs(raw_res)) * 1000),
            "beat_times_sec": tracked.tolist(),
        },
        "auxiliary_detector": {
            "sample_rate": int(sr), "n_fft": n_fft, "hop": aux_hop,
            "broadband": "20 Hz 至 Nyquist；逐频点正差分求和，再全曲最大值归一",
            "broadband_peak_height": 0.08, "broadband_peak_prominence": 0.03,
            "broadband_peak_distance_ms": 20,
            "all_detected_broadband_peaks": len(pp),
            "anchor_search_window_ms": 55,
            "anchor_selection": "预测拍 ±55 ms 内最近的独立峰，每拍最多一个；迭代三次；不以 15 ms 裁除。",
            "strong_low_band_hz": [20, 200], "strong_low_height": 0.5,
            "strong_low_prominence": 0.2, "strong_low_distance_ms": 90,
            "strong_low_integer_tolerance_ms": 35,
        },
        "tempo_candidates": [c[0] for c in candidates],
        "selected": metrics,
        "global_match_note": "全局主拍命中率包含休止、拖尾与稀疏段；未命中不自动等于变速，也不隐去。未达到参考的 98% 全局密集鼓点门槛。",
        "tempo_change_evidence": "保留全部固定窗内主拍锚点后残差可直接评估；仅当其超标且存在持续速度差才应分段，不能用随意分段掩盖检测量化。",
        "anchors": [{"beat_index": int(k), "observed_t": float(t),
                     "grid_t": float(t0 + k * T), "residual_ms": float(r * 1000)}
                    for k, t, r in zip(ids, ts, res)],
    }
    return {"grid": grid, "diagnostics": diagnostics}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("-o", "--output", default="probe_grid.json")
    args = ap.parse_args()
    y, sr = sf.read(args.audio, dtype="float32")
    result = analyze_grid(y, sr)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["grid"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
