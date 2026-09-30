"""ElevenLabs voice: eleven_v4 (audio, then forced alignment) and the older with-timestamps path, faked."""

import base64
import json

import pytest

from noirstudio import ffmpeg
from noirstudio.spec import Voice
from noirstudio.voice import ElevenLabsVoice, OfflineVoice, VoiceError, spoken_text, voice_settings


@pytest.fixture(scope="module")
def audio(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("v") / "a.wav"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2", "-c:a", "pcm_s16le", str(path)])
    return path.read_bytes()


class Fake:
    def __init__(self, audio, align=None, fail_align=False):
        self.audio, self.align, self.fail_align, self.calls = audio, align, fail_align, []

    def __call__(self, method, path, data, content_type, accept, query=""):
        self.calls.append((method, path, data, content_type, accept, query))
        if path.startswith("/v1/text-to-speech/") and path.endswith("/with-timestamps"):
            chars = list("Two words")
            starts = [i * 0.1 for i in range(len(chars))]
            return json.dumps({"audio_base64": base64.b64encode(self.audio).decode(), "alignment": {
                "characters": chars, "character_start_times_seconds": starts,
                "character_end_times_seconds": [s + 0.1 for s in starts]}}).encode()
        if path.startswith("/v1/text-to-speech/"):
            return self.audio
        if path == "/v1/forced-alignment":
            if self.fail_align:
                from noirstudio.voice import VoiceError as E
                raise E("HTTP 422")
            return json.dumps(self.align).encode()
        raise AssertionError(path)


def engine(monkeypatch, fake):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    eng = ElevenLabsVoice()
    monkeypatch.setattr(eng, "_send", fake)
    return eng


def test_audio_tags_direct_the_delivery_and_are_not_captioned():
    assert spoken_text("[quietly] He said,  [laughing] no.") == "He said, no."
    assert voice_settings(Voice(model_id="eleven_v4", stability=0.6, similarity_boost=0.8)) == {
        "stability": 0.6, "similarity_boost": 0.8}
    assert "style" in voice_settings(Voice(model_id="eleven_multilingual_v2"))


def test_v4_speaks_then_aligns(monkeypatch, tmp_path, audio):
    fake = Fake(audio, align={"words": [{"text": "He", "start": 0.1, "end": 0.3}, {"text": "said,", "start": 0.3, "end": 0.7},
                                        {"text": "no.", "start": 0.9, "end": 1.4}], "loss": 0.1})
    r = engine(monkeypatch, fake).synthesize("[quietly] He said, [laughing] no.", Voice(voice_id="ZS", model_id="eleven_v4"),
                                             tmp_path / "s.wav")
    (m1, p1, d1, _ct, acc1, q1), (m2, p2, d2, ct2, _a, _q) = fake.calls
    body = json.loads(d1)
    assert (m1, p1, acc1, q1) == ("POST", "/v1/text-to-speech/ZS", "audio/mpeg", "?output_format=mp3_44100_128")
    assert body["text"] == "[quietly] He said, [laughing] no." and set(body["voice_settings"]) == {"stability", "similarity_boost"}
    assert p2 == "/v1/forced-alignment" and ct2.startswith("multipart/form-data; boundary=")
    assert b'name="text"\r\n\r\nHe said, no.\r\n' in d2 and b'name="file"; filename="s.mp3"' in d2
    assert [w.text for w in r.words] == ["He", "said,", "no."] and r.meta["timings"] == "forced-alignment"
    assert 1.9 <= r.duration <= 2.1 and (tmp_path / "s.mp3").exists()


def test_v4_gives_the_word_the_aligner_dropped_at_the_end_an_estimated_time(monkeypatch, tmp_path, audio):
    """Round 5: "machine" had no time in either L3 take, so a caption would have lost the end of the line."""
    fake = Fake(audio, align={"words": [{"text": "He", "start": 0.1, "end": 0.3}, {"text": "said,", "start": 0.3, "end": 0.7}],
                              "loss": 0.1})
    r = engine(monkeypatch, fake).synthesize("He said, no.", Voice(voice_id="ZS", model_id="eleven_v4"), tmp_path / "s.wav")
    assert [w.text for w in r.words] == ["He", "said,", "no."] and r.meta["timings"] == "forced-alignment"
    assert r.meta["tail_estimated"] == 1
    assert r.words[2].start == pytest.approx(0.7) and 0.7 < r.words[2].end <= r.duration  # after the last aligned word, inside the audio


def test_a_word_missing_from_the_middle_is_not_guessed_at(monkeypatch, tmp_path, audio):
    fake = Fake(audio, align={"words": [{"text": "He", "start": 0.1, "end": 0.3}, {"text": "no.", "start": 0.9, "end": 1.4}],
                              "loss": 0.1})
    r = engine(monkeypatch, fake).synthesize("He said, no.", Voice(voice_id="ZS", model_id="eleven_v4"), tmp_path / "s.wav")
    assert [w.text for w in r.words] == ["He", "no."] and "tail_estimated" not in r.meta  # something else is wrong: leave it


def test_v4_estimates_over_the_real_duration_when_alignment_fails(monkeypatch, tmp_path, audio):
    r = engine(monkeypatch, Fake(audio, fail_align=True)).synthesize(
        "One two three four.", Voice(voice_id="ZS", model_id="eleven_v4"), tmp_path / "s.wav")
    assert [w.text for w in r.words] == ["One", "two", "three", "four."] and r.meta["timings"].startswith("estimated (")
    assert r.words[-1].end == pytest.approx(r.duration - 0.45, abs=0.01)


def test_older_models_keep_with_timestamps(monkeypatch, tmp_path, audio):
    fake = Fake(audio)
    r = engine(monkeypatch, fake).synthesize("[laughing] Two words", Voice(voice_id="XW", model_id="eleven_multilingual_v2"),
                                             tmp_path / "s.wav")
    (_m, path, data, *_rest), = fake.calls
    assert path == "/v1/text-to-speech/XW/with-timestamps" and json.loads(data)["text"] == "Two words"
    assert [w.text for w in r.words] == ["Two", "words"] and r.meta["timings"] == "with-timestamps"


def test_offline_preview_skips_tags(tmp_path):
    r = OfflineVoice().synthesize("[whispering] Quiet now.", Voice(), tmp_path / "o.wav")
    assert [w.text for w in r.words] == ["Quiet", "now."]


def test_live_needs_a_voice_id(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    with pytest.raises(VoiceError, match="voice_id"):
        ElevenLabsVoice().synthesize("hi", Voice(), None)


def test_a_stalled_read_is_a_voice_error_and_alignment_is_asked_twice(monkeypatch, tmp_path, audio):
    import socket
    import urllib.request

    def stalls(req, timeout=None):
        raise socket.timeout("The read operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", stalls)
    with pytest.raises(VoiceError, match="timed out"):  # not a bare TimeoutError that kills the whole take
        ElevenLabsVoice(api_key="k").list_voices()

    calls = []

    def flaky(self, method, path, data, content_type, accept, query=""):
        calls.append(path)
        if len(calls) == 1:
            raise VoiceError("ElevenLabs POST /v1/forced-alignment: timed out after 120 s")
        return json.dumps({"words": [{"text": "hi", "start": 0.1, "end": 0.4}]}).encode()

    monkeypatch.setattr(ElevenLabsVoice, "_send", flaky)
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(audio)
    words = ElevenLabsVoice(api_key="k").align(mp3, "hi")
    assert len(calls) == 2 and [w.text for w in words] == ["hi"]

    calls.clear()

    def always_stalls(self, method, path, data, content_type, accept, query=""):
        calls.append(path)
        raise VoiceError("ElevenLabs POST /v1/forced-alignment: timed out after 120 s")

    monkeypatch.setattr(ElevenLabsVoice, "_send", always_stalls)
    with pytest.raises(VoiceError, match="timed out"):  # twice, then the caller degrades to estimated timings
        ElevenLabsVoice(api_key="k").align(mp3, "hi")
    assert len(calls) == 2
