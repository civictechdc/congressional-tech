# Meeting-field comparison — November 6, 2026

The selected SpicyRegs generation and the retained candidate agree on Congress and Congress.gov type for all **6,096 matched events**. Meeting **119583** now agrees with its held source detail. All **30 building and 17 room differences** are supported House additions where SpicyRegs states no value, at the same sitting start. Five source-update differences remain explicit; event **338794** also differs by 30 minutes in its sitting start.

This is local candidate evidence. Published release `e145d24c389e` retains its missing 119583 detail. Private candidate `720c495b66d1691ee270dadb45c752f1c47d997c9fbe561dbbd039be15786b2f`, built at source `5d1a8779faedf2ddae3a77fd75ad4e624966be6a`, predates later model changes and is not the final current-main release. The release owner must qualify the actual final output and its readers. [Exact comparison and raw evidence](../../.cache/archive-release/implementation/reviewed-non-news-20261106/ct-r4rd/selected-comparison.json)

## Exact inputs and field meanings

Both comparisons use SpicyRegs generation `37a6ebd400a610e0928cc52bd2528cd63ed3f78ba44e1c73663559a7b773554f`, published October 31, with **6,099 events**. Its retained Parquet SHA-256 is `406707300c3ebb5131c957216f216a628e44b749c15ad201522ff20226063b59` (3,517,953 bytes). The adapter retained this small input in the main checkout's evidence directory; it copied no shared corpus into a worktree.

| Input | Exact identity |
| --- | --- |
| Published archive | `e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99`; meetings SHA-256 `277f58a50075460db697d78a035a87c1b36e4f8b69afb01747542767d07ce5af` |
| Private candidate | `720c495b66d1691ee270dadb45c752f1c47d997c9fbe561dbbd039be15786b2f`; meetings SHA-256 `03bb6276a4f185f07fb1b68fab1bb42c3942d4897a43d566c235ee548106d016` |
| Maintained upstream comparator | SpicyRegs commit `519ffb308fd798d5d3c42c4d73a72b3248318a26`; script SHA-256 `7e20281af61f4797b03c6b0dbcc3787df3484018a73e1e2df0e7f9e11160ac63` |

| SpicyRegs field | Archive destination and comparison |
| --- | --- |
| `congress` | `meetings.congress`, by numeric event ID |
| `update_date` | `meetings.congress_gov_updated`, same UTC instant as Congress.gov `updateDate` |
| `meeting_type` | `meetings.congress_gov_meeting_type`, the equivalent Congress.gov label |
| `location_building` | `meetings.sittings[].building` at the unique identical start instant |
| `location_room` | `meetings.sittings[].room` at that same start |

The mixed `meetings.meeting_type` also carries House XML codes and remains useful. Missing, different, or duplicate sitting starts prevent a location comparison; list order never chooses a corresponding sitting. Committee names and URLs resolve through `committees.system_code`. Detail-read observations stay with `ct-tbrj`; document keys stay with `ct-mt0h`.

## Results and dispositions

| Measure | Published e145 | Private 720c |
| --- | ---: | ---: |
| Matched events | 6,091 | 6,096 |
| Congress differences | 1 | 0 |
| Equivalent type differences | 1 | 0 |
| Source-update differences | 6 | 5 |
| Building differences, all supported House fill | 30 | 30 |
| Room differences, all supported House fill | 17 | 17 |
| Events with a residual | 52 | 51 |

These counts are neither defect totals nor a complete parity pass. Five previously missing in-window meetings are present in 720c. The selected 37a6 source still has three unmatched events: `119588` is after the observed archive window; `338764` and `338786` have the retained 404/source dispositions owned by coverage work. The earlier candidate comparison used different source generation `fbf53579` (6,098 rows), yielding 11 update differences and only two unmatched events. Its counts must not replace the selected 37a6 comparison. [Prior source dispositions](../../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/source-coverage/coverage-ledger.json) · [Coordinator's candidate handoff](../../.cache/archive-release/implementation/production-mvp-20261105T190929Z/combined-release-prep/cross-session-release-handoff-20261106.md)

### Meeting 119583

The held response's decoded SHA-256 is `a720069d93fd6d76f56d6387f32b96abb6a5f35934ad959ac71d75e6df012d2e`. Its stored-byte hash, receipt identity, and staged producer pin remain in the accepted [input freeze](../../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/source-coverage/source-coverage-freeze-inputs.json).

| Value | Held raw response, SpicyRegs 37a6, and private 720c |
| --- | --- |
| Congress | 119 |
| Congress.gov type | Hearing |
| Source `updateDate` | `2026-10-15T10:41:10Z` |
| Sitting start | `2026-10-23T14:00:00Z` |
| Building / room | Neither field stated |

The published e145 row has no Congress, equivalent type, update or sitting. This was an input-selection gap, already repaired in the retained stage and candidate. No additional parser replay was needed here. A planted Congress value of 118 fails the raw comparison. The raw response also contains a field-address JSON string; this report makes no address-parity claim because 720c does not select it into the public sitting.

### Newer SpicyRegs source versions

Each event below has an older archive source update in both inspected archive outputs. Their Congress and type agree. Four have the same sitting start. The remaining start difference stays unresolved against the newer detail; it is not evidence of a time-zone parser defect.

| Event | Archive `updateDate` (UTC) | SpicyRegs `updateDate` (UTC) | Disposition |
| --- | --- | --- | --- |
| 119260 | `2026-09-29 13:48:22+00:00` | `2026-10-30 00:35:19+00:00` | Same sitting and location. |
| 119549 | `2026-09-28 14:18:21+00:00` | `2026-10-21 21:18:22+00:00` | Same sitting and location. |
| 119575 | `2026-09-29 23:48:37+00:00` | `2026-10-06 14:41:31+00:00` | Same sitting; archive building is supported House fill. |
| 338792 | `2026-09-26 02:08:23+00:00` | `2026-09-28 22:08:22+00:00` | Same sitting and location. |
| 338794 | `2026-09-26 02:08:23+00:00` | `2026-10-01 00:08:27+00:00` | Archive start 14:30 UTC; newer source start 15:00 UTC on October 1. Location comparison withheld. |

The separate document-reference review leaves event `119575`'s exact Congress.gov raw version unqualified and its null document references unaccepted as empty. The supported House building does not resolve that independently owned gap. [Document-reference disposition](../../.cache/archive-release/implementation/production-mvp-20261105T190929Z/combined-release-prep/candidate-acceptance/720c495b-independent/HANDOFF.md)

Retain these source versions. Any later refresh belongs to the maintained detail-acquisition/publication path; compare the resulting exact detail before changing a producer or claiming convergence.

### House location fills

All 47 event bodies were read from the held mirror and checked by decoded digest, event ID, selected House update, raw local time interpreted in Eastern time, and the exact corresponding archive start. The raw field value equals the populated archive field. The upstream equivalent field is absent. Room text such as `CLOSED` is preserved as a source statement; this is not a claim that it names a physical room. These additions preserve the accepted Congress.gov-first rule with House filling a missing field on a matching sitting. The same 47 values survive in both archive outputs. The JSON evidence records each body path, digest, raw value and start.

| Event | Filled field | Raw House value |
| --- | --- | --- |
| 115299 | building | Allegheny Wood Products, INC |
| 115382 | room | 2167 |
| 115407 | building | Express Clydesdales |
| 115476 | building | South Texas College Regional Center for Public Safety Excellence |
| 115881 | building | Global Container Terminals New York |
| 115915 | room | 2175 |
| 116139 | building | Champions Club Parc Stadium |
| 116155 | building | Belmont University, Gabhart Student Center, Multipurpose Room A/B |
| 116215 | building | Goodyear Recreation Center |
| 116220 | room | 2175 |
| 116380 | building | Council on Foreign Relations |
| 116562 | room | 360 |
| 116788 | room | 2167 |
| 117059 | building | Lake Cumberland State Resort Park |
| 117060 | building | Lake Cumberland State Resort Park |
| 117471 | room | 2318 |
| 117697 | room | 2123 |
| 117852 | room | 2318 |
| 118122 | building | Wilbur J. Cohen Federal Building Auditorium |
| 118541 | building | Ronald Reagan Presidential Library |
| 118553 | building | Jenny Lake Visitors Center |
| 118585 | room | 1100 LHOB |
| 118599 | room | 1324HR |
| 118607 | room | 1100 LHOB |
| 118662 | room | 2020 RHOB |
| 118675 | room | 1100 LHOB |
| 118719 | room | 1100 LHOB |
| 118895 | room | 2128 |
| 118931 | building | Green Valley Enterprises |
| 119025 | room | CLOSED |
| 119032 | building | Central Arkansas Library System (CALS) |
| 119051 | building | United States Mission to the United Nations |
| 119135 | building | Lake Erie College of Osteopathic Medicine |
| 119249 | building | Vincennes University Gibson County Center for Advanced Manufacturing and Logistics |
| 119326 | building | The Arlington Hotel |
| 119376 | building | Grand Ledge Army Aviation Facility |
| 119382 | building | Vast |
| 119460 | building | Georgia Cyber Innovation and Training Center, Hull McKnight Building, Augusta University |
| 119461 | building | Federal Hall National Memorial |
| 119501 | building | Richmond City Hall |
| 119513 | building | Flight 93 National Memorial |
| 119533 | building | College of the Canyons Performing Arts Center |
| 119539 | building | Charlotte Marriott City Center, Uptown Ballroom, 1st/2nd Ward |
| 119551 | room | 2167 |
| 119564 | building | Center for the Arts, Eastern Kentucky University |
| 119569 | building | Old Parkland |
| 119575 | building | Orgill Innovation Center |

Event `119063` is separate: SpicyRegs room `----------` and the archive's absent room both mean no stated room. Event `334445` is leading whitespace: building ` SD` versus `SD`; room 106 agrees. The comparator retains both formatting cases separately from substantive differences.

## Parser trace and verification

The [independent raw sitting tally](explorer-raw-sittings-20261101.json) read 6,165 Congress.gov and 6,179 House records with none unread. It established 4-hour summer and 5-hour winter offsets, 6,157 Congress.gov starts, 107 House building fills and 146 House room fills. Those historical counts concern that frozen cohort, not a new corpus run. The [published release record](../releases/2026-11-05-e145d24c389e.md) and retained transition preserve all 42,551 meeting rows while advancing 6,180 House version stamps with **zero XML payload replays**.

| Output | Congress.gov parser | House XML parser |
| --- | --- | --- |
| e145 | `ecc51fcdb572b426da01a9135b467bf3f9a85e91d268ff895a56e2dda5ef716e` | `8a2417a2c876b2cd3f202ed92dfbc48bca580f7fa2848d6644310771484617c8` |
| 720c | `325702c1794f246323ed30d7430650355121dd4891a7cea62b44a34a8ae5084d` | `684f3663274217a2c24a19a5a71887aa0f5f9f8c61dc5a590959e48ab84dd24b` |

The accepted first-wave record-only stage at `75c992547b2c81127653383398fb45d78bf8974c` moved to the latter versions. Its own 42,551-row verification records 27,462 selected rows replayed, 15,089 reused and prior meeting fields preserved. This task reuses that qualified result; it performed no producer replay. The selected House record artifact is SHA-256 `475fa09b5ed1076e5590158245ee13118bff656dc8c95f40533eaaf3bb171523`. [Stage verification](../../.cache/archive-release/implementation/production-mvp-20261105T190929Z/reader-metadata/integration-meeting-appearance-meeting_records.verification.json)

The bounded adapter reuses the unmodified `_rows` and `meeting_detail_agreement` functions from the checked upstream script. It reproduced every original e145 meeting-detail count and residual value before comparing the private candidate. It verified source/table hashes, the candidate manifest's release identity, and all 47 held House bodies. It changed no sibling checkout. [Adapter](../../.cache/archive-release/implementation/reviewed-non-news-20261106/ct-r4rd/compare_selected.py) · [Focused checks](../../.cache/archive-release/implementation/reviewed-non-news-20261106/ct-r4rd/focused-tests.log) · [Independent review](../../.cache/archive-release/implementation/reviewed-non-news-20261106/ct-r4rd/review.md)

Six existing summer/winter, field-location and placeholder tests passed through this worktree's `scripts/dev.py test production-offline` entry point. This was a **partial lane**, not a full-lane result. The prior five-test upstream comparator qualification remains reusable because the accepted script bytes match. Independent review verifies the raw values and wrong-Congress plant separately.

## Remaining integration

`ct-r4rd` remains open. Upstream `ss-ikn9` owns integration of SpicyRegs comparator commit `519ffb308fd798d5d3c42c4d73a72b3248318a26`. The final release owner must compare the same source generation to the actual final meeting output, preserve residual dispositions, and verify 119583 through selected readers. Reuse this result when the relevant meeting bytes and parser identities still match. Keep the five newer-source cases explicit. No full build, source request, shared-catalog write, publication, deployment, pointer change or scheduler action occurred in this task.
