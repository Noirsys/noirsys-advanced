"""Locate and run ffmpeg without requiring a system install.

imageio-ffmpeg ships a static ffmpeg binary (with libass, libx264 and
libfreetype), so captions, encoding and text all work in a bare container.
A system `ffmpeg` on PATH is preferred when present.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


class FFmpegError(RuntimeError):
    """Raised when ffmpeg exits non-zero; carries the tail of stderr."""


def ffmpeg_path() -> str:
    """Return a path to an ffmpeg executable, preferring the system one."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - depends on environment
        raise FFmpegError(
            "ffmpeg not found. Install ffmpeg or `pip install imageio-ffmpeg`."
        ) from exc


def run(args: Sequence[str], *, quiet: bool = True) -> str:
    """Run ffmpeg with `args` (excluding the binary) and return stderr text."""
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-25:])
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}):\n  {' '.join(cmd)}\n{tail}")
    if not quiet:
        print(proc.stderr)
    return proc.stderr


_TIME_RE = re.compile(r"time=(\d+):(\d{2}):(\d{2})\.(\d+)")


def probe_duration(path: Path) -> float:
    """Duration in seconds by decoding to the null muxer (no ffprobe needed)."""
    err = run(["-i", str(path), "-f", "null", "-"])
    matches = _TIME_RE.findall(err)
    if not matches:
        raise FFmpegError(f"could not determine duration of {path}")
    h, m, s, frac = matches[-1]
    return int(h) * 3600 + int(m) * 60 + int(s) + float(f"0.{frac}")


def filter_escape(value: str) -> str:
    """Escape a filter-graph argument value (paths with ':' or quotes)."""
    out = value.replace("\\", "\\\\")
    for ch in (":", "'", "[", "]", ",", ";"):
        out = out.replace(ch, "\\" + ch)
    return out
