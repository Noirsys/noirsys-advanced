"""Where a vertical video's text sits, against the UI the platforms draw over it.

Shorts, Reels and TikTok lay their own buttons, titles and captions over the
picture. The box that is clear on all of them (Google's vertical safe zones,
Meta's 14% top / 35% bottom / 6% sides, TikTok's in-feed template with its
button column; sources in strategy/04), on a 1080x1920 frame:

    x 120-888, y 288-1248, and left of x 780 below y 840

`audit` samples frames, takes the bright foreground (text, cards, waveforms;
the backgrounds here are near-black) and reports how often it enters each
unsafe zone. Any frame size works: zones scale with the frame.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image

from . import ffmpeg

REF_W, REF_H = 1080, 1920
# name -> (x0, y0, x1, y1) in 1080x1920 reference pixels
ZONES: Dict[str, Tuple[int, int, int, int]] = {
    "top": (0, 0, 1080, 288),          # status bar, search, menu
    "bottom": (0, 1248, 1080, 1920),   # title, channel, caption, music
    "left": (0, 0, 120, 1920),
    "right": (888, 0, 1080, 1920),     # like / comment / share / remix
    "buttons": (780, 840, 1080, 1920),  # TikTok's column plus its margin
}
SAFE_BOX = (120, 288, 888, 1248)


def _frames(video: Path, fps: float, width: int, height: int):
    """Yield (seconds, grayscale PIL image) at `fps`, scaled to width x height, via one ffmpeg pipe."""
    cmd = [ffmpeg.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-vf", f"fps={fps},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    size = width * height
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        i = 0
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield (i + 0.5) / fps, Image.frombytes("L", (width, height), buf)
            i += 1


def audit(video: Path, fps: float = 1.0, threshold: int = 110, min_pixels: int = 40,
          width: int = 540, height: int = 960) -> dict:
    """How often bright content enters each unsafe zone (a frame counts past `min_pixels` there)."""
    sx, sy = width / REF_W, height / REF_H
    boxes = {k: (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy)) for k, (x0, y0, x1, y1) in ZONES.items()}
    per_zone = {k: {"frames": 0, "worst_s": None, "worst_pixels": 0} for k in ZONES}
    union = None
    n = 0
    for t, im in _frames(video, fps, width, height):
        n += 1
        mask = im.point(lambda v: 255 if v > threshold else 0)
        bbox = mask.getbbox()
        if bbox:
            union = bbox if union is None else (min(union[0], bbox[0]), min(union[1], bbox[1]),
                                                max(union[2], bbox[2]), max(union[3], bbox[3]))
        for k, box in boxes.items():
            count = mask.crop(box).histogram()[255]
            if count >= min_pixels:
                z = per_zone[k]
                z["frames"] += 1
                if count > z["worst_pixels"]:
                    z["worst_s"], z["worst_pixels"] = round(t, 1), count
    if n == 0:
        raise ValueError(f"no frames read from {video}")
    extents = None if union is None else [round(union[0] / sx), round(union[1] / sy), round(union[2] / sx), round(union[3] / sy)]
    return {
        "video": str(video), "frames": n, "fps": fps, "content_extents": extents, "safe_box": list(SAFE_BOX),
        "zones": {k: {"share": round(v["frames"] / n, 3), "frames": v["frames"], "worst_s": v["worst_s"]} for k, v in per_zone.items()},
    }


def verdict(report: dict, tolerance: float = 0.05) -> List[str]:
    """Plain-language warnings for zones entered in more than `tolerance` of frames."""
    labels = {"top": "the top band (y < 288)", "bottom": "the bottom band (y > 1248)", "left": "the left edge (x < 120)",
              "right": "the right edge (x > 888), under the like/comment/share buttons",
              "buttons": "TikTok's button column (x > 780 below y 840)"}
    out = []
    for k, z in report["zones"].items():
        if z["share"] > tolerance:
            out.append(f"content in {labels[k]} in {z['share']:.0%} of frames (worst near {z['worst_s']}s)")
    return out
