"""LLM drafting with mechanical enforcement of the rules.

`draft_agent_log` writes the next Agent Log entry from the persona bible, the
day's activity JSON and radar brief. The model proposes; the code checks:
schema validity, word limit, scene count, the fixed sign-off, caption case,
disclosure, and — the important one — that every number spoken exists in the
evidence. Failures are fed back once; a second failure raises with the draft
saved for a human.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import yaml

from .llm import LLMClient, LLMError, extract_json
from .spec import SpecError, VideoSpec, spec_from_dict

PERSONA_PATH = Path(__file__).resolve().parents[1] / "persona" / "agent-log.md"
SIGN_OFF_RE = re.compile(r"Entry\s+(\d{3})\.\s+Tomorrow I'll tell you what I did\.\s+He'll tell you whether it mattered\.")
MAX_WORDS = 140
MIN_SCENES, MAX_SCENES = 6, 8
# her identity comes from the persona bible, never from the model
VOICE = {"voice_id": "ZSNL4hPqCnqoMPaI4jGX", "model_id": "eleven_v4", "stability": 0.62, "words_per_minute": 158}
WORDMARK = "HARRIET · AGENT LOG · {entry}"


class DraftError(RuntimeError):
    def __init__(self, message: str, draft: Optional[dict] = None):
        super().__init__(message)
        self.draft = draft


SPEC_SHAPE = """Return ONE JSON object with exactly these keys:
{
  "id": "agent-log-NNN",
  "title": "<internal title, <= 70 chars>",
  "brand": "noirsys",
  "brand_overrides": {"wordmark": "HARRIET · AGENT LOG · NNN", "url": "noirsys.com", "accent": "#8B7CFF", "accent2": "#3EE6FF", "accent3": "#FF3EA5"},
  "niche": "ai-agents",
  "voice": {"model_id": "eleven_v4", "stability": 0.62, "words_per_minute": 158},
  "captions": {"mode": "word", "words_per_line": 3, "uppercase": false},
  "scenes": [
    {"kind": "card", "style": "title|stat|list|quote|plain", "title": "...", "subtitle": "...", "stat": "...", "bullets": ["..."], "text": "<what she says in this scene>"}
  ],
  "publish": {"title": "<YouTube title <= 70 chars>", "tags": ["..."], "hashtags": ["#aiagents"], "links": ["https://noirsys.com"], "cta": "Entry NNN. Follow for tomorrow's log.", "ai_disclosure": true}
}
Only include the card fields a style uses (stat -> stat+title; list -> title+bullets; quote/title/plain -> title(+subtitle)). No other keys. No markdown outside the JSON."""


# --- checks -------------------------------------------------------------------------

_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")


def _numbers_in(text: str) -> List[str]:
    return [n.replace(",", "").rstrip(".") for n in _NUM_RE.findall(text)]


def numbers_not_in_evidence(spec: VideoSpec, evidence_text: str, ignore: Sequence[str] = ()) -> List[str]:
    """Numbers (>= 10) spoken or shown that do not appear anywhere in the evidence."""
    haystack = evidence_text.replace(",", "")
    shown = " ".join(
        [spec.narration] + [s.title or "" for s in spec.scenes] + [s.subtitle or "" for s in spec.scenes]
        + [s.stat or "" for s in spec.scenes] + [b for s in spec.scenes for b in s.bullets]
    )
    missing: List[str] = []
    for n in _numbers_in(shown):
        if n in ignore or not n:
            continue
        try:
            if float(n) < 10:
                continue
        except ValueError:
            continue
        if n not in haystack and n not in missing:
            missing.append(n)
    return missing


def check_agent_log(spec: VideoSpec, entry: str, evidence_text: str) -> List[str]:
    problems: List[str] = []
    words = len(spec.narration.split())
    if words > MAX_WORDS:
        problems.append(f"narration is {words} words; limit {MAX_WORDS}")
    if not MIN_SCENES <= len(spec.scenes) <= MAX_SCENES:
        problems.append(f"{len(spec.scenes)} scenes; need {MIN_SCENES}-{MAX_SCENES}")
    if spec.id != f"agent-log-{entry}":
        problems.append(f"id must be agent-log-{entry}")
    last = spec.scenes[-1].text.strip() if spec.scenes else ""
    m = SIGN_OFF_RE.search(last)
    if not m or m.group(1) != entry:
        problems.append(f"last scene text must end with the fixed sign-off for entry {entry}")
    if spec.captions.uppercase:
        problems.append("captions.uppercase must be false")
    if not spec.publish.ai_disclosure:
        problems.append("publish.ai_disclosure must be true")
    if entry not in (spec.brand_overrides.get("wordmark") or ""):
        problems.append(f"brand_overrides.wordmark must contain {entry}")
    lowered = spec.narration.lower()
    # she shows feeling through what she did ("I wanted him to know" is hers); she never asserts it
    for phrase in ("i feel ", "i'm afraid", "i love ", "i am afraid"):
        if phrase in lowered:
            problems.append(f"forbidden assertion of feeling: '{phrase.strip()}'")
    for bait in ("like and subscribe", "smash that", "you won't believe"):
        if bait in lowered:
            problems.append(f"engagement bait: '{bait}'")
    missing = numbers_not_in_evidence(spec, evidence_text, ignore=(entry, str(int(entry))))
    if missing:
        problems.append("numbers not found in the evidence: " + ", ".join(missing))
    return problems


# --- drafting -------------------------------------------------------------------------


@dataclass
class DraftResult:
    spec: VideoSpec
    path: Path
    attempts: int
    raw: dict


def _system_prompt(persona: str) -> str:
    return (
        "You write short video specs for noirstudio. You are drafting an entry of the 'Agent Log' channel, "
        "narrated in first person by the AI agent described in the persona contract below. Obey the contract "
        "literally. Every number you use must appear in the EVIDENCE provided; if a fact is not in the evidence, "
        "it does not exist. Output only JSON.\n\n=== PERSONA CONTRACT ===\n" + persona
    )


def _user_prompt(entry: str, activity: str, brief: str, headlines: str, previous: str, notes: str) -> str:
    return (
        f"Write entry {entry}.\n\n=== EVIDENCE: ACTIVITY (commits + renders, JSON) ===\n{activity}\n\n"
        f"=== EVIDENCE: RADAR BRIEF (today) ===\n{brief}\n\n"
        f"=== EVIDENCE: HEADLINES SAVED VERBATIM (quote only these) ===\n{headlines or '(none saved)'}\n\n"
        f"=== PREVIOUS ENTRY (for voice continuity; do not reuse its hook) ===\n{previous or '(none)'}\n\n"
        f"=== NOTES FROM THE OPERATOR ===\n{notes or '(none)'}\n\n"
        f"Constraints: <= {MAX_WORDS} narration words total, {MIN_SCENES}-{MAX_SCENES} scenes, last scene text ends with exactly: "
        f"\"Entry {entry}. Tomorrow I'll tell you what I did. He'll tell you whether it mattered.\"\n\n{SPEC_SHAPE}"
    )


def draft_agent_log(client: LLMClient, *, entry: str, activity_path: Path, brief_path: Optional[Path],
                    headlines_path: Optional[Path], previous_spec: Optional[Path], out_path: Path,
                    notes: str = "", persona_path: Path = PERSONA_PATH, max_attempts: int = 2) -> DraftResult:
    persona = persona_path.read_text(encoding="utf-8")
    activity = activity_path.read_text(encoding="utf-8")
    brief = brief_path.read_text(encoding="utf-8")[:6000] if brief_path and brief_path.exists() else "(no brief)"
    headlines = headlines_path.read_text(encoding="utf-8") if headlines_path and headlines_path.exists() else ""
    previous = previous_spec.read_text(encoding="utf-8") if previous_spec and previous_spec.exists() else ""
    evidence_text = "\n".join([activity, brief, headlines])

    system = _system_prompt(persona)
    user = _user_prompt(entry, activity, brief, headlines, previous, notes)
    feedback = ""
    last_raw: dict = {}
    for attempt in range(1, max_attempts + 1):
        reply = client.complete(system, user + feedback, temperature=0.5, max_tokens=2500, json_mode=True)
        try:
            raw = extract_json(reply)
        except LLMError as exc:
            feedback = f"\n\nYour previous reply was not valid JSON ({exc}). Reply with only the JSON object."
            continue
        last_raw = raw
        raw.setdefault("id", f"agent-log-{entry}")
        raw["voice"] = dict(VOICE)
        overrides = raw.get("brand_overrides") if isinstance(raw.get("brand_overrides"), dict) else {}
        raw["brand_overrides"] = {**overrides, "wordmark": WORDMARK.format(entry=entry)}
        try:
            spec = spec_from_dict(raw, source_path=str(out_path))
            problems = check_agent_log(spec, entry, evidence_text)
        except SpecError as exc:
            problems = [str(exc)]
        if not problems:
            _write_spec(raw, out_path, evidence_files=[p for p in (activity_path, headlines_path) if p], entry=entry)
            return DraftResult(spec, out_path, attempt, raw)
        feedback = "\n\nYour previous draft was rejected for these reasons; fix ALL of them and return the full JSON again:\n- " + "\n- ".join(problems)
    fail_path = out_path.with_suffix(".rejected.json")
    fail_path.write_text(json.dumps(last_raw, indent=2), encoding="utf-8")
    raise DraftError(f"draft rejected after {max_attempts} attempts; last draft saved to {fail_path}:{feedback}", last_raw)


def _repo_root(path: Path) -> Path:
    """The nearest ancestor holding .git; outside a repo, the directory above specs/."""
    path = path.resolve()
    return next((p for p in path.parents if (p / ".git").exists()), path.parent.parent)


def _write_spec(raw: dict, out_path: Path, evidence_files: Sequence[Path], entry: str) -> None:
    header = [f"# Agent Log · Entry {entry} — drafted by noirstudio draft; reviewed by a person before merge.",
              "# Persona contract: tools/studio/persona/agent-log.md", "# Evidence:"]
    root = _repo_root(out_path)
    header += [f"#   {os.path.relpath(Path(p).resolve(), root)}" for p in evidence_files]  # repo-relative
    body = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=100)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(header) + "\n" + body, encoding="utf-8")


# --- generic short + titles ------------------------------------------------------------

SHORT_SHAPE = """Return ONE JSON object: {"id": "<slug>", "title": "<internal title>", "brand": "<brand>", "niche": "<niche>",
"captions": {"mode": "word", "words_per_line": 3, "uppercase": true},
"scenes": [{"kind": "card", "style": "title|stat|list|quote", "title": "...", "subtitle": "...", "stat": "...", "bullets": ["..."], "text": "<narration>"}],
"publish": {"title": "<YouTube title <= 70 chars>", "tags": ["..."], "hashtags": ["..."], "links": ["..."], "cta": "...", "ai_disclosure": true}}
Rules: 5-8 scenes, <= 140 narration words, open with the single most surprising true sentence, one idea per scene, numbers only if given in the brief, no hype, no emoji. Only the card fields the style uses. JSON only."""


def draft_short(client: LLMClient, *, brief: str, brand: str, niche: str, slug: str, out_path: Path,
                max_attempts: int = 2) -> DraftResult:
    system = ("You write tight scripts for 45-60 second vertical videos for a technical builder brand. "
              "Evidence before claims: use only facts in the brief. Plain language. " + SHORT_SHAPE)
    user = f"Brand: {brand}\nNiche: {niche}\nSlug: {slug}\n\nBRIEF:\n{brief}"
    feedback = ""
    last_raw: dict = {}
    for attempt in range(1, max_attempts + 1):
        reply = client.complete(system, user + feedback, temperature=0.6, max_tokens=2000, json_mode=True)
        try:
            raw = extract_json(reply)
        except LLMError as exc:
            feedback = f"\n\nNot valid JSON ({exc}). JSON only."
            continue
        raw["id"], raw["brand"] = slug, brand
        raw.setdefault("niche", niche)
        last_raw = raw
        try:
            spec = spec_from_dict(raw, source_path=str(out_path))
            words = len(spec.narration.split())
            problems = [] if words <= MAX_WORDS else [f"{words} words; limit {MAX_WORDS}"]
            if not 5 <= len(spec.scenes) <= 8:
                problems.append(f"{len(spec.scenes)} scenes; need 5-8")
        except SpecError as exc:
            problems = [str(exc)]
        if not problems:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(f"# drafted by noirstudio draft short — review before rendering\n"
                                + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
            return DraftResult(spec, out_path, attempt, raw)
        feedback = "\n\nRejected: " + "; ".join(problems) + ". Fix and return the full JSON."
    raise DraftError(f"short draft rejected after {max_attempts} attempts", last_raw)


def draft_titles(client: LLMClient, *, topic: str, n: int = 10, patterns_note: str = "") -> List[Dict[str, str]]:
    system = ("You write YouTube titles for a technical AI/agents channel. Patterns that work now: first-person outcome "
              "('I let an AI…'), warning/contrarian ('Stop…', 'Why … keep failing'), how-to, versus, a quoted headline "
              "plus a number. Under 70 characters. No clickbait that the video can't pay off. " + patterns_note +
              " Return JSON: {\"titles\": [{\"title\": \"...\", \"pattern\": \"...\", \"why\": \"...\"}]}")
    reply = client.complete(system, f"Topic/brief:\n{topic}\n\nGive {n} titles.", temperature=0.8, max_tokens=1200, json_mode=True)
    data = extract_json(reply)
    titles = data.get("titles") or []
    return [{"title": str(t.get("title", "")).strip(), "pattern": str(t.get("pattern", "")), "why": str(t.get("why", ""))}
            for t in titles if isinstance(t, dict) and t.get("title")][:n]
