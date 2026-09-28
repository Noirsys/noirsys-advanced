"""Generated video scenes via the ElevenLabs Flows video API.

Two scene types use it:
  * `avatar` -> `creatify-aurora`: lip-syncs a still image of your avatar to the
    scene's narration audio (your cloned voice), i.e. a talking head.
  * `broll`  -> Veo 3.1 (fast by default): 9:16 generated footage from a prompt.

Both are async: `POST /v1/flows/video` returns an id, then `GET
/v1/flows/video/{id}` is polled until `completed` and the signed `content_url`
is downloaded. Requires a paid ElevenLabs plan with API access to Image & Video.
Offline mode returns None and the pipeline falls back to a brand card.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from .voice import DEFAULT_BASE_URL, ENV_API_KEY


class VideoGenError(RuntimeError):
    pass


class OfflineVideo:
    provider = "offline"

    def avatar(self, image: Path, audio: Path, out_path: Path, **_) -> Optional[Path]:
        return None

    def broll(self, prompt: str, out_path: Path, **_) -> Optional[Path]:
        return None


class FlowsVideo:
    provider = "elevenlabs-flows"

    def __init__(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL,
                 poll_seconds: float = 6.0, timeout_seconds: float = 900.0):
        self.api_key = api_key or os.environ.get(ENV_API_KEY)
        if not self.api_key:
            raise VideoGenError(f"{ENV_API_KEY} is not set")
        self.base_url = base_url.rstrip("/")
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method)
        req.add_header("xi-api-key", self.api_key)
        req.add_header("accept", "application/json")
        if data is not None:
            req.add_header("content-type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:600]
            raise VideoGenError(f"Flows {method} {path} -> HTTP {exc.code}: {detail}") from None

    @staticmethod
    def _inline(path: Path, mime: str) -> dict:
        raw = path.read_bytes()
        if len(raw) > 25 * 1024 * 1024:
            raise VideoGenError(f"{path.name} exceeds the 25MB inline limit; upload via /v1/assets instead")
        return {"type": "inline_base64", "content_base64": base64.b64encode(raw).decode(), "mime_type": mime}

    def _create_and_wait(self, body: dict, out_path: Path) -> Path:
        created = self._request("POST", "/v1/flows/video", body)
        gen_id = created["id"]
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            status = self._request("GET", f"/v1/flows/video/{gen_id}")
            state = status.get("status")
            if state == "completed":
                with urllib.request.urlopen(status["content_url"], timeout=300) as resp:
                    out_path.write_bytes(resp.read())
                return out_path
            if state == "failed":
                raise VideoGenError(
                    f"generation {gen_id} failed: {status.get('failure_reason')}: {status.get('error_message')}"
                )
            time.sleep(self.poll_seconds)
        raise VideoGenError(f"generation {gen_id} timed out after {self.timeout_seconds:.0f}s")

    def avatar(self, image: Path, audio: Path, out_path: Path, resolution: str = "720p") -> Path:
        mime_img = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        mime_aud = "audio/wav" if audio.suffix.lower() == ".wav" else "audio/mpeg"
        body = {
            "model_id": "creatify-aurora",
            "image": self._inline(image, mime_img),
            "audio": self._inline(audio, mime_aud),
            "resolution": resolution,
        }
        return self._create_and_wait(body, out_path)

    def broll(self, prompt: str, out_path: Path, duration: int = 8, aspect: str = "9:16",
              model_id: str = "veo-3.1-fast-generate-001", resolution: str = "720p") -> Path:
        body = {
            "model_id": model_id,
            "prompt": prompt,
            "aspect_ratio": aspect,
            "duration_secs": min(max(int(round(duration)), 4), 8) if "veo" in model_id else int(duration),
            "generate_audio": False,
            "resolution": resolution,
        }
        return self._create_and_wait(body, out_path)


def get_engine(live: bool):
    return FlowsVideo() if live else OfflineVideo()
