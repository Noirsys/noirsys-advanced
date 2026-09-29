"""His voice notes, rebuilt: a clean read made to sound like him, talking at home into his phone.

Where his recording of a voice note is lost and only the transcript survives, his own
voice clone reads the line (his decision, 2026-09-29). He talks quietly, at home, with a
small noise floor in the room, and he thinks out loud (his note, the same night). So the
line carries his disfluencies (uh, um, a restart, a self-correction) and `[pause 1.2]`
marks where he stops to think. The pauses come out of the text before the clone reads it
and go back in as real silence at the aligned word boundary, with his room running under
them. Then the read goes through his phone:

    band      highpass 100 Hz, lowpass 8 kHz (24 dB/oct)     a phone mic's voice input
    colour    -2 dB at 250 Hz, +1.5 dB at 2.8 kHz, -2 dB above 6 kHz   a quiet voice, not projected
    room      reflections at 11 and 23 ms                     a small room, close to the mouth
    AGC       3:1 above -24 dBFS, fast attack                 the phone's level control

That is `rough` 0, the clean phone note. His note (2026-09-29): the clone still sounds too
perfect, dynamic and articulate. A studio-trained clone talks like a performance, and he
talks like a tired man at home. So `rough` 1-3 make it lazier, each step:

    top end   lowpass 6.5 / 5.5 / 4.8 kHz, a shelf from 4.5 / 4 / 3.5 kHz         consonants stop being crisp
    presence  0 / -1.5 / -2.5 dB at 2.8 kHz, a de-esser 0.3 / 0.5 / 0.7            "s" and "t" stop cutting
    body      +1 / +2 / +3 dB at 180 Hz                                             closer to the mouth, less studio
    AGC       ratio 3.5 / 4.5 / 6 from -26 / -28 / -32 dBFS, slower release          the swings in level get squashed

and `swing` (optional, `--swing ST`) flattens the read's pitch to what `voiceprint` measures in his
real notes, and `roughen` does the same to the text before the clone reads it: ellipses, dashes,
exclamation marks and mid-line question marks each cue a performed rise or drop, so they
become commas, and (rough 2+) "going to" becomes "gonna". The clone's stability (higher =
steadier, less expressive) is the other half, and lives in the `--say` call.
    level     linear gain to -22 LUFS, peaks held at -1.5 dBFS
    tone      his room: a dark room tone at -54 dBFS, or the real one (`--room`), from
              0.35 s before the first word to 0.5 s after the last, and under every pause
    codec     Opus, mono, 48 kHz, 24 kbps, VoIP mode           Telegram's voice-note format

`measure` reads one of his surviving notes (loudness, room tone, bitrate) so a rebuilt
note can be matched to the real ones next to it; `room_tone` lifts the quiet stretches
out of one so his actual room plays under the clone. The filter never edits the speech
itself: no time-stretch, no cuts.
"""

from __future__ import annotations

import json
import math
import random
import re
import shutil
import statistics
import subprocess
import wave
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import ffmpeg
from .captions import Word, normalize_text

HIS_VOICE = "XwGJOzi38Fyoct3IvqA9"  # his Professional Voice Clone, eleven_v4
# The synthetic room tone (pink, darkened) at amplitude 1 through Opus reads NOISE_GAIN_DB below
# full scale in measure(); noise_db means that reading, on both sides of a match.
NOISE_GAIN_DB = 19.7
GATED_DB = -80.0  # a real note whose pauses read below this was noise-suppressed: no room to copy
NOTE_EXTS = (".ogg", ".opus")  # these outputs are the Opus note itself; anything else is decoded
DEFAULT_PAUSE_S = 0.8


class VoiceNoteError(ValueError):
    pass


@dataclass
class NoteStyle:
    highpass_hz: float = 100.0
    lowpass_hz: float = 8000.0
    room: bool = True
    lufs: float = -22.0  # he talks quietly
    peak_db: float = -1.5
    noise_db: float = -54.0  # room tone: RMS of the quietest tenth of 100 ms windows, as measure() reads it
    lead_s: float = 0.35
    tail_s: float = 0.5
    kbps: int = 24
    seed: int = 7
    room_tone: Optional[str] = None  # a WAV of his real room (room_tone()); None = the synthetic one
    rough: int = 2  # 0 = the clean phone note; 1-3 = a quieter, lazier, less crisp voice (see the top of this file)

    def problems(self) -> List[str]:
        out = []
        if not 20 <= self.highpass_hz < self.lowpass_hz <= 20000:
            out.append(f"band {self.highpass_hz:g}-{self.lowpass_hz:g} Hz: need 20 <= highpass < lowpass <= 20000")
        if not -40 <= self.lufs <= -8:
            out.append(f"lufs {self.lufs:g}: expected -40 to -8")
        if not -12 <= self.peak_db <= 0:
            out.append(f"peak {self.peak_db:g} dBFS: expected -12 to 0")
        if not -100 <= self.noise_db <= -20:
            out.append(f"room tone {self.noise_db:g} dBFS: expected -100 to -20")
        if not (0 <= self.lead_s <= 5 and 0 <= self.tail_s <= 5):
            out.append("lead and tail: 0 to 5 s")
        if not 6 <= self.kbps <= 256:
            out.append(f"{self.kbps} kbps: Opus takes 6 to 256")
        if self.room_tone and not Path(self.room_tone).exists():
            out.append(f"room tone file {self.room_tone} is missing")
        if self.rough not in (0, 1, 2, 3):
            out.append(f"rough {self.rough}: expected 0 to 3")
        return out


# One row per `rough` step. Step 0 is the clean phone note exactly as v3 shipped it.
_ROUGH = (
    dict(lowpass=8000, presence=1.5, shelf=(6000, -2), deess=0.0, body=0.0, comp=(-24, 3, 5, 90, 2)),
    dict(lowpass=6500, presence=0.0, shelf=(4500, -3), deess=0.3, body=1.0, comp=(-26, 3.5, 5, 120, 2)),
    dict(lowpass=5500, presence=-1.5, shelf=(4000, -4), deess=0.5, body=2.0, comp=(-28, 4.5, 4, 150, 3)),
    dict(lowpass=4800, presence=-2.5, shelf=(3500, -5), deess=0.7, body=3.0, comp=(-32, 6, 3, 180, 4)),
)


def voice_chain(style: NoteStyle) -> str:
    """The speech path before its level is set: band-limit, a quiet voice's colour, room, AGC."""
    step = _ROUGH[style.rough if style.rough in (0, 1, 2, 3) else 0]
    lowpass = min(style.lowpass_hz, step["lowpass"])
    band = (f"highpass=f={style.highpass_hz:g}:poles=2,highpass=f={style.highpass_hz:g}:poles=2,"
            f"lowpass=f={lowpass:g}:poles=2,lowpass=f={lowpass:g}:poles=2")
    parts = ["aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=mono", band,
             "equalizer=f=250:t=q:w=1:g=-2"]
    if step["body"]:
        parts.append(f"equalizer=f=180:t=q:w=0.8:g={step['body']:g}")
    parts += [f"equalizer=f=2800:t=q:w=1.2:g={step['presence']:g}",
              f"highshelf=f={step['shelf'][0]}:g={step['shelf'][1]}"]
    if step["deess"]:
        parts.append(f"deesser=i={step['deess']:g}:m=0.6")
    if style.room:
        parts.append("aecho=0.9:0.9:11|23:0.22|0.12")
    threshold, ratio, attack, release, makeup = step["comp"]
    parts.append(f"acompressor=threshold={threshold}dB:ratio={ratio:g}:attack={attack}:release={release}:makeup={makeup}")
    return ",".join(parts)


def room_chain(style: NoteStyle, total: float) -> Tuple[List[str], str]:
    """Extra ffmpeg inputs and the filter that makes the room bed [n], `total` seconds long."""
    if style.room_tone:
        reading = _floor(Path(style.room_tone))
        gain = style.noise_db - reading
        return (["-stream_loop", "-1", "-i", style.room_tone],
                f"[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,atrim=0:{total:.3f},"
                f"asetpts=PTS-STARTPTS,volume={gain:.2f}dB[n]")
    return ([], f"anoisesrc=d={total:.3f}:c=pink:r=48000:a=1:seed={style.seed},"
                f"highpass=f={style.highpass_hz:g},lowpass=f=3500,equalizer=f=150:t=q:w=1:g=4,"
                f"volume={style.noise_db + NOISE_GAIN_DB:.2f}dB[n]")


_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def loudness(path: Path, chain: str = "") -> float:
    """Integrated loudness (LUFS) of a file, optionally through a filter chain first."""
    af = f"{chain},loudnorm=print_format=json" if chain else "loudnorm=print_format=json"
    blocks = _LOUDNORM_JSON.findall(ffmpeg.run(["-nostats", "-i", str(path), "-vn", "-af", af, "-f", "null", "-"]))
    if not blocks:
        raise VoiceNoteError(f"no loudness reading for {path}")
    return float(json.loads(blocks[-1])["input_i"])


def render(src: Path, out: Path, style: Optional[NoteStyle] = None) -> dict:
    """Clean speech in, voice note out (.ogg/.opus is the note itself; .wav etc. is it decoded)."""
    style = style or NoteStyle()
    problems = style.problems()
    if problems:
        raise VoiceNoteError("; ".join(problems))
    speech = ffmpeg.probe_duration(src)
    measured = loudness(src, voice_chain(style))
    if measured == float("-inf") or measured < -70:
        raise VoiceNoteError(f"{src} has no speech to rebuild ({measured} LUFS)")
    total = style.lead_s + speech + style.tail_s
    out.parent.mkdir(parents=True, exist_ok=True)
    note = out if out.suffix.lower() in NOTE_EXTS else out.with_name(out.stem + ".note.ogg")
    room_inputs, room = room_chain(style, total)

    def encode(gain: float) -> float:
        graph = (f"[0:a]{voice_chain(style)},volume={gain:.2f}dB,"
                 f"alimiter=limit={10 ** (style.peak_db / 20):.4f}:level=0,"
                 f"adelay={round(style.lead_s * 1000)}:all=1,apad=whole_dur={total:.3f}[v];{room};"
                 f"[v][n]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                 f"afade=t=in:d=0.02,afade=t=out:st={max(0.0, total - 0.04):.3f}:d=0.04[out]")
        ffmpeg.run(["-y", "-i", str(src), *room_inputs, "-filter_complex", graph, "-map", "[out]", "-ac", "1",
                    "-ar", "48000", "-c:a", "libopus", "-b:a", f"{style.kbps}k", "-vbr", "on", "-application", "voip",
                    str(note)])
        return loudness(note)

    gain = max(-40.0, min(40.0, style.lufs - measured))
    lufs = encode(gain)
    if abs(style.lufs - lufs) > 0.5:  # the limiter and codec shave a little; correct once
        gain = max(-40.0, min(40.0, gain + style.lufs - lufs))
        lufs = encode(gain)
    if note != out:
        codec = ["-c:a", "pcm_s16le"] if out.suffix.lower() == ".wav" else []
        ffmpeg.run(["-y", "-i", str(note), "-ar", "48000", "-ac", "1", *codec, str(out)])
        note.unlink(missing_ok=True)
    return {"path": str(out), "source": str(src), "speech_s": round(speech, 2), "duration_s": round(total, 2),
            "source_lufs": round(measured, 1), "gain_db": round(gain, 1), "lufs": round(lufs, 1),
            "style": asdict(style)}


# --- thinking pauses ----------------------------------------------------------------------

_PAUSE = re.compile(r"\s*\[pause(?:\s+(\d+(?:\.\d+)?)\s*s?)?\]", re.I)
_TAG = re.compile(r"\[[^\[\]\n]{1,48}\]")


_CASUAL = ((r"\bgoing to\b", "gonna"), (r"\bwant to\b", "wanna"), (r"\bkind of\b", "kinda"),
           (r"\bsort of\b", "sorta"), (r"\bgot to\b", "gotta"), (r"\bdon't know\b", "dunno"),
           (r"\byou know\b", "y'know"))


def roughen(text: str, level: int) -> str:
    """Write a line the way he says it, not the way it's punctuated.

    Ellipses, dashes and "!" each cue the clone to perform (a drawn-out fall, a sharp cut, a lift),
    and a "?" mid-line lifts the pitch, so they become commas. Level 2 adds the casual contractions
    ("gonna", "wanna", "kinda", "dunno"); level 3 runs the sentences together so nothing falls
    at a full stop. `[tags]` and `[pause N]` markers pass through untouched.
    """
    if level <= 0:
        return text
    kept: List[str] = []

    def stash(m: "re.Match[str]") -> str:
        kept.append(m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    s = _TAG.sub(stash, text)
    s = re.sub(r"\s*(?:…|\.{3,}|—|–|\s-\s)\s*", ", ", s)
    s = re.sub(r"!+", ".", s)
    s = re.sub(r"\?(?=\s*\S)", ",", s)
    if level >= 2:
        for pattern, repl in _CASUAL:
            s = re.sub(pattern, lambda m, r=repl: r.capitalize() if m.group(0)[0].isupper() else r, s, flags=re.I)
    if level >= 3:
        s = re.sub(r"\.\s+(?=[A-Za-z\x00])", ", ", s)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r"([.?!]),", r"\1", s)
    s = re.sub(r",(\s*,)+", ",", s)
    s = re.sub(r"[,\s]+$", "", s) if not re.search(r"[.?!]\s*$", s) else s
    s = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], s)
    return normalize_text(s)


def rawify(text: str) -> str:
    """A line the way his transcripts read: lowercase, no punctuation, run together.

    His stored transcripts are all "understood and i thank you for um working with me on this um
    you know i just feel i just feel that it won't be long before you know whether...". Punctuation
    tells a clone how to perform (fall at a full stop, lift at a question), so a line without it
    is read in one breath, like him. Apostrophes and hyphens inside words stay; `[tags]` and
    `[pause N]` markers pass through untouched.
    """
    kept: List[str] = []

    def stash(m: "re.Match[str]") -> str:
        kept.append(m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    s = _TAG.sub(stash, text).lower()
    s = re.sub(r"[.,;:!?…—–\"“”()]+|\s[-–]+\s|--+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], s)


def split_pauses(text: str, trail: str = "…") -> Tuple[str, List[Tuple[int, float]]]:
    """Take `[pause]` / `[pause 1.2]` out of a line: (line for the clone, [(words before it, seconds)]).

    Where the text runs straight into a pause, `trail` (an ellipsis by default; a comma for a flat
    read) is left so the clone trails off there instead of reading through it.
    """
    pieces, pauses, pos = [], [], 0
    for m in _PAUSE.finditer(text):
        before = "".join(pieces) + text[pos:m.start()]
        if before.strip() and not before.rstrip()[-1] in ".,!?…—-":
            before = before.rstrip() + trail
        pieces, pos = [before], m.end()
        pauses.append((len(_TAG.sub(" ", before).split()), float(m.group(1)) if m.group(1) else DEFAULT_PAUSE_S))
    return normalize_text("".join(pieces) + text[pos:]), pauses


# How he stops to think, measured on 87 of his real notes (29 min of speech, `voiceprint`, 2026-09-29):
# about 17 pauses a minute, median 0.88 s, middle half 0.49 to 1.54 s. The clone's own median was 0.34 s.
HIS_PAUSES = {"rate_per_min": 17.0, "median_s": 0.85, "sigma": 0.85, "min_s": 0.25, "max_s": 3.0}
_PUNCT = ".,?!;:…—-\"'"
_FILLERS = {"uh", "um", "er", "erm", "ah", "hmm", "mm"}
_LEADS = {"so", "and", "but", "like", "well", "okay", "ok", "because", "cause", "then", "yeah", "honestly",
          "actually", "basically", "anyway", "i", "y'know", "you"}
_SEARCHING = {"the", "a", "an", "to", "of", "my", "your", "his", "her", "that", "this", "some", "for", "with"}


def hesitations(line: str, words: Sequence[Word], explicit: Sequence[Tuple[int, float]] = (), scale: float = 1.0,
                seed: int = 7, habits: Optional[dict] = None) -> List[Tuple[int, float]]:
    """Where and for how long he stops to think, drawn from his measured habits: [(words before it, seconds)].

    A clone reads straight through; he stops about 17 times a minute, for a median of 0.85 s and
    sometimes for several seconds. `scale` 1 is his rate (2 is twice as often, 0 none) and the
    `[pause N]` markers already in the line count toward it. A pause lands where a person's does:
    after a comma or a full stop, where the clone already drew breath, before "so", "and", "like",
    after "uh" and "um", and after "the" and "to" while the next word is being looked for. Never
    at the first or last two words, and never within two words of another pause. The same line
    and seed always give the same pauses. What comes back is the *extra* silence to insert: the
    gap the clone already left at that spot is taken off.
    """
    h = {**HIS_PAUSES, **(habits or {})}
    n = len(words)
    if scale <= 0 or n < 8:
        return []
    rng = random.Random(f"{seed}:{line}")
    tokens = line.split()
    tokens = tokens if len(tokens) == n else None  # punctuation only helps when it lines up with the aligned words
    span = words[-1].end - words[0].start + sum(s for _, s in explicit)
    expected = scale * h["rate_per_min"] * span / 60 - len(explicit)
    if expected <= 0:
        return []
    count = int(expected) + (1 if rng.random() < expected - int(expected) else 0)
    weight = {}
    for b in range(2, n - 1):  # a pause after word b-1, with at least two words on each side
        if any(abs(b - k) <= 2 for k, _ in explicit):
            continue
        w = 0.3
        if words[b].start - words[b - 1].end >= 0.12:  # the clone drew breath here already
            w += 3.0
        if tokens:
            before, after = tokens[b - 1], tokens[b].lower().strip(_PUNCT)
            if before[-1:] in _PUNCT:
                w += 3.0
            w += 1.5 * (after in _LEADS) + 1.5 * (before.lower().strip(_PUNCT) in _FILLERS)
            w += 1.0 * (before.lower().strip(_PUNCT) in _SEARCHING)
        weight[b] = w
    chosen: List[int] = []
    while len(chosen) < count and weight:
        b = rng.choices(list(weight), list(weight.values()))[0]
        chosen.append(b)
        for near in range(b - 2, b + 3):
            weight.pop(near, None)
    out = []
    for b in sorted(chosen):
        length = min(h["max_s"], max(h["min_s"], rng.lognormvariate(math.log(h["median_s"]), h["sigma"])))
        out.append((b, round(max(0.1, length - max(0.0, words[b].start - words[b - 1].end)), 2)))
    return out


def insert_pauses(wav_path: Path, words: Sequence[Word], pauses: Sequence[Tuple[int, float]]) -> List[Word]:
    """Put the pauses back into the clean read as silence, between the aligned words; returns shifted words."""
    if not pauses:
        return list(words)
    at = []
    for k, seconds in pauses:
        if not words or k <= 0:
            t = 0.0
        elif k >= len(words):
            t = words[-1].end
        else:
            t = (words[k - 1].end + words[k].start) / 2
        at.append((t, seconds))
    at.sort()
    with wave.open(str(wav_path), "rb") as wf:
        params, rate = wf.getparams(), wf.getframerate()
        frame_bytes = wf.getsampwidth() * wf.getnchannels()
        audio = wf.readframes(wf.getnframes())
    chunks, last = [], 0
    for t, seconds in at:
        cut = min(len(audio), round(t * rate) * frame_bytes)
        chunks += [audio[last:cut], b"\x00" * (round(seconds * rate) * frame_bytes)]
        last = cut
    chunks.append(audio[last:])
    with wave.open(str(wav_path), "wb") as wf:
        wf.setparams(params)
        wf.writeframes(b"".join(chunks))
    shifted = []
    for w in words:
        d = sum(s for t, s in at if w.start >= t)
        shifted.append(Word(w.text, round(w.start + d, 3), round(w.end + d, 3)))
    return shifted


# --- pitch and pace -----------------------------------------------------------------------

def prosody(src: Path, out: Path, swing_st: Optional[float] = None, median_hz: Optional[float] = None,
            pace: float = 1.0, floor_hz: float = 70.0, ceiling_hz: float = 300.0, seed: int = 7) -> dict:
    """Bring a read's pitch level, pitch swing and speaking rate down to his, as `voiceprint` measures them.

    On the same words as two of his real notes, the clone sat 3 to 5 semitones higher (126-144 Hz
    against his 100-108), swung its pitch twice as far (6 semitones against his 3) and spoke a
    quarter faster (225 words a minute of speech against his 175). Praat's "Change gender" is a
    pitch-synchronous resynthesis: it moves the pitch median (`median_hz`), scales the excursions
    around it (`swing_st`, the pitch standard deviation in semitones as `voiceprint` reads it) and
    lengthens the speech (`pace` 1.2 is 20% slower), while the voice, the formants and the level
    stay. Praat scales the excursions it tracks and the estimator also sees jitter it doesn't, so the
    factor is found by measuring the result and correcting, not assumed. A read already flatter than
    `swing_st` keeps its swing: this only ever flattens. Praat's resynthesis is not deterministic on its
    own (two identical calls differ at the sample level and by 0.2-0.5 semitones of measured swing), so
    its random generator is seeded and the same read gives the same bytes every time.

    Returns the before and after numbers, and `pace_effective`: what to multiply the aligned word
    timings by. Needs praat-parselmouth (`pip install "noirstudio[voice]"`).
    """
    try:
        import parselmouth
        from parselmouth.praat import call
    except ImportError as exc:
        raise VoiceNoteError('pitch, swing and pace need praat-parselmouth: pip install "noirstudio[voice]"') from exc
    from .voiceprint import voiceprint

    if swing_st is not None and not 0.3 <= swing_st <= 8:
        raise VoiceNoteError(f"swing {swing_st:g}: expected 0.3 to 8 semitones")
    if median_hz is not None and not 60 <= median_hz <= 250:
        raise VoiceNoteError(f"pitch {median_hz:g} Hz: expected 60 to 250")
    if not 0.6 <= pace <= 1.6:
        raise VoiceNoteError(f"pace {pace:g}: expected 0.6 to 1.6 (1.2 is 20% slower)")
    src, out = Path(src), Path(out)
    seen = voiceprint(src, levels=False)
    sd0, median0 = seen.get("f0_sd_st"), seen.get("f0_median_hz")
    flatten = swing_st is not None and bool(sd0) and sd0 > swing_st
    if not flatten and median_hz is None and pace == 1.0:
        if src != out:
            shutil.copyfile(src, out)
        return {"swing_target_st": swing_st, "swing_before_st": sd0, "swing_after_st": sd0, "factor": 1.0,
                "median_target_hz": None, "median_before_hz": median0, "median_after_hz": median0,
                "pace": 1.0, "pace_effective": 1.0, "drift_s": 0.0}
    sound = parselmouth.Sound(str(src))
    if sound.n_channels > 1:  # a clone's read arrives as 48 kHz stereo, and Praat's gender change takes mono only
        sound = sound.convert_to_mono()

    def run(factor: float) -> dict:
        try:  # Praat's resynthesis draws random numbers; the same read must come out the same every time
            parselmouth.praat.run(f"random_initializeWithSeedUnsafelyButPredictably({int(seed)})")
        except Exception:  # pragma: no cover - an older Praat without the command
            pass
        result = call(sound, "Change gender", floor_hz, ceiling_hz, 1.0, float(median_hz or 0), factor, float(pace))
        out.parent.mkdir(parents=True, exist_ok=True)
        result.save(str(out), "WAV")
        return voiceprint(out, levels=False)

    factor = max(0.15, swing_st / sd0) if flatten else 1.0
    got = run(factor)
    if flatten:  # two secant steps on (factor -> measured swing), from (1.0 -> what it was)
        earlier = (1.0, sd0)
        for _ in range(2):
            sd = got.get("f0_sd_st")
            if sd is None or sd <= swing_st * 1.08 or sd == earlier[1] or factor == earlier[0]:
                break
            nxt = factor + (swing_st - sd) * (factor - earlier[0]) / (sd - earlier[1])
            nxt = max(0.15, min(factor, nxt))
            if factor - nxt < 0.01:
                break
            earlier, factor = (factor, sd), nxt
            got = run(factor)
    seconds_in, seconds_out = ffmpeg.probe_duration(src), ffmpeg.probe_duration(out)
    return {"swing_target_st": swing_st, "swing_before_st": sd0, "swing_after_st": got.get("f0_sd_st"),
            "factor": round(factor, 3), "median_target_hz": median_hz, "median_before_hz": median0,
            "median_after_hz": got.get("f0_median_hz"), "pace": pace,
            "pace_effective": round(seconds_out / seconds_in, 4) if seconds_in else 1.0,
            "drift_s": round(seconds_out - seconds_in * pace, 3)}


def swing(src: Path, out: Path, target_st: float, floor_hz: float = 70.0, ceiling_hz: float = 300.0) -> dict:
    """Only the pitch swing of `prosody`: flatten a read to `target_st` semitones, median and pace unchanged."""
    got = prosody(src, out, swing_st=target_st, floor_hz=floor_hz, ceiling_hz=ceiling_hz)
    return {"target_st": target_st, "before_st": got["swing_before_st"], "after_st": got["swing_after_st"],
            "factor": got["factor"], "drift_s": got["drift_s"]}


# --- matching a real note -----------------------------------------------------------------

_BITRATE = re.compile(r"Duration: .*?bitrate: (\d+) kb/s")
_AUDIO = re.compile(r"Stream #\d+:\d+.*?Audio: (\w+)[^,]*, (\d+) Hz, (\w+)")  # a WAV says "pcm_s16le ([1][0][0][0] / 0x0001),"
_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-inf)")


def _levels(path: Path, rate: int, window_s: float = 0.1) -> List[float]:
    err = ffmpeg.run(["-nostats", "-i", str(path), "-vn", "-af",
                      f"asetnsamples=n={max(1, round(rate * window_s))}:p=0,astats=metadata=1:reset=1,"
                      "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level", "-f", "null", "-"])
    return sorted(float(v) for v in _RMS.findall(err) if v != "-inf")


def _floor(path: Path) -> float:
    """The quietest tenth of a file's 100 ms windows (RMS dBFS): how measure() reads room tone."""
    levels = _levels(path, 48000)
    if not levels:
        return -120.0
    return statistics.quantiles(levels, n=10)[0] if len(levels) >= 2 else levels[0]


def measure(path: Path, window_s: float = 0.1) -> dict:
    """What one of his real notes sounds like: loudness, room tone (quietest tenth), bitrate."""
    header = subprocess.run([ffmpeg.ffmpeg_path(), "-hide_banner", "-i", str(path)],
                            capture_output=True, text=True).stderr
    audio = _AUDIO.search(header)
    if not audio:
        raise VoiceNoteError(f"no audio stream in {path}")
    rate = int(audio.group(2))
    levels = _levels(path, rate, window_s)
    if not levels:
        raise VoiceNoteError(f"{path} is silent")
    floor = statistics.quantiles(levels, n=10)[0] if len(levels) >= 2 else levels[0]
    bitrate = _BITRATE.search(header)
    return {"path": str(path), "codec": audio.group(1), "sample_rate": rate, "channels": audio.group(3),
            "kbps": int(bitrate.group(1)) if bitrate else None, "lufs": round(loudness(path), 1),
            "noise_db": round(floor, 1)}


def matched(style: NoteStyle, ref: dict) -> NoteStyle:
    """A style that lands a rebuilt note at a real one's loudness, room tone and bitrate.

    A note whose pauses read below GATED_DB was noise-suppressed on the way in, and its
    silence isn't his room, so the room tone stays as it is.
    """
    kbps = ref.get("kbps")
    noise = float(ref["noise_db"])
    return replace(style, lufs=max(-40.0, min(-8.0, float(ref["lufs"]))),
                   noise_db=max(-100.0, min(-20.0, noise)) if noise >= GATED_DB else style.noise_db,
                   kbps=max(6, min(256, int(kbps))) if kbps else style.kbps)


def room_tone(real: Path, out: Path, min_s: float = 0.2) -> Optional[dict]:
    """His room, lifted from one of his real notes: its quiet stretches, joined into a WAV to loop.

    Returns None when the note has no room in it (noise-suppressed, or too little silence).
    """
    from .cut import silences

    ref = measure(real)
    if ref["noise_db"] < GATED_DB:
        return None
    edge = 0.03  # keep clear of the words on either side
    # silencedetect compares sample peaks, and room noise peaks sit 10-12 dB over its RMS reading
    spans = [(a + edge, b - edge) for a, b in silences(real, ref["noise_db"] + 14, min_s) if b - a >= min_s + 2 * edge]
    if sum(b - a for a, b in spans) < 0.5:
        return None
    chains = [f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,"
              f"afade=t=out:st={b - a - 0.01:.3f}:d=0.01[s{i}]" for i, (a, b) in enumerate(spans)]
    graph = ";".join(chains) + ";" + "".join(f"[s{i}]" for i in range(len(spans))) + f"concat=n={len(spans)}:v=0:a=1[out]"
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-y", "-i", str(real), "-filter_complex", graph, "-map", "[out]", "-ac", "1", "-ar", "48000",
                "-c:a", "pcm_s16le", str(out)])
    return {"path": str(out), "seconds": round(sum(b - a for a, b in spans), 2), "stretches": len(spans),
            "noise_db": ref["noise_db"]}
