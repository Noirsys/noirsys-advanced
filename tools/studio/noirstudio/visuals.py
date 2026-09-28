"""Brand cards rendered with Pillow: title, stat, quote, list, plain — plus the
thumbnail. These are the offline visual layer and the fallback for any scene
whose generated video is unavailable.

Layout keeps text inside a safe band (platform UI covers the top ~250px and
bottom ~420px of a vertical video; captions sit around 70% height).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .brandkit import BrandKit, hex_to_rgb
from .spec import Output, Scene, VideoSpec

Font = ImageFont.FreeTypeFont


def _font(path: Path, size: int) -> Font:
    return ImageFont.truetype(str(path), size)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: Font) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def wrap(draw: ImageDraw.ImageDraw, text: str, font: Font, max_width: int) -> List[str]:
    """Greedy word wrap by measured pixel width."""
    words = text.split()
    lines: List[str] = []
    cur: List[str] = []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and _text_width(draw, trial, font) > max_width:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def fit_font(draw: ImageDraw.ImageDraw, text: str, path: Path, max_width: int, max_lines: int,
             start: int, floor: int = 40) -> Tuple[Font, List[str]]:
    """Shrink the font until the text wraps into at most `max_lines` lines."""
    size = start
    while size > floor:
        font = _font(path, size)
        lines = wrap(draw, text, font, max_width)
        if len(lines) <= max_lines and all(_text_width(draw, l, font) <= max_width for l in lines):
            return font, lines
        size -= 4
    font = _font(path, floor)
    return font, wrap(draw, text, font, max_width)[:max_lines]


def _background(size: Tuple[int, int], brand: BrandKit, glow: str) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, hex_to_rgb(brand.bg))
    # vertical gradient bg -> surface
    top, bot = hex_to_rgb(brand.bg), hex_to_rgb(brand.surface)
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    img.paste(grad.resize(size))
    # soft accent glow, top-left
    glow_layer = Image.new("RGB", size, (0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    r = int(w * 0.55)
    gd.ellipse((-r * 0.4, -r * 0.5, r * 0.9, r * 0.6), fill=hex_to_rgb(glow))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=w * 0.18))
    img = Image.blend(img, Image.composite(glow_layer, img, glow_layer.convert("L")), 0.28)
    # faint grid
    d = ImageDraw.Draw(img)
    line = hex_to_rgb(brand.line)
    step = 120
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=line, width=1)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=line, width=1)
    return img


def _chrome(img: Image.Image, brand: BrandKit, badge: Optional[str]) -> None:
    """Wordmark, accent rule and footer URL."""
    w, h = img.size
    d = ImageDraw.Draw(img)
    mono = _font(brand.font_mono, int(w * 0.034))
    pad = int(w * 0.075)
    y = int(h * 0.145)
    d.text((pad, y), brand.wordmark, font=mono, fill=hex_to_rgb(brand.ink))
    d.rectangle((pad, y + int(w * 0.06), pad + int(w * 0.12), y + int(w * 0.06) + 6), fill=hex_to_rgb(brand.accent))
    foot = _font(brand.font_mono, int(w * 0.03))
    d.text((pad, int(h * 0.875)), brand.url, font=foot, fill=hex_to_rgb(brand.muted))
    if badge:
        bf = _font(brand.font_mono, int(w * 0.026))
        tw = _text_width(d, badge, bf)
        x1, y1 = w - pad, y + int(w * 0.02)
        x0, y0 = x1 - tw - 40, y1 - int(w * 0.03)
        d.rounded_rectangle((x0, y0, x1, y1 + int(w * 0.03)), radius=14, outline=hex_to_rgb(brand.accent2), width=3)
        d.text((x0 + 20, y0 + 8), badge, font=bf, fill=hex_to_rgb(brand.accent2))


def render_card(scene: Scene, brand: BrandKit, output: Output, path: Path, badge: Optional[str] = None) -> Path:
    w, h = output.width, output.height
    glow = {"title": brand.accent, "stat": brand.accent2, "quote": brand.accent3, "list": brand.accent, "plain": brand.accent2}
    img = _background((w, h), brand, glow.get(scene.style, brand.accent))
    _chrome(img, brand, badge)
    d = ImageDraw.Draw(img)
    pad = int(w * 0.075)
    max_w = w - 2 * pad
    ink, muted, accent = hex_to_rgb(brand.ink), hex_to_rgb(brand.muted), hex_to_rgb(brand.accent)
    y = int(h * 0.27)

    if scene.style == "stat" and scene.stat:
        stat_font, _ = fit_font(d, scene.stat, brand.font_display, max_w, 1, int(w * 0.26), floor=int(w * 0.12))
        d.text((pad, y), scene.stat, font=stat_font, fill=hex_to_rgb(brand.accent2))
        y += int(stat_font.size * 1.15)
        if scene.title:
            f, lines = fit_font(d, scene.title, brand.font_sans, max_w, 3, int(w * 0.075))
            for line in lines:
                d.text((pad, y), line, font=f, fill=ink)
                y += int(f.size * 1.2)
    else:
        headline = scene.title or (scene.text if scene.style != "plain" else "")
        if headline:
            if scene.style == "quote":
                headline = f"“{headline}”"
            f, lines = fit_font(d, headline, brand.font_display, max_w, 5, int(w * 0.105))
            for line in lines:
                d.text((pad, y), line, font=f, fill=ink)
                y += int(f.size * 1.08)
        if scene.subtitle:
            y += int(h * 0.02)
            f, lines = fit_font(d, scene.subtitle, brand.font_sans, max_w, 3, int(w * 0.046))
            for line in lines:
                d.text((pad, y), line, font=f, fill=muted)
                y += int(f.size * 1.25)
        if scene.bullets:
            y += int(h * 0.025)
            f = _font(brand.font_sans, int(w * 0.05))
            for b in scene.bullets[:6]:
                d.ellipse((pad, y + f.size * 0.35, pad + f.size * 0.45, y + f.size * 0.8), fill=accent)
                for i, line in enumerate(wrap(d, b, f, max_w - int(f.size * 0.9))):
                    d.text((pad + int(f.size * 0.9), y), line, font=f, fill=ink)
                    y += int(f.size * 1.25)
                y += int(f.size * 0.25)
    img.save(path, "PNG", optimize=True)
    return path


def render_thumbnail(spec: VideoSpec, brand: BrandKit, path: Path, size: Tuple[int, int] = (1280, 720)) -> Path:
    w, h = size
    img = _background(size, brand, brand.accent)
    d = ImageDraw.Draw(img)
    pad = int(w * 0.06)
    mono = _font(brand.font_mono, int(w * 0.024))
    d.text((pad, int(h * 0.1)), brand.wordmark, font=mono, fill=hex_to_rgb(brand.ink))
    title = spec.publish.title or spec.title
    f, lines = fit_font(d, title, brand.font_display, w - 2 * pad, 3, int(w * 0.085), floor=int(w * 0.04))
    y = int(h * 0.3)
    for line in lines:
        d.text((pad, y), line, font=f, fill=hex_to_rgb(brand.ink))
        y += int(f.size * 1.08)
    d.rectangle((pad, y + 18, pad + int(w * 0.12), y + 26), fill=hex_to_rgb(brand.accent))
    foot = _font(brand.font_mono, int(w * 0.022))
    d.text((pad, int(h * 0.86)), brand.url, font=foot, fill=hex_to_rgb(brand.muted))
    img.save(path, "PNG", optimize=True)
    return path


def render_image_scene(media: Path, output: Output, path: Path) -> Path:
    """Fit a user image onto a brand-neutral black canvas of the output size."""
    w, h = output.width, output.height
    src = Image.open(media).convert("RGB")
    scale = min(w / src.width, h / src.height)
    src = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))))
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    canvas.paste(src, ((w - src.width) // 2, (h - src.height) // 2))
    canvas.save(path, "PNG")
    return path
