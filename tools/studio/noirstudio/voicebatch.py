"""Many lines of his, one recipe: `voicenote --batch MANIFEST OUTDIR`.

A Diary episode has a handful of lines his clone reads, and a change of recipe means all of them again. The manifest is a JSON
file, `{"lines": [{"id": "e02-1", "say": "the line as the script has it"}, ...]}` (kept out of git when the lines are his), and
every `voicenote` option given on the command line applies to every line. Each line becomes `OUTDIR/<id><suffix>.ogg` with the
files a build always writes beside it (`.words.json`, `.unswung.wav` and the rest) and its own `.out` and `.rc`. It is
resumable (a line whose note and words.json are there is skipped, `--force` builds it again) and it stops when the account
refuses a read: the lines built by then keep theirs. `--report` builds nothing and prints what is in OUTDIR.
"""
import contextlib
import copy
import io
import json
import re
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# what ElevenLabs says when the account, not the line, is the trouble: a failed payment, no credit left, a bad or revoked key,
# too many calls at once. Every further line would fail the same way, so the batch stops.
ACCOUNT_REFUSED = re.compile(r"HTTP (?:401|402|403|429)\b|payment_required|payment_issue|quota_exceeded|invalid_api_key", re.I)


class BatchError(ValueError):
    """The manifest cannot be used."""


def load_manifest(path: Path) -> List[dict]:
    """The lines of a manifest, checked: each has a unique file-safe `id` and a `say`."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BatchError(f"cannot read the manifest {path}: {exc}") from None
    lines = data.get("lines") if isinstance(data, dict) else data
    if not isinstance(lines, list) or not lines:
        raise BatchError(f'{path} needs {{"lines": [{{"id": "...", "say": "..."}}, ...]}}')
    seen, out = set(), []
    for n, row in enumerate(lines, 1):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not isinstance(row.get("say"), str) \
                or not row["say"].strip():
            raise BatchError(f'line {n} of {path}: it needs an "id" and a "say" (both text, the line not empty)')
        if not _ID.match(row["id"]):
            raise BatchError(f'line {n}: the id {row["id"]!r} must be letters, digits, dots, dashes and underscores '
                             "(it is the file name)")
        if row["id"] in seen:
            raise BatchError(f'the id {row["id"]!r} is in the manifest twice')
        seen.add(row["id"])
        out.append({"id": row["id"], "say": row["say"]})
    return out


def _stem(out_dir: Path, row_id: str, suffix: str) -> Path:
    return out_dir / (row_id + suffix)


def _file(stem: Path, ext: str) -> Path:
    """A file of one line (`.ogg`, `.words.json`, `.rc`, `.out`). Not `with_suffix`: an id may have a dot in it (e02.1)."""
    return stem.with_name(stem.name + ext)


def _done(stem: Path) -> bool:
    return _file(stem, ".ogg").exists() and _file(stem, ".words.json").exists()


def summarize(stem: Path) -> Optional[dict]:
    """What one built line came to, from its words.json (and its note): the pauses asked for, the ones that went in and the ones
    left out, in numbers. None when the line is not built."""
    if not _done(stem):
        return None
    meta = json.loads(_file(stem, ".words.json").read_text(encoding="utf-8"))
    fill = meta.get("fill") or {}
    kept, dropped = fill.get("kept", []), fill.get("dropped", [])
    try:
        from . import ffmpeg

        seconds = ffmpeg.probe_duration(_file(stem, ".ogg"))
    except Exception:  # noqa: BLE001 - a table with a blank is better than none
        seconds = None
    return {"id": stem.name, "seconds": seconds, "words": len(meta.get("words", [])), "asked": len(kept) + len(dropped),
            "kept": len(kept), "dropped": len(dropped), "kept_s": round(sum(d["s"] for d in kept), 2),
            "per_min": round(60 * len(kept) / seconds, 1) if seconds else None,
            "longest_s": max((d["s"] for d in kept), default=0.0), "speech_dbfs": fill.get("speech_dbfs"),
            "moved": [(d["asked_after_words"], d["after_words"]) for d in kept if "asked_after_words" in d],
            "left_out": [(d["after_words"], d["s"], d.get("cut_dbfs")) for d in dropped]}


def _seam_cells(note: Path) -> dict:
    try:
        from .voiceprint import seams

        found = seams(note)
    except Exception:  # noqa: BLE001 - no numpy, or a clip too short to have a pause
        return {}
    rows = [r["dips_per_s"] for r in found.get("rows", []) if "dips_per_s" in r]
    return {"dips_per_s": found.get("dips_per_s"), "dips_max": max(rows, default=None),
            "floor_step_db": found.get("floor_step_db"), "short_gap_floor_db": found.get("short_gap_floor_db")}


def report(rows: Sequence[dict], out_dir: Path, suffix: str = "", write=print) -> None:
    """A table of the lines in OUTDIR, and a line for each pause that was left out or moved."""
    head = ("id", "rc", "s", "words", "asked", "kept", "dropped", "kept_s", "per_min", "longest", "dips/s", "dips_max",
            "floor_step", "short_gap")
    write("  ".join(f"{h:>9}" for h in head))
    notes, built, asked, kept = [], 0, 0, 0
    for row in rows:
        stem = _stem(out_dir, row["id"], suffix)
        rc_file = _file(stem, ".rc")
        rc = rc_file.read_text(encoding="utf-8").strip() if rc_file.exists() else "-"
        got = summarize(stem)
        if got is None:
            write(f"{stem.name:>9}  {rc:>9}  not built")
            continue
        built, asked, kept = built + 1, asked + got["asked"], kept + got["kept"]
        seam = _seam_cells(_file(stem, ".ogg"))
        cells = (stem.name, rc, None if got["seconds"] is None else f"{got['seconds']:.1f}", got["words"], got["asked"], got["kept"],
                 got["dropped"], f"{got['kept_s']:.2f}", got["per_min"], f"{got['longest_s']:.2f}", seam.get("dips_per_s"),
                 seam.get("dips_max"), seam.get("floor_step_db"), seam.get("short_gap_floor_db"))
        write("  ".join(f"{'-' if c is None else str(c):>9}" for c in cells))
        for after, seconds, level in got["left_out"]:
            here = "" if level is None else f" ({level} dBFS there, the speech {got['speech_dbfs']})"
            notes.append(f"{stem.name}: the pause after word {after} ({seconds:g} s) was left out, the clone left no gap{here}")
        for asked_after, went_after in got["moved"]:
            notes.append(f"{stem.name}: the pause asked for after word {asked_after} went in after word {went_after}")
    write("")
    write(f"{built} of {len(rows)} lines built; {kept} of {asked} pauses asked for went in")
    for note in notes:
        write("  " + note)


def run_batch(args, build_one: Callable, write=print) -> int:
    """Build every line of `args.batch` into `args.paths[0]`, each by `build_one` (the `voicenote --say` command) with a copy of
    `args` that has that line's `say` and note. Returns 0 when every line is built or was, 2 when one failed or the account
    refused a read, 1 for a manifest or a call that cannot be used."""
    try:
        rows = load_manifest(Path(args.batch))
    except BatchError as exc:
        write(f"VOICENOTE BATCH: {exc}")
        return 1
    out_dir, suffix = Path(args.paths[0]), args.suffix or ""
    only = {s for s in (args.only or "").split(",") if s}
    unknown = only - {r["id"] for r in rows}
    if unknown:
        write(f"VOICENOTE BATCH: not in the manifest: {', '.join(sorted(unknown))}")
        return 1
    rows = [r for r in rows if not only or r["id"] in only]
    if args.report:
        report(rows, out_dir, suffix, write)
        return 0
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        write(f"VOICENOTE BATCH: cannot use {out_dir} for the notes: {exc}")
        return 1
    built, skipped, failed = 0, 0, []
    for row in rows:
        stem = _stem(out_dir, row["id"], suffix)
        if _done(stem) and not args.force:
            skipped += 1
            write(f"{stem.name}: already built, skipped")
            continue
        one = copy.copy(args)
        one.batch, one.say, one.paths = None, row["say"], [str(_file(stem, ".ogg"))]
        one.only, one.suffix, one.force, one.report = None, "", False, False  # options of the batch, not of a line
        out, err, began = io.StringIO(), io.StringIO(), time.time()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = build_one(one)
        except Exception as exc:  # noqa: BLE001 - one bad line must not end the batch
            code = 2
            err.write(f"{type(exc).__name__}: {exc}\n")
        _file(stem, ".out").write_text(f"{out.getvalue()}\n--- stderr\n{err.getvalue()}", encoding="utf-8")
        _file(stem, ".rc").write_text(str(code), encoding="utf-8")
        got = summarize(stem) if code == 0 else None
        if code == 0 and got:
            built += 1
            write(f"{stem.name}: built in {time.time() - began:.0f} s"
                  + (f", {got['seconds']:.1f} s long" if got["seconds"] else "")
                  + f", {got['kept']} of {got['asked']} pauses in")
            continue
        failed.append(stem.name)
        tail = [ln for ln in (err.getvalue() + out.getvalue()).strip().splitlines() if ln.strip()][-3:]
        write(f"{stem.name}: FAILED (exit {code}): " + " | ".join(tail))
        if ACCOUNT_REFUSED.search(err.getvalue() + out.getvalue()):
            write(f"STOPPED: the account refused a read. {built} built so far keep their reads ({stem.parent.name}/*.unswung.wav "
                  "and *.words.json); run the same command again when it answers, and the built ones are skipped.")
            return 2
    write(f"{built} built, {skipped} skipped (already there), {len(failed)} failed" + (f": {', '.join(failed)}" if failed else ""))
    return 2 if failed else 0
