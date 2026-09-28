"""Brand kits derived from the live sites' design tokens.

Colours were read from the shipped CSS of noirsys.com / noirsys.xyz (Tailwind
build: #050505 background, lime #a3e635 + teal #2dd4bf accents, Space Grotesk)
and noirpost.live (CSS variables: --black #07070B, --magenta #FF3EA5,
--cyan #3EE6FF, --violet #8B7CFF, --lime #C6FF4D, --ink #ECE9F3; Big Shoulders
Display + Archivo + JetBrains Mono).

Fonts are bundled as static TTFs in assets/fonts (SIL Open Font License; see
assets/fonts/LICENSES.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"


@dataclass(frozen=True)
class BrandKit:
    name: str
    wordmark: str
    tagline: str
    url: str
    bg: str
    surface: str
    ink: str
    muted: str
    line: str
    accent: str
    accent2: str
    accent3: str
    font_display: Path
    font_sans: Path
    font_mono: Path
    caption_font: Path

    @property
    def caption_font_family(self) -> str:
        return font_family_name(self.caption_font)


BRANDS: Dict[str, BrandKit] = {
    "noirsys": BrandKit(
        name="noirsys",
        wordmark="NOIRSYS",
        tagline="Systems that finish the job.",
        url="noirsys.com",
        bg="#050505",
        surface="#09090d",
        ink="#F4F4F5",
        muted="#8A8F98",
        line="#1C1F24",
        accent="#A3E635",
        accent2="#2DD4BF",
        accent3="#FBBF24",
        font_display=FONTS_DIR / "SpaceGrotesk-Bold.ttf",
        font_sans=FONTS_DIR / "Archivo-Bold.ttf",
        font_mono=FONTS_DIR / "JetBrainsMono-Bold.ttf",
        caption_font=FONTS_DIR / "Archivo-ExtraBold.ttf",
    ),
    "noirpost": BrandKit(
        name="noirpost",
        wordmark="Noirpost",
        tagline="Your long stream has more than one shape.",
        url="noirpost.live",
        bg="#07070B",
        surface="#0F0F17",
        ink="#ECE9F3",
        muted="#9C99B0",
        line="#26263A",
        accent="#FF3EA5",
        accent2="#3EE6FF",
        accent3="#C6FF4D",
        font_display=FONTS_DIR / "BigShouldersDisplay-ExtraBold.ttf",
        font_sans=FONTS_DIR / "Archivo-Bold.ttf",
        font_mono=FONTS_DIR / "JetBrainsMono-Bold.ttf",
        caption_font=FONTS_DIR / "Archivo-ExtraBold.ttf",
    ),
}


def get_brand(name: str) -> BrandKit:
    try:
        return BRANDS[name]
    except KeyError:
        raise KeyError(f"unknown brand `{name}`; known: {sorted(BRANDS)}") from None


def hex_to_rgb(value: str) -> Tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def hex_to_ass(value: str, alpha: int = 0) -> str:
    """#RRGGBB -> ASS &HAABBGGRR (alpha 0 = opaque, 255 = transparent)."""
    r, g, b = hex_to_rgb(value)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


@lru_cache(maxsize=None)
def font_family_name(path: Path) -> str:
    """Family name as libass will see it, read from the TTF's name table."""
    from PIL import ImageFont

    family, _style = ImageFont.truetype(str(path), 24).getname()
    return family
