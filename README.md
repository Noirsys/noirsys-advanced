# noirsys-advanced

The base from which Noirsys's growth work is carried out: the content engine, the research behind it, and the plan.

| Path | What it is |
|---|---|
| [`tools/studio/`](tools/studio/) | **noirstudio** — script → cloned voice → captioned vertical video. Content-as-code: a video is a YAML file a person approves; the machine renders it. Runs with no API keys (offline preview) and with ElevenLabs for the real thing. |
| [`strategy/01-youtube-research-2026-09-28.md`](strategy/01-youtube-research-2026-09-28.md) | Data-backed research: what's winning on YouTube in the AI space right now (vidIQ + YouTube pulls), keyword demand, four faceless channel concepts, twenty scored titles, and the founder-face shortlist. |
| [`strategy/02-growth-playbook.md`](strategy/02-growth-playbook.md) | The playbook: positioning, the flywheel between noirsys.com / noirsys.xyz / noirpost.live, the content system, autonomy loops, and the 90-day plan. |

## Try it

```bash
cd tools/studio && pip install -e .
noirstudio render examples/ai-agents-short.yaml     # a finished preview MP4 in ~40s, no keys needed
```

Set `ELEVENLABS_API_KEY` in the environment (never in the repo) and add `--live` for your cloned voice.

## Principles (same as the sites)

1. **Evidence before claims.** Every render ships a `report.json` saying exactly what produced each shot.
2. **Human authority at the gates.** Nothing publishes itself; the spec is the approval.
3. **Products emerge from use.** The tooling here exists because it was needed to ship the content.
