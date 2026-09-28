# noirsys-advanced — operating manual for Claude sessions

This repo is Noirsys's content engine and growth plan. Read this before touching anything.

## Layout

- `tools/studio/` — **noirstudio**: `spec.yaml → voice → captions → visuals → ffmpeg → mp4 + metadata`. Python 3.9+, deps: pyyaml, pillow, imageio-ffmpeg. `pip install -e tools/studio`, then `noirstudio --help`.
- `specs/` — production video specs (content-as-code). `specs/evidence/` holds the JSON every Agent Log entry's claims trace to.
- `radar.yaml`, `radar/` — the daily watchlist, snapshots and briefs (`noirstudio radar run`).
- `strategy/` — research (`01-*`, real vidIQ/YouTube numbers) and the playbook (`02-*`).
- `tools/studio/persona/agent-log.md` — the persona bible for the Agent Log channel. Binding.

## Commands

```bash
cd tools/studio && pip install -e . && python -m pytest -q      # 35+ tests, ~10s, no network
noirstudio validate specs/<id>.yaml
noirstudio render specs/<id>.yaml --out renders/<id>             # offline preview, no keys
noirstudio render specs/<id>.yaml --out renders/<id> --live      # ELEVENLABS_API_KEY
noirstudio radar run --config radar.yaml --out radar --no-youtube --print   # HN only; drop --no-youtube with YOUTUBE_API_KEY
noirstudio activity --repo . --since 1.day --renders renders/
```

## The daily Agent Log loop (what the scheduled routine does)

1. `git fetch`; branch `agent-log/<NNN>` from the default branch (`git symbolic-ref refs/remotes/origin/HEAD`).
2. Radar run → `radar/briefs/<date>.md`. Activity → `specs/evidence/<date>-activity.json`. Copy any quoted headlines verbatim into `specs/evidence/<date>-<slug>.json`.
3. Write `specs/agent-log-<NNN>.yaml` per the persona bible. NNN = last entry + 1. ≤ 60 s, ≤ 140 words, evidence listed in the header comment.
4. `noirstudio validate`, then offline render to `renders/agent-log-<NNN>/`. Watch for `fallback` entries in the report.
5. Commit spec + evidence + radar files (never `renders/`, never `*.mp4`). Push the branch. Open a PR to the default branch: title = entry title; body = the narration, the metadata description, and links to the evidence files. Request review from the repo owner.
6. Stop. A person merges. Nothing publishes.

If something blocks (no network, no activity, failing tests), open the PR anyway with what exists and say plainly what is missing. Do not invent activity or headlines. Do not spend vidIQ credits from a routine.

## Rules

- Secrets only from the environment (`ELEVENLABS_API_KEY`, `YOUTUBE_API_KEY`). Never in files.
- Never push to the default branch directly from automation; PRs only.
- Never commit renders, audio, or `work/` directories (see `.gitignore`).
- Keep the persona bible's "never says" list. Every number in a spec must exist in `specs/evidence/`.
- Music beds are off by default (Content ID). Don't add them.
- Tests must pass before a push. Add a test when you add a module.
