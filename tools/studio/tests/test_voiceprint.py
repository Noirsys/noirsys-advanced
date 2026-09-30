"""voiceprint: the measurable habits of a voice, checked on signals whose answers are known."""

import json
import re
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


def formant_voice(dur=4.0, sd_st=2.5, seed=1, base=105.0, syll_hz=4.5):
    """Vowels with formants (each harmonic weighted by three resonances, the vowel changing every syllable) on
    a pitch contour whose standard deviation is known: what a pitch reader has to survive that a bare
    harmonic tone does not. Returns the signal and the contour's sd in semitones."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(dur * RATE)) / RATE
    c = sum(rng.normal() * np.sin(2 * np.pi * rng.uniform(0.5, 4.0) * t + rng.uniform(0, 6.28)) for _ in range(9))
    c = c / c.std() * sd_st
    f0 = base * 2 ** (c / 12)
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    vowels = [(700, 1200, 2600), (300, 2200, 3000), (330, 800, 2300), (500, 1800, 2500), (500, 900, 2400)]
    n = int(dur * syll_hz) + 2
    seq = [vowels[rng.integers(len(vowels))] for _ in range(n)]
    centres = (np.arange(n) + 0.5) / syll_hz
    formants = [np.interp(t, centres, [v[k] for v in seq]) for k in range(3)]
    x = np.zeros_like(t)
    for k in range(1, int(3800 / base) + 1):
        fk = k * f0
        amp = 1.0 / k ** 1.2
        for centre, bw in zip(formants, (80, 100, 140)):  # a 2-pole resonance's magnitude at the harmonic
            pole = -np.pi * bw + 2j * np.pi * centre * np.sqrt(1 - (bw / (2 * centre)) ** 2)
            amp = amp * (1 + 6 * np.abs(pole) ** 2 / np.abs((2j * np.pi * fk - pole) * (2j * np.pi * fk - np.conj(pole))))
        x += amp * np.sin(k * phase) * (fk < 4000)
    x = x * (0.55 + 0.45 * np.cos(2 * np.pi * syll_hz * t))
    return 0.35 * x / np.abs(x).max() + 0.002 * rng.standard_normal(len(x)), float(c.std())


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


@pytest.mark.parametrize("reader", ["praat", "autocorr"])
def test_the_swing_is_read_true_on_vowels_with_formants(tmp_path, reader):
    """The 200 Hz high-pass that was tried once read every one of these 2 semitones too wide: the formants won."""
    if reader == "praat":
        pytest.importorskip("parselmouth")
    for seed, sd in ((1, 1.5), (2, 2.5), (3, 3.5)):
        x, truth = formant_voice(4.0, sd, seed)
        r = vp.voiceprint(write(tmp_path / f"v{seed}.wav", np.concatenate([hush(0.3), x, hush(0.3, seed=9)])),
                          levels=False, reader=reader)
        assert r["pitch_reader"] == reader
        assert r["f0_sd_st"] == pytest.approx(truth, abs=0.6)
        assert r["f0_median_hz"] == pytest.approx(105, rel=0.07)


@pytest.mark.parametrize("reader", ["praat", "autocorr"])
def test_the_phone_chain_does_not_move_the_swing(tmp_path, reader):
    from noirstudio import ffmpeg

    if reader == "praat":
        pytest.importorskip("parselmouth")
    x, _ = formant_voice(4.0, 2.5, 4)
    clean = write(tmp_path / "clean.wav", np.concatenate([hush(0.3), x, hush(0.3, seed=9)]))
    chained = tmp_path / "chained.wav"
    ffmpeg.run(["-y", "-i", str(clean), "-af", "highpass=f=100:poles=2,highpass=f=100:poles=2,lowpass=f=8000", str(chained)])
    a, b = (vp.voiceprint(f, levels=False, reader=reader) for f in (clean, chained))
    assert abs(a["f0_sd_st"] - b["f0_sd_st"]) < 0.4
    assert b["f0_median_hz"] == pytest.approx(a["f0_median_hz"], rel=0.05)


def test_without_praat_the_numpy_reader_takes_over_and_says_so(tmp_path, monkeypatch):
    import sys

    x, truth = formant_voice(4.0, 2.5, 2)
    path = write(tmp_path / "v.wav", np.concatenate([hush(0.3), x, hush(0.3, seed=9)]))
    monkeypatch.setitem(sys.modules, "parselmouth", None)  # what `import parselmouth` sees when it isn't installed
    r = vp.voiceprint(path, levels=False)
    assert r["pitch_reader"] == "autocorr" and r["f0_sd_st"] == pytest.approx(truth, abs=0.6)
    with pytest.raises(vp.VoiceNoteError, match="praat-parselmouth"):
        vp.voiceprint(path, levels=False, reader="praat")
    with pytest.raises(vp.VoiceNoteError, match="pitch reader"):
        vp.voiceprint(path, levels=False, reader="crepe")


def test_a_clip_praat_refuses_has_no_pitch_but_does_not_stop_the_batch(tmp_path, monkeypatch):
    pytest.importorskip("parselmouth")
    x, _ = formant_voice(3.0, 2.0, 5)
    path = write(tmp_path / "v.wav", np.concatenate([hush(0.3), x, hush(0.3, seed=9)]))

    import parselmouth

    def refuse(*_a, **_k):
        raise parselmouth.PraatError("The Sound is too short")

    monkeypatch.setattr(vp, "_praat_pitch", refuse)
    r = vp.voiceprint(path, levels=False)
    assert r["pitch_reader"] == "praat" and "f0_sd_st" not in r and r["speech_s"] > 2  # the rest of the row is fine
    assert "too short" in r["pitch_error"]
    assert cli.main(["voiceprint", str(path), "--fast"]) == 0
    monkeypatch.setattr(vp, "_praat_pitch", lambda *_a, **_k: (_ for _ in ()).throw(IndexError("a real bug")))
    with pytest.raises(IndexError):  # only Praat's own refusals are swallowed: a bug in our code is not
        vp.voiceprint(path, levels=False)


def test_a_clip_with_no_pauses_has_no_pause_length_rather_than_a_zero(tmp_path):
    r = vp.voiceprint(write(tmp_path / "run.wav", np.concatenate([hush(0.3), burst(2.0), hush(0.3, seed=2)])), levels=False)
    assert r["pauses_per_min"] == 0 and r["pause_count"] == 0
    assert r["pause_median_s"] is None and r["longest_pause_s"] is None and r["pause_p90_s"] is None
    rows = [{"speech_s": 3.0, "pause_median_s": None}, {"speech_s": 3.0, "pause_median_s": 0.6},
            {"speech_s": 3.0, "pause_median_s": 0.8}]
    assert vp.summarize(rows)["pause_median_s"]["median"] == 0.7  # the clip that never paused doesn't drag it to zero


def test_pitch_is_not_compared_across_readers_but_the_rest_still_is():
    def summary(reader):
        return {"readers": [reader],
                "f0_sd_st": {"median": 3.0, "q1": 2.5, "q3": 3.5, "n": 5},
                "hf_db": {"median": -25.0, "q1": -27.0, "q3": -23.0, "n": 5}}

    rows = {r["metric"]: r for r in vp.compare(summary("praat"), summary("autocorr"))}
    assert rows["f0_sd_st"]["verdict"] == "different readers" and rows["f0_sd_st"]["ratio"] is None
    assert rows["hf_db"]["verdict"] == "close"
    same = {r["metric"]: r for r in vp.compare(summary("praat"), summary("praat"))}
    assert same["f0_sd_st"]["verdict"] == "close"


def test_a_summary_says_which_reader_made_the_pitch():
    rows = [{"speech_s": 5.0, "pitch_reader": "praat"}, {"speech_s": 6.0, "pitch_reader": "autocorr"},
            {"speech_s": 7.0}]
    assert vp.summarize(rows)["readers"] == ["autocorr", "praat"]


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


# --- timeline: what is inside one clip -----------------------------------------------------------

def _laugh_then_words():
    """Half a second of room, a 1.6 s train of five bursts a second that fades (a laugh's shape, on a 220 Hz
    buzz), 0.6 s of room, then 1.2 s of a steady 120 Hz voice."""
    t = np.arange(int(1.6 * RATE)) / RATE
    buzz = tone(1.6, lambda x: 220 + 0 * x)
    trail = buzz * np.clip(np.sin(2 * np.pi * 5 * t), 0, None) ** 2 * np.exp(-t / 1.0)
    laugh = 0.3 * trail / np.abs(trail).max()
    words = 0.2 * tone(1.2) * np.hanning(int(1.2 * RATE)) ** 0.5
    return np.concatenate([hush(0.5), laugh, hush(0.6, seed=2), words, hush(0.3, seed=3)])


def test_timeline_tells_a_train_of_fading_bursts_from_a_steady_voice(tmp_path):
    tl = vp.timeline(write(tmp_path / "l.wav", _laugh_then_words()))
    assert tl["duration_s"] == pytest.approx(4.2, abs=0.01)
    assert len(tl["rows"]) == pytest.approx(42, abs=1) and tl["rows"][0]["t_s"] == 0.0
    burst, steady = tl["events"]  # the 0.6 s of room is longer than the 0.3 s that joins bursts into one event
    assert burst["start_s"] == pytest.approx(0.5, abs=0.1) and burst["dur_s"] == pytest.approx(1.5, abs=0.25)
    assert 4 <= burst["bursts_per_s"] <= 6.5 and burst["burst_cv"] < 0.25
    assert burst["decay_db_s"] < -3  # it fades
    assert burst["f0_median_hz"] == pytest.approx(220, rel=0.05)
    assert steady["start_s"] == pytest.approx(2.7, abs=0.1) and steady["f0_median_hz"] == pytest.approx(120, rel=0.05)
    assert steady["bursts"] <= 1 and "decay_db_s" not in steady
    quiet = next(r for r in tl["rows"] if r["t_s"] == 0.2)
    loud = next(r for r in tl["rows"] if r["t_s"] == 3.0)
    assert quiet["on"] == 0.0 and quiet["f0_hz"] is None
    assert loud["on"] >= 0.9 and loud["f0_hz"] == pytest.approx(120, rel=0.05) and loud["level_db"] > quiet["level_db"] + 30


def test_cli_timeline_prints_the_table_and_json(tmp_path, capsys):
    clip = write(tmp_path / "clip.wav", _laugh_then_words())
    assert cli.main(["voiceprint", str(clip), "--timeline"]) == 0
    text = capsys.readouterr().out
    assert "clip.wav" in text and "events" in text and "bursts" in text and "#####" in text
    assert cli.main(["voiceprint", str(clip), "--timeline", "--step", "0.2", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["failed"] == [] and len(out["timelines"]) == 1
    assert out["timelines"][0]["step_s"] == 0.2 and len(out["timelines"][0]["events"]) == 2


def test_cli_timeline_of_a_silent_clip_is_skipped_not_a_crash(tmp_path, capsys):
    quiet = write(tmp_path / "quiet.wav", hush(2.0))
    code = cli.main(["voiceprint", str(quiet), "--timeline"])
    captured = capsys.readouterr()
    assert code == 1 and "quiet.wav" in captured.err


# --- where the two pitch readers part ------------------------------------------------------------

def _two_voices(tmp_path):
    paths = []
    for seed, sd in ((1, 1.5), (2, 3.0)):
        x, _ = formant_voice(4.0, sd, seed)
        paths.append(write(tmp_path / f"v{seed}.wav", np.concatenate([hush(0.3), x, hush(0.3, seed=9)])))
    return paths


def test_the_readers_agree_on_a_clean_voice_and_the_frames_add_up(tmp_path):
    pytest.importorskip("parselmouth")
    (path, _) = _two_voices(tmp_path)
    r = vp.readers_apart(path)
    assert r["praat"] == r["both"] + r["only_praat"] and r["autocorr"] == r["both"] + r["only_autocorr"]
    assert sum(r["apart"].values()) == r["both"] and r["frames"] >= r["both"] > 100
    assert r["apart"]["lt0.5"] > 0.9 * r["both"] and r["high"] == 0 and r["low"] == 0
    assert abs(r["f0_sd_praat"] - r["f0_sd_autocorr"]) < 0.4 and abs(r["bias_st"]) < 0.3
    assert r["f0_sd_praat_top"] is not None and r["f0_sd_autocorr_bottom"] is not None
    assert r["periodicity_top"] >= r["periodicity_bottom"]


def test_the_clips_together_pool_their_frames_and_take_the_median_of_the_rest(tmp_path):
    pytest.importorskip("parselmouth")
    rows = [vp.readers_apart(p) for p in _two_voices(tmp_path)]
    s = vp.readers_apart_summary(rows)
    assert s["n"] == 2 and s["both"] == sum(r["both"] for r in rows) and s["frames"] == sum(r["frames"] for r in rows)
    assert sum(s["apart_share"].values()) == pytest.approx(1.0, abs=0.01)
    lo, hi = sorted(r["f0_sd_praat"] for r in rows)
    assert lo <= s["median"]["f0_sd_praat"] <= hi
    text = vp.readers_apart_text(rows, s)
    assert "v1.wav" in text and "v2.wav" in text and "2 clips" in text and "only Praat" in text and "oct%" in text


def test_comparing_the_readers_needs_praat_and_speech(tmp_path, monkeypatch):
    import sys

    pytest.importorskip("parselmouth")
    (path, _) = _two_voices(tmp_path)
    with pytest.raises(vp.VoiceNoteError, match="no speech"):
        vp.readers_apart(write(tmp_path / "quiet.wav", hush(2.0)))
    monkeypatch.setitem(sys.modules, "parselmouth", None)
    with pytest.raises(vp.VoiceNoteError, match="praat-parselmouth"):
        vp.readers_apart(path)


def test_cli_readers_apart_prints_the_table_and_json_and_keeps_going_past_a_bad_file(tmp_path, capsys):
    pytest.importorskip("parselmouth")
    a, b = _two_voices(tmp_path)
    quiet = write(tmp_path / "quiet.wav", hush(2.0))
    assert cli.main(["voiceprint", str(a), str(quiet), str(b), "--readers-apart"]) == 0
    captured = capsys.readouterr()
    assert "v1.wav" in captured.out and "v2.wav" in captured.out and "2 clips" in captured.out and "quiet.wav" in captured.err
    assert cli.main(["voiceprint", str(a), str(b), "--readers-apart", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["clips"]) == 2 and out["summary"]["n"] == 2 and out["outside"] == 0
    assert cli.main(["voiceprint", str(a), str(b), "--readers-apart", "--min-speech", "60"]) == 1
    assert "no clip to compare" in capsys.readouterr().err


# --- voicenote --swing: flatten a read's pitch to his level ------------------------------------

def _expressive_read(tmp_path, name="read.wav"):
    f0 = lambda t: 120 * 2 ** ((5 * np.sin(2 * np.pi * 0.7 * t) + 2 * np.sin(2 * np.pi * 3 * t)) / 12)
    return write(tmp_path / name, np.concatenate([hush(0.3), 0.15 * tone(4.0, f0), hush(0.3, seed=2)]))


def test_swing_flattens_to_the_target_and_keeps_median_and_length(tmp_path):
    pytest.importorskip("parselmouth")
    from noirstudio import voicenote as vn

    src = _expressive_read(tmp_path)
    got = vn.swing(src, tmp_path / "flat.wav", 2.0)
    assert got["before_st"] > 3
    assert got["factor"] == pytest.approx(2.0 / got["before_st"], abs=0.02)
    assert got["after_st"] == pytest.approx(2.0, abs=0.5)
    assert abs(got["drift_s"]) < 0.02  # the aligned word timings stay valid
    a = vp.voiceprint(src, levels=False)
    b = vp.voiceprint(tmp_path / "flat.wav", levels=False)
    assert b["f0_median_hz"] == pytest.approx(a["f0_median_hz"], rel=0.03)
    assert b["f0_range_st"] < 0.7 * a["f0_range_st"]


def test_swing_only_ever_flattens(tmp_path):
    pytest.importorskip("parselmouth")
    from noirstudio import voicenote as vn

    steady = write(tmp_path / "steady.wav", np.concatenate([hush(0.3), 0.15 * tone(3.0), hush(0.3, seed=2)]))
    got = vn.swing(steady, tmp_path / "out.wav", 3.0)
    assert got["factor"] == 1.0
    assert (tmp_path / "out.wav").read_bytes() == steady.read_bytes()
    with pytest.raises(vn.VoiceNoteError):
        vn.swing(steady, tmp_path / "x.wav", 0.1)


def test_voicenote_cli_swing_on_a_read_you_already_have(tmp_path, capsys):
    pytest.importorskip("parselmouth")
    src = _expressive_read(tmp_path)
    plain, flat = tmp_path / "plain.ogg", tmp_path / "flat.ogg"
    assert cli.main(["voicenote", str(src), str(plain), "--json"]) == 0
    capsys.readouterr()
    assert cli.main(["voicenote", str(src), str(flat), "--swing", "2.0", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["swing"]["swing_target_st"] == 2.0
    assert report["swing"]["swing_after_st"] < report["swing"]["swing_before_st"]
    assert not (tmp_path / "flat.swung.wav").exists()  # the working copy is cleaned up
    assert vp.voiceprint(flat, levels=False)["f0_sd_st"] < 0.75 * vp.voiceprint(plain, levels=False)["f0_sd_st"]


def test_max_speech_keeps_long_dictations_out_of_a_short_comparison():
    rows = [{"speech_s": 5.0, "pause_median_s": 0.5}, {"speech_s": 12.0, "pause_median_s": 0.7},
            {"speech_s": 90.0, "pause_median_s": 3.0}]
    assert vp.summarize(rows)["pause_median_s"]["median"] == 0.7
    short = vp.summarize(rows, 2.0, 25.0)
    assert short["n"] == 2 and short["skipped"] == 1 and short["pause_median_s"]["median"] == 0.6


def test_swing_takes_the_stereo_wav_a_clones_read_arrives_as(tmp_path):
    pytest.importorskip("parselmouth")
    from noirstudio import ffmpeg
    from noirstudio import voicenote as vn

    mono = _expressive_read(tmp_path, "mono.wav")
    stereo = tmp_path / "stereo.wav"  # what voice.to_wav() hands the tool: 48 kHz, two channels
    ffmpeg.run(["-y", "-i", str(mono), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(stereo)])
    got = vn.swing(stereo, tmp_path / "flat.wav", 2.0)
    assert got["after_st"] == pytest.approx(2.0, abs=0.6) and abs(got["drift_s"]) < 0.02


def test_say_with_swing_hesitate_and_raw_end_to_end(tmp_path, monkeypatch):
    """The whole H recipe through the fake clone: stereo 48 kHz in (as voice.to_wav makes it), a note and its captions out."""
    pytest.importorskip("parselmouth")
    from noirstudio import ffmpeg
    from noirstudio.voice import ElevenLabsVoice

    mono = _expressive_read(tmp_path, "tts.wav")
    stereo = tmp_path / "tts_stereo.wav"
    ffmpeg.run(["-y", "-i", str(mono), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(stereo)])
    text = "So, uh, I think we should probably just go with the first one, you know, and see what happens."
    tokens = text.split()
    step = 4.0 / len(tokens)
    aligned = [{"text": w.lower().strip(",."), "start": round(0.3 + i * step, 3), "end": round(0.3 + i * step + step * 0.85, 3)}
               for i, w in enumerate(tokens)]

    def fake_send(self, method, path, data, content_type, accept, query=""):
        return json.dumps({"words": aligned}).encode() if path == "/v1/forced-alignment" else stereo.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    out = tmp_path / "note.ogg"
    args = ["voicenote", "--say", text, str(out), "--rough", "2", "--raw", "--swing", "2.0", "--hesitate", "2"]
    assert cli.main(args) == 0
    got = json.loads((tmp_path / "note.words.json").read_text(encoding="utf-8"))
    assert got["swing"]["swing_before_st"] > 3 and got["swing"]["swing_after_st"] == pytest.approx(2.0, abs=0.4)
    assert got["pauses"] and all(p["auto"] for p in got["pauses"])
    assert [w["text"] for w in got["words"]] == tokens  # the captions are the script's own words
    added = sum(p["s"] for p in got["pauses"])
    assert ffmpeg.probe_duration(out) == pytest.approx(0.35 + 4.6 + added + 0.5, abs=0.25)  # lead + read + pauses + tail
    assert got["words"][-1]["end"] == pytest.approx(0.35 + 0.3 + 4.0 + added - 0.6 * step, abs=0.2)


def test_preset_home_fills_in_the_recipe_and_what_you_pass_wins(tmp_path, monkeypatch):
    """`--preset home` is the measured recipe (stability 0.9, rough 2, raw, swing 2.1, pitch 104, pace 1.2, hesitate 1)."""
    pytest.importorskip("parselmouth")
    from noirstudio import ffmpeg
    from noirstudio.voice import ElevenLabsVoice

    mono = _expressive_read(tmp_path, "tts.wav")
    stereo = tmp_path / "tts_stereo.wav"
    ffmpeg.run(["-y", "-i", str(mono), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(stereo)])
    text = ("So, uh, I think we should probably just go with the first one, you know, um, and see what happens, because "
            "the thing is that we need to decide by tomorrow and I do not want to wait any longer than that.")
    sent = []

    def fake_send(self, method, path, data, content_type, accept, query=""):
        if path == "/v1/forced-alignment":  # aligned to the text the clone was sent, stumbles and all
            tokens = sent[-1]["text"].split()
            step = 4.0 / len(tokens)
            return json.dumps({"words": [{"text": w.lower().strip(",."), "start": round(0.3 + i * step, 3),
                                          "end": round(0.3 + i * step + step * 0.85, 3)} for i, w in enumerate(tokens)]}).encode()
        sent.append(json.loads(data))
        return stereo.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)

    def build(name, *flags):
        out = tmp_path / f"{name}.ogg"
        assert cli.main(["voicenote", "--say", text, str(out), *flags]) == 0
        return json.loads((tmp_path / f"{name}.words.json").read_text(encoding="utf-8"))

    home = build("home", "--preset", "home")
    assert sent[-1]["voice_settings"]["stability"] == 0.9 and home["stability"] == 0.9 and home["rough"] == 2
    assert home["swing"]["swing_target_st"] == 2.1 and home["swing"]["swing_after_st"] == pytest.approx(2.1, abs=0.5)
    assert home["swing"]["pace_effective"] == pytest.approx(1.2, abs=0.05)
    assert home["stumble"] == 2.0 and len(home["said"].split()) > len(text.split())  # the stumbles are in what was said
    from noirstudio.voicenote import roughen

    shown = [t for t in roughen(home["said"], 2).split() if any(c.isalnum() for c in t)]
    assert [w["text"] for w in home["words"]] == shown  # --raw: the captions are the line, stumbles and all
    assert re.search(r"\bum\b", home["said"])  # his "um" goes to the clone as "ummm" (a plain one merges into the word before it)
    assert re.search(r"\bummm\b", sent[-1]["text"]) and not re.search(r"\bum\b", sent[-1]["text"])
    assert home["spelled"] != home["read"] and "ummm" not in home["read"]
    um = re.compile(r"^um\W*$", re.I)  # and it is captioned "um" (with whatever punctuation the script gave it)
    assert sum(bool(um.match(w["text"])) for w in home["words"]) == sum(bool(um.match(w)) for w in home["said"].split()) >= 1
    assert not any("ummm" in w["text"] for w in home["words"])
    mine = build("mine", "--preset", "home", "--stability", "0.5", "--swing", "3.0", "--rough", "1")
    assert sent[-1]["voice_settings"]["stability"] == 0.5 and mine["stability"] == 0.5 and mine["rough"] == 1
    assert mine["swing"]["swing_target_st"] == 3.0
    assert mine["stumble"] == 2.0
    quiet = build("quiet", "--preset", "home", "--stumble", "0")
    assert quiet["said"] == text and quiet["stumble"] == 0.0  # an explicit flag wins over the preset's
    plain = build("plain")  # without the preset nothing changes: the old defaults
    assert sent[-1]["voice_settings"]["stability"] == 0.85 and plain["rough"] == 2 and plain["swing"] is None
    assert plain["said"] == text and plain["stumble"] == 0.0


def test_reuse_runs_a_build_again_from_the_read_it_kept_without_asking_for_a_new_one(tmp_path, monkeypatch, capsys):
    """The clone's account can be locked (a failed payment) or the change can be after the read (a new bed, a new fill): `--reuse`
    takes the read and word timings an earlier build of the same line kept, and runs everything after them again."""
    pytest.importorskip("parselmouth")
    from noirstudio import ffmpeg
    from noirstudio.voice import ElevenLabsVoice

    mono = _expressive_read(tmp_path, "tts.wav")
    stereo = tmp_path / "tts_stereo.wav"
    ffmpeg.run(["-y", "-i", str(mono), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(stereo)])
    text = ("So, uh, I think we should probably just go with the first one, you know, um, and see what happens, because "
            "the thing is that we need to decide by tomorrow and I do not want to wait any longer than that.")
    sent = []

    def fake_send(self, method, path, data, content_type, accept, query=""):
        sent.append(path)
        if path == "/v1/forced-alignment":
            tokens = json.loads(data_of[-1])["text"].split()
            step = 4.0 / len(tokens)
            return json.dumps({"words": [{"text": w.lower().strip(",."), "start": round(0.3 + i * step, 3),
                                          "end": round(0.3 + i * step + step * 0.85, 3)} for i, w in enumerate(tokens)]}).encode()
        data_of.append(data)
        return stereo.read_bytes()

    data_of: list = []
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    first = tmp_path / "first.ogg"
    assert cli.main(["voicenote", "--say", text, str(first), "--preset", "home"]) == 0
    was = json.loads((tmp_path / "first.words.json").read_text(encoding="utf-8"))
    calls = len(sent)
    assert calls == 2 and was["pauses"] and was["fill"]["cuts"]  # a read and its alignment; and the build says where each pause went
    assert {"after_words", "moved_ms", "over_floor_db", "fade_out_ms", "fade_in_ms"} <= set(was["fill"]["cuts"][0])

    again = tmp_path / "again.ogg"
    assert cli.main(["voicenote", "--say", text, str(again), "--preset", "home", "--reuse", str(tmp_path / "first")]) == 0
    got = json.loads((tmp_path / "again.words.json").read_text(encoding="utf-8"))
    assert len(sent) == calls  # nothing was asked of the clone
    assert got["reused"].endswith("first") and got["pauses"] == was["pauses"] and got["said"] == was["said"]
    assert [w["text"] for w in got["words"]] == [w["text"] for w in was["words"]]
    for a, b in zip(got["words"], was["words"]):  # the timings worked back from the captions land where they were
        assert a["start"] == pytest.approx(b["start"], abs=0.02) and a["end"] == pytest.approx(b["end"], abs=0.02)
    assert ffmpeg.probe_duration(again) == pytest.approx(ffmpeg.probe_duration(first), abs=0.02)

    # a different line is not that read, and a build that kept no read cannot be reused; neither reaches the clone
    assert cli.main(["voicenote", "--say", text + " Also this.", str(tmp_path / "x.ogg"), "--preset", "home",
                     "--reuse", str(tmp_path / "first")]) == 2
    assert "different line" in capsys.readouterr().err
    assert cli.main(["voicenote", "--say", text, str(tmp_path / "y.ogg"), "--preset", "home", "--reuse", str(tmp_path / "none")]) == 2
    assert "nothing to reuse" in capsys.readouterr().err
    assert cli.main(["voicenote", str(stereo), str(tmp_path / "z.ogg"), "--reuse", str(tmp_path / "first")]) == 1
    assert len(sent) == calls


# --- prosody: pitch level, swing and pace, found by measuring ---------------------------------

def test_prosody_moves_the_pitch_level_the_swing_and_the_pace_together(tmp_path):
    pytest.importorskip("parselmouth")
    from noirstudio import ffmpeg
    from noirstudio import voicenote as vn

    src = _expressive_read(tmp_path)
    got = vn.prosody(src, tmp_path / "his.wav", swing_st=2.5, median_hz=105, pace=1.25)
    assert got["median_before_hz"] == pytest.approx(126, rel=0.05)
    assert got["median_after_hz"] == pytest.approx(105, rel=0.06)  # 3.5 semitones lower
    assert got["swing_after_st"] == pytest.approx(2.5, abs=0.35)  # found by measuring, not by the factor alone
    assert got["pace_effective"] == pytest.approx(1.25, abs=0.03)
    assert abs(got["drift_s"]) < 0.05
    assert ffmpeg.probe_duration(tmp_path / "his.wav") == pytest.approx(1.25 * ffmpeg.probe_duration(src), rel=0.03)


def test_prosody_pitch_alone_leaves_swing_and_pace_be(tmp_path):
    pytest.importorskip("parselmouth")
    from noirstudio import voicenote as vn

    src = _expressive_read(tmp_path)
    got = vn.prosody(src, tmp_path / "low.wav", median_hz=100)
    assert got["median_after_hz"] == pytest.approx(100, rel=0.06)
    assert got["swing_after_st"] == pytest.approx(got["swing_before_st"], rel=0.2)  # moving the level moves the swing a little;
    assert got["pace_effective"] == pytest.approx(1.0, abs=0.02) and got["factor"] == 1.0  # asking for a swing corrects for it


def test_prosody_with_nothing_to_change_copies_the_read_and_refuses_silly_numbers(tmp_path):
    pytest.importorskip("parselmouth")
    from noirstudio import voicenote as vn

    steady = write(tmp_path / "steady.wav", np.concatenate([hush(0.3), 0.15 * tone(3.0), hush(0.3, seed=2)]))
    got = vn.prosody(steady, tmp_path / "same.wav", swing_st=3.0)
    assert got["pace_effective"] == 1.0 and (tmp_path / "same.wav").read_bytes() == steady.read_bytes()
    for bad in ({"swing_st": 0.1}, {"median_hz": 20}, {"pace": 3.0}):
        with pytest.raises(vn.VoiceNoteError):
            vn.prosody(steady, tmp_path / "x.wav", **bad)


def test_say_with_pitch_and_pace_scales_the_captions_with_the_speech(tmp_path, monkeypatch):
    pytest.importorskip("parselmouth")
    from noirstudio import ffmpeg
    from noirstudio.voice import ElevenLabsVoice

    mono = _expressive_read(tmp_path, "tts.wav")
    stereo = tmp_path / "tts_stereo.wav"
    ffmpeg.run(["-y", "-i", str(mono), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(stereo)])
    text = "so we should just go with the first one and see what happens"
    tokens = text.split()
    aligned = [{"text": w, "start": round(0.3 + i * 0.3, 3), "end": round(0.3 + i * 0.3 + 0.25, 3)} for i, w in enumerate(tokens)]

    def fake_send(self, method, path, data, content_type, accept, query=""):
        return json.dumps({"words": aligned}).encode() if path == "/v1/forced-alignment" else stereo.read_bytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(ElevenLabsVoice, "_send", fake_send)
    plain, slow = tmp_path / "plain.ogg", tmp_path / "slow.ogg"
    assert cli.main(["voicenote", "--say", text, str(plain), "--rough", "0"]) == 0
    assert cli.main(["voicenote", "--say", text, str(slow), "--rough", "0", "--pitch", "105", "--pace", "1.25"]) == 0
    a = json.loads((tmp_path / "plain.words.json").read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "slow.words.json").read_text(encoding="utf-8"))
    assert b["swing"]["median_after_hz"] == pytest.approx(105, rel=0.07)
    k = b["swing"]["pace_effective"]
    assert k == pytest.approx(1.25, abs=0.03)
    # a word's time on the captions is the alignment's, scaled by how much the speech was stretched
    first, last = a["words"][0], a["words"][-1]
    assert b["words"][-1]["end"] == pytest.approx(0.35 + (last["end"] - 0.35) * k, abs=0.03)
    assert b["words"][0]["start"] == pytest.approx(0.35 + (first["start"] - 0.35) * k, abs=0.03)
    assert ffmpeg.probe_duration(slow) > ffmpeg.probe_duration(plain) + 0.8


def test_prosody_gives_the_same_bytes_every_time(tmp_path):
    pytest.importorskip("parselmouth")
    from noirstudio import voicenote as vn

    src = _expressive_read(tmp_path)
    a = vn.prosody(src, tmp_path / "a.wav", swing_st=2.5, median_hz=105, pace=1.2)
    b = vn.prosody(src, tmp_path / "b.wav", swing_st=2.5, median_hz=105, pace=1.2)
    assert (tmp_path / "a.wav").read_bytes() == (tmp_path / "b.wav").read_bytes()  # Praat's random draws are seeded
    assert a == b
    c = vn.prosody(src, tmp_path / "c.wav", swing_st=2.5, median_hz=105, pace=1.2, seed=8)
    assert (tmp_path / "c.wav").read_bytes() != (tmp_path / "a.wav").read_bytes()  # a different seed, a different draw


def test_pitch_is_read_the_same_before_and_after_the_phone_chain(tmp_path):
    """The chain's 100 Hz high-pass takes the fundamental out of a processed read but not out of his raw note."""
    from noirstudio import voicenote as vn

    f0 = lambda tt: 100 * 2 ** ((3.0 * np.sin(2 * np.pi * 0.8 * tt) + 1.0 * np.sin(2 * np.pi * 3.2 * tt)) / 12)
    n = int(1.1 * RATE)
    tt = np.arange(n) / RATE
    phase = 2 * np.pi * np.cumsum(f0(tt)) / RATE
    # a voice whose first two harmonics are weak next to the formant region, as a phone-band male voice is
    vowel = sum((0.05 if k == 1 else 0.3 if k == 2 else 1.0 / k ** 0.5) * np.sin(k * phase) for k in range(1, 40))
    vowel = 0.2 * vowel * np.hanning(n) ** 0.4 / np.abs(vowel).max()
    read = write(tmp_path / "raw.wav", np.concatenate([hush(0.3)] + [np.concatenate([vowel, hush(0.35, seed=i)]) for i in range(4)]))
    processed = tmp_path / "chain.ogg"
    vn.render(read, processed, vn.NoteStyle(rough=3, noise_db=-95))
    a, b = vp.voiceprint(read, levels=False), vp.voiceprint(processed, levels=False)
    assert b["f0_sd_st"] == pytest.approx(a["f0_sd_st"], abs=0.35)
    assert b["f0_median_hz"] == pytest.approx(a["f0_median_hz"], rel=0.04)


def _seam_clip(path, fall_ms=0.0, floor_db=-50.0, wander_db=0.0, swell_db=0.0, gap_floor_db=None, seed=1, notches=()):
    """Three bursts of a 130 Hz voice with two 1 s pauses between them (and a 150 ms gap inside the last burst), each burst
    falling to the floor over `fall_ms`; the floor is noise at `floor_db`, wandering by `wander_db` (5 Hz) and rising by
    `swell_db` over each pause, and at `gap_floor_db` (else the same) inside the short gap. The floor drops out to nothing for
    20 ms (a fade out and in over 10 ms) at each of `notches` (seconds)."""
    np = pytest.importorskip("numpy")
    rate = 16000
    rng = np.random.RandomState(seed)
    t = np.arange(int(6.0 * rate)) / rate
    bursts = [(0.3, 1.4), (2.4, 3.5), (4.5, 4.9), (5.05, 5.4)]
    env = np.zeros_like(t)
    for a, b in bursts:
        env[(t >= a) & (t < b)] = 1.0
        k = int(fall_ms / 1000 * rate)
        if k:
            i = int(b * rate)
            env[i:i + k] = np.maximum(env[i:i + k], np.linspace(1.0, 0.0, k))
    voice = 0.1 * np.sin(2 * np.pi * 130 * t) * env * (0.7 + 0.3 * np.sin(2 * np.pi * 4 * t))
    level = floor_db + wander_db * np.sin(2 * np.pi * 5 * t)
    for a, b in ((1.4, 2.4), (3.5, 4.5)):
        mask = (t >= a) & (t < b)
        level[mask] += swell_db * (t[mask] - a)
    if gap_floor_db is not None:
        gap = (t >= 4.9) & (t < 5.05)
        level[gap] = gap_floor_db
    noise = 10 ** (level / 20) * rng.randn(len(t))
    for c in notches:
        noise *= np.minimum(1.0, np.abs(t - c) / 0.010)
    x = voice + noise
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def test_seams_tell_a_cliff_from_a_decay(tmp_path):
    from noirstudio.voiceprint import seams

    cliff = seams(_seam_clip(tmp_path / "cliff.wav", fall_ms=0))
    decay = seams(_seam_clip(tmp_path / "decay.wav", fall_ms=150))
    assert cliff["pauses"] == decay["pauses"] == 2 and cliff["short_gaps"] == 1
    assert cliff["fall_ms"] < 15 and decay["fall_ms"] > 30  # speech that stops at once, and speech that dies away
    assert cliff["fall_ms"] < decay["fall_ms"] / 2
    assert 22 < cliff["depth_db"] < 32 and -52 < cliff["floor_db"] < -48  # 30 dB of voice over a floor at -50


def test_seams_read_a_wandering_or_swelling_floor(tmp_path):
    from noirstudio.voiceprint import seams

    steady = seams(_seam_clip(tmp_path / "steady.wav", fall_ms=40))
    wander = seams(_seam_clip(tmp_path / "wander.wav", fall_ms=40, wander_db=4.0))
    swell = seams(_seam_clip(tmp_path / "swell.wav", fall_ms=40, swell_db=8.0))
    assert steady["floor_sd_db"] < 0.6 and abs(steady["swell_db"]) < 1.5
    assert wander["floor_sd_db"] > 1.5 > steady["floor_sd_db"]  # a floor that moves from one 50 ms to the next
    assert 4 < swell["swell_db"] < 9 and swell["floor_sd_db"] > steady["floor_sd_db"]  # an AGC letting go of the floor


def test_seams_count_the_dropouts_in_a_floor(tmp_path):
    """A looped room bed joined bare dropped out for 20 ms at every join. A plain floor has none."""
    from noirstudio.voiceprint import seams

    plain = seams(_seam_clip(tmp_path / "plain.wav", fall_ms=40))
    notched = seams(_seam_clip(tmp_path / "notched.wav", fall_ms=40, notches=(1.7, 1.95, 2.2, 3.8, 4.05, 4.3)))
    assert plain["dips_per_s"] == 0
    assert notched["dips_per_s"] >= 2  # three in the 0.8 s inside each pause
    assert notched["floor_db"] == pytest.approx(plain["floor_db"], abs=1.0)  # the median floor does not show them


def test_seams_do_not_time_a_fall_that_barely_clears_the_floor(tmp_path):
    """Harriet checked the tool on his real notes: with speech only 12 dB over the floor the two thresholds are 1 dB apart and
    the fall was always "0 ms"."""
    np = pytest.importorskip("numpy")
    from noirstudio.voiceprint import seams

    rate = 16000
    rng = np.random.RandomState(4)
    t = np.arange(int(6.0 * rate)) / rate
    amp = np.zeros_like(t)
    amp[(t >= 0.3) & (t < 1.4)] = 0.1  # loud, then a pause
    amp[(t >= 2.4) & (t < 3.0)] = 0.1  # loud again, then trailing off to a soft end (about 12 dB over the floor)
    amp[(t >= 3.0) & (t < 3.5)] = 0.018
    amp[(t >= 4.5) & (t < 5.4)] = 0.1
    x = amp * np.sin(2 * np.pi * 130 * t) + 10 ** (-50 / 20) * rng.randn(len(t))
    path = tmp_path / "soft.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    rows = seams(path)["rows"]
    assert len(rows) == 2
    assert "fall_ms" in rows[0] and rows[0]["fall_ms"] >= 0 and rows[0]["depth_db"] > 25  # the loud one is timed
    assert rows[1]["speech_before_db"] - rows[1]["floor_db"] < 16 and "fall_ms" not in rows[1]  # the soft one is not guessed at


def test_a_wandering_floor_does_not_start_the_rise_early(tmp_path):
    """On his loud-floor notes a frame 130 ms before an onset that dipped under floor+3 dB started the clock: 330 ms for a 50 ms rise."""
    from noirstudio.voiceprint import seams

    calm = seams(_seam_clip(tmp_path / "calm.wav", fall_ms=40))
    wandering = seams(_seam_clip(tmp_path / "wandering.wav", fall_ms=40, wander_db=6.0))
    assert calm["rise_ms"] <= 20 and wandering["rise_ms"] <= 30  # the onsets are abrupt in both
    assert wandering["floor_sd_db"] > 2  # and the second floor really does wander


def test_seams_compare_the_floor_of_the_pauses_with_the_floor_of_the_gaps(tmp_path):
    from noirstudio.voiceprint import seams

    even = seams(_seam_clip(tmp_path / "even.wav", fall_ms=40))
    louder_gaps = seams(_seam_clip(tmp_path / "gaps.wav", fall_ms=40, gap_floor_db=-47.5))
    assert abs(even["floor_step_db"]) < 3  # the same background everywhere
    assert -4 < louder_gaps["floor_step_db"] < -1.5  # the pauses sit 2.5 dB under the gaps between words (a gap much louder is not a gap: it is speech)


def test_seams_cli_sets_ours_next_to_his(tmp_path, capsys):
    his = [_seam_clip(tmp_path / f"his{i}.wav", fall_ms=100, seed=i) for i in (1, 2, 3)]
    ours = _seam_clip(tmp_path / "ours.wav", fall_ms=0)
    assert cli.main(["voiceprint", "--seams", *map(str, his), "--vs", str(ours)]) == 0
    out = capsys.readouterr().out
    assert "3 clips, 6 pauses" in out and "fall_ms" in out and "below it" in out  # ours falls faster than his middle half
    assert "ours, clip by clip:" in out and "ours.wav: 2 pauses" in out
    assert cli.main(["voiceprint", "--seams", str(his[0]), "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["his_summary"]["pauses"] == 2 and got["his"][0]["rows"][0]["length_s"] == pytest.approx(1.0, abs=0.1)
    assert cli.main(["voiceprint", "--seams", str(tmp_path / "missing.wav")]) == 1  # nothing to measure: an error, not a crash
