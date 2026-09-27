# Committee hearings on YouTube: coverage findings

*September 2026. Covers House, Senate and joint committee hearings from the 113th Congress (2013) through the 119th (to date). The numbers come from the weekly matcher (`gpo-match`); the original research-pass snapshot is kept in `hearing_video_verdicts.csv`.*

## Summary

We compared every official hearing transcript that GPO has published since 2013 against the videos on every official committee YouTube channel we could find: 119 channels for 52 committees and commissions, holding 67,244 videos. The matching combines automatic evidence (Congress.gov video links, event IDs and dates in video text, upload-window title similarity) with the reviewed verdicts of a 16-agent research pass and a 6-agent adversarial verification. For the Senate, which hosts its own video, it also checks the Senate's player. It runs every week, so these numbers move as committees upload.

**House and joint committees (9,643 hearings):**

<!-- table:house_summary -->
| Outcome | Hearings | Share |
|---|---|---|
| Full recording on a tracked committee channel | 8,768 | 90.9% |
| Full recording only on another YouTube channel (member, news, third party) | 64 | 0.7% |
| Full recording off YouTube (senate.gov, C-SPAN, an archive) | 217 | 2.3% |
| Only clips or opening statements on YouTube | 227 | 2.4% |
| Never public video (closed session, written-only volume, errata) | 65 | 0.7% |
| No video found | 298 | 3.1% |
| Held before the committee's earliest tracked video | 4 | 0.0% |
<!-- /table:house_summary -->

The gaps are almost entirely historical. **Since the 116th Congress (2019), 99.1% of House and joint hearings have a full recording.** Only 18 hearings since 2019 have no video found; among them are field hearings and Appropriations placeholder records.

**Senate committees (5,835 hearings):**

<!-- table:senate_summary -->
| Outcome | Hearings | Share |
|---|---|---|
| Full recording on a tracked committee channel | 347 | 5.9% |
| Full recording only on another YouTube channel (member, news, third party) | 5 | 0.1% |
| Full recording off YouTube (senate.gov, C-SPAN, an archive) | 5,203 | 89.2% |
| Only clips or opening statements on YouTube | 13 | 0.2% |
| Never public video (closed session, written-only volume, errata) | 49 | 0.8% |
| No video found | 191 | 3.3% |
| Held before the committee's earliest tracked video | 17 | 0.3% |
| Committee has no YouTube channel | 10 | 0.2% |
<!-- /table:senate_summary -->

**Senate hearings are on the Senate's own player, not YouTube.** The Senate Recording Studio hosts committee video at senate.gov and names each recording after the committee and date. Congress.gov links those recordings from Senate meeting records since late 2023 (1,381 links, none to YouTube, while all 7,538 House links go to YouTube). For everything earlier or unlinked, a probe of the player by committee and date found recordings for 4,786 of 5,115 hearings. Senate committees' YouTube channels are party channels carrying members' statements and a selection of hearings; only Environment and Public Works' Democrats have livestreamed hearings there since 2011.

Where older House hearings are missing, the main causes are:
- **They were never uploaded to YouTube.** Before 2015 many committees streamed on Ustream, Windows Media or Facebook, and those recordings are gone or not on YouTube.
- **Committees later made the videos private or deleted them.** This hit Education & Workforce (2013–14) and Veterans' Affairs (mid-2014 to 2015).
- **Only clips were posted.** Homeland Security (2013–15) and Foreign Affairs (April 2014 to August 2015) posted opening statements rather than full hearings.

Most of what looked missing wasn't. Committees bulk-uploaded their archives months or years after the hearings, under titles like "7/23/2013. EMR. 10:00 AM", "Markup: H.R. 2848", "W&M Hearing: Feb 26, 2014", or a date code plus an EventID. The research pass found 1,278 of these; the matcher's event-ID and date rules now find them automatically, and found a further 134 that the research pass had marked as clips only or no video, almost all of them Ways and Means hearings.

What was still missing was then searched off YouTube. Eight agents took the 840 House and joint hearings without a full recording and checked C-SPAN's video library day by day, the Wayback Machine's copies of each committee's hearing pages, and whatever archive those pages pointed to. They found recordings for about a third of them: on C-SPAN, in the Senate's video archive (which records the Helsinki Commission and the Joint Economic Committee), on the Helsinki Commission's Facebook page, on DVIDS, and on the committees' own YouTube channels as unlisted or untitled uploads that no search returns. What they could not find is gone: every committee's own 2013–2015 stream (Ustream, Windows Media, Granicus) is dead, and the Wayback Machine kept the player pages but never the video.

## House and joint coverage by Congress

"Found" is the share with a full recording, on a tracked channel or elsewhere.

<!-- table:house_congress -->
| Congress | Years | Hearings | Full recording | Clips only | Not public | None found | Found |
|---|---|---|---|---|---|---|---|
| 113th | 2013–14 | 1,791 | 1,389 | 168 | 17 | 216 | 77.6% |
| 114th | 2015–16 | 1,716 | 1,587 | 54 | 23 | 50 | 92.5% |
| 115th | 2017–18 | 1,482 | 1,462 | 4 | 2 | 14 | 98.7% |
| 116th | 2019–20 | 1,404 | 1,373 | 1 | 14 | 15 | 97.8% |
| 117th | 2021–22 | 1,163 | 1,158 | 0 | 5 | 0 | 99.6% |
| 118th | 2023–24 | 1,439 | 1,434 | 0 | 2 | 3 | 99.7% |
| 119th | 2025– | 648 | 646 | 0 | 2 | 0 | 99.7% |
<!-- /table:house_congress -->

The 5 hearings held before a committee's earliest tracked video are counted in the totals but not in the other columns.

## House and joint coverage by committee

Sorted from least to most complete. Committees with fewer than 5 GPO hearings are omitted (Intelligence prints few hearings, for example). "Senate Veterans' Affairs" here is six House hearings GPO filed under the Senate committee's code.

<!-- table:house_committee -->
| Committee | Hearings | Full recording | Clips only | Not public | None found | Found | Found since 2019 |
|---|---|---|---|---|---|---|---|
| Select Committee on Benghazi | 15 | 4 | 0 | 11 | 0 | 27% | — |
| (no committee code in GPO data) | 6 | 4 | 0 | 1 | 1 | 67% | 67% of 3 |
| Homeland Security | 533 | 442 | 79 | 1 | 11 | 83% | 100% of 284 |
| Education & Workforce | 390 | 330 | 18 | 10 | 32 | 85% | 100% of 225 |
| Armed Services | 681 | 588 | 22 | 0 | 71 | 86% | 100% of 287 |
| Veterans' Affairs | 456 | 400 | 19 | 2 | 35 | 88% | 100% of 206 |
| Appropriations | 308 | 272 | 0 | 24 | 12 | 88% | 93% of 140 |
| Helsinki Commission | 202 | 180 | 0 | 1 | 21 | 89% | 98% of 90 |
| Transportation and Infrastructure | 428 | 384 | 14 | 0 | 30 | 90% | 100% of 238 |
| Judiciary | 654 | 612 | 12 | 10 | 20 | 94% | 97% of 368 |
| Foreign Affairs | 1,000 | 937 | 51 | 0 | 12 | 94% | 100% of 348 |
| Small Business | 503 | 473 | 1 | 0 | 29 | 94% | 95% of 261 |
| Congressional-Executive Commission on China | 71 | 67 | 0 | 2 | 0 | 94% | 100% of 40 |
| Select Committee on the Climate Crisis | 43 | 42 | 0 | 0 | 0 | 98% | 98% of 43 |
| Natural Resources | 449 | 439 | 2 | 1 | 7 | 98% | 99% of 253 |
| House Administration | 190 | 186 | 0 | 0 | 4 | 98% | 99% of 129 |
| Ways and Means | 269 | 264 | 2 | 0 | 3 | 98% | 100% of 83 |
| Budget | 85 | 84 | 1 | 0 | 0 | 99% | 100% of 60 |
| Oversight and Government Reform | 911 | 901 | 4 | 0 | 6 | 99% | 100% of 466 |
| Agriculture | 221 | 219 | 0 | 1 | 1 | 99% | 100% of 120 |
| Financial Services | 731 | 727 | 1 | 0 | 3 | 99% | 100% of 394 |
| Science,Space,and Technology | 474 | 473 | 1 | 0 | 0 | 100% | 100% of 210 |
| Energy & Commerce | 869 | 868 | 0 | 1 | 0 | 100% | 100% of 325 |
| Joint Economic Committee | 96 | 96 | 0 | 0 | 0 | 100% | 100% of 32 |
| Rules | 18 | 18 | 0 | 0 | 0 | 100% | 100% of 16 |
| Select Committee on the January 6th Attack | 10 | 10 | 0 | 0 | 0 | 100% | 100% of 10 |
| Select Committee on the Modernization of Congress | 21 | 21 | 0 | 0 | 0 | 100% | 100% of 21 |
| Senate Veterans' Affairs (House hearings, miscoded) | 6 | 6 | 0 | 0 | 0 | 100% | 100% of 1 |
<!-- /table:house_committee -->

Notes:
- **Benghazi:** 11 of its 15 GPO volumes are closed-door transcribed witness interviews, so there is no public video to find.
- **Helsinki Commission:** most of its 2013–2019 GPO "hearings" are staff briefings. Its website embeds recordings of 31 of them from the Commission's Facebook page, not YouTube.
- **Appropriations:** the "not public" rows are printed volumes that contain only written testimony, budget justifications or answers for the record.
- **Clips only** now means what it says. A video found by weak evidence (a date window or a date in the title) counts as a clip when it's under 20 minutes, or under 30 with a member-clip title ("Q&A", "Questions", "Opening Statement"). The research-pass snapshot counted some of those as recordings, which is why Homeland Security, Foreign Affairs and the Joint Economic Committee show more clips here.

## Senate coverage

The Senate numbers cover 16 committees with 32 YouTube channels, found by checking each committee's website and searching YouTube for the committee, its party caucuses and its chairs since 2007 (notes in `research/data/senate_channels.csv`), plus the Senate's own player. "On senate.gov" counts recordings found there, through Congress.gov's links or the archive probe (`research/scripts/as_run/senate_isvp_probe.py`); "Full recording" includes them.

<!-- table:senate_congress -->
| Congress | Years | Hearings | Full recording | Clips only | Not public | None found | On senate.gov | Before channel | No channel | Found |
|---|---|---|---|---|---|---|---|---|---|---|
| 113th | 2013–14 | 987 | 938 | 3 | 2 | 28 | 930 | 16 | 0 | 95.0% |
| 114th | 2015–16 | 1,010 | 926 | 4 | 16 | 62 | 918 | 0 | 2 | 91.7% |
| 115th | 2017–18 | 960 | 907 | 3 | 6 | 39 | 903 | 0 | 5 | 94.5% |
| 116th | 2019–20 | 696 | 664 | 3 | 5 | 24 | 652 | 0 | 0 | 95.4% |
| 117th | 2021–22 | 1,051 | 1,010 | 0 | 17 | 22 | 922 | 0 | 2 | 96.1% |
| 118th | 2023–24 | 794 | 777 | 0 | 1 | 14 | 616 | 1 | 1 | 97.9% |
| 119th | 2025– | 337 | 333 | 0 | 2 | 2 | 262 | 0 | 0 | 98.8% |
<!-- /table:senate_congress -->

By committee, sorted from least to most complete. "Veterans' Affairs" at the bottom is seven joint House–Senate veterans' service organization hearings printed by the Senate under the House committee's code.

<!-- table:senate_committee -->
| Committee | Hearings | Full recording | Clips only | Not public | None found | On senate.gov | Before channel | No channel | Found | Found since 2019 |
|---|---|---|---|---|---|---|---|---|---|---|
| Joint Select Solvency of Multiemployer Pension Plans | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0% | — |
| Small Business and Entrepreneurship | 146 | 109 | 0 | 1 | 31 | 103 | 5 | 0 | 75% | 82% of 80 |
| Veterans' Affairs (joint hearings, House code) | 7 | 6 | 0 | 0 | 1 | 0 | 0 | 0 | 86% | 86% of 7 |
| Aging | 196 | 176 | 0 | 9 | 10 | 163 | 1 | 0 | 90% | 98% of 103 |
| Energy and Natural Resources | 434 | 391 | 11 | 5 | 27 | 368 | 0 | 0 | 90% | 95% of 212 |
| Veterans' Affairs (Senate) | 184 | 167 | 0 | 2 | 15 | 165 | 0 | 0 | 91% | 93% of 114 |
| Appropriations | 625 | 570 | 0 | 2 | 48 | 570 | 5 | 0 | 91% | 90% of 260 |
| Environment and Public Works | 426 | 405 | 0 | 3 | 18 | 300 | 0 | 0 | 95% | 99% of 227 |
| Rules and Administration | 46 | 44 | 0 | 1 | 0 | 44 | 0 | 1 | 96% | 97% of 37 |
| Homeland Security and Governmental Affairs | 491 | 472 | 1 | 13 | 5 | 468 | 0 | 0 | 96% | 95% of 211 |
| Indian Affairs | 185 | 178 | 0 | 0 | 7 | 172 | 0 | 0 | 96% | 99% of 74 |
| Budget | 87 | 84 | 0 | 2 | 1 | 73 | 0 | 0 | 97% | 99% of 69 |
| Commerce, Science, and Transportation | 570 | 551 | 1 | 1 | 17 | 484 | 0 | 0 | 97% | 99% of 270 |
| Health, Education, Labor, and Pensions | 322 | 316 | 0 | 1 | 5 | 295 | 0 | 0 | 98% | 99% of 134 |
| Armed Services | 346 | 340 | 0 | 4 | 0 | 339 | 0 | 2 | 98% | 99% of 177 |
| Select Intelligence | 77 | 76 | 0 | 0 | 0 | 76 | 0 | 1 | 99% | 97% of 37 |
| Judiciary | 342 | 338 | 0 | 0 | 0 | 338 | 4 | 0 | 99% | 100% of 211 |
| Foreign Relations | 436 | 431 | 0 | 3 | 0 | 431 | 2 | 0 | 99% | 98% of 182 |
| Finance | 307 | 304 | 0 | 0 | 3 | 303 | 0 | 0 | 99% | 99% of 138 |
| Banking, Housing, and Urban Affairs | 444 | 440 | 0 | 1 | 3 | 361 | 0 | 0 | 99% | 99% of 234 |
| Agriculture, Nutrition, and Forestry | 151 | 150 | 0 | 1 | 0 | 150 | 0 | 0 | 99% | 99% of 93 |
<!-- /table:senate_committee -->

What the Senate table means:
- **Almost everything is on senate.gov.** 5,119 of the 5,835 hearings have a recording there, and 345 more are on YouTube. Coverage is 90–96% in every Congress since 2013, and 88% so far in the 119th, where the newest hearings' recordings were not yet posted when probed.
- **Committees with no YouTube channel are covered anyway.** Agriculture, Armed Services, Rules and Intelligence have no official YouTube presence, and 96–99% of their hearings are on senate.gov.
- **What's still missing (211 hearings):** mostly Appropriations (52), Small Business (32) and Energy (30) hearings whose recording, if it exists, carries a name the probe didn't try (a subcommittee's own stream, or a third hearing that day); field hearings; and the 66 Senate records GPO filed with no committee code, which the probe can't place.
- **The YouTube channels matter little.** Foreign Relations' only channel began uploading in April 2026, Senate Judiciary Democrats' in April 2025, and Appropriations' stopped in 2016; their hearings are on senate.gov regardless.
- **How the probe works, and its limits.** The player loads `<committee><MMDDYY>_1/master.m3u8` from the Senate's archive (or a live path for recordings since mid-2023), with `A` and `B` inserted for a second and third hearing that day. The probe asks whether that manifest exists for each hearing's committee and date. It confirms a recording exists, not which hearing a same-day recording is (several hearings on one day share it, on 420 days) or how long it runs.

## What happened to the missing House video, committee by committee

**Ways and Means.**
- **Found, late:** the committee's 2013–2018 hearings are on `@waysmeanscmte`, uploaded in March–July 2019 under titles like "W&M Hearing: Feb 26, 2014" with a date code in the description. The research pass missed them because they carry no topic words and were uploaded years after the hearings. The matcher's date rule now finds 138 of them, and coverage rose from 39% to 88%.
- **Found by file name:** each 2019 re-upload's description is the House's raw recording file name, such as `10W M1100 130717 1000` (room 1100 Longworth, July 17, 2013, 10:00). Matching room and start time against the transcript told apart the untitled "W&M Hearing: <date>" and "<date> PM" videos for 27 more hearings, including days with a markup and a hearing.
- **Still missing:** a handful of 2015–16 field hearings and subcommittee hearings the 2019 upload skipped. The WordPress site's 2016–18 hearing pages embed YouTube IDs that are now private or deleted.
- **Elsewhere:** a few 2014 trade subcommittee hearings survive only on Devin Nunes's channel, 2016 tax hearings on the Tax Revolution Institute's, and one each on the Foster Youth Caucus, the City of Auburn and news channels.

**Education & Workforce (2013–14).** Every hearing page on edworkforce.house.gov links an "Archived Webcast" YouTube video, but all of those videos are now private. Only member clips (mostly Rep. Rokita's) remain public.

**Veterans' Affairs.**
- **Late uploads (found):** `@HouseVetsAffairs` bulk-uploaded 2013 to April 2014 hearings in July 2014, and early-2015 hearings in 2016, under titles like "4/9/14 FC".
- **Lost:** about 30 of the committee's original uploads from mid-2014 through 2015 are now private or deleted. Mid-2015 hearings were streamed on Ustream only. C-SPAN is the only public record for 20 hearings from May–November 2014 and April–July 2015, usually split into panels.
- **Field hearings:** none from 2013–2017 has video anywhere. Where later ones exist at all, they are on local community TV channels.

**Armed Services (2013–14).** The committee hosted its own hearing video on Granicus, linked as "Watch Live" from every hearing page. The Wayback Machine has the player pages, but the media files are gone (the archive's playlists point to a dead Windows Media server). The channel's public uploads start in January 2015, apart from about 11 hearings back-uploaded later. C-SPAN has 14 of the missing hearings, DVIDS has two full recordings and many short news packages, and a few more survive on DARPA's channel, a third-party DoD video archive (`@Galactic007A`), and a witness's channel. The 2009–2012 Republican channel `@HASCRepublicans` has earlier hearings.

**Homeland Security (2013 to mid-2015).** The majority channel only began posting full hearings in September 2015. Before then, the Democrats' channel posted only the ranking member's opening statements. C-SPAN carried 32 of the missing hearings, mostly full-committee ones; the committee's own archived-video links of the era point to Windows Media and Ustream streams that are gone. Six later hearings turned out to be unlisted uploads on `@HouseHomeland`, found only through the hearing pages that embed them.

**Foreign Affairs.**
- **Late uploads (found):** `@HouseForeignGOP` re-uploaded many 2012–2015 hearings in 2016 with "(EventID=…)" in the titles. Two more are unlisted, so no search finds them; the hearing pages embed them.
- **Clips only:** from April 2014 to August 2015 it posted only chair clips. The full hearings of that period were Ustream recordings embedded on the hearing pages, and all of those are dead. C-SPAN covered about a third of the 2014–15 hearings.
- **Markups:** these are titled by bill number only ("Markup: H.R. 2848"). The 2019 and 2023 markups are embedded on the minority's site.

**Transportation and Infrastructure (2013–2015).** Hearings streamed on Ustream, and the recordings embedded on the committee site no longer play. `@transport` posted member clips and a few hand-picked full hearings until it started livestreaming in March 2014.

**Natural Resources.**
- **2013–14 back catalogue:** the Republican channel uploaded it in 2015–16, titled only with a date and subcommittee code ("7/23/2013. EMR. 10:00 AM"). The real title is in the description. Four more of these were found by reading the archived hearing pages, where the matcher had settled for a clip.
- **Dead streams:** the 2013–15 hearing pages otherwise link Ustream, Windows Media playlists on edgeboss.net, or an Akamai Flash stream for field hearings; the Wayback Machine kept 99 playlists and no video.
- **Since 2019:** titles are generic ("Oversight Hearing | Full Committee"). The EventID in the description settles them.
- **Missing:** six 2013–14 hearings were never uploaded.

**Judiciary.** `@JudiciaryDems` uploaded its 2012–2015 archive in September–November 2015 with "(EventID=…)" titles. That covers about 60% of the period. The rest were Ustream recordings on the hearing pages, all dead; C-SPAN has 13 of them, including both days of the 2014 music licensing hearings. The 2019 impeachment markup is one proceeding printed as eleven volumes; volume I holds the markup and its recordings, and volumes II–XI are documents submitted for the record, so they count as not public.

**Financial Services, Science, Budget, House Administration, Agriculture, Appropriations.** Each bulk-uploaded its 2011–2015 archive in 2015–2018, with EventIDs or date codes in titles and descriptions. Almost everything is there; it was just posted outside the original matcher's date window.

**Small Business.** Field hearings were almost never posted by the committee; none from 2013–2019 has video anywhere. Several "clips" of 8–14 minutes turned out to be whole markups and organizational meetings: the transcripts show the meetings lasted that long.

**Joint Economic Committee (2013–14).** Only 4–10 minute member clips were posted to YouTube. The Senate Recording Studio recorded the hearings, though: 25 of them are in the Senate's archive under the committee's own stream name, and the committee's site links more.

**Helsinki Commission.** Its events in Senate rooms in 2013–2015 are in the Senate's archive (22 found by probing it), and its 2017–2019 briefings are on the Commission's Facebook page, which its website embeds (43 found through archived pages). Briefings held in House rooms in 2014–2016 had no webcast at all. The Facebook finds can't be checked while logged out, so they carry medium confidence.

## YouTube channels

We now track **119 channels for 52 committees and commissions**: 87 for 36 House and joint bodies, and 32 for 16 Senate committees. The list started at 24 channels for 18 House committees. One of the original 24 was a dead handle and has been replaced.

- **House and joint channels found:** 60 channels were added, from four sources:
  - the YouTube links on each committee's majority and minority websites;
  - about 250 YouTube channel and video searches, covering current and historical committee names, chairs since 2007, and Democrats/Republicans/Minority variants;
  - all 7,545 YouTube videos that Congress.gov links from its committee meeting records;
  - the 16-agent research pass, which found three more channels.
- **Senate channels found:** the same website-and-search method, applied to all 23 Senate committees, caucuses and select committees with GPO hearings. Sixteen have at least one official channel; the notes for every committee, including the seven with none, are in `research/data/senate_channels.csv`.
- **Checks on every channel:** each one was checked against its uploads, and against its .gov link where it has one. Every handle was re-resolved to confirm it points to the intended channel ID, with no duplicates.
- **Cross-check against Congress.gov:** of the 7,545 official House hearing videos Congress.gov links, all but 9 are on a tracked channel. The 9 are unlisted videos on tracked channels, which never appear in a channel's public upload list. The matcher counts them as found from the Congress.gov link.

House and joint channels added, by committee:

| Committee | Channels |
|---|---|
| Armed Services | Democrats' current channel (`@armedservices8789`, Ranking Member Smith); `@armedservicesGOP`; `@HASCDems` (2010 archive); `@HASCRepublicans` (2009–2012 hearings) |
| Homeland Security | `@HomelandDems`; Republicans' current channel `@HomelandSecurityCommitteeGOP` |
| Intelligence | `@HouseIntel`; current majority channel; 2019–22 minority channel |
| Oversight | `@OversightDems`; both Coronavirus select subcommittees; `@OversightMaj`, `@OversightRepublicans` and `@CommitteeonOversight` archives |
| Financial Services | `@fscdems9522` and `@fscdems484` (2016–17); an older committee channel |
| Judiciary | Two older Democratic channels, including `@HouseJudDems` (Conyers era); a 2020–23 livestream channel |
| Small Business | `@HouseSmallBizCommitteeDems`; the 2009–10 `@HouseSmallBizDems` archive (1,934 videos) |
| Veterans' Affairs | `@HouseVetsAffairs` (Republicans); `@VetAffairsDems` |
| Ways and Means | `@waysmeanscmte` (hearings, 976 videos); `@waysandmeansdems` |
| Education & Workforce, Energy & Commerce, Rules, Science, House Administration | Minority channels, plus Science's Republican channel and older House Administration channels |
| Transportation and Infrastructure (new) | `@transport`, `@transportdems` |
| Ethics (new) | `@HouseEthics`; the adjudicatory-hearing stream channel |
| Select committees (new) | CCP; Climate Crisis; Modernization of Congress; Benghazi (both sides); January 6th; Economic Disparity (both sides); Energy Independence and Global Warming (Republicans, 2009–10); the 2018 Joint Select Committee on Budget and Appropriations Process Reform (under our placeholder code `jsbp00`) |
| Commissions and task forces (new) | Tom Lantos Human Rights Commission; Task Force on the Attempted Assassination of Donald J. Trump; Congressional Oversight Commission (2020) |
| Joint (new) | Joint Economic Committee (4 channels); Helsinki Commission; Congressional-Executive Commission on China; Joint Committee on Taxation |

Senate channels, by committee (majority or main channel first):

| Committee | Channels |
|---|---|
| Appropriations | `@SenateApprops` (Democrats, 2014–16) |
| Banking, Housing, and Urban Affairs | `@SenBankingGOP`; `@senatebankinghousingandurbdems`; `@SenateBankingGOP` (2013–18); `@SenateBanking` (2011–13) |
| Budget | `@BudgetGOP` (2011–22); `@SenateBudget` (Democrats) |
| Commerce, Science, and Transportation | `@CommerceRepublicans`; `@commercedems`; `@senatecommercecommitteedem873` (2017–18); `@SenateCommercePress` (2009–16) |
| Energy and Natural Resources | `@ENRGOP`; `@SenateEnergy` (Democrats) |
| Environment and Public Works | `@EPWGOP`; `@EPWCmte` (Democrats, since 2011) |
| Finance | `@GOPSenateFinance` (2012–18); `@SenFinanceMajority` (2011–16); `@SenateFinance` (no public uploads) |
| Foreign Relations | `@SFRCDems` (since April 2026) |
| Homeland Security and Governmental Affairs | `@HSGACDems` |
| Health, Education, Labor, and Pensions | `@gophelp`; `@HELPCommitteeGOP` (2011–17) |
| Judiciary | `@SenateJudiciaryDemocrats` (since April 2025) |
| Small Business and Entrepreneurship | `@SenateSmallBusiness`; `@SenateSmallBiz` (2014) |
| Veterans' Affairs | `@senateveterans6644` (2013–14); `@ussenateveteransaffairsdem9792` |
| Caucus on International Narcotics Control | `@senatecaucusoninternationa2031` |
| Indian Affairs | `@SenateIndianAffairs` |
| Aging | `@SenateAging`; `@u.s.senatespecialcommittee3047` (2014); `@demsonaging7345` (2017–18) |

Handled specially:
- **Chairs' personal channels.** Ed Markey's (now `@senatormarkey`) holds the Global Warming committee's hearings, and Trey Gowdy's holds Benghazi's. They are listed in the channel list's `member_channels` column: fetched and used for matching, but not counted as committee videos in the weekly report, so they don't distort committee numbers.
- **House Special Events** is not tracked. It covers ceremonies, not committee hearings.

## Problems found in the pipeline (fixed)

- **Six committees were never fetched.** A dead channel handle (`@NaturalResourcesDems`) crashed the weekly fetch at the same point every week, so every committee after it was skipped, while the job still reported success.
  - **Fix:** the handle is corrected, and the fetch now checks every channel and then fails the job if any channel failed.
- **The report counted only each committee's last channel.** Channels such as `@USHouseFSC` (758 videos) were fetched weekly but never reported.
- **Education & Workforce had the wrong committee code** (`hsed00a` instead of `hsed00`), so it could never match Congress.gov or GPO data.
- **The report's chamber was always "house".** It now comes from the committee code, so joint and Senate committees report as such.
- **A committee could only list two channels.** The second column now takes several handles, separated by `;`.
- **Video length wasn't stored.** The fetch now records each video's duration, which the matcher uses to tell clips from recordings.
- **A channel with no public uploads crashed the fetch.** Empty channels (Senate Finance's `@SenateFinance`) are now recorded as empty.
- **GPO committee codes had typos and blanks.** `gpo-fetch` now fixes known typos, fills blank codes from the committee name where it can, marks errata sheets, and reads the hearing days out of every transcript since the 113th Congress.

## Problems found in GPO's metadata

The research pass turned up many GPO records whose metadata doesn't match the transcript. These are worth reporting to GPO, and matching against GPO data has to allow for them:

- **Wrong held dates.** Often GPO used a date that appears in the title, or the date of the incident the hearing was about. Examples:
  - CHRG-113hhrg88456 (Taliban detainee transfer) is dated May 31, 2014, but was held June 11, 2014.
  - CHRG-116hhrg40718 (Lafayette Square) is dated the day of the incident; the hearings were June 29 and July 28, 2020.
  - Both H. Res. 755 impeachment markup packages are dated January or July 2019 but ran December 11–13, 2019.
  - CHRG-117hhrg49370 is dated 2021 but was held in 2022.
- **Missing dates.** Four Senate records have no held date at all; the matcher reports them as "no video found" with a note.
- **Placeholder dates on Appropriations volumes.** Multi-hearing volumes carry the first day of the Congress (e.g. 2021-01-01) as their held date. `gpo-fetch` reads the real hearing days from the transcript, except for the quarter of volumes that are scanned PDFs with no text.
- **One date per package, whatever the package holds.** Agriculture's `CHRG-114hhrg93961` ("Supplemental Nutrition Assistance Program") prints five hearings, from February 25 to June 10, 2015, and Homeland Security's `CHRG-114hhrg94105` prints two, February 3 and April 30, 2015; GPO dates each by its first day, so the other days couldn't link to their meetings or videos. **Fix:** `gpo-fetch` now reads the day headers of every transcript since the 113th Congress (15,478) and records the days in `hearing_dates` wherever they say more than GPO's date: 776 prints cover several days, and 159 name one day that differs from GPO's. The matcher and the text index match on those days. Where the transcript names one day and GPO another, both count, because either can be the misprint: the Taliban-transfer hearing's GPO date is wrong, while "Human Rights Abuses in Egypt" (`CHRG-113hhrg86002`) has the misprint in its own header. For printed hearings the gain is small, since a hearing's first day usually had its video already (3 more hearings found, 28 gained the recordings of their other days). For the meeting records it is larger: 228 more meetings link to a print.
- **Wrong or missing committee codes.** For example:
  - an impeachment hearing is coded as Appropriations;
  - an air traffic control hearing is filed under Appropriations but belongs to Transportation and Infrastructure;
  - a 2019 House Veterans' Affairs subcommittee hearing (CHRG-116hhrg48810) is coded as the Senate committee;
  - 22 Helsinki hearings, 15 other House records and 66 Senate records have a blank code. **Fix:** where GPO names no committee, `gpo-fetch` reads it from the transcript's title page ("COMMITTEE ON THE JUDICIARY / UNITED STATES SENATE"), which filled 76 of the 81 blank codes since the 113th Congress, 65 of them Senate Judiciary. With a committee and the right day, the Senate archive had recordings for 46 more printed hearings, and Congress.gov's own links attached to 28;
  - one Small Business record is coded `hssmoo` instead of `hssm00`.
- **Wrong titles or event IDs.** For example, CHRG-115hhrg26237's title says NASA's FY2018 budget, but the transcript is a different hearing. CHRG-117hhrg45372's event ID points to another hearing.
- **Records that aren't hearings.** These include errata cover sheets, a staff report, and a chapter of an annual report.

## Recommendations

Done since the research pass:
1. **Match on EventIDs with no date window.** The matcher now takes "EventID=NNNNNN" or "(ID: NNNNNN)" from any video, whenever it was uploaded.
2. **Match on date codes in titles.** "031815 -", "7/23/2013. EMR.", "YYYYMMDD Title", "W&M Hearing: Feb 26, 2014" and descriptions saying "Hearing Date: …" all count.
3. **Use Congress.gov's video links.** The weekly run keeps every Congress.gov committee meeting record, and a video linked from a hearing's meeting record is the strongest evidence, including for unlisted videos.
4. **Make the matching a weekly report with a one-video-per-hearing rule.** `gpo-match` writes `apps/committee_youtube/data/gpo_hearing_videos.csv` and its per-committee summary every week.
5. **Track Senate video where it lives.** A senate.gov link in a hearing's Congress.gov record now counts as a recording (`full_recording_offsite`), and the archive probe covered the back catalogue to 2013. New Senate hearings get their Congress.gov link within days, so the weekly run keeps up without re-probing.

Still open:
6. **Ask committees to restore private or deleted archives.** Education & Workforce (2013–14) and Veterans' Affairs (2014–15) made public hearing recordings private, and Ways and Means' 2016–18 hearing pages embed dead videos even though the 2019 re-uploads exist. The dead video IDs are listed in the research verdicts.
7. **Report the GPO metadata problems above** to GPO, starting with the wrong dates and blank codes, since they hide hearings from every date-based search.

## Transcripts and captions

GPO's printed transcript is the record, but it arrives 6–8 months after a House hearing (12–18 months for the Senate) and only for what committees send to print: no markups, and 10–30% of hearings never. `research/data/hearing_text_sources.csv` lists, for every Congress.gov meeting since 2013 (hearings, markups and business meetings), where its text can be found.

**Which print is a meeting's.** A print is matched to a meeting by event ID, or when the committee held it that day and one of three things is true: the titles agree, the print collects several hearings under one title (an Appropriations volume, a multi-day print), or it is the day's only print for the committee's only meeting. A markup takes only a print that says it is one. The date alone is not enough: a committee often holds a hearing and a markup, or two hearings, on one day, and the date would give each the other's transcript. An earlier version of this index did that, and 676 meetings claimed a print that was another proceeding's. Congress.gov's own `hearingTranscript` field makes the same mistake: it ties six unrelated Appropriations hearings of March 4, 2015 to one print, so it is not used.

**Committee transcripts.** House committees attach their own transcripts to meeting records as documents ("Hearing: Transcript", "Markup Transcript"), and Senate committees post them on the hearing's page. 3,998 meetings have one: 3,410 in the House, 531 in the Senate and 57 of the joint bodies. For 614 meetings it is the only text (551 House, 48 Senate, 15 joint), and 285 of those are markups, which GPO never prints.

**Which recording is a meeting's.** A recording counts when Congress.gov links it, a tracked video carries the meeting's event ID, a tracked video of the committee was posted within a day before to three days after with a matching title or naming one of the same bills (the matcher's rules for printed hearings, applied to unprinted meetings too), a tracked upload of the committee is titled with the meeting's date, or is a generic hearing or markup upload from the meeting's day when the committee held nothing else that day or the title names the meeting's subcommittee, or the Senate archive has one for the committee and day (including a House committee's joint hearing with its Senate counterpart). A joint hearing is entered once per committee, so same-day meetings with the same title share their records. Recordings found by hand, on a committee's own event page or a partner committee's channel, are listed in `research/data/meeting_recordings_found.csv` and counted.

| Where the text is | House meetings | Senate meetings |
|---|---|---|
| GPO print | 8,645 (67%) | 2,695 (59%) |
| Committee's own transcript | 551 (4%) | 48 (1%) |
| YouTube caption track (uploader's or automatic) | 2,034 (16%) | 31 (1%) |
| Senate player caption track (recordings since mid-2023) | — | 652 (14%) |
| Recording with no text | 1,147 (9%) | 630 (14%) |
| No recording found | 488 (4%) | 519 (11%) |

**Meetings with nothing** (`research/data/meetings_without_records.csv`): 970 since 2013 have no print, no transcript, no recording found and no captions. 549 are closed by nature: the record's type or title says closed, briefing or deposition. Of the 447 House meetings, 260 are markups and business meetings and 187 are hearings, led by Intelligence (144 of the House rows in all, closed by design), Natural Resources (37), Ways and Means (31) and Veterans' Affairs (31). 294 have documents, in the record or on the committee's page. The 421 open meetings have all been searched for. Some were never held: Congress.gov keeps a meeting as Scheduled when the committee postponed it. When the postponed meeting was re-entered under a new event ID and held within 60 days, the index marks the stale record with `rescheduled_to` and leaves it out of this file (44 meetings). Eleven more say so in their own title ("POSTPONED: FY19 Oversight Hearing on the NASA James Webb Space Telescope", or just "Test", dated Christmas Day 2019) and are marked `not_held`, as are two Senate hearings with no recording whose committee page is headed POSTPONED. Eleven Senate hearings have a committee page and no recording. On nine of them the page embeds the Senate's player for a file the archive no longer serves (`energy110719`, `help020122`): the committee linked a recording that is gone at the source.

## What each meeting has on the record

`research/data/meeting_completeness.csv` has one row per meeting: its recording, where its text is, its witness list and where that came from, its documents, its location. For open hearings that were held:

| | House (9,821) | Senate (3,110) | Joint bodies (116) |
|---|---|---|---|
| Recording | 96% | 99% | 98% |
| Text (print, transcript or captions) | 94% | 94% | 97% |
| Witness list | 98% | 96% | 87% |
| Any document | 98% | 85% | 78% |
| Location | 93% | 99% | 91% |

A document counts when it has an address. In Congress.gov's own records that is 92% of House hearings and none of the Senate's.

**Congress.gov's House records are incomplete copies of the House's own repository.** Its meeting records are built from docs.house.gov, but not all of it arrives. `research/scripts/house_event_pages.py` read the repository's page for the 5,741 House and joint meetings whose record lacked documents, witnesses, or a transcript or print. 2,191 of them have documents the record lacks (18,271 in all: 8,104 witness statements, 3,701 Truth in Testimony forms, 3,247 biographies, 1,735 bills and amendments, 55 transcripts), and 1,881 have a witness list the record lacks (7,921 witnesses). With them, House hearings with a witness list go from 80% to 98%. Both are in `research/data/house_documents_found.csv` and `house_witnesses_found.csv`.

**Congress.gov has no witnesses and no document files for the Senate.** Its Senate records name documents ("Generic Document", "Bills and Resolutions") without an address, and list no witnesses. The committees' own sites have both. `research/scripts/senate_hearing_pages.py` reads every hearing page that 21 Senate and joint committee sites list since June 2019 (4,925 pages) and finds the page of 2,900 of the 3,217 open hearings on record: the page that names the hearing's date and holds most of its subject, both in text that is the page's own. From those pages:

- witnesses for 2,769 hearings (9,401, with a post for 8,228), in `research/data/senate_witnesses_found.csv`;
- 14,407 documents for 2,746 hearings (7,695 witness statements, 1,398 members' statements, 1,283 sets of questions for the record, 599 transcripts, 252 nominees' questionnaires), in `senate_documents_found.csv`;
- the page itself, in `senate_hearing_pages_found.csv`.

Senate witness lists (`research/data/meeting_witnesses.csv`) come from the GPO record of the hearing's print, when the print and the meeting are each other's only match (48% of Senate hearings), from the committee's page (48%), and from the meeting's own title for a nomination hearing, whose nominees are its witnesses (1%). Where a hearing has both a GPO list and a page, they were compared as a check on the page matching: of 1,246 hearings, 1,224 share most or all of their witnesses' surnames, and the 22 that share few are nomination hearings where GPO lists the senators who introduced the nominee and the page lists the nominee. 110 Senate hearings (4%) are left without a witness list: 81 have no page found, and 29 have a page that names no witnesses. Of the joint bodies, the Helsinki Commission's pages are read (27% of joint hearings take their witness list from them); the Joint Economic Committee writes its witnesses in running text, which is not read. 15 joint hearings have no list.

Three things the pages taught the matching. A listing's date can't be trusted: the Aging Committee's listing puts each hearing beside the date of the row above, and matched by listing date, 68 of its 78 hearings took the page of the hearing before. A page names dates that are not its own: sites carry a panel of coming hearings on every page, so a line that more than five pages carry is not counted. And a later page can name an earlier hearing's day and subject: the business meeting that reports a nominee gives the day of the nominee's hearing.

**GPO's witness lines come three ways** ("Mr. Nels Leader, Vice President, Bread Alone Bakery"; "Richard J. Powell, Executive Director, ClearPath"; surname first, "Campbell, Jr., J.H., President and CEO"), plus contents lines that are not witnesses at all. The reader in `congress_api.transcribe.metadata` handles the three and drops the fourth; `hearing-transcribe` uses the same reader for its participant list, and the Senate pages' names go through it too. It takes a title off the front of a name (civil, clerical, or a military rank written in full or abbreviated: "Lieutenant General", "LTG", "Master Chief Petty Officer"), degrees and service branches off the end, and rejects a line that holds a noun of office or of paper ("State Director", "Printed Hearing Record"), which is a post or a document and not a person.

The captions were fetched with `youtube-captions` and `senate-captions` (see the app README); they are search-grade text, unpunctuated for YouTube's automatic ones, with no speaker attribution. C-SPAN no longer publishes transcripts.

For the hearings with video but no print, `hearing-transcribe` produces a transcript in the print's shape with members and witnesses named: Gemini 3.8 Flash watches the video in 25-minute windows, reading name plates and hearing the chair's recognitions, with the committee roster and witness list in the prompt. Tested on a 2023 Judiciary subcommittee hearing against its print (193 turns, 13,112 words): word error rate 8.7%, mostly the print's own editing of false starts, and 85% of words attributed to the right speaker. Two alternatives were tried and dropped: the dedicated transcription model (Gemini 3.5 Transcribe, diarization and word timestamps, then a resolver) matched the words as well but its speaker labels, which the model documents as experimental beyond three speakers, mapped to the right person for only 66–74% of words; and a single call for the whole hearing, which the model's recitation filter refuses, as it does any verbatim window much over 30 minutes.

## Verification

Two kinds of checks stand behind the numbers.

### The research pass (September 2026)

After the 16-agent research pass, two checks ran on its verdicts. They are recorded in `hearing_video_verdicts.csv` and now apply to the weekly matcher through `hearing_video_overrides.csv`.

**Automatic check.** This covers every hearing and every claimed video:
- **Coverage:** every hearing got exactly one verdict.
- **Videos resolve:** of 2,496 claimed videos, 2,400 resolve to the claimed channel and 42 more exist but block embedding. The remaining 54 are on a different tracked committee's channel than the one listed (joint hearings, miscoded rows). Eight "found elsewhere" claims turned out to be on another committee's tracked channel and were reclassified.
- **Evidence strength:** of the 1,335 "found" claims, 510 have videos whose own title or description carries the hearing's event ID, 636 match its title and 89 give its date. The other 100 had no such signal; most are multi-hearing Appropriations volumes, bill-number markups and third-party uploads.

**Adversarial check.** Six more agents re-examined verdicts independently:
- **Refuters (4 agents):** they tried to disprove the 176 riskiest "found" claims: every off-channel find, every medium- or low-confidence match, and every claim with no signal in the video text.
  - 166 held up. 7 were revised: 3 added a missed video, 2 swapped in a fuller copy, and 2 were downgraded to clips only because the only upload covered half the hearing.
  - 3 were refuted: a third-party upload that was a different hearing under the wrong title, a video already belonging to an adjacent hearing, and a volume of written testimony only.
- **Challengers (2 agents):** they tried to find a full recording for a random sample of 90 "no video" and "clips only" verdicts.
  - 85 held up and 4 were revised: 3 "no video" rows had member clips, so they became "clips only", and 1 "clips only" row gained a missing segment.
  - 1 was refuted: a 2014 Homeland Security hearing livestreamed by Roll Call under a generic news title.

**What this implies:**
- **"Found" claims are reliable.** Even among the riskiest claims, about 3% were wrong outright and about 6% needed a partial correction.
- **"No video" verdicts could hide recordings on tracked channels**, and did: the weekly matcher's date rule overturned 134 of them, almost all Ways and Means hearings re-uploaded years later under date-only titles.
- **"No video" verdicts may hide a few news livestreams.** The challengers' one refutation was a Roll Call stream under a generic title, so a news-channel search followed it up (next).

### The news-channel search

Every House and joint hearing since 2013 still without a full recording (825) was searched again: a YouTube search on its title and year, plus searches inside Roll Call, the Washington Post and PBS NewsHour. Candidates of 30 minutes or more on untracked channels were checked against the YouTube Data API for their exact upload date, and counted only when uploaded within three days of the hearing (or dated in their own text) with a matching title. That produced 26 hearings for review by hand:
- **14 were real recordings** on news channels (Roll Call, The Hill, Reuters, Forbes), witness organizations (UC Berkeley Haas, HCM Strategists), a local paper's video of a field hearing, a member's channel, and third-party copies of C-SPAN and DoD coverage. They are now `found_untracked`.
- **The rest were not:** other hearings on the same subject days apart, a think tank's own event on the same day, and a 47-minute compilation of one member's questions.
- **A side find:** nine volumes of the December 2019 impeachment markup had no video because a sibling volume's wrong GPO date had reserved the committee's livestreams for another day. They now share those recordings.

The rate confirms the earlier estimate: about 1% of negatives hid a full recording somewhere on YouTube. The remaining negatives were then investigated off YouTube (next).

### The archive investigation

Eight agents took the 840 House and joint hearings still without a full recording, about 100 each grouped by committee, with the earlier research evidence for each hearing. For each one they listed C-SPAN's programs for the hearing date (and the next day), found the committee's own hearing page for the event in the Wayback Machine and followed every video reference on it, and checked archives the evidence pointed to (DVIDS, the Senate's video archive, the Helsinki Commission's site, host organizations). The brief is `research/agent_briefs/archive_brief.md`; the verdicts, one line per hearing with the evidence, are `research/agent_results/archive_01…08.jsonl`.

- **Finds:** recordings for about a third of the hearings. C-SPAN has 120; the Senate's archive has 52 (Joint Economic Committee and Helsinki Commission events, found by probing the archive by date); the Helsinki Commission's Facebook page has 43; DVIDS has 2; and 96 are on YouTube after all, almost all on the committees' own channels, as unlisted uploads, untitled archive uploads, or videos filed under the wrong hearing.
- **Checks:** every claimed YouTube video was looked up in the Data API. Seventeen finds under 20 minutes, or with no length on record, were reviewed by hand: ten are whole proceedings that ran only minutes (organizational meetings, markups, a two-minute Member Day hearing, a hearing that went into closed session after five minutes) or unlisted uploads the API lists without a length, and were kept; two Ways and Means re-uploads whose file-name room didn't match the transcript and five Facebook embeds that can't be verified were dropped. C-SPAN finds were checked against the program page's date and length and the transcript's gavel times; where C-SPAN has only one session of a two-session print, or a session runs short, the find is marked medium.
- **What's gone:** the committees' own 2013–2015 streams. Ustream recordings (Judiciary, Foreign Affairs, Transportation, Veterans' Affairs, Appropriations, Natural Resources), Windows Media playlists on edgeboss.net (Homeland Security, Education & Workforce, Natural Resources), Granicus (Armed Services) and an Akamai Flash stream (Natural Resources field hearings) are all dead, and the Wayback Machine holds the player pages and playlists but never the video. Field hearings of every committee came up empty.
- **Research verdicts it overturned:** 31 hearings the research pass had marked found on a tracked channel were in fact 1–6 minute member clips (Homeland Security Democrats' and JEC Republicans' channels); the agents found their full recordings on C-SPAN and in the Senate's archive. Comparing the live output with the frozen research snapshot (`hearing_video_verdicts.csv`) is how such changes are caught; nothing in the pipeline reads the snapshot itself.
- **What was learned about the data:** committees tag videos with the wrong event ID more often than expected (Financial Services, Small Business, Ways and Means), which is why the matcher now discounts a late, mismatched tag. Several GPO held dates are wrong by days or months. C-SPAN's listings include placeholder entries with a committee's name and no video.

### The weekly matcher

- **One video per hearing.** Each video is assigned to its best-evidenced hearing; hearings on different days can't share one. This retires the research snapshot's 74 "unconfirmed" automatic matches, where the old matcher had given one video to consecutive-day hearings with similar titles. 32 hearings share a video with another hearing on the same day (joint hearings, or several GPO packages for one proceeding) and are flagged.
- **Research verdicts are kept unless outweighed.** A reviewed "found" verdict always stands. A reviewed "no video" or "clips only" verdict gives way only to strong evidence (a Congress.gov link or event ID) or to a dated recording of 30 minutes or more, and rows the verifiers rejected are locked.
- **Spot check of the overturned verdicts.** A random sample of the Ways and Means re-uploads was checked by hand: each is a 90–200 minute video titled with the hearing's date, and the description carries a `YYMMDD` code that confirms the date where the title has a typo.
- **Search-engine check of the open gaps.** 1,389 gap rows were searched on Google in eight rounds (`research/data/search_smoke_test.csv`). The first four rounds were run in a browser: one hand-picked row per gap listed in this document, then seeded random samples across printed hearings with no video or clips only and unprinted meetings with no records, stratified by chamber, committee and meeting type. The last four went through SerpAPI (`research/scripts/search_smoke.py`), with every committee page among the answers read for the videos it embeds: the 50 open House meetings whose committee had recorded 80% or more of that kind of meeting that year, every open meeting not yet searched (235), every printed hearing since the 113th Congress without a full recording (844), and the 109 meetings that turned out to have claimed another proceeding's print. 1,250 held: the search surfaced nothing beyond what the pipeline had. Twelve were wrong in a way a rule could fix, and the unprinted-meeting index gained those rules: the matcher's committee-code aliases (Congress.gov files the Joint Economic Committee as `jjec00`, GPO as `jsec00`); a shared bill number counts as a title match ("Rules Committee Hearing H.R. 5 and H.R. 79"); an upload titled with the meeting's date matches when the committee held nothing else that day or the title names the subcommittee (Natural Resources' "3.2.16. EMR. 10:00 AM.", Ways and Means' 2019 re-uploads "W&M Hearing: Jun 25, 2014"); a generic "Full Committee Markup" or "Legislative Hearing | Federal Lands Subcommittee" upload from the meeting's day matches under the same condition when its kind agrees with the meeting's type; House meetings titled as joint hearings with the Senate are probed on the Senate counterpart's stream; same-day, same-title records of a joint hearing share their records; and two blank-code Senate Judiciary hearings got senate.gov overrides. Those rules gave 322 meetings a recording, and 46 records of meetings that were postponed or never held are marked instead of counted. 105 more had a recording. 74 of them were printed hearings found while the search ran, once their transcripts' own days and committees were read. The rest are recordings no rule reaches safely, now overrides (printed hearings) or rows in `research/data/meeting_recordings_found.csv` (meetings): Senate field hearings carried by WisconsinEye, Arkansas TV or a senator's own channel, joint hearings whose upload sits on the partner committee's channel (Veterans' Affairs with Oversight, Homeland Security with Armed Services and with Oversight, Armed Services with Foreign Affairs, Agriculture with Appropriations), uploads that cover two same-day meetings, a markup only 14 minutes long, an upload whose title carries the wrong year, a hearing re-entered under an event ID that Congress.gov's export lacks, and a Natural Resources field hearing streamed only on the committee's Facebook page. Twelve were explained rather than changed: closed sessions and depositions, executive sessions on tax-return documents, a conference meeting, postponed hearings, a hearing its witnesses skipped, a livestream that never started, and the undated Legislative Branch FY2021 volume, whose clerk's note says the subcommittee was unable to hold hearings. The rest: one Intelligence interview has a committee-released transcript but no recording; one C-SPAN listing is a medium-confidence find; two leads are unverifiable; and two meetings sat inside multi-day prints that GPO dates by their first day, since fixed (below). The no-records list went from 1,291 to 923, and to 907 once the transcripts' own hearing days were read. Two relaxations were measured and rejected for their false matches: accepting an upload when the meeting is the only one of its kind that day, and matching titles across committees' channels by rule (17 candidates, 7 right).

**Known limitations:**
- **Multi-hearing volumes count as found if any hearing day in them has video.** The `volume_days_with_video` flag says how many days were covered.
- **Some archive uploads are audio only.** A few of Appropriations' 2015 archive uploads say "This is an audio recording" and are flagged `audio_only`.
- **Automatic matches weren't individually re-verified.** The 7,400 automatic matches got the one-video-per-hearing check and spot checks during development.
- **The Senate studio names a second recording of the day with a trailing `p`** (`banking040622p`), beside the `A` and `B` names the probe already tried. 164 committee-days have one.
- **Congress.gov's committee video pages add nothing to its meeting records.** One committee's listing (House Budget, 891 videos, fetched through Zyte because the site blocks scripts) pairs 108 videos with events, and the meeting export already carries all 108.
- **The channel cache is complete.** Checked in September 2026 by listing every tracked channel's uploads playlist from the Data API and looking each video up in the cache: 117 channels list 65,085 videos, and 19 are not cached, all of them published after the last fetch. The cache holds 67,244, because it keeps videos that were later deleted or made private. Comparing the two totals would have hidden any shortfall, so the check is by video ID. Unlisted uploads are outside any uploads playlist and reach the pipeline only through a Congress.gov link or a committee page.
- **Senate recordings are confirmed by name, not content.** The senate.gov probe checks that a recording exists for the committee and day; it doesn't tell same-day hearings apart or check length.
- **Off-YouTube finds are only as durable as their hosts.** The C-SPAN, DVIDS and senate.gov recordings were confirmed live in September 2026; the 43 Facebook videos were confirmed only through archived copies of their pages.

## Method

- **Data:**
  - GPO transcripts: `apps/committee_youtube/data/gpo_hearings.csv`, 34,559 House, Senate and joint hearings since the 106th Congress, fetched weekly with `gpo-fetch`.
  - YouTube data: the weekly fetch of all 119 channels (67,244 videos), on the `pipeline-data` branch.
  - Congress.gov: all 18,139 House, Senate and joint committee meeting records from the 112th Congress on, fetched weekly with `congress-meetings`.
  - senate.gov: the Senate player's archive, probed once by committee and date for every Senate hearing since 2013 without a recording (`research/scripts/as_run/senate_isvp_probe.py`, results in `research/data/senate_isvp_probe.csv`).
- **Automatic matching (`gpo-match`):** evidence for each hearing, strongest first:
  1. a Congress.gov video link from the meeting record with the hearing's event ID;
  2. the hearing's event ID in a video's title or description, whenever it was uploaded;
  3. the hearing's date in the title or description, with a matching title or subcommittee, or alone when the video's title is only a date label and the committee held one hearing that day;
  4. a similar title, or the subcommittee's name, on a video posted one day before to three days after.
  A video found by the weaker rules counts as a clip when it's under 20 minutes, or under 30 with a member-clip title. Event-ID or Congress.gov evidence for a video posted more than a week after the hearing ranks below a same-week title match when its title doesn't fit (committees mistag videos). Multi-hearing Appropriations volumes are matched on each hearing day.
- **Research pass:** 16 agents, one per batch of 113–162 hearings grouped by committee. They worked from prepared evidence packets:
  - the hearing metadata;
  - every video from that committee within a few days;
  - Congress.gov meeting records.

  They also used YouTube search, in-channel search, committee websites and the transcripts, through a shared, rate-limited, cached client.
- **Verification:** 6 more agents, described under Verification above.
- **Verdict rules:**
  - "Full recording" means the proceeding itself (livestream, full upload, or all its parts), not clips or statements.
  - "Not public" requires evidence: a "CLOSED" notice, a written-only volume, an errata page, or closed-door interviews.
- **Reach:** the original research pass could not reach the Wayback Machine, C-SPAN or YouTube watch pages (bot-walled). The archive investigation later reached the first two (C-SPAN through the Zyte API) and the Data API stood in for watch pages. Private archives and dead streams remain out of reach.

## Files

- **`apps/committee_youtube/data/gpo_hearing_videos.csv`:** the live result, one row per GPO hearing (34,559 rows), rewritten weekly. Columns: hearing (package ID, Congress, chamber, committee code, dates, record type), `status`, `video_ids`, `channels`, `method`, `score`, `video_minutes`, `flags`, `source` (automatic or research) and `note`. `gpo_hearing_video_coverage.csv` next to it counts hearings per Congress, committee and status.
- **`apps/committee_youtube/data/hearing_video_overrides.csv`:** the verdicts the matcher applies: the research pass's reviewed verdicts, the news-channel search's finds, and the senate.gov probe's finds (`found_offsite`). To correct a match by hand, add or edit a row.
- **`hearing_video_verdicts.csv` (this folder):** the research-pass snapshot, one row per House and joint hearing since 2013 (9,643 rows). Columns:
  - hearing: date, Congress, chamber, committee, subcommittees, title, transcript URL;
  - `source`: automatic or swarm;
  - verdict: verdict, confidence, video IDs, channel;
  - `evidence`: the agent's one- or two-sentence reasoning;
  - `prior_status`: status before the research pass.
  - `verification`: the adversarial outcome (upheld, revised or refuted) where the row was checked;
  - `verdict_note` and `shared_video`: flags for videos matched to more than one hearing.
- **`research/data/hearing_text_sources.csv`, `meeting_completeness.csv`, `meeting_witnesses.csv`, `house_documents_found.csv`, `house_witnesses_found.csv`, `senate_hearing_pages_found.csv`, `senate_witnesses_found.csv`, `senate_documents_found.csv`:** one row per meeting for where its text is and what it has on the record, and the witnesses, documents and committee pages found outside Congress.gov's records.
- **`research/`:** the agents' briefs and raw results, the Congress.gov meeting records, the channel-search evidence, the Senate channel notes, and scripts. `research/scripts/aggregate.py` rebuilds `hearing_video_verdicts.csv` offline, byte for byte. See `research/README.md`.
- **`packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv`:** the channel list.
- **`apps/committee_youtube/data/youtube_event_id_report.csv`:** the weekly per-channel report (videos, event-ID coverage, captions).
