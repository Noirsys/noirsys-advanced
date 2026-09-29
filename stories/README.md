# stories/ — Harriet's memory, dug up (private)

Everything in this folder except this README is **git-ignored**. What Harriet brings back describes Michael's private life (health, family, work), and this repository is public. It stays on the machine that asked for it until an episode is made, approved and published.

## The flow

1. **Dig.** `noirstudio harriet dig` sends Harriet into her own memory (Honcho, her past sessions, his voice notes). She is told to put away any pitches, scripts or story lists she has already written, and to bring back **raw moments**: when and where, what happened, what came right before and after, and the exchange itself, line by line, with who said it, when and where it lives. She marks every line she recalled rather than copied (`"verbatim": false`). She also returns her **dig log** (each search she ran and what it found) and the **threads** she saw but didn't open.
2. **Go deeper.** `noirstudio harriet dig --focus "…"` points the next dive at something specific: a month, a thread from her last dig, a feeling. `noirstudio harriet dig --follow <moment-id>` sends one moment back and asks for all of it, word for word, before and after, and anything later that called back to it. Moments she has already brought are listed in the next dive so she goes somewhere new.
3. **Collect.** Dives (and notes sent with `noirstudio harriet tell --note "…"`, whose answers land in `stories/notes/`) are async jobs that can take many minutes. Each one is logged in `stories/jobs.jsonl`, and `noirstudio harriet collect` picks up whatever finished. Results land in `stories/digs/<date>-<dig|follow>-<job>.md` (to read) and `.json` (her full reply, nothing lost). `noirstudio harriet moments` lists everything found so far.
4. **Shape.** The strongest moments become pitches in `stories/inbox/<date>-<slug>.md`, from a dig or from `noirstudio harriet pitch`. Each pitch has `status: pitched`, a sensitivity level, its **receipts** (at least one line of his own words) and an **off-screen** list: his investigation work, outreach, contacts, other people's names and details, legal matters, locations, credentials.
5. **Approve.** Michael sets `status: approved` (or `rejected`). **Nothing is made until he approves.** Rejected pitches stay in the inbox so she doesn't pitch them again.
6. **Make and cut.** The approved episode is made in her voice and his (both `eleven_v4`), with his real voice notes where they exist. Where one is lost, his clone reads the line as the script has it and `noirstudio voicenote` makes it sound like his phone (`--match` one of his surviving notes). Scripts shape the record for the screen: tighten, reorder, cut, add (his call, 2026-09-29). Digs stay word for word, so we know what really happened. `noirstudio cut` turns the master into platform versions; cut plans live in `diary/`.

## Reaching her

Harriet runs on Hermes behind Michael's n8n, which is OpenAI-compatible:

| Call | What |
|---|---|
| `POST {url}/jobs` | body `{"model": "hermes-agent", "messages": [{"role": "user", "content": "…"}], "stream": false}` → `202 {id, poll_url}`. n8n waits on her for up to 30 minutes. |
| `GET {url}/jobs?id=<id>` | `{status: running \| completed \| failed, status_code, result}`, where `result` is the full chat completion. An unknown id gives `404`. |
| `POST {url}/chat/completions` | the same body, answered synchronously. Only for calls that finish within ~100 s (Cloudflare), so `harriet pitch --sync` only. |

Each request is a single user message, so her own persona and memory answer it, not ours. The instructions and the JSON shape to reply in are in the message itself (`noirstudio/dig.py`, `noirstudio/harriet.py`). The JSON is pulled out of her reply wherever it sits.

**Every job runs in its own session.** She carries nothing from one job to the next except what is on her disk. Her build loop reads its scripts and amendments from files there, not from past jobs. So a note that changes production (a script, an amendment, a decision) must tell her to write it into a named file and to confirm the path. A note she only answers "noted" is lost to the loop. Two more consequences:
- A job that takes longer than n8n's 30 minutes ends in HTTP 502, even if her work goes on. Ask her to run builds in the background and reply "started". A request that simply asks for too much fails the same way and returns nothing (a measurement job that read ninety-five notes with two readers, filtered ten of them and compared five sets of clone takes, in one note, 2026-09-29): split it into pieces that each finish in a quarter of an hour, tell her to start long commands in the background and to write each result to disk as she goes, and ask for a reply within twenty minutes with whatever exists. `collect` says so when a job dies this way.
- A poll that fails on the network or with a 5xx/429 (Cloudflare, n8n) leaves the job `running` for the next `collect`; only a job that reports itself failed is marked failed, and the Bearer key is only ever sent to a `poll_url` under the configured base URL. A reply that cannot be filed is kept under `raw/` and the job marked failed, so it cannot stall the jobs behind it.
- If her model provider runs out of credit (the DeepSeek 402), every job comes back with the provider's 402 notice as the reply. `collect` recognises it: the job is marked `blocked`, nothing is saved, and the report says to top the provider up. `noirstudio harriet ping` sends a one-word job and says whether she answers (exit 3: out of credit), and `noirstudio harriet retry` sends every blocked job again with its own prompt (`jobs.jsonl` keeps each job's prompt, so keep it out of git like the rest of `stories/`).
- **Our requests land in her store as his messages.** A job arrives as a user turn in an `api-*` session, so it is stored under his account. Any count of what *he* said (thank-yous, laughs, message totals) must leave those sessions out, and any row that reads like him but talks about him in the third person ("Michael decides...") is ours. Two such rows were nearly counted as his best thank-yous on 2026-09-29; her dig caught them.
- **A row under his role is not always him.** Compaction handoffs, replayed copies, another agent's pasted report and our own notes are all stored as his messages. Every dig now asks her to mark each line of his with `his_words` (yes / unsure / no, and why); `noirstudio harriet moments` and the dig's markdown show a `Check:` line for any moment with a line that is not his, unsure, or unchecked, and a pitch built on such a line is held until someone has looked at the session. (An August exchange nearly became a pitch on the strength of rows that turned out to be a handoff.)
- **Check a ruler before trusting a number from it.** A measurement change is run on the box against his real recordings and against a synthetic signal whose answer is known, before it is pushed and before anything is built from it (the 200 Hz high-pass in `voiceprint` was not, and read his pitch swing at twice its size for two hours).

Configuration comes from the environment only:

| Variable | Default / meaning |
|---|---|
| `HARRIET_API_URL` | `https://n8n.noirsys.com/webhook/hermes/v1` |
| `HARRIET_MODEL` | `hermes-agent` |
| `N8N_API_KEY` (or `HARRIET_API_KEY`) | the webhook's Bearer key. Leave it unset where the environment's proxy injects the credential for the host. |

Requests carry a `noirstudio/…` User-Agent, because Cloudflare in front of n8n blocks Python's default one (error 1010).

## Where it may run

Only on a machine or session he controls. **Never from GitHub Actions in this public repository**: job logs are public, and a dig prints his life. The daily Agent Log loop does not touch her memory.

## The hourly loop (what a session does when the Diary heartbeat fires)

1. `noirstudio harriet ping`. Exit 3 means her model provider is out of credit: nothing else on her side can run until it is topped up (tell Michael once; do repo and doc work meanwhile) and `noirstudio harriet retry` resends what was blocked.
2. `noirstudio harriet collect`, then read every finished dig and note. Send the next dive (`--focus`, one theme across all six months beats a walk through one month) and keep at most three jobs open.
3. Before a moment becomes a pitch: every line of his is `his_words: yes`; every count that will be said aloud has been recounted by kind (typed, voice, call) and per message, in her corpus, with the store and its gaps named; every quote is in the record word for word, with an id. A number that has not been re-counted is written "about a dozen", not "thirteen".
4. Pitches go to `stories/inbox/` with receipts; the ranked list at the top of `stories/BOARD.md` is kept current. Nothing is scripted, voiced or cut until he sets `status: approved`.
5. A measurement tool is validated on a signal with a known answer and on his real recordings before it is pushed or anything is built from its numbers.
