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
    noirstudio llm ping [--env-file ~/.hermes/.env]           check OpenRouter / DeepSeek access
    noirstudio draft agent-log --entry 2 --activity ... --brief ...   LLM-draft the next entry (rules enforced)
    noirstudio draft short my-slug --topic "..." | draft titles "..."
    noirstudio loop agent-log [--push --pr]      the whole daily loop in one command (what CI runs)
    noirstudio harriet pitch [-n 3] | inbox       Harriet pitches diary stories from her memory (private inbox)
    noirstudio cut specs/diary/<ep>.cuts.yaml --master EP.mp4   platform versions of a finished episode
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


def _llm_client(args: argparse.Namespace):
    from .llm import LLMError, resolve_client

    try:
        return resolve_client(args.provider, args.model, env_file=args.env_file, config_path=args.llm_config)
    except LLMError as exc:
        print(f"LLM: {exc}", file=sys.stderr)
        return None


def _add_llm_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", choices=["openrouter", "deepseek", "openai-compatible"], help="default: first with a key")
    p.add_argument("--model", help="e.g. deepseek/deepseek-chat-v3.1 (OpenRouter) or deepseek-chat")
    p.add_argument("--env-file", help="dotenv file holding OPENROUTER_API_KEY / DEEPSEEK_API_KEY (e.g. ~/.hermes/.env)")
    p.add_argument("--llm-config", help="YAML with provider/model/base_url (default ~/.config/noirstudio/llm.yaml)")


def _cmd_llm(args: argparse.Namespace) -> int:
    from .llm import LLMError

    client = _llm_client(args)
    if client is None:
        return 1
    if args.llm_cmd == "ping":
        try:
            reply = client.ping()
        except LLMError as exc:
            print(f"{client.provider} {client.model}: FAILED — {exc}", file=sys.stderr)
            return 2
        u = client.usage
        print(f"{client.provider} {client.model}: {reply!r} in {u.seconds:.2f}s "
              f"({u.prompt_tokens} prompt / {u.completion_tokens} completion tokens)")
        return 0
    print(f"provider={client.provider} model={client.model} base_url={client.base_url}")
    return 0


def _cmd_draft(args: argparse.Namespace) -> int:
    from . import draft as d
    from .llm import LLMError

    client = _llm_client(args)
    if client is None:
        return 1
    try:
        if args.draft_cmd == "agent-log":
            entry = f"{int(args.entry):03d}"
            out = Path(args.out or f"specs/agent-log-{entry}.yaml")
            prev = Path(args.previous) if args.previous else Path(f"specs/agent-log-{int(entry) - 1:03d}.yaml")
            res = d.draft_agent_log(
                client, entry=entry, activity_path=Path(args.activity),
                brief_path=Path(args.brief) if args.brief else None,
                headlines_path=Path(args.headlines) if args.headlines else None,
                previous_spec=prev if prev.exists() else None, out_path=out, notes=args.notes or "",
            )
        elif args.draft_cmd == "short":
            brief = Path(args.brief).read_text(encoding="utf-8") if args.brief else args.topic
            out = Path(args.out or f"specs/{args.slug}.yaml")
            res = d.draft_short(client, brief=brief, brand=args.brand, niche=args.niche, slug=args.slug, out_path=out)
        else:  # titles
            for t in d.draft_titles(client, topic=args.topic, n=args.n):
                print(f"[{t['pattern']:<22}] {t['title']}\n{'':<25}{t['why']}")
            return 0
    except (d.DraftError, LLMError, FileNotFoundError) as exc:
        print(f"DRAFT FAILED: {exc}", file=sys.stderr)
        return 2
    words = len(res.spec.narration.split())
    u = client.usage
    print(f"wrote {res.path} — {len(res.spec.scenes)} scenes, {words} words, attempt {res.attempts}, "
          f"{u.prompt_tokens}+{u.completion_tokens} tokens via {client.provider}/{client.model}")
    print("Review it, then: noirstudio render", res.path)
    return 0


def _cmd_loop(args: argparse.Namespace) -> int:
    from .loop import run_agent_log

    yt = None if args.youtube == "auto" else (args.youtube == "on")
    try:
        res = run_agent_log(Path(args.repo), draft=args.draft, push=args.push, pr=args.pr, notes=args.notes,
                            use_youtube=yt, log=lambda m: print(m, file=sys.stderr))
    except Exception as exc:
        if args.debug:
            raise
        print(f"LOOP FAILED: {exc}", file=sys.stderr)
        return 2
    print(res.to_json())
    # a requested push/PR that failed must fail the run, so CI shows red instead of a quiet green
    if any(res.steps.get(step) == "failed" for step in ("push", "pr", "render")):
        print("LOOP INCOMPLETE: " + "; ".join(res.errors), file=sys.stderr)
        return 3
    return 0


def _cmd_harriet(args: argparse.Namespace) -> int:
    from . import harriet as h
    from .llm import LLMError

    root = Path(args.dir)
    if args.harriet_cmd == "inbox":
        files = sorted(p for p in root.glob("*.md") if p.name != "README.md") if root.exists() else []
        for p in files:
            s = h.read_status(p)
            print(f"{str(s.get('status', '?')):<9} {str(s.get('sensitivity', '?')):<7} {p.name} — {s.get('title', '')}")
        print(f"{len(files)} pitch(es) in {root}" if files else f"no pitches in {root}")
        return 0
    try:
        kept, dropped = h.mine_pitches(n=args.n, theme=args.theme, since=args.since,
                                       avoid=h.told_titles(root) if root.exists() else [])
    except LLMError as exc:
        print(f"HARRIET: {exc}", file=sys.stderr)
        return 2
    for reason in dropped:
        print(f"dropped {reason}", file=sys.stderr)
    if args.json:
        print(h.dump_json(kept))
    else:
        for path in h.write_inbox(kept, root):
            print(f"wrote {path}")
        if kept:
            print("Read them; set `status: approved` on the ones worth telling. They stay out of git.")
    return 0 if kept else 2


def _cmd_cut(args: argparse.Namespace) -> int:
    from .cut import CutError, load_plan, plan_problems, probe, run_plan, seam_warnings, silences
    from .ffmpeg import FFmpegError

    try:
        plan = load_plan(Path(args.plan))
    except (CutError, FileNotFoundError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    candidates = [Path(args.master)] if args.master else (
        [Path(plan.master), plan.source.parent / plan.master] if plan.master else [])
    master = next((c for c in candidates if c.exists()), None)
    if master is None:
        print(f"master not found ({', '.join(map(str, candidates)) or 'none named'}); pass --master PATH", file=sys.stderr)
        return 1
    try:
        if args.check:
            info = probe(master)
            problems = plan_problems(plan, info["duration"])
            pauses = silences(master, plan.pause_db, plan.min_pause_s)
            for line in problems + seam_warnings(plan, pauses, info["duration"]):
                print(line)
            for o in plan.outputs:
                print(f"{o.name:<14} {o.duration:7.2f}s  cap {o.cap_s or '-'}  {len(o.segments)} segment(s)")
            return 1 if problems else 0
        report = run_plan(plan, master, Path(args.out or f"renders/{plan.id}"), only=args.only,
                          log=lambda m: print(m, file=sys.stderr))
    except (CutError, FFmpegError) as exc:
        print(f"CUT FAILED: {exc}", file=sys.stderr)
        return 2
    for w in report["seam_warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    for o in report["outputs"]:
        loud = o["loudness"]
        print(f"{o['name']:<14} {o['duration_s']:7.2f}s  {loud['lufs']:+.1f} LUFS  {loud['true_peak_db']:+.1f} dBTP  {o['path']}")
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

    llm = sub.add_parser("llm", help="LLM provider setup check (OpenRouter / DeepSeek / OpenAI-compatible)")
    llm.add_argument("llm_cmd", choices=["ping", "show"])
    _add_llm_flags(llm)
    llm.set_defaults(fn=_cmd_llm)

    dr = sub.add_parser("draft", help="LLM drafting with rule enforcement: agent-log | short | titles")
    dsub = dr.add_subparsers(dest="draft_cmd", required=True)
    al = dsub.add_parser("agent-log", help="draft the next Agent Log entry from evidence files")
    al.add_argument("--entry", required=True, help="entry number, e.g. 2")
    al.add_argument("--activity", required=True, help="specs/evidence/<date>-activity.json")
    al.add_argument("--brief", help="radar/briefs/<date>.md")
    al.add_argument("--headlines", help="specs/evidence/<date>-<slug>.json (verbatim headlines)")
    al.add_argument("--previous", help="previous entry spec (default: entry-1 in specs/)")
    al.add_argument("--notes", help="operator notes for this entry")
    al.add_argument("--out")
    _add_llm_flags(al)
    al.set_defaults(fn=_cmd_draft)
    sh = dsub.add_parser("short", help="draft a Short spec from a topic or brief file")
    sh.add_argument("slug", help="spec id, e.g. opus-55-briefing")
    sh.add_argument("--topic", default="", help="one-paragraph brief (or use --brief FILE)")
    sh.add_argument("--brief", help="brief file (markdown/text)")
    sh.add_argument("--brand", default="noirsys", choices=sorted(BRANDS))
    sh.add_argument("--niche", default="ai-agents")
    sh.add_argument("--out")
    _add_llm_flags(sh)
    sh.set_defaults(fn=_cmd_draft)
    ti = dsub.add_parser("titles", help="10 title candidates with the hook pattern each uses")
    ti.add_argument("topic")
    ti.add_argument("-n", type=int, default=10)
    _add_llm_flags(ti)
    ti.set_defaults(fn=_cmd_draft)

    lp = sub.add_parser("loop", help="run a whole content loop end to end (radar -> evidence -> draft -> render -> PR)")
    lp.add_argument("loop_cmd", choices=["agent-log"])
    lp.add_argument("--repo", default=".")
    lp.add_argument("--draft", choices=["auto", "skip"], default="auto", help="auto = LLM if a key exists")
    lp.add_argument("--push", action="store_true", help="push the entry branch")
    lp.add_argument("--pr", action="store_true", help="open the PR (needs --push; gh or GH_TOKEN)")
    lp.add_argument("--notes", default="", help="operator notes passed to the drafter")
    lp.add_argument("--youtube", choices=["auto", "on", "off"], default="auto")
    lp.add_argument("--debug", action="store_true")
    lp.set_defaults(fn=_cmd_loop)

    hr = sub.add_parser("harriet", help="ask Harriet for diary stories from her memory (HARRIET_STORIES_URL)")
    hr.add_argument("harriet_cmd", choices=["pitch", "inbox"])
    hr.add_argument("-n", type=int, default=3, help="how many stories she curates (default 3)")
    hr.add_argument("--theme", default="", help="optional focus, e.g. 'the week the voice came online'")
    hr.add_argument("--since", default="", help="only moments from this date on")
    hr.add_argument("--dir", default="stories/inbox", help="where pitches are kept (git-ignored: his private life)")
    hr.add_argument("--json", action="store_true", help="print the pitches as JSON instead of writing files")
    hr.set_defaults(fn=_cmd_harriet)

    ct = sub.add_parser("cut", help="cut a finished master into platform versions from a cut plan (YAML)")
    ct.add_argument("plan", help="e.g. specs/diary/2026-09-27.cuts.yaml")
    ct.add_argument("--master", help="the master video (default: the plan's `master`)")
    ct.add_argument("--out", help="output directory (default renders/<plan id>)")
    ct.add_argument("--only", action="append", default=[], help="render just this output (repeatable)")
    ct.add_argument("--check", action="store_true", help="validate the plan and its seams; render nothing")
    ct.set_defaults(fn=_cmd_cut)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
