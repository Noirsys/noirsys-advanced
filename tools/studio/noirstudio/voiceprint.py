"""How close a read is to him: the habits that make a voice sound like a person at home.

His note (2026-09-29): the clone "still sounds too perfect, dynamic and articulate". Those
three complaints are measurable, so this measures them on his real notes and on our reads
and sets the two side by side, in numbers, before anyone has to trust their ears:

    dynamic      how far the pitch and the loudness swing
                 (f0_sd_st, f0_range_st, f0_move_st_s, level_sd_db, level_range_db)
    articulate   how crisp the top end is, and how even the syllables run
                 (hf_db, centroid_hz, syll_cv)
    perfect      how few and how short the pauses are
                 (pauses_per_min, pause_median_s, pause_ratio, longest_pause_s)

`voiceprint` reads one file; `summarize` takes the median and spread over a set of them;
`compare` puts his notes next to ours and says which numbers are off, and which way.

Nothing here judges the words. It reads the audio at 16 kHz mono: a 40 ms frame every 10 ms,
a speech gate 8 dB over the room (or 35 dB under the loudest frames, for a clean read with
digital silence), and, per frame, its level, its top end, its pitch (autocorrelation, octave
jumps repaired against the neighbouring frames) and its syllable-band energy. It needs numpy
(`pip install "noirstudio[voice]"`); nothing else in noirstudio does.
"""

from __future__ import annotations

import math
import statistics
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import ffmpeg
from .voicenote import VoiceNoteError, measure

RATE = 16000
FRAME = 640  # 40 ms
HOP = 160  # 10 ms
MAX_S = 180.0  # a long dictation is measured on its first three minutes
MIN_PAUSE_S = 0.20  # a shorter gap is a breath or a consonant, not a pause
VOICED = 0.45  # normalised autocorrelation at the pitch lag, above which a frame counts as voiced
_BLOCK = 4096  # frames per numpy block

# For each metric: +1 if a bigger number sounds more performed, -1 if a smaller one does.
DIRECTION: Dict[str, int] = {
    "f0_sd_st": 1, "f0_range_st": 1, "f0_move_st_s": 1, "level_sd_db": 1, "level_range_db": 1,
    "hf_db": 1, "centroid_hz": 1, "syll_cv": -1,
    "pauses_per_min": -1, "pause_median_s": -1, "pause_ratio": -1, "longest_pause_s": -1,
}
GROUP: Dict[str, str] = {
    "f0_sd_st": "dynamic", "f0_range_st": "dynamic", "f0_move_st_s": "dynamic",
    "level_sd_db": "dynamic", "level_range_db": "dynamic",
    "hf_db": "articulate", "centroid_hz": "articulate", "syll_cv": "articulate",
    "pauses_per_min": "perfect", "pause_median_s": "perfect", "pause_ratio": "perfect",
    "longest_pause_s": "perfect",
}
NUMERIC = ("speech_s", "utterance_s", "lufs", "noise_db", "wpm_speech", "wpm_total", "syll_rate_hz",
           "voiced_ratio", "f0_median_hz", *DIRECTION)


def _np():
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise VoiceNoteError('voiceprint needs numpy: pip install "noirstudio[voice]"') from exc
    return numpy


def _decode(path: Path):
    np = _np()
    cmd = [ffmpeg.ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(path), "-t", f"{MAX_S:g}", "-vn",
           "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or len(proc.stdout) < 4 * FRAME:
        raise VoiceNoteError(f"cannot read speech from {path}")
    return np.frombuffer(proc.stdout, dtype="<i2").astype("float32") / 32768.0


def _runs(mask) -> List[Tuple[int, int, bool]]:
    """Run-length encode a boolean array as (start, end, value)."""
    out: List[Tuple[int, int, bool]] = []
    start = 0
    for i in range(1, len(mask) + 1):
        if i == len(mask) or bool(mask[i]) != bool(mask[start]):
            out.append((start, i, bool(mask[start])))
            start = i
    return out


def _speech(rms):
    """Which frames are speech: over the gate, gaps under 50 ms closed, blips under 60 ms dropped."""
    np = _np()
    gate = max(float(np.percentile(rms, 10)) + 8.0, float(np.percentile(rms, 95)) - 35.0)
    on = rms > gate
    for a, b, v in _runs(on):
        if not v and a > 0 and b < len(on) and b - a < 5:
            on[a:b] = True
    for a, b, v in _runs(on):
        if v and b - a < 6:
            on[a:b] = False
    return on, gate


def _analyse(x):
    """Per-frame level (dB), top-end share (dB), spectral centroid (Hz), syllable-band level (dB),
    pitch lag (samples) and its autocorrelation."""
    np = _np()
    n = 1 + (len(x) - FRAME) // HOP
    win = np.hanning(FRAME).astype("float32")
    freqs = np.fft.rfftfreq(1024, 1 / RATE)
    band, top, mid = (freqs >= 100) & (freqs <= 8000), (freqs >= 4000) & (freqs <= 8000), (freqs >= 300) & (freqs <= 3000)
    lo, hi = RATE // 350, RATE // 60
    cols: Dict[str, list] = {k: [] for k in ("rms", "hf", "cen", "mid", "lag", "val")}
    for s in range(0, n, _BLOCK):
        e = min(n, s + _BLOCK)
        fr = x[np.arange(FRAME)[None, :] + HOP * np.arange(s, e)[:, None]] * win
        cols["rms"].append(20 * np.log10(np.sqrt((fr ** 2).mean(axis=1) / 0.375) + 1e-5))  # 0.375 = mean of hann^2
        power = np.abs(np.fft.rfft(fr, 1024, axis=1)) ** 2
        total = power[:, band].sum(axis=1) + 1e-12
        cols["hf"].append(10 * np.log10(power[:, top].sum(axis=1) / total + 1e-9))
        cols["cen"].append((power[:, band] * freqs[band]).sum(axis=1) / total)
        cols["mid"].append(10 * np.log10(power[:, mid].sum(axis=1) + 1e-12))
        ac = np.fft.irfft(np.abs(np.fft.rfft(fr, 2 * FRAME, axis=1)) ** 2, axis=1)[:, :FRAME]
        seg = ac[:, lo:hi + 1] / (ac[:, :1] + 1e-12)
        rows = np.arange(len(seg))
        first = (seg >= 0.85 * seg.max(axis=1, keepdims=True)).argmax(axis=1)  # the shortest lag near the top
        near = np.stack([seg[rows, np.minimum(first + k, seg.shape[1] - 1)] for k in range(12)], axis=1)
        idx = np.clip(first + near.argmax(axis=1), 1, seg.shape[1] - 2)
        y0, y1, y2 = seg[rows, idx - 1], seg[rows, idx], seg[rows, idx + 1]
        den = y0 - 2 * y1 + y2
        delta = np.where(np.abs(den) > 1e-9, 0.5 * (y0 - y2) / np.where(np.abs(den) > 1e-9, den, 1.0), 0.0)
        cols["lag"].append(lo + idx + np.clip(delta, -1, 1))
        cols["val"].append(y1)
    return {k: np.concatenate(v) for k, v in cols.items()}


def _pitch(lag, val, on):
    """Semitones (re 100 Hz) for each voiced speech frame, else NaN; octave jumps repaired."""
    np = _np()
    st = np.full(len(lag), np.nan)
    voiced = on & (val >= VOICED)
    st[voiced] = 12 * np.log2((RATE / lag[voiced]) / 100.0)
    fixed = st.copy()
    for i in np.flatnonzero(voiced):
        near = st[max(0, i - 3):i + 4]
        near = near[~np.isnan(near)]
        if len(near) >= 3:
            med = float(np.median(near))
            if abs(st[i] - med) > 2.5:
                fixed[i] = med
    return fixed


def _syllables(band_db, on, cuts) -> Tuple[int, List[float]]:
    """Syllable nuclei: peaks of the 300-3000 Hz level, 3 dB proud of the dip on each side."""
    np = _np()
    sm = np.convolve(band_db, np.ones(3) / 3, mode="same")
    peaks = []
    for i in range(12, len(sm) - 12):
        if on[i] and sm[i] > sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] == sm[i - 8:i + 9].max():
            if sm[i] - max(sm[i - 12:i].min(), sm[i + 1:i + 13].min()) >= 3.0:
                peaks.append(i)
    gaps = [(peaks[k + 1] - peaks[k]) * HOP / RATE for k in range(len(peaks) - 1)
            if not any(peaks[k] < c <= peaks[k + 1] for c in cuts)]
    return len(peaks), [g for g in gaps if g <= 0.5]


def voiceprint(path: Path, words: Optional[int] = None, levels: bool = True) -> dict:
    """The measurable habits of one voice note or read (see the top of this file)."""
    np = _np()
    path = Path(path)
    x = _decode(path)
    a = _analyse(x)
    on, gate = _speech(a["rms"])
    runs = [(s, e) for s, e, v in _runs(on) if v]
    if not runs:
        raise VoiceNoteError(f"no speech in {path}")
    speech_s = sum(e - s for s, e in runs) * HOP / RATE
    utter_s = (runs[-1][1] - runs[0][0]) * HOP / RATE
    gaps = [(runs[k + 1][0] - runs[k][1]) * HOP / RATE for k in range(len(runs) - 1)]
    pauses = [g for g in gaps if g >= MIN_PAUSE_S]
    cuts = [runs[k][1] for k in range(len(runs) - 1) if gaps[k] >= MIN_PAUSE_S]
    lvl = a["rms"][on]
    st = _pitch(a["lag"], a["val"], on)
    v = st[~np.isnan(st)]
    n_syll, beats = _syllables(a["mid"], on, cuts)
    out: dict = {"path": str(path), "duration_s": round(len(x) / RATE, 2), "utterance_s": round(utter_s, 2),
                 "speech_s": round(speech_s, 2), "gate_db": round(gate, 1),
                 "pause_count": len(pauses),
                 "pauses_per_min": round(60 * len(pauses) / utter_s, 1) if utter_s else 0.0,
                 "pause_median_s": round(statistics.median(pauses), 2) if pauses else 0.0,
                 "pause_p90_s": round(float(np.percentile(pauses, 90)), 2) if pauses else 0.0,
                 "pause_ratio": round(sum(pauses) / utter_s, 3) if utter_s else 0.0,
                 "longest_pause_s": round(max(pauses), 2) if pauses else 0.0,
                 "level_sd_db": round(float(lvl.std()), 2),
                 "level_range_db": round(float(np.percentile(lvl, 95) - np.percentile(lvl, 5)), 2),
                 "hf_db": round(float(a["hf"][on].mean()), 2), "centroid_hz": round(float(a["cen"][on].mean())),
                 "syll_rate_hz": round(n_syll / speech_s, 2) if speech_s else 0.0,
                 "syll_cv": round(statistics.pstdev(beats) / statistics.mean(beats), 3) if len(beats) >= 8 else None,
                 "voiced_ratio": round(len(v) / max(1, int(on.sum())), 2)}
    if len(v) >= 10:
        both = ~np.isnan(st[:-1]) & ~np.isnan(st[1:])
        out.update(f0_median_hz=round(100 * 2 ** (float(np.median(v)) / 12), 1), f0_sd_st=round(float(v.std()), 2),
                   f0_range_st=round(float(np.percentile(v, 95) - np.percentile(v, 5)), 2),
                   f0_move_st_s=round(float(np.median(np.abs(np.diff(st)[both]))) * 100, 1) if both.any() else None)
    if words:
        out.update(words=int(words), wpm_speech=round(60 * words / speech_s, 1), wpm_total=round(60 * words / utter_s, 1))
    if levels:
        m = measure(path)
        out.update(lufs=m["lufs"], noise_db=m["noise_db"])
    return out


def summarize(rows: Sequence[dict], min_speech_s: float = 2.0) -> dict:
    """Median and quartiles of every metric over the files with enough speech to read."""
    keep = [r for r in rows if r.get("speech_s", 0) >= min_speech_s]
    out: dict = {"n": len(keep), "skipped": len(rows) - len(keep),
                 "speech_min": round(sum(r["speech_s"] for r in keep) / 60, 1)}
    for key in NUMERIC:
        vals = [r[key] for r in keep if r.get(key) is not None]
        if not vals:
            continue
        q = statistics.quantiles(vals, n=4) if len(vals) >= 2 else [vals[0]] * 3
        out[key] = {"median": round(statistics.median(vals), 2), "q1": round(q[0], 2), "q3": round(q[2], 2), "n": len(vals)}
    return out


def compare(his: dict, ours: dict, tol: float = 0.20) -> List[dict]:
    """His summary against ours: which numbers are off, and on which side.

    "close" is inside his middle half, or within `tol` of his median. Past that, "too performed"
    is ours on the performed side of his (more swing, cleaner top end, fewer pauses...), and
    "past him" is ours beyond him the other way: too flat, too muddy, too many pauses.
    """
    rows = []
    for key, sign in DIRECTION.items():
        a, b = his.get(key), ours.get(key)
        if not a or not b:
            continue
        gap = (b["median"] - a["median"]) / abs(a["median"]) if a["median"] else 0.0
        inside = a["q1"] <= b["median"] <= a["q3"]
        verdict = "close" if inside or abs(gap) <= tol else ("too performed" if gap * sign > 0 else "past him")
        rows.append({"metric": key, "group": GROUP[key], "his": a["median"], "his_q1": a["q1"], "his_q3": a["q3"],
                     "ours": b["median"], "ratio": round(b["median"] / a["median"], 2) if a["median"] else None,
                     "verdict": verdict})
    return rows


def table(rows: Sequence[dict]) -> str:
    """The comparison as text."""
    lines = [f"{'metric':<17}{'group':<12}{'his median (middle half)':<28}{'ours':<10}{'ours/his':<10}verdict"]
    for r in rows:
        his = f"{r['his']:g}  ({r['his_q1']:g} to {r['his_q3']:g})"
        ratio = f"{r['ratio']:g}x" if r["ratio"] is not None else "-"
        lines.append(f"{r['metric']:<17}{r['group']:<12}{his:<28}{r['ours']:<10g}{ratio:<10}{r['verdict']}")
    return "\n".join(lines)
