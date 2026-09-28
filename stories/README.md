# stories/ — Harriet's pitches (private)

Everything in this folder except this README is **git-ignored**. Pitches describe Michael's private life (health, family, work), and this repository is public. They live on the machine that asked for them until an episode is made and published.

## The flow

1. `noirstudio harriet pitch` asks Harriet to go through her memory and curate the best true stories for the next diary episodes (3 by default). Each pitch lists its **receipts**: the voice notes, messages or commits it rests on, with when and the exact words. A pitch with no receipts is dropped.
2. Pitches land in `stories/inbox/<date>-<slug>.md` with `status: pitched`, a sensitivity level (`low` / `medium` / `high`) and an **off-screen** list: what must not appear (his investigation work, outreach state, contacts, other people, legal matters, locations, credentials).
3. Michael reads them and sets `status: approved` (or `rejected`). **Nothing is made until he approves.** `noirstudio harriet inbox` lists them with their status.
4. Harriet makes the approved episode; `noirstudio cut` turns the master into platform versions (cut plans live in `diary/`).

Titles already in the inbox are sent back to her as "already told", so she doesn't repeat herself.

## The endpoint contract (n8n webhook)

Set in the environment, never in files:

| Variable | What |
|---|---|
| `HARRIET_STORIES_URL` | the n8n webhook's production URL |
| `HARRIET_API_KEY` | the key the webhook checks (leave unset if the environment's proxy injects it) |
| `HARRIET_API_KEY_HEADER` | header the key goes in; default `Authorization` (sent as `Bearer <key>`); set e.g. `X-API-Key` to send it raw |

**Request** — `POST`, `Content-Type: application/json`:

```json
{
  "n": 3,
  "theme": "",
  "since": "",
  "avoid": ["titles already pitched"],
  "prompt": "the full instructions for Harriet, including the JSON shape to reply in"
}
```

Pass `prompt` to Harriet as-is: it tells her what made episode one work, the rules (true only, receipts, off-screen list, sensitivity) and the exact reply shape.

**Response** — `200`, any of these is fine:

- `{"pitches": [ ... ]}` (best);
- `{"output": "<her reply>"}` or `[{"output": "<her reply>"}]`, as n8n's AI Agent node returns it; the JSON is pulled out of her text;
- her reply as plain text containing the JSON.

Each pitch:

```json
{
  "title": "working title, <= 70 characters",
  "logline": "one sentence",
  "when": "2026-09-24 03:11-03:44",
  "hook": "the first line on screen",
  "beats": ["4-8 beats: the moment, what went wrong or got misread, the turn, the ending"],
  "ending": "the last line",
  "receipts": [{"kind": "voice_note | message | commit | document | other", "when": "...", "excerpt": "exact words"}],
  "sensitivity": {"level": "low | medium | high", "topics": ["family"]},
  "off_screen": ["what must not appear"],
  "length_s": 150,
  "why_it_lands": "one or two sentences"
}
```

She searches her memory, so the client waits up to 10 minutes. If the webhook sits behind a proxy with a shorter timeout (Cloudflare cuts at 100 s), have the workflow respond when Harriet is done rather than streaming.
