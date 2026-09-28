"""Collect what the agent actually did: commits and renders, as structured JSON.

This is the raw material for an agent-perspective diary. Nothing is invented:
a Short about "today" is drafted from this record, and the record is kept
next to the spec so the claim can be checked.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed in {repo}")
    return proc.stdout


def commits(repo: Path, since: str = "1.day", limit: int = 50) -> List[Dict]:
    fmt = "%H%x1f%aI%x1f%an%x1f%s"
    out = _git(repo, "log", f"--since={since}", f"--max-count={limit}", f"--format={fmt}", "--shortstat")
    entries: List[Dict] = []
    current: Optional[Dict] = None
    for line in out.splitlines():
        if "\x1f" in line:
            sha, date, author, subject = line.split("\x1f", 3)
            current = {"sha": sha[:10], "date": date, "author": author, "subject": subject,
                       "files": 0, "insertions": 0, "deletions": 0}
            entries.append(current)
        elif current and ("changed" in line):
            for part in line.split(","):
                part = part.strip()
                n = int(part.split()[0]) if part and part.split()[0].isdigit() else 0
                if "file" in part:
                    current["files"] = n
                elif "insertion" in part:
                    current["insertions"] = n
                elif "deletion" in part:
                    current["deletions"] = n
    return entries


def renders(root: Path) -> List[Dict]:
    out: List[Dict] = []
    for report in sorted(root.rglob("*.report.json")):
        try:
            d = json.loads(report.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "spec_id": d.get("spec_id"), "brand": d.get("brand"), "live": d.get("live"),
            "duration_seconds": d.get("duration_seconds"), "words": d.get("words"),
            "scenes": len(d.get("scenes", [])), "generated_at": d.get("generated_at"),
            "fallbacks": [s["id"] for s in d.get("scenes", []) if s.get("fallback")],
        })
    return out


def collect(repos: List[Path], since: str = "1.day", render_roots: Optional[List[Path]] = None) -> Dict:
    record: Dict = {
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "since": since,
        "repos": [],
        "renders": [],
    }
    for repo in repos:
        try:
            cs = commits(repo, since)
        except RuntimeError as exc:
            record["repos"].append({"path": str(repo), "error": str(exc)})
            continue
        record["repos"].append({
            "path": str(repo),
            "commits": cs,
            "totals": {
                "commits": len(cs),
                "files": sum(c["files"] for c in cs),
                "insertions": sum(c["insertions"] for c in cs),
                "deletions": sum(c["deletions"] for c in cs),
            },
        })
    for root in render_roots or []:
        record["renders"].extend(renders(root))
    return record
