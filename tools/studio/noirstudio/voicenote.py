"""His voice notes, rebuilt: a clean read made to sound like a note he recorded on his phone.

Where his recording of a voice note is lost and only the transcript survives, his own
voice clone reads the transcript word for word (his decision, 2026-09-29), and this
makes the clean studio read sound like what it stands in for: a phone held close in a
small room, sent over Telegram.

    band      highpass 100 Hz, lowpass 8 kHz (24 dB/oct)     a phone mic's voice input
    colour    -2 dB at 250 Hz, +3 dB at 2.8 kHz               a small capsule's presence
    room      reflections at 11 and 23 ms                     a small room, close to the mouth
    AGC       3:1 above -24 dBFS, fast attack                 the phone's level control
    level     linear gain to -18 LUFS, peaks held at -1.5 dBFS
    tone      pink room tone at -50 dBFS, from 0.35 s before the first word to 0.5 s after the last
    codec     Opus, mono, 48 kHz, 24 kbps, VoIP mode           Telegram's voice-note format

`measure` reads one of his surviving notes (loudness, room tone, bitrate) so a rebuilt
note can be matched to the real ones next to it. The speech itself is never edited: no
time-stretch, no cuts, nothing said that the transcript doesn't have.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from . import ffmpeg

HIS_VOICE = "XwGJOzi38Fyoct3IvqA9"  # his Professional Voice Clone, eleven_v4
# anoisesrc pink at amplitude 1, band-limited, reads -17.6 dBFS RMS; through Opus, measure() reads
# its quietest tenth about 2.4 dB lower. noise_db means that reading, on both sides of a match.
NOISE_GAIN_DB = 17.6 + 2.4
NOTE_EXTS = (".ogg", ".opus")  # these outputs are the Opus note itself; anything else is decoded


class VoiceNoteError(ValueError):
    pass


@dataclass
class NoteStyle:
    highpass_hz: float = 100.0
    lowpass_hz: float = 8000.0
    room: bool = True
    lufs: float = -18.0
    peak_db: float = -1.5
    noise_db: float = -50.0  # room tone: RMS of the quietest tenth of 100 ms windows, as measure() reads it
    lead_s: float = 0.35
    tail_s: float = 0.5
    kbps: int = 24
    seed: int = 7

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
        return out


def voice_chain(style: NoteStyle) -> str:
    """The speech path before its level is set: band-limit, mic colour, room, AGC."""
    band = (f"highpass=f={style.highpass_hz:g}:poles=2,highpass=f={style.highpass_hz:g}:poles=2,"
            f"lowpass=f={style.lowpass_hz:g}:poles=2,lowpass=f={style.lowpass_hz:g}:poles=2")
    parts = ["aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=mono", band,
             "equalizer=f=250:t=q:w=1:g=-2", "equalizer=f=2800:t=q:w=1.2:g=3"]
    if style.room:
        parts.append("aecho=0.9:0.9:11|23:0.18|0.1")
    parts.append("acompressor=threshold=-24dB:ratio=3:attack=5:release=90:makeup=2")
    return ",".join(parts)


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

    def encode(gain: float) -> float:
        graph = (f"[0:a]{voice_chain(style)},volume={gain:.2f}dB,"
                 f"alimiter=limit={10 ** (style.peak_db / 20):.4f}:level=0,"
                 f"adelay={round(style.lead_s * 1000)}:all=1,apad=whole_dur={total:.3f}[v];"
                 f"anoisesrc=d={total:.3f}:c=pink:r=48000:a=1:seed={style.seed},"
                 f"highpass=f={style.highpass_hz:g},lowpass=f={style.lowpass_hz:g},"
                 f"volume={style.noise_db + NOISE_GAIN_DB:.2f}dB[n];"
                 f"[v][n]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                 f"afade=t=in:d=0.02,afade=t=out:st={max(0.0, total - 0.04):.3f}:d=0.04[out]")
        ffmpeg.run(["-y", "-i", str(src), "-filter_complex", graph, "-map", "[out]", "-ac", "1", "-ar", "48000",
                    "-c:a", "libopus", "-b:a", f"{style.kbps}k", "-vbr", "on", "-application", "voip", str(note)])
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


# --- matching a real note -----------------------------------------------------------------

_BITRATE = re.compile(r"Duration: .*?bitrate: (\d+) kb/s")
_AUDIO = re.compile(r"Stream #\d+:\d+.*?Audio: (\w+), (\d+) Hz, (\w+)")
_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-inf)")


def measure(path: Path, window_s: float = 0.1) -> dict:
    """What one of his real notes sounds like: loudness, room tone (quietest tenth), bitrate."""
    header = subprocess.run([ffmpeg.ffmpeg_path(), "-hide_banner", "-i", str(path)],
                            capture_output=True, text=True).stderr
    audio = _AUDIO.search(header)
    if not audio:
        raise VoiceNoteError(f"no audio stream in {path}")
    rate = int(audio.group(2))
    err = ffmpeg.run(["-nostats", "-i", str(path), "-vn", "-af",
                      f"asetnsamples=n={max(1, round(rate * window_s))}:p=0,astats=metadata=1:reset=1,"
                      "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level", "-f", "null", "-"])
    levels = sorted(float(v) for v in _RMS.findall(err) if v != "-inf")
    if not levels:
        raise VoiceNoteError(f"{path} is silent")
    floor = statistics.quantiles(levels, n=10)[0] if len(levels) >= 2 else levels[0]
    bitrate = _BITRATE.search(header)
    return {"path": str(path), "codec": audio.group(1), "sample_rate": rate, "channels": audio.group(3),
            "kbps": int(bitrate.group(1)) if bitrate else None, "lufs": round(loudness(path), 1),
            "noise_db": round(floor, 1)}


def matched(style: NoteStyle, ref: dict) -> NoteStyle:
    """A style that lands a rebuilt note at a real one's loudness, room tone and bitrate."""
    kbps = ref.get("kbps")
    return NoteStyle(**{**asdict(style), "lufs": max(-40.0, min(-8.0, float(ref["lufs"]))),
                        "noise_db": max(-100.0, min(-20.0, float(ref["noise_db"]))),
                        "kbps": max(6, min(256, int(kbps))) if kbps else style.kbps})
