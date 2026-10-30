---
id: cefr-7sar
status: closed
deps: []
links: []
created: 2026-10-27T17:09:26Z
type: task
priority: 2
assignee: raw
---
# D1: rebuild captures from every receipt shape through native jobs

Owner reassigned D1 to raw in run2. Follow current DM6.1; message engine before changing a column or rule.

## Acceptance Criteria

Native receipt mapping covers all shapes and status/time/completeness; rebuild-equivalence passes; pinned old-index comparison has written transformations and lists owner-only rows; local append races covered; live lake writes owner-gated.


## Notes

**2026-10-27T23:27:54Z**

Typed physical slice fdb9242c follows contracts5ad1e036/aebd627c/d154a16d. All68 affected checks plus1 edge passed; independent CODE5checks passed13.85s and both CODE/ARCH APPROVE without blockers or concerns. Paired131072-row fixture outputs byte-identical; runner87.33 to43.40seconds, reported maxRSS1680293888 to1039368192bytes, bounded shared-Mac evidence only. Full counter retry began23:25:15Z on0c5545a with cap00:10:15Z; no accepted population or old-index comparison yet. Ticket remains in progress; live lake writes remain owner-gated.

Final owner exceptions follow fixture commit f91b7626: 34 public columns retain entry sniff facts, expansion and root writer identity, with recorded-entry/legacy completeness and the original six cutoff cases. No prior/header arrays, inline record hashes or metadata cache returned. Qualified source-pin reuse remains intact. Focused runtime486 checks: 52 passed/40.24s; 59 passed and one heavy fixture deselected/14.38s; 19 passed/14.68s after added boundary assertions; final 13 passed/9.41s. Actual plans have one receipt scan, one reference fanout, three shared C8 bundles, then only primitive materialized fields through storage joins and windows. Source count: committed wide360+363=723, superseded dirty narrow276+211=487, final308+215=523 (200 fewer than committed wide). No performance claim, completed full-corpus result or live lake write. Parent owns full qualification/comparison and the remaining CLI/fixture changes; ticket stays in progress.

**2026-10-28T03:41:21Z**

Current narrow component and slice qualified:43D1PASS31.09s plus49extendedPASS/1heavy deselected43.15s, actual9b50original lines→106rows1.72s/maxRSS119472128B, public bytes identical to486. Comparator34PASS6.57s before tiny exact-pointer guard followup. Slice0old-only/0new-only,41changed rows preserved owner-gated(19context/28entrytime/1providerstatus overlapping). Full population and3,909,134-row comparison remain unfinished pending accepted end-to-end slice/resource projection; no live append. D1 README now has exact local/owner commands; ticket remains in progress.

**2026-10-28T04:07:16Z**

Largest complete receipt key accepted28source lines223captures55.32s/RSS8.192GB on9b, containing187MB/196-capture line. Caption complete key fails portable byte limit102.84s/RSS8.144GB; native pre-materialization profile passes910574rows/maxstring148B90.05s/RSS8.922GB. Tiny generic256×1KiB rows,batch_rows32/max64KiB passes direct query but refuses materialize=true. Exact jobs sent core/engine; no application chunking or limit increase. Full still unfinished pending native byte fit; generic batch_rows256 bounded measurement now active. Merged seam99PASS/1fixture failure fixed by engine6f6818e3 (writer identity); failed actual-release assertion then passes1check15.06s without weakening.

**2026-10-28T21:02:33Z**

Full local public guard passed:2292receipts4176794captures0violations; original200receipt proof61628rows/all34EXCEPT0/0 passed on729. Single full old-index comparison480.51s/native0cb within approved20native/24physical/12scratch/17owned limits: oldOnly0, expectedNew265688, unexplainedNew0, unexplainedMatched2693191. All2704137changed rows retained; owner disposition required. Lead now requests saved-record outcome and403-to404 analysis; D3/model/E4 held for its outcome fix. No live import.

**2026-10-29T01:16:34Z**

Reviewed D1 mapping3fc8c112…d77ec is implemented; corrected independent counts2292 receipts/2598311source/4147132captures with17/17 different-parser affected-receipt crosscheck. Blocked: owner resource window/new corpus jobs. Immutable corrected packet shared/capture-corrected-counts-a072668a. Exact guarded detached proof/full/comparison/D3 commands prepared under scratch/codex-raw/run2/d1-corrected-3fc8;32 source/runtime/input pins. Prior78047 comparison already ended and is historical, never rerun. No old stage/generation retag.

**2026-10-29T01:33:08Z**

Owner requested a small proof-profile repair after5830 failed at17,683,779,072physicalB against16GiB. Proof sample contains historical assembly receipts; propagate the already-approved local assembly20native/24physical profile through outer and nested proof guards, preserving standard14native/16physical defaults. Preserve failed paths/control/source evidence, use fresh proof-v2 paths, update pins, and send a lead-only launch command. Active D2fast5747 and engine5921 sources stay untouched.

**2026-10-29T01:45:22Z**

Proof-profile fix009d6a60 approved by ONE focused CODE review after sole standard-cap concern closed fixture-first678eccfe.46 focused PASS67.360s; mixed actual200receipt sample selects assembly.runtime20native/24physical; standard10/14 retains16physical, remote/nonassembly20 and native>20 refuse. New cxb_d1_corrected_v2.py uses fresh proof-v2 work/monitor/status/markers and full requires new proof-v2 acceptance.33pins match; failed5830 evidence/control/source archived and preserved. All16 active D2fast pins unchanged. Lead-only command in proof-v2-owner-command.md; no proof launch, memory admission must be resampled.

**2026-10-30T14:32:57Z**

Completed D1 full captures rebuild on Basin and merged to main (including e31aeb42).
