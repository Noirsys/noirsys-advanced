"""Radar tests with fake sources — no network, no keys."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from noirstudio import radar
from noirstudio.radar import Snapshot, apply_deltas, brief, collect, hook_pattern, parse_iso8601_duration

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeYT:
    """Two channels; channel A has one breakout video; a keyword search returns one extra."""

    def __init__(self):
        self.units = 0
        self.catalog = {
            "a1": dict(id="a1", title="I Let an AI Run My Life for a Week", channel_id="UCA", channel_title="Chan A",
                       published_at=_iso(10), views=50_000, likes=900, comments=120, duration_s=600),
            "a2": dict(id="a2", title="Weekly update", channel_id="UCA", channel_title="Chan A",
                       published_at=_iso(100), views=4_000, likes=50, comments=5, duration_s=700),
            "a3": dict(id="a3", title="Another update", channel_id="UCA", channel_title="Chan A",
                       published_at=_iso(200), views=5_000, likes=60, comments=6, duration_s=650),
            "b1": dict(id="b1", title="How to build agents", channel_id="UCB", channel_title="Chan B",
                       published_at=_iso(30), views=9_000, likes=100, comments=10, duration_s=900),
            "k1": dict(id="k1", title="Why AI agents keep failing", channel_id="UCK", channel_title="Keyword Chan",
                       published_at=_iso(5), views=20_000, likes=300, comments=40, duration_s=120),
            "tiny": dict(id="tiny", title="noise", channel_id="UCK", channel_title="Keyword Chan",
                         published_at=_iso(5), views=10, likes=0, comments=0, duration_s=30),
        }

    def resolve_channel(self, ref):
        self.units += 1
        if ref == "UCA":
            return {"id": "UCA", "title": "Chan A", "subscribers": 12_000, "uploads": "UUA"}
        if ref == "UCB":
            return {"id": "UCB", "title": "Chan B", "subscribers": 300_000, "uploads": "UUB"}
        raise radar.RadarError(f"channel not found: {ref}")

    def channel_upload_ids(self, uploads, n=15):
        self.units += 1
        return {"UUA": ["a1", "a2", "a3"], "UUB": ["b1"]}[uploads]

    def search_ids(self, query, published_after, n=25, order="viewCount"):
        self.units += 100
        return ["k1", "a1", "tiny"]  # overlap with channel video a1 on purpose

    def videos(self, ids):
        self.units += 1
        return [dict(self.catalog[i]) for i in ids if i in self.catalog]


class FakeHN:
    def stories(self, query, days=3, n=30):
        return [
            {"id": "1", "title": f"Show HN: {query} thing", "url": "https://x.test", "points": 120, "comments": 40,
             "created_at": _iso(4)},
            {"id": "2", "title": "old story", "url": "https://y.test", "points": 10, "comments": 1, "created_at": _iso(60)},
        ]


CFG = {
    "settings": {"days": 7, "uploads_per_channel": 15, "results_per_keyword": 25, "hn_days": 3, "min_views": 500},
    "channels": [{"ref": "UCA", "label": "A"}, {"ref": "UCB", "label": "B"}, {"ref": "UCMISSING", "label": "Missing"}],
    "keywords": ["ai agents"],
    "hn_queries": ["mcp"],
}


def test_collect_computes_vph_breakout_and_dedup():
    yt, hn = FakeYT(), FakeHN()
    snap = collect(CFG, yt, hn, now=NOW)
    by_id = {v.id: v for v in snap.videos}
    assert "tiny" not in by_id  # below min_views
    assert by_id["a1"].source == "channel:A"  # channel attribution wins over keyword
    assert by_id["k1"].source == "keyword:ai agents"
    assert by_id["a1"].vph == 5000.0  # 50k views / 10h
    assert by_id["a1"].breakout == 11.11  # 50k / median(4k, 5k)=4.5k
    assert by_id["b1"].breakout == 1.0  # single upload: itself
    assert snap.channels["UCA"]["subscribers"] == 12_000
    assert by_id["a1"].subscribers == 12_000
    assert any("Missing" in e for e in snap.errors)
    assert snap.quota_units == yt.units and snap.quota_units >= 100
    assert snap.stories[0].pph == 30.0  # 120 pts / 4h


def test_apply_deltas_scales_to_24h():
    yt, hn = FakeYT(), FakeHN()
    snap = collect(CFG, yt, hn, now=NOW)
    prev = Snapshot.from_dict(json.loads(json.dumps(snap.to_dict())))
    prev.generated_at = (NOW - timedelta(hours=12)).isoformat(timespec="seconds")
    for v in prev.videos:
        v.views -= 6_000
    apply_deltas(snap, prev)
    assert {v.id: v.views_24h for v in snap.videos}["a1"] == 12_000  # +6k over 12h -> 12k/24h


def test_brief_sections_and_round_trip(tmp_path):
    snap = collect(CFG, FakeYT(), FakeHN(), now=NOW)
    text = brief(snap)
    for heading in ("Fastest right now", "Breakouts", "Keywords", "Hacker News", "Hook patterns", "Make today"):
        assert heading in text
    assert "I Let an AI Run My Life" in text and "Show HN: mcp thing" in text
    again = Snapshot.from_dict(json.loads(json.dumps(snap.to_dict())))
    assert [v.id for v in again.videos] == [v.id for v in snap.videos]


def test_run_writes_snapshot_and_brief(tmp_path, monkeypatch):
    cfg = tmp_path / "radar.yaml"
    cfg.write_text(yaml.safe_dump(CFG), encoding="utf-8")
    monkeypatch.setattr(radar, "_now", lambda: NOW)
    path = radar.run(cfg, tmp_path / "out", yt=FakeYT(), hn=FakeHN())
    assert path.name == "2026-09-28.md" and path.exists()
    snaps = list((tmp_path / "out" / "snapshots").glob("*.json"))
    assert len(snaps) == 1
    # HN-only run (no key) still produces a brief
    path2 = radar.run(cfg, tmp_path / "out2", use_youtube=False, hn=FakeHN())
    assert "Hacker News" in path2.read_text(encoding="utf-8")


def test_default_config_parses_and_helpers():
    cfg = yaml.safe_load(radar.DEFAULT_CONFIG)
    assert len(cfg["channels"]) == 10 and len(cfg["keywords"]) == 16
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("PT45S") == 45 and parse_iso8601_duration("") == 0
    assert hook_pattern("I Built an AI Clerk") == "first-person outcome"
    assert hook_pattern("How to Build AI Agents") == "how-to"
    assert hook_pattern("Stop Using ChatGPT") == "warning/contrarian"
    assert hook_pattern("5 AI Agents That Work") == "listicle"
    assert hook_pattern("Claude vs GPT") == "versus"
