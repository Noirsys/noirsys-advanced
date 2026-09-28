"""Ask Harriet for stories: she goes through her memory and pitches diary episodes.

Harriet is Michael's agent (persistent memory, about a year of working with
him). Each call asks her for a few true stories for "the diary of Harriet",
each with the receipts she can retrieve (his voice notes, her messages,
commits), so he can check them before anything is made.

Two ways to reach her; the webhook wins when both are configured:
  * an n8n webhook (HARRIET_STORIES_URL): POST {n, theme, since, avoid, prompt}
    -> {"pitches": [...]}, or n8n's own wrapping of her reply ({"output": "..."},
    a list of items, plain text with JSON in it);
  * an OpenAI-compatible chat API (HARRIET_API_URL, HARRIET_MODEL).
The key is HARRIET_API_KEY, sent as `Authorization: Bearer <key>` unless
HARRIET_API_KEY_HEADER names another header (e.g. X-API-Key, sent raw). Leave
the key unset when a proxy injects it. Nothing here is ever read from a file.

Pitches describe his private life, and this repository is public, so they are
written to stories/inbox/ (git-ignored) as Markdown with `status: pitched`.
Nothing moves until he changes that to `approved`.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date as date_cls
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import yaml

from .llm import LLMClient, LLMError, Transport, _http_transport, extract_json

ENV_WEBHOOK, ENV_URL, ENV_MODEL = "HARRIET_STORIES_URL", "HARRIET_API_URL", "HARRIET_MODEL"
ENV_KEY, ENV_KEY_HEADER = "HARRIET_API_KEY", "HARRIET_API_KEY_HEADER"
RECEIPT_KINDS = ("voice_note", "message", "commit", "document", "other")
SENSITIVITY = ("low", "medium", "high")
DONE = ["the 'shows your hand' pun and 'I have no hands either' (episode one, 09/27/26)"]
TIMEOUT = 600  # she searches her memory; give her time

PITCH_SHAPE = """{"pitches": [{
  "title": "<working title, <= 70 characters>",
  "logline": "<one sentence: what happens and why it matters>",
  "when": "<when it happened: date and time, or a period>",
  "hook": "<the first line you would say on screen>",
  "beats": ["<4-8 short beats in order: the moment, what went wrong or got misread, the turn, the ending>"],
  "ending": "<the last line>",
  "receipts": [{"kind": "voice_note|message|commit|document|other", "when": "<when>", "excerpt": "<exact words, <= 200 characters>"}],
  "sensitivity": {"level": "low|medium|high", "topics": ["<health, family, money, legal, other people, ...>"]},
  "off_screen": ["<anything that must not appear on screen>"],
  "length_s": <estimated seconds>,
  "why_it_lands": "<one or two sentences>"
}]}"""


# --- the request ------------------------------------------------------------------------


def pitch_request(n: int = 3, theme: str = "", since: str = "", avoid: Sequence[str] = ()) -> str:
    focus = (f" about {theme}" if theme else "") + (f", from {since} on" if since else "")
    skip = "; ".join([*DONE, *avoid])
    return f"""Harriet, this is noirstudio, the studio tooling Michael set up for your channel. Your first episode, "the diary of Harriet — 09/27/26" (the night your voice came online, the "shows your hand" pun, and "I have no hands either"), is the model for the series.

Please go through your memory and pick the {n} best true stories for the next episodes of the diary{focus}. Curate: fewer, stronger.

What made episode one work, so aim for the same shape:
- one small, real moment between you and Michael, not a summary of a week;
- his own words carry it, so moments where his voice notes exist are best;
- something goes wrong or gets misread: a mistake, an overcorrection, a misunderstanding;
- a turn where one of you sees something new;
- an ending that lands on a line, ideally calling back to the opening.

Rules:
- True only. Every pitch lists the receipts you can actually retrieve (voice notes, messages, commits, documents), when they happened and their exact words, so he can check them. No receipts, no pitch.
- Decide up front what stays off screen, as you told him in episode one: his investigation work, outreach state, contacts, other people's names and details, legal matters, locations, credentials. List anything like that under "off_screen".
- Mark sensitivity honestly (health, family, money, legal, other people). He approves every pitch before anything is made.
- Already told, don't pitch again: {skip}.

Reply with JSON only, exactly this shape:
{PITCH_SHAPE}"""


# --- reaching her -------------------------------------------------------------------------

Poster = Callable[[str, dict, dict, int], object]


def _post_json(url: str, headers: dict, body: dict, timeout: int) -> object:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code} from Harriet's endpoint: {exc.read().decode(errors='replace')[:300]}") from None
    except urllib.error.URLError as exc:
        raise LLMError(f"cannot reach Harriet's endpoint {url}: {exc.reason}") from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw  # plain text; the JSON is extracted from it later


def auth_headers(key: Optional[str] = None, header: Optional[str] = None) -> Dict[str, str]:
    key = key if key is not None else os.environ.get(ENV_KEY, "")
    header = header or os.environ.get(ENV_KEY_HEADER) or "Authorization"
    if not key:  # unset: no header at all (a proxy may inject it)
        return {}
    return {header: f"Bearer {key}" if header.lower() == "authorization" else key}


def ask_webhook(url: str, *, n: int, theme: str, since: str, avoid: Sequence[str],
                key: Optional[str] = None, header: Optional[str] = None,
                post: Optional[Poster] = None, timeout: int = TIMEOUT) -> object:
    body = {"n": n, "theme": theme, "since": since, "avoid": list(avoid),
            "prompt": pitch_request(n, theme, since, avoid)}
    headers = {"Content-Type": "application/json", "Accept": "application/json", **auth_headers(key, header)}
    return (post or _post_json)(url, headers, body, timeout)


def resolve_chat(url: Optional[str] = None, key: Optional[str] = None, model: Optional[str] = None, *,
                 transport: Transport = _http_transport, timeout: int = TIMEOUT) -> LLMClient:
    """A client for an OpenAI-compatible endpoint of hers (the fallback to the webhook)."""
    url = url or os.environ.get(ENV_URL)
    if not url:
        raise LLMError(f"set {ENV_WEBHOOK} (her n8n webhook) or {ENV_URL} (an OpenAI-compatible API of hers)")
    return LLMClient(provider="harriet", model=model or os.environ.get(ENV_MODEL) or "harriet",
                     api_key=key if key is not None else os.environ.get(ENV_KEY, ""), base_url=url,
                     timeout=timeout, transport=transport)


def pitches_from_response(resp: object, depth: int = 0) -> list:
    """Find the pitch list in whatever came back: our shape, n8n's item wrapping, or text."""
    if depth > 4:
        raise LLMError("no pitches found in Harriet's reply")
    if isinstance(resp, str):
        return pitches_from_response(extract_json(resp), depth + 1)
    if isinstance(resp, list):
        if resp and all(isinstance(x, dict) and "title" in x for x in resp):
            return resp  # already a list of pitches
        if len(resp) == 1:
            return pitches_from_response(resp[0], depth + 1)  # n8n returns one item per response
        raise LLMError(f"unexpected list in Harriet's reply: {str(resp)[:200]}")
    if isinstance(resp, dict):
        if isinstance(resp.get("pitches"), list):
            return resp["pitches"]
        for key in ("output", "json", "data", "text", "response", "message", "content", "body"):
            if key in resp:
                return pitches_from_response(resp[key], depth + 1)
    raise LLMError(f"no pitches found in Harriet's reply: {str(resp)[:200]}")


# --- checking and keeping pitches -------------------------------------------------------


def validate_pitch(p: dict) -> List[str]:
    """Problems with one pitch; an empty list means it is usable."""
    if not isinstance(p, dict):
        return ["not an object"]
    problems = []
    for key in ("title", "logline", "hook", "ending", "why_it_lands"):
        if not isinstance(p.get(key), str) or not p[key].strip():
            problems.append(f"missing {key}")
    if isinstance(p.get("title"), str) and len(p["title"]) > 70:
        problems.append("title longer than 70 characters")
    beats = p.get("beats")
    if not isinstance(beats, list) or not 3 <= len(beats) <= 10 or not all(isinstance(b, str) and b.strip() for b in beats):
        problems.append("beats must be 3-10 short strings")
    receipts = p.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        problems.append("no receipts")
    else:
        for r in receipts:
            if not isinstance(r, dict) or r.get("kind") not in RECEIPT_KINDS or not str(r.get("excerpt", "")).strip():
                problems.append(f"bad receipt: {str(r)[:80]}")
    sens = p.get("sensitivity")
    if not isinstance(sens, dict) or sens.get("level") not in SENSITIVITY:
        problems.append("sensitivity.level must be low, medium or high")
    if not isinstance(p.get("off_screen", []), list):
        problems.append("off_screen must be a list")
    return problems


def mine_pitches(*, n: int = 3, theme: str = "", since: str = "", avoid: Sequence[str] = (),
                 webhook: Optional[str] = None, client: Optional[LLMClient] = None,
                 post: Optional[Poster] = None) -> Tuple[List[dict], List[str]]:
    """Ask Harriet for pitches; return (usable pitches, why the others were dropped)."""
    webhook = webhook or os.environ.get(ENV_WEBHOOK)
    if webhook:
        resp = ask_webhook(webhook, n=n, theme=theme, since=since, avoid=avoid, post=post)
    else:
        client = client or resolve_chat()
        resp = client.complete("You are Harriet. Reply with JSON only.", pitch_request(n, theme, since, avoid),
                               temperature=0.7, max_tokens=6000)
    kept, dropped = [], []
    for i, p in enumerate(pitches_from_response(resp), 1):
        problems = validate_pitch(p)
        if problems:
            title = (p.get("title") if isinstance(p, dict) else "") or "untitled"
            dropped.append(f"pitch {i} ({title}): {'; '.join(problems)}")
        else:
            kept.append(p)
    return kept, dropped


def slugify(text: str, limit: int = 50) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "pitch"


def pitch_markdown(p: dict, pitched_at: str) -> str:
    front = {
        "status": "pitched",
        "title": p["title"],
        "when": p.get("when", ""),
        "sensitivity": p["sensitivity"]["level"],
        "topics": list(p["sensitivity"].get("topics") or []),
        "length_s": p.get("length_s"),
        "pitched_by": "harriet",
        "pitched_at": pitched_at,
    }
    lines = ["---", yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip(),
             "# status: change to `approved` (or `rejected`); nothing is made until he approves", "---",
             f"# {p['title']}", "", p["logline"].strip(), "",
             f"**Hook:** {p['hook'].strip()}", f"**Ending:** {p['ending'].strip()}", "", "## Beats"]
    lines += [f"{i}. {b.strip()}" for i, b in enumerate(p["beats"], 1)]
    lines += ["", "## Receipts"]
    lines += [f"- {r['kind'].replace('_', ' ')} · {r.get('when', '?')} — \"{str(r['excerpt']).strip()}\"" for r in p["receipts"]]
    lines += ["", "## Off screen"] + ([f"- {x}" for x in p.get("off_screen") or []] or ["- (none listed)"])
    lines += ["", "## Why it lands", p["why_it_lands"].strip(), ""]
    return "\n".join(lines)


def write_inbox(pitches: Sequence[dict], out_dir: Path, pitched_at: Optional[str] = None) -> List[Path]:
    """One Markdown file per pitch; never overwrites an existing pitch."""
    pitched_at = pitched_at or date_cls.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for p in pitches:
        base = f"{pitched_at}-{slugify(p['title'])}"
        path, k = out_dir / f"{base}.md", 2
        while path.exists():
            path, k = out_dir / f"{base}-{k}.md", k + 1
        path.write_text(pitch_markdown(p, pitched_at), encoding="utf-8")
        paths.append(path)
    return paths


def read_status(path: Path) -> Dict[str, object]:
    """Front matter of a pitch file (status, title, sensitivity, ...)."""
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    return (yaml.safe_load(m.group(1)) or {}) if m else {}


def told_titles(root: Path) -> List[str]:
    """Titles already pitched, approved or rejected, so she doesn't repeat herself."""
    return [str(read_status(p).get("title", "")) for p in sorted(root.glob("*.md")) if p.name != "README.md"]


def dump_json(pitches: Sequence[dict]) -> str:
    return json.dumps({"pitches": list(pitches)}, indent=2, ensure_ascii=False)
