# Efficiency and debt follow-up

Twelve efficiency and debt follow-ups are resolved: nine implemented changes and three measured optimization proposals rejected. The final integrated changes passed 251 local tests and seven subtests, followed by independent source and evidence review.

The changes reduce repeated durability work, remove one duplicate read after an uncertain mapping write, bound recovery downloads, and make publication failures easier to diagnose. Three proposed optimizations were measured and rejected because their overall cost did not improve enough to justify added complexity.

| Area | Result | Evidence and limit |
| --- | --- | --- |
| Local event persistence | One event owner replaces duplicate state and journal writes. | In three paired 128-write fixtures, disk syncs fell from 783 to 276 and serialized characters from 5,493,025 to 511,187. State and payload hashes match. Retained scratch grows from 117,247 to 245,262 bytes. |
| Cloud checkpoints | Compact serialization and one verified-version checkpoint. | Three normal-path fixture medians: 3.564 to 2.931 seconds. Remote request counts are unchanged; resume timing did not consistently improve. |
| Mapping lost acknowledgment | Reuse an exact current readback receipt. | Plain-client fixture drops from three GETs to two and 206 to 119 received bytes, with the same conditional PUT and result. Guarded-client counts are unchanged. |
| Mandatory recovery loading | Bounded stream and deadline use the shared reader. | A 4 MiB overrun consumes only 64 KiB in the test; oversized declared input makes no fetch. These are input/read bounds, not a browser heap guarantee. |
| Explicit workflow resume | One validated original-attempt descriptor replaces five manual fields. | Exact UTF-8 bytes, original revision and artifact identity survive checkout. Local validation becomes slower, 12.15 to 19.73 ms; this is an assurance and usability improvement. |
| Runtime selection | One selected project source tree before admission. | All eight unsafe source-owner cases refuse before admission/client creation. More complete pins add 330,101 bytes of hashing input; no speed gain claimed. |
| Failed catalog builds | Retained path, accepted phase and exact read-only next checks. | Diagnostic failures preserve the original build error. No automatic rebuild or new source acquisition. |
| Recovery progress | One bounded, input-bound latest observation. | Three paired scans preserve all current reads and proof/state values; the fixture adds 17 local replacements and 565 retained bytes. It reports progress without authorizing replay. |
| Shared accepted publication plan | Local and cloud routes reuse accepted file and recovery results. | Known complete output hash helper passes fall from 823 to 270, with identical payloads and results. The tiny candidate is slower and adds three GETs and syncs; no speed or memory improvement is claimed. |
| Search | Retain the exact scan after rejecting the cache candidate. | No useful warm improvement; cold queries and memory regressed. |
| Exact-value export | Retain exact values and explicit failure behavior. | The proposed Blob route increased known storage by 25.9%. Logical counters are not a hard heap limit. |
| Catalog memory | Retain the current implementation after rejecting packed members. | Only small memory reductions with slightly slower publication on the bounded fixture. Nested source occurrences were typed null; this does not qualify the complete live catalog. |

Local tests and independent reviews are the merge gates. Full backend, live catalog and browser qualification already accepted earlier were not repeated. The relocated full-suite run recorded 9,457 passes, 38 subtests, 50 deselections and two failures; targeted repairs passed, but that run is not described as a clean full-suite pass.

Historical grades and qualification remain separate from the current, scoped rescore. Closing a measured experiment does not mean its underlying performance debt disappeared. External cleanup removed some old ignored publication evidence before the user stopped it; tracked historical reports remain, while current efficiency evidence is retained separately.

Savings accumulate when the affected operations recur, but the fixture percentages cannot be added: local event persistence and cloud checkpointing are different routes. The useful aggregate is fewer repeated syncs, serialized state bytes and avoidable GETs per applicable operation. End-to-end production savings depend on the number of writes, uncertain acknowledgments and resumed scans; this work does not invent that workload.

## Evidence and assessment

The source and measurement reports are [local events](local-events.md), [cloud checkpoints](checkpoints.md), [mapping writes](mappings.md), [recovery loading](recovery.md), [workflow resume](workflow-resume.md), [runtime ownership](runtime-ownership.md), [failed catalog builds](incomplete-build.md), [reconciliation progress](reconciliation.md), [accepted publication plans](accepted-plan.md), [search](search.md), [complete export](complete-export.md) and [Catalog memory](catalog.md). Each records its baseline, measurement limits and test evidence.

Independent [rescore supplements](rescore/index.json) preserve the historical 168-row assessment and distinguish changed grades from retained debt. The final architecture addendum explains what these changes improve and what remains expensive. Ticket closure records completion of the scoped work, including rejected experiments; it does not mean every function now grades B+ or higher.

PRs 132 and 133 integrated the completed external script/test relocation work. PRs 134 through 137 merged the first eleven efficiency follow-ups. The final accepted-plan change and this assessment are the last integration batch. This report covers implementation and local verification. Consult `output/efficiency-debt-20261019/completion.json` in the primary checkout for the current merge and cleanup status.
