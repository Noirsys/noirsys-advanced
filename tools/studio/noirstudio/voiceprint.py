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
`timeline` looks inside one clip, tenth of a second by tenth of a second, for the question a
machine transcript can't answer (is that a laugh, a breath, or nothing?): it shows the sound and
its bursts, and leaves the naming to whoever listens.

Nothing here judges the words. It reads the audio at 16 kHz mono: a 40 ms frame every 10 ms,
a speech gate 8 dB over the room (or 35 dB under the loudest frames, for a clean read with
digital silence), and, per frame, its level, its top end and its syllable-band energy, and its pitch,
on the loud speech frames only. Pitch is Praat's tracker (the one the resynthesis in `voicenote` uses,
so a swing that is asked for is a swing that is read the same way) when praat-parselmouth is installed,
else a numpy autocorrelation through a 60 Hz to 1 kHz band; every row says which it was, and only rows
from the same reader compare. The numpy reader is the fallback, and on real phone notes it reads about a semitone more swing than
Praat (on his 101 notes, 7% of the frames both read are numpy an octave up, where a phone's high-pass left the fundamental weak;
`--readers-apart` shows where). Octave jumps are repaired against the neighbouring frames. It needs numpy
(`pip install "noirstudio[voice]"`); nothing else in noirstudio does.

Do not high-pass before reading pitch. A 200 Hz high-pass "to take the phone filter out of the
reading" let the formants win the autocorrelation and read his swing at 6.8 semitones (Praat reads 2.1, the numpy reader 3.2)
(2026-09-29): a low voice's period is carried by the low harmonics, and the formants are what is left above them.
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
PITCH_FLOOR_HZ, PITCH_CEILING_HZ = 70.0, 300.0  # the range Praat searches: the one the resynthesis in voicenote uses
# The numpy fallback reads through 60 Hz to 1 kHz: below the first formant, so that the low harmonics decide the period
# and not a formant's ringing. On synthetic vowels with a known contour this reads the swing to within 0.1 semitone; a
# 200 Hz high-pass in front of it read 2.5 semitones too wide.
AUTOCORR_BAND = "highpass=f=60:poles=2,lowpass=f=1000:poles=2,lowpass=f=1000:poles=2"
PITCH_READERS = ("auto", "praat", "autocorr")
PITCH_KEYS = ("f0_sd_st", "f0_range_st", "f0_move_st_s")
PITCH_WINDOW_DB = 25.0  # pitch is read only on frames within this many dB of the loud ones: the quiet tails are all noise
EVENT_GAP_S = 0.30  # in a timeline, sound less than this apart is one event: a laugh is a train of bursts, not one

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


def _decode(path: Path, af: str = ""):
    np = _np()
    cmd = [ffmpeg.ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(path), "-t", f"{MAX_S:g}", "-vn",
           "-ac", "1", *(["-af", af] if af else []), "-ar", str(RATE), "-f", "s16le", "-"]
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


def _analyse(x, pitch: bool = True):
    """Per-frame level (dB), top-end share (dB), spectral centroid (Hz), syllable-band level (dB) and,
    with `pitch`, the pitch lag (samples) and its autocorrelation."""
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
        if not pitch:
            continue
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
    return {k: np.concatenate(v) for k, v in cols.items() if v}


def _repair(st):
    """Octave jumps: a frame more than 2.5 semitones from the median of its neighbours takes that median."""
    np = _np()
    fixed = st.copy()
    for i in np.flatnonzero(~np.isnan(st)):
        near = st[max(0, i - 3):i + 4]
        near = near[~np.isnan(near)]
        if len(near) >= 3:
            med = float(np.median(near))
            if abs(st[i] - med) > 2.5:
                fixed[i] = med
    return fixed


def _pitch(lag, val, on):
    """Semitones (re 100 Hz) for each voiced speech frame, else NaN; octave jumps repaired."""
    np = _np()
    st = np.full(len(lag), np.nan)
    voiced = on & (val >= VOICED)
    st[voiced] = 12 * np.log2((RATE / lag[voiced]) / 100.0)
    return _repair(st)


def _praat_pitch(x, n_frames, window):
    """Praat's autocorrelation tracker, one value per analysis frame (nearest 10 ms step), on `window` only."""
    import parselmouth

    np = _np()
    pitch = parselmouth.Sound(x.astype("float64"), sampling_frequency=RATE).to_pitch_ac(
        time_step=HOP / RATE, pitch_floor=PITCH_FLOOR_HZ, pitch_ceiling=PITCH_CEILING_HZ)
    hz, times = pitch.selected_array["frequency"], pitch.xs()
    centres = (np.arange(n_frames) * HOP + FRAME / 2) / RATE
    at = np.clip(np.round((centres - times[0]) / (HOP / RATE)).astype(int), 0, len(hz) - 1)
    f = hz[at]
    st = np.full(n_frames, np.nan)
    ok = window & (f > 0)
    st[ok] = 12 * np.log2(f[ok] / 100.0)
    return _repair(st)


def _read_pitch(path, x, a, on, reader: str = "auto", everything: bool = False):
    """Semitones (re 100 Hz) per analysis frame on the loud speech frames (every frame over the gate, with
    `everything`), else NaN; which reader made them; and why it made none, if Praat refused the clip."""
    np = _np()
    if reader not in PITCH_READERS:
        raise VoiceNoteError(f"pitch reader {reader!r}: expected one of {', '.join(PITCH_READERS)}")
    window = on if everything else on & (a["rms"] > float(np.percentile(a["rms"][on], 95)) - PITCH_WINDOW_DB)
    if reader != "autocorr":
        try:
            import parselmouth
        except ImportError as exc:
            if reader == "praat":
                raise VoiceNoteError('--pitch-reader praat needs praat-parselmouth: pip install "noirstudio[voice]"') from exc
        else:
            try:
                return _praat_pitch(x, len(on), window), "praat", ""
            except parselmouth.PraatError as exc:  # Praat refuses some clips: that one has no pitch, the batch goes on
                return np.full(len(on), np.nan), "praat", " ".join(str(exc).split())[:120]
    p = _analyse(_decode(path, AUTOCORR_BAND))
    return _pitch(p["lag"], p["val"], window), "autocorr", ""


def _peaks(band_db, on):
    """Syllable nuclei: peaks of the 300-3000 Hz level, 3 dB proud of the dip on each side. Returns the
    frame of each peak and the smoothed level they were found in."""
    np = _np()
    sm = np.convolve(band_db, np.ones(3) / 3, mode="same")
    peaks = []
    for i in range(12, len(sm) - 12):
        if on[i] and sm[i] > sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] == sm[i - 8:i + 9].max():
            if sm[i] - max(sm[i - 12:i].min(), sm[i + 1:i + 13].min()) >= 3.0:
                peaks.append(i)
    return peaks, sm


def _syllables(band_db, on, cuts) -> Tuple[int, List[float]]:
    peaks, _ = _peaks(band_db, on)
    gaps = [(peaks[k + 1] - peaks[k]) * HOP / RATE for k in range(len(peaks) - 1)
            if not any(peaks[k] < c <= peaks[k + 1] for c in cuts)]
    return len(peaks), [g for g in gaps if g <= 0.5]


def voiceprint(path: Path, words: Optional[int] = None, levels: bool = True, reader: str = "auto") -> dict:
    """The measurable habits of one voice note or read (see the top of this file)."""
    np = _np()
    path = Path(path)
    x = _decode(path)
    a = _analyse(x, pitch=False)
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
    st, method, refused = _read_pitch(path, x, a, on, reader)
    v = st[~np.isnan(st)]
    n_syll, beats = _syllables(a["mid"], on, cuts)
    out: dict = {"path": str(path), "duration_s": round(len(x) / RATE, 2), "utterance_s": round(utter_s, 2),
                 "speech_s": round(speech_s, 2), "gate_db": round(gate, 1),
                 "pause_count": len(pauses),
                 "pauses_per_min": round(60 * len(pauses) / utter_s, 1) if utter_s else 0.0,
                 "pause_median_s": round(statistics.median(pauses), 2) if pauses else None,
                 "pause_p90_s": round(float(np.percentile(pauses, 90)), 2) if pauses else None,
                 "pause_ratio": round(sum(pauses) / utter_s, 3) if utter_s else 0.0,
                 "longest_pause_s": round(max(pauses), 2) if pauses else None,
                 "level_sd_db": round(float(lvl.std()), 2),
                 "level_range_db": round(float(np.percentile(lvl, 95) - np.percentile(lvl, 5)), 2),
                 "hf_db": round(float(a["hf"][on].mean()), 2), "centroid_hz": round(float(a["cen"][on].mean())),
                 "syll_rate_hz": round(n_syll / speech_s, 2) if speech_s else 0.0,
                 "syll_cv": round(statistics.pstdev(beats) / statistics.mean(beats), 3) if len(beats) >= 8 else None,
                 "voiced_ratio": round(len(v) / max(1, int(on.sum())), 2), "pitch_reader": method}
    if refused:
        out["pitch_error"] = refused
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


def timeline(path: Path, step_s: float = 0.1, reader: str = "auto") -> dict:
    """One clip, moment by moment: every `step_s`, the peak level, the top end, the pitch and how much of the
    step is over the speech gate; and the runs of sound (events), each with its length, level, pitch and how
    many bursts it holds, how evenly spaced they are and how fast they die away.

    A laugh is a train of four to six bursts a second that fades; so is a run of syllables, and a cough is
    one burst. This shows the sound, not what it was: it is for someone who has heard the clip, or is
    about to, and for a clip whose transcript has words in it and a stretch with none.
    """
    np = _np()
    path = Path(path)
    x = _decode(path)
    a = _analyse(x, pitch=False)
    on, gate = _speech(a["rms"])
    if not on.any():
        raise VoiceNoteError(f"no sound over the gate in {path}")
    loud = float(np.percentile(a["rms"][on], 95))
    st, method, _refused = _read_pitch(path, x, a, on, reader, everything=True)  # a laugh can be 20 dB under the words
    voiced = ~np.isnan(st)
    hz = 100 * 2 ** (st / 12)  # NaN where a frame has no pitch
    peaks, smooth = _peaks(a["mid"], on)

    step = max(1, round(step_s * RATE / HOP))
    rows = []
    for i in range(0, len(on), step):
        sl = slice(i, min(len(on), i + step))
        f = hz[sl][~np.isnan(hz[sl])]
        rows.append({"t_s": round(i * HOP / RATE, 2), "level_db": round(float(a["rms"][sl].max()), 1),
                     "hf_db": round(float(a["hf"][sl][on[sl]].mean()), 1) if on[sl].any() else None,
                     "f0_hz": round(float(np.median(f)), 1) if len(f) else None,
                     "on": round(float(on[sl].mean()), 2)})

    close = int(EVENT_GAP_S * RATE / HOP)
    spans: List[List[int]] = []
    for s, e, v in _runs(on):
        if v:
            if spans and s - spans[-1][1] < close:
                spans[-1][1] = e
            else:
                spans.append([s, e])
    events = []
    for s, e in spans:
        here = on[s:e]
        lvl = a["rms"][s:e][here]
        pitch = st[s:e][~np.isnan(st[s:e])]
        hit = [k for k in peaks if s <= k < e]
        dur = (e - s) * HOP / RATE
        ev = {"start_s": round(s * HOP / RATE, 2), "end_s": round(e * HOP / RATE, 2), "dur_s": round(dur, 2),
              "peak_db": round(float(lvl.max()), 1), "mean_db": round(float(lvl.mean()), 1),
              "hf_db": round(float(a["hf"][s:e][here].mean()), 1),
              "voiced_share": round(float(voiced[s:e].sum()) / max(1, int(here.sum())), 2),
              "bursts": len(hit), "bursts_per_s": round(len(hit) / dur, 1) if dur else 0.0}
        if len(pitch) >= 5:
            ev["f0_median_hz"] = round(100 * 2 ** (float(np.median(pitch)) / 12), 1)
            ev["f0_sd_st"] = round(float(pitch.std()), 2)
        gaps = [(hit[k + 1] - hit[k]) * HOP / RATE for k in range(len(hit) - 1)]
        if len(gaps) >= 3:
            ev["burst_cv"] = round(statistics.pstdev(gaps) / statistics.mean(gaps), 2)
        if len(hit) >= 3:  # dB per second of the burst peaks, least squares: negative is a fade
            ev["decay_db_s"] = round(float(np.polyfit(np.array(hit) * HOP / RATE, smooth[hit], 1)[0]), 1)
        events.append(ev)
    return {"path": str(path), "duration_s": round(len(x) / RATE, 2), "gate_db": round(gate, 1),
            "loud_db": round(loud, 1), "step_s": step_s, "pitch_reader": method, "rows": rows, "events": events}


def timeline_text(t: dict) -> str:
    """The timeline as a table a person can read down: one line per step, with a bar for the level."""
    lines = [f"{Path(t['path']).name}: {t['duration_s']} s, gate {t['gate_db']} dB, loud {t['loud_db']} dB "
             f"(95th percentile of the sound); pitch: {t.get('pitch_reader', '?')}", "", "   t_s  level_db  hf_db  f0_hz   on"]
    floor = t["gate_db"] - 10
    for r in t["rows"]:
        bar = "#" * max(0, min(40, int(round((r["level_db"] - floor) / 2))))
        hf = "-" if r["hf_db"] is None else f"{r['hf_db']:g}"
        f0 = "-" if r["f0_hz"] is None else f"{r['f0_hz']:g}"
        lines.append(f"{r['t_s']:6.2f} {r['level_db']:9.1f} {hf:>6} {f0:>6} {r['on']:4.1f}  {bar}")
    lines += ["", f"events (sound over the gate; sound less than {EVENT_GAP_S:g} s apart is one event):",
              "  #  start_s  end_s  dur_s  peak_db  mean_db  voiced  f0_hz  f0_sd_st  hf_db  bursts  per_s  burst_cv  decay_db_s"]

    def cell(ev, key, width, fmt="{:g}"):
        return f"{'-' if ev.get(key) is None else fmt.format(ev[key]):>{width}}"

    for i, ev in enumerate(t["events"], 1):
        lines.append(f"{i:3d}  " + "  ".join([
            cell(ev, "start_s", 7), cell(ev, "end_s", 5), cell(ev, "dur_s", 5), cell(ev, "peak_db", 7),
            cell(ev, "mean_db", 7), cell(ev, "voiced_share", 6), cell(ev, "f0_median_hz", 5),
            cell(ev, "f0_sd_st", 8), cell(ev, "hf_db", 5), cell(ev, "bursts", 6), cell(ev, "bursts_per_s", 5),
            cell(ev, "burst_cv", 8), cell(ev, "decay_db_s", 10)]))
    return "\n".join(lines)


# --- where the two pitch readers part --------------------------------------------------------------

DIFF_BINS = (("lt0.5", 0.0, 0.5), ("0.5-1", 0.5, 1.0), ("1-2", 1.0, 2.0), ("2-4", 2.0, 4.0), ("4-8", 4.0, 8.0),
             ("8-11", 8.0, 11.0), ("11-13", 11.0, 13.0), ("gt13", 13.0, math.inf))  # |difference| in semitones; 11-13 is an octave


def readers_apart(path: Path) -> dict:
    """Praat's tracker and the numpy autocorrelation on one clip, frame by frame on the same frames, and where
    they part: the frames each reads that the other does not, how far apart they are where both read (in bins,
    an octave being 11-13 semitones), the swing on the frames they share, and the numpy swing on the plainly
    periodic thirds of the shared frames against the least periodic (by the numpy autocorrelation at the pitch
    lag). On a synthetic voice they agree to a tenth of a semitone; on a real note they can differ by a semitone,
    and this says whether that is frames one of them invents or drops, or a different value on the same frames."""
    np = _np()
    try:
        import parselmouth
    except ImportError as exc:
        raise VoiceNoteError('comparing the readers needs praat-parselmouth: pip install "noirstudio[voice]"') from exc
    path = Path(path)
    x = _decode(path)
    a = _analyse(x, pitch=False)
    on, _gate = _speech(a["rms"])
    if not on.any():
        raise VoiceNoteError(f"no speech in {path}")
    window = on & (a["rms"] > float(np.percentile(a["rms"][on], 95)) - PITCH_WINDOW_DB)
    try:
        st_p = _praat_pitch(x, len(on), window)
    except parselmouth.PraatError as exc:
        raise VoiceNoteError(f"Praat refused {path}: {' '.join(str(exc).split())[:100]}") from exc
    band = _analyse(_decode(path, AUTOCORR_BAND))
    st_a = _pitch(band["lag"], band["val"], window)
    has_p, has_a = ~np.isnan(st_p), ~np.isnan(st_a)
    both = has_p & has_a
    if int(both.sum()) < 10:
        raise VoiceNoteError(f"too little pitch in {path} to compare the readers")
    d = st_a[both] - st_p[both]
    ref = float(np.median(st_p[both]))
    val = band["val"][both]
    low_cut, high_cut = (float(c) for c in np.percentile(val, [100 / 3, 200 / 3]))
    top, bottom = both & (band["val"] >= high_cut), both & (band["val"] <= low_cut)  # the most and the least periodic third

    def sd(v):
        return round(float(v.std()), 2) if len(v) >= 10 else None

    def off(v):
        return round(float(np.median(np.abs(v - ref))), 2) if len(v) else None

    def hz(v):
        return round(100 * 2 ** (float(np.median(v)) / 12), 1)

    mag = np.abs(d)
    return {"path": str(path), "speech_s": round(float(on.sum()) * HOP / RATE, 2), "frames": int(window.sum()),
            "praat": int(has_p.sum()), "autocorr": int(has_a.sum()), "both": int(both.sum()),
            "only_praat": int((has_p & ~has_a).sum()), "only_autocorr": int((has_a & ~has_p).sum()),
            "f0_median_hz_praat": hz(st_p[has_p]), "f0_median_hz_autocorr": hz(st_a[has_a]),
            "f0_sd_praat": sd(st_p[has_p]), "f0_sd_autocorr": sd(st_a[has_a]),
            "f0_sd_praat_both": sd(st_p[both]), "f0_sd_autocorr_both": sd(st_a[both]),
            "f0_sd_praat_top": sd(st_p[top]), "f0_sd_autocorr_top": sd(st_a[top]),
            "f0_sd_praat_bottom": sd(st_p[bottom]), "f0_sd_autocorr_bottom": sd(st_a[bottom]),
            "periodicity_top": round(high_cut, 2), "periodicity_bottom": round(low_cut, 2),
            "bias_st": round(float(np.median(d)), 2),
            "apart": {name: int(((mag >= lo) & (mag < hi)).sum()) for name, lo, hi in DIFF_BINS},
            "high": int((d > 2).sum()), "low": int((d < -2).sum()),
            "off_both_st": off(st_p[both]), "off_only_praat_st": off(st_p[has_p & ~has_a]),
            "off_only_autocorr_st": off(st_a[has_a & ~has_p])}


def readers_apart_summary(rows: Sequence[dict]) -> dict:
    """The clips together: frames pooled, the medians of the per-clip numbers."""
    np = _np()

    def total(key):
        return sum(r[key] for r in rows)

    def median(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(float(np.median(vals)), 2) if vals else None

    both = max(1, total("both"))
    return {"n": len(rows), "frames": total("frames"), "praat": total("praat"), "autocorr": total("autocorr"),
            "both": total("both"), "only_praat": total("only_praat"), "only_autocorr": total("only_autocorr"),
            "apart_share": {name: round(sum(r["apart"][name] for r in rows) / both, 3) for name, _lo, _hi in DIFF_BINS},
            "high_share": round(total("high") / both, 3), "low_share": round(total("low") / both, 3),
            "median": {k: median(k) for k in (
                "f0_sd_praat", "f0_sd_autocorr", "f0_sd_praat_both", "f0_sd_autocorr_both", "f0_sd_praat_top",
                "f0_sd_autocorr_top", "f0_sd_praat_bottom", "f0_sd_autocorr_bottom", "periodicity_top",
                "periodicity_bottom", "bias_st", "f0_median_hz_praat", "f0_median_hz_autocorr",
                "off_both_st", "off_only_praat_st", "off_only_autocorr_st")}}


def readers_apart_text(rows: Sequence[dict], summary: dict) -> str:
    """One line per clip, then the clips together. `sd` is the pitch swing (standard deviation, semitones)."""
    def cell(v, width, fmt="{:g}"):
        return f"{'-' if v is None else fmt.format(v):>{width}}"

    lines = ["pitch swing (sd, st) by Praat and by numpy autocorrelation, on their own frames and on the frames both read, and on "
             "the most and the least periodic third of those (by the numpy autocorrelation at the pitch lag);",
             "frames only one of them reads (% of the frames either reads); how far apart they are where both read; "
             "high/low = numpy more than 2 st above/below Praat; bias = numpy minus Praat, median.", "",
             "file                        speech_s | sd_praat sd_numpy | both: praat numpy | top third: praat numpy | "
             "bottom third: praat numpy | only_p% only_n% | <1st% 1-2% 2-4% >4% oct% | high% low% | bias"]
    for r in rows:
        either = max(1, r["praat"] + r["only_autocorr"])
        apart = r["apart"]
        n = max(1, r["both"])
        lt1 = apart["lt0.5"] + apart["0.5-1"]
        far = apart["4-8"] + apart["8-11"] + apart["gt13"] + apart["11-13"]
        lines.append(
            f"{Path(r['path']).name[:26]:<26} {r['speech_s']:9.2f} | {cell(r['f0_sd_praat'], 8)} {cell(r['f0_sd_autocorr'], 8)} | "
            f"{cell(r['f0_sd_praat_both'], 14)} {cell(r['f0_sd_autocorr_both'], 5)} | "
            f"{cell(r['f0_sd_praat_top'], 20)} {cell(r['f0_sd_autocorr_top'], 5)} | "
            f"{cell(r['f0_sd_praat_bottom'], 23)} {cell(r['f0_sd_autocorr_bottom'], 5)} | "
            f"{100 * r['only_praat'] / either:7.0f} {100 * r['only_autocorr'] / either:7.0f} | "
            f"{100 * lt1 / n:5.0f} {100 * apart['1-2'] / n:4.0f} {100 * apart['2-4'] / n:4.0f} {100 * far / n:3.0f} "
            f"{100 * apart['11-13'] / n:4.0f} | {100 * r['high'] / n:5.0f} {100 * r['low'] / n:4.0f} | {r['bias_st']:+.2f}")
    m, ap = summary["median"], summary["apart_share"]
    either = max(1, summary["praat"] + summary["only_autocorr"])
    lines += ["", f"{summary['n']} clips, {summary['frames']} frames in the pitch window; Praat reads {summary['praat']}, numpy "
              f"{summary['autocorr']}, both {summary['both']}; only Praat {summary['only_praat']} "
              f"({100 * summary['only_praat'] / either:.0f}%), only numpy {summary['only_autocorr']} "
              f"({100 * summary['only_autocorr'] / either:.0f}%).",
              "where both read, |numpy - Praat| in semitones (share of those frames): "
              + ", ".join(f"{name} {100 * ap[name]:.1f}%" for name, _lo, _hi in DIFF_BINS)
              + f"; numpy more than 2 st above Praat {100 * summary['high_share']:.1f}%, more than 2 st below {100 * summary['low_share']:.1f}%.",
              "medians over clips: swing " + ", ".join(f"{k.replace('f0_sd_', '')} {m[k]}" for k in (
                  "f0_sd_praat", "f0_sd_autocorr", "f0_sd_praat_both", "f0_sd_autocorr_both", "f0_sd_praat_top",
                  "f0_sd_autocorr_top", "f0_sd_praat_bottom", "f0_sd_autocorr_bottom") if m.get(k) is not None)
              + f"; periodicity cut-offs (autocorrelation at the pitch lag) top {m['periodicity_top']}, bottom "
              f"{m['periodicity_bottom']}; bias {m['bias_st']} st; median f0 Praat {m['f0_median_hz_praat']} Hz, "
              f"numpy {m['f0_median_hz_autocorr']} Hz.",
              f"how far from the shared median the frames only one reads sit (median |st|): both {m['off_both_st']}, "
              f"only Praat {m['off_only_praat_st']}, only numpy {m['off_only_autocorr_st']}."]
    return "\n".join(lines)


def summarize(rows: Sequence[dict], min_speech_s: float = 2.0, max_speech_s: Optional[float] = None) -> dict:
    """Median and quartiles of every metric over the files with enough speech to read.

    A long dictation stops to think more than a short line does, so `max_speech_s` keeps a set of his
    notes comparable with a set of short reads.
    """
    keep = [r for r in rows if r.get("speech_s", 0) >= min_speech_s
            and (max_speech_s is None or r.get("speech_s", 0) <= max_speech_s)]
    out: dict = {"n": len(keep), "skipped": len(rows) - len(keep),
                 "speech_min": round(sum(r["speech_s"] for r in keep) / 60, 1),
                 "readers": sorted({r["pitch_reader"] for r in keep if r.get("pitch_reader")})}
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
    mixed = len(set(his.get("readers") or []) | set(ours.get("readers") or [])) > 1
    for key, sign in DIRECTION.items():
        a, b = his.get(key), ours.get(key)
        if not a or not b:
            continue
        if mixed and key in PITCH_KEYS:  # two different pitch readers do not measure the same thing
            rows.append({"metric": key, "group": GROUP[key], "his": a["median"], "his_q1": a["q1"], "his_q3": a["q3"],
                         "ours": b["median"], "ratio": None, "verdict": "different readers"})
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
