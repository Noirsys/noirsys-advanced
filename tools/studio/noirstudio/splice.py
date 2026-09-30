"""A stretch of one of his real notes swapped for a rebuilt read: `noirstudio splice`.

His recording is what happened, and sometimes it is missing a few words: the phone started recording late, and the note opens
mid-sentence ("I mean to say fuck you", when what he said was "I didn't mean to say fuck you"). The words are his, so the
fix is to take the wrong stretch out of the real note and put a read of what he said in its place (his clone, made to sound
like this very note: `voicenote --match NOTE`), and to leave every other sample of the real note alone.

    noirstudio splice NOTE.ogg READ.ogg OUT.wav --replace 1.00-2.60

The cuts are made in the quietest 5 ms within `search_s` of the times given, and a cut that would land in his speech is refused
(the note has to be 18 dB under its loud parts there, the limit `voicenote --pauses reflow` puts on a pause: a cut into the end of
a word was "cutting off some of my words"). The read is trimmed to its words, brought to the level of the note's own speech, and
stripped of the room it was made in, laid over a bed of the note's own floor, the floor on the left of the stretch fading into the floor on the right of it, so a note
the phone gated to near silence stays that way and a note with a room keeps its room: no seam drops the floor. Both joins are
short equal-power crossfades. `splice` reports what it did in numbers (the cuts, the gain, the floor either side of each seam,
how much later everything after the stretch now is), because nobody can hear the seams from here.

Write the result as WAV for an episode (it is decoded and trimmed anyway, and a second Opus generation only costs quality); an
`.ogg` output is Opus at his notes' 24 kbps, for sending someone a note that sounds like a phone note.
"""

from __future__ import annotations

import math
import tempfile
import wave
from pathlib import Path
from typing import Optional, Tuple

from . import ffmpeg
from .voicenote import GATED_DB, NOTE_EXTS, REAL_QUIET_BELOW_SPEECH_DB, VoiceNoteError

RATE = 48000
FRAME_S = 0.02  # a frame of speech level, as `voicenote` counts it
CUT_S = 0.005  # the window a cut is made in
BED_S = 0.4  # how much of the note's floor is copied into the bed, at most
SPEECH_BELOW_DB = 30.0  # the read's words begin and end where it is within this of its own loud parts


def _np():
    try:
        import numpy as np
    except ImportError:
        raise VoiceNoteError("splice needs numpy: pip install 'noirstudio[voice]'") from None
    return np


def load(path: Path):
    """A note (or read) as mono float32 at 48 kHz, whatever it was."""
    np = _np()
    path = Path(path)
    if not path.exists():
        raise VoiceNoteError(f"no such file: {path}")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "in.wav"
        ffmpeg.run(["-y", "-i", str(path), "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
        with wave.open(str(wav), "rb") as w:
            data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return data.astype("float32") / 32768.0


def save(x, path: Path, kbps: int = 24) -> None:
    """WAV (16-bit, 48 kHz, mono) or, for .ogg/.opus, the Opus note format his own notes have."""
    np = _np()
    path = Path(path)
    pcm = np.clip(np.round(x * 32768.0), -32768, 32767).astype("<i2")

    def write_wav(target: Path) -> None:
        with wave.open(str(target), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm.tobytes())

    if path.suffix.lower() in NOTE_EXTS:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "out.wav"
            write_wav(wav)
            ffmpeg.run(["-y", "-i", str(wav), "-c:a", "libopus", "-b:a", f"{kbps}k", "-application", "voip", "-ar",
                        str(RATE), "-ac", "1", str(path)])
    else:
        write_wav(path)


def _db(np, x) -> float:
    return float(10 * np.log10(float((x.astype("float64") ** 2).mean()) + 1e-18)) if len(x) else -180.0


def _frames_db(np, x, n: int):
    m = len(x) // n
    if m == 0:
        return np.array([_db(np, x)])
    f = x[: m * n].reshape(m, n).astype("float64")
    return 10 * np.log10((f ** 2).mean(axis=1) + 1e-18)


def _speech_db(np, x) -> float:
    """How loud his loud parts are: the 95th percentile of the 20 ms levels (`voicenote._speech_db`, in dBFS)."""
    return float(np.percentile(_frames_db(np, x, int(FRAME_S * RATE)), 95))


def _cut(np, x, near: int, search: int, limit_db: Optional[float]) -> Tuple[int, float]:
    """The sample to cut at: the centre of the quietest 5 ms within `search` of `near` (the nearest of the windows that are
    within half a dB of it), and the level there. A cut louder than `limit_db` is refused (None: anywhere)."""
    w = max(int(CUT_S * RATE), 8)
    lo, hi = max(0, near - search), min(len(x), near + search + w)
    if hi - lo < w:
        raise VoiceNoteError(f"no room to cut at {near / RATE:.3f} s")
    cum = np.concatenate([[0.0], np.cumsum(x[lo:hi].astype("float64") ** 2)])
    energy = (cum[w:] - cum[:-w]) / w
    db = 10 * np.log10(energy + 1e-18)
    starts = np.flatnonzero(db <= db.min() + 0.5)
    pick = int(starts[np.argmin(np.abs(lo + starts + w // 2 - near))])
    level = float(db[pick])
    if limit_db is not None and level > limit_db:
        raise VoiceNoteError(f"the cut at {near / RATE:.3f} s is in his speech: it is {level:.1f} dBFS there within "
                             f"{search / RATE * 1000:.0f} ms either way, and the limit is {limit_db:.1f} (18 dB under his "
                             "loud parts). Give a time in a pause, widen --search-ms, or --anywhere")
    return lo + pick + w // 2, level


def _floor(np, x, lo: int, hi: int, ceiling_db: float, before: bool):
    """The floor next to a seam: in x[lo:hi], the run of 20 ms frames within 3 dB of the quietest fifth that lies nearest the seam
    (the last run of the stretch left of a seam, `before`, the first run of the stretch right of it), the BED_S of it beside the
    seam. None when it is under 60 ms, or louder than `ceiling_db` (then it is not floor, it is speech)."""
    lo, hi = max(0, lo), min(len(x), hi)
    n = int(FRAME_S * RATE)
    m = (hi - lo) // n
    if m < 3:
        return None
    db = _frames_db(np, x[lo: lo + m * n], n)
    quiet = db <= min(float(np.percentile(db, 20)) + 3.0, ceiling_db)
    runs, at = [], None
    for i, q in enumerate(list(quiet) + [False]):
        if q and at is None:
            at = i
        elif not q and at is not None:
            if i - at >= 3:
                runs.append((at, i))
            at = None
    if not runs:
        return None
    first, last = runs[-1] if before else runs[0]
    keep = min((last - first) * n, int(BED_S * RATE))
    end = lo + last * n
    start = end - keep if before else lo + first * n
    return x[start: start + keep].copy()


def _tile(np, src, n: int, join: int = int(0.02 * RATE)):
    """`n` samples of the floor `src`, repeated with equal-power crossfades at the joins (no dropout at the loop)."""
    if len(src) >= n:
        return src[:n].copy()
    join = min(join, len(src) // 2)
    out = src.copy()
    t = np.linspace(0, np.pi / 2, join, endpoint=False, dtype="float32")
    while len(out) < n:
        out = np.concatenate([out[:-join], out[-join:] * np.cos(t) + src[:join] * np.sin(t), src[join:]])
    return out[:n]


def _bed(np, left, right, n: int):
    """The floor under the new stretch: the floor on its left fading into the floor on its right."""
    if left is None and right is None:
        return np.zeros(n, dtype="float32")
    a = _tile(np, left if left is not None else right, n)
    b = _tile(np, right if right is not None else left, n)
    t = np.linspace(0, np.pi / 2, n, dtype="float32")
    return a * np.cos(t) + b * np.sin(t)


def _xf(np, left, right, n: int):
    """left then right, the last n samples of one crossfaded with the first n of the other."""
    n = min(n, len(left), len(right))
    if n < 2:
        return np.concatenate([left, right])
    t = np.linspace(0, np.pi / 2, n, dtype="float32")
    return np.concatenate([left[:-n], left[-n:] * np.cos(t) + right[:n] * np.sin(t), right[n:]])


def _ramps(np, y, pre: int, post: int):
    """The read's own lead and tail faded in and out over their whole length: whatever floor the read carries around its words
    (a room the clone was given) rises out of nothing into the first word and dies away after the last, and is gone before
    the note's own floor takes over."""
    y = y.copy()
    if pre >= 2:
        y[:pre] *= np.sin(np.linspace(0, np.pi / 2, pre, dtype="float32"))
    if post >= 2:
        y[-post:] *= np.cos(np.linspace(0, np.pi / 2, post, dtype="float32"))
    return y


def _gate(np, y):
    """The read's own floor taken out: the floor under the sentence is the note's (the bed), not the room the clone was given.
    Frames within 3 dB of the read's quietest tenth are closed, frames 9 dB above it open, smoothly over 25 ms. A read with
    less than 20 dB between its floor and its loud parts has no floor to take out and is left alone."""
    n = int(0.005 * RATE)
    db = _frames_db(np, y, n)
    floor, top = float(np.percentile(db, 10)), float(np.percentile(db, 95))
    if top - floor < 20.0:
        return y
    g = np.convolve(np.clip((db - floor - 3.0) / 6.0, 0.0, 1.0), np.ones(5) / 5.0, mode="same")
    return y * np.interp(np.arange(len(y)), (np.arange(len(g)) + 0.5) * n, g).astype("float32")


def _trim_read(np, read, lead_s: float, tail_s: float):
    """The read cut to its words plus a little lead and tail (its words are where it is 12 dB above its own floor, and within 30 dB of its loud parts). Returns
    it, when its words begin and end, and how many samples of lead and tail it kept."""
    n = int(0.01 * RATE)
    db = _frames_db(np, read, n)
    top, floor = float(np.percentile(db, 95)), float(np.percentile(db, 10))
    live = np.flatnonzero(db > max(floor + 12.0, top - SPEECH_BELOW_DB))  # well above its own floor, and not 30 dB under its top
    if len(live) == 0 or (live[-1] - live[0] + 1) * 0.01 < 0.15:
        raise VoiceNoteError("the read has less than 150 ms of speech in it")
    on, off = int(live[0]) * n, (int(live[-1]) + 1) * n
    start, end = max(0, on - int(lead_s * RATE)), min(len(read), off + int(tail_s * RATE))
    return read[start:end], on / RATE, off / RATE, on - start, end - off


def _seams(np, real, bed, a: int, b: int) -> list:
    """The floor at each join: the note's own on the far side, the bed's on the near side. They are the same floor, faded from
    one side of the stretch to the other, so the step is small (`voiceprint --seams OUT` measures the finished clip)."""
    w = int(0.03 * RATE)
    left, right = _db(np, real[max(0, a - w - int(0.005 * RATE)): max(0, a - int(0.005 * RATE))]), \
        _db(np, real[b + int(0.005 * RATE): b + int(0.005 * RATE) + w])
    return [{"at_s": round(a / RATE, 4), "note_db": round(left, 1), "bed_db": round(_db(np, bed[:w]), 1),
             "step_db": round(_db(np, bed[:w]) - left, 1)},
            {"at_s": round(b / RATE, 4), "note_db": round(right, 1), "bed_db": round(_db(np, bed[-w:]), 1),
             "step_db": round(_db(np, bed[-w:]) - right, 1)}]


def splice(real, read, start_s: float, end_s: float, *, search_s: float = 0.12, lead_s: float = 0.025,
           tail_s: float = 0.06, xfade_s: float = 0.006, gain_db: Optional[float] = None, anywhere: bool = False,
           gate: bool = True):
    """`real` (mono float32, 48 kHz) with the stretch about start_s..end_s replaced by `read`. Returns (samples, report)."""
    np = _np()
    if not (0 <= start_s < end_s <= len(real) / RATE + 1e-9):
        raise VoiceNoteError(f"the stretch {start_s}-{end_s} s is not inside the note ({len(real) / RATE:.3f} s)")
    loud = _speech_db(np, real)
    limit = None if anywhere else loud - REAL_QUIET_BELOW_SPEECH_DB
    search = int(search_s * RATE)
    a, a_db = _cut(np, real, int(start_s * RATE), search, limit)
    b, b_db = _cut(np, real, min(int(end_s * RATE), len(real) - 1), search, limit)
    if b - a < int(0.05 * RATE):
        raise VoiceNoteError(f"the cuts {a / RATE:.3f} s and {b / RATE:.3f} s leave nothing to replace")
    trimmed, on_s, off_s, pre, post = _trim_read(np, _gate(np, read) if gate else read, lead_s, tail_s)
    outside = np.concatenate([real[:a], real[b:]])
    ref = _speech_db(np, outside) if len(outside) >= int(FRAME_S * RATE) * 5 else loud
    gain = float(np.clip(ref - _speech_db(np, trimmed), -15.0, 15.0)) if gain_db is None else float(gain_db)
    peak = float(np.abs(trimmed).max()) or 1e-9
    gain = min(gain, -1.0 - 20 * math.log10(peak))  # the loudest sample stays under -1 dBFS
    core = _ramps(np, trimmed * np.float32(10 ** (gain / 20)), pre, post)
    room, ceiling = int(0.6 * RATE), loud - REAL_QUIET_BELOW_SPEECH_DB
    bed = _bed(np, _floor(np, real, a - room, a, ceiling, True), _floor(np, real, b, b + room, ceiling, False), len(core))
    seg = core + bed
    xf = int(xfade_s * RATE)
    out = _xf(np, _xf(np, real[:a], seg, xf), real[b:], xf)
    shift = len(out) - len(real)
    report = {
        "cut_a_s": round(a / RATE, 4), "cut_b_s": round(b / RATE, 4), "cut_a_sample": a, "cut_b_sample": b, "xfade_samples": xf,
        "cut_a_db": round(a_db, 1), "cut_b_db": round(b_db, 1),
        "limit_db": None if limit is None else round(limit, 1),
        "removed_s": round((b - a) / RATE, 4), "inserted_s": round(len(seg) / RATE, 4), "shift_s": round(shift / RATE, 4),
        "read_speech_s": [round(on_s, 3), round(off_s, 3)], "gain_db": round(gain, 1),
        "note_speech_db": round(ref, 1), "read_speech_db": round(_speech_db(np, core), 1),
        "floor_gated": bool(_db(np, bed) < GATED_DB), "floor_db": round(_db(np, bed), 1),
        "seams": _seams(np, real, bed, a, b),
        "read_lead_db": round(_db(np, core[:pre]), 1) if pre else None,
        "read_tail_db": round(_db(np, core[len(core) - post:]), 1) if post else None,
        "peak_dbfs": round(20 * math.log10(float(np.abs(out).max()) + 1e-9), 1),
        "duration_in_s": round(len(real) / RATE, 4), "duration_out_s": round(len(out) / RATE, 4),
    }
    return out, report


def summary(report: dict) -> str:
    """What `splice` did, for a person to read."""
    s0, s1 = report["seams"]
    return "\n".join([
        f"cut the note at {report['cut_a_s']:.3f} s ({report['cut_a_db']} dBFS there) and {report['cut_b_s']:.3f} s "
        f"({report['cut_b_db']} dBFS; the limit is {report['limit_db']})",
        f"removed {report['removed_s']:.3f} s, put in {report['inserted_s']:.3f} s (the read's words are "
        f"{report['read_speech_s'][0]:.3f}-{report['read_speech_s'][1]:.3f} s of it): everything after is {report['shift_s']:+.3f} s later",
        f"level: the read is {report['read_speech_db']} dBFS in its loud parts, the note's speech {report['note_speech_db']} "
        f"(gain {report['gain_db']:+} dB); peak {report['peak_dbfs']} dBFS",
        f"floor under the read: {report['floor_db']} dBFS ({'gated: near silence' if report['floor_gated'] else 'a room'}); "
        f"the read's own lead {report['read_lead_db']} and tail {report['read_tail_db']} dBFS, faded in and out",
        f"seam at {s0['at_s']:.3f} s: the note's floor {s0['note_db']} dB, the bed {s0['bed_db']} dB (step {s0['step_db']:+})",
        f"seam at {s1['at_s']:.3f} s: the note's floor {s1['note_db']} dB, the bed {s1['bed_db']} dB (step {s1['step_db']:+})",
        "the joins of the finished clip: noirstudio voiceprint OUT --seams",
    ])
