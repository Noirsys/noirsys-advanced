"""Voice synthesis: ElevenLabs cloned voice with timestamps, or an offline stub.

Live mode uses `POST /v1/text-to-speech/{voice_id}/with-timestamps`, which
returns the audio plus character-level start/end times — the source of the
word-by-word captions. Offline mode writes silence of the estimated duration
and estimates word timings, so the whole pipeline can be previewed for free.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import ffmpeg
from .captions import Word, estimate_duration, estimate_words, normalize_text, words_from_alignment
from .spec import Voice

DEFAULT_BASE_URL = "https://api.elevenlabs.io"
ENV_API_KEY = "ELEVENLABS_API_KEY"


class VoiceError(RuntimeError):
    pass


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
        text = normalize_text(text)
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
    def _request(self, method: str, path: str, body: Optional[dict] = None, query: str = "") -> dict:
        url = f"{self.base_url}{path}{query}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("xi-api-key", self.api_key)
        req.add_header("accept", "application/json")
        if data is not None:
            req.add_header("content-type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:600]
            raise VoiceError(f"ElevenLabs {method} {path} -> HTTP {exc.code}: {detail}") from None

    # -- api --------------------------------------------------------------
    def list_voices(self) -> List[dict]:
        data = self._request("GET", "/v1/voices")
        return [
            {"voice_id": v.get("voice_id"), "name": v.get("name"), "category": v.get("category")}
            for v in data.get("voices", [])
        ]

    def synthesize(self, text: str, voice: Voice, out_path: Path) -> VoiceResult:
        if not voice.voice_id:
            raise VoiceError("voice.voice_id is required in live mode (see `noirstudio voices`)")
        text = normalize_text(text)
        body = {
            "text": text,
            "model_id": voice.model_id,
            "voice_settings": {
                "stability": voice.stability,
                "similarity_boost": voice.similarity_boost,
                "style": voice.style,
                "speed": voice.speed,
                "use_speaker_boost": True,
            },
        }
        data = self._request(
            "POST",
            f"/v1/text-to-speech/{voice.voice_id}/with-timestamps",
            body,
            query="?output_format=mp3_44100_128",
        )
        mp3_path = out_path.with_suffix(".mp3")
        mp3_path.write_bytes(base64.b64decode(data["audio_base64"]))
        to_wav(mp3_path, out_path)
        align = data.get("alignment") or data.get("normalized_alignment") or {}
        words = words_from_alignment(
            align.get("characters", []),
            align.get("character_start_times_seconds", []),
            align.get("character_end_times_seconds", []),
        )
        if not words:  # alignment missing: fall back to an estimate over the real duration
            words = estimate_words(text, voice.words_per_minute)
        return VoiceResult(
            out_path,
            words,
            _wav_duration(out_path),
            self.provider,
            {"model_id": voice.model_id, "voice_id": voice.voice_id, "mp3": str(mp3_path)},
        )


def get_engine(live: bool):
    return ElevenLabsVoice() if live else OfflineVoice()
