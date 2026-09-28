import math

from noirstudio.brandkit import get_brand
from noirstudio.captions import (
    Word,
    ass_time,
    estimate_duration,
    estimate_words,
    srt_time,
    to_ass,
    to_srt,
    words_from_alignment,
)
from noirstudio.spec import Captions, Output

TEXT = "Your AI agent is not failing at the task. It is failing at the handoff."


def test_estimate_words_is_monotonic_and_complete():
    words = estimate_words(TEXT, 150)
    assert [w.text for w in words] == TEXT.split()
    assert words[0].start == 0.0
    for a, b in zip(words, words[1:]):
        assert a.end <= b.start
        assert a.end > a.start
    # sentence end adds a pause larger than the inter-word gap
    idx = [w.text for w in words].index("task.")
    assert words[idx + 1].start - words[idx].end > 0.3


def test_estimate_duration_scales_with_rate():
    slow = estimate_duration(TEXT, 100)
    fast = estimate_duration(TEXT, 200)
    assert slow > fast > 0
    assert estimate_duration("", 150) > 0


def test_words_from_alignment_groups_characters():
    chars = list("Hi there.")
    starts = [i * 0.1 for i in range(len(chars))]
    ends = [s + 0.1 for s in starts]
    words = words_from_alignment(chars, starts, ends, offset=1.0)
    assert [w.text for w in words] == ["Hi", "there."]
    assert math.isclose(words[0].start, 1.0)
    assert math.isclose(words[0].end, 1.2)
    assert math.isclose(words[1].start, 1.3)
    assert math.isclose(words[1].end, 1.9)


def test_time_formatting():
    assert ass_time(61.5) == "0:01:01.50"
    assert ass_time(-1) == "0:00:00.00"
    assert srt_time(3661.25) == "01:01:01,250"


def _words(n=7):
    return [Word(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(n)]


def test_to_ass_word_mode_highlights_current_word():
    brand = get_brand("noirsys")
    out = to_ass(_words(7), brand, Output(), Captions(words_per_line=3))
    dialogues = [l for l in out.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogues) == 7  # one event per spoken word
    assert brand.caption_font_family in out
    assert "\\c&H" in dialogues[0]  # highlight colour tag present
    assert "W0" in dialogues[0] and "W1" in dialogues[0] and "W2" in dialogues[0]
    assert "W3" not in dialogues[0]


def test_to_ass_line_mode_and_none():
    brand = get_brand("noirpost")
    line = to_ass(_words(7), brand, Output(), Captions(mode="line", words_per_line=3, uppercase=False))
    assert sum(1 for l in line.splitlines() if l.startswith("Dialogue:")) == 3
    assert "w0 w1 w2" in line
    none = to_ass(_words(7), brand, Output(), Captions(mode="none"))
    assert "Dialogue:" not in none
    assert "[Events]" in none


def test_to_ass_escapes_braces():
    brand = get_brand("noirsys")
    out = to_ass([Word("{evil}", 0, 1)], brand, Output(), Captions(uppercase=False))
    assert "{evil}" not in out and "(evil)" in out


def test_to_srt_blocks():
    srt = to_srt(_words(7), words_per_line=3)
    assert srt.count("-->") == 3
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,400\nw0 w1 w2")
