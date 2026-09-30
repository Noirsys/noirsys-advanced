"""Voice synthesis: ElevenLabs cloned voice with word timings, or an offline stub.

Word timings drive the word-by-word captions:
- `eleven_v4` (his clone and Harriet both speak v4) has no `/with-timestamps`,
  so the audio comes from `POST /v1/text-to-speech/{voice_id}` and the timings
  from `POST /v1/forced-alignment` on that audio. v4 takes audio tags in the
  text (`[laughing]`, `[quietly]`): they direct the delivery, they are not said,
  so captions and alignment use the text without them. v4 has stability and
  similarity only: no style, speed or speaker boost.
- older models return audio plus character timings from `/with-timestamps`.
If alignment fails, timings are estimated over the real duration.
Offline mode writes silence of the estimated duration and estimates word
timings, so the whole pipeline can be previewed for free.
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import uuid
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import ffmpeg
from .captions import Word, estimate_duration, estimate_words, normalize_text, words_from_alignment
from .spec import Voice

DEFAULT_BASE_URL = "https://api.elevenlabs.io"
ENV_API_KEY = "ELEVENLABS_API_KEY"


class VoiceError(RuntimeError):
    pass


_TAG = re.compile(r"\[[^\[\]\n]{1,48}\]")


def is_v4(model_id: str) -> bool:
    return model_id.startswith("eleven_v4")


def takes_audio_tags(model_id: str) -> bool:
    return model_id.startswith(("eleven_v4", "eleven_v3"))


def spoken_text(text: str) -> str:
    """What is heard: audio tags like [laughing] direct the delivery and are not said."""
    return normalize_text(_TAG.sub(" ", text))


def voice_settings(voice: Voice) -> Dict[str, object]:
    settings: Dict[str, object] = {"stability": voice.stability, "similarity_boost": voice.similarity_boost}
    if not is_v4(voice.model_id):  # v4 has no style, speed or speaker-boost controls
        settings.update(style=voice.style, speed=voice.speed, use_speaker_boost=True)
    return settings


def fit_words(words: List[Word], duration: float, tail: float = 0.45) -> List[Word]:
    """Stretch estimated timings so the last word ends just before the audio does."""
    if not words or words[-1].end <= 0:
        return words
    k = max(duration - tail, 0.1) / words[-1].end
    return [Word(w.text, w.start * k, w.end * k) for w in words]


@dataclass
class VoiceResult:
    audio_path: Path
    words: List[Word]
    duration: float
    provider: str
    meta: dict = field(default_factory=dict)


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def to_wav(src: Path, dst: Path, sample_rate: int = 48000) -> Path:
    """Normalise any audio to 48 kHz stereo PCM WAV (uniform input for concat)."""
    ffmpeg.run(["-y", "-i", str(src), "-ar", str(sample_rate), "-ac", "2", "-c:a", "pcm_s16le", str(dst)])
    return dst


class OfflineVoice:
    """No network, no credits: silence sized to the estimated speech duration."""

    provider = "offline"

    def synthesize(self, text: str, voice: Voice, out_path: Path) -> VoiceResult:
        text = spoken_text(text)
        duration = estimate_duration(text, voice.words_per_minute)
        ffmpeg.run(
            [
                "-y",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", f"{duration:.3f}",
                "-c:a", "pcm_s16le", str(out_path),
            ]
        )
        words = estimate_words(text, voice.words_per_minute)
        return VoiceResult(out_path, words, _wav_duration(out_path), self.provider, {"estimated": True})


class ElevenLabsVoice:
    provider = "elevenlabs"

    def __init__(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL, timeout: int = 120):
        self.api_key = api_key or os.environ.get(ENV_API_KEY)
        if not self.api_key:
            raise VoiceError(f"{ENV_API_KEY} is not set; run without --live for an offline preview")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- http -------------------------------------------------------------
    def _send(self, method: str, path: str, data: Optional[bytes], content_type: str, accept: str,
              query: str = "") -> bytes:
        req = urllib.request.Request(f"{self.base_url}{path}{query}", data=data, method=method)
        req.add_header("xi-api-key", self.api_key)
        req.add_header("accept", accept)
        if data is not None:
            req.add_header("content-type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:600]
            raise VoiceError(f"ElevenLabs {method} {path} -> HTTP {exc.code}: {detail}") from None
        except urllib.error.URLError as exc:
            raise VoiceError(f"ElevenLabs {method} {path}: {exc.reason}") from None
        except (socket.timeout, TimeoutError):  # a read that stalls after the connection is up isn't a URLError
            raise VoiceError(f"ElevenLabs {method} {path}: timed out after {self.timeout} s") from None

    def _request(self, method: str, path: str, body: Optional[dict] = None, query: str = "") -> dict:
        data = json.dumps(body).encode() if body is not None else None
        return json.loads(self._send(method, path, data, "application/json", "application/json", query).decode())

    # -- api --------------------------------------------------------------
    def list_voices(self) -> List[dict]:
        data = self._request("GET", "/v1/voices")
        return [
            {"voice_id": v.get("voice_id"), "name": v.get("name"), "category": v.get("category")}
            for v in data.get("voices", [])
        ]

    def align(self, audio_path: Path, text: str) -> List[Word]:
        """Word timings for audio we already have: `POST /v1/forced-alignment`."""
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="text"\r\n\r\n{text}\r\n'.encode(),
                 (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'
                  "Content-Type: audio/mpeg\r\n\r\n").encode() + audio_path.read_bytes() + b"\r\n",
                 f"--{boundary}--\r\n".encode()]
        for attempt in (1, 2):  # the endpoint has taken 54 s and more than 120 s for the same request: ask twice
            try:
                raw = self._send("POST", "/v1/forced-alignment", b"".join(parts),
                                 f"multipart/form-data; boundary={boundary}", "application/json")
                break
            except VoiceError as exc:
                if attempt == 2 or "timed out" not in str(exc):
                    raise
        data = json.loads(raw.decode())
        return [Word(str(w["text"]), float(w["start"]), float(w["end"]))
                for w in data.get("words") or [] if str(w.get("text", "")).strip()]

    def synthesize(self, text: str, voice: Voice, out_path: Path) -> VoiceResult:
        if not voice.voice_id:
            raise VoiceError("voice.voice_id is required in live mode (see `noirstudio voices`)")
        heard = spoken_text(text)
        body = {"text": normalize_text(text) if takes_audio_tags(voice.model_id) else heard,
                "model_id": voice.model_id, "voice_settings": voice_settings(voice)}
        mp3_path = out_path.with_suffix(".mp3")
        meta: Dict[str, object] = {"model_id": voice.model_id, "voice_id": voice.voice_id, "mp3": str(mp3_path)}
        if is_v4(voice.model_id):
            mp3_path.write_bytes(self._send("POST", f"/v1/text-to-speech/{voice.voice_id}", json.dumps(body).encode(),
                                            "application/json", "audio/mpeg", query="?output_format=mp3_44100_128"))
            to_wav(mp3_path, out_path)
            try:
                words, meta["timings"] = self.align(mp3_path, heard), "forced-alignment"
            except VoiceError as exc:
                words, meta["timings"] = [], f"estimated ({exc})"
        else:
            data = self._request("POST", f"/v1/text-to-speech/{voice.voice_id}/with-timestamps", body,
                                 query="?output_format=mp3_44100_128")
            mp3_path.write_bytes(base64.b64decode(data["audio_base64"]))
            to_wav(mp3_path, out_path)
            align = data.get("alignment") or data.get("normalized_alignment") or {}
            words = words_from_alignment(
                align.get("characters", []),
                align.get("character_start_times_seconds", []),
                align.get("character_end_times_seconds", []),
            )
            meta["timings"] = "with-timestamps"
        duration = _wav_duration(out_path)
        if not words:  # no alignment: estimate, stretched over the real duration
            words = fit_words(estimate_words(heard, voice.words_per_minute), duration)
            if not str(meta.get("timings", "")).startswith("estimated"):
                meta["timings"] = "estimated"
        return VoiceResult(out_path, words, duration, self.provider, meta)


def get_engine(live: bool):
    return ElevenLabsVoice() if live else OfflineVoice()
