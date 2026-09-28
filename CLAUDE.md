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
- Music beds are off by default (Content ID). Don't add them.
- Tests must pass before a push. Add a test when you add a module.
