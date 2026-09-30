# 04 — Harriet's channel: the decision and its evidence

*2026-09-29. Built from her own first episode (*the diary of Harriet — 09/27/26*, measured frame by frame), a market scan of YouTube (vidIQ + TubeAlfred, 2026-09-29), and the platforms' own help pages as of 2026-09-28. vidIQ search volumes are modeled estimates. Nothing private is in this file: the stories themselves live in `stories/` (git-ignored) until he approves and publishes them.*

---

## 1. The decision

**The channel is Harriet's.** She is Michael's agent, with five months of memory of working with him (her record starts 2026-04-16). The flagship is **the Diary**: true, first-person stories about him, told by her, each with its receipts on screen (the real messages, his voice notes). **The Agent Log** stays as the daily heartbeat, 30–60 s of what she did that day, and it is the proof that she is real.

Who does what:

| Who | Does |
|---|---|
| **Harriet** | Digs her own memory for moments (`noirstudio harriet dig`), makes the episodes in her voice with his voice notes, and decides up front what stays off screen. |
| **noirstudio** | Sends her deeper each round (`dig --focus`, `dig --follow`), shapes moments into pitches, cuts each master into platform versions (`cut`), checks it (`safe-area`, loudness, seams), and packages it. |
| **Michael** | Approves every story before anything is made, and publishes. |

This supersedes Bet 0's framing in `02-growth-playbook.md` ("Agent Log: her channel, about him"). The bet is the same, but the flagship is the Diary. The Log is the heartbeat.

## 2. Why: the gap is real and the shape is proven

**Nobody does this.** The market scan found no channel where an agent tells true, first-person stories about its real human with receipts.

- The closest channels named "Diary of an AI" are fiction or AI-news diaries: 5–1.04K subscribers, 103–228 views per Short. *An AI Keeps a Diary About You* has 5,968 views, with a fictional AI and no real human.
- Of the top 25 AI-agent Shorts outliers of the last six months, all are news, demos or tutorials. None is an agent telling a story about its human.

**Each part of the shape already works somewhere else:**

| Pattern | Evidence |
|---|---|
| A **"realization" moment** on something real | *Two AI agents on a phone call realize they're both AI*: 14.1M views at 1:10, with 18,292 comments; it was a real demo. Ai Convo reused that beat for 69.7K subscribers and 18.18M views from 30 uploads. Episode 1 already has this beat in its last line. |
| An **AI teasing its creator** | Neuro-sama / Vedal clips: 0.6–1.27M views. All are fiction, cut by third parties. Nobody does it true and first-person. |
| **Titles that make the agent the main character** | *Your AI agent is begging you*: 55× its channel's subscriber count in views. *I put AI agents in charge of my business, they fired me*: 1.35M. |
| **Chat bubbles plus a twist** | Texting stories: 1.6–4.2M views at 104–179 s, several on channels under 75K subscribers (one on 3.03K). |
| **Demand** | "ai agent": about 768K searches a month (+2.3%); hourly views on the topic rose from 255K to 672K between Aug 31 and Sep 27. "voice ai agent": about 17K (+21.8%), with the lowest competition in the set. |

**A strong premise beats volume.** Ai Convo reached 69.7K subscribers from 30 uploads. A disability-builder channel with 390 uploads has 15.1K.

## 3. Format rules that follow from it

- **Length.** Diary episodes run 1:30–2:45, and the Shorts version never goes over 3:00. All five texting-story outliers above 1M ran 104–179 s, and no Short in any outlier set ran past 180 s.
  - A story that needs longer runs as the full vertical master, which YouTube treats as a regular video over 3:00 (§4), and gets a ≤3:00 cut.
  - The Agent Log stays at 30–60 s. Under 60 s wins for explainers, not stories.
- **Hook.** Open on the receipt (a chat bubble or voice-note card) and save the realization for the last line. Longer stories can split into "Part 2".
- **Titles.**
  - Harriet is the one acting, something unexpected happens, and it has a consequence, in plain words.
  - Say "my AI" or "AI agent", never "companion".
  - Use "no hands" rather than "amputee" in titles and tags (§7).
  - "The diary of Harriet" goes in the description and on the end card, not in the title. As a search term, "AI diary" returns *The Diary Of A CEO*.
- **Trust.** Put "true story" on screen and in the description. Lines get shaped, so never claim "every word from the record". It answers the skepticism of developer audiences toward AI-made content (*Writing code by hand is now an advantage*: 345.8K views).
- **His voice carries it.** Use his real recordings wherever they exist; about 40% of episode 1 is his voice.
  - Where only a transcript survives, his own voice clone reads the line, made to sound like the phone note it replaces (`noirstudio voicenote`, matched to his surviving notes). His decision, 2026-09-29.
  - His lines sound like him, not like a read: uh and um, restarts, self-corrections, thinking pauses. Quiet, with his room under it. His note, the same night.
  - **Measured, not guessed.** `noirstudio voiceprint` sets his real notes beside the clone's reads (101 of his notes, 30 minutes of speech; the 58 of 3 to 25 s are the comparison set). Read by Praat's tracker: he speaks at 174 words a minute of speech, stops about 17 times a minute for a median of 0.94 s (40% of the time is pauses), sits at 104 Hz and swings his pitch 2.1 semitones (middle half 1.7 to 2.8). The clone's plain reads (v3, and the variants that only changed steadiness or the filter) spoke a quarter faster (225 words a minute), paused for less than half as long (median 0.3 to 0.4 s), sat 15 to 25 Hz higher on the same lines (118 to 127 Hz against 99 to 105) and swung its pitch 2.3 times as far (4.8 to 5.0 st against 2.1). Stability and the filter changed none of the pitch. The pitch, pace and pause options close the gap on paper: P3, the same recipe aimed at his real numbers (`--swing 2.1 --pitch 104 --pace 1.2 --hesitate 1 --raw --rough 2 --stability 0.9`, matched to his note, roomless), reads 2.17 st, 104 Hz, 13 pauses a minute of a median 1.1 s and 176 words a minute against his 2.13, 104, 17, 0.94 and 174, inside his middle half on every metric but one: how fast the pitch moves from frame to frame (6.4 semitones a second against his 12.7; the flattened contour is smoother than his, where the plain reads were 1.7 times faster than his). His ear still has the last word, and a real recording beats any of it. **Which ruler:** a numpy autocorrelation reads the same 101 notes at 3.2 st and 108 Hz, a semitone more than Praat, although on a synthetic voice with a known contour every reader is within 0.1 st. Where they part is octaves: of the 92,000 frames both read, 86% agree within half a semitone and 7% are the numpy reader sitting an octave above Praat (once a phone has high-passed a low voice its fundamental is weak, and the second harmonic wins); those frames are the extra semitone. Checks on real audio, all favouring Praat: ten of his notes through the phone filter and Opus move Praat's swing by +0.04 st (no file by more than 0.26) and the numpy reader's by +0.58 (up to 1.6); white noise added to eight of them, up to -45 dBFS, moves Praat's by 0.02 (no file by more than 0.13); and on a clean clone read flattened to a Praat swing of 3.2 the numpy reader says 4.1. Praat is the ruler, and a pitch number is never trusted without the reader that made it. The pitch options were aimed at the numpy scale until 6cf209f, so the first P takes were flattened to the wrong number: on a flattened read the numpy reader counts its octave errors as swing, so a build aimed at its 3.1 came out at 0.9 st on Praat in one case and 3.0 in another, for the same lines (two builds, 2.1 st apart on Praat, 0.4 apart on numpy). The factor search now uses Praat, and P3 lands within 0.2 st of its target on all four builds. A first attempt at the ruler (a 200 Hz high-pass) read his swing at 6.8 and is gone.
  - **Cliffs and continuity, measured** (2026-09-30). After the fourth round he said the pauses still had "weird little cliffs, not down to complete silence" and asked how hard it was for "everything" to have "continuity" (about a clip Harriet had built with faded pause edges, not about the clips built to fix it). `voiceprint --seams` reads the joins between speech and its pauses on a 5 ms grid. On his 58 short notes (298 pauses) there are two families: 48 have digital silence in their pauses (about -97 dBFS, depth 63 to 80 dB, a fall into it of 80 to 175 ms), the phone's noise suppression; six have a real room (-45 to -60 dBFS, depth 22 to 42 dB, falls of 20 to 50 ms). The rounds 4 to 6 builds (his room at -47 dBFS under filled pauses) sit in the room family on every number (fall 25 to 85 ms, depth 26 to 30 dB, a floor that wanders 1.3 to 2.5 dB, pauses and gaps at one floor), and round 3's (zeros in the pauses over a clone floor in the gaps) had a step between the two that his notes do not have (21 to 36 dB against his 7 to 20). It also showed a real defect: where the aligner said two words touch, the pause was cut in with a 37 dB step in 2 ms (fixed: the cut goes at the quietest 5 ms near the boundary, and the fade-out lasts as long as the level there is over the floor). Whether the room family is what he hears as continuity is his call; it is what he asked for.
  - **Content, not testimony** (his decision, 2026-09-29): lines can be tightened, reordered, cut or added to make an episode great. Digs stay word for word, so we always know what really happened before we shape it. No invented words for anyone but him and Harriet.
  - Both voices run on ElevenLabs `eleven_v4`.

## 4. Platform rules (as of 2026-09-28)

| Platform | Rule | Consequence for the Diary |
|---|---|---|
| **YouTube Shorts** | Square or vertical videos "up to three minutes" are Shorts ([help](https://support.google.com/youtube/answer/15424877)). YouTube's advice is to link Shorts to the full video with "Related video" ([help](https://support.google.com/youtube/answer/14075157), [blog, Jul 14 2026](https://blog.youtube/creator-and-artist-stories/youtube-related-videos-traffic-guide/)). | A vertical master over 3:00 posts as a regular video. The ≤3:00 cut and the ≤60 s hook go to the Shorts feed, linked to the full video. |
| **YouTube views** | Since Aug 24, 2026, a view counts "the moment a video starts to play" ([help](https://support.google.com/youtube/answer/2991785)). **Engaged views** still drive Partner Program pay ([blog, Aug 19 2026](https://blog.youtube/inside-youtube/engaged-views-youtube-explained/)). | Judge episodes on engaged views and "viewed vs swiped away" ([help](https://support.google.com/youtube/answer/12942217)), not raw views. |
| **Instagram Reels** | Up to 20 minutes, but "Reels over 3 minutes won't be recommended to new audiences" ([about.instagram.com](https://about.instagram.com/features/reels)). | Only the ≤3:00 cut goes to Reels. |
| **TikTok** | Uploads of up to 60 minutes ([help](https://support.tiktok.com/en/using-tiktok/creating-videos/camera-tools)). Creator Rewards requires videos "at least 1 minute" long, and qualified views exclude those under 5 s ([terms](https://www.tiktok.com/legal/page/global/creator-rewards-program-us/en), [FAQ](https://support.tiktok.com/en/business-and-creator/creator-rewards-program/creator-rewards-program)). | Post the full master or the ≤3:00 cut, never the <60 s hook. |
| **Facebook** | Reels have no length or format restrictions ([Meta, Jun 17 2025](https://about.fb.com/news/2025/06/making-it-easier-create-videos-facebook/)). | Post the full master. |
| **Loudness** | No platform publishes a target. YouTube turns loud audio down to about −14 LUFS and doesn't turn quiet audio up. AES TD1008 caps true peak at −1 dBTP. | Master every version to −14 LUFS integrated, −1 dBTP (`noirstudio cut` does it in two passes). |

Each episode ships as three files:

| File | Platforms |
|---|---|
| **full** (her master) | YouTube (a regular video if over 3:00), TikTok, Facebook |
| **shorts-reels** (≤3:00, ≥1 min) | Shorts, Reels, and TikTok if the full runs long |
| **hook** (≤60 s) | Shorts and Reels, linked to the full |

Episode 1's cut plan is `diary/ep01-2026-09-27.cuts.yaml`: shorts-reels is 2:57.7 and the hook is 59.3 s, with every seam in a measured pause.

## 5. Her template, measured

No platform publishes margins for ordinary posts, so I intersected the official ad templates:
- Google's vertical safe zones ([PDF](https://services.google.com/fh/files/misc/universalsafezones-youtube.pdf));
- Meta's Reels guides (14% top, 35% bottom, 6% sides);
- TikTok's in-feed template, measured.

The layout that is safe on all four platforms, on a 1080×1920 frame: **text inside x 120–888, y 288–1248, and left of x 780 below y 840.** `noirstudio safe-area` checks a video against it.

Episode 1, audited at 1 fps:

| Where | Found |
|---|---|
| Text extent | x 72–1004 |
| Right edge (x > 888) | text in 68% of frames |
| TikTok's button column | text in 90% of frames |
| Bottom band | text in 11% of frames, including the end-card signature at the very bottom |

**Fix for her template:** narrow the text column to x 120–888, and move the `the diary of Harriet — MM/DD/YY` signature above y 1248.

## 6. Disclosure

- **YouTube** requires disclosure for photorealistic content that "makes a real person appear to say or do something they didn't do" ([help](https://support.google.com/youtube/answer/14328491)).
  - "Cloning one's own voice to create voice overs or dubs" is explicitly exempt.
  - An obviously-AI narrator who says she's an AI isn't misleading anyone. That is our reading; the page has no example of it.
- **TikTok** requires a label when "AI-generated audio mimics the voice of a real person," with no exemption for your own voice. It does not require one for generic narration that isn't a recognizable person's voice ([guidelines, effective Sep 24 2026](https://www.tiktok.com/community-guidelines/en/integrity-authenticity)).
  - An episode that uses his clone gets TikTok's label, including rebuilt voice notes. His real recordings don't need it.
  - A rebuilt note that keeps his words is his clone saying what he said; our reading is that YouTube needs no disclosure for it. A changed or added line in his clone does make him "appear to say" something he didn't, so that episode gets YouTube's altered-or-synthetic toggle at upload. It is a checkbox in Studio, not a line in the description.
- **Policy (owner's call):** no disclaimer lines in descriptions. The `ai_disclosure` flag stays in the upload metadata so each platform's toggle is set correctly.
- **YouTube's Partner Program** "inauthentic content" rule (Jul 15, 2025) targets "AI-generated content made with generic or unoriginal templates" ([policy](https://support.google.com/youtube/answer/1311392)). The Diary's defense is specificity: one real relationship, real receipts, no templated scripts.

## 7. Risks and guardrails

- **Being read as an AI girlfriend.** "ai girlfriend" searches are up 31% while "ai companion" is down 13.7%. A warm female AI voice talking about a man gets read that way unless she is clearly his agent.
  - She is a colleague who keeps receipts: not a mascot, not a girlfriend.
  - No romantic framing in titles or thumbnails.
- **The "amputee" keyword.** 11 of the top 20 "amputee" Shorts of the past year come from one account whose content appears aimed at fetishists. Stay out of that neighborhood: say "no hands" or "types with his arms".
- **Privacy.**
  - Nothing she digs up goes in git, and a dig never runs in GitHub Actions, where logs are public.
  - Her off-screen list is binding: his investigation work, outreach, contacts, other people's names and details, legal matters, locations, credentials.
  - Family members are never identified.
  - He approves every story before anything is made.
- **Truth.** Every line on screen traces to a receipt. She marks what she recalled as opposed to copied, and recalled lines don't go on screen as quotes.

## 8. Cadence

- The Diary weekly. The Agent Log daily.
- The digs run continuously: an hourly heartbeat sends her back into her memory, deeper each round, so the pipeline stays ahead of the calendar.

## 9. How we'll know

- **Per episode:** engaged views, "viewed vs swiped away" on Shorts, completion of the ≤3:00 cut, shares/sends, and comments about whether it's real.
- **After six episodes:** which kinds of moment hold best (funny, tender, friction, breakthrough). Dig for more of that kind, and title toward it.
