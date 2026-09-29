"""His lost voice notes, rebuilt: a clean read in, a phone voice note out (Opus, room tone, his level)."""

import json
import re
from pathlib import Path

import pytest

from noirstudio import ffmpeg
from noirstudio.cli import main
from noirstudio.captions import Word
from noirstudio.voice import ElevenLabsVoice
from noirstudio.voicenote import (HIS_VOICE, NoteStyle, VoiceNoteError, insert_pauses, loudness, matched, measure,
                                  render, room_tone, split_pauses)

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


@pytest.fixture(scope="module")
def real_note(tmp_path_factory) -> Path:
    """One of his notes, stood in for: two bursts of speech over a steady room at about -50 dBFS."""
    path = tmp_path_factory.mktemp("real") / "real.ogg"
    speech = ("if(between(t,0.3,1.2)+between(t,2.0,3.2),"
              "(0.3*sin(2*PI*140*t)+0.2*sin(2*PI*280*t))*(0.55+0.45*sin(2*PI*3.5*t)),0)")
    ffmpeg.run(["-y", "-f", "lavfi", "-i", f"aevalsrc='{speech}':s=48000:d=4",
                "-f", "lavfi", "-i", "anoisesrc=d=4:c=brown:r=48000:a=0.02:seed=3",
                "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0[o]", "-map", "[o]",
                "-c:a", "libopus", "-b:a", "32k", str(path)])
    return path


def test_his_room_comes_from_a_real_note(clean, real_note, tmp_path):
    room = room_tone(real_note, tmp_path / "room.wav")
    assert room and room["stretches"] == 3 and room["seconds"] > 1.0
    real = measure(real_note)
    style = NoteStyle(**{**matched(NoteStyle(), real).__dict__, "room_tone": room["path"]})
    render(clean, tmp_path / "rebuilt.ogg", style)
    rebuilt = measure(tmp_path / "rebuilt.ogg")
    assert abs(rebuilt["lufs"] - real["lufs"]) < 0.6 and abs(rebuilt["noise_db"] - real["noise_db"]) < 2


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
    assert main(["voicenote", "--say", "Say it [pause 1] for me.", str(out)]) == 0
    assert json.loads(calls[0][1])["text"] == "Say it… for me."  # the clone never sees the marker
    words = json.loads((tmp_path / "note.words.json").read_text(encoding="utf-8"))
    assert words["pauses"] == [{"after_words": 2, "s": 1.0}]
    assert words["words"][2] == {"text": "for", "start": 1.75, "end": 1.95}  # 0.4 + 1.0 pause + 0.35 lead
    assert abs(ffmpeg.probe_duration(out) - (0.35 + 3.0 + 0.5)) < 0.1
