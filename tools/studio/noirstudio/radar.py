"""radar — a daily bird's-eye view of what is working, built on free APIs.

Sources
  * YouTube Data API v3 (needs YOUTUBE_API_KEY; 10,000 units/day free):
      - watched channels: latest uploads + stats -> views/hour and a breakout
        ratio (views vs. the channel's own median), the same idea as vidIQ's
        outlier score, computed here for free.
      - keywords: videos published in the last N days, sorted by views.
  * Hacker News (Algolia, no key): stories per query with points/hour.

Every run stores a snapshot in `radar/snapshots/<date>.json`. When yesterday's
snapshot exists, the brief also reports true 24h view deltas per video, which
is a cleaner velocity signal than views/age for anything older than a day.

Quota: search.list costs 100 units, everything else ~1. The default config
(16 keywords, 10 channels) spends ~1,700 units per run.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import yaml

ENV_YT_KEY = "YOUTUBE_API_KEY"
YT_BASE = "https://www.googleapis.com/youtube/v3"
HN_BASE = "https://hn.algolia.com/api/v1"
USER_AGENT = "noirstudio-radar/0.1 (+https://noirsys.com)"


class RadarError(RuntimeError):
    pass


# --- models -----------------------------------------------------------------


@dataclass
class Video:
    id: str
    title: str
    channel_id: str
    channel_title: str
    published_at: str  # ISO 8601
    views: int
    likes: int
    comments: int
    duration_s: int
    source: str  # "channel:<label>" or "keyword:<kw>"
    subscribers: Optional[int] = None
    vph: float = 0.0
    breakout: Optional[float] = None
    views_24h: Optional[int] = None

    @property
    def url(self) -> str:
        return f"https://youtu.be/{self.id}"

    @property
    def is_short(self) -> bool:
        return 0 < self.duration_s <= 180


@dataclass
class Story:
    id: str
    title: str
    url: str
    points: int
    comments: int
    created_at: str
    query: str
    pph: float = 0.0  # points per hour

    @property
    def hn_url(self) -> str:
        return f"https://news.ycombinator.com/item?id={self.id}"


@dataclass
class Snapshot:
    date: str
    generated_at: str
    videos: List[Video] = field(default_factory=list)
    stories: List[Story] = field(default_factory=list)
    channels: Dict[str, dict] = field(default_factory=dict)
    quota_units: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "generated_at": self.generated_at,
            "quota_units": self.quota_units,
            "errors": self.errors,
            "channels": self.channels,
            "videos": [asdict(v) for v in self.videos],
            "stories": [asdict(s) for s in self.stories],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        return cls(
            date=d["date"],
            generated_at=d["generated_at"],
            videos=[Video(**v) for v in d.get("videos", [])],
            stories=[Story(**s) for s in d.get("stories", [])],
            channels=d.get("channels", {}),
            quota_units=d.get("quota_units", 0),
            errors=d.get("errors", []),
        )


# --- helpers ------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def hours_since(iso: str, now: Optional[datetime] = None) -> float:
    delta = (now or _now()) - _parse_iso(iso)
    return max(delta.total_seconds() / 3600.0, 1.0)


def parse_iso8601_duration(s: str) -> int:
    """PT1H2M3S -> seconds (YouTube contentDetails.duration)."""
    if not s or not s.startswith("PT"):
        return 0
    total, num = 0, ""
    for ch in s[2:]:
        if ch.isdigit():
            num += ch
        else:
            n = int(num or 0)
            total += n * {"H": 3600, "M": 60, "S": 1}.get(ch, 0)
            num = ""
    return total


def _get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RadarError(f"HTTP {exc.code} for {url.split('?')[0]}: {detail}") from None


# --- sources ------------------------------------------------------------------


class YouTubeSource:
    """Thin client over the Data API v3 with quota accounting."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get(ENV_YT_KEY)
        if not self.api_key:
            raise RadarError(f"{ENV_YT_KEY} is not set (free key: console.cloud.google.com -> YouTube Data API v3)")
        self.units = 0

    def _call(self, endpoint: str, cost: int, **params) -> dict:
        params["key"] = self.api_key
        self.units += cost
        return _get_json(f"{YT_BASE}/{endpoint}?{urllib.parse.urlencode(params)}")

    def resolve_channel(self, ref: str) -> dict:
        if ref.startswith("UC") and len(ref) == 24:
            data = self._call("channels", 1, part="snippet,statistics,contentDetails", id=ref)
        else:
            data = self._call("channels", 1, part="snippet,statistics,contentDetails", forHandle=ref.lstrip("@"))
        items = data.get("items") or []
        if not items:
            raise RadarError(f"channel not found: {ref}")
        c = items[0]
        return {
            "id": c["id"],
            "title": c["snippet"]["title"],
            "subscribers": int(c["statistics"].get("subscriberCount", 0)),
            "uploads": c["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    def channel_upload_ids(self, uploads_playlist: str, n: int = 15) -> List[str]:
        data = self._call("playlistItems", 1, part="contentDetails", playlistId=uploads_playlist, maxResults=min(n, 50))
        return [i["contentDetails"]["videoId"] for i in data.get("items", [])]

    def search_ids(self, query: str, published_after: datetime, n: int = 25, order: str = "viewCount") -> List[str]:
        data = self._call(
            "search", 100, part="id", q=query, type="video", order=order,
            publishedAfter=published_after.strftime("%Y-%m-%dT%H:%M:%SZ"), maxResults=min(n, 50),
            relevanceLanguage="en",
        )
        return [i["id"]["videoId"] for i in data.get("items", []) if i.get("id", {}).get("videoId")]

    def videos(self, ids: Sequence[str]) -> List[dict]:
        out: List[dict] = []
        ids = list(dict.fromkeys(ids))
        for i in range(0, len(ids), 50):
            chunk = ids[i : i + 50]
            data = self._call("videos", 1, part="snippet,statistics,contentDetails", id=",".join(chunk))
            for v in data.get("items", []):
                st = v.get("statistics", {})
                out.append({
                    "id": v["id"],
                    "title": v["snippet"]["title"],
                    "channel_id": v["snippet"]["channelId"],
                    "channel_title": v["snippet"]["channelTitle"],
                    "published_at": v["snippet"]["publishedAt"],
                    "views": int(st.get("viewCount", 0)),
                    "likes": int(st.get("likeCount", 0)),
                    "comments": int(st.get("commentCount", 0)),
                    "duration_s": parse_iso8601_duration(v.get("contentDetails", {}).get("duration", "")),
                })
        return out


class HNSource:
    def stories(self, query: str, days: int = 3, n: int = 30) -> List[dict]:
        since = int((_now() - timedelta(days=days)).timestamp())
        q = urllib.parse.urlencode({
            "query": query, "tags": "story", "hitsPerPage": min(n, 100), "numericFilters": f"created_at_i>{since}",
        })
        data = _get_json(f"{HN_BASE}/search_by_date?{q}")
        return [
            {
                "id": h["objectID"],
                "title": h.get("title") or "",
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                "points": int(h.get("points") or 0),
                "comments": int(h.get("num_comments") or 0),
                "created_at": h["created_at"],
            }
            for h in data.get("hits", [])
        ]


# --- config -------------------------------------------------------------------

DEFAULT_CONFIG = """# noirstudio radar watchlist. `noirstudio radar run --config radar.yaml`
# YouTube needs YOUTUBE_API_KEY in the environment (free, 10k units/day).
settings:
  days: 7                 # keyword search window
  uploads_per_channel: 15 # for breakout medians
  results_per_keyword: 25
  hn_days: 3
  min_views: 500          # ignore noise below this

channels:                 # channel IDs (UC...) or @handles; label is yours
  - { ref: UCkdgAA0rfK7lG5dv4o__Paw, label: "Alberta Tech" }
  - { ref: UC3yaWWA9FF9OBog5U9ml68A, label: "SavvyNik" }
  - { ref: UCafjal1QYJ3rb0Y9xZk1Ezg, label: "80,000 Hours" }
  - { ref: UCKWaEZ-_VweaEx1j62do_vQ, label: "IBM Technology" }
  - { ref: UC4JX40jDee_tINbkjycV4Sg, label: "Tech With Tim" }
  - { ref: UCY6N8zZhs2V7gNTUxPuKWoQ, label: "Ishan Sharma" }
  - { ref: UCSsmX3rvY0s8uJsvvS5NB8w, label: "Podcast Gold" }
  - { ref: UCakdY-DuPRO9M0VVNmk9qgw, label: "Fru Dev" }
  - { ref: UCWfaTtD5e1LDo4fNdmbj8xw, label: "Jose Zuma" }
  - { ref: UC3cqs-r3789-BrE1-2g5xGw, label: "Learn & Laugh" }

keywords:                 # 100 quota units each
  - ai agents
  - ai agent tutorial
  - autonomous ai agents
  - agentic ai
  - claude code
  - opus 5.5
  - mcp server
  - ai automation
  - vibe coding
  - ai safety
  - ai interpretability
  - ai consciousness
  - is ai alive
  - are ai agents dead
  - local ai agent
  - ai from the ai's perspective

hn_queries:
  - ai agents
  - mcp
  - claude code
  - interpretability
  - llm safety
"""


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg.setdefault("settings", {})
    cfg.setdefault("channels", [])
    cfg.setdefault("keywords", [])
    cfg.setdefault("hn_queries", [])
    return cfg


# --- collection ---------------------------------------------------------------


def collect(cfg: dict, yt: Optional[YouTubeSource], hn: Optional[HNSource], now: Optional[datetime] = None) -> Snapshot:
    now = now or _now()
    s = cfg["settings"]
    snap = Snapshot(date=now.strftime("%Y-%m-%d"), generated_at=now.isoformat(timespec="seconds"))
    seen: Dict[str, Video] = {}

    def add(raw: dict, source: str, subs: Optional[int] = None) -> Video:
        if raw["id"] in seen:
            v = seen[raw["id"]]
            if source.startswith("channel:") and not v.source.startswith("channel:"):
                v.source = source  # prefer the channel attribution
            return v
        v = Video(source=source, subscribers=subs, **raw)
        v.vph = round(v.views / hours_since(v.published_at, now), 2)
        seen[v.id] = v
        return v

    if yt is not None:
        for ch in cfg["channels"]:
            ref, label = ch["ref"], ch.get("label") or ch["ref"]
            try:
                info = yt.resolve_channel(ref)
                ids = yt.channel_upload_ids(info["uploads"], int(s.get("uploads_per_channel", 15)))
                vids = [add(raw, f"channel:{label}", info["subscribers"]) for raw in yt.videos(ids)]
                views = sorted(v.views for v in vids)
                median = statistics.median(views) if views else 0
                for v in vids:
                    others = [x for x in views if x != v.views] or views
                    base = statistics.median(others) if others else median
                    v.breakout = round(v.views / base, 2) if base else None
                snap.channels[info["id"]] = {"label": label, "title": info["title"], "subscribers": info["subscribers"],
                                             "median_views": median, "uploads_checked": len(vids)}
            except RadarError as exc:
                snap.errors.append(f"channel {label}: {exc}")
        after = now - timedelta(days=int(s.get("days", 7)))
        for kw in cfg["keywords"]:
            try:
                ids = yt.search_ids(kw, after, int(s.get("results_per_keyword", 25)))
                for raw in yt.videos(ids):
                    add(raw, f"keyword:{kw}")
            except RadarError as exc:
                snap.errors.append(f"keyword {kw}: {exc}")
        snap.quota_units = yt.units

    if hn is not None:
        for q in cfg["hn_queries"]:
            try:
                for raw in hn.stories(q, int(s.get("hn_days", 3))):
                    st = Story(query=q, **raw)
                    st.pph = round(st.points / hours_since(st.created_at, now), 3)
                    snap.stories.append(st)
            except RadarError as exc:
                snap.errors.append(f"hn {q}: {exc}")

    min_views = int(s.get("min_views", 0))
    snap.videos = [v for v in seen.values() if v.views >= min_views]
    return snap


def apply_deltas(snap: Snapshot, previous: Optional[Snapshot]) -> None:
    if not previous:
        return
    prev = {v.id: v.views for v in previous.videos}
    hours = max(hours_since(previous.generated_at, _parse_iso(snap.generated_at)), 1.0)
    for v in snap.videos:
        if v.id in prev:
            v.views_24h = int(round((v.views - prev[v.id]) * (24.0 / hours)))


# --- brief --------------------------------------------------------------------

_HOOK_PATTERNS = [
    ("listicle", re.compile(r"^\s*\d+\s")),
    ("how-to", re.compile(r"\bhow\b")),
    ("why/what", re.compile(r"\b(why|what)\b")),
    ("warning/contrarian", re.compile(r"\b(stop|don'?t|never|wrong|dead|worse|scary|lie[sd]?|lying)\b")),
    ("versus", re.compile(r"\bvs\.?\b|\bversus\b")),
    ("first-person outcome", re.compile(r"\b(i|i'm|i've|i'll|my|me)\b")),
    ("question", re.compile(r"\?")),
]


def hook_pattern(title: str) -> str:
    """Coarse title archetype, used to summarise what the winners have in common."""
    t = title.lower()
    for name, rx in _HOOK_PATTERNS:
        if rx.search(t):
            return name
    return "other"


def _fmt(n: Optional[float]) -> str:
    if n is None:
        return "—"
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return f"{n:.0f}"


def brief(snap: Snapshot, top: int = 10) -> str:
    vids = snap.videos
    lines: List[str] = [f"# Radar brief — {snap.date}", "",
                        f"*{len(vids)} videos · {len(snap.stories)} HN stories · {snap.quota_units} YouTube quota units · generated {snap.generated_at}*", ""]
    if snap.errors:
        lines += ["> Errors: " + "; ".join(snap.errors), ""]

    def table(rows: Iterable[Video], metric: str, key) -> List[str]:
        out = [f"| {metric} | views | age | channel (subs) | title |", "|---:|---:|---:|---|---|"]
        for v in rows:
            age_h = hours_since(v.published_at, _parse_iso(snap.generated_at))
            age = f"{age_h:.0f}h" if age_h < 48 else f"{age_h / 24:.0f}d"
            out.append(f"| {key(v)} | {_fmt(v.views)} | {age} | {v.channel_title} ({_fmt(v.subscribers)}) | [{v.title}]({v.url}) |")
        return out

    fastest = sorted(vids, key=lambda v: v.vph, reverse=True)[:top]
    lines += ["## Fastest right now (views/hour)", ""] + table(fastest, "vph", lambda v: _fmt(v.vph)) + [""]

    movers = [v for v in vids if v.views_24h is not None]
    if movers:
        movers = sorted(movers, key=lambda v: v.views_24h or 0, reverse=True)[:top]
        lines += ["## 24h movers (measured, not estimated)", ""] + table(movers, "+24h", lambda v: _fmt(v.views_24h)) + [""]

    breakouts = sorted([v for v in vids if v.breakout and v.breakout >= 2], key=lambda v: v.breakout or 0, reverse=True)[:top]
    if breakouts:
        lines += ["## Breakouts (× the channel's own median)", ""] + table(breakouts, "×", lambda v: f"{v.breakout:.1f}") + [""]

    small = sorted([v for v in vids if (v.subscribers or 10**9) < 25_000 or v.source.startswith("keyword:")],
                   key=lambda v: v.vph, reverse=True)
    small = [v for v in small if v.views >= 5_000][:top]
    if small:
        lines += ["## Working for small channels / from keyword search", ""] + table(small, "vph", lambda v: _fmt(v.vph)) + [""]

    kws: Dict[str, List[Video]] = {}
    for v in vids:
        if v.source.startswith("keyword:"):
            kws.setdefault(v.source.split(":", 1)[1], []).append(v)
    if kws:
        lines += ["## Keywords (last window)", "", "| keyword | videos | median vph | best |", "|---|---:|---:|---|"]
        for kw, group in sorted(kws.items(), key=lambda kv: -statistics.median([g.vph for g in kv[1]])):
            best = max(group, key=lambda v: v.views)
            lines.append(f"| {kw} | {len(group)} | {_fmt(statistics.median([g.vph for g in group]))} | [{best.title}]({best.url}) ({_fmt(best.views)}) |")
        lines.append("")

    if snap.stories:
        hot = sorted(snap.stories, key=lambda s: s.pph, reverse=True)[:top]
        lines += ["## Hacker News (points/hour)", "", "| pts/h | pts | cmts | title |", "|---:|---:|---:|---|"]
        for s in hot:
            lines.append(f"| {s.pph:.2f} | {s.points} | {s.comments} | [{s.title}]({s.url}) · [HN]({s.hn_url}) |")
        lines.append("")

    counts: Dict[str, int] = {}
    for v in fastest + breakouts:
        counts[hook_pattern(v.title)] = counts.get(hook_pattern(v.title), 0) + 1
    if counts:
        lines += ["## Hook patterns among the winners", ""]
        lines += [f"- **{k}**: {n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])] + [""]

    lines += ["## Make today", ""]
    picks = sorted(vids, key=lambda v: (v.breakout or 1) * v.vph, reverse=True)[:5]
    for v in picks:
        lines.append(f"- *{hook_pattern(v.title)}* angle on **{v.channel_title}**'s [{v.title}]({v.url}) — {_fmt(v.vph)} vph, ×{v.breakout or 1:.1f}")
    lines.append("")
    return "\n".join(lines)


# --- run ----------------------------------------------------------------------


def run(config_path: Path, out_dir: Path, *, use_youtube: bool = True, use_hn: bool = True,
        yt: Optional[YouTubeSource] = None, hn: Optional[HNSource] = None) -> Path:
    cfg = load_config(config_path)
    snaps = out_dir / "snapshots"
    briefs = out_dir / "briefs"
    snaps.mkdir(parents=True, exist_ok=True)
    briefs.mkdir(parents=True, exist_ok=True)

    if use_youtube and yt is None:
        yt = YouTubeSource()
    if use_hn and hn is None:
        hn = HNSource()
    snap = collect(cfg, yt if use_youtube else None, hn if use_hn else None)

    previous = None
    older = sorted(p for p in snaps.glob("*.json") if p.stem < snap.date)
    if older:
        previous = Snapshot.from_dict(json.loads(older[-1].read_text(encoding="utf-8")))
    apply_deltas(snap, previous)

    (snaps / f"{snap.date}.json").write_text(json.dumps(snap.to_dict(), indent=1), encoding="utf-8")
    path = briefs / f"{snap.date}.md"
    path.write_text(brief(snap), encoding="utf-8")
    return path
