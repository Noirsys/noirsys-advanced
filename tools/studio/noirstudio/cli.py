"""noirstudio command line.

    noirstudio new my-video [--brand noirpost]   write a starter spec
    noirstudio validate my-video.yaml            check a spec
    noirstudio render my-video.yaml [--out DIR]  offline preview (no keys)
    noirstudio render my-video.yaml --live       real cloned voice (ELEVENLABS_API_KEY)
    noirstudio render ... --live --video         + avatar/b-roll via Flows video API
    noirstudio voices                            list ElevenLabs voices (live)
    noirstudio fonts                             show bundled fonts as libass sees them
    noirstudio radar init | run [--no-youtube]   daily brief: what's working (YouTube API + HN)
    noirstudio activity --repo . --since 1.day   commits + renders as JSON (agent diary material)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .brandkit import BRANDS, FONTS_DIR, font_family_name
from .spec import SpecError, load_spec, starter_spec


def _cmd_new(args: argparse.Namespace) -> int:
    path = Path(f"{args.name}.yaml")
    if path.exists() and not args.force:
        print(f"{path} exists (use --force to overwrite)", file=sys.stderr)
        return 1
    path.write_text(starter_spec(args.name, args.brand), encoding="utf-8")
    print(f"wrote {path}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        spec = load_spec(args.spec)
    except (SpecError, FileNotFoundError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    words = len(spec.narration.split())
    est = words / spec.voice.words_per_minute * 60
    print(f"OK: {spec.id} — {len(spec.scenes)} scenes, {words} words, ~{est:.0f}s narration, brand={spec.brand}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    from .pipeline import render

    try:
        spec = load_spec(args.spec)
    except (SpecError, FileNotFoundError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else Path("renders") / spec.id
    try:
        result = render(spec, out, live=args.live, generate_video=args.video, keep_work=not args.clean)
    except Exception as exc:  # surface a clean one-liner; full trace with --debug
        if args.debug:
            raise
        print(f"RENDER FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"\nvideo      {result.video}\nthumbnail  {result.thumbnail}\ncaptions   {result.captions_srt}"
          f"\nmetadata   {result.metadata_md}\nreport     {result.report}")
    return 0


def _cmd_voices(_args: argparse.Namespace) -> int:
    from .voice import ElevenLabsVoice, VoiceError

    try:
        for v in ElevenLabsVoice().list_voices():
            print(f"{v['voice_id']}  {v['category'] or '':<12} {v['name']}")
    except VoiceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _cmd_radar(args: argparse.Namespace) -> int:
    from . import radar

    cfg = Path(args.config)
    if args.radar_cmd == "init":
        if cfg.exists() and not args.force:
            print(f"{cfg} exists (use --force to overwrite)", file=sys.stderr)
            return 1
        cfg.write_text(radar.DEFAULT_CONFIG, encoding="utf-8")
        print(f"wrote {cfg}")
        return 0
    if not cfg.exists():
        print(f"no config at {cfg}; run `noirstudio radar init` first", file=sys.stderr)
        return 1
    try:
        path = radar.run(cfg, Path(args.out), use_youtube=not args.no_youtube, use_hn=not args.no_hn)
    except radar.RadarError as exc:
        print(f"RADAR FAILED: {exc}", file=sys.stderr)
        return 2
    print(path.read_text(encoding="utf-8") if args.print else f"brief: {path}")
    return 0


def _cmd_activity(args: argparse.Namespace) -> int:
    import json

    from .activity import collect

    record = collect([Path(r) for r in args.repo], since=args.since, render_roots=[Path(r) for r in args.renders])
    print(json.dumps(record, indent=2))
    return 0


def _cmd_fonts(_args: argparse.Namespace) -> int:
    for p in sorted(FONTS_DIR.glob("*.ttf")):
        print(f"{p.name:<36} family='{font_family_name(p)}'")
    print(f"\nbrands: {', '.join(sorted(BRANDS))}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="noirstudio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"noirstudio {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="write a starter spec")
    n.add_argument("name")
    n.add_argument("--brand", default="noirsys", choices=sorted(BRANDS))
    n.add_argument("--force", action="store_true")
    n.set_defaults(fn=_cmd_new)

    v = sub.add_parser("validate", help="validate a spec")
    v.add_argument("spec")
    v.set_defaults(fn=_cmd_validate)

    r = sub.add_parser("render", help="render a spec to MP4 (+captions, thumbnail, metadata)")
    r.add_argument("spec")
    r.add_argument("--out", help="output directory (default renders/<id>)")
    r.add_argument("--live", action="store_true", help="use ElevenLabs cloned voice (needs ELEVENLABS_API_KEY)")
    r.add_argument("--video", action="store_true", help="with --live: generate avatar/b-roll scenes via Flows")
    r.add_argument("--clean", action="store_true", help="delete the work/ directory after rendering")
    r.add_argument("--debug", action="store_true")
    r.set_defaults(fn=_cmd_render)

    sub.add_parser("voices", help="list ElevenLabs voices").set_defaults(fn=_cmd_voices)
    sub.add_parser("fonts", help="show bundled fonts").set_defaults(fn=_cmd_fonts)

    rd = sub.add_parser("radar", help="daily bird's-eye view: YouTube Data API + Hacker News -> markdown brief")
    rd.add_argument("radar_cmd", choices=["init", "run"])
    rd.add_argument("--config", default="radar.yaml")
    rd.add_argument("--out", default="radar", help="directory for snapshots/ and briefs/")
    rd.add_argument("--no-youtube", action="store_true", help="skip YouTube (no key needed)")
    rd.add_argument("--no-hn", action="store_true")
    rd.add_argument("--print", action="store_true", help="print the brief to stdout")
    rd.add_argument("--force", action="store_true")
    rd.set_defaults(fn=_cmd_radar)

    ac = sub.add_parser("activity", help="what happened: commits + renders as JSON (diary raw material)")
    ac.add_argument("--repo", action="append", default=[], help="git repo path (repeatable)")
    ac.add_argument("--renders", action="append", default=[], help="directory to scan for *.report.json (repeatable)")
    ac.add_argument("--since", default="1.day")
    ac.set_defaults(fn=_cmd_activity)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
