"""End-to-end offline render on a tiny spec (no network, no keys)."""

import json

from noirstudio.pipeline import render
from noirstudio.publish import AI_DISCLOSURE, build_metadata
from noirstudio.brandkit import get_brand
from noirstudio.spec import spec_from_dict

TINY = {
    "id": "tiny",
    "title": "Tiny render",
    "brand": "noirpost",
    "output": {"width": 540, "height": 960, "fps": 24},
    "voice": {"words_per_minute": 220},
    "scenes": [
        {"kind": "card", "style": "title", "title": "Hello", "text": "Hello there, this is a test."},
        {"kind": "avatar", "text": "No avatar image, so this falls back."},
        {"kind": "broll", "prompt": "dark studio", "text": "Offline b-roll falls back too."},
        {"kind": "card", "style": "plain", "text": "", "duration": 1.0},
    ],
    "publish": {"tags": ["test"], "cta": "Follow."},
}


def test_offline_render_produces_all_outputs(tmp_path):
    spec = spec_from_dict(TINY)
    result = render(spec, tmp_path / "out", live=False, log=lambda _m: None)

    assert result.video.exists() and result.video.stat().st_size > 10_000
    assert result.thumbnail.exists()
    assert result.captions_srt.read_text().count("-->") >= 3
    assert "Dialogue:" in result.captions_ass.read_text()
    assert result.live is False
    assert 5.0 < result.duration < 20.0

    report = json.loads(result.report.read_text())
    assert report["voice_engine"] == "offline" and report["video_engine"] == "offline"
    by_id = {s["id"]: s for s in report["scenes"]}
    assert by_id["s02"]["fallback"] == "no avatar_image in spec"
    assert by_id["s03"]["fallback"] == "video engine offline"
    assert by_id["s04"]["voice_source"] == "silence" and by_id["s04"]["duration"] == 1.0

    meta = json.loads(result.metadata_json.read_text())
    assert meta["is_short"] is True
    assert AI_DISCLOSURE in meta["description"]
    assert "Follow." in meta["description"]
    assert "noirpost" in meta["tags"] and "shorts" in meta["tags"]


def test_metadata_chapters_only_for_long_videos():
    spec = spec_from_dict({"id": "m", "title": "T", "scenes": ["a", "b"], "publish": {"chapters": True}})
    brand = get_brand("noirsys")
    short = build_metadata(spec, brand, 45.0, [("a", 0.0), ("b", 20.0)])
    assert "Chapters:" not in short["description"]
    long = build_metadata(spec, brand, 90.0, [("a", 0.0), ("b", 61.0)])
    assert "Chapters:" in long["description"] and "1:01 b" in long["description"]
    assert long["is_short"] is True  # 90s vertical is still a Short (≤ 3 min)
    assert "https://noirsys.com" in long["description"]  # default link
    too_long = build_metadata(spec, brand, 200.0, [("a", 0.0)])
    assert too_long["is_short"] is False and "shorts" not in too_long["tags"]
    spec.output.width, spec.output.height = 1920, 1080
    assert build_metadata(spec, brand, 45.0, [("a", 0.0)])["is_short"] is False  # landscape
