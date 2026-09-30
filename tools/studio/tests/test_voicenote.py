"""His lost voice notes, rebuilt: a clean read in, a phone voice note out (Opus, room tone, his level)."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from noirstudio import ffmpeg
from noirstudio.cli import main
from noirstudio.captions import Word
from noirstudio.voice import ElevenLabsVoice
from noirstudio.voicenote import (HIS_VOICE, NoteStyle, VoiceNoteError, clone_spelling, hesitations,
                                  insert_pauses, loudness, matched, measure, plain_filler, rawify, render, room_tone,
                                  roughen, split_pauses, stumbles, voice_chain)

# voiced at 140 Hz with harmonics, syllable-paced, plus air at 10 kHz: a stand-in for a studio read
SPEECHY = ("(0.3*sin(2*PI*140*t)+0.2*sin(2*PI*280*t)+0.1*sin(2*PI*420*t)+0.06*sin(2*PI*2800*t)"
           "+0.06*sin(2*PI*10000*t))*(0.55+0.45*sin(2*PI*3.5*t))")


@pytest.fixture(scope="module")
def clean(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("vn") / "clean.wav"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", f"aevalsrc='{SPEECHY}':s=44100:d=2", "-ac", "2", "-c:a", "pcm_s16le",
                str(path)])
    return path


def _rms(path: Path, af: str = "anull") -> float:
    err = ffmpeg.run(["-nostats", "-i", str(path), "-af", f"{af},astats=measure_perchannel=none", "-f", "null", "-"])
    return float(re.findall(r"RMS level dB: (-?[\d.]+|-inf)", err)[-1])


def _header(path: Path) -> str:
    import subprocess

    return subprocess.run([ffmpeg.ffmpeg_path(), "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr


def test_a_clean_read_comes_out_sounding_recorded(clean, tmp_path):
    out = tmp_path / "note.wav"
    report = render(clean, out)
    assert abs(ffmpeg.probe_duration(out) - 2.85) < 0.05  # 0.35 s of room before the words, 0.5 s after
    assert abs(loudness(out) + 22) < 0.6 and report["lufs"] == pytest.approx(-22, abs=0.6)  # he talks quietly
    assert -59 < _rms(out, "atrim=0.05:0.3") < -49  # his room before he speaks, not digital silence
    air = "highpass=f=9000:poles=2,highpass=f=9000:poles=2"
    assert _rms(out, air) - _rms(out) < _rms(clean, air) - _rms(clean) - 6  # the studio air is gone
    assert "48000 Hz, mono" in _header(out)
    assert not list(tmp_path.glob("*.note.ogg"))


def test_ogg_out_is_the_opus_note_itself(clean, tmp_path):
    render(clean, tmp_path / "note.ogg", NoteStyle(kbps=32))
    head = _header(tmp_path / "note.ogg")
    assert "Audio: opus, 48000 Hz, mono" in head


def test_match_lands_on_a_real_notes_level_room_and_bitrate(clean, tmp_path):
    render(clean, tmp_path / "real.ogg", NoteStyle(noise_db=-40, lufs=-24, kbps=32))
    real = measure(tmp_path / "real.ogg")
    assert real["codec"] == "opus" and real["sample_rate"] == 48000
    assert abs(real["lufs"] + 24) < 0.6 and abs(real["noise_db"] + 40) < 2 and 24 <= real["kbps"] <= 40
    style = matched(NoteStyle(), real)
    assert (style.lufs, style.noise_db, style.kbps) == (real["lufs"], real["noise_db"], real["kbps"])
    render(clean, tmp_path / "rebuilt.ogg", style)
    rebuilt = measure(tmp_path / "rebuilt.ogg")
    assert abs(rebuilt["lufs"] - real["lufs"]) < 0.6 and abs(rebuilt["noise_db"] - real["noise_db"]) < 2


def test_bad_styles_and_silence_are_refused(tmp_path):
    assert NoteStyle().problems() == []
    assert NoteStyle(highpass_hz=9000).problems()  # above the lowpass
    assert NoteStyle(kbps=2).problems() and NoteStyle(noise_db=-5).problems() and NoteStyle(lufs=0).problems()
    assert NoteStyle(room_tone=str(tmp_path / "missing.wav")).problems()
    with pytest.raises(VoiceNoteError, match="band"):
        render(tmp_path / "unused.wav", tmp_path / "x.ogg", NoteStyle(lowpass_hz=50))
    silent = tmp_path / "silent.wav"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "1", "-c:a", "pcm_s16le", str(silent)])
    with pytest.raises(VoiceNoteError, match="no speech"):
        render(silent, tmp_path / "x.ogg")


def test_cli_say_has_his_clone_read_his_words(clean, tmp_path, monkeypatch, capsys):
    calls = []

    def fake_send(self, method, path, data, content_type, accept, query=""):
        calls.append((path, data))
        if path == "/v1/forced-alignment":
            return json.dumps({"words": [{"text": "Say", "start": 0.1, "end": 0.3},
                                         {"text": "it", "start": 0.3, "end": 0.4},
                                         {"text": "for", "start": 0.4, "end": 0.6},
                                         {"text": "me.", "start": 0.6, "end": 0.9}]}).encode()
        return clean.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    out = tmp_path / "say-it-for-me.ogg"
    assert main(["voicenote", "--say", "Say it for me.", str(out)]) == 0
    tts_path, body = calls[0]
    assert tts_path == f"/v1/text-to-speech/{HIS_VOICE}"
    sent = json.loads(body)
    assert sent["text"] == "Say it for me." and sent["model_id"] == "eleven_v4"
    assert sent["voice_settings"]["stability"] == 0.85  # steadier than the v3 read: he sounds tired, not performed
    assert "Audio: opus" in _header(out)
    words = json.loads((tmp_path / "say-it-for-me.words.json").read_text(encoding="utf-8"))
    assert words["said"] == "Say it for me." and words["voice_id"] == HIS_VOICE
    assert words["words"][0] == {"text": "Say", "start": 0.45, "end": 0.65}  # shifted by the 0.35 s lead
    assert "room tone -54.0 dBFS" in capsys.readouterr().out
    # a delivery tag directs his clone and is not said: sent to TTS, kept out of alignment
    assert main(["voicenote", "--say", "[laughing] Say it for me.", str(out)]) == 0
    assert json.loads(calls[2][1])["text"] == "[laughing] Say it for me."
    assert b"[laughing]" not in calls[3][1] and b"Say it for me." in calls[3][1]


def test_cli_filter_and_measure(clean, tmp_path, capsys):
    out = tmp_path / "note.ogg"
    assert main(["voicenote", str(clean), str(out), "--lufs", "-20", "--no-room", "--kbps", "32"]) == 0
    assert main(["voicenote", "--measure", str(out)]) == 0
    printed = capsys.readouterr().out
    read = [float(x) for x in re.findall(r"(-\d+\.\d) LUFS", printed)]
    assert len(read) == 2 and all(abs(x + 20) < 0.6 for x in read) and "opus" in printed
    assert main(["voicenote", str(clean)]) == 1  # IN needs an OUT


def test_thinking_pauses_come_out_of_the_line_and_back_in_as_silence(tmp_path):
    line, pauses = split_pauses("Um, I— I don't know. [pause 1.2] Maybe [pause] yeah.")
    assert line == "Um, I— I don't know. Maybe… yeah." and pauses == [(5, 1.2), (6, 0.8)]
    assert split_pauses("[laughs] no pauses here") == ("[laughs] no pauses here", [])
    wav = tmp_path / "read.wav"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", "sine=frequency=200:duration=1", "-ar", "48000", "-ac", "2",
                "-c:a", "pcm_s16le", str(wav)])
    words = [Word("a", 0.1, 0.3), Word("b", 0.5, 0.7)]
    shifted = insert_pauses(wav, words, [(1, 0.5)])  # between "a" and "b", at 0.4 s
    assert shifted == [Word("a", 0.1, 0.3), Word("b", 1.0, 1.2)]
    assert abs(ffmpeg.probe_duration(wav) - 1.5) < 0.02


def _read_with_floor(path: Path, floor_db=-50.0, seconds=3.0, rate=48000):
    """A stand-in clone read: two bursts of voice over a floor at `floor_db` (None: digital silence between them)."""
    import wave

    import numpy as np

    rng = np.random.RandomState(4)
    t = np.arange(int(seconds * rate)) / rate
    voice = 0.3 * np.sin(2 * np.pi * 140 * t) * (((t > 0.3) & (t < 1.1)) | ((t > 1.9) & (t < 2.7)))
    floor = 0.0 if floor_db is None else 10 ** (floor_db / 20) * rng.randn(len(t))
    x = np.clip((voice + floor) * 32767, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(x.tobytes())
    return x.astype("float64") / 32768


def _window_db(x, rate, start_s, end_s):
    import numpy as np

    seg = x[int(start_s * rate): int(end_s * rate)]
    return 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-12)


def test_a_pause_is_filled_with_the_reads_own_floor_and_joined_without_a_cliff(tmp_path):
    """He heard "weird dropoffs ... audible cliffs" where the artificial silences were: a step from the clone's floor to nothing."""
    import wave

    np = pytest.importorskip("numpy")
    wav = tmp_path / "read.wav"
    before = _read_with_floor(wav)
    words = [Word("a", 0.3, 1.1), Word("b", 1.9, 2.7)]
    shifted = insert_pauses(wav, words, [(1, 1.0)])  # in the gap, at 1.5 s
    assert shifted == [Word("a", 0.3, 1.1), Word("b", 2.9, 3.7)]
    with wave.open(str(wav), "rb") as wf:
        rate, frames = wf.getframerate(), wf.getnframes()
        after = np.frombuffer(wf.readframes(frames), dtype="<i2").astype("float64") / 32768
    assert frames == len(before) + 48000  # exactly the pause, nothing lost and nothing added at the seams
    floor = _window_db(before, rate, 1.2, 1.8)
    assert floor == pytest.approx(-50, abs=1.5)
    assert _window_db(after, rate, 1.6, 2.4) == pytest.approx(floor, abs=2.5)  # the pause carries the floor, not zeros
    steps = [_window_db(after, rate, 1.1 + 0.01 * i, 1.11 + 0.01 * i) for i in range(0, 180)]  # 10 ms windows across both seams
    assert max(steps) - min(steps) < 8  # no cliff; a zero fill would drop more than 30 dB
    # the words did not move
    assert np.allclose(after[: int(1.4 * rate)], before[: int(1.4 * rate)], atol=1e-4)
    assert np.allclose(after[int(2.9 * rate): int(3.7 * rate)], before[int(1.9 * rate): int(2.7 * rate)], atol=1e-4)


def test_the_fill_does_not_wander_when_the_reads_floor_does(tmp_path):
    """Round 5: one pause's floor read -31, -42, -54, -47, -42 dBFS in 200 ms, because the fill was drawn from windows 30 dB apart."""
    import wave

    np = pytest.importorskip("numpy")
    rate = 48000
    rng = np.random.RandomState(9)
    t = np.arange(int(4.0 * rate)) / rate
    voice = 0.3 * np.sin(2 * np.pi * 140 * t) * (((t > 0.3) & (t < 1.3)) | ((t > 2.2) & (t < 3.2)))
    level = np.where((np.arange(len(t)) // int(0.2 * rate)) % 2 == 0, -46.0, -62.0)  # the read's floor moves 16 dB every 200 ms
    x = np.clip((voice + 10 ** (level / 20) * rng.randn(len(t))) * 32767, -32768, 32767).astype("<i2")
    wav = tmp_path / "wander.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(x.tobytes())
    insert_pauses(wav, [Word("a", 0.3, 1.3), Word("b", 2.2, 3.2)], [(1, 1.5)])  # a 1.5 s pause at 1.75 s
    with wave.open(str(wav), "rb") as wf:
        after = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float64") / 32768
    body = [_window_db(after, rate, 1.9 + 0.05 * i, 1.95 + 0.05 * i) for i in range(0, 24)]  # inside the pause, 50 ms at a time
    assert max(body) - min(body) < 3  # one steady floor (the unfixed fill stepped by 16 dB)
    assert -64 < min(body) and max(body) < -44  # and it is the read's own floor, not zeros and not a tail


def _steps_around(after, rate, centre_s, span_s=0.012, hop_s=0.002):
    """The level, 2 ms at a time, around a seam; returns the largest step between neighbours."""
    import numpy as np

    lv = [_window_db(after, rate, centre_s - span_s + hop_s * i, centre_s - span_s + hop_s * (i + 1))
          for i in range(int(2 * span_s / hop_s))]
    return max(abs(b - a) for a, b in zip(lv, lv[1:]))


def test_words_that_touch_are_not_cut_with_a_step(tmp_path):
    """The aligner said two words met at 1.4 s, in the middle of continuous speech: the pause went in with a 37 dB step in
    2 ms at each end. A cliff that is not silence, and what he heard."""
    import wave

    np = pytest.importorskip("numpy")
    rate = 48000
    rng = np.random.RandomState(3)
    t = np.arange(int(3.0 * rate)) / rate
    voice = 0.2 * np.sin(2 * np.pi * 130 * t) * ((t > 0.2) & (t < 2.6)) * (0.7 + 0.3 * np.sin(2 * np.pi * 3 * t))
    x = np.clip((voice + 10 ** (-55 / 20) * rng.randn(len(t))) * 32767, -32768, 32767).astype("<i2")
    wav = tmp_path / "abut.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(x.tobytes())
    shifted = insert_pauses(wav, [Word("a", 0.2, 1.4), Word("b", 1.4, 2.6)], [(1, 0.8)])  # words touching: no gap at all
    assert shifted == [Word("a", 0.2, 1.4), Word("b", 2.2, 3.4)]
    with wave.open(str(wav), "rb") as wf:
        after = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float64") / 32768
    assert len(after) == len(x) + int(0.8 * rate)  # exactly the pause was added
    body = _window_db(after, rate, 1.6, 2.0)
    assert body < -45  # a pause: the floor, not speech
    starts = [c for c in np.arange(1.0, 1.9, 0.001) if _window_db(after, rate, c, c + 0.001) < -40]  # where the speech stopped
    stop = starts[0]
    assert _steps_around(after, rate, stop, span_s=0.06, hop_s=0.004) < 12  # it fades out over tens of ms, not in one step
    begin = [c for c in np.arange(2.0, 2.6, 0.001) if _window_db(after, rate, c, c + 0.001) > -40][0]
    assert _steps_around(after, rate, begin, span_s=0.04, hop_s=0.004) < 25  # and comes back in over 25 ms (a hard cut was 38 dB in 2 ms)


def test_a_pause_does_not_eat_the_end_of_a_word_that_runs_into_the_next(tmp_path):
    """"Cutting off some of my words like before they're fully pronounced. After the word of, after the word trying" (his
    01:15 and 01:19, EDT). In "of of" the /v/ of the first word runs straight into the vowel of the second, with no gap to cut
    in; the cut then falls in the weak /v/, 26 dB over the floor, and the speech used to be faded out over up to 60 ms before
    it and the next word in over up to 25 ms: the whole /v/ and the start of the vowel after the pause."""
    import wave

    np = pytest.importorskip("numpy")
    rate = 48000
    rng = np.random.RandomState(6)
    t = np.arange(int(2.0 * rate)) / rate
    env = np.zeros_like(t)
    env[(t >= 0.30) & (t < 0.42)] = 1.0          # the vowel of the first "of"
    env[(t >= 0.42) & (t < 0.49)] = 0.03         # its /v/: weak, 30 dB under the vowel, and it does not stop before the next word
    env[(t >= 0.49) & (t < 0.61)] = 1.0          # the vowel of the second "of", right behind it
    env[(t >= 0.61) & (t < 0.68)] = 0.03
    voice = 0.25 * np.sin(2 * np.pi * 140 * t) * env
    x = np.clip((voice + 10 ** (-62 / 20) * rng.randn(len(t))) * 32767, -32768, 32767).astype("<i2")
    wav = tmp_path / "of_of.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(x.tobytes())
    before = x.astype("float64") / 32768
    words = [Word("of", 0.30, 0.49), Word("of", 0.49, 0.68)]
    shifted = insert_pauses(wav, words, [(1, 1.5)])
    with wave.open(str(wav), "rb") as wf:
        after = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float64") / 32768
    # the first word keeps its weak /v/ apart from the last few ms before the cut (a 60 ms fade took all of it)
    assert _window_db(after, rate, 0.42, 0.465) == pytest.approx(_window_db(before, rate, 0.42, 0.465), abs=1.0)
    # and the second word comes back at full level within 10 ms of the end of the pause (a 25 ms fade-in was 5 dB down there)
    began = shifted[1].start
    assert _window_db(after, rate, began + 0.010, began + 0.040) == pytest.approx(_window_db(before, rate, 0.50, 0.53), abs=1.5)
    assert len(after) == len(x) + int(1.5 * rate)


def _of_of_what(tmp_path):
    """"... of of [a real gap] what": the first "of" runs into the second with its /v/ still 14 dB under the vowel (a cut
    there takes the end of the word), and the second is followed by 270 ms of floor before "what"."""
    import wave

    np = pytest.importorskip("numpy")
    rate = 48000
    rng = np.random.RandomState(9)
    t = np.arange(int(1.6 * rate)) / rate
    env = np.zeros_like(t)
    env[(t >= 0.30) & (t < 0.42)] = 1.0
    env[(t >= 0.42) & (t < 0.49)] = 0.2
    env[(t >= 0.49) & (t < 0.61)] = 1.0
    env[(t >= 0.61) & (t < 0.68)] = 0.2
    env[(t >= 0.95) & (t < 1.20)] = 1.0
    x = np.clip((0.25 * np.sin(2 * np.pi * 140 * t) * env + 10 ** (-62 / 20) * rng.randn(len(t))) * 32767, -32768, 32767).astype("<i2")
    wav = tmp_path / "ofofwhat.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(x.tobytes())
    return wav, [Word("of", 0.30, 0.49), Word("of", 0.49, 0.68), Word("what", 0.95, 1.20)], len(x), rate


def test_gaps_only_leaves_out_a_pause_that_would_cut_into_a_word(tmp_path):
    """Q17 (his 01:19 EDT): \"after the word of, after the word trying, it's fucked up, everything else is perfect\": the two pauses that
    landed in live audio. Q21, with only the pauses that land in real quiet, was \"perfect\"."""
    wav, words, n, rate = _of_of_what(tmp_path)
    report: dict = {}
    shifted = insert_pauses(wav, words, [(1, 2.0), (2, 1.0)], report=report, gaps_only=True)
    assert [d["after_words"] for d in report["kept"]] == [2] and [d["after_words"] for d in report["dropped"]] == [1]
    assert report["dropped"][0]["cut_dbfs"] > report["quiet_limit_dbfs"]  # the /v/ is -29 dBFS, the limit -39
    assert report["kept"][0]["s"] == 1.0
    # the word before the dropped pause is untouched, and only the pause that went in moved the words after it
    assert shifted[:2] == words[:2] and shifted[2] == Word("what", 1.95, 2.20)
    import wave

    with wave.open(str(wav), "rb") as wf:
        assert wf.getnframes() == n + int(1.0 * rate)


def test_gaps_only_can_move_a_pause_to_the_next_gap(tmp_path):
    wav, words, n, rate = _of_of_what(tmp_path)
    report: dict = {}
    shifted = insert_pauses(wav, words, [(1, 2.0)], report=report, gaps_only=True, snap=True)
    assert report["kept"] == [{"after_words": 2, "s": 2.0, "asked_after_words": 1}] and not report["dropped"]
    assert shifted[:2] == words[:2] and shifted[2] == Word("what", 2.95, 3.20)  # the pause came after the second "of", where there is a gap


def test_gaps_only_keeps_a_pause_at_the_very_start_or_end(tmp_path):
    wav, words, n, rate = _of_of_what(tmp_path)
    report: dict = {}
    insert_pauses(wav, words, [(0, 0.4), (3, 0.3)], report=report, gaps_only=True)
    assert [d["after_words"] for d in report["kept"]] == [0, 3] and not report["dropped"]


def test_reflow_puts_a_pause_inside_the_gap_as_silence_and_touches_no_word(tmp_path):
    """Q21, "perfect": the pause sits in the gap the clone left, silent (the room tone is what is heard in it), the fades stay
    in the gap and the words on either side are not scaled by a sample."""
    import wave

    np = pytest.importorskip("numpy")
    wav, words, n, rate = _of_of_what(tmp_path)
    with wave.open(str(wav), "rb") as wf:
        before = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").copy()
    report: dict = {}
    shifted = insert_pauses(wav, words, [(2, 1.0)], report=report, gaps_only=True, bed_db=-54.0)
    with wave.open(str(wav), "rb") as wf:
        after = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")
    assert len(after) == n + rate and shifted[:2] == words[:2] and shifted[2] == Word("what", 1.95, 2.20)
    cut = report["cuts"][0]
    assert report["method"] == "reflow" and 0.68 <= cut["at_s"] <= 0.95 and cut["gap_ms"] == 270  # in the gap between "of" and "what"
    start = round(cut["at_s"] * rate) - round(cut["fade_out_ms"] / 1000 * rate)
    # everything before the fade-out, "of of" whole, is the read itself, sample for sample
    assert (after[:start] == before[:start]).all() and start >= round(0.68 * rate) - 1
    zeros = np.flatnonzero(after[round(cut["at_s"] * rate): round(cut["at_s"] * rate) + rate] != 0)
    assert len(zeros) == 0  # a second of exact silence, at the place it was put
    # and "what" is the read itself again from where its fade-in ends (which is before it starts)
    resume = round(cut["at_s"] * rate) + rate + round(cut["fade_in_ms"] / 1000 * rate)
    assert (after[resume:] == before[round(cut["at_s"] * rate) + round(cut["fade_in_ms"] / 1000 * rate):]).all()
    assert cut["fade_out_ms"] <= 270 and cut["depth_db"] >= 6


def test_reflow_fades_end_under_the_room_tone(tmp_path):
    """The fade goes down only as far as it must: to `REFLOW_HEADROOM_DB` under the bed, from where the read stands."""
    import wave

    from noirstudio.voicenote import REFLOW_HEADROOM_DB

    np = pytest.importorskip("numpy")
    rate = 48000
    rng = np.random.RandomState(4)
    t = np.arange(int(2.0 * rate)) / rate
    env = np.zeros_like(t)
    env[(t >= 0.2) & (t < 0.6)] = 1.0
    env[(t >= 0.6) & (t < 0.75)] = np.exp(-(t[(t >= 0.6) & (t < 0.75)] - 0.6) / 0.03)  # a word dying away over its gap
    env[(t >= 1.2) & (t < 1.6)] = 1.0
    x = np.clip((0.25 * np.sin(2 * np.pi * 140 * t) * env + 10 ** (-60 / 20) * rng.randn(len(t))) * 32767, -32768, 32767).astype("<i2")
    wav = tmp_path / "decay.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(x.tobytes())
    report: dict = {}
    insert_pauses(wav, [Word("a", 0.2, 0.6), Word("b", 1.2, 1.6)], [(1, 0.8)], report=report, gaps_only=True, bed_db=-54.0)
    cut = report["cuts"][0]
    assert cut["cut_dbfs"] < -50 and 0.6 <= cut["at_s"] <= 1.2  # in the quiet after the decay
    assert cut["depth_db"] == pytest.approx(max(6.0, cut["cut_dbfs"] + 54.0 + REFLOW_HEADROOM_DB), abs=0.2)
    assert cut["fade_out_ms"] == pytest.approx(cut["depth_db"] / 0.4, abs=1.5) or cut["fade_out_ms"] < cut["depth_db"] / 0.4  # bounded by the gap


def test_a_pause_goes_in_after_the_words_tail_not_through_it(tmp_path):
    """The aligner put a word's end 140 ms before its sound had died away: the cut belongs where the sound has."""
    import wave

    np = pytest.importorskip("numpy")
    rate = 48000
    rng = np.random.RandomState(5)
    t = np.arange(int(3.0 * rate)) / rate
    env = ((t > 0.3) & (t < 1.1)).astype(float) + np.where((t >= 1.1) & (t < 1.25), np.linspace(1, 0, int((t >= 1.1).sum() and 0.15 * rate))[: int(((t >= 1.1) & (t < 1.25)).sum())] if False else 0.0, 0.0)
    tail = (t >= 1.1) & (t < 1.25)
    env[tail] = np.linspace(1.0, 0.0, tail.sum())  # the word's release, dying over 150 ms after its aligned end
    env += ((t > 1.9) & (t < 2.7))
    voice = 0.25 * np.sin(2 * np.pi * 140 * t) * env
    x = np.clip((voice + 10 ** (-52 / 20) * rng.randn(len(t))) * 32767, -32768, 32767).astype("<i2")
    wav = tmp_path / "tail.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(x.tobytes())
    insert_pauses(wav, [Word("a", 0.3, 1.1), Word("b", 1.9, 2.7)], [(1, 1.0)])  # nominal cut: the middle of the gap, 1.5 s
    with wave.open(str(wav), "rb") as wf:
        after = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float64") / 32768
    # the tail is all there (it dies away by itself over 1.1 to 1.25 s), and nothing after it is speech until the word b
    assert _window_db(after, rate, 1.10, 1.12) > -25
    assert _window_db(after, rate, 1.30, 1.40) < -45
    lv = [_window_db(after, rate, 1.0 + 0.004 * i, 1.004 + 0.004 * i) for i in range(0, 100)]
    assert max(abs(b - a) for a, b in zip(lv, lv[1:])) < 14  # no step anywhere across the release and the seam


def test_a_pause_at_the_very_start_or_end_of_a_read_is_fine(tmp_path):
    import wave

    np = pytest.importorskip("numpy")
    wav = tmp_path / "edges.wav"
    _read_with_floor(wav)
    n0 = wave.open(str(wav)).getnframes()
    words = [Word("a", 0.3, 1.1), Word("b", 1.9, 2.7)]
    shifted = insert_pauses(wav, words, [(0, 0.5), (2, 0.4)])  # before the first word, after the last
    assert wave.open(str(wav)).getnframes() == n0 + int(0.9 * 48000)
    assert shifted[0].start == pytest.approx(0.8) and shifted[1].end == pytest.approx(3.2, abs=0.01)
    # a read that begins in speech: the pause before it still comes in over a few ms, not as a bare splice
    rate = 48000
    speech = (np.sin(2 * np.pi * 140 * np.arange(rate) / rate) * 0.3 * 32767).astype("<i2")
    start = tmp_path / "start.wav"
    with wave.open(str(start), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(speech.tobytes())
    insert_pauses(start, [Word("a", 0.0, 1.0)], [(0, 0.3)])
    with wave.open(str(start), "rb") as wf:
        got = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float64") / 32768
    edge = int(0.3 * rate)
    assert abs(got[edge]) < 0.05 and abs(got[edge + 1]) < 0.05  # the first samples of the speech are faded, not full level
    assert np.abs(got[edge + int(0.010 * rate): edge + int(0.030 * rate)]).max() > 0.2  # and it is at full level by 10 to 30 ms


def test_a_long_pause_is_at_the_level_of_the_short_gaps_around_it(tmp_path):
    """The seams tool found the pauses of round 7 sat 6 dB under the short gaps between words; in his notes with a room the two
    are the same floor. The read here has a much quieter lead-in (-64 dBFS) than its gaps (-50): the fill follows the gaps."""
    import wave

    np = pytest.importorskip("numpy")
    rate = 48000
    rng = np.random.RandomState(8)
    t = np.arange(int(9.0 * rate)) / rate
    words, level = [], np.full(len(t), -50.0)
    level[t < 2.5] = -64.0  # the lead-in
    level[t > 6.7] = -64.0  # and the tail: more of the read is quiet than is gaps
    voice = np.zeros_like(t)
    at = 2.5
    for i in range(10):
        a, b = at, at + 0.25
        env = ((t >= a) & (t < b)).astype(float)
        tail = (t >= b) & (t < b + 0.07)  # and each word dies away over 70 ms, so a gap is never steady (the real clone's are not)
        env[tail] = np.exp(-(t[tail] - b) / 0.012)
        voice += 0.2 * np.sin(2 * np.pi * (120 + 6 * i) * t) * env
        words.append(Word(f"w{i}", round(a, 3), round(b, 3)))
        at = b + 0.16
    x = np.clip((voice + 10 ** (level / 20) * rng.randn(len(t))) * 32767, -32768, 32767).astype("<i2")
    wav = tmp_path / "gaps.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(x.tobytes())
    report: dict = {}
    shifted = insert_pauses(wav, words, [(5, 0.8)], report=report)  # after w4, in its 160 ms gap
    with wave.open(str(wav), "rb") as wf:
        after = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float64") / 32768
    # and the build says what it did: nine gaps, a target at the gaps' floor, a fill 2 dB short of it (its own windows sit at
    # -64 and it may lift them by 12), the level it ended at
    assert report["gaps_used"] == 9 and report["target_dbfs"] == pytest.approx(-50, abs=1.5)
    assert report["own_dbfs"] == pytest.approx(-64, abs=2) and report["short_db"] == pytest.approx(2, abs=1.5)
    assert report["fill_dbfs"] == report["level_dbfs"] == pytest.approx(-52, abs=1.5)
    w4 = shifted[4]
    inside = _window_db(after, rate, w4.end + 0.25, w4.end + 0.65)  # the middle of the inserted pause
    gap = _window_db(after, rate, words[1].end + 0.09, words[1].end + 0.15)  # an untouched gap, after the tail has died away
    assert gap == pytest.approx(-50, abs=2)
    assert abs(inside - gap) < 3  # one floor; a fill from the quiet lead-in would have sat 14 dB lower


def test_a_read_whose_floor_is_digital_silence_gets_silence_in_its_pause(tmp_path):
    import wave

    np = pytest.importorskip("numpy")
    wav = tmp_path / "read.wav"
    _read_with_floor(wav, floor_db=None)
    insert_pauses(wav, [Word("a", 0.3, 1.1), Word("b", 1.9, 2.7)], [(1, 1.0)])
    with wave.open(str(wav), "rb") as wf:
        after = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")
    assert not after[int(1.6 * 48000): int(2.4 * 48000)].any()


def test_stumbles_are_his_measured_rate_deterministic_and_leave_markers_alone():
    from noirstudio.voicenote import HIS_STUMBLES

    line = ("so I think we should probably just go with the first one, you know, and see what happens because the thing "
            "is that we need to decide by tomorrow and I don't want to wait any longer than that [pause 1.2] honestly "
            "it is what it is and that is really all there is to say about it for now okay") * 3
    assert stumbles(line, 0) == line and stumbles("too short", 5) == "too short"
    heavy = stumbles(line, 6)
    assert heavy == stumbles(line, 6) and stumbles(line, 6, seed=8) != heavy  # the same line and seed, the same stumbles
    assert "[pause 1.2]" in heavy and heavy.count("[pause 1.2]") == 3  # the markers pass through whole
    words = line.replace("[pause 1.2]", "").split()
    got = heavy.replace("[pause 1.2]", "").split()
    n = len(words)
    fillers = [w for w in got if w in ("uh", "um")]
    expected = 6 * HIS_STUMBLES["fillers_per_100"] * n / 100
    assert expected * 0.5 <= len(fillers) <= expected * 1.5 + 1
    added = len(got) - n
    total = 6 * sum(HIS_STUMBLES.values()) * n / 100
    assert total * 0.6 <= added <= total * 1.6 + 2  # fillers, repeated words and restarts together, at his rate x scale
    # only ever additions: take the inserted words out and his words are left, in order
    def plain(ws):
        out = []
        for w in ws:
            if w in ("uh", "um"):
                continue
            out.append(w.lower())
        return out

    def collapse(ws):  # repeats and restarts removed: a word said twice in a row, a pair said twice in a row
        ws = list(ws)
        changed = True
        while changed:
            changed = False
            for i in range(len(ws) - 1):
                if ws[i] == ws[i + 1]:
                    del ws[i + 1]
                    changed = True
                    break
            if changed:
                continue
            for i in range(len(ws) - 3):
                if ws[i: i + 2] == ws[i + 2: i + 4]:
                    del ws[i + 2: i + 4]
                    changed = True
                    break
        return ws

    assert collapse(plain(got)) == collapse(plain(words))


def test_asking_for_more_is_audible_on_a_short_line_and_a_restart_repeats_two_words():
    line = "all right another thing and this is a big deal to me you know how people back up their agents to their github just in case"
    n = len(line.split())
    for seed in range(6):
        out = stumbles(line, 2, seed=seed)
        assert len(out.split()) > n  # a 25-word line always gets something at twice his rate
    restarts = 0
    for seed in range(40):
        got = stumbles(line, 8, seed=seed).split()
        restarts += sum(1 for i in range(len(got) - 3) if got[i: i + 2] == got[i + 2: i + 4] and got[i] != got[i + 1])
    assert restarts >= 40  # "i don't i don't": two words said again; placed first, so a crowded line still gets them
    only = {"fillers_per_100": 0, "repeats_per_100": 0, "restarts_per_100": 12}
    for seed in range(6):  # restarts on their own: three on 26 words, each one two words said again, nothing else added
        got = stumbles(line, 1, seed=seed, habits=only).split()
        assert len(got) == n + 2 * int(12 * n / 100 + 0.5)
        assert all(w not in ("uh", "um") for w in got)


def test_um_is_asked_for_as_ummm_and_captioned_as_um():
    """Filler lab, 2026-09-30: "base um or" came back as "basem" (0.2 s, not voiced); "ummm" was a real filler in both takes."""
    assert clone_spelling("so um tell me, Um, and umm and ummm and umbrella and Umm...") == \
        "so ummm tell me, Ummm, and ummm and ummm and umbrella and Ummm..."
    assert plain_filler("so ummm tell me, Ummm, and umm and ummm. and Ummmm,") == "so um tell me, Um, and umm and um. and Um,"
    line = "it was a local model um or something, um, that is what he said"
    assert plain_filler(clone_spelling(line)) == line  # what is captioned is what was written
    assert clone_spelling("uh, so I mean the umpire") == "uh, so I mean the umpire"  # only "um" changes; "uh" and other words do not


def test_the_fillers_it_adds_are_always_um():
    """Filler lab 2 (60 clone reads, ten words before the filler): a written "ummm" was heard in 15 takes of 20, "uh" in 7."""
    line = ("we went over to the old house on the hill and looked at the whole thing again because it was the only way "
            "to be sure that nothing had been left behind in the cellar or the attic or the barn out back")
    added = set()
    for seed in range(60):
        added |= {w for w in stumbles(line, 4, seed=seed).split() if w in ("uh", "um")}
    assert added == {"um"}
    assert "uh" in stumbles("so we went uh over to the old house on the hill and looked at the whole thing again", 0.5)  # a written one stays


def test_a_line_that_already_stumbles_is_topped_up_not_doubled():
    """The episode scripts are written the way he talks ("uh…", "your— your"): --stumble must count those."""
    written = ("look I— I might get upset and knock over a chair, you know, during an episode of sadness and sleep fine "
               "but if I started, uh, pushing kittens to the floor whenever I got upset, um, that wouldn't sit right with me")
    n = len(written.split())
    for scale in (1, 2):
        for seed in range(8):
            got = stumbles(written, scale, seed=seed)
            added = len(got.split()) - n
            # he has 4.0 in 100 words: 3 already written (I I, uh, um) in 40 words is 7.5 per 100, so nothing is added at 1
            assert added == 0 if scale == 1 else 0 <= added <= 4
    bare = " ".join(["so we went over to the other room and looked at the whole thing again"] * 3)  # 42 plain words
    assert len(stumbles(bare, 2, seed=1).split()) > len(bare.split())  # the same rate on a bare line does add some


@pytest.fixture(scope="module")
def real_note(tmp_path_factory) -> Path:
    """One of his notes, stood in for: four bursts of speech over a steady room at about -50 dBFS, a second of room before the
    first and after the last (three stretches of room between them)."""
    path = tmp_path_factory.mktemp("real") / "real.ogg"
    speech = ("if(between(t,1.0,1.8)+between(t,2.6,3.6)+between(t,4.4,5.2)+between(t,5.8,6.4),"
              "(0.3*sin(2*PI*140*t)+0.2*sin(2*PI*280*t))*(0.55+0.45*sin(2*PI*3.5*t)),0)")
    ffmpeg.run(["-y", "-f", "lavfi", "-i", f"aevalsrc='{speech}':s=48000:d=7.5",
                "-f", "lavfi", "-i", "anoisesrc=d=7.5:c=brown:r=48000:a=0.02:seed=3",
                "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0[o]", "-map", "[o]",
                "-c:a", "libopus", "-b:a", "32k", str(path)])
    return path


def test_his_room_comes_from_a_real_note(clean, real_note, tmp_path):
    room = room_tone(real_note, tmp_path / "room.wav")
    assert room and room["stretches"] == 3 and room["dropped"] == 2 and room["seconds"] > 1.0  # its opening and closing are not used
    real = measure(real_note)
    style = NoteStyle(**{**matched(NoteStyle(), real).__dict__, "room_tone": room["path"]})
    render(clean, tmp_path / "rebuilt.ogg", style)
    rebuilt = measure(tmp_path / "rebuilt.ogg")
    assert abs(rebuilt["lufs"] - real["lufs"]) < 0.6 and abs(rebuilt["noise_db"] - real["noise_db"]) < 2


def test_cli_room_says_what_it_made_the_room_of(clean, real_note, tmp_path, capsys):
    out = tmp_path / "rebuilt.ogg"
    assert main(["voicenote", str(clean), str(out), "--room", str(real_note), "--noise-db", "-50"]) == 0
    err = capsys.readouterr().err
    assert "room: 3 stretches of real.ogg joined, 2 put aside" in err
    assert (tmp_path / "rebuilt.room.wav").exists() and out.exists()


def test_his_room_has_no_dropouts_at_its_joins_or_where_it_loops(tmp_path):
    """The room is looped under every pause, and in a pause it is all there is to hear: a join that dips (the stretches used to be
    faded out and in over 10 ms and joined bare: 10 to 12 dB, once a second) is a little cliff in the floor."""
    np = pytest.importorskip("numpy")
    real = tmp_path / "white.ogg"
    bursts = "+".join(f"between(t,{a},{a + 0.6})" for a in (0.3, 1.9, 3.5, 5.1, 6.7, 8.3))
    speech = f"if({bursts},(0.3*sin(2*PI*140*t)+0.2*sin(2*PI*280*t))*(0.55+0.45*sin(2*PI*3.5*t)),0)"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", f"aevalsrc='{speech}':s=48000:d=9.5",
                "-f", "lavfi", "-i", "anoisesrc=d=9.5:c=white:r=48000:a=0.01:seed=5",
                "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0[o]", "-map", "[o]",
                "-c:a", "libopus", "-b:a", "48k", str(real)])
    room = room_tone(real, tmp_path / "room.wav")
    assert room and room["stretches"] >= 5 and room["seconds"] > 3.0
    assert not list(tmp_path.glob("*.join.wav"))
    raw = subprocess.run([ffmpeg.ffmpeg_path(), "-loglevel", "error", "-stream_loop", "2", "-i", str(tmp_path / "room.wav"),
                          "-f", "f32le", "-ac", "1", "-ar", "16000", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype="<f4")
    n = 1 + (len(x) - 160) // 80  # 10 ms windows every 5 ms, three turns of the loop
    level = 20 * np.log10(np.sqrt((x[np.arange(160)[None, :] + 80 * np.arange(n)[:, None]] ** 2).mean(axis=1)) + 1e-9)
    assert len(x) / 16000 > 3 * room["seconds"] - 0.1
    # Opus-coded noise wanders up to 5 dB under its median in 10 ms windows; the bare joins went 12 to 13 dB under it
    assert np.median(level) - level.min() < 6.0
    assert level.max() - np.median(level) < 4.0


def test_a_notes_dead_opening_and_dead_patches_are_not_his_room(tmp_path):
    """The note the bed was built from opens with 29 ms of digital zeros and a second 10 dB under its room (a phone's noise
    suppression coming in), and once a turn of the loop that was a dip to near silence; Harriet found it in round 12."""
    np = pytest.importorskip("numpy")
    real = tmp_path / "opens_dead.ogg"
    bursts = "+".join(f"between(t,{a:.1f},{a + 0.6:.1f})" for a in (1.9 + 1.6 * i for i in range(10)))
    speech = f"if({bursts},(0.3*sin(2*PI*140*t)+0.2*sin(2*PI*280*t))*(0.55+0.45*sin(2*PI*3.5*t)),0)"
    # the room: nothing for 30 ms, 10 dB under until 0.9 s, a 0.3 s dead patch inside one pause, and zeros from 19.4 s on
    # (all of it under a tenth of the note, so that its quietest tenth is still the room)
    envelope = "if(lt(t,0.03),0,if(lt(t,0.9),0.3,if(between(t,4.3,4.6),0.03,if(gt(t,19.4),0,1))))"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", f"aevalsrc='{speech}':s=48000:d=20",
                "-f", "lavfi", "-i", "anoisesrc=d=20:c=white:r=48000:a=0.01:seed=5",
                "-filter_complex", f"[1:a]volume='{envelope}':eval=frame[n];[0:a][n]amix=inputs=2:normalize=0[o]",
                "-map", "[o]", "-c:a", "libopus", "-b:a", "48k", str(real)])
    room = room_tone(real, tmp_path / "room.wav")
    assert room and room["stretches"] == 8 and room["dropped"] == 3  # the opening, the pause with the dead patch, the closing
    raw = subprocess.run([ffmpeg.ffmpeg_path(), "-loglevel", "error", "-stream_loop", "2", "-i", str(tmp_path / "room.wav"),
                          "-f", "f32le", "-ac", "1", "-ar", "16000", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype="<f4")
    n = 1 + (len(x) - 160) // 80
    level = 20 * np.log10(np.sqrt((x[np.arange(160)[None, :] + 80 * np.arange(n)[:, None]] ** 2).mean(axis=1)) + 1e-9)
    assert level.min() > np.median(level) - 6.0  # not a window of the dead opening, nor of the dead patch, nor of the zeros


def test_a_noise_suppressed_note_gives_no_room_and_keeps_ours(tmp_path):
    gated = tmp_path / "gated.ogg"
    speech = "if(between(t,0.3,1.2),0.3*sin(2*PI*140*t),0)"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", f"aevalsrc='{speech}':s=48000:d=2", "-c:a", "libopus", str(gated)])
    assert room_tone(gated, tmp_path / "room.wav") is None
    style = matched(NoteStyle(), {"lufs": -25.2, "noise_db": -95.4, "kbps": 26})
    assert (style.lufs, style.noise_db, style.kbps) == (-25.2, NoteStyle().noise_db, 26)


def test_cli_say_puts_his_pauses_in(clean, tmp_path, monkeypatch):
    calls = []

    def fake_send(self, method, path, data, content_type, accept, query=""):
        calls.append((path, data))
        if path == "/v1/forced-alignment":
            return json.dumps({"words": [{"text": "Say", "start": 0.1, "end": 0.3}, {"text": "it…", "start": 0.3, "end": 0.4},
                                         {"text": "for", "start": 0.4, "end": 0.6},
                                         {"text": "me.", "start": 0.6, "end": 0.9}]}).encode()
        return clean.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    out = tmp_path / "note.ogg"
    assert main(["voicenote", "--say", "Say it [pause 1] for me.", str(out), "--anywhere"]) == 0  # the fake read has no real gaps
    assert json.loads(calls[0][1])["text"] == "Say it, for me."  # the clone never sees the marker; rough 2 trails off in a comma
    assert main(["voicenote", "--say", "Say it [pause 1] for me.", str(out), "--rough", "0", "--anywhere"]) == 0
    assert json.loads(calls[2][1])["text"] == "Say it… for me."  # the clean read trails off in an ellipsis
    words = json.loads((tmp_path / "note.words.json").read_text(encoding="utf-8"))
    assert words["pauses"] == [{"after_words": 2, "s": 1.0}]
    assert words["fill"]["method"] == "reflow" and words["fill"]["cuts"][0]["after_words"] == 2  # the build's own record of where it went
    assert words["words"][2] == {"text": "for", "start": 1.75, "end": 1.95}  # 0.4 + 1.0 pause + 0.35 lead
    assert abs(ffmpeg.probe_duration(out) - (0.35 + 3.0 + 0.5)) < 0.1


def test_cli_puts_pauses_only_where_the_clone_left_a_gap(tmp_path, monkeypatch, capsys):
    wav, words, n, rate = _of_of_what(tmp_path)

    def fake_send(self, method, path, data, content_type, accept, query=""):
        if path == "/v1/forced-alignment":
            return json.dumps({"words": [{"text": w.text, "start": w.start, "end": w.end} for w in words]}).encode()
        return wav.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)

    def build(name, *flags):
        out = tmp_path / f"{name}.ogg"
        assert main(["voicenote", "--say", "Of [pause 2] of what", str(out), "--rough", "0", *flags]) == 0
        return json.loads((tmp_path / f"{name}.words.json").read_text(encoding="utf-8")), capsys.readouterr().err

    left_out, err = build("default")  # the default: the pause after the first "of" would cut into its /v/, so it is left out
    assert left_out["pauses"] == [] and "was left out" in err and "the clone left no gap" in err
    assert left_out["words"][2]["start"] == pytest.approx(0.35 + 0.95, abs=0.01)  # nothing moved
    moved, err = build("snap", "--snap")  # or moved to the gap after the second one
    assert moved["pauses"] == [{"after_words": 2, "s": 2.0}] and "went in after word 2" in err
    assert moved["words"][2]["start"] == pytest.approx(0.35 + 0.95 + 2.0, abs=0.01)
    anywhere, err = build("anywhere", "--anywhere")  # and asked for anywhere, it goes in where it was asked for
    assert anywhere["pauses"] == [{"after_words": 1, "s": 2.0}] and "left out" not in err
    assert anywhere["fill"]["cuts"][0]["cut_dbfs"] > anywhere["fill"]["quiet_limit_dbfs"]  # cut in live audio, and the build's own record says so


# --- "too perfect, too dynamic, too articulate" -----------------------------------------------

V3_CHAIN = ("aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,highpass=f=100:poles=2,highpass=f=100:poles=2,"
            "lowpass=f=8000:poles=2,lowpass=f=8000:poles=2,equalizer=f=250:t=q:w=1:g=-2,equalizer=f=2800:t=q:w=1.2:g=1.5,"
            "highshelf=f=6000:g=-2,aecho=0.9:0.9:11|23:0.22|0.12,acompressor=threshold=-24dB:ratio=3:attack=5:release=90:makeup=2")


def test_rough_zero_is_the_note_v3_shipped():
    assert voice_chain(NoteStyle(rough=0)) == V3_CHAIN  # the baseline to compare every other level against
    assert NoteStyle(rough=4).problems() and not NoteStyle(rough=3).problems()


def test_roughen_writes_a_line_the_way_he_says_it():
    line = "I mean— we wrote a whole paper on this… but, you know what? I want to keep it! [pause 0.6] I'm going to. [laughs]"
    assert roughen(line, 0) == line
    one = roughen(line, 1)
    assert "—" not in one and "…" not in one and "!" not in one and "what?" not in one
    assert "I mean, we wrote" in one and "on this, but" in one and "what, I want to keep it." in one
    assert "[pause 0.6]" in one and "[laughs]" in one  # markers and delivery tags pass through
    two = roughen(line, 2)
    assert "y'know" in two and "I wanna keep it" in two and "I'm gonna" in two
    three = roughen("First thing. Second thing. Third?", 3)
    assert three == "First thing, Second thing, Third?"  # nothing falls at a full stop; a final question stays
    assert roughen("Wait…", 2) == "Wait"  # trailing off stays unpunctuated
    assert roughen("Going to be fine. Kind of.", 2) == "Gonna be fine. Kinda."


@pytest.fixture(scope="module")
def sibilant(tmp_path_factory) -> Path:
    """A voice with a level swing and 'ess' hiss bursts at 5-9.5 kHz: what a crisp read has and a lazy one doesn't."""
    path = tmp_path_factory.mktemp("sib") / "sib.wav"
    voiced = ("(0.3*sin(2*PI*140*t)+0.2*sin(2*PI*280*t)+0.1*sin(2*PI*420*t)+0.06*sin(2*PI*2800*t))"
              "*(0.30+0.70*abs(sin(2*PI*1.7*t)))")
    ffmpeg.run(["-y", "-f", "lavfi", "-i", f"aevalsrc='{voiced}':s=44100:d=4:c=mono",
                "-f", "lavfi", "-i", "anoisesrc=d=4:c=white:r=44100:a=0.35",
                "-filter_complex", "[1:a]highpass=f=5000,lowpass=f=9500,volume='if(lt(mod(t,0.6),0.12),1,0)':eval=frame[h];"
                "[0:a][h]amix=inputs=2:normalize=0,aformat=channel_layouts=stereo[o]",
                "-map", "[o]", "-c:a", "pcm_s16le", str(path)])
    return path


def test_each_rough_step_softens_the_top_end_and_holds_his_level(sibilant, tmp_path):
    top_end = []
    for rough in range(4):
        out = tmp_path / f"r{rough}.wav"
        report = render(sibilant, out, NoteStyle(rough=rough))
        assert abs(report["lufs"] + 22) < 0.6  # softer, not louder or quieter
        air = "highpass=f=5000,highpass=f=5000"
        top_end.append(_rms(out, air) - _rms(out))
    assert top_end == sorted(top_end, reverse=True)  # every step is less crisp than the one before
    assert top_end[2] < top_end[0] - 6  # the default is at least 6 dB softer above 5 kHz than the v3 note


def test_cli_rough_and_stability_reach_the_clone(clean, tmp_path, monkeypatch):
    calls = []

    def fake_send(self, method, path, data, content_type, accept, query=""):
        calls.append((path, data))
        if path == "/v1/forced-alignment":
            return json.dumps({"words": [{"text": "w", "start": 0.1, "end": 0.9}]}).encode()
        return clean.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    out = tmp_path / "n.ogg"
    said = "I want to go… you know? It's going to be fine!"
    assert main(["voicenote", "--say", said, str(out), "--rough", "3", "--stability", "0.95"]) == 0
    sent = json.loads(calls[0][1])
    assert sent["voice_settings"]["stability"] == 0.95
    assert sent["text"] == "I wanna go, y'know, It's gonna be fine."
    words = json.loads((tmp_path / "n.words.json").read_text(encoding="utf-8"))
    assert (words["said"], words["rough"], words["stability"]) == (said, 3, 0.95)  # the record of what was read, and how
    assert main(["voicenote", "--say", said, str(out), "--rough", "0", "--stability", "0.5"]) == 0
    assert json.loads(calls[2][1])["text"] == said  # rough 0 sends the line exactly as written


# --- how he stops to think ---------------------------------------------------------------------

def _words(n, step=0.35, length=0.32):
    return [Word(f"w{i}", round(i * step, 3), round(i * step + length, 3)) for i in range(n)]


def test_hesitations_land_on_his_measured_rate_and_length():
    words = _words(180)  # 63 s of speech, with 0.03 s between the words
    line = " ".join("word," if i % 7 == 6 else "word" for i in range(180))
    got = hesitations(line, words, seed=3)
    minutes = (words[-1].end - words[0].start) / 60
    assert len(got) / minutes == pytest.approx(17, rel=0.2)  # about 17 a minute
    lengths = sorted(s for _, s in got)
    assert 0.5 < lengths[len(lengths) // 2] < 1.1  # the median is near his 0.85 s, less the gap the clone left
    assert max(lengths) <= 3.0 and min(lengths) >= 0.1
    ks = [k for k, _ in got]
    assert ks == sorted(ks) and all(2 <= k <= len(words) - 2 for k in ks)  # never at the edges
    assert all(b - a >= 3 for a, b in zip(ks, ks[1:]))  # never bunched


def test_hesitations_prefer_the_places_a_person_stops():
    words = _words(200)
    line = " ".join("word," if i % 8 == 7 else "word" for i in range(200))  # a comma after every 8th word
    after_comma = sum(1 for seed in range(12) for k, _ in hesitations(line, words, seed=seed) if k % 8 == 0)
    total = sum(len(hesitations(line, words, seed=seed)) for seed in range(12))
    assert after_comma / total > 0.5  # a comma is 1 boundary in 8, and 3 in 4 pauses follow one
    # with no punctuation to go on, a breath the clone already drew is where it goes
    gappy = [Word(f"w{i}", i * 0.35 + (0.4 if i >= 60 else 0), i * 0.35 + 0.32 + (0.4 if i >= 60 else 0)) for i in range(120)]
    plain = " ".join("word" for _ in range(120))
    picks = [k for seed in range(10) for k, _ in hesitations(plain, gappy, seed=seed)]
    assert sum(1 for k in picks if k == 60) >= 6  # the one gap in the read gets picked almost every time


def test_hesitations_are_repeatable_and_count_the_ones_already_written():
    words = _words(120)
    line = " ".join(["word"] * 120)
    assert hesitations(line, words, seed=1) == hesitations(line, words, seed=1)
    assert hesitations(line, words, seed=1) != hesitations(line, words, seed=2)
    assert hesitations(line, words, scale=0) == []
    assert hesitations(line, _words(6)) == []  # a short line is left alone
    plain = hesitations(line, words, seed=1)
    marked = [(k, 1.0) for k in range(10, 110, 10)]  # ten written pauses already cover his rate for 42 s
    extra = hesitations(line, words, explicit=marked, seed=1)
    assert len(extra) < len(plain)
    assert all(abs(k - m) > 2 for k, _ in extra for m, _ in marked)  # and none sits on top of a written one
    assert len(hesitations(line, words, scale=2, seed=1)) > 1.6 * len(plain)


def test_cli_hesitate_adds_his_pauses_and_marks_them(clean, tmp_path, monkeypatch):
    text = "so uh I think, like, we should probably just go with the first one, you know, and see what happens, right?"
    n = len(text.split())
    aligned = [{"text": w, "start": round(0.1 + i * 0.3, 3), "end": round(0.1 + i * 0.3 + 0.27, 3)}
               for i, w in enumerate(text.split())]

    def fake_send(self, method, path, data, content_type, accept, query=""):
        if path == "/v1/forced-alignment":
            return json.dumps({"words": aligned}).encode()
        return clean.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    out = tmp_path / "note.ogg"
    assert main(["voicenote", "--say", text, str(out), "--rough", "0"]) == 0
    plain = json.loads((tmp_path / "note.words.json").read_text(encoding="utf-8"))
    assert plain["pauses"] == []
    assert main(["voicenote", "--say", text, str(out), "--rough", "0", "--hesitate", "2", "--anywhere"]) == 0
    got = json.loads((tmp_path / "note.words.json").read_text(encoding="utf-8"))
    assert got["pauses"] and all(p["auto"] for p in got["pauses"])
    added = sum(p["s"] for p in got["pauses"])
    assert got["words"][-1]["end"] == pytest.approx(plain["words"][-1]["end"] + added, abs=0.02)  # the captions moved with them
    assert n == len(got["words"])


def test_rawify_writes_a_line_the_way_his_transcripts_read():
    assert rawify("Um, I— I don't know. [pause 1.2] Maybe... yeah!") == "um i i don't know [pause 1.2] maybe yeah"
    assert rawify("You know what? I refuse to change your name — honestly.") == "you know what i refuse to change your name honestly"
    assert rawify("[quietly] Well-known, isn't it?") == "[quietly] well-known isn't it"  # apostrophes, inner hyphens and tags stay
    line, pauses = split_pauses(rawify("So, uh, I mean... [pause 0.5] it works."), trail=",")
    assert line == "so uh i mean, it works" and pauses == [(4, 0.5)]


def test_cli_raw_sends_the_clone_his_kind_of_line(clean, tmp_path, monkeypatch):
    sent = []

    def fake_send(self, method, path, data, content_type, accept, query=""):
        if path == "/v1/forced-alignment":
            return json.dumps({"words": [{"text": "so", "start": 0.1, "end": 0.3}]}).encode()
        sent.append(json.loads(data)["text"])
        return clean.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    assert main(["voicenote", "--say", "So, uh, I think... we should go!", str(tmp_path / "a.ogg"), "--raw"]) == 0
    assert sent[-1] == "so uh i think we should go"


def test_cli_raw_keeps_the_scripts_own_words_on_the_captions(clean, tmp_path, monkeypatch):
    text = "So, uh, I think... we should go — now!"
    tokens = [t for t in text.split() if any(c.isalnum() for c in t)]  # the dash on its own is not a word

    def fake_send(self, method, path, data, content_type, accept, query=""):
        if path == "/v1/forced-alignment":  # the alignment hears the run-on
            said = "so uh i think we should go now".split()
            return json.dumps({"words": [{"text": w, "start": round(0.1 + i * 0.3, 3), "end": round(0.1 + i * 0.3 + 0.25, 3)}
                                         for i, w in enumerate(said)]}).encode()
        return clean.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    out = tmp_path / "b.ogg"
    assert main(["voicenote", "--say", text, str(out), "--raw"]) == 0
    got = json.loads((tmp_path / "b.words.json").read_text(encoding="utf-8"))
    assert [w["text"] for w in got["words"]] == tokens  # "So," "uh," "I" "think..." "we" "should" "go" "now!"
    assert got["read"] == "so uh i think we should go now"
    assert got["words"][3]["start"] == pytest.approx(0.1 + 3 * 0.3 + 0.35)  # the timings are the alignment's, plus the lead-in


def test_cli_raw_still_places_pauses_by_the_scripts_punctuation(clean, tmp_path, monkeypatch):
    import noirstudio.voicenote as vn

    text = "So, uh, I think we should probably just go with the first one, you know, and see what happens, right?"
    said = "so uh i think we should probably just go with the first one you know and see what happens right".split()
    seen = []
    real = vn.hesitations

    def spy(line, words, explicit=(), scale=1.0, seed=7, habits=None):
        seen.append(line)
        return real(line, words, explicit, scale, seed, habits)

    def fake_send(self, method, path, data, content_type, accept, query=""):
        if path == "/v1/forced-alignment":
            return json.dumps({"words": [{"text": w, "start": round(0.1 + i * 0.3, 3), "end": round(0.1 + i * 0.3 + 0.25, 3)}
                                         for i, w in enumerate(said)]}).encode()
        return clean.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    monkeypatch.setattr(vn, "hesitations", spy)
    assert main(["voicenote", "--say", text, str(tmp_path / "c.ogg"), "--raw", "--hesitate", "1"]) == 0
    assert seen == [text]  # the commas reach the pause-placer even though the clone never sees them
