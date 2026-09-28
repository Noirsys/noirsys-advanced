"""noirstudio — turn a script into a finished, captioned vertical video.

A small, dependency-light content pipeline for the Noirsys/Noirpost world:

    spec (YAML)  ->  voice (ElevenLabs cloned TTS, or offline)  ->  word-by-word
    captions  ->  visuals (brand cards / avatar / b-roll)  ->  ffmpeg assembly
    ->  a finished 1080x1920 MP4 + upload metadata (with AI disclosure).

Design goals:
  * Runs with NO API keys in dry-run mode and still produces a real preview MP4,
    so a video can be reviewed before a single credit is spent.
  * `--live` swaps the offline stubs for real ElevenLabs calls (cloned voice with
    character-level timestamps, and the Flows video API for avatar/b-roll scenes).
  * Content-as-code: a video is a reviewable text file. A person approves the
    spec; the machine renders it. Human authority stays at the gate.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
