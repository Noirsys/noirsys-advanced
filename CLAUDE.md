# noirsys-advanced — operating manual for Claude sessions

This repo is Noirsys's content engine and growth plan. Read this before touching anything.

## Layout

- `tools/studio/` — **noirstudio**: `spec.yaml → voice → captions → visuals → ffmpeg → mp4 + metadata`. Python 3.9+, deps: pyyaml, pillow, imageio-ffmpeg. `pip install -e tools/studio`, then `noirstudio --help`.
- `specs/` — production video specs (content-as-code). `specs/evidence/` holds the JSON every Agent Log entry's claims trace to.
- `radar.yaml`, `radar/` — the daily watchlist, snapshots and briefs (`noirstudio radar run`).
- `strategy/` — research (`01-*`, real vidIQ/YouTube numbers), the playbook (`02-*`), and the Harriet decision (`04-*`).
- `tools/studio/persona/agent-log.md` — Harriet's persona bible, for both her formats (the Diary and the Agent Log). Binding.
- `diary/` — cut plans for her Diary episodes (`noirstudio cut`). Beat labels only; never quotes. Not under `specs/`: CI's render job treats `specs/**/*.yaml` as video specs.
- `stories/` — what Harriet digs out of her memory (`noirstudio harriet dig`) and her pitches. **Git-ignored**: it describes his private life and the repo is public. Nothing is made until he sets `status: approved`. See `stories/README.md`.

## Commands

```bash
cd tools/studio && pip install -e . && python -m pytest -q      # 90+ tests, ~30s, no network
noirstudio harriet dig [--focus ...|--follow ID] && noirstudio harriet collect   # she goes through her memory (N8N_API_KEY or proxy)
noirstudio harriet moments | pitch | inbox                      # what she found; curated pitches
noirstudio harriet ping | retry                                  # does she answer (or is her provider out of credit)?; resend the blocked jobs
noirstudio cut diary/<ep>.cuts.yaml --master EP.mp4 [--check]    # full / <=3:00 / <=60 s versions, -14 LUFS
noirstudio voicenote --say "his line" OUT.ogg --match REAL.ogg   # a lost voice note of his, rebuilt (ELEVENLABS_API_KEY)
noirstudio voicenote --say "his line" OUT.ogg --preset home --match REAL.ogg   # the same, with the recipe measured from his real notes (swing 2.1 st, 104 Hz, pace, pauses, stumbles); opt-in until he has heard it; leave --noise-db alone (a pause with nothing under it is the dead silence he hears as fake)
noirstudio voiceprint HIS.ogg ... --vs OURS.ogg ...              # how close our reads are to his real notes, in numbers (needs numpy)
noirstudio voiceprint CLIP.ogg --timeline                        # inside one clip, 100 ms at a time: level, pitch, bursts (a laugh? a breath?)
noirstudio voiceprint HIS.ogg ... --readers-apart               # where the two pitch readers part on real notes (needs parselmouth)
noirstudio validate specs/<id>.yaml
noirstudio render specs/<id>.yaml --out renders/<id>             # offline preview, no keys
noirstudio render specs/<id>.yaml --out renders/<id> --live      # ELEVENLABS_API_KEY
noirstudio radar run --config radar.yaml --out radar --no-youtube --print   # HN only; drop --no-youtube with YOUTUBE_API_KEY
noirstudio activity --repo . --since 1.day --renders renders/
```

## Runners

Two things can run the daily loop; either produces one PR for a human.

- **GitHub Actions** (`.github/workflows/agent-log.yml`, 10:10 UTC daily, or *Run workflow*): executes `noirstudio loop agent-log --push --pr` with repo secrets (`OPENROUTER_API_KEY`/`DEEPSEEK_API_KEY`, optional `YOUTUBE_API_KEY`). Credentialed by `GITHUB_TOKEN`; needs the repo setting "Allow GitHub Actions to create and approve pull requests" to open PRs itself. Mechanical drafting + enforcement, no editorial pass.
- **Claude routine** ("Agent Log daily entry", 06:10 ET) — **disabled 2026-09-28**: two trigger-spawned sessions ran the steps but produced no branch, PR, or report (they lack push credentials and connectors, and their transcripts are unreadable from outside). Keep it off unless that changes; an interactive Claude session can still run the loop by hand and edit the draft against the persona bible.

Repo settings the Actions runner needs (Noirsys is an organization, so the first is org-level): *Organization → Settings → Actions → General → Workflow permissions → "Allow GitHub Actions to create and approve pull requests"*, then the same in the repo; and the LLM key as a **repository secret** named exactly `OPENROUTER_API_KEY` (not an Environment secret, not a variable).

`noirstudio loop agent-log` (no `--push`) is also the fastest way to reproduce a run locally.

## The daily Agent Log loop (what the scheduled routine does)

1. `git fetch`; branch `agent-log/<NNN>` from the default branch (`git symbolic-ref refs/remotes/origin/HEAD`).
2. Radar run → `radar/briefs/<date>.md`. Activity → `specs/evidence/<date>-activity.json`. Copy any quoted headlines verbatim into `specs/evidence/<date>-<slug>.json`.
3. Write `specs/agent-log-<NNN>.yaml` per the persona bible. NNN = last entry + 1. ≤ 60 s, ≤ 140 words, evidence listed in the header comment. If `OPENROUTER_API_KEY` or `DEEPSEEK_API_KEY` is set, get the first draft from `noirstudio draft agent-log --entry NNN --activity <activity.json> --brief <brief.md> [--headlines <hn.json>]` (it enforces the contract mechanically), then read it as an editor: tighten, cut anything the evidence doesn't support, keep the sign-off. Without a key, write it yourself to the same rules.
4. `noirstudio validate`, then offline render to `renders/agent-log-<NNN>/`. Watch for `fallback` entries in the report.
5. Commit spec + evidence + radar files (never `renders/`, never `*.mp4`). Push the branch. Open a PR to the default branch: title = entry title; body = the narration, the metadata description, and links to the evidence files. Request review from the repo owner.
6. Stop. A person merges. Nothing publishes.

If something blocks (no network, no activity, failing tests), open the PR anyway with what exists and say plainly what is missing. Do not invent activity or headlines. Do not spend vidIQ credits from a routine.

## Rules

- Secrets only from the environment (`ELEVENLABS_API_KEY`, `YOUTUBE_API_KEY`). Never in files.
- Never push to the default branch directly from automation; PRs only.
- Never commit renders, audio, or `work/` directories (see `.gitignore`).
- Keep the persona bible's "never says" list. Every number in a spec must exist in `specs/evidence/`.
- Voices (`eleven_v4`, both): his Professional Voice Clone `XwGJOzi38Fyoct3IvqA9` is for specs he narrates (e.g. `specs/straightshot-teaser.yaml`), and for his Diary voice notes whose recordings are lost: it reads the line as the script has it, written the way he talks (uh, um, restarts, self-corrections, `[pause 1.2]` where he thinks), and `noirstudio voicenote` makes it sound like him at home: quiet, on his phone, with his room under it (`--room` lifts the real room tone from one of his notes). His clone must not sound performed (his note: "too perfect, dynamic, articulate"): `--rough` (default 2) and `--stability` (default 0.85) keep it lazy, and his lines are written like his transcripts, not like sentences. `noirstudio voiceprint` measures it: against 87 of his real notes (2026-09-29) the clone sat well above him in pitch, swung further, spoke a quarter faster and paused a third as long, and none of `--rough` or `--stability` moved the pitch (the pitch numbers are in `strategy/04`, with the reader that read them: never trust a pitch number whose reader is not named, and never high-pass before reading it). `--swing`, `--pitch`, `--pace`, `--hesitate` and `--raw` close those gaps (opt-in until he has heard it; his ear decides). The Diary is content, not testimony (his decisions, 2026-09-29): scripts may tighten, reorder, cut or add lines, but never invent words for anyone but him and Harriet. An episode where his clone says a line he never said gets YouTube's altered-content toggle at upload. Harriet (the Diary and the Agent Log) speaks with `ZSNL4hPqCnqoMPaI4jGX` — the drafter sets it on every entry, and a test fails any Agent Log spec without it or with his clone. v4 takes stability + similarity only and has no `/with-timestamps`: caption timings come from forced alignment (see `voice.py`).
- Harriet's pitches and receipts (his voice notes, her messages) never go in git until the episode is published; he approves every story first. Her off-screen list is binding: his investigation work, outreach state, contacts, other people, legal matters, locations, credentials.
- Music beds are off by default (Content ID). Don't add them.
- Tests must pass before a push. Add a test when you add a module.
