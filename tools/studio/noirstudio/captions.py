"""Word-level caption timing and ASS/SRT writers.

Two timing sources:
  * ElevenLabs `with-timestamps` character alignment (live mode) -> exact words.
  * A words-per-minute estimate with punctuation pauses (offline preview).

Captions are emitted as ASS so libass can burn them with the brand font and a
karaoke-style highlight on the word being spoken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from .brandkit import BrandKit, hex_to_ass
from .spec import Captions, Output


@dataclass
class Word:
    text: str
    start: float
    end: float

    def shifted(self, offset: float) -> "Word":
        return Word(self.text, self.start + offset, self.end + offset)


# --- timing ---------------------------------------------------------------

_PAUSE = {",": 0.16, ";": 0.2, ":": 0.2, ".": 0.38, "!": 0.38, "?": 0.38, "—": 0.25, "…": 0.4}


def estimate_words(text: str, words_per_minute: float, offset: float = 0.0) -> List[Word]:
    """Distribute an estimated duration across words (longer words take longer)."""
    tokens = text.split()
    if not tokens:
        return []
    per_word = 60.0 / words_per_minute
    weights = [max(len(t.strip("\"'()[]")), 1) for t in tokens]
    mean_w = sum(weights) / len(weights)
    words: List[Word] = []
    t = offset
    for tok, w in zip(tokens, weights):
        dur = per_word * (0.55 + 0.45 * (w / mean_w))
        words.append(Word(tok, t, t + dur))
        t += dur
        for ch, pause in _PAUSE.items():
            if tok.endswith(ch):
                t += pause
                break
        else:
            t += 0.06
    return words


def estimate_duration(text: str, words_per_minute: float, tail: float = 0.45) -> float:
    words = estimate_words(text, words_per_minute)
    return (words[-1].end + tail) if words else tail


def words_from_alignment(
    characters: Sequence[str],
    starts: Sequence[float],
    ends: Sequence[float],
    offset: float = 0.0,
) -> List[Word]:
    """Group ElevenLabs character timings into whitespace-delimited words."""
    words: List[Word] = []
    buf: List[str] = []
    w_start = 0.0
    w_end = 0.0
    for ch, s, e in zip(characters, starts, ends):
        if ch.isspace():
            if buf:
                words.append(Word("".join(buf), w_start + offset, w_end + offset))
                buf = []
            continue
        if not buf:
            w_start = s
        buf.append(ch)
        w_end = e
    if buf:
        words.append(Word("".join(buf), w_start + offset, w_end + offset))
    return words


# --- writers ----------------------------------------------------------------


def ass_time(t: float) -> str:
    t = max(t, 0.0)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def srt_time(t: float) -> str:
    t = max(t, 0.0)
    ms = int(round((t - int(t)) * 1000))
    t = int(t)
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d},{ms:03d}"


def _chunks(items: Sequence[Word], n: int) -> Iterable[Sequence[Word]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


_ASS_ESCAPE = str.maketrans({"{": "(", "}": ")", "\\": "/"})


def _clean(text: str, uppercase: bool) -> str:
    out = text.translate(_ASS_ESCAPE)
    return out.upper() if uppercase else out


def to_ass(words: Sequence[Word], brand: BrandKit, output: Output, cfg: Captions) -> str:
    """Build an ASS document: one line of N words, current word highlighted."""
    primary = hex_to_ass(brand.ink)
    highlight = hex_to_ass(brand.accent)
    outline = hex_to_ass("#000000")
    back = hex_to_ass("#000000", alpha=0x60)
    margin_h = int(output.width * 0.06)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {output.width}
PlayResY: {output.height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{brand.caption_font_family},{cfg.font_size},{primary},{primary},{outline},{back},-1,0,0,0,100,100,1,0,1,7,0,2,{margin_h},{margin_h},{cfg.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: List[str] = []
    if cfg.mode == "none" or not words:
        return header

    for chunk in _chunks(list(words), max(1, cfg.words_per_line)):
        texts = [_clean(w.text, cfg.uppercase) for w in chunk]
        if cfg.mode == "line" or not cfg.highlight:
            start, end = chunk[0].start, chunk[-1].end + 0.08
            lines.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,," + " ".join(texts)
            )
            continue
        for i, w in enumerate(chunk):
            start = w.start
            nxt = chunk[i + 1].start if i + 1 < len(chunk) else w.end + 0.10
            end = min(max(nxt, w.end), w.end + 1.0)
            parts = []
            for j, t in enumerate(texts):
                if j == i:
                    parts.append(f"{{\\c{highlight}}}{t}{{\\c{primary}}}")
                else:
                    parts.append(t)
            lines.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,," + " ".join(parts)
            )
    return header + "\n".join(lines) + "\n"


def to_srt(words: Sequence[Word], words_per_line: int = 3, uppercase: bool = False) -> str:
    out: List[str] = []
    for idx, chunk in enumerate(_chunks(list(words), max(1, words_per_line)), start=1):
        text = " ".join(_clean(w.text, uppercase) for w in chunk)
        out.append(f"{idx}\n{srt_time(chunk[0].start)} --> {srt_time(chunk[-1].end)}\n{text}\n")
    return "\n".join(out)


_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _WS.sub(" ", text).strip()
