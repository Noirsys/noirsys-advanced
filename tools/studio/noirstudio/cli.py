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
    noirstudio harriet dig [--focus ...] [--follow ID] | collect | moments   Harriet goes through her memory (private)
    noirstudio harriet tell --note "..."         a note or request for her; her answer lands in stories/notes/
    noirstudio harriet pitch [--kinds emotional,funny] | inbox   curated pitches from her (private inbox)
    noirstudio cut diary/<ep>.cuts.yaml --master EP.mp4   platform versions of a finished episode
    noirstudio safe-area EP.mp4                  how often text sits under the platforms' buttons/captions
    noirstudio voicenote --say "um, his line [pause 1]" OUT.ogg [--match|--room REAL.ogg]   a lost voice note of his, rebuilt
    noirstudio voiceprint HIS.ogg ... --vs OURS.ogg ...   how close our reads are to his real notes, in numbers
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
    from . import dig as d
    from . import harriet as h
    from .llm import LLMError

    root, cmd = Path(args.root), args.harriet_cmd
    inbox = root / "inbox"
    say = lambda m: print(m, file=sys.stderr)  # noqa: E731
    if cmd == "inbox":
        files = sorted(p for p in inbox.glob("*.md") if p.name != "README.md") if inbox.exists() else []
        for p in files:
            s = h.read_status(p)
            print(f"{str(s.get('status', '?')):<9} {str(s.get('sensitivity', '?')):<7} {p.name} — {s.get('title', '')}")
        print(f"{len(files)} pitch(es) in {inbox}" if files else f"no pitches in {inbox}")
        return 0
    if cmd == "moments":
        moments = d.all_moments(root)
        for m in moments:
            lines = [x for x in m.get("exchange") or [] if isinstance(x, dict)]
            his = sum(1 for x in lines if x.get("speaker") == "michael")
            copied = sum(1 for x in lines if x.get("verbatim") is not False)
            print(f"{str(m.get('id')):<32} {str(m.get('kind', '?')):<12} {str(m.get('when', '?'))[:16]:<16} "
                  f"lines {len(lines):>2} (his {his}, copied {copied}) audio {m.get('his_audio', '?')}")
        print(f"{len(moments)} moment(s) in {root / 'digs'}")
        return 0
    try:
        if cmd == "collect":
            changed = d.collect(root)
            for job in changed:
                print(f"{job['id']} ({job.get('what')}): {job['status']}"
                      + (f" → {', '.join(map(str, job.get('saved') or []))}" if job.get("saved") else "")
                      + (f": {job['error']}" if job.get("error") else ""))
            running = [j for j in h.read_jobs(root) if j.get("status") == "running"]
            for job in running:
                print(f"{job['id']} ({job.get('what')}): still running, started {job.get('started_at')}")
            if not changed and not running:
                print("no open jobs")
            return 0
        if cmd == "tell":
            if not args.note.strip():
                say("tell needs --note \"...\" (a production note or request for her)")
                return 1
            job = d.start(root, "note", args.note.strip(), note=args.note.strip())
            print(f"note job {job['id']} started; collect her answer with: noirstudio harriet collect")
            return 0
        if cmd == "dig":
            if args.follow:
                moment = d.find_moment(root, args.follow)
                if not moment:
                    say(f"no moment `{args.follow}` in {root / 'digs'} (see `noirstudio harriet moments`)")
                    return 1
                prompt, what = d.follow_request(moment, args.focus), "follow"
            else:
                prompt, what = d.dig_request(args.n or d.DIG_N, args.focus, avoid=h.told_titles(inbox),
                                             known=d.known_lines(root)), "dig"
            job = d.start(root, what, prompt, focus=args.focus, follow=args.follow)
            print(f"{what} job {job['id']} started; she has up to 30 min")
            if not args.wait:
                print("collect it with: noirstudio harriet collect")
                return 0
            done = d.wait_for(root, job["id"], log=say)
            if done["status"] == "running":
                print("still digging; collect it later with: noirstudio harriet collect")
                return 0
            for path in done.get("saved") or []:
                print(f"wrote {path}")
            if done.get("error"):
                say(f"HARRIET: {done['error']}")
            return 0 if done["status"] == "collected" else 2
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip()] if args.kinds else list(h.DEFAULT_KINDS)
        started = []

        def logged(job: dict) -> None:
            started.append(job["id"])
            h.log_job(root, id=job["id"], poll_url=job["poll_url"], what="pitch", status="running",
                      started_at=d._now())

        kept, dropped = h.mine_pitches(n=args.n or len(kinds), theme=args.theme, since=args.since, kinds=kinds,
                                       avoid=h.told_titles(inbox), mode="sync" if args.sync else "jobs",
                                       log=say, on_start=logged)
    except LLMError as exc:
        print(f"HARRIET: {exc}", file=sys.stderr)
        return 2
    for reason in dropped:
        say(f"dropped {reason}")
    if args.json:
        print(h.dump_json(kept))
        paths = []
    else:
        paths = h.write_inbox(kept, inbox)
        for path in paths:
            print(f"wrote {path}")
        if kept:
            print("Read them; set `status: approved` on the ones worth telling. They stay out of git.")
    for job_id in started:
        h.log_job(root, id=job_id, status="collected", saved=[str(p) for p in paths])
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


def _cmd_safe_area(args: argparse.Namespace) -> int:
    import json

    from .safearea import audit, verdict

    report = audit(Path(args.video), fps=args.fps)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    x0, y0, x1, y1 = report["content_extents"] or (0, 0, 0, 0)
    print(f"{report['frames']} frames at {args.fps}/s; content spans x {x0}-{x1}, y {y0}-{y1} "
          f"(safe box x 120-888, y 288-1248)")
    for line in verdict(report):
        print(f"warning: {line}")
    return 1 if verdict(report) else 0


def _cmd_voicenote(args: argparse.Namespace) -> int:
    import json
    import shutil
    from dataclasses import replace

    from .captions import Word
    from .ffmpeg import FFmpegError
    from .voice import VoiceError
    from .voicenote import (NoteStyle, VoiceNoteError, hesitations, insert_pauses, matched, measure, prosody, rawify,
                            render, roughen, room_tone, split_pauses)

    if len(args.paths) != (1 if args.say or args.measure else 2):
        print("usage: voicenote IN OUT | voicenote --say TEXT OUT | voicenote --measure REAL", file=sys.stderr)
        return 1
    try:
        if args.measure:
            ref = measure(Path(args.paths[0]))
            print(json.dumps(ref, indent=2) if args.json else
                  f"{ref['path']}: {ref['codec']}, {ref['sample_rate']} Hz {ref['channels']}, {ref['kbps']} kbps, "
                  f"{ref['lufs']:+.1f} LUFS, room tone {ref['noise_db']:+.1f} dBFS")
            return 0
        style = matched(NoteStyle(), measure(Path(args.match))) if args.match else NoteStyle()
        given = {"lufs": args.lufs, "noise_db": args.noise_db, "kbps": args.kbps, "lead_s": args.lead,
                 "tail_s": args.tail, "highpass_hz": args.highpass, "lowpass_hz": args.lowpass, "rough": args.rough}
        style = replace(style, room=not args.no_room, **{k: v for k, v in given.items() if v is not None})
        out, words, swung, flat = Path(args.paths[-1]), None, None, None
        if args.room:
            room = room_tone(Path(args.room), out.with_name(out.stem + ".room.wav"))
            if room:
                style = replace(style, room_tone=room["path"])
            else:
                print(f"note: {args.room} has no room in it (noise-suppressed or no pauses); "
                      "using the synthetic room tone", file=sys.stderr)
        if args.say:
            from .spec import Voice
            from .voice import ElevenLabsVoice

            voice = Voice(voice_id=args.voice, model_id=args.model, stability=args.stability,
                          similarity_boost=args.similarity)
            text = roughen(args.say, style.rough)
            line, pauses = split_pauses(rawify(text) if args.raw else text, trail="," if style.rough else "…")
            said = ElevenLabsVoice().synthesize(line, voice, out.with_name(out.stem + ".clean.wav"))
            src, aligned = said.audio_path, said.words
            if args.swing or args.pitch or args.pace:  # his pitch, swing and pace, on the speech before any pause goes in
                unswung = src.with_name(out.stem + ".unswung.wav")
                shutil.copyfile(src, unswung)
                swung = prosody(unswung, src, args.swing, args.pitch, args.pace or 1.0)
                k = swung["pace_effective"]
                aligned = [Word(w.text, round(w.start * k, 3), round(w.end * k, 3)) for w in said.words]
            shown = None
            if args.raw:  # the clone read a run-on; the script's own words (casing, commas) still go on the captions
                for source in (args.say, text):  # as written, else as roughened
                    tokens = [t for t in split_pauses(source, trail="")[0].split() if any(c.isalnum() for c in t)]
                    if len(tokens) == len(aligned):
                        shown = tokens
                        break
            auto = hesitations(" ".join(shown) if shown else line, aligned, pauses, args.hesitate, style.seed)
            pauses = sorted(pauses + auto)
            timed = insert_pauses(src, aligned, pauses)
            if shown:
                timed = [Word(t, w.start, w.end) for t, w in zip(shown, timed)]
            words = {"said": args.say, "read": line, "voice_id": args.voice, "model_id": args.model,
                     "stability": args.stability, "rough": style.rough, "swing": swung,
                     "timings": said.meta.get("timings"), "lead_s": style.lead_s,
                     "pauses": [{"after_words": k, "s": s, **({"auto": True} if (k, s) in auto else {})}
                                for k, s in pauses],
                     "words": [{"text": w.text, "start": round(w.start + style.lead_s, 3),
                                "end": round(w.end + style.lead_s, 3)} for w in timed]}
        else:
            src = Path(args.paths[0])
            if args.swing or args.pitch or args.pace:
                flat = out.with_name(out.stem + ".swung.wav")
                swung = prosody(src, flat, args.swing, args.pitch, args.pace or 1.0)
                src = flat
        report = render(src, out, style)
        if flat is not None:
            flat.unlink(missing_ok=True)
    except (VoiceNoteError, VoiceError, FFmpegError, FileNotFoundError) as exc:
        print(f"VOICENOTE FAILED: {exc}", file=sys.stderr)
        return 2
    if swung is not None:
        report["swing"] = swung
    if words is not None:
        words_path = out.with_name(out.stem + ".words.json")
        words_path.write_text(json.dumps(words, indent=2, ensure_ascii=False), encoding="utf-8")
        report["words"] = str(words_path)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        st = report["style"]
        print(f"{report['path']}  {report['duration_s']:.2f}s ({report['speech_s']:.2f}s of speech)  "
              f"{report['lufs']:+.1f} LUFS  room tone {st['noise_db']:+.1f} dBFS  opus {st['kbps']} kbps"
              + (f"  words: {report['words']}" if words is not None else ""))
        if swung is not None:
            print(f"prosody: swing {swung['swing_before_st']} -> {swung['swing_after_st']} st"
                  + (f" (target {swung['swing_target_st']:g})" if swung["swing_target_st"] else "")
                  + f", pitch {swung['median_before_hz']} -> {swung['median_after_hz']} Hz"
                  + (f" (target {swung['median_target_hz']:g})" if swung["median_target_hz"] else "")
                  + f", pace x{swung['pace_effective']:g}")
    return 0


def _cmd_voiceprint(args: argparse.Namespace) -> int:
    import json

    from .ffmpeg import FFmpegError
    from .voicenote import VoiceNoteError
    from .voiceprint import compare, summarize, table, timeline, timeline_text, voiceprint

    if args.timeline:
        looked, failed = [], []
        for name in args.paths:
            try:
                looked.append(timeline(Path(name), args.step, args.pitch_reader))
            except (VoiceNoteError, FFmpegError, FileNotFoundError) as exc:
                failed.append(f"{name}: {str(exc).splitlines()[0]}")
        for line in failed:
            print(f"skipped {line}", file=sys.stderr)
        if args.json:
            print(json.dumps({"timelines": looked, "failed": failed}, indent=2))
        else:
            print("\n\n".join(timeline_text(t) for t in looked))
        return 0 if looked else 1

    counts = json.loads(Path(args.words).read_text(encoding="utf-8")) if args.words else {}

    def words_for(path: Path):
        """A word count for one file: from --words (a number, or the transcript), else a .words.json beside it."""
        given = counts.get(path.name, counts.get(str(path), counts.get(path.stem)))
        if isinstance(given, str):
            given = len(given.split())
        side = path.with_name(path.stem + ".words.json")
        if given is None and side.exists():
            listed = json.loads(side.read_text(encoding="utf-8")).get("words")
            given = len(listed) if isinstance(listed, list) else None
        return given

    def read(paths):
        rows, failed = [], []
        for name in paths:
            path = Path(name)
            try:
                rows.append(voiceprint(path, words=words_for(path), levels=not args.fast, reader=args.pitch_reader))
            except (VoiceNoteError, FFmpegError, FileNotFoundError) as exc:
                failed.append(f"{name}: {str(exc).splitlines()[0]}")
        return rows, failed

    his, bad = read(args.paths)
    ours, bad_ours = read(args.vs or [])
    bad += bad_ours
    his_sum = summarize(his, args.min_speech, args.max_speech)
    ours_sum = summarize(ours, args.min_speech, args.max_speech) if ours else None
    rows = compare(his_sum, ours_sum) if ours_sum and ours_sum["n"] and his_sum["n"] else []
    if args.json:
        print(json.dumps({"his": his, "his_summary": his_sum, "ours": ours, "ours_summary": ours_sum,
                          "compare": rows, "failed": bad}, indent=2))
        return 1 if bad and not his else 0
    label = "his" if ours_sum else "these"
    print(f"{label}: {his_sum['n']} files, {his_sum['speech_min']} min of speech"
          + (f" ({his_sum['skipped']} skipped: outside {args.min_speech:g} to {args.max_speech:g} s of speech)"
             if his_sum["skipped"] and args.max_speech else
             f" ({his_sum['skipped']} skipped: under {args.min_speech:g} s of speech)" if his_sum["skipped"] else ""))
    if ours_sum:
        print(f"ours: {ours_sum['n']} files, {ours_sum['speech_min']} min of speech"
              + (f" ({ours_sum['skipped']} skipped)" if ours_sum["skipped"] else ""))
    for line in bad:
        print(f"skipped {line}", file=sys.stderr)
    readers = sorted(set(his_sum["readers"]) | set(ours_sum["readers"] if ours_sum else []))
    if len(readers) > 1:
        print(f"WARNING: the pitch rows were read by different readers ({', '.join(readers)}); they do not compare",
              file=sys.stderr)
    elif readers:
        print(f"pitch read by: {readers[0]}")
    if rows:
        print()
        print(table(rows))
        print("\ntoo performed: ours sits on the polished side of his middle half by more than 20%.  "
              "past him: beyond him the other way.")
    else:
        for key, value in his_sum.items():
            if isinstance(value, dict):
                print(f"  {key:<17}{value['median']:g}  ({value['q1']:g} to {value['q3']:g})")
    for key in ("wpm_speech", "wpm_total"):
        if his_sum.get(key) and ours_sum and ours_sum.get(key):
            print(f"{key}: his {his_sum[key]['median']:g}, ours {ours_sum[key]['median']:g}")
    return 1 if bad and not his else 0


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

    hr = sub.add_parser("harriet", help="Harriet's memory: dig for raw moments, pitch diary stories (Hermes via n8n)")
    hr.add_argument("harriet_cmd", choices=["dig", "collect", "moments", "tell", "pitch", "inbox"],
                    help="dig: she goes through her memory (async job); collect: pick up finished jobs; "
                         "moments: what she has found; tell: send her a note (--note); pitch/inbox: curated pitches")
    hr.add_argument("--note", default="", help="tell: the note or request, sent as-is; her answer lands in stories/notes/")
    hr.add_argument("-n", type=int, default=0, help="dig: how many moments (default 10); pitch: how many stories")
    hr.add_argument("--focus", default="", help="dig: where to look this time, e.g. 'the first month'; "
                                                "with --follow: what to ask about that moment")
    hr.add_argument("--follow", default="", help="dig: a moment id to open all the way up, word for word")
    hr.add_argument("--wait", action="store_true", help="dig: wait for her (up to 30 min) instead of collecting later")
    hr.add_argument("--kinds", default="", help="pitch: comma-separated, one story each: e.g. 'emotional,funny'")
    hr.add_argument("--sync", action="store_true", help="pitch: the ~100 s endpoint instead of an async job")
    hr.add_argument("--theme", default="", help="pitch: optional focus, e.g. 'the week the voice came online'")
    hr.add_argument("--since", default="", help="pitch: only moments from this date on")
    hr.add_argument("--root", default="stories", help="where her material is kept (git-ignored: his private life)")
    hr.add_argument("--json", action="store_true", help="pitch: print the pitches as JSON instead of writing files")
    hr.set_defaults(fn=_cmd_harriet)

    ct = sub.add_parser("cut", help="cut a finished master into platform versions from a cut plan (YAML)")
    ct.add_argument("plan", help="e.g. specs/diary/2026-09-27.cuts.yaml")
    ct.add_argument("--master", help="the master video (default: the plan's `master`)")
    ct.add_argument("--out", help="output directory (default renders/<plan id>)")
    ct.add_argument("--only", action="append", default=[], help="render just this output (repeatable)")
    ct.add_argument("--check", action="store_true", help="validate the plan and its seams; render nothing")
    ct.set_defaults(fn=_cmd_cut)

    sa = sub.add_parser("safe-area", help="how often a vertical video's text sits under Shorts/Reels/TikTok UI")
    sa.add_argument("video")
    sa.add_argument("--fps", type=float, default=1.0, help="frames sampled per second (default 1)")
    sa.add_argument("--json", action="store_true")
    sa.set_defaults(fn=_cmd_safe_area)

    from .voicenote import HIS_VOICE

    vn = sub.add_parser("voicenote", help="a lost voice note of his, rebuilt: his clone's read made to sound like his phone")
    vn.add_argument("paths", nargs="+", metavar="PATH",
                    help="IN OUT (filter a clean read); OUT with --say; REAL with --measure. OUT .ogg is the note itself")
    vn.add_argument("--say", metavar="TEXT", help="his line as the script has it, uh/um and all; [pause 1.2] marks where he "
                    "stops to think (default 0.8 s). His clone reads it (ELEVENLABS_API_KEY)")
    vn.add_argument("--voice", default=HIS_VOICE, help="voice id for --say (default: his clone)")
    vn.add_argument("--model", default="eleven_v4")
    vn.add_argument("--stability", type=float, default=0.85,
                    help="the clone's steadiness: higher is flatter and less performed (default 0.85; 0.5 is the v3 read)")
    vn.add_argument("--similarity", type=float, default=0.8)
    vn.add_argument("--match", metavar="REAL", help="one of his real notes: match its loudness, room tone and bitrate")
    vn.add_argument("--room", metavar="REAL", help="one of his real notes: loop its quiet stretches (his room) under the note")
    vn.add_argument("--measure", action="store_true", help="read PATH (a real note) and print what --match would use")
    vn.add_argument("--rough", type=int, choices=[0, 1, 2, 3], default=2,
                    help="how lazy he sounds, in the text and the filter: 0 = the clean phone note (v3), 1-3 = quieter, "
                    "less crisp, flatter (default 2)")
    vn.add_argument("--raw", action="store_true",
                    help="write the line the way his transcripts read: lowercase, no punctuation, run together (a clone "
                    "performs punctuation: it falls at a full stop and lifts at a question)")
    vn.add_argument("--hesitate", type=float, default=0.0, metavar="X",
                    help="add the thinking pauses he makes on his own, at his measured rate (17 a minute, median 0.85 s): "
                    "0 = none (default), 1 = his rate, 2 = twice as often. [pause N] markers in the line count toward it")
    vn.add_argument("--swing", type=float, metavar="ST",
                    help="flatten the read's pitch to at most this swing, in semitones (standard deviation; needs "
                    "praat-parselmouth). `voiceprint` measures his (strategy/04 has the number): a clone swings further than he does at home")
    vn.add_argument("--pitch", type=float, metavar="HZ",
                    help="move the read's median pitch here (needs praat-parselmouth). The clone sat well above his "
                    "real recordings of the same lines (strategy/04 has the numbers)")
    vn.add_argument("--pace", type=float, metavar="X",
                    help="slow (or quicken) the speech, pitch kept (needs praat-parselmouth): 1.2 is 20%% slower. "
                    "The clone spoke about a quarter faster than he does")
    vn.add_argument("--lufs", type=float, help="loudness (default -22: he talks quietly)")
    vn.add_argument("--noise-db", type=float, help="room tone, dBFS (default -54)")
    vn.add_argument("--kbps", type=int, help="Opus bitrate (default 24)")
    vn.add_argument("--lead", type=float, help="room tone before the first word, s (default 0.35)")
    vn.add_argument("--tail", type=float, help="room tone after the last word, s (default 0.5)")
    vn.add_argument("--highpass", type=float, help="Hz (default 100)")
    vn.add_argument("--lowpass", type=float, help="Hz (default 8000)")
    vn.add_argument("--no-room", action="store_true", help="no small-room reflections")
    vn.add_argument("--json", action="store_true")
    vn.set_defaults(fn=_cmd_voicenote)

    vp = sub.add_parser("voiceprint", help="how close reads are to his real notes: pitch swing, pauses, crispness (needs numpy)")
    vp.add_argument("paths", nargs="+", metavar="HIS", help="his real notes (or any set of audio to measure)")
    vp.add_argument("--vs", nargs="+", metavar="OURS", help="our reads, to set next to his")
    vp.add_argument("--words", metavar="MAP.json",
                    help="file name -> word count (or the transcript), for words per minute; a .words.json beside a read counts too")
    vp.add_argument("--min-speech", type=float, default=2.0, help="skip clips with less speech than this, s (default 2)")
    vp.add_argument("--max-speech", type=float, help="skip clips with more speech than this, s: a long dictation pauses more "
                    "than a short line, so 25 keeps his notes comparable with short reads")
    vp.add_argument("--fast", action="store_true", help="skip the loudness and room-tone readings")
    vp.add_argument("--pitch-reader", choices=("auto", "praat", "autocorr"), default="auto",
                    help="who reads the pitch: Praat's tracker if praat-parselmouth is installed (auto), or a numpy "
                    "autocorrelation. Only rows from the same reader compare")
    vp.add_argument("--timeline", action="store_true",
                    help="look inside each clip instead: level, top end and pitch every --step, and the runs of sound "
                    "with their bursts (is that a laugh, a breath, or nothing?)")
    vp.add_argument("--step", type=float, default=0.1, metavar="S", help="--timeline: seconds per row (default 0.1)")
    vp.add_argument("--json", action="store_true")
    vp.set_defaults(fn=_cmd_voiceprint)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
