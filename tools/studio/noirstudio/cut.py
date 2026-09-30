"""Cut a finished master into platform versions (e.g. a diary episode Harriet made).

A cut plan (YAML, content-as-code) names each output, its length cap, and the
[start, end] seconds of the master it keeps, in order:

    id: diary-2026-09-27
    master: the-diary-of-harriet-2026-09-27.mp4    # not in git; --master overrides
    outputs:
      - name: short
        cap_s: 59
        segments:
          - [35.05, 38.40]   # "...is the same stuff that shows your hand."
          - [58.20, 61.35]   # his voice note: "Was that pun intended or not intended?"

Each output is rendered frame-accurately (every segment gets its own seek, then
the pieces are concatenated), with a short audio fade at every seam and
loudness normalized in two passes (-14 LUFS integrated, -1 dBTP by default).
A plan over its cap fails before anything renders, and a seam that falls
mid-speech rather than in a pause is flagged, because that is the cut you hear.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import yaml

from . import ffmpeg


class CutError(ValueError):
    pass


@dataclass
class CutOutput:
    name: str
    segments: List[Tuple[float, float]]
    cap_s: Optional[float] = None
    lufs: float = -14.0
    true_peak: float = -1.0

    @property
    def duration(self) -> float:
        return sum(end - start for start, end in self.segments)


@dataclass
class CutPlan:
    id: str
    outputs: List[CutOutput]
    master: Optional[str] = None
    source: Optional[Path] = None
    fade_s: float = 0.02
    pause_db: float = -30.0  # voice notes carry room tone; -30 dB still finds their pauses, not their words
    min_pause_s: float = 0.15
    notes: str = ""


_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_plan(path: Path) -> CutPlan:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data.get("id") or not isinstance(data.get("outputs"), list):
        raise CutError(f"{path}: a cut plan needs `id` and a list of `outputs`")
    outputs = []
    for i, o in enumerate(data["outputs"], 1):
        if not isinstance(o, dict) or not _NAME.match(str(o.get("name", ""))):
            raise CutError(f"{path}: output {i} needs a lowercase `name` (letters, digits, hyphens)")
        segs = o.get("segments")
        if not isinstance(segs, list) or not segs:
            raise CutError(f"{path}: output `{o['name']}` needs `segments: [[start, end], ...]`")
        try:
            pairs = [(float(s[0]), float(s[1])) for s in segs]
        except (TypeError, ValueError, IndexError):
            raise CutError(f"{path}: output `{o['name']}` has a segment that is not [start, end] in seconds") from None
        outputs.append(CutOutput(name=o["name"], segments=pairs, cap_s=o.get("cap_s"),
                                 lufs=float(o.get("lufs", -14.0)), true_peak=float(o.get("true_peak", -1.0))))
    return CutPlan(id=str(data["id"]), outputs=outputs, master=data.get("master"), source=Path(path),
                   fade_s=float(data.get("fade_s", 0.02)), pause_db=float(data.get("pause_db", -30.0)),
                   min_pause_s=float(data.get("min_pause_s", 0.15)), notes=str(data.get("notes", "")))


def plan_problems(plan: CutPlan, master_duration: Optional[float] = None) -> List[str]:
    """Everything that would make a cut wrong, found before rendering."""
    problems = []
    names = [o.name for o in plan.outputs]
    for dup in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"output `{dup}` is defined twice")
    for o in plan.outputs:
        for start, end in o.segments:
            if start < 0 or end <= start:
                problems.append(f"{o.name}: segment [{start}, {end}] is empty or reversed")
            elif master_duration is not None and end > master_duration + 0.05:
                problems.append(f"{o.name}: segment [{start}, {end}] runs past the master's end ({master_duration:.2f}s)")
            elif end - start < 2 * plan.fade_s:
                problems.append(f"{o.name}: segment [{start}, {end}] is shorter than its fades")
        if o.cap_s is not None and o.duration > float(o.cap_s):
            problems.append(f"{o.name}: {o.duration:.2f}s is over its {float(o.cap_s):g}s cap")
    return problems


# --- reading the master -------------------------------------------------------------------

_DURATION = re.compile(r"Duration: (\d+):(\d{2}):(\d{2}\.\d+)")
_SIZE = re.compile(r"Stream #\d+:\d+.*Video: .*?, (\d{2,5})x(\d{2,5})")


def probe(master: Path) -> dict:
    """Duration and frame size from ffmpeg's header read (fast; no decode)."""
    proc = subprocess.run([ffmpeg.ffmpeg_path(), "-hide_banner", "-i", str(master)], capture_output=True, text=True)
    m = _DURATION.search(proc.stderr)
    if not m:
        raise CutError(f"cannot read {master}: {proc.stderr.strip()[-300:]}")
    h, mi, s = m.groups()
    info = {"duration": int(h) * 3600 + int(mi) * 60 + float(s)}
    size = _SIZE.search(proc.stderr)
    if size:
        info["width"], info["height"] = int(size.group(1)), int(size.group(2))
    return info


_SILENCE = re.compile(r"silence_(start|end): (-?[\d.]+)")


def silences(master: Path, noise_db: float = -30.0, min_s: float = 0.15) -> List[Tuple[float, float]]:
    """Pauses in the master's audio: the places a seam can't be heard."""
    err = ffmpeg.run(["-nostats", "-i", str(master), "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"])
    out, start = [], None
    for kind, t in _SILENCE.findall(err):
        if kind == "start":
            start = max(0.0, float(t))
        elif start is not None:
            out.append((start, float(t)))
            start = None
    return out


def seam_warnings(plan: CutPlan, pauses: Sequence[Tuple[float, float]], master_duration: float,
                  tolerance: float = 0.06) -> List[str]:
    """Seams that land mid-speech: every segment boundary should sit inside a pause."""
    def in_pause(t: float) -> bool:
        return t <= tolerance or t >= master_duration - tolerance or any(a - tolerance <= t <= b + tolerance for a, b in pauses)

    warnings = []
    for o in plan.outputs:
        for start, end in o.segments:
            for edge, t in (("in", start), ("out", end)):
                if not in_pause(t):
                    warnings.append(f"{o.name}: {edge}-point {t:.2f}s is not in a pause (mid-speech?)")
    return warnings


# --- rendering ------------------------------------------------------------------------------

_JSON_TAIL = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def _loudnorm_stats(stderr: str) -> dict:
    blocks = _JSON_TAIL.findall(stderr)
    if not blocks:
        raise CutError("loudnorm printed no measurement")
    return json.loads(blocks[-1])


def render_output(master: Path, out: CutOutput, out_dir: Path, *, fade_s: float = 0.02, fps: int = 30,
                  log: Callable[[str], None] = print) -> dict:
    """One platform version: accurate trims -> concat -> two-pass loudness -> MP4."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stage, final = out_dir / f"{out.name}.stage.mov", out_dir / f"{out.name}.mp4"
    inputs, chains, pads = [], [], []
    for i, (start, end) in enumerate(out.segments):
        d = end - start
        inputs += ["-ss", f"{start:.3f}", "-t", f"{d:.3f}", "-i", str(master)]
        chains.append(f"[{i}:v]setpts=PTS-STARTPTS,fps={fps}[v{i}]")
        chains.append(f"[{i}:a]asetpts=PTS-STARTPTS,aresample=48000,afade=t=in:st=0:d={fade_s},"
                      f"afade=t=out:st={max(0.0, d - fade_s):.3f}:d={fade_s}[a{i}]")
        pads.append(f"[v{i}][a{i}]")
    graph = ";".join(chains) + f";{''.join(pads)}concat=n={len(out.segments)}:v=1:a=1[v][a]"
    log(f"[cut] {out.name}: {len(out.segments)} segment(s), {out.duration:.2f}s")
    ffmpeg.run(["-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "pcm_s16le", str(stage)])
    target = f"I={out.lufs}:TP={out.true_peak}:LRA=11"
    measured = _loudnorm_stats(ffmpeg.run(["-nostats", "-i", str(stage), "-vn", "-af",
                                           f"loudnorm={target}:print_format=json", "-f", "null", "-"]))
    second = (f"loudnorm={target}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
              f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
              f"offset={measured['target_offset']}:linear=true:print_format=json")
    result = _loudnorm_stats(ffmpeg.run(["-y", "-i", str(stage), "-c:v", "copy", "-af", second, "-ar", "48000",
                                         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)]))
    stage.unlink(missing_ok=True)
    return {
        "name": out.name, "path": str(final), "duration_s": round(out.duration, 2), "cap_s": out.cap_s,
        "segments": [[round(a, 3), round(b, 3)] for a, b in out.segments], "seams": len(out.segments) - 1,
        "loudness": {"source_lufs": float(measured["input_i"]), "lufs": float(result["output_i"]),
                     "true_peak_db": float(result["output_tp"])},
    }


def run_plan(plan: CutPlan, master: Path, out_dir: Path, only: Sequence[str] = (),
             log: Callable[[str], None] = print) -> dict:
    """Validate, then render every (or the named) output; returns the report written to out_dir."""
    info = probe(master)
    problems = plan_problems(plan, info["duration"])
    if problems:
        raise CutError("cut plan has problems:\n  " + "\n  ".join(problems))
    unknown = [n for n in only if n not in {o.name for o in plan.outputs}]
    if unknown:
        raise CutError(f"no output named {', '.join(unknown)} in the plan")
    report = {"id": plan.id, "master": str(master), "master_duration_s": round(info["duration"], 2),
              "frame": [info.get("width"), info.get("height")],
              "seam_warnings": seam_warnings(plan, silences(master, plan.pause_db, plan.min_pause_s), info["duration"]),
              "outputs": []}
    if info.get("width") and info.get("height") and info["width"] * 16 != info["height"] * 9:
        report["seam_warnings"].insert(0, f"master is {info['width']}x{info['height']}, not 9:16")
    for o in plan.outputs:
        if not only or o.name in only:
            report["outputs"].append(render_output(master, o, out_dir, fade_s=plan.fade_s, log=log))
    (out_dir / f"{plan.id}.cuts.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
