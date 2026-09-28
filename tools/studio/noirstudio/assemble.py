"""ffmpeg assembly: per-scene clips -> concat -> burn captions -> optional music."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from . import ffmpeg
from .spec import Output

_VIDEO_CODEC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
_AUDIO_CODEC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def _fit_filter(output: Output, cover: bool) -> str:
    w, h = output.width, output.height
    if cover:
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"


def clip_from_image(image: Path, audio: Path, duration: float, output: Output, path: Path, motion: bool = True) -> Path:
    """A still (card) held for `duration`, with an optional slow push-in."""
    frames = max(int(round(duration * output.fps)), 1)
    vf = [_fit_filter(output, cover=False)]
    if motion:
        vf.append(
            f"zoompan=z='min(zoom+0.0004,1.06)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={output.width}x{output.height}:fps={output.fps}"
        )
    vf.append("format=yuv420p")
    ffmpeg.run(
        [
            "-y",
            "-loop", "1", "-framerate", str(output.fps), "-i", str(image),
            "-i", str(audio),
            "-t", f"{duration:.3f}",
            "-vf", ",".join(vf),
            "-r", str(output.fps),
            *_VIDEO_CODEC, *_AUDIO_CODEC,
            "-shortest", str(path),
        ]
    )
    return path


def clip_from_video(video: Path, audio: Path, duration: float, output: Output, path: Path) -> Path:
    """Generated/user footage cropped to the frame, looped if short, re-muxed with the narration."""
    ffmpeg.run(
        [
            "-y",
            "-stream_loop", "-1", "-i", str(video),
            "-i", str(audio),
            "-t", f"{duration:.3f}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", _fit_filter(output, cover=True) + ",format=yuv420p",
            "-r", str(output.fps),
            *_VIDEO_CODEC, *_AUDIO_CODEC,
            "-shortest", str(path),
        ]
    )
    return path


def concat(clips: Sequence[Path], path: Path) -> Path:
    """Stream-copy concat of uniformly encoded clips (concat demuxer)."""
    listing = path.with_suffix(".txt")
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
    ffmpeg.run(["-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(path)])
    return path


def burn_captions(video: Path, ass: Path, fonts_dir: Path, path: Path) -> Path:
    vf = f"ass=filename={ffmpeg.filter_escape(str(ass))}:fontsdir={ffmpeg.filter_escape(str(fonts_dir))}"
    ffmpeg.run(
        [
            "-y", "-i", str(video),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(path),
        ]
    )
    return path


def mix_music(video: Path, music: Path, gain_db: float, path: Path) -> Path:
    """Loop a (rights-cleared) music bed under the narration at `gain_db`."""
    ffmpeg.run(
        [
            "-y", "-i", str(video),
            "-stream_loop", "-1", "-i", str(music),
            "-filter_complex",
            f"[1:a]volume={gain_db}dB[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", *_AUDIO_CODEC,
            "-movflags", "+faststart",
            str(path),
        ]
    )
    return path


def finalize_copy(video: Path, path: Path) -> Path:
    """No captions: still write a faststart mp4 at the final path."""
    ffmpeg.run(["-y", "-i", str(video), "-c", "copy", "-movflags", "+faststart", str(path)])
    return path
