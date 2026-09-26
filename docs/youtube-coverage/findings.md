# Committee hearings on YouTube: coverage findings

*September 2026. Covers House, Senate and joint committee hearings from the 113th Congress (2013) through the 119th (to date). The numbers come from the weekly matcher (`gpo-match`); the original research-pass snapshot is kept in `hearing_video_verdicts.csv`.*

## Summary

We compared every official hearing transcript that GPO has published since 2013 against the videos on every official committee YouTube channel we could find: 119 channels for 52 committees and commissions, holding 67,244 videos. The matching combines automatic evidence (Congress.gov video links, event IDs and dates in video text, upload-window title similarity) with the reviewed verdicts of a 16-agent research pass and a 6-agent adversarial verification. For the Senate, which hosts its own video, it also checks the Senate's player. It runs every week, so these numbers move as committees upload.

**House and joint committees (9,643 hearings):**

<!-- table:house_summary -->
| Outcome | Hearings | Share |
|---|---|---|
| Full recording on a tracked committee channel | 8,687 | 90.1% |
| Full recording only on another YouTube channel (member, news, third party) | 67 | 0.7% |
| Only clips or opening statements on YouTube | 374 | 3.9% |
| Never public video (closed session, written-only volume, errata) | 55 | 0.6% |
| No video found | 443 | 4.6% |
| Held before the committee's earliest tracked video | 17 | 0.2% |
<!-- /table:house_summary -->

The gaps are almost entirely historical. **Since the 116th Congress (2019), 98.6% of House and joint hearings have a full recording on YouTube.** Only 42 hearings since 2019 have no video found; among them are field hearings and Appropriations placeholder records.

**Senate committees (5,835 hearings):**

<!-- table:senate_summary -->
| Outcome | Hearings | Share |
|---|---|---|
| Full recording on a tracked committee channel | 345 | 5.9% |
| Full recording off YouTube (senate.gov, C-SPAN, an archive) | 5,119 | 87.7% |
| Only clips or opening statements on YouTube | 13 | 0.2% |
| Never public video (closed session, written-only volume, errata) | 49 | 0.8% |
| No video found | 211 | 3.6% |
| Held before the committee's earliest tracked video | 23 | 0.4% |
| Committee has no YouTube channel | 75 | 1.3% |
<!-- /table:senate_summary -->

**Senate hearings are on the Senate's own player, not YouTube.** The Senate Recording Studio hosts committee video at senate.gov and names each recording after the committee and date. Congress.gov links those recordings from Senate meeting records since late 2023 (1,381 links, none to YouTube, while all 7,538 House links go to YouTube). For everything earlier or unlinked, a probe of the player by committee and date found recordings for 4,786 of 5,115 hearings. Senate committees' YouTube channels are party channels carrying members' statements and a selection of hearings; only Environment and Public Works' Democrats have livestreamed hearings there since 2011.

Where older House hearings are missing, the main causes are:
- **They were never uploaded to YouTube.** Before 2015 many committees streamed on Ustream, Windows Media or Facebook, and those recordings are gone or not on YouTube.
- **Committees later made the videos private or deleted them.** This hit Education & Workforce (2013–14) and Veterans' Affairs (mid-2014 to 2015).
- **Only clips were posted.** Homeland Security (2013–15) and Foreign Affairs (April 2014 to August 2015) posted opening statements rather than full hearings.

Most of what looked missing wasn't. Committees bulk-uploaded their archives months or years after the hearings, under titles like "7/23/2013. EMR. 10:00 AM", "Markup: H.R. 2848", "W&M Hearing: Feb 26, 2014", or a date code plus an EventID. The research pass found 1,278 of these; the matcher's event-ID and date rules now find them automatically, and found a further 134 that the research pass had marked as clips only or no video, almost all of them Ways and Means hearings.

## House and joint coverage by Congress

"Found" is the share with a full recording, on a tracked channel or elsewhere.

<!-- table:house_congress -->
| Congress | Years | Hearings | Full recording | Clips only | Not public | None found | Found |
|---|---|---|---|---|---|---|---|
| 113th | 2013–14 | 1,791 | 1,229 | 276 | 17 | 256 | 68.6% |
| 114th | 2015–16 | 1,716 | 1,539 | 76 | 23 | 76 | 89.7% |
| 115th | 2017–18 | 1,482 | 1,395 | 15 | 2 | 69 | 94.1% |
| 116th | 2019–20 | 1,404 | 1,370 | 4 | 4 | 25 | 97.6% |
| 117th | 2021–22 | 1,163 | 1,150 | 1 | 5 | 7 | 98.9% |
| 118th | 2023–24 | 1,439 | 1,428 | 1 | 2 | 8 | 99.2% |
| 119th | 2025– | 648 | 643 | 1 | 2 | 2 | 99.2% |
<!-- /table:house_congress -->

The 17 hearings held before a committee's earliest tracked video (14 of them the Congressional-Executive Commission on China's) are counted in the totals but not in the other columns.

## House and joint coverage by committee

Sorted from least to most complete. Committees with fewer than 5 GPO hearings are omitted (Intelligence prints few hearings, for example). "Senate Veterans' Affairs" here is six House hearings GPO filed under the Senate committee's code.

<!-- table:house_committee -->
| Committee | Hearings | Full recording | Clips only | Not public | None found | Found | Found since 2019 |
|---|---|---|---|---|---|---|---|
| Select Committee on Benghazi | 15 | 4 | 0 | 11 | 0 | 27% | — |
| Helsinki Commission | 202 | 109 | 8 | 1 | 84 | 54% | 91% of 90 |
| Joint Economic Committee | 96 | 71 | 25 | 0 | 0 | 74% | 100% of 32 |
| Homeland Security | 533 | 403 | 111 | 1 | 18 | 76% | 100% of 284 |
| Congressional-Executive Commission on China | 71 | 55 | 0 | 2 | 0 | 77% | 100% of 40 |
| Education & Workforce | 388 | 315 | 23 | 10 | 40 | 81% | 99% of 223 |
| (no committee code in GPO data) | 17 | 14 | 0 | 2 | 1 | 82% | 83% of 12 |
| Senate Veterans' Affairs (House hearings, miscoded) | 6 | 5 | 1 | 0 | 0 | 83% | 100% of 1 |
| Armed Services | 678 | 567 | 28 | 0 | 83 | 84% | 99% of 284 |
| Veterans' Affairs | 456 | 382 | 29 | 2 | 43 | 84% | 100% of 206 |
| Appropriations | 308 | 263 | 2 | 24 | 19 | 85% | 91% of 140 |
| Ways and Means | 269 | 238 | 14 | 0 | 17 | 88% | 100% of 83 |
| Transportation and Infrastructure | 428 | 381 | 15 | 0 | 32 | 89% | 100% of 238 |
| Foreign Affairs | 1,000 | 915 | 64 | 0 | 20 | 92% | 99% of 348 |
| Small Business | 503 | 467 | 4 | 0 | 32 | 93% | 94% of 261 |
| Judiciary | 651 | 605 | 23 | 0 | 23 | 93% | 100% of 366 |
| Select Committee on the Climate Crisis | 43 | 41 | 0 | 0 | 1 | 95% | 95% of 43 |
| Natural Resources | 449 | 431 | 9 | 1 | 8 | 96% | 98% of 253 |
| House Administration | 190 | 183 | 2 | 0 | 5 | 96% | 98% of 129 |
| Budget | 85 | 83 | 2 | 0 | 0 | 98% | 98% of 60 |
| Financial Services | 731 | 719 | 3 | 0 | 9 | 98% | 98% of 394 |
| Oversight and Government Reform | 910 | 896 | 7 | 0 | 7 | 98% | 100% of 466 |
| Agriculture | 220 | 217 | 1 | 1 | 1 | 99% | 100% of 119 |
| Energy & Commerce | 868 | 866 | 2 | 0 | 0 | 100% | 100% of 324 |
| Science,Space,and Technology | 474 | 473 | 1 | 0 | 0 | 100% | 100% of 210 |
| Rules | 18 | 18 | 0 | 0 | 0 | 100% | 100% of 16 |
| Select Committee on the January 6th Attack | 10 | 10 | 0 | 0 | 0 | 100% | 100% of 10 |
| Select Committee on the Modernization of Congress | 21 | 21 | 0 | 0 | 0 | 100% | 100% of 21 |
<!-- /table:house_committee -->

Notes:
- **Benghazi:** 11 of its 15 GPO volumes are closed-door transcribed witness interviews, so there is no public video to find.
- **Helsinki Commission:** most of its 2013–2019 GPO "hearings" are staff briefings. Its website embeds recordings of 31 of them from the Commission's Facebook page, not YouTube.
- **Appropriations:** the "not public" rows are printed volumes that contain only written testimony, budget justifications or answers for the record.
- **Clips only** now means what it says. A video under 10 minutes found by weak evidence (a date window or a date in the title) counts as a clip. The research-pass snapshot counted some of those as recordings, which is why Homeland Security, Foreign Affairs and the Joint Economic Committee show more clips here.

## Senate coverage

The Senate numbers cover 16 committees with 32 YouTube channels, found by checking each committee's website and searching YouTube for the committee, its party caucuses and its chairs since 2007 (notes in `research/data/senate_channels.csv`), plus the Senate's own player. "On senate.gov" counts recordings found there, through Congress.gov's links or the archive probe (`research/scripts/as_run/senate_isvp_probe.py`); "Full recording" includes them.

<!-- table:senate_congress -->
| Congress | Years | Hearings | Full recording | Clips only | Not public | None found | On senate.gov | Before channel | No channel | Found |
|---|---|---|---|---|---|---|---|---|---|---|
| 113th | 2013–14 | 987 | 935 | 3 | 2 | 30 | 928 | 17 | 0 | 94.7% |
| 114th | 2015–16 | 1,010 | 913 | 4 | 16 | 69 | 909 | 0 | 8 | 90.4% |
| 115th | 2017–18 | 960 | 903 | 3 | 6 | 41 | 901 | 2 | 5 | 94.1% |
| 116th | 2019–20 | 696 | 659 | 3 | 5 | 26 | 647 | 0 | 3 | 94.7% |
| 117th | 2021–22 | 1,051 | 1,004 | 0 | 17 | 23 | 916 | 0 | 7 | 95.5% |
| 118th | 2023–24 | 794 | 753 | 0 | 1 | 18 | 592 | 4 | 18 | 94.8% |
| 119th | 2025– | 337 | 297 | 0 | 2 | 4 | 226 | 0 | 34 | 88.1% |
<!-- /table:senate_congress -->

By committee, sorted from least to most complete. "Veterans' Affairs" at the bottom is seven joint House–Senate veterans' service organization hearings printed by the Senate under the House committee's code.

<!-- table:senate_committee -->
| Committee | Hearings | Full recording | Clips only | Not public | None found | On senate.gov | Before channel | No channel | Found | Found since 2019 |
|---|---|---|---|---|---|---|---|---|---|---|
| (no committee code in GPO data) | 66 | 0 | 0 | 0 | 0 | 0 | 0 | 66 | 0% | 0% of 60 |
| Joint Select Solvency of Multiemployer Pension Plans | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0% | — |
| Small Business and Entrepreneurship | 146 | 108 | 0 | 1 | 32 | 102 | 5 | 0 | 74% | 81% of 80 |
| Veterans' Affairs (joint hearings, House code) | 7 | 6 | 0 | 0 | 1 | 0 | 0 | 0 | 86% | 86% of 7 |
| Aging | 196 | 174 | 0 | 9 | 12 | 161 | 1 | 0 | 89% | 96% of 103 |
| Energy and Natural Resources | 434 | 388 | 11 | 5 | 30 | 365 | 0 | 0 | 89% | 95% of 212 |
| Veterans' Affairs (Senate) | 184 | 165 | 0 | 2 | 17 | 165 | 0 | 0 | 90% | 93% of 114 |
| Appropriations | 625 | 565 | 0 | 2 | 52 | 565 | 6 | 0 | 90% | 89% of 260 |
| Environment and Public Works | 426 | 404 | 0 | 3 | 19 | 299 | 0 | 0 | 95% | 99% of 227 |
| Homeland Security and Governmental Affairs | 491 | 469 | 1 | 13 | 8 | 468 | 0 | 0 | 96% | 95% of 211 |
| Rules and Administration | 46 | 44 | 0 | 1 | 0 | 44 | 0 | 1 | 96% | 97% of 37 |
| Indian Affairs | 185 | 178 | 0 | 0 | 7 | 172 | 0 | 0 | 96% | 99% of 74 |
| Commerce, Science, and Transportation | 570 | 550 | 1 | 1 | 18 | 484 | 0 | 0 | 96% | 99% of 270 |
| Budget | 87 | 84 | 0 | 2 | 1 | 73 | 0 | 0 | 97% | 99% of 69 |
| Foreign Relations | 436 | 426 | 0 | 3 | 0 | 426 | 7 | 0 | 98% | 96% of 182 |
| Health, Education, Labor, and Pensions | 322 | 316 | 0 | 1 | 5 | 295 | 0 | 0 | 98% | 99% of 134 |
| Armed Services | 346 | 340 | 0 | 4 | 0 | 339 | 0 | 2 | 98% | 99% of 177 |
| Judiciary | 277 | 273 | 0 | 0 | 0 | 273 | 4 | 0 | 99% | 100% of 152 |
| Banking, Housing, and Urban Affairs | 444 | 438 | 0 | 1 | 5 | 359 | 0 | 0 | 99% | 98% of 234 |
| Finance | 307 | 303 | 0 | 0 | 4 | 303 | 0 | 0 | 99% | 99% of 138 |
| Select Intelligence | 77 | 76 | 0 | 0 | 0 | 76 | 0 | 1 | 99% | 97% of 37 |
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
- **Still missing:** 17 hearings, mostly 2015–16 field hearings and subcommittee hearings the 2019 upload skipped. The WordPress site's 2016–18 hearing pages embed YouTube IDs that are now private or deleted.
- **Elsewhere:** a few 2014 trade subcommittee hearings survive only on Devin Nunes's channel, 2016 tax hearings on the Tax Revolution Institute's, and one each on the Foster Youth Caucus, the City of Auburn and news channels.

**Education & Workforce (2013–14).** Every hearing page on edworkforce.house.gov links an "Archived Webcast" YouTube video, but all of those videos are now private. Only member clips (mostly Rep. Rokita's) remain public.

**Veterans' Affairs.**
- **Late uploads (found):** `@HouseVetsAffairs` bulk-uploaded 2013 to April 2014 hearings in July 2014, and early-2015 hearings in 2016, under titles like "4/9/14 FC".
- **Lost:** about 30 of the committee's original uploads from mid-2014 through 2015 are now private or deleted. Mid-2015 hearings were streamed on Ustream only.
- **Field hearings:** where they exist at all, they are on local community TV channels.

**Armed Services (2013–14).** Hearings were streamed live but never archived publicly. The channel's public uploads start in January 2015, apart from about 11 hearings back-uploaded later. Some full recordings survive on DARPA's channel, a third-party DoD video archive (`@Galactic007A`), and a witness's channel. The 2009–2012 Republican channel `@HASCRepublicans` has earlier hearings.

**Homeland Security (2013 to mid-2015).** The majority channel only began posting full hearings in September 2015. Before then, the Democrats' channel posted only the ranking member's opening statements, so 108 hearings from the 113th and 114th Congresses are clips-only.

**Foreign Affairs.**
- **Late uploads (found):** `@HouseForeignGOP` re-uploaded many 2012–2015 hearings in 2016 with "(EventID=…)" in the titles.
- **Clips only:** from April 2014 to August 2015 it posted only chair clips. Where the 2016 archive skipped an event, only clips remain.
- **Markups:** these are titled by bill number only ("Markup: H.R. 2848").

**Transportation and Infrastructure (2013–2015).** Hearings streamed on Ustream, and the recordings embedded on the committee site no longer play. `@transport` posted member clips and a few hand-picked full hearings until it started livestreaming in March 2014.

**Natural Resources.**
- **2013–14 back catalogue:** the Republican channel uploaded it in 2015–16, titled only with a date and subcommittee code ("7/23/2013. EMR. 10:00 AM"). The real title is in the description.
- **Since 2019:** titles are generic ("Oversight Hearing | Full Committee"). The EventID in the description settles them.
- **Missing:** six 2013–14 hearings were never uploaded.

**Judiciary.** `@JudiciaryDems` uploaded its 2012–2015 archive in September–November 2015 with "(EventID=…)" titles. That covers about 60% of the period. The rest have only member clips.

**Financial Services, Science, Budget, House Administration, Agriculture, Appropriations.** Each bulk-uploaded its 2011–2015 archive in 2015–2018, with EventIDs or date codes in titles and descriptions. Almost everything is there; it was just posted outside the original matcher's date window.

**Small Business.** Field hearings were almost never posted by the committee. When they exist at all, they are on local community TV or news channels.

**Joint Economic Committee (2013–14).** Only 4–10 minute member clips were posted. Two hearings were uploaded years later, one of them seven years after it was held.

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
- **GPO committee codes had typos and blanks.** `gpo-fetch` now fixes known typos, fills blank codes from the committee name where it can, marks errata sheets, and reads each hearing day out of multi-hearing Appropriations volumes.

## Problems found in GPO's metadata

The research pass turned up many GPO records whose metadata doesn't match the transcript. These are worth reporting to GPO, and matching against GPO data has to allow for them:

- **Wrong held dates.** Often GPO used a date that appears in the title, or the date of the incident the hearing was about. Examples:
  - CHRG-113hhrg88456 (Taliban detainee transfer) is dated May 31, 2014, but was held June 11, 2014.
  - CHRG-116hhrg40718 (Lafayette Square) is dated the day of the incident; the hearings were June 29 and July 28, 2020.
  - Both H. Res. 755 impeachment markup packages are dated January or July 2019 but ran December 11–13, 2019.
  - CHRG-117hhrg49370 is dated 2021 but was held in 2022.
- **Missing dates.** Four Senate records have no held date at all; the matcher reports them as "no video found" with a note.
- **Placeholder dates on Appropriations volumes.** Multi-hearing volumes carry the first day of the Congress (e.g. 2021-01-01) as their held date. `gpo-fetch` now reads the real hearing days from the transcript, except for the quarter of volumes that are scanned PDFs with no text.
- **Wrong or missing committee codes.** For example:
  - an impeachment hearing is coded as Appropriations;
  - an air traffic control hearing is filed under Appropriations but belongs to Transportation and Infrastructure;
  - a 2019 House Veterans' Affairs subcommittee hearing (CHRG-116hhrg48810) is coded as the Senate committee;
  - 22 Helsinki hearings, 15 other House records and 66 Senate records have a blank code;
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

### The weekly matcher

- **One video per hearing.** Each video is assigned to its best-evidenced hearing; hearings on different days can't share one. This retires the research snapshot's 74 "unconfirmed" automatic matches, where the old matcher had given one video to consecutive-day hearings with similar titles. Thirty-nine hearings share a video with another hearing on the same day (joint hearings, or several GPO packages for one proceeding) and are flagged.
- **Research verdicts are kept unless outweighed.** A reviewed "found" verdict always stands. A reviewed "no video" or "clips only" verdict gives way only to strong evidence (a Congress.gov link or event ID) or to a dated recording of 30 minutes or more, and rows the verifiers rejected are locked.
- **Spot check of the overturned verdicts.** A random sample of the Ways and Means re-uploads was checked by hand: each is a 90–200 minute video titled with the hearing's date, and the description carries a `YYMMDD` code that confirms the date where the title has a typo.

**Known limitations:**
- **Multi-hearing volumes count as found if any hearing day in them has video.** The `volume_days_with_video` flag says how many days were covered.
- **Some archive uploads are audio only.** A few of Appropriations' 2015 archive uploads say "This is an audio recording" and are flagged `audio_only`.
- **Automatic matches weren't individually re-verified.** The 7,399 automatic matches got the one-video-per-hearing check and spot checks during development.
- **Senate recordings are confirmed by name, not content.** The senate.gov probe checks that a recording exists for the committee and day; it doesn't tell same-day hearings apart or check length.

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
  A video under 10 minutes found by the weaker rules counts as a clip. Multi-hearing Appropriations volumes are matched on each hearing day.
- **Research pass:** 16 agents, one per batch of 113–162 hearings grouped by committee. They worked from prepared evidence packets:
  - the hearing metadata;
  - every video from that committee within a few days;
  - Congress.gov meeting records.

  They also used YouTube search, in-channel search, committee websites and the transcripts, through a shared, rate-limited, cached client.
- **Verification:** 6 more agents, described under Verification above.
- **Verdict rules:**
  - "Full recording" means the proceeding itself (livestream, full upload, or all its parts), not clips or statements.
  - "Not public" requires evidence: a "CLOSED" notice, a written-only volume, an errata page, or closed-door interviews.
- **Not reachable from the research environment:** the Wayback Machine, C-SPAN, and YouTube watch pages (bot-walled). Some recordings may exist there or in private archives.

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
- **`research/`:** the agents' briefs and raw results, the Congress.gov meeting records, the channel-search evidence, the Senate channel notes, and scripts. `research/scripts/aggregate.py` rebuilds `hearing_video_verdicts.csv` offline, byte for byte. See `research/README.md`.
- **`packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv`:** the channel list.
- **`apps/committee_youtube/data/youtube_event_id_report.csv`:** the weekly per-channel report (videos, event-ID coverage, captions).
