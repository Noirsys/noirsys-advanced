"""voiceprint: the measurable habits of a voice, checked on signals whose answers are known."""

import json
import wave

import pytest

np = pytest.importorskip("numpy")

from noirstudio import cli  # noqa: E402
from noirstudio import voiceprint as vp  # noqa: E402

RATE = 16000


def tone(dur, f0=lambda t: 120 + 0 * t, harmonics=10):
    t = np.arange(int(dur * RATE)) / RATE
    phase = 2 * np.pi * np.cumsum(f0(t)) / RATE
    return sum(np.sin(k * phase) / k for k in range(1, harmonics + 1))


def burst(dur, level=0.3):
    s = tone(dur)
    return level * s * np.hanning(len(s)) ** 0.5 / np.abs(s).max()


def hush(dur, level=0.0005, seed=1):
    return level * np.random.default_rng(seed).standard_normal(int(dur * RATE))


def write(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def test_pauses_are_counted_and_short_gaps_are_not(tmp_path):
    gap = hush(0.45)
    x = np.concatenate([hush(0.3), burst(0.3), gap, burst(0.3), hush(0.1, seed=2), burst(0.3), gap, burst(0.3),
                        hush(0.45, seed=3), burst(0.3), hush(0.3)])
    r = vp.voiceprint(write(tmp_path / "p.wav", x), levels=False)
    assert r["pause_count"] == 3  # the 0.1 s breath inside is not a pause
    assert r["pause_median_s"] == pytest.approx(0.45, abs=0.04)
    assert r["longest_pause_s"] == pytest.approx(0.45, abs=0.04)
    assert r["utterance_s"] == pytest.approx(2.85, abs=0.15)  # leading and trailing silence don't count
    assert r["pauses_per_min"] == pytest.approx(60 * 3 / r["utterance_s"], rel=0.02)


def test_pitch_and_pitch_swing(tmp_path):
    steady = np.concatenate([hush(0.3), 0.15 * tone(3.0), hush(0.3, seed=2)])
    vib = np.concatenate([hush(0.3), 0.15 * tone(3.0, lambda t: 120 * 2 ** (4 * np.sin(2 * np.pi * 3 * t) / 12)),
                          hush(0.3, seed=2)])
    a = vp.voiceprint(write(tmp_path / "a.wav", steady), levels=False)
    b = vp.voiceprint(write(tmp_path / "b.wav", vib), levels=False)
    assert a["f0_median_hz"] == pytest.approx(120, rel=0.03)
    assert b["f0_median_hz"] == pytest.approx(120, rel=0.05)
    assert a["f0_sd_st"] < 0.3
    assert b["f0_sd_st"] == pytest.approx(4 / 2 ** 0.5, abs=0.5)  # a 4-semitone sine has sd 4/sqrt(2)
    assert b["f0_range_st"] > 5 > a["f0_range_st"]
    assert b["f0_move_st_s"] > 10 * (a["f0_move_st_s"] or 0.1)


def test_a_crisper_top_end_reads_higher(tmp_path):
    clean = np.concatenate([hush(0.3), burst(0.4), hush(0.3, seed=2)])
    hiss = np.diff(np.random.default_rng(3).standard_normal(len(clean)), n=2, prepend=[0, 0])
    crisp = clean + 0.08 * hiss / np.abs(hiss).max() * (np.abs(clean) > 0.01)
    a = vp.voiceprint(write(tmp_path / "a.wav", clean), levels=False)
    b = vp.voiceprint(write(tmp_path / "b.wav", crisp), levels=False)
    assert b["hf_db"] > a["hf_db"] + 20
    assert b["centroid_hz"] > a["centroid_hz"] + 500


def test_loudness_swing(tmp_path):
    t = np.arange(int(3 * RATE)) / RATE
    flat = 0.2 * tone(3.0)
    swung = flat * 10 ** (6 * np.sin(2 * np.pi * 3 * t) / 20)  # +-6 dB at 3 Hz
    a = vp.voiceprint(write(tmp_path / "a.wav", np.concatenate([hush(0.3), flat, hush(0.3)])), levels=False)
    b = vp.voiceprint(write(tmp_path / "b.wav", np.concatenate([hush(0.3), swung, hush(0.3)])), levels=False)
    assert a["level_range_db"] < 1.0
    assert b["level_sd_db"] == pytest.approx(6 / 2 ** 0.5, abs=0.6)  # a +-6 dB sine has sd 6/sqrt(2)
    assert b["level_range_db"] == pytest.approx(12, abs=1.5)


def test_loudness_and_room_tone_are_read_for_wav_and_opus(tmp_path):
    from noirstudio import ffmpeg

    wav = write(tmp_path / "x.wav", np.concatenate([hush(0.3), burst(1.5), hush(0.5), burst(1.5), hush(0.3)]))
    ogg = tmp_path / "x.ogg"
    ffmpeg.run(["-y", "-i", str(wav), "-ar", "48000", "-ac", "1", "-c:a", "libopus", "-b:a", "24k",
                "-application", "voip", str(ogg)])
    a, b = vp.voiceprint(wav), vp.voiceprint(ogg)
    for r in (a, b):
        assert -40 < r["lufs"] < -10
        assert r["noise_db"] < -50
        assert r["pause_count"] == 1
    assert b["f0_median_hz"] == pytest.approx(a["f0_median_hz"], rel=0.05)  # the codec doesn't move the pitch


def test_words_per_minute(tmp_path):
    x = np.concatenate([hush(0.3), burst(1.0), hush(0.3), burst(1.0), hush(0.3)])
    r = vp.voiceprint(write(tmp_path / "w.wav", x), words=6, levels=False)
    assert r["wpm_speech"] == pytest.approx(60 * 6 / r["speech_s"], abs=0.2)
    assert r["wpm_total"] == pytest.approx(60 * 6 / r["utterance_s"], abs=0.2)
    assert r["wpm_speech"] > r["wpm_total"]


def test_compare_says_which_side_and_how_far():
    his = {"f0_sd_st": {"median": 2.0, "q1": 1.6, "q3": 2.4, "n": 9},
           "pauses_per_min": {"median": 20.0, "q1": 16.0, "q3": 26.0, "n": 9},
           "hf_db": {"median": -20.0, "q1": -22.0, "q3": -18.0, "n": 9},
           "syll_cv": {"median": 0.5, "q1": 0.4, "q3": 0.6, "n": 9},
           "level_sd_db": {"median": 6.0, "q1": 5.0, "q3": 7.0, "n": 9}}
    ours = {"f0_sd_st": {"median": 4.0, "q1": 3.0, "q3": 5.0, "n": 3},           # twice his swing
            "pauses_per_min": {"median": 8.0, "q1": 6.0, "q3": 9.0, "n": 3},    # far fewer pauses
            "hf_db": {"median": -19.0, "q1": -20.0, "q3": -18.0, "n": 3},       # inside his middle half
            "syll_cv": {"median": 0.8, "q1": 0.7, "q3": 0.9, "n": 3},           # more uneven than he is
            "level_sd_db": {"median": 6.9, "q1": 6.0, "q3": 7.5, "n": 3}}       # within 20%
    got = {r["metric"]: r for r in vp.compare(his, ours)}
    assert got["f0_sd_st"]["verdict"] == "too performed" and got["f0_sd_st"]["ratio"] == 2.0
    assert got["pauses_per_min"]["verdict"] == "too performed"  # fewer pauses is the polished side
    assert got["hf_db"]["verdict"] == "close"
    assert got["syll_cv"]["verdict"] == "past him"  # more uneven than his, the other way from polished
    assert got["level_sd_db"]["verdict"] == "close"
    assert "f0_sd_st" in vp.table(list(got.values()))


def test_summarize_skips_clips_with_too_little_speech():
    rows = [{"speech_s": 5.0, "f0_sd_st": 2.0}, {"speech_s": 6.0, "f0_sd_st": 3.0}, {"speech_s": 0.8, "f0_sd_st": 9.0}]
    s = vp.summarize(rows)
    assert s["n"] == 2 and s["skipped"] == 1
    assert s["f0_sd_st"]["median"] == 2.5


def test_cli_compares_two_sets_and_reads_a_words_sidecar(tmp_path, capsys):
    a = write(tmp_path / "his1.wav", np.concatenate([hush(0.3), burst(1.5), hush(0.6), burst(1.5), hush(0.3)]))
    b = write(tmp_path / "his2.wav", np.concatenate([hush(0.3), burst(1.4), hush(0.7), burst(1.4), hush(0.3)]))
    c = write(tmp_path / "read.wav", np.concatenate([hush(0.3), burst(1.5), hush(0.25), burst(1.5), hush(0.3)]))
    (tmp_path / "read.words.json").write_text(json.dumps({"words": [{"text": w} for w in "a b c d e f g".split()]}))
    code = cli.main(["voiceprint", str(a), str(b), "--vs", str(c), "--min-speech", "1", "--fast", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["his_summary"]["n"] == 2 and out["ours_summary"]["n"] == 1
    assert out["ours"][0]["words"] == 7 and "wpm_speech" in out["ours"][0]  # the sidecar's word count
    by = {r["metric"]: r for r in out["compare"]}
    assert by["pauses_per_min"]["verdict"] in {"close", "too performed", "past him"}
    assert by["longest_pause_s"]["his"] > by["longest_pause_s"]["ours"]  # his pauses are longer


def test_cli_text_report_and_a_file_that_is_not_audio(tmp_path, capsys):
    good = write(tmp_path / "g.wav", np.concatenate([hush(0.3), burst(1.5), hush(0.5), burst(1.5), hush(0.3)]))
    junk = tmp_path / "junk.wav"
    junk.write_bytes(b"not audio")
    code = cli.main(["voiceprint", str(good), str(junk), "--fast"])
    captured = capsys.readouterr()
    assert code == 0  # one file read is enough
    assert "these: 1 files" in captured.out and "f0_sd_st" in captured.out
    assert "junk.wav" in captured.err
