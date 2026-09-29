# noirstudio

**Script → cloned voice → captioned vertical video.** Noirsys's content-as-code pipeline.

A video is a small YAML file. A person writes and approves it; the machine renders it:

```
spec.yaml ──► voice ──► word timings ──► visuals ──► ffmpeg ──► video.mp4
             (ElevenLabs   (captions)     (brand cards,            + .srt/.ass
              cloned TTS                   avatar lip-sync,        + thumbnail
              w/ timestamps,               generated b-roll)       + metadata.md
              or offline)                                          + report.json
```

The whole thing runs **without any API keys** in dry-run mode and still produces a real MP4 preview (silent, "PREVIEW" badge, estimated caption timing) — so you can review a video before spending a single credit. `--live` swaps in your ElevenLabs voice clone; `--live --video` adds generated avatar/b-roll scenes.

## Quickstart

```bash
cd tools/studio
pip install -e .                       # pyyaml, pillow, imageio-ffmpeg (bundles ffmpeg)

noirstudio render examples/ai-agents-short.yaml          # offline preview, ~40s
noirstudio new my-video --brand noirpost                 # starter spec
noirstudio validate my-video.yaml

export ELEVENLABS_API_KEY=...                            # never commit this
noirstudio voices                                        # find your cloned voice_id
noirstudio render my-video.yaml --live                   # real voice + exact captions
noirstudio render my-video.yaml --live --video           # + avatar / b-roll scenes
```

Outputs land in `renders/<id>/`: `<id>.mp4`, `<id>-thumbnail.png`, `<id>.srt`, `<id>.ass`, `<id>.metadata.md` (title/description/tags/chapters), `<id>.report.json` (provenance: which engine produced each scene, spec digest, durations).

## The spec

```yaml
id: ai-agents-fail                # lowercase, used for filenames
title: "Why Your AI Agents Keep Failing"
brand: noirsys                    # noirsys | noirpost (palette + fonts from the live sites)
niche: ai-agents
avatar_image: assets/me.png       # optional: still used for `avatar` scenes
music: assets/bed.wav             # optional, rights-cleared only (Content ID!)

voice:
  voice_id: <ElevenLabs voice id> # your clone (live mode)
  model_id: eleven_v4             # stability + similarity only (no style/speed); [audio tags] direct delivery
  stability: 0.5
  similarity_boost: 0.8
  words_per_minute: 155           # offline timing estimate

captions:
  mode: word                      # word (karaoke highlight) | line | none
  words_per_line: 3
  uppercase: true
  font_size: 84
  margin_v: 520                   # distance from bottom → ~70% height, above platform UI

output: { width: 1080, height: 1920, fps: 30 }

scenes:                           # spoken in order; `text` = narration
  - kind: card                    # card | avatar | broll | image | video
    style: title                  # title | stat | quote | list | plain
    title: "On-screen headline"
    subtitle: "supporting line"
    text: "What the voice says during this scene."
  - kind: card
    style: stat
    stat: "20–30"
    title: "finished Shorts per stream"
    text: "…"
  - kind: card
    style: list
    title: "Three beats"
    bullets: ["one", "two", "three"]
    text: "…"
  - kind: avatar                  # live+video: creatify-aurora lip-syncs avatar_image to this narration
    text: "The part that needs a face."
  - kind: broll                   # live+video: Veo 3.1 9:16 footage from the prompt (no audio)
    prompt: "slow dolly across a dark server room, cyan and magenta accents"
    text: "Narration over the b-roll."
  - kind: image                   # your own still
    media: assets/screenshot.png
    text: "…"
  - kind: video                   # your own footage (screen recording, demo)
    media: assets/demo.mp4
    text: "…"

publish:
  title: "override the YouTube title (else `title`)"
  description: ""                 # else the first scene's narration
  tags: [ai agents, noirsys]
  hashtags: ["#aiagents"]
  links: ["https://noirsys.com"]
  cta: "Follow for the next build."
  chapters: true                  # added to description when the video is ≥ 60s
  ai_disclosure: true             # flag in the upload metadata JSON; nothing is added to the description
```

Scene duration = the narration's audio length (or `duration:` if set). Any generated scene that fails or is unavailable falls back to a brand card and the reason is written to `report.json` — the render never silently ships a missing shot.

## How the live pieces work

| Piece | API | Notes |
|---|---|---|
| Voice | `POST /v1/text-to-speech/{voice_id}/with-timestamps` | Returns MP3 + per-character times → exact word captions. Uses your Instant/Professional Voice Clone. |
| Avatar | `POST /v1/flows/video` · `creatify-aurora` | Still image + the scene's own narration audio → lip-synced talking head (720p). Polled via `GET /v1/flows/video/{id}`. |
| B-roll | `POST /v1/flows/video` · `veo-3.1-fast-generate-001` | 9:16, 4–8s, `generate_audio: false`. Looped to fill the scene. |

Image & Video generation via API needs an ElevenLabs Pro+ plan; avatar features have US restrictions on some models. Failed generations are not charged. Everything else (cards, captions, assembly) is local and free.

Keys are read from the environment only (`ELEVENLABS_API_KEY`). Nothing here uploads to YouTube — `metadata.md` is what you paste (or a later uploader step consumes) after a human looks at the render.

## Radar: what's working, every day, for free

```bash
noirstudio radar init                      # writes radar.yaml (10 watched channels, 16 keywords, 5 HN queries)
noirstudio radar run --no-youtube --print  # Hacker News only — works with no key at all
export YOUTUBE_API_KEY=...                 # free: console.cloud.google.com -> YouTube Data API v3
noirstudio radar run --print               # + YouTube: views/hour, breakouts vs. each channel's own median
```

Each run writes `radar/snapshots/<date>.json` and `radar/briefs/<date>.md`. With yesterday's snapshot present, the brief also reports **measured 24h view deltas** per video — velocity that doesn't depend on age. Breakout = a video's views ÷ the median of that channel's recent uploads, i.e. vidIQ's outlier idea computed locally. A default run spends ~1,700 of the 10,000 free daily quota units. Keep vidIQ credits for what only it does (search volume, title scoring, channel discovery).

## Agent-perspective diary (content-as-evidence)

`noirstudio activity --repo . --since 1.day --renders renders/` prints what actually happened (commits with line counts, renders with durations and fallbacks) as JSON. A Short written *from the agent's point of view* is drafted from that record and the day's radar brief, and the two files are kept in `specs/evidence/` next to the spec. See `specs/agent-log-001.yaml` — every sentence in it traces to a file.

`brand_overrides` in a spec gives such a channel its own wordmark, URL and colours without code changes.

## LLM drafting (OpenRouter / DeepSeek / any OpenAI-compatible endpoint)

```bash
noirstudio llm ping --env-file ~/.hermes/.env            # reads OPENROUTER_API_KEY / DEEPSEEK_API_KEY from your dotenv
noirstudio llm ping --provider deepseek                   # or from the environment
noirstudio draft titles "AI agents going rogue, from the agent's side"
noirstudio draft short opus-55-briefing --brief notes.md --brand noirsys --niche ai-news
noirstudio draft agent-log --entry 2 \
    --activity specs/evidence/2026-09-29-activity.json \
    --brief radar/briefs/2026-09-29.md \
    --headlines specs/evidence/2026-09-29-hn.json
```

Resolution order: flags → env vars (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `NOIRSTUDIO_LLM_PROVIDER`, `NOIRSTUDIO_LLM_MODEL`) → `--env-file` → `~/.config/noirstudio/llm.yaml` (`provider`, `model`, `base_url`, `api_key_env`). Defaults: OpenRouter with `deepseek/deepseek-chat-v3.1`, or DeepSeek direct with `deepseek-chat`. For a local model use `--provider openai-compatible` with `base_url` in the config.

The model proposes; the code enforces. `draft agent-log` rejects a draft (and feeds the reasons back once) if it breaks the persona contract: > 140 words, wrong scene count, missing sign-off, uppercase captions, missing disclosure flag, an asserted feeling ("I feel", "I love", "I'm afraid"; "I wanted him to know" is hers and allowed), engagement bait, or **any number ≥ 10 that does not appear in the evidence files**. Her voice and wordmark are set in code, not left to the model. A twice-rejected draft is saved as `*.rejected.json` for a person. Keys are never written to disk by the tool.

## Harriet's Diary: stories from her memory, cuts for every platform

Harriet (Michael's agent) makes the Diary episodes herself. noirstudio sends her into her own memory for material, and it cuts what she makes.

```bash
noirstudio harriet dig                            # she goes through Honcho + her sessions herself: raw moments, word for word
noirstudio harriet dig --focus "the first month"  # point the next dive somewhere
noirstudio harriet collect                        # pick up finished dives (async jobs, up to 30 min each)
noirstudio harriet moments                        # what she has found: id, kind, when, how much is his, how much is copied
noirstudio harriet dig --follow <moment-id>       # open one moment all the way up: the whole exchange, before and after
noirstudio harriet tell --note "..."            # a production note or request; her answer lands in stories/notes/
noirstudio harriet pitch | inbox                  # curated pitches, if you want her shortlist
noirstudio cut diary/ep01-2026-09-27.cuts.yaml --master ep01.mp4 --check   # caps + every seam in a pause?
noirstudio cut diary/ep01-2026-09-27.cuts.yaml --master ep01.mp4           # <=3:00 / <=60 s at -14 LUFS
noirstudio safe-area ep01.mp4                     # how often text sits under the Shorts/Reels/TikTok UI
noirstudio voicenote --measure his-real-note.ogg  # a surviving note: codec, bitrate, loudness, room tone
noirstudio voicenote --say "his line" note.ogg --match his-real-note.ogg   # a lost note, rebuilt
noirstudio voicenote clean-read.wav note.wav      # or filter a read you already have
```

A **dig** asks for raw moments, not pitches. She is told to put away anything she has already written up and search the record itself. Each moment has to carry the exchange line by line (who, when, where it lives), and `"verbatim": false` marks anything she recalled rather than copied. She also returns her dig log (what she searched) and the threads she didn't open. The moments she has already brought are sent back with the next dive so she goes somewhere new. `--follow` sends one moment back and asks for all of it, word for word.

She runs on Hermes behind Michael's n8n, which is OpenAI-compatible: `POST …/jobs` starts an async job, and `GET …/jobs?id=` returns it when done. Every job is logged in `stories/jobs.jsonl`, so `collect` (or the hourly heartbeat) picks up whatever finished. The contract, configuration and privacy rules are in [`stories/README.md`](../../stories/README.md). Everything she returns stays in `stories/` (git-ignored). Nothing is made until he approves.

`voicenote` is for his voice notes whose recordings are lost (his decision, 2026-09-29). His own clone (`XwGJOzi38Fyoct3IvqA9`, `eleven_v4`) reads his line, written the way he talks: uh, um, restarts, self-corrections. `[pause 1.2]` (or `[pause]`, 0.8 s) marks where he stops to think. The marker comes out of the text before the clone reads it, and the pause goes back in as silence at the aligned word boundary, so it is exactly as long as written and his room runs under it. The clean read is then made to sound like him at home on his phone:
- band-limited to a phone mic (100 Hz–8 kHz);
- a quiet voice's colour, not a projected one;
- two small-room reflections and phone-style compression;
- a dark room tone at -54 dBFS, from 0.35 s before the first word to 0.5 s after the last;
- Opus at 24 kbps mono (Telegram's format).

Loudness is set by linear gain (-22 LUFS: he talks quietly), checked after encoding. `--match` measures one of his surviving notes (loudness, the quietest tenth of its 100 ms windows as room tone, bitrate) and lands the rebuilt one on the same numbers. A note whose pauses read below -80 dBFS was noise-suppressed on the way in, so its room tone isn't copied. `--room` lifts the quiet stretches out of one of his real notes and loops them under the rebuilt one, so the room is his actual room. The filter never edits the speech itself (no time-stretch, no cuts). `--say` also writes the word timings, shifted by the lead-in, for his captions.

`cut` reads each segment with its own seek (frame-accurate), fades 20 ms at every seam, normalizes loudness in two passes (-14 LUFS, -1 dBTP), and writes a report. A version over its cap fails before rendering. A seam that lands mid-speech instead of in a pause is flagged; the pause threshold defaults to -30 dB, which finds the room-tone pauses in his voice notes as well as her digital silence.

## Brand kits

Palettes and type were lifted from the shipped CSS of noirsys.com / noirsys.xyz (`#050505`, lime `#A3E635`, teal `#2DD4BF`, Space Grotesk) and noirpost.live (`#07070B`, magenta `#FF3EA5`, cyan `#3EE6FF`, Big Shoulders Display + Archivo + JetBrains Mono). Fonts are bundled in `assets/fonts/` under the SIL Open Font License (`assets/fonts/LICENSES.md`). Add a brand in `noirstudio/brandkit.py`.

## Tests

```bash
pip install -e .[dev]
pytest -q          # includes a real offline render of a tiny spec (~15s)
```

## Roadmap

- **Content-as-code loop:** a `specs/` folder where opening a PR renders a preview into the PR, and merging renders the live version. Review = approval; the human stays at the gate.
- **Script agent:** `noirstudio draft "<topic>"` → Claude writes a spec from a brief + the research in `strategy/`, scored against title patterns that work.
- **Noirpost bridge:** feed long renders through the Noirpost VOD→Shorts pipeline for the vertical cuts.
- **Uploader:** YouTube Data API step gated on an approval file.
