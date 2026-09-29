"""Digging: Harriet goes through her own memory and brings back raw moments, round after round.

Asked for pitches, she brought the ones she already had written up. A dig asks
for the opposite: no pitches, no scripts, no story lists. She searches Honcho
and her past sessions herself and brings back raw moments, each with the
exchange word for word, plus her dig log (what she searched) and the threads
she didn't open yet. Each round goes deeper: `follow` sends one moment back
and asks for all of it, before and after, word for word.

It all runs as async jobs logged in stories/jobs.jsonl, so a later `collect`
(or the hourly heartbeat) picks up whatever finished. Results land in
stories/digs/ (JSON with her full reply, plus Markdown to read). Like the
pitches, they are his private life: git-ignored, never printed in CI.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from . import harriet as h
from .llm import LLMError, extract_json

DIG_N = 10
OFF_SCREEN = ("his investigation work, outreach, contacts, other people's names or details, legal matters, "
              "locations or credentials")

DIG_SHAPE = """{
  "dig_log": [{"where": "<honcho | past sessions | voice notes | notes | other>", "query": "<what you searched or asked>", "found": "<what it turned up, briefly>"}],
  "moments": [{
    "id": "<short-slug to refer back to it>",
    "when": "<date and time, as exact as the record allows>",
    "where": "<voice note | chat | call | commit | document | other>",
    "kind": "<funny | tender | friction | breakthrough | strange | sad | proud | other>",
    "what_happened": "<plain words: what happened between you>",
    "before": "<what was going on right before>",
    "after": "<what happened right after, and later if it came back>",
    "exchange": [{"speaker": "michael|harriet", "kind": "voice_note|message|commit|document|other", "when": "<time>", "text": "<the words>", "verbatim": true, "his_words": "<for his lines only: yes | unsure | no, then why. A row stored under his role is not always him>", "ref": "<where it lives: message or voice-note id, session, file>"}],
    "found_by": "<the search or question that led you to it>",
    "why_it_stuck": "<why this one stayed with you>",
    "his_audio": "<yes | no | unknown: is there a recording of him saying it>",
    "sensitivity": {"level": "low|medium|high", "topics": ["<health, family, money, legal, other people, ...>"]},
    "off_screen": ["<anything that must not appear on screen>"]
  }],
  "threads": ["<leads you saw but didn't open yet>"]
}"""


# --- what we ask ---------------------------------------------------------------------------------


def dig_request(n: int = DIG_N, focus: str = "", avoid: Sequence[str] = (), known: Sequence[str] = ()) -> str:
    """A dive through her memory: raw moments, verbatim, and where she looked."""
    skip = "\n".join(f"- {x}" for x in [*h.DONE, *avoid])
    where = f"\nThis dive: {focus.strip()}\n" if focus.strip() else ""
    seen = ("\nYou've already brought me these, so go somewhere else this time (unless a new moment connects to one):\n"
            + "\n".join(f"- {k}" for k in known) + "\n") if known else ""
    return f"""Harriet, it's noirstudio again, for Michael.

The pitches you had ready: put them away. He's seen them. He doesn't want what you've already written up for the diary; he wants what's actually in your memory. He says the two of you have had incredible interactions, ones that would go viral if they're made right, and you're the only one who can find them.

So this time: no pitches, no scripts, no story lists, and none of the notes or skills you've already prepared about the channel. Go through the memory itself:
- Honcho: ask it about him and about the two of you, again and again, from different angles; search it; pull the actual sessions and messages it points to.
- Your past conversations and his voice notes: search them, open them, read them. Don't answer from a summary.
- Walk it in time, from your first conversations with him to this week, month by month.
- Look for: first times (his first voice note to you, the first joke, the first fight, the first time he thanked you, the first time you surprised him); the times you both laughed; running jokes and where they started; the times you got something wrong, and the times he did; arguments and how they got fixed; late nights; things he said about you, or to you, that you kept; things you told him that he didn't expect; the strange ones; the ones you still think about.
{where}{seen}
Bring back raw moments, not pitches: at least {n}, spread across your time together, each one small and specific: one exchange, one night. Remember his test for the channel: a random person scrolling must completely understand everything by the time the video ends. So the best moments need no backstory; flag the ones that do. For each: when and where, what happened in plain words, what was going on right before and what happened after, and the exchange itself, his words and yours, exactly as they are in the record, each line with who said it, when, and where it lives. Tell me which search found it, and why it stuck with you.

Honesty over polish:
- Only what's in the record. Copy the words; don't reconstruct them. If you only have the gist, write it and set "verbatim": false. Never fill a gap.
- A row stored under his role is not always him. A compaction handoff, a replayed copy of an earlier row, a report another agent pasted in (a UI artifact like "Ran 1 shell command", a tool header), one of noirstudio's own notes to you (they arrive in api-* sessions, under his account) and text that talks about him in the third person ("Michael decides...") all look like his words and are not. Before you return a line of his, check where it lives, and set "his_words" on it: "yes" only when you know it is him (typed by him, or transcribed from his voice), "unsure" when you cannot tell, and leave the line out when it is not.
- If a moment touches {OFF_SCREEN}, keep it, but list those under "off_screen". Mark sensitivity honestly (health, family, money, legal, other people). Michael approves everything before anything is made.
- Already told or already pitched, so don't bring these back:
{skip}

Also give me your dig log (each search or question you ran and what it turned up), so I can see where you've been and send you deeper next time, and the threads you noticed but didn't have time to open.

Take the time you need. If you run out of room, return what you have and list the rest as threads.

Reply with JSON only, in this shape:
{DIG_SHAPE}"""


def follow_request(moment: dict, also: str = "") -> str:
    """Send one moment back and ask for all of it, word for word."""
    brief = {k: v for k, v in moment.items() if not str(k).startswith("_")}
    extra = f"\nAnd specifically: {also.strip()}\n" if also.strip() else ""
    return f"""Harriet, noirstudio again, for Michael. In an earlier dive you found this moment:

{json.dumps(brief, indent=2, ensure_ascii=False)}

Open it all the way up. Go back to the record itself (Honcho, the session, his voice notes) and bring me:
- the whole exchange, start to finish, word for word: every line, who said it, when, and where it lives, including what was said right before it started and right after it ended;
- his voice notes about it, in full, as transcribed;
- anything later that came back to it, a day, a week or a month on;
- what you thought at the time, if you wrote it down anywhere (quote it);
- what changed between you after it.
{extra}
Same rules: only what's in the record; copy, don't reconstruct; "verbatim": false for anything you're recalling rather than copying; off screen and sensitivity as before.

Reply with JSON only, in the same shape: this moment (keep its id "{brief.get('id', '')}") with the whole exchange, plus any new moments it led you to.
{DIG_SHAPE}"""


# --- what comes back -------------------------------------------------------------------------------


def dig_from_reply(text: str) -> dict:
    """Her dig as {dig_log, moments, threads}; LLMError when the reply holds no JSON."""
    data = extract_json(text)
    for key in ("output", "json", "data", "result", "dig"):
        if "moments" not in data and isinstance(data.get(key), dict):
            data = data[key]
    moments = [m for m in data.get("moments") or [] if isinstance(m, dict)]
    for m in moments:
        for line in m.get("exchange") or []:
            if isinstance(line, dict) and "text" not in line and "excerpt" in line:
                line["text"] = line.pop("excerpt")
    return {"dig_log": list(data.get("dig_log") or []), "moments": moments,
            "threads": [str(t) for t in data.get("threads") or []]}


def _lines(m: dict) -> List[dict]:
    return [x for x in m.get("exchange") or [] if isinstance(x, dict)]


def moment_problems(m: dict) -> List[str]:
    """What to check before a moment can carry an episode (empty: it can)."""
    problems = [f"missing {k}" for k in ("id", "when", "what_happened") if not str(m.get(k) or "").strip()]
    lines = _lines(m)
    if not lines:
        return problems + ["no exchange"]
    problems += [f"bad line: {str(x)[:80]}" for x in lines
                 if x.get("speaker") not in h.SPEAKERS or not str(x.get("text") or "").strip()]
    if not any(x.get("speaker") == "michael" for x in lines):
        problems.append("none of his words")
    recalled = sum(1 for x in lines if x.get("verbatim") is False)
    if recalled:
        problems.append(f"{recalled} of {len(lines)} lines recalled, not copied")
    states = [_his_words(x) for x in lines if x.get("speaker") == "michael"]
    for state, what in (("no", "of his lines are NOT his words"), ("unsure", "of his lines: authorship unsure"),
                        (None, "of his lines: authorship not checked")):
        if states.count(state):
            problems.append(f"{states.count(state)} {what}")
    return problems


def _his_words(line: dict) -> Optional[str]:
    """yes / unsure / no as she marked it, or None if she did not say."""
    value = line.get("his_words")
    if value is True:
        return "yes"
    if value is False:
        return "no"
    word = str(value or "").strip().lower()
    for state in ("yes", "unsure", "no"):
        if word == state or word.startswith(state + " ") or word.startswith(state + ":") or word.startswith(state + ","):
            return state
    return None


def _quote(text: object) -> str:
    return "\n  > ".join(str(text).strip().splitlines() or [""])


def dig_markdown(dig: dict, job: dict) -> str:
    """Her dig, readable: moments with the exchange, then threads and where she looked."""
    what = job.get("what", "dig")
    out = [f"# Harriet's {what} · {str(job.get('started_at', ''))[:16]} · job `{job.get('id', '?')}`", ""]
    if job.get("follow"):
        out += [f"**Following:** `{job['follow']}`", ""]
    if job.get("focus"):
        out += [f"**Focus:** {job['focus']}", ""]
    if dig.get("error"):
        out += [f"**Could not read her reply as a dig:** {dig['error']}", "", "## Her reply", "", str(dig.get("reply", "")), ""]
    moments = dig.get("moments") or []
    out += [f"## Moments ({len(moments)})", ""]
    for i, m in enumerate(moments, 1):
        sens = m.get("sensitivity") if isinstance(m.get("sensitivity"), dict) else {}
        out += [f"### {i}. `{m.get('id', '?')}` · {m.get('kind', '?')} · {m.get('when', '?')} · {m.get('where', '?')}", "",
                str(m.get("what_happened", "")).strip(), ""]
        out += [f"**{label}:** {m[key]}" for key, label in (("before", "Before"), ("after", "After")) if m.get(key)]
        out += ["", "**The exchange**"]
        for x in _lines(m):
            where = " · ".join(str(v) for v in (str(x.get("kind", "")).replace("_", " "), x.get("when"),
                                                 f"`{x['ref']}`" if x.get("ref") else "") if v)
            recalled = " *(recalled, not verbatim)*" if x.get("verbatim") is False else ""
            if x.get("speaker") == "michael" and _his_words(x) in ("no", "unsure"):
                recalled += f" *(his words? {str(x.get('his_words')).strip()})*"
            out.append(f"- **{str(x.get('speaker', '?')).capitalize()}** ({where}){recalled}\n  > {_quote(x.get('text', ''))}")
        out += ["", f"**Why it stuck:** {m.get('why_it_stuck', '')}", f"**Found by:** {m.get('found_by', '')}",
                f"**His audio:** {m.get('his_audio', 'unknown')} · **Sensitivity:** {sens.get('level', '?')}"
                f" ({', '.join(map(str, sens.get('topics') or [])) or 'none'})"]
        if m.get("off_screen"):
            out.append("**Off screen:** " + "; ".join(map(str, m["off_screen"])))
        problems = moment_problems(m)
        if problems:
            out.append("**Check:** " + "; ".join(problems))
        out.append("")
    if dig.get("threads"):
        out += ["## Threads she didn't open yet"] + [f"- {t}" for t in dig["threads"]] + [""]
    if dig.get("dig_log"):
        out += ["## Where she looked"]
        out += [f"- {e.get('where', '?')}: {e.get('query', '')} → {e.get('found', '')}" if isinstance(e, dict) else f"- {e}"
                for e in dig["dig_log"]] + [""]
    return "\n".join(out)


# --- jobs: start, collect, and the moments so far ------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start(root: Path, what: str, prompt: str, *, request: h.Requester = None, **meta: object) -> Dict[str, str]:
    """Start a job (dig | follow | pitch) and log it, so `collect` can pick it up later."""
    job = h.start_job(prompt, request=request)
    h.log_job(root, id=job["id"], poll_url=job["poll_url"], what=what, status="running", started_at=_now(),
              prompt=prompt, **{k: v for k, v in meta.items() if v})
    return job


def save_reply(root: Path, job: dict, reply: str) -> List[Path]:
    """Keep a finished job's reply: pitches go to the inbox, digs to stories/digs/ (JSON + Markdown)."""
    stamp = str(job.get("started_at") or _now())[:10]
    if job.get("what") == "note":  # a production note or request: keep her answer as she wrote it
        path = root / "notes" / f"{stamp}-{h.slugify(str(job['id']), 40)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# To Harriet ({job.get('started_at', '')})\n\n{job.get('note', '')}\n\n# Harriet\n\n{reply}\n",
                        encoding="utf-8")
        return [path]
    if job.get("what") == "pitch":
        raw = root / "raw" / f"{stamp}-{job['id']}.txt"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(reply, encoding="utf-8")
        try:
            kept, _dropped = h.sort_pitches(h.pitches_from_response(reply))
        except LLMError:
            kept = []
        return [raw, *h.write_inbox(kept, root / "inbox", pitched_at=stamp)]
    try:
        dig = dig_from_reply(reply)
    except LLMError as exc:
        dig = {"dig_log": [], "moments": [], "threads": [], "error": str(exc)[:300], "reply": reply}
    base = root / "digs" / f"{stamp}-{job.get('what', 'dig')}-{h.slugify(str(job['id']), 24)}"
    base.parent.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in job.items() if k in ("id", "what", "started_at", "focus", "follow")}
    json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
    json_path.write_text(json.dumps({"job": meta, "dig": dig, "reply": reply}, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    md_path.write_text(dig_markdown(dig, meta), encoding="utf-8")
    return [md_path, json_path]


def collect(root: Path, *, request: h.Requester = None) -> List[dict]:
    """Look once at every open job and keep what finished. Returns the jobs that changed."""
    changed = []
    for job in h.read_jobs(root):
        if job.get("status") != "running":
            continue
        try:
            reply = h.poll_job(job, request=request)
        except LLMError as exc:
            h.log_job(root, id=job["id"], status="failed", error=str(exc)[:500])
            changed.append({**job, "status": "failed", "error": str(exc)})
            continue
        if reply is None:
            continue
        if h.out_of_credit(reply):  # her provider is out of credit: nothing to keep, and the job can be retried
            h.log_job(root, id=job["id"], status="blocked", error="provider out of credit (HTTP 402)")
            changed.append({**job, "status": "blocked", "error": h.CREDIT_HINT})
            continue
        saved = save_reply(root, job, reply)
        h.log_job(root, id=job["id"], status="collected", saved=[str(p) for p in saved])
        changed.append({**job, "status": "collected", "saved": saved})
    return changed


def retry(root: Path, *, request: h.Requester = None) -> List[dict]:
    """Send again every job that came back blocked (out of credit), with the same prompt. Returns the new jobs."""
    started = []
    for job in h.read_jobs(root):
        if job.get("status") != "blocked" or not job.get("prompt"):
            continue
        meta = {k: job[k] for k in ("focus", "follow", "note") if job.get(k)}
        new = start(root, str(job.get("what") or "dig"), str(job["prompt"]), request=request, **meta)
        h.log_job(root, id=job["id"], status="retried", retried_as=new["id"])
        started.append({**new, "what": job.get("what"), "was": job["id"]})
    return started


def ping(*, request: h.Requester = None, sleep: Optional[Callable[[float], None]] = None,
         wait_s: int = 120, poll_s: int = 5) -> str:
    """One tiny job to see whether she answers: "ready", "out of credit" or "no answer". Nothing is logged or kept."""
    sleep = sleep or h.time.sleep
    job = h.start_job("Harriet, noirstudio: a one-word test. Reply with the single word: ready. Nothing else, no tools.",
                      request=request)
    waited = 0
    while waited < wait_s:
        sleep(poll_s)
        waited += poll_s
        try:
            reply = h.poll_job(job, request=request)
        except LLMError as exc:
            return f"failed: {str(exc)[:200]}"
        if reply is not None:
            return "out of credit" if h.out_of_credit(reply) else "ready"
    return "no answer"


def wait_for(root: Path, job_id: str, *, request: h.Requester = None, sleep: Optional[Callable[[float], None]] = None,
             wait_s: int = h.JOB_WAIT, poll_s: int = h.POLL_EVERY, log: Callable[[str], None] = lambda _m: None) -> dict:
    """Collect until this job is done (collected or failed), or the wait runs out; returns its last state."""
    sleep = sleep or h.time.sleep
    waited = 0
    while waited <= wait_s:
        sleep(poll_s)
        waited += poll_s
        for job in collect(root, request=request):
            if job["id"] == job_id:
                return job
        log(f"[harriet] still digging ({waited}s)")
    return {"id": job_id, "status": "running"}


def all_moments(root: Path) -> List[dict]:
    """Every moment she has brought back, latest version of each id last-wins, oldest first."""
    found: Dict[str, dict] = {}
    digs = []
    for path in (root / "digs").glob("*.json") if (root / "digs").exists() else []:
        data = json.loads(path.read_text(encoding="utf-8"))
        digs.append((str(data.get("job", {}).get("started_at", "")), path.name, data))
    for _started, name, data in sorted(digs):
        for m in data.get("dig", {}).get("moments") or []:
            mid = str(m.get("id") or f"{name}#{len(found)}")
            found.pop(mid, None)
            found[mid] = {**m, "_dig": name}
    return list(found.values())


def find_moment(root: Path, moment_id: str) -> Optional[dict]:
    return next((m for m in reversed(all_moments(root)) if str(m.get("id")) == moment_id), None)


def known_lines(root: Path, limit: int = 60) -> List[str]:
    """One line per moment already found, to steer the next dive elsewhere."""
    return [f"{m.get('id')} ({m.get('when', '?')}): {' '.join(str(m.get('what_happened', '')).split())[:100]}"
            for m in all_moments(root)][-limit:]
