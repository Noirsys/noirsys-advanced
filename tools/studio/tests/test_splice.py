"""A stretch of one of his real notes swapped for a rebuilt read: the note stays as it was everywhere else, and no seam drops the floor."""

import json
import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from noirstudio.cli import main  # noqa: E402
from noirstudio.splice import RATE, load, save, splice, summary  # noqa: E402
from noirstudio.voicenote import VoiceNoteError  # noqa: E402


def speech(seconds, level_db, seed=1, f0=130.0):
    """A stand-in for a voice: harmonics on a syllable rhythm, at `level_db` RMS (dBFS)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * RATE)) / RATE
    x = sum(a * np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28)) for k, a in ((1, 1.0), (2, 0.6), (3, 0.4), (4, 0.2)))
    x = x * (0.55 + 0.45 * np.sin(2 * np.pi * 3.5 * t) ** 2)
    return (x * 10 ** (level_db / 20) / np.sqrt((x ** 2).mean())).astype("float32")


def hush(seconds, level_db, seed=2):
    """Floor: white noise at `level_db` RMS (-inf: digital silence)."""
    n = int(seconds * RATE)
    if level_db <= -150:
        return np.zeros(n, dtype="float32")
    return (np.random.default_rng(seed).standard_normal(n) * 10 ** (level_db / 20)).astype("float32")


def note(floor_db=-95.0, seed=1):
    """His real note, its recording begun late: silence, "I mean to say fuck you" (1.0-2.4 s), a pause, the rest, silence."""
    return np.concatenate([hush(0.5, -200), hush(0.5, floor_db, seed), speech(1.4, -22, seed),
                           hush(0.5, floor_db, seed + 1), speech(1.2, -20, seed + 2, 150.0), hush(0.4, floor_db, seed + 3)])


def read(floor_db=-54.0, seed=5, seconds=2.0, level_db=-30.0):
    """The rebuilt sentence: a floor, the words, a floor (the clone's own room)."""
    return np.concatenate([hush(0.3, floor_db, seed), speech(seconds, level_db, seed, 120.0), hush(0.5, floor_db, seed + 1)])


def write_wav(path: Path, x) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(np.clip(np.round(x * 32768.0), -32768, 32767).astype("<i2").tobytes())
    return path


def loud_db(x):
    f = x[: len(x) // 960 * 960].reshape(-1, 960).astype("float64")
    return float(np.percentile(10 * np.log10((f ** 2).mean(axis=1) + 1e-18), 95))


def test_the_stretch_is_swapped_and_nothing_else_moves():
    real = note()
    out, r = splice(real, read(), 1.0, 2.55)
    a, b, xf = r["cut_a_sample"], r["cut_b_sample"], r["xfade_samples"]
    assert 0.85 <= r["cut_a_s"] <= 1.0 and 2.4 <= r["cut_b_s"] <= 2.9  # in the quiet either side of his words
    assert np.array_equal(out[: a - xf], real[: a - xf])  # everything before the cut is the same samples
    assert np.array_equal(out[len(out) - (len(real) - b - xf):], real[b + xf:])  # and everything after
    assert len(out) == round(r["duration_out_s"] * RATE) and r["shift_s"] == pytest.approx((len(out) - len(real)) / RATE, abs=1e-4)
    assert r["inserted_s"] > r["removed_s"] and r["shift_s"] > 0  # "I didn't mean" is longer than "I mean"
    assert abs(r["read_speech_db"] - r["note_speech_db"]) < 3  # the read is at the note's level
    assert loud_db(out[a: a + int(r["inserted_s"] * RATE)]) == pytest.approx(r["note_speech_db"], abs=3)
    assert r["peak_dbfs"] < -1 and np.isfinite(out).all()


def test_a_gated_note_stays_gated_and_a_note_with_a_room_keeps_its_room():
    gated, r = splice(note(-95.0), read(), 1.0, 2.55)
    assert r["floor_gated"] and r["floor_db"] < -85
    assert all(abs(s["step_db"]) < 6 for s in r["seams"])
    a, b = int(r["cut_a_s"] * RATE), int(r["cut_b_s"] * RATE)
    w = 960
    # the read's own room (-54 dBFS) is taken out: without the gate it sits in the note's silence, with it it does not
    _, open_ = splice(note(-95.0), read(), 1.0, 2.55, gate=False)
    assert open_["read_lead_db"] > -50 and r["read_lead_db"] < open_["read_lead_db"] - 8
    assert r["read_tail_db"] < open_["read_tail_db"] - 8
    room, r2 = splice(note(-60.0), read(floor_db=-45.0), 1.0, 2.55)
    assert not r2["floor_gated"] and r2["floor_db"] == pytest.approx(-60, abs=3)
    assert all(abs(s["step_db"]) < 3 for s in r2["seams"])  # the bed is the note's own room
    # nowhere in the new stretch does the floor drop out: every 20 ms frame is near the room or above it
    a2, b2 = int(r2["cut_a_s"] * RATE), int(r2["cut_a_s"] * RATE) + int(r2["inserted_s"] * RATE)
    frames = room[a2:b2][: (b2 - a2) // w * w].reshape(-1, w).astype("float64")
    assert (10 * np.log10((frames ** 2).mean(axis=1) + 1e-18)).min() > -66
    assert np.isfinite(gated).all() and gated.size > 0 and a < b


def test_a_cut_in_his_speech_is_refused_unless_asked_for():
    real = note()
    with pytest.raises(VoiceNoteError, match="in his speech"):
        splice(real, read(), 1.6, 1.9, search_s=0.02)
    out, r = splice(real, read(), 1.6, 1.9, search_s=0.02, anywhere=True)
    assert r["limit_db"] is None and len(out) > 0


def test_bad_stretches_and_reads_are_refused():
    real = note()
    for start, end in ((2.0, 1.0), (-1.0, 2.0), (1.0, 99.0)):
        with pytest.raises(VoiceNoteError, match="not inside the note"):
            splice(real, read(), start, end)
    with pytest.raises(VoiceNoteError, match="less than 150 ms of speech"):
        splice(real, hush(1.0, -60), 1.0, 2.55)
    with pytest.raises(VoiceNoteError, match="leave nothing to replace"):
        splice(real, read(), 2.5, 2.52)


def test_gain_can_be_given_and_the_peak_is_still_held():
    real = note()
    _, base = splice(real, read(), 1.0, 2.55)
    _, hot = splice(real, read(), 1.0, 2.55, gain_db=base["gain_db"] + 3)
    assert hot["gain_db"] == pytest.approx(base["gain_db"] + 3, abs=0.2) or hot["peak_dbfs"] <= -1.0
    _, wild = splice(real, read(), 1.0, 2.55, gain_db=40)
    assert wild["peak_dbfs"] <= -0.9  # a big gain is cut back to keep the loudest sample under -1 dBFS


@pytest.mark.parametrize("seed", range(12))
def test_holds_on_awkward_notes(seed):
    rng = np.random.default_rng(seed)
    floor = float(rng.choice([-200.0, -95.0, -75.0, -62.0, -55.0]))
    first, gap = float(rng.uniform(0.8, 1.6)), float(rng.uniform(0.3, 0.8))
    real = np.concatenate([hush(0.4, floor, seed), speech(first, float(rng.uniform(-28, -16)), seed), hush(gap, floor, seed + 1),
                           speech(float(rng.uniform(0.6, 1.4)), float(rng.uniform(-28, -16)), seed + 2, 140.0),
                           hush(0.3, floor, seed + 3)])
    room = float(rng.uniform(-70, -50))
    said = read(floor_db=room, seed=seed, seconds=float(rng.uniform(0.6, 3.0)), level_db=max(room + 22, float(rng.uniform(-40, -18))))
    out, r = splice(real, said, 0.4 - 0.02, 0.4 + first + gap * 0.5)  # his first words, out to the middle of the pause after
    assert np.isfinite(out).all() and r["peak_dbfs"] < -0.9
    assert r["cut_a_db"] <= r["limit_db"] and r["cut_b_db"] <= r["limit_db"]
    a, b, xf = r["cut_a_sample"], r["cut_b_sample"], r["xfade_samples"]
    assert np.array_equal(out[: a - xf], real[: a - xf]) and np.array_equal(out[len(out) - (len(real) - b - xf):], real[b + xf:])
    assert abs(r["read_speech_db"] - r["note_speech_db"]) < 4 or abs(r["gain_db"]) >= 14.9 or r["peak_dbfs"] > -1.5
    assert all(abs(s["step_db"]) < 12 for s in r["seams"])


def test_the_command_writes_the_note_and_says_what_it_did(tmp_path, capsys):
    note_path, read_path = write_wav(tmp_path / "note.wav", note()), write_wav(tmp_path / "read.wav", read())
    out = tmp_path / "sub" / "fixed.wav"
    assert main(["splice", str(note_path), str(read_path), str(out), "--replace", "1.0-2.55"]) == 0
    text = capsys.readouterr().out
    assert "removed" in text and "seam at" in text and "voiceprint OUT --seams" in text
    report = json.loads((tmp_path / "sub" / "fixed.wav.json").read_text())
    assert report["out"] == str(out) and report["inserted_s"] > 0
    fixed = load(out)
    assert len(fixed) == pytest.approx(report["duration_out_s"] * RATE, abs=2)
    assert main(["splice", str(note_path), str(read_path), str(tmp_path / "j.wav"), "--replace", "1.0-2.55", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cut_a_s"] == report["cut_a_s"]


def test_an_opus_note_can_be_written(tmp_path):
    from noirstudio import ffmpeg

    path = tmp_path / "out.ogg"
    save(note(), path)
    assert abs(ffmpeg.probe_duration(path) - len(note()) / RATE) < 0.1
    assert len(load(path)) > 0


def test_the_command_says_plainly_when_it_cannot(tmp_path, capsys):
    note_path, read_path = write_wav(tmp_path / "note.wav", note()), write_wav(tmp_path / "read.wav", read())
    bad = [(["--replace", "soon"], "START-END"), (["--replace", "2.0-1.0"], "not inside the note"),
           (["--replace", "1.6-1.9", "--search-ms", "10"], "in his speech")]
    for extra, why in bad:
        assert main(["splice", str(note_path), str(read_path), str(tmp_path / "x.wav"), *extra]) == 1
        assert why in capsys.readouterr().err
    assert main(["splice", str(tmp_path / "missing.wav"), str(read_path), str(tmp_path / "x.wav"), "--replace", "1-2"]) == 1
    assert "no such file" in capsys.readouterr().err
    assert not (tmp_path / "x.wav").exists()


def test_the_summary_reads_in_plain_words():
    _, r = splice(note(), read(), 1.0, 2.55)
    text = summary(r)
    assert text.count("\n") >= 5 and "everything after is" in text and "gain" in text
