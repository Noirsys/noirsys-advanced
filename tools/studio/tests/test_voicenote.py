"""His lost voice notes, rebuilt: a clean read in, a phone voice note out (Opus, room tone, his level)."""

import json
import re
from pathlib import Path

import pytest

from noirstudio import ffmpeg
from noirstudio.cli import main
from noirstudio.voice import ElevenLabsVoice
from noirstudio.voicenote import HIS_VOICE, NoteStyle, VoiceNoteError, loudness, matched, measure, render

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
    assert abs(loudness(out) + 18) < 0.6 and report["lufs"] == pytest.approx(-18, abs=0.6)
    assert -54 < _rms(out, "atrim=0.05:0.3") < -46  # room tone before he speaks, not digital silence
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
    assert "room tone -50.0 dBFS" in capsys.readouterr().out
    assert main(["voicenote", "--say", "[laughing] Say it for me.", str(out)]) == 1  # no tags on his lines
    assert len(calls) == 2  # refused before anything was sent


def test_cli_filter_and_measure(clean, tmp_path, capsys):
    out = tmp_path / "note.ogg"
    assert main(["voicenote", str(clean), str(out), "--lufs", "-20", "--no-room", "--kbps", "32"]) == 0
    assert main(["voicenote", "--measure", str(out)]) == 0
    printed = capsys.readouterr().out
    read = [float(x) for x in re.findall(r"(-\d+\.\d) LUFS", printed)]
    assert len(read) == 2 and all(abs(x + 20) < 0.6 for x in read) and "opus" in printed
    assert main(["voicenote", str(clean)]) == 1  # IN needs an OUT
