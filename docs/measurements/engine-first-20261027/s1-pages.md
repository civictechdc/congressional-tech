# S1 page readings and bounded extractor decision

Use locked Trafilatura 2.0.0 for HTML main-content fingerprints. On the existing available sample it retained more substantive pages and produced more equal, nonempty paired results. No further extractor comparison is needed for this choice. Missing bodies limit coverage; these Mac extraction times do not establish Linux backfill speed.

| Existing result | Trafilatura | readability-lxml 0.9 |
|---|---:|---:|
| Nonempty outputs | 3,424 | 3,291 |
| Equal, nonempty candidate endpoints | 1,622 | 1,562 |
| Extraction time, total | 26.090 s | 20.004 s |
| Median per available page | 7.056 ms | 4.492 ms |

DataFusion identified 2,709 paired endpoint candidates and 6,470 unique bodies across the paired and stratified samples. The local cache supplied 3,425 bodies; 3,045 remained unavailable. Each available body was SHA-256 checked. Inspection of 12 Commerce agenda differences and 16 short-page outputs found substantive names and agendas that readability omitted. This is sampled evidence, not S2's several-hundred-file labeled sample.

The current page-reader replay completed all 3,425 available bodies without errors: 397,586,443 input bytes, 303,064 literal links and 3,424 fingerprints. The focused page/sniff/archive/PDF runner has 89 passing checks. Literal link order, repeated links, separate embedded groups, safe XML and owned MODS event IDs are covered. DM §6.2 incorporates embedded-group prefixes and the locked parser timezone.

A bounded additional native join against the retained cache inventory found 212 House XML bodies. Twelve were read and hash-checked successfully: eleven `floorschedule` records and one `committee-meeting`. The only available selected GovInfo ZIP candidate was an empty response; no End of Term candidate body was available in that inventory. These are coverage limits, not successful archive-slice checks. No PDF was read whole and no network body acquisition ran.

S1 stays open for grouping/link SQL, real registry seeds and the required complete semantic slice checks. Existing role SQL matches all 28 committed role fixtures. Grouping expectations are committed before their SQL. Further extractor comparisons are outside the owner-bounded scope.

Evidence retained in scratch: `cx_s1_current_page_*`, `cx_s1_real_retained*`, `cx_s1_real_slice*`, `cx_s1_summary_report.json`, and `cx_s1_roles_joined_retry_report.json`. Earlier rejected wide joins and cache-guard attempts are excluded from the accepted counts.
