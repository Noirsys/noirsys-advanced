# 03 — Noirpost prospect list (data-backed) — 2026-09-28

Prospects for [Noirpost](https://noirpost.live): turns a streamer's livestream VOD into 20-30 finished vertical Shorts by the next day (first batch free, then ~$6-8/Short). Target profile: English-language channels, 10k-200k subscribers, that go live for hours at least 2x/week and post few Shorts (<= 5 in the last 30 days).

Every figure below comes from a tool result (vidIQ `vidiq_channel_search`, TubeAlfred `youtube_channel_videos` / `youtube_channel_streams` / `youtube_channel_shorts`) or is arithmetic on those results. Nothing was sent to anyone.

## 1. Method and budget actually spent

**Budget used (hard caps were 3 vidIQ calls / 25 TubeAlfred calls):**

| Tool | Calls | Credits | Balance before -> after |
|---|---|---|---|
| vidIQ `vidiq_balance` (free) | 1 | 0 | - |
| vidIQ `vidiq_channel_search` (discovery) | **3** | **15** | 40 -> 25 |
| TubeAlfred `youtube_search_query` | 1 | 1 | 46 -> 45 (returned empty: the `live` filter only matches currently-live streams) |
| TubeAlfred `youtube_channel_videos` (Uploads tab, 30 items/page) | 15 | 15 | |
| TubeAlfred `youtube_channel_streams` (Live tab) | 3 | 3 | |
| TubeAlfred `youtube_channel_shorts` (Shorts tab) | 6 | 6 | |
| **TubeAlfred total** | **25** | **25** | 46 -> 21 |

**Discovery (vidIQ, 3 calls, 90 result rows, ~55 unique channels).** Each call used the same structured pre-screen: subscribers 10,000-200,000; language `en`; trailing-30-day long-form average length >= 3,600 s (>= 3,000 s for the podcast query); >= 8 long-form uploads in the trailing 30 days (>= 2x/week); <= 5 Shorts in the trailing 30 days; last upload on/after 2026-09-21. Semantic queries: (1) "live coding programming stream software developer", (2) "live video podcast talk show interviews streamed live", (3) "live stream cooking workshop maker woodworking electronics repair 3D printing product demo teardown". Query 1 returned mostly Twitch-VOD archive channels; query 3 returned very few genuine live makers (see Flags), so the ranked list is gaming-heavy with podcast, talk-show and live-coding entries for diversity.

**Per-channel measurement (TubeAlfred).** 13 of the 15 measured channels are Twitch-VOD archives that upload full streams as ordinary videos, so their YouTube *Live* tab is empty or stale (checked on 3 channels: The Jeff Gerstmann Show's Live tab has 4 old streams, AngryJoeShow Live's is empty, CinemaZeeVT's shows only 2022 streams). Stream hours were therefore measured from the **Uploads tab** (`youtube_channel_videos`, first page = 30 most recent uploads with `length_seconds` and a `published_time`).

**Window actually measured.** TubeAlfred derives `published_time` from YouTube's relative labels ("2 weeks ago" -> 2026-09-14, "3 weeks ago" -> 2026-09-07, "4 weeks ago" -> 2026-08-31, "1 month ago" -> 2026-08-28). I counted items dated **>= 2026-08-29** ("4 weeks ago" and newer) and excluded "1 month ago" and older. Because of label granularity the window is approximately the last **28-34 days**, ending 2026-09-28. For two channels (Baalorlord Unedited, GrandPooBear VODs) all 30 items on the page fell inside the window, so their totals are **lower bounds** (marked "partial"). Uploads shorter than 30 minutes and titles starting "Review:" were excluded as edited, non-stream uploads (4 exclusions in total; listed in the table notes).

**Shorts.** `shorts_30d` is vidIQ's trailing-30-day Shorts count (0 for every ranked channel). The TubeAlfred Shorts tab was pulled for 6 channels: LilAggy VODs, Baalorlord Unedited and sphaerophoria have **no Shorts at all**; Dr. Kavi Simpson (48+ Shorts listed), PearlescentMoonies (8) and GrandPooBear VODs (5) have Shorts histories, but the Shorts tab carries no dates, so their 30-day figure rests on vidIQ (0 in each case; vidIQ's index was current to 2026-09-26).

**Formulas (Noirpost's stated planning figures):**

- `hours_30d` = sum of qualifying upload lengths in the window / 3600
- `moments` = hours_30d x 5 (about five clippable moments per streamed hour)
- `content_debt` = moments - shorts_30d
- `views_floor` = content_debt x 1,000 (floor of the 1,000-3,000 views/Short planning range)
- indicative revenue to Noirpost if they clipped everything ~ content_debt x $6.40 (indicative only; a per-VOD delivery of 20-30 Shorts gives a different number)

**Worked example (LilAggy VODs):** 21 qualifying uploads dated 2026-08-31..2026-09-27 sum to 319,085 s = 319,085 / 3600 = **88.63 h**; moments = 88.63 x 5 = **443.2**; shorts_30d = 0 (Shorts tab empty); content_debt = 443.2 - 0 = **443** (443.17 unrounded); views_floor = 443.17 x 1,000 = **443,174**; indicative revenue = 443.17 x $6.40 = **$2,836/month**. All table values are computed from unrounded hours and then rounded for display, which is why views_floor is not exactly content_debt x 1,000 in the table.

## 2. Ranked prospects (15 measured channels, sorted by content_debt)

Totals across the 15: **829 streamed hours** and **4,144 un-clipped moments** in roughly one month.

| # | Channel | Country | Subs | Uploads counted (streams_30d) | hours_30d | moments (x5) | shorts_30d | content_debt | views_floor | Indicative $/mo (x$6.40) | Category | Measured window | Outreach hook |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | [39daph vods](https://www.youtube.com/channel/UCOBXQF0RKsxYIBNRxI4kPSg) | CA | 199,000 | 23 | 109.6 | 548 | 0 | **548** | 547,776 | $3,506 | Gameplay + art streams, Twitch VOD archive | 2026-08-31..2026-09-24 | Your 11 h 16 m VOD "39daph Plays Marvel's Wolverine" (Sep 23) alone holds ~55 clippable moments by our count, and the VOD channel has posted no Shorts in the past year (vidIQ). |
| 2 | [Baalorlord Unedited](https://www.youtube.com/channel/UCOBCFrVoBoHBH7wojml0i0w) | n/a | 13,300 | 30 | 102.2 | 511 | 0 | **511** | 511,158 | $3,271 | Gameplay (Slay the Spire 2, roguelikes), daily show VODs | 2026-08-31..2026-09-28 (partial) | "[Show #1970]" (the XCOM Baalor Edition run) went up today; you publish a 5-6 h show five days a week and the unedited channel's Shorts tab is empty. |
| 3 | [LilAggy VODs](https://www.youtube.com/channel/UCthaRPvF9aViVlsPkBHtytw) | US | 127,000 | 21 | 88.6 | 443 | 0 | **443** | 443,174 | $2,836 | Gameplay (Soulslike/randomizers), Twitch VOD archive | 2026-08-31..2026-09-27 | Seven "Mortal Shell 2" VODs in eight days (Sep 19-27), 4-6 h each, and not one boss kill exists as a vertical clip (Shorts tab empty). |
| 4 | [BarryWasStreaming](https://www.youtube.com/channel/UCuFu-BTHzzfr2Dg3d1W_w2w) | US | 44,600 | 14 | 79.0 | 395 | 0 | **395** | 395,007 | $2,528 | Gameplay (variety/retro), Twitch VOD archive | 2026-08-31..2026-09-25 | "NORMAL GOLF GAME" (Sep 25) ran 6 h 22 m, roughly 30 Shorts' worth of material sitting in a single archive upload. |
| 5 | [SimpleClips: Full Streams](https://www.youtube.com/channel/UCydmoF3pPpijDuFMvTaQIZw) | US | 43,400 | 24 | 77.0 | 385 | 0 | **385** | 385,015 | $2,464 | Gameplay (Mario/randomizers/events), full-stream archive | 2026-08-31..2026-09-27 | "This Cow has a Special Secret in the Ocarina of Time Randomizer" (Sep 27) is 8 h 30 m; the archive channel has no Shorts in the past year (vidIQ). |
| 6 | [GrandPooBear VODs](https://www.youtube.com/channel/UCxL43jo_2d5TVp4wbE_qVbA) | US | 23,800 | 30 | 73.0 | 365 | 0 | **365** | 365,040 | $2,336 | Gameplay (speedrun/kaizo/randomizers), VODs split by subject | 2026-09-07..2026-09-27 (partial) | Kaizo Colosseum 2026 produced four VODs in two days (Sep 26-27, e.g. "We Held a Mario Maker Pros vs Joes Match!"); none of it exists in vertical yet. |
| 7 | [QuarterJade Vods](https://www.youtube.com/channel/UCQM2QW4byyVQr-VyIvW6STA) | US | 35,000 | 14 | 61.9 | 309 | 0 | **309** | 309,379 | $1,980 | Gameplay (Minecraft SMP/variety), official VOD channel | 2026-08-31..2026-09-22 | "My first time in the Aether! \| Minecraft OTV Day 14" (Sep 22) closes a 14-day series of 2.5-9 h VODs with zero Shorts on the VOD channel. |
| 8 | [SnapCube 2](https://www.youtube.com/channel/UCCHruaQlOKPHTl8iOPGDjFg) | US | 196,000 | 9 | 47.9 | 239 | 0 | **239** | 239,338 | $1,532 | Gameplay/let's-play streams (Zelda, Deltarune) | 2026-09-07..2026-09-26 | Twilight Princess parts 1-7 in three weeks (latest "A Playground for Adults!", 6 h 09 m) and no Shorts in the past year (vidIQ). |
| 9 | [fruit salad: grayfruit full streams](https://www.youtube.com/channel/UCYFnrEm7NpDx553KEHyK4iQ) | US | 60,500 | 14 | 39.2 | 196 | 0 | **196** | 196,114 | $1,255 | Gameplay/let's-play full streams (retro, Ace Attorney) | 2026-08-31..2026-09-28 | Every recent title starts with "[Full stream]" (latest "Sillybandz Play the CRAZE", Sep 28); nothing uploaded in the last 30 days is under 40 minutes. |
| 10 | [PearlescentMoonies](https://www.youtube.com/channel/UCs5DKTSS7QqYCzKyQU0pR3w) | n/a | 39,400 | 10 | 36.1 | 180 | 0 | **180** | 180,435 | $1,155 | Gameplay (Hermitcraft/Minecraft), Twitch stream archive | 2026-08-31..2026-09-27 | "Slay The Spire 2 MULTIPLAYER With Ren!" (4 h 42 m, Sep 27); the channel has 8 Shorts in total and none in the last 30 days (vidIQ). |
| 11 | [The Jeff Gerstmann Show](https://www.youtube.com/channel/UCR9R2ARN74dCebn1kv06UhA) | US | 50,500 | 12 | 31.1 | 156 | 0 | **156** | 155,711 | $997 | Video-game podcast (weekly 3 h show) + retro-gaming episodes | 2026-08-31..2026-09-26 | "The Jeff Gerstmann Show 224" (2 h 55 m) and the 3 h retro "Episode 014" landed the same week; the channel has no Shorts in the past year (vidIQ). |
| 12 | [sphaerophoria](https://www.youtube.com/channel/UCXzL31BCxf8En1KT34gSK6g) | n/a | 33,500 | 12 | 25.1 | 125 | 0 | **125** | 125,258 | $802 | Live coding (Zig/C, graphics, tooling) | 2026-08-31..2026-09-26 | "Fixing claude's deranged dota replay format" (2 h 50 m) is the kind of debugging session that yields 30-60 s payoffs; the channel's Shorts tab is empty. |
| 13 | [Nextlander](https://www.youtube.com/channel/UCO0gHyqLNeIrCAjwlO2BmiA) | US | 48,400 | 10 | 23.2 | 116 | 0 | **116** | 116,049 | $743 | Video-game podcast crew: scheduled multi-host streams | 2026-08-31..2026-09-26 | A fixed schedule ("Monday Multiplayer Madness: Valheim (Part 02)", "Friday Fun Stream") means a predictable weekly batch; no Shorts in the past year (vidIQ). |
| 14 | [MrAtomicDuck VODs](https://www.youtube.com/channel/UCCi92mBmKj-PZ31gUAppIXA) | GB | 24,100 | 9 | 18.3 | 92 | 0 | **92** | 91,747 | $587 | Gameplay (survival/sim), Twitch VOD archive | 2026-08-31..2026-09-26 | "DAY ONE In Valheim 1.0... Gameplay, First Impressions & Nostalgia!" (Sep 23) is launch-week material; next-day Shorts would ride the update's search interest. |
| 15 | [Dr. Kavi Simpson](https://www.youtube.com/channel/UCvvMBnTEooKAL5UhegWiRkQ) | n/a | 11,400 | 11 | 16.6 | 83 | 0 | **83** | 82,993 | $531 | Talk show (live on Kick MWF, VODs on YouTube) | 2026-08-31..2026-09-27 | "The Dr.Kavi Simpson Show EP.63" (Sep 27); the show posts Mon/Wed/Fri and its Shorts output stopped about a month ago while subs grew 52% in 30 days (vidIQ). |

Row notes: **Baalorlord Unedited** — partial: all 30 page items fall inside the window (oldest 2026-08-31), so true 30-day total is >= this; **GrandPooBear VODs** — partial: page covers only 2026-09-07..09-27 (~3 weeks); VODs are split by subject so n > streams; **SnapCube 2** — full window; only 9 uploads (3-11 h each); **The Jeff Gerstmann Show** — 3 edited uploads excluded (2 reviews, one 29:55 item); **Dr. Kavi Simpson** — 1 edited 8:51 clip excluded; live on Kick, VODs uploaded to YouTube; **sphaerophoria** — 5 'Happy hour' items show 0 views (possibly members-only); included; **SimpleClips: Full Streams** — 1 item <30 min excluded.

## 3. Send-first picks (three draft emails)

Chosen for: verified empty Shorts tab, a clear owner or named manager to write to, a predictable weekly schedule, and category spread (two gaming archives, one live-coding channel). 39daph vods and BarryWasStreaming are the next two in line (largest debt, but no named contact path in the tool data).

**Pick 1 — LilAggy VODs** (127k subs, 88.6 h in window, Shorts tab empty)

> **Subject:** Your Mortal Shell 2 VODs, cut into Shorts by tomorrow — first batch free
>
> You've put up seven Mortal Shell 2 streams in the last eight days (4-6 hours each) and the VOD channel has no Shorts, so we'd like to cut the next one into 20-30 finished vertical Shorts and send them back the next day, free, with no card, no call and no channel logins. You own the clips outright; the only paperwork is a one-page rights note to sign, and the only thing we ask is a "cut by Noirpost" line in the description of the Shorts you choose to post. If that's useful, reply with the VOD link you want cut first and we'll start on it.

**Pick 2 — Baalorlord Unedited** (13.3k subs on the VOD channel; channel managed by Niklas Bickel per the About text; >= 102.2 h in window, Shorts tab empty)

> **Subject:** Show #1970 -> 25 Shorts by tomorrow, free, no logins
>
> Show #1970 (the XCOM "Baalor Edition" run) went up this morning, and with five 5-6 hour shows a week plus zero Shorts on the unedited channel, you're sitting on roughly 500 clippable moments a month by our count. We'll take one show VOD and return 20-30 finished vertical Shorts the next day at no cost, with no card, no call and no access to your accounts; you own the clips and sign a one-page rights note, and all we ask is a "cut by Noirpost" line in the description if you post them. Send a link to whichever show you'd like cut first and we'll have it back to you tomorrow.

**Pick 3 — sphaerophoria** (33.5k subs, live coding, 25.1 h in window, Shorts tab empty)

> **Subject:** Your live-coding streams have Shorts in them — first batch is free
>
> Streams like "Fixing claude's deranged dota replay format" are full of 30-60 second moments (the bug found, the fix that finally compiles) and your channel currently has no Shorts, so we'd like to cut one recent VOD into 20-30 finished vertical Shorts and send them back the next day, free. There is no card, no call and no channel logins; you own the clips, you sign a one-page rights note, and the only ask is a "cut by Noirpost" line in the description of any you post. If you want to try it, reply with the VOD link and we'll get started.

## 4. Flags and caveats

**Could not measure (budget or tool limits):**
- AngryJoeShow Live: Live tab empty; its uploads were not fetched (budget). CinemaZeeVT: Live tab returned only 2022 streams; its recent 5-hour "live events" were not located. Both appear only in the appendix with vidIQ figures.
- Baalorlord Unedited and GrandPooBear VODs: first page exhausted inside the window, so hours are lower bounds (a second page would cost 1 call each).
- Shorts tab items are undated, so `shorts_30d` for channels with Shorts history (Dr. Kavi Simpson, PearlescentMoonies, GrandPooBear VODs) is vidIQ's count, not a TubeAlfred count.
- Country is "n/a" where YouTube has no country set (Baalorlord, PearlescentMoonies, sphaerophoria, Dr. Kavi Simpson); language was confirmed as English by vidIQ and by titles.
- Dates are approximate (derived from relative labels), so per-item dates near the window edge can be off by several days; the window is ~28-34 days, not exactly 30.
- Upload counts are not stream counts where creators split VODs (GrandPooBear VODs "separated by subject"; Baalorlord's shorter "Low Budget Spire" segments). Whether The Jeff Gerstmann Show's ~3 h episodes are streamed live or recorded could not be verified from tool data (the channel multistreams per a Feb-2026 Live-tab item).
- Subscriber counts are the VOD/archive channel's, not the creator's main channel. Several creators (39daph, SnapCube, QuarterJade, SimpleFlips, GrandPooBear, PearlescentMoon, LilAggy, Poofesure) have main channels that are probably well above 200k and may already employ editors; the *VOD channel* fits the profile, the creator may not.
- Fan-run or manager-run archives: outreach must go to the streamer or the named manager, not the channel. Fan-run channels were excluded from the ranking (Fake DotoDoya Vods, Krinkels Live). Manager-run but official: Baalorlord Unedited (Niklas Bickel), MOONMOON Vods, Aimsey LIVE, MelinksVODS.
- sphaerophoria's "Happy hour" streams show 0 views in the feed (possibly members-only); they were included in hours because they are 1-3.5 h stream VODs.
- Revenue figures are indicative only, assume every clippable moment becomes a paid Short at $6.40, and ignore the free first batch.

**May already use a clipping service / active Shorts output (excluded or down-weighted):** Katie Nolan (112 Shorts in trailing year), Aimsey LIVE (51/yr), Hass Le Bhai (5 Shorts in 30 days), Xena East (5 in 30 days), KIT'S Auto and Truck Repair (16/yr, 1 in 30 days), Dr. Kavi Simpson (77/yr but 0 in the last 30 days — kept, and the lapse is the pitch), Ashlizzlle (posts edited 1 h VODs, so already edits; 3 Shorts/yr).

**Non-English or mixed-language channels excluded (returned by vidIQ despite the `en` filter):** Marathi Coding Shala (mr/en), VLR Training (te/en), Programming Avec Reza (en/fr, short-form), Tauraruwar Arewa TV (Hausa), Comedy Patrol / HaHa Junction / Comedy King / Hass Le Bhai / Kappu Comedy / Kapil Comedy Darbar (Hindi TV re-uploads), Satria Muda Entertainment (id), byyb radio (zh/en), than_folder (th), PH Live UPDATES (tl), Rinse France (fr), Oriyomi Hamzat Reality Shows (yo), Asabe AfrikaTV (en/yo), EEE IQ (hi), Nong-Lading Official (Filipino live drama).

**Excluded as not-a-streamer, re-upload or aggregator:** ACCU Conference and CppNow (conference talks), Hi Shane Gillis (fan clip archive), Cozy Maple View (re-streams of other influencers), Full Course (course re-uploads), GC The Expert Live Camera Video Maker (traffic cams), Steve Harvey FM and KiSS 92.5 (corporate radio), WOW Teardown (gameplay videos, not live), Mai Anh Mechanical / Chy By repair / Creative HD / Truong Carpenter / Woodworking World (recorded videos; no live streaming evident; country labels questionable), BILLSTMAXX and KIT'S Auto (recorded repair videos; live status not evident). Net effect: the "cooking / workshop / maker / teardown" categories produced **no verified live-streaming prospect** in this pass; a follow-up search should use TubeAlfred `youtube_search_query` with `type=video`, `duration=over_twenty_mins`, `upload_date=month` and queries like "workshop live stream" without the `live` flag.

## Appendix — pre-qualified by vidIQ but not measured with TubeAlfred (not ranked)

These passed the same vidIQ filters. Hours here are **vidIQ-index estimates** (long-form uploads in trailing 30 days x average length), not TubeAlfred measurements, and are not comparable to the ranked table.

| Channel | Country | Subs | long uploads 30d (vidIQ) | avg length (vidIQ) | est. hours_30d (vidIQ: count x avg) | Shorts 30d / 1y (vidIQ) | Note |
|---|---|---|---|---|---|---|---|
| [Hutts 2](https://www.youtube.com/channel/UC2HZ6A_jScWdijaeKWwQTaw) | US | 150,000 | 39 | 84 min | ~55 h | 0 / 0 | Twitch archive (streams Tue/Thu); 39 uploads = stream footage split into parts |
| [LRR Streams](https://www.youtube.com/channel/UCpvugL8Qxc8-aXlO0KUtXXQ) | n/a | 69,400 | 46 | 177 min | ~135 h | 0 / 0 | LoadingReadyRun Twitch archive; established production company (likely has editors) |
| [MOONMOON Vods](https://www.youtube.com/channel/UCLQ1ezqQq_cMzp7Vj3CjwMQ) | US | 15,000 | 65 | 146 min | ~158 h | 0 / 0 | Official archive run by a channel manager; streamer's audience is far larger than the VOD channel |
| [AngryJoeShow Live](https://www.youtube.com/channel/UCbxJk4rCatLG4uCsTE-ChhQ) | US | 89,900 | 17 | 296 min | ~84 h | 0 / 0 | Live tab empty (TubeAlfred); VODs are uploads, not fetched within budget |
| [Aimsey LIVE](https://www.youtube.com/channel/UCZch5b068HaaUAGW6CaU1kA) | n/a | 108,000 | 17 | 118 min | ~33 h | 0 / 51 | Managed archive; 51 Shorts in trailing year -> may already clip |
| [iHasCupquakeLIVE](https://www.youtube.com/channel/UC1ory5ymKEudKTEXxnIZwaw) | US | 66,600 | 8 | 113 min | ~15 h | 0 / 0 | Streams Mon/Wed/Fri on TikTok/Twitch/YouTube; main channel is very large |
| [More Poofesure](https://www.youtube.com/channel/UCBE0Oeljr6SIXhb3mt4xJzg) | US | 31,100 | 8 | 191 min | ~25 h | 0 / 0 | Second channel; main channel much larger |
| [MelinksVODS](https://www.youtube.com/channel/UCJgAOaa-SvToqWLmYbgK69A) | GB | 25,800 | 9 | 161 min | ~24 h | 0 / 0 | Managed VOD channel |
| [Ashlizzlle](https://www.youtube.com/channel/UC9HvNU6-MihLe5JGBkJ3DgQ) | NL | 74,800 | 24 | 62 min | ~25 h | 0 / 3 | Uploads edited ~1 h VODs (already edits); streams 6 days/week on Twitch; full VODs only on Twitch |
| [CinemaZeeVT](https://www.youtube.com/channel/UCuY7g3VCs5jFMFvOSdvxcLw) | US | 28,400 | 9 | 300 min | ~45 h | 0 / 14 | Live tab returned only 2022 streams; recent 5 h 'live events' not located within budget |
| [Daniel Hirsch](https://www.youtube.com/channel/UCOt3Ssxx03pxLdH3qzyTAsQ) | DE | 77,800 | 12 | 61 min | ~12 h | 0 / 3 | Live-coding style videos ~1 h; whether they are live streams is unverified |
| [Katie Nolan (Casuals)](https://www.youtube.com/channel/UCsz2u4jRqnI0caP6hlCkX0g) | n/a | 112,000 | 10 | 125 min | ~21 h | 0 / 112 | 112 Shorts in trailing year -> almost certainly already clipping; excluded from ranking |

---
*Files:* pre-screen data `scratchpad/vidiq_prescreen.csv`, per-channel item lists and arithmetic `scratchpad/streams_30d.py` (session scratchpad). Generated 2026-09-28.
