"""Upload metadata: title, description (with chapters, links, disclosure), tags.

Nothing here uploads anything. The output is a JSON + Markdown pair a person
reviews before posting, or that a later uploader step can consume.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Sequence, Tuple

from .brandkit import BrandKit
from .spec import VideoSpec

AI_DISCLOSURE = (
    "Disclosure: narration uses an AI voice clone of the creator's own voice; "
    "some visuals are AI-generated. Scripts are written and reviewed by a person."
)


def _chapter_stamp(t: float) -> str:
    t = int(t)
    return f"{t // 60:d}:{t % 60:02d}" if t < 3600 else f"{t // 3600}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def build_metadata(spec: VideoSpec, brand: BrandKit, duration: float,
                   scene_starts: Sequence[Tuple[str, float]]) -> dict:
    pub = spec.publish
    title = pub.title or spec.title
    lines: List[str] = []
    if pub.description.strip():
        lines.append(pub.description.strip())
    else:
        first = spec.scenes[0].text.strip() if spec.scenes else ""
        if first:
            lines.append(first)
    if pub.chapters and len(scene_starts) > 1 and duration >= 60:
        lines.append("")
        lines.append("Chapters:")
        for label, start in scene_starts:
            lines.append(f"{_chapter_stamp(start)} {label}")
    if pub.cta:
        lines.append("")
        lines.append(pub.cta)
    links = list(pub.links) or [f"https://{brand.url}"]
    lines.append("")
    lines.extend(links)
    if pub.ai_disclosure:
        lines.append("")
        lines.append(AI_DISCLOSURE)
    if pub.hashtags:
        lines.append("")
        lines.append(" ".join(h if h.startswith("#") else f"#{h}" for h in pub.hashtags))
    tags = list(dict.fromkeys([*pub.tags, brand.name, *(["shorts"] if duration <= 180 else [])]))
    return {
        "title": title[:100],
        "description": "\n".join(lines)[:5000],
        "tags": tags[:30],
        "duration_seconds": round(duration, 2),
        "is_short": duration <= 180 and spec.output.height > spec.output.width,
        "brand": brand.name,
        "niche": spec.niche,
        "ai_disclosure": pub.ai_disclosure,
        "spec_id": spec.id,
        "spec_digest": spec.digest(),
    }


def write_metadata(meta: dict, path_json: Path, path_md: Path) -> None:
    path_json.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    md = [
        f"# {meta['title']}",
        "",
        f"*{'Short' if meta['is_short'] else 'Long-form'} · {meta['duration_seconds']}s · brand: {meta['brand']}*",
        "",
        "## Description",
        "",
        meta["description"],
        "",
        "## Tags",
        "",
        ", ".join(meta["tags"]),
        "",
    ]
    path_md.write_text("\n".join(md), encoding="utf-8")
