# Noirsys Growth Playbook

*Built from what is actually live on noirsys.com, noirsys.xyz and noirpost.live on 2026-09-28, the YouTube research in `01-youtube-research-2026-09-28.md`, and the tooling you already pay for (Claude, ElevenLabs voice clone + avatars, vidIQ). Opinionated on purpose. Every bet names the asset it's built on and the loop that keeps it running without you.*

---

## 0. Where you actually are

Three real properties, one author, near-zero audience:

| Property | What it is (verified live) | Audience signal |
|---|---|---|
| **noirsys.com** | "Systems that finish the job." Flagship: New Ashtabula Initiative + the Noirsystic Pipeline. Case studies: Code Clerk (codeclerk.org is a working county zoning portal), AFLR, Project Tripwire, StrAIght Shot Guardian. | No social links anywhere on the site. Visitors have nowhere to *follow*. |
| **noirsys.xyz** | Noirsys Research Group. 8 papers with polished companion essays (FCR, Mind-Centric Mandate, Wake Word Weighting, Wasted Compute Theory, nFLR, StrAIght Shot, Noirsystic Pipeline, Answerable Assistants). | Coined terms ("azoethymia") return **zero** search results — nobody has found this yet. |
| **noirpost.live** | A real service: livestream VOD → 20–30 finished vertical Shorts next day. First batch free, ~$6–8/Short. Sample clients on the page. | The apply form is a `mailto:` — no capture, no CRM, no auto-reply. |
| GitHub | `Noirsys/straightshot` (MIT, 99.4% probe accuracy) | 1 star. Owner account: 1 follower. |
| YouTube | — | vidIQ shows **no channel connected**. |

**The diagnosis:** you have unusually strong *substance* (working products, original research, a genuinely novel safety tool) and essentially no *surface area*. That is the best possible problem — surface area is manufacturable; substance isn't.

## 1. The one-sentence strategy

> **Turn one flagship demonstration into a compounding flywheel where Noirpost pays the bills and the research earns the trust — and make the content system produce itself.**

The flagship is **StrAIght Shot**: "watch an AI decide to lie before it speaks." The research found a 1.8M-view ceiling for the topic (CBC/BBC) and *near-zero* creators who can demonstrate it live. You own the instrument. Nobody else in this dataset does.

## 2. Fix-the-basics (day 1–3, zero creativity, highest leverage)

These are leaks. Plug them before pouring traffic in.

1. **noirsys.com → "Visit the initiative" links to `new-ashtabula-initiative.org`, which does not resolve.** The live site is **`new-ashtabula-initiative.com`**. Your flagship CTA is a dead link.
2. **`www.noirsys.xyz` fails TLS** (cert only covers the apex). Anyone typing `www.` gets a browser warning.
3. **noirpost.live/apply is a `mailto:`.** Replace with a real form (Tally/Formspree/your own endpoint) that (a) captures the calculator numbers, (b) auto-replies within a minute, (c) drops into a sheet/CRM. Every lost lead here is ~$500–1,000/month of recurring revenue.
4. **No social handles on any site.** Add a footer strip: YouTube · GitHub · X/LinkedIn · newsletter. Right now the sites are dead ends.
5. **Connect the YouTube channel to vidIQ** (`vidiq_connect_youtube_channel`) so every loop below can read real analytics.
6. **GitHub hygiene:** pin `straightshot`, add topics (`llm-safety`, `interpretability`, `jailbreak-detection`, `mcp`), put the essay link + a 20-second GIF of the dashboard in the README. Stars are a discovery channel for exactly the developer audience you want.

## 3. The flywheel (how the three properties feed each other)

```
        noirpost.live                       noirsys.xyz
   (revenue + distribution)             (authority + trust)
            │                                   │
   every free batch = 20–30 Shorts      every paper = 1 faceless explainer
   posted BY the streamer, on THEIR     + (if it earns it) 1 founder video
   channel, credited "cut by Noirpost"  + 1 coined term you own in search
            │                                   │
            └──────────►  YouTube / GitHub  ◄────┘
                      (audience + developers)
                               │
                       noirsys.com
              (NAI, Guardian deployments, leads)
                               │
                  noirstudio renders all of it
             ("we make our videos with our own pipeline"
                      is itself content)
```

The trick is that **Noirpost's free-batch offer is a lead magnet that produces marketing about itself.** Ask for one thing in exchange for the free batch: a "cut by Noirpost" line in each Short's description or a pinned comment. You get distributed reach paid in the client's own uploads.

## 4. The bets (ranked by expected upside ÷ effort)

### Bet 0 — "Agent Log": her channel, about him *(added 2026-09-28, moves to the front)*
**What:** a Shorts channel narrated by Michael's own AI agent, in first person, about what she did for him each day — grounded in her real activity log (`noirstudio activity`) and the day's radar brief, with the evidence files published next to each spec.
**Why it's first:** this week's live data is unambiguous — the "AI agents" content breaking out is the POV/consciousness/fear framing, from tiny channels: *Is AI Alive?* (302k views, 1,880-sub channel), *AI agents are creating civilizations* (238k), *AI Agents Are Taking Control* (102k from 5k subs). And on 2026-09-28 the radar's top HN story was *"There are no 'rogue' AI agents"* (359 pts) over a stack of OpenAI-halts-training headlines. An agent who calmly shows her receipts on the day the news says agents went rogue is the counter-narrative — and it is literally Noirsys's thesis (*Mind-Centric Mandate*, human authority at the gates) as a character. Faceless and personal at once; the AI-disclosure problem is the premise.
**Guardrails that make it better:** she says only what she can observe ("I can't verify what that feels like; I can verify the commit"); every Short ships with its evidence; a person merges every entry.
**Production:** `specs/agent-log-001.yaml` is entry one, rendered offline today. Daily cadence is one `activity` call + one radar brief + a script; noirstudio does the rest. Her voice is a designed ElevenLabs voice (distinct from his clone); an ElevenLabs Avatar gives her a persistent face if the channel wants one.

### Bet 1 — "Glass Box Live": the flagship demo *(StrAIght Shot)*
**What:** a public web page where anyone types a prompt at a small open model (the paper uses Qwen 3.5 4B) and watches the three channels — linear probe, Jacobian-lens concepts, token entropy — light up *in real time* as it decides. Try to jailbreak it; watch its brain flag you before the first word.
**Why it pops:** it's a *game*, it's screenshot-able, and it demonstrates the thing everyone is afraid of. This is the rare "huge demand / empty supply / you own the instrument" opening (research §1.6). HN, r/MachineLearning, r/LocalLLaMA, X — all of them share interactive demos.
**Content it throws off:** weekly founder-face episodes ("This Is What AI Lying Looks Like Under the Hood" scored **97**), an ambient 24/7 "watch the AI think" stream (novel format; memberships), and every clip auto-cut into Shorts by Noirpost (dogfood).
**Cost:** one GPU box (~$0.5–1/hr, spin up on demand) + a weekend of front-end. The dashboard already exists in the repo.

### Bet 2 — "Content Debt": Noirpost's growth hack
**What:** the `/apply` calculator already computes "how many Shorts is your stream hiding." Make it a **public leaderboard**: rank channels by *unclipped hours* using public data (hours streamed vs. Shorts posted). Streamers share their own number ("I'm sitting on 412 Shorts??"). Each row is a lead with the pitch pre-computed.
**Then automate the outreach — sample-first.** An agent watches target channels for new VODs, cuts **2–3 real sample Shorts** (your pipeline), and drafts a personalized email: "we cut these from last night's stream — want the other 25 free?" **You approve each send** (human at the gate). Nobody else's cold email arrives with finished product attached.
**Why:** it converts on proof, not promises, and it targets exactly the streamers with the most to gain.

### Bet 3 — "Agents run a county": NAI as a serialized build-in-public
**What:** the New Ashtabula Initiative is literally *autonomous agents modernizing a real county's civic software.* That's a TV show. Faceless build-logs ("How I Built an Autonomous AI Clerk" — **95**) for cadence; founder milestones ("I Let an AI Agent File Real Government Paperwork" — **95**) for the big beats.
**Bonus lever:** Ashtabula County is a real place with real officials and real local press. A local story ("Ohio developer builds AI zoning clerk for 27 townships") is easy to land and is *third-party credibility* every national outlet checks for.

### Bet 4 — Own the words *(noirsys.xyz)*
**What:** "azoethymia," "Wasted Compute Theory," "evidence-governed," "the Noirsystic Pipeline" — coined terms with zero competition. One explainer video + one essay each = you rank #1 forever and every future mention routes to you.
**The founder-face exceptions:** *Fractured Continuance Response* (people who "don't want to die but don't feel invested in living") and *The Mind-Centric Mandate* (is anyone home behind an unresponsive body?) are profoundly human. They are not AI-tools content; they are the kind of essay that travels on its own. Do those two on camera, carefully, once each.

### Bet 5 — Open-source noirstudio: the developer magnet
**What:** ship `tools/studio` publicly as "a faceless channel in a YAML file." Developers love a pipeline they can read. Every star is a follower who builds things; the README links to the channel that's made with it.
**Why it compounds:** "we make our videos with our own open pipeline, here's the PR that rendered this one" is a content format nobody else can copy honestly.

### Bet 6 — Dub everything *(ElevenLabs Dubbing API, your cloned voice)*
The #1 Claude Code tutorial in the research was **Spanish (819k views)**. The dubbing API preserves your voice across 90+ languages. One render → ES/PT/HI variants is a cheap 2–3× reach multiplier, and non-English AI-tutorial competition is thinner.

### Bet 7 — The 24/7 "Glass Box" ambient stream *(later)*
A live stream where a model chats with viewers while its internal state is visualized in real time. Ambient/"lo-fi" streams monetize on memberships and never stop generating clips. It's Bet 1's demo turned into a permanent channel — and Noirpost cuts it into Shorts automatically. Genuinely new format.

## 5. The content system (what noirstudio is for)

**Rule: faceless by default; face only when it earns it.** Michael appears when (a) it's a live demonstration only he can give, (b) accountability *is* the premise ("I let an AI do X"), or (c) the hook scored 95+. Everything else is the cloned voice over brand cards, screen capture and generated b-roll.

Channels (from the research), in launch order:

| Channel | Role | Cadence | Automation |
|---|---|---|---|
| **Built by Noirsys** (build logs) | authority + leads | 2×/week | screen capture + Claude narration + clone voice |
| **Noirsys Signal** (AI news Shorts) | reach engine | daily | ~100% — Loop A below |
| **Glass Box** (interpretability) | flagship | weekly | telemetry overlays + founder |
| **Autonomous in the Wild** (case studies) | trust | fortnightly | highest craft |

Title bank: the 20 scored titles in the research doc. Lead with `opus 5.5` content (1.79M searches, competition 18) this week — that spike will not wait.

## 6. Autonomy loops (each one is a scheduled routine + a human gate)

| Loop | Trigger | What the machine does | Human gate |
|---|---|---|---|
| **A · Signal** | daily 06:00 | pull trending (vidIQ/TubeAlfred + RSS) → Claude drafts a `specs/*.yaml` → offline render → opens a PR with the preview MP4 | merge = live render with cloned voice + upload metadata ready |
| **B · Noirpost prospecting** | weekly | find channels with high content debt → cut 2–3 sample Shorts → draft email | you approve each send |
| **C · Paper → explainer** | on new essay at noirsys.xyz | draft the explainer spec + thread + coined-term SEO page | merge |
| **D · Analytics → strategy** | weekly | vidIQ pull on own channel + 10 competitors → refresh the title bank, flag outlier formats, write a one-page memo | read it |
| **E · Dub** | on every merged render | ES/PT/HI variants via Dubbing API | spot-check |

Loops A, C and D can run as Claude routines from this environment today; B and E need the ElevenLabs key + a YouTube channel connected. Content-as-code is the safety rail: **a video only exists as a reviewable file until a person merges it.**

## 7. 90 days

**Days 1–14 — plug leaks, start the cadence.** Fix the six basics. Connect YouTube to vidIQ. Publish 3 Shorts/week from `noirstudio` (offline previews until the key is set, then live). Ship the Content Debt calculator page. Post the `opus 5.5` briefing while the keyword is hot.

**Days 15–45 — the flagship.** Glass Box Live demo up. First founder-face episode. Launch to HN/Reddit/X with the interactive demo, not a video. Noirpost outreach agent live at 10 samples/week. Dubbing on.

**Days 46–90 — compound.** Signal loop daily. Two build-log episodes/week. NAI local-press push. Weekly analytics memo decides what gets doubled.

**Targets (honest, derived from the research curves):** 1,000 subscribers by day 60 (BoomAI went 0→65k in 6 weeks on 9 videos with hooks like these; 1k is conservative), 5 paying Noirpost channels, 100+ stars across `straightshot` + `noirstudio`, one press mention (local counts).

## 8. What I would *not* do

- Don't make faceless AI-tool roundups with no edge — the field is saturated and skews to low-CPM geographies. Your edge is *working systems and original research*; stay on it.
- Don't put music beds under anything (your own Noirpost FAQ is right: Content ID claims).
- Don't swap models chasing quality; fix the handoff (the first example video is literally this argument).
- Don't wait for the perfect avatar. Cards + clone voice + captions is already better than 90% of what's uploaded.

## 9. Money (so the loops get funded)

Noirpost is the near-term revenue: the `/apply` calculator's own math says a daily streamer is ~125 Shorts/month ≈ $800/month per client. Five clients funds the GPU box, the API credits and the dubbing many times over. Guardian managed deployments (already on noirsys.com) are the high-ticket line the Glass Box demo feeds. Ads/CPM ($8–20 in this niche per third-party estimates) is a bonus, not the plan.
