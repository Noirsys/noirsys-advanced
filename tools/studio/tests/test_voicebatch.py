"""`voicenote --batch`: a manifest of his lines, built with one recipe, resumable, stopped by a refused account."""

import json
from pathlib import Path

import pytest

from noirstudio import ffmpeg
from noirstudio.cli import main
from noirstudio.voice import ElevenLabsVoice, VoiceError
from noirstudio.voicebatch import BatchError, load_manifest

SPEECHY = ("(0.3*sin(2*PI*140*t)+0.2*sin(2*PI*280*t)+0.1*sin(2*PI*420*t)+0.06*sin(2*PI*2800*t)"
           "+0.06*sin(2*PI*10000*t))*(0.55+0.45*sin(2*PI*3.5*t))")
ALIGNED = {"words": [{"text": "Say", "start": 0.1, "end": 0.3}, {"text": "it", "start": 0.3, "end": 0.4},
                     {"text": "for", "start": 0.4, "end": 0.6}, {"text": "me.", "start": 0.6, "end": 0.9}]}


@pytest.fixture(scope="module")
def clean(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("batch") / "clean.wav"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", f"aevalsrc='{SPEECHY}':s=44100:d=2", "-ac", "2", "-c:a", "pcm_s16le", str(path)])
    return path


def _manifest(tmp_path, lines=None):
    path = tmp_path / "lines.json"
    path.write_text(json.dumps({"lines": lines or [{"id": "a", "say": "Say it for me."},
                                                   {"id": "b", "say": "Tell it to me."}]}), encoding="utf-8")
    return path


def _clone(monkeypatch, clean, refuse_on=None):
    """The clone answers with `clean`; `refuse_on` is the number of the read (1, 2, ...) that the account refuses."""
    reads = []

    def fake_send(self, method, path, data, content_type, accept, query=""):
        if path == "/v1/forced-alignment":
            return json.dumps(ALIGNED).encode()
        reads.append(json.loads(data)["text"])
        if refuse_on == len(reads):
            raise VoiceError(f"ElevenLabs POST {path} -> HTTP 401: payment_required: a failed or incomplete payment")
        return clean.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    return reads


def test_the_manifest_is_checked(tmp_path):
    lines = tmp_path / "m.json"
    lines.write_text('{"lines": [{"id": "a", "say": "Hi."}, {"id": "b", "say": "Yo."}]}', encoding="utf-8")
    assert [r["id"] for r in load_manifest(lines)] == ["a", "b"]
    for bad, message in (('{"lines": []}', "needs"), ("not json", "cannot read"),
                         ('{"lines": [{"id": "a"}]}', "needs an"), ('{"lines": [{"id": "a", "say": "  "}]}', "needs an"),
                         ('{"lines": [{"id": "a b", "say": "Hi."}]}', "file name"),
                         ('{"lines": [{"id": "a", "say": "Hi."}, {"id": "a", "say": "Yo."}]}', "twice")):
        lines.write_text(bad, encoding="utf-8")
        with pytest.raises(BatchError, match=message):
            load_manifest(lines)
    with pytest.raises(BatchError, match="cannot read"):
        load_manifest(tmp_path / "missing.json")


def test_a_batch_builds_every_line_and_keeps_every_read(clean, tmp_path, monkeypatch, capsys):
    reads = _clone(monkeypatch, clean)
    out = tmp_path / "v4"
    assert main(["voicenote", "--batch", str(_manifest(tmp_path)), str(out), "--no-room"]) == 0
    assert reads == ["Say it for me.", "Tell it to me."]
    for name in ("a", "b"):  # the note, its captions, the read as the clone made it (no swing was asked for), and the log
        for ext in (".ogg", ".words.json", ".unswung.wav", ".out", ".rc"):
            assert (out / (name + ext)).exists(), name + ext
        assert (out / (name + ".rc")).read_text(encoding="utf-8") == "0"
    assert json.loads((out / "b.words.json").read_text(encoding="utf-8"))["said"] == "Tell it to me."
    printed = capsys.readouterr().out
    assert "a: built in" in printed and "b: built in" in printed and "2 built, 0 skipped (already there), 0 failed" in printed


def test_a_batch_is_resumable_and_can_take_a_line_again(clean, tmp_path, monkeypatch, capsys):
    reads = _clone(monkeypatch, clean)
    out, manifest = tmp_path / "v4", _manifest(tmp_path)
    assert main(["voicenote", "--batch", str(manifest), str(out), "--no-room"]) == 0
    assert main(["voicenote", "--batch", str(manifest), str(out), "--no-room"]) == 0
    assert len(reads) == 2 and "a: already built, skipped" in capsys.readouterr().out  # nothing was asked of the clone twice
    assert main(["voicenote", "--batch", str(manifest), str(out), "--no-room", "--only", "b", "--force"]) == 0
    assert reads[2:] == ["Tell it to me."]
    assert main(["voicenote", "--batch", str(manifest), str(out), "--no-room", "--only", "a", "--suffix", "-2"]) == 0
    assert (out / "a-2.ogg").exists() and not (out / "b-2.ogg").exists() and reads[3:] == ["Say it for me."]


def test_a_batch_stops_when_the_account_refuses_a_read(clean, tmp_path, monkeypatch, capsys):
    lines = [{"id": n, "say": "Say it for me."} for n in ("a", "b", "c")]
    reads = _clone(monkeypatch, clean, refuse_on=2)
    out, manifest = tmp_path / "v4", _manifest(tmp_path, lines)
    assert main(["voicenote", "--batch", str(manifest), str(out), "--no-room"]) == 2
    printed = capsys.readouterr().out
    assert len(reads) == 2 and (out / "a.ogg").exists() and not (out / "b.ogg").exists() and not (out / "c.ogg").exists()
    assert "b: FAILED" in printed and "payment_required" in printed and "STOPPED: the account refused a read" in printed
    assert (out / "b.rc").read_text(encoding="utf-8") == "2" and "payment_required" in (out / "b.out").read_text(encoding="utf-8")
    # when it answers again, the same command builds only what is missing
    reads.clear()
    _clone(monkeypatch, clean)
    assert main(["voicenote", "--batch", str(manifest), str(out), "--no-room"]) == 0
    assert (out / "b.ogg").exists() and (out / "c.ogg").exists()


def test_a_line_that_fails_for_another_reason_does_not_end_the_batch(clean, tmp_path, monkeypatch, capsys):
    reads = _clone(monkeypatch, clean)
    lines = [{"id": "a", "say": "Say it for me."}, {"id": "b", "say": "Tell it to me."}]
    original = ElevenLabsVoice._send

    def broken_first(self, method, path, data, content_type, accept, query=""):
        if path != "/v1/forced-alignment" and json.loads(data)["text"] == "Say it for me.":
            raise VoiceError("ElevenLabs POST /v1/text-to-speech/x -> HTTP 400: text too short")
        return original(self, method, path, data, content_type, accept, query)

    monkeypatch.setattr(ElevenLabsVoice, "_send", broken_first)
    assert main(["voicenote", "--batch", str(_manifest(tmp_path, lines)), str(tmp_path / "v4"), "--no-room"]) == 2
    printed = capsys.readouterr().out
    assert "a: FAILED" in printed and "STOPPED" not in printed and (tmp_path / "v4" / "b.ogg").exists()
    assert "1 built, 0 skipped (already there), 1 failed: a" in printed and reads == ["Tell it to me."]


def test_the_report_says_which_pauses_went_in_and_which_were_left_out(clean, tmp_path, monkeypatch, capsys):
    pytest.importorskip("numpy")
    _clone(monkeypatch, clean)
    lines = [{"id": "a", "say": "Say it [pause 0.5] for me."}, {"id": "b", "say": "Tell it to me. [pause 0.4]"},
             {"id": "c", "say": "Never built."}]
    out, manifest = tmp_path / "v4", _manifest(tmp_path, lines)
    assert main(["voicenote", "--batch", str(manifest), str(out), "--no-room", "--only", "a,b"]) == 0
    capsys.readouterr()
    assert main(["voicenote", "--batch", str(manifest), str(out), "--report"]) == 0
    printed = capsys.readouterr().out
    assert "2 of 3 lines built; 1 of 2 pauses asked for went in" in printed  # the read has no gap after "it"; the end is free
    assert "a: the pause after word 2 (0.5 s) was left out" in printed and "c" in printed and "not built" in printed
    assert not (out / "c.ogg").exists()  # a report builds nothing


def test_a_batch_is_refused_where_it_makes_no_sense(clean, tmp_path, monkeypatch, capsys):
    reads = _clone(monkeypatch, clean)
    out, manifest = tmp_path / "v4", _manifest(tmp_path)
    assert main(["voicenote", "--batch", str(manifest), str(out), "--say", "Hi."]) == 1
    assert main(["voicenote", "--batch", str(manifest), str(out), "--reuse", "x"]) == 1
    assert main(["voicenote", "--batch", str(manifest), str(out), str(out / "again")]) == 1
    assert main(["voicenote", "--batch", str(manifest), str(out), "--only", "nope"]) == 1
    assert main(["voicenote", "--batch", str(tmp_path / "missing.json"), str(out)]) == 1
    assert main(["voicenote", "--say", "Hi.", str(out / "x.ogg"), "--force"]) == 1  # --force is a batch option
    (tmp_path / "a-file").write_text("x", encoding="utf-8")
    assert main(["voicenote", "--batch", str(manifest), str(tmp_path / "a-file")]) == 1  # OUTDIR is a file
    assert reads == [] and not out.exists()
    err = capsys.readouterr()
    assert "not in the manifest: nope" in err.out and "go with --batch" in err.err


def test_a_reuse_needs_no_swing_because_every_read_is_kept(clean, tmp_path, monkeypatch):
    """A build that asked the clone keeps the read whatever it did to it next, so a plain build can be run again for free."""
    reads = _clone(monkeypatch, clean)
    first = tmp_path / "first.ogg"
    assert main(["voicenote", "--say", "Say it for me.", str(first), "--no-room"]) == 0
    assert (tmp_path / "first.unswung.wav").exists() and len(reads) == 1
    monkeypatch.setattr(ElevenLabsVoice, "_send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked the clone again")))
    second = tmp_path / "second.ogg"
    assert main(["voicenote", "--say", "Say it for me.", str(second), "--no-room", "--lufs", "-19", "--reuse", str(tmp_path / "first")]) == 0
    assert json.loads((tmp_path / "second.words.json").read_text(encoding="utf-8"))["reused"] == str(tmp_path / "first")


def test_a_tilde_in_a_path_is_the_home_directory(clean, tmp_path, monkeypatch):
    """A recipe kept in a variable and a path typed in quotes reach the tool with the ~ still in them."""
    from noirstudio.voicenote import NoteStyle, render

    _clone(monkeypatch, clean)
    monkeypatch.setenv("HOME", str(tmp_path))
    render(clean, tmp_path / "real.ogg", NoteStyle(noise_db=-40, lufs=-24, kbps=32))
    (tmp_path / "lines.json").write_text(json.dumps({"lines": [{"id": "a", "say": "Say it for me."}]}), encoding="utf-8")
    assert main(["voicenote", "--batch", "~/lines.json", "~/v4", "--match", "~/real.ogg", "--lufs", "-18.2", "--no-room"]) == 0
    assert (tmp_path / "v4" / "a.ogg").exists() and not Path("~").exists()
