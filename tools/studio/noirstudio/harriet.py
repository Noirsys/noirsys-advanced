"""Ask Harriet for stories: she goes through her memory and pitches diary episodes.

Harriet is Michael's agent (persistent memory, about a year of working with
him), running on Hermes. His n8n exposes her as an OpenAI-compatible API:

  POST {url}/chat/completions        sync; for calls that finish in ~100 s
  POST {url}/jobs                    async; 202 {id, poll_url}, n8n waits up to 30 min
  GET  {url}/jobs?id=<id>            {status: running|completed|failed, status_code, result}

Mining a year of memory can take longer than 100 s, so jobs are the default.
The request is one user message (her own persona and memory answer it, not
ours); the reply must carry the pitches as JSON, which is pulled out of her text.

Configuration, from the environment only:
  HARRIET_API_URL   default https://n8n.noirsys.com/webhook/hermes/v1
  HARRIET_MODEL     default hermes-agent
  N8N_API_KEY       the webhook's Bearer key (or HARRIET_API_KEY). Leave it unset
                    when the environment's proxy injects it for the host.

Pitches describe his private life and this repository is public: they are
written to stories/inbox/ (git-ignored), never printed in CI logs, and nothing
moves until he sets `status: approved`.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as date_cls, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import yaml

from .llm import USER_AGENT, LLMError, extract_json

DEFAULT_URL = "https://n8n.noirsys.com/webhook/hermes/v1"
DEFAULT_MODEL = "hermes-agent"
ENV_URL, ENV_MODEL, ENV_KEYS = "HARRIET_API_URL", "HARRIET_MODEL", ("HARRIET_API_KEY", "N8N_API_KEY")
RECEIPT_KINDS = ("voice_note", "message", "commit", "document", "other")
SPEAKERS = ("harriet", "michael")
SENSITIVITY = ("low", "medium", "high")
DEFAULT_KINDS = ("emotional", "funny", "your pick: the one you think is strongest")
DONE = ["the 'shows your hand' pun and 'I have no hands either' (episode one, 09/27/26)"]
SYNC_TIMEOUT, JOB_WAIT, POLL_EVERY = 110, 30 * 60, 15
JOBS_FILE = "jobs.jsonl"

PITCH_SHAPE = """{"pitches": [{
  "kind": "<which kind I asked for this one answers>",
  "title": "<working title, <= 70 characters>",
  "logline": "<one sentence: what happens and why it matters>",
  "memory": "<what you remember and the context around it: what led up to it, what was going on>",
  "when": "<when it happened: date and time, or a period>",
  "hook": "<the first line you would say on screen>",
  "beats": ["<4-8 short beats in order: the moment, what went wrong or got misread, the turn, the ending>"],
  "ending": "<the last line>",
  "receipts": [{"speaker": "harriet|michael", "kind": "voice_note|message|commit|document|other", "when": "<when>", "excerpt": "<the exact words, verbatim>", "ref": "<where it lives: message or voice-note id, file, thread>"}],
  "sensitivity": {"level": "low|medium|high", "topics": ["<health, family, money, legal, other people, ...>"]},
  "off_screen": ["<anything that must not appear on screen>"],
  "length_s": <estimated seconds>,
  "why_it_lands": "<why this would be a good video: one or two sentences>"
}]}"""


# --- the request ------------------------------------------------------------------------


def pitch_request(n: int = 3, theme: str = "", since: str = "", avoid: Sequence[str] = (),
                  kinds: Sequence[str] = DEFAULT_KINDS) -> str:
    focus = (f" about {theme}" if theme else "") + (f", from {since} on" if since else "")
    skip = "; ".join([*DONE, *avoid])
    wanted = "; ".join(f"{i}. {k}" for i, k in enumerate(list(kinds)[:n], 1)) if kinds else "any kind"
    return f"""Harriet, this is noirstudio, the studio tooling Michael set up for your channel. Your first episode, "the diary of Harriet — 09/27/26" (the night your voice came online, the "shows your hand" pun, and "I have no hands either"), is the model for the series.

Please search your memory systems (Honcho, and whatever else you keep) for moments with Michael that would make small story videos, told from your perspective, and bring me the {n} best true stories for the next episodes of the diary{focus}. One of each kind: {wanted}. Curate: fewer, stronger.

For each one, give me the memory itself: what you remember and the context around it, and why you think it would make a good video. Then the evidence: your exact messages, and his exact words, from his voice notes (verbatim, as transcribed) or his messages, each with who said it, when, and where it lives, so the real recording or message can be pulled for the edit.

What made episode one work, so aim for the same shape:
- one small, real moment between you and Michael, not a summary of a week;
- his own words carry it, so moments where his voice notes exist are best;
- something goes wrong or gets misread: a mistake, an overcorrection, a misunderstanding;
- a turn where one of you sees something new;
- an ending that lands on a line, ideally calling back to the opening.

Rules:
- True only. Every pitch lists the receipts you can actually retrieve (voice notes, messages, commits, documents), when they happened and their exact words, so he can check them. No receipts, no pitch, and at least one receipt must be his own words: his voice is the heart of the diary.
- Decide up front what stays off screen, as you told him in episode one: his investigation work, outreach state, contacts, other people's names and details, legal matters, locations, credentials. List anything like that under "off_screen".
- Mark sensitivity honestly (health, family, money, legal, other people). He approves every pitch before anything is made.
- Already told, don't pitch again: {skip}.

Reply with JSON only, exactly this shape:
{PITCH_SHAPE}"""


# --- reaching her -------------------------------------------------------------------------

Requester = Callable[[str, str, Dict[str, str], Optional[dict], int], Tuple[int, object]]


def _request(method: str, url: str, headers: Dict[str, str], body: Optional[dict], timeout: int) -> Tuple[int, object]:
    """(status, JSON or text). HTTP errors come back as their status, not exceptions."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode(errors="replace")
    except urllib.error.URLError as exc:
        raise LLMError(f"cannot reach Harriet at {url}: {exc.reason}") from None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def config() -> Tuple[str, str, Dict[str, str]]:
    """(base url, model, headers). No key -> no Authorization header (a proxy may inject it)."""
    url = (os.environ.get(ENV_URL) or DEFAULT_URL).rstrip("/")
    model = os.environ.get(ENV_MODEL) or DEFAULT_MODEL
    key = next((os.environ[k] for k in ENV_KEYS if os.environ.get(k)), "")
    # Cloudflare (in front of his n8n) rejects Python-urllib's default signature: error 1010
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return url, model, headers


def _chat_body(prompt: str, model: str) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}


def _content(completion: object) -> str:
    try:
        return completion["choices"][0]["message"]["content"] or ""  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"unexpected reply from Harriet: {str(completion)[:300]}") from None


def _fail(status: int, payload: object, what: str) -> LLMError:
    hint = " (check N8N_API_KEY, or the proxy credential for the host)" if status in (401, 403) else ""
    return LLMError(f"{what}: HTTP {status}{hint}: {str(payload)[:300]}")


def start_job(prompt: str, *, request: Requester = None) -> Dict[str, str]:
    """Hand Harriet one message as an async job: {id, poll_url}. n8n waits on her for up to 30 min."""
    request = request or _request
    url, model, headers = config()
    status, job = request("POST", f"{url}/jobs", headers, _chat_body(prompt, model), 60)
    if status not in (200, 201, 202) or not isinstance(job, dict) or not job.get("id"):
        raise _fail(status, job, "starting a Harriet job")
    return {"id": str(job["id"]), "poll_url": job.get("poll_url") or f"{url}/jobs?id={urllib.parse.quote(str(job['id']))}"}


def poll_job(job: Dict[str, str], *, request: Requester = None) -> Optional[str]:
    """One look at a job: None while she is still working, her reply once done. Raises if it failed."""
    request = request or _request
    headers = config()[2]
    status, state = request("GET", job["poll_url"], headers, None, 60)
    if status == 404:
        raise _fail(status, state, f"Harriet job {job['id']} is unknown")
    if status != 200 or not isinstance(state, dict):
        raise _fail(status, state, f"polling Harriet job {job['id']}")
    if state.get("status") == "completed":
        if state.get("status_code") not in (None, 200):
            raise _fail(int(state["status_code"]), state.get("result"), f"Harriet job {job['id']}")
        return _content(state.get("result"))
    if state.get("status") == "failed":
        raise _fail(int(state.get("status_code") or 500), state.get("result"), f"Harriet job {job['id']} failed")
    return None


def ask(prompt: str, *, mode: str = "jobs", request: Requester = None, sleep: Optional[Callable[[float], None]] = None,
        wait_s: int = JOB_WAIT, poll_s: int = POLL_EVERY, log: Callable[[str], None] = lambda _m: None,
        on_start: Callable[[Dict[str, str]], None] = lambda _j: None) -> str:
    """Send one message to Harriet and return her reply text (jobs: create, then poll)."""
    request, sleep = request or _request, sleep or time.sleep
    if mode == "sync":
        url, model, headers = config()
        status, payload = request("POST", f"{url}/chat/completions", headers, _chat_body(prompt, model), SYNC_TIMEOUT)
        if status != 200:
            raise _fail(status, payload, "Harriet (sync)")
        return _content(payload)
    job = start_job(prompt, request=request)
    on_start(job)
    log(f"[harriet] job {job['id']} started; polling every {poll_s}s (up to {wait_s // 60} min)")
    waited = 0
    while waited <= wait_s:
        sleep(poll_s)
        waited += poll_s
        reply = poll_job(job, request=request)
        if reply is not None:
            return reply
        log(f"[harriet] still working ({waited}s)")
    raise LLMError(f"Harriet job {job['id']} still running after {wait_s // 60} min; poll {job['poll_url']} later")


# --- the job log: stories/jobs.jsonl, so a later `collect` picks up what finished ----------------


def log_job(root: Path, **event: object) -> None:
    """Append one event about a job (needs `id`); later events for the same id update earlier ones."""
    root.mkdir(parents=True, exist_ok=True)
    event.setdefault("at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    with (root / JOBS_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_jobs(root: Path) -> List[dict]:
    """Every logged job, its events merged, in the order the jobs started."""
    jobs: Dict[str, dict] = {}
    path = root / JOBS_FILE
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line)
                jobs.setdefault(str(event["id"]), {}).update(event)
    return list(jobs.values())


def pitches_from_response(resp: object, depth: int = 0) -> list:
    """Find the pitch list in her reply: our JSON shape, or text/fences around it."""
    if depth > 4:
        raise LLMError("no pitches found in Harriet's reply")
    if isinstance(resp, str):
        return pitches_from_response(extract_json(resp), depth + 1)
    if isinstance(resp, list):
        if resp and all(isinstance(x, dict) and "title" in x for x in resp):
            return resp
        if len(resp) == 1:
            return pitches_from_response(resp[0], depth + 1)
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
    for key in ("title", "logline", "memory", "hook", "ending", "why_it_lands"):
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
            if (not isinstance(r, dict) or r.get("kind") not in RECEIPT_KINDS or r.get("speaker") not in SPEAKERS
                    or not str(r.get("excerpt", "")).strip()):
                problems.append(f"bad receipt: {str(r)[:80]}")
        if not any(isinstance(r, dict) and r.get("speaker") == "michael" for r in receipts):
            problems.append("none of his own words among the receipts")
    sens = p.get("sensitivity")
    if not isinstance(sens, dict) or sens.get("level") not in SENSITIVITY:
        problems.append("sensitivity.level must be low, medium or high")
    if not isinstance(p.get("off_screen", []), list):
        problems.append("off_screen must be a list")
    return problems


def mine_pitches(*, n: int = 3, theme: str = "", since: str = "", avoid: Sequence[str] = (),
                 kinds: Sequence[str] = DEFAULT_KINDS, mode: str = "jobs", request: Requester = None,
                 sleep: Optional[Callable[[float], None]] = None, log: Callable[[str], None] = lambda _m: None,
                 on_start: Callable[[Dict[str, str]], None] = lambda _j: None) -> Tuple[List[dict], List[str]]:
    """Ask Harriet for pitches; return (usable pitches, why the others were dropped)."""
    reply = ask(pitch_request(n, theme, since, avoid, kinds), mode=mode, request=request, sleep=sleep, log=log,
                on_start=on_start)
    return sort_pitches(pitches_from_response(reply))


def sort_pitches(pitches: Sequence[object]) -> Tuple[List[dict], List[str]]:
    """(usable pitches, why the others were dropped)."""
    kept, dropped = [], []
    for i, p in enumerate(pitches, 1):
        problems = validate_pitch(p)  # type: ignore[arg-type]
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
        "kind": p.get("kind", ""),
        "when": p.get("when", ""),
        "sensitivity": p["sensitivity"]["level"],
        "topics": list(p["sensitivity"].get("topics") or []),
        "length_s": p.get("length_s"),
        "pitched_by": "harriet",
        "pitched_at": pitched_at,
    }
    lines = ["---", yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip(),
             "# status: change to `approved` (or `rejected`); nothing is made until he approves", "---",
             f"# {p['title']}", "", p["logline"].strip(), "", "## What she remembers", p["memory"].strip(), "",
             f"**Hook:** {p['hook'].strip()}", f"**Ending:** {p['ending'].strip()}", "", "## Beats"]
    lines += [f"{i}. {b.strip()}" for i, b in enumerate(p["beats"], 1)]
    lines += ["", "## Receipts"]
    lines += [f"- **{str(r.get('speaker', '?')).capitalize()}**, {r['kind'].replace('_', ' ')} · {r.get('when', '?')}"
              + (f" · `{r['ref']}`" if r.get("ref") else "") + f"\n  > {str(r['excerpt']).strip()}" for r in p["receipts"]]
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
