from PIL import Image

from noirstudio.brandkit import BRANDS, get_brand
from noirstudio.spec import Output, Scene, spec_from_dict
from noirstudio.visuals import render_card, render_thumbnail, wrap


def _bright_pixels(path):
    im = Image.open(path).convert("L")
    return sum(im.histogram()[128:])


def test_cards_render_for_every_style_and_brand(tmp_path):
    out = Output(width=540, height=960)
    scenes = [
        Scene(text="t", style="title", title="A headline that is long enough to wrap onto lines", subtitle="sub"),
        Scene(text="t", style="stat", stat="20–30", title="finished Shorts"),
        Scene(text="t", style="quote", title="Evidence before claims."),
        Scene(text="t", style="list", title="Three things", bullets=["one", "two", "three"]),
        Scene(text="plain narration only", style="plain"),
    ]
    for brand_name in BRANDS:
        brand = get_brand(brand_name)
        for scene in scenes:
            path = tmp_path / f"{brand_name}-{scene.style}.png"
            render_card(scene, brand, out, path, badge="PREVIEW")
            im = Image.open(path)
            assert im.size == (540, 960)
            assert _bright_pixels(path) > 2000  # text actually drawn


def test_thumbnail_size(tmp_path):
    spec = spec_from_dict({"id": "x", "title": "Why Your AI Agents Keep Failing", "scenes": ["a"]})
    path = render_thumbnail(spec, get_brand("noirsys"), tmp_path / "t.png")
    assert Image.open(path).size == (1280, 720)
    assert _bright_pixels(path) > 2000


def test_wrap_respects_width():
    from PIL import ImageDraw, ImageFont

    brand = get_brand("noirsys")
    font = ImageFont.truetype(str(brand.font_sans), 40)
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines = wrap(draw, "the quick brown fox jumps over the lazy dog again and again", font, 300)
    assert len(lines) > 1
    for line in lines:
        assert draw.textbbox((0, 0), line, font=font)[2] <= 300 + 40  # single long words may exceed
