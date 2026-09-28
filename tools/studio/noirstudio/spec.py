"""The video spec: a reviewable YAML file that fully describes one video.

Content-as-code. A person edits and approves the spec; the pipeline renders
exactly what it says. Every field has a safe default so a spec can be tiny:

    id: hello
    title: Hello World
    scenes:
      - text: "This is the first thing the viewer hears."
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import yaml

SCENE_KINDS = ("card", "avatar", "broll", "image", "video")
CARD_STYLES = ("title", "stat", "quote", "list", "plain")
CAPTION_MODES = ("word", "line", "none")


@dataclass
class Scene:
    text: str
    id: str = ""
    kind: str = "card"
    style: str = "title"
    title: Optional[str] = None
    subtitle: Optional[str] = None
    stat: Optional[str] = None
    bullets: List[str] = field(default_factory=list)
    prompt: Optional[str] = None
    media: Optional[str] = None
    duration: Optional[float] = None
    motion: bool = True


@dataclass
class Voice:
    provider: str = "elevenlabs"
    voice_id: Optional[str] = None
    model_id: str = "eleven_multilingual_v2"
    stability: float = 0.5
    similarity_boost: float = 0.8
    style: float = 0.15
    speed: float = 1.0
    words_per_minute: float = 155.0


@dataclass
class Captions:
    enabled: bool = True
    mode: str = "word"
    words_per_line: int = 3
    uppercase: bool = True
    font_size: int = 84
    margin_v: int = 520
    highlight: bool = True


@dataclass
class Output:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    filename: Optional[str] = None


@dataclass
class Publish:
    title: Optional[str] = None
    description: str = ""
    tags: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    cta: Optional[str] = None
    chapters: bool = True
    ai_disclosure: bool = True


@dataclass
class VideoSpec:
    id: str
    title: str
    scenes: List[Scene]
    brand: str = "noirsys"
    niche: Optional[str] = None
    avatar_image: Optional[str] = None
    music: Optional[str] = None
    music_gain_db: float = -18.0
    voice: Voice = field(default_factory=Voice)
    captions: Captions = field(default_factory=Captions)
    output: Output = field(default_factory=Output)
    publish: Publish = field(default_factory=Publish)
    source_path: Optional[str] = None

    @property
    def narration(self) -> str:
        return " ".join(s.text.strip() for s in self.scenes if s.text.strip())

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("source_path", None)
        return d

    def digest(self) -> str:
        raw = yaml.safe_dump(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()[:16]


class SpecError(ValueError):
    pass


def _build(cls, data: Any, name: str):
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise SpecError(f"`{name}` must be a mapping")
    allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
    unknown = set(data) - allowed
    if unknown:
        raise SpecError(f"`{name}` has unknown keys: {sorted(unknown)}")
    return cls(**data)


def spec_from_dict(data: dict, source_path: Optional[str] = None) -> VideoSpec:
    if not isinstance(data, dict):
        raise SpecError("spec root must be a mapping")
    for key in ("id", "title"):
        if not data.get(key):
            raise SpecError(f"spec is missing required `{key}`")
    raw_scenes = data.get("scenes")
    if not raw_scenes or not isinstance(raw_scenes, list):
        raise SpecError("spec needs a non-empty `scenes` list")

    scenes: List[Scene] = []
    for i, raw in enumerate(raw_scenes):
        if isinstance(raw, str):
            raw = {"text": raw}
        scene = _build(Scene, raw, f"scenes[{i}]")
        if not scene.id:
            scene.id = f"s{i + 1:02d}"
        scenes.append(scene)

    spec = VideoSpec(
        id=str(data["id"]),
        title=str(data["title"]),
        scenes=scenes,
        brand=data.get("brand", "noirsys"),
        niche=data.get("niche"),
        avatar_image=data.get("avatar_image"),
        music=data.get("music"),
        music_gain_db=float(data.get("music_gain_db", -18.0)),
        voice=_build(Voice, data.get("voice"), "voice"),
        captions=_build(Captions, data.get("captions"), "captions"),
        output=_build(Output, data.get("output"), "output"),
        publish=_build(Publish, data.get("publish"), "publish"),
        source_path=source_path,
    )
    problems = validate(spec)
    if problems:
        raise SpecError("invalid spec:\n  - " + "\n  - ".join(problems))
    return spec


def load_spec(path: Path | str) -> VideoSpec:
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return spec_from_dict(data, source_path=str(p.resolve()))


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def validate(spec: VideoSpec) -> List[str]:
    """Return a list of human-readable problems (empty when the spec is fine)."""
    problems: List[str] = []
    if not _ID_RE.match(spec.id):
        problems.append("`id` must be lowercase letters, digits, '.', '_' or '-' (max 64)")
    if spec.captions.mode not in CAPTION_MODES:
        problems.append(f"captions.mode must be one of {CAPTION_MODES}")
    if spec.captions.words_per_line < 1 or spec.captions.words_per_line > 8:
        problems.append("captions.words_per_line must be 1..8")
    if spec.output.width % 2 or spec.output.height % 2:
        problems.append("output.width and output.height must be even")
    if not 1 <= spec.output.fps <= 60:
        problems.append("output.fps must be 1..60")
    if spec.voice.words_per_minute <= 0:
        problems.append("voice.words_per_minute must be positive")
    base = Path(spec.source_path).parent if spec.source_path else Path.cwd()
    for rel in (spec.music, spec.avatar_image):
        if rel and not (base / rel).exists() and not Path(rel).exists():
            problems.append(f"file not found: {rel}")
    seen = set()
    for s in spec.scenes:
        if s.id in seen:
            problems.append(f"duplicate scene id `{s.id}`")
        seen.add(s.id)
        if s.kind not in SCENE_KINDS:
            problems.append(f"scene `{s.id}`: kind must be one of {SCENE_KINDS}")
        if s.kind == "card" and s.style not in CARD_STYLES:
            problems.append(f"scene `{s.id}`: style must be one of {CARD_STYLES}")
        if not s.text.strip() and s.duration is None:
            problems.append(f"scene `{s.id}`: needs `text` or an explicit `duration`")
        if s.kind in ("image", "video"):
            if not s.media:
                problems.append(f"scene `{s.id}`: kind `{s.kind}` needs `media`")
            elif not (base / s.media).exists() and not Path(s.media).exists():
                problems.append(f"scene `{s.id}`: media not found: {s.media}")
        if s.kind == "broll" and not s.prompt:
            problems.append(f"scene `{s.id}`: kind `broll` needs a `prompt`")
        if s.duration is not None and s.duration <= 0:
            problems.append(f"scene `{s.id}`: duration must be positive")
    return problems


def resolve_asset(spec: VideoSpec, rel: str) -> Path:
    """Resolve a spec-relative asset path (relative to the spec file, then cwd)."""
    p = Path(rel)
    if p.is_absolute() and p.exists():
        return p
    if spec.source_path:
        cand = Path(spec.source_path).parent / rel
        if cand.exists():
            return cand
    return p.resolve()


def starter_spec(video_id: str, brand: str = "noirsys") -> str:
    """A commented starter YAML for `noirstudio new`."""
    return f"""# noirstudio video spec — edit, review, then `noirstudio render {video_id}.yaml`
id: {video_id}
title: "Working title"
brand: {brand}            # noirsys | noirpost
niche: ai-agents

voice:
  # voice_id: YOUR_ELEVENLABS_VOICE_ID   # your cloned voice (live mode)
  model_id: eleven_multilingual_v2
  words_per_minute: 155                  # offline timing estimate

captions:
  mode: word            # word | line | none
  words_per_line: 3
  uppercase: true

# Scenes are spoken in order. `text` is the narration. Card fields are on-screen.
scenes:
  - kind: card
    style: title
    title: "The hook goes here"
    subtitle: "One line that earns the next 3 seconds"
    text: "Open with the single most surprising true sentence you have."
  - kind: card
    style: stat
    stat: "20–30"
    title: "finished Shorts per stream"
    text: "Back the hook with one number the viewer can verify."
  - kind: card
    style: list
    title: "What actually happened"
    bullets: ["Step one", "Step two", "Step three"]
    text: "Then show the mechanism in three beats, not ten."
  # - kind: avatar               # live mode: lip-synced talking head of your avatar image
  #   text: "Say the part that needs a human face."
  # - kind: broll                # live mode: generated 9:16 b-roll
  #   prompt: "slow dolly across a dark server room, cyan and magenta accents"
  #   text: "Narration over the b-roll."

publish:
  tags: [ai agents, noirsys]
  hashtags: ["#ai", "#agents"]
  links: ["https://noirsys.com"]
  cta: "Follow for the next build."
  ai_disclosure: true
"""
