# CS 300 final review: the specification set at 9a87e119

Reviewer role: systems / data-intensive software engineering. Date: 2026-10-25.
Reviewed at `9a87e119` against `d9730967`: *Architecture* (**A §n**), *Data Model* (**DM §n**),
*Implementation Plan* (**P §n**) and the new *Implementation Bindings* Note (**B §n**); the diff
is saved beside this file. Measurements ran on the read-only Oct 19 snapshot and on the four
receipt files fetched publicly in earlier passes, through the project venv
(`prof4_checks.py`). No network.

## Verdict

**Ready to build from, with one sentence to change in the plan's order.** My last must-fix is
restored (64 KB data pages beside the 1,024-row limit, and the per-view figure now matches:
≈65 KB measured against the stated 50–90 KB). The three owner decisions are specified
correctly and stay linear. The B0 receipt cleanup is safe and verifiable as written. The one
thing the new order got wrong is that the bucket lock, "the single most protective step", now
waits behind B2's receipt rules and B0 for all three raw prefixes, although B0 rewrites only
`receipts/`: lock `bodies/` and `provenance/` now and `receipts/` after B0.

**Grades.** Architecture **A (94)**, +1 from A (93). Plan **A (93)**, unchanged.

## 1. My last must-fix and nice-to-haves

| Item | Verdict | Where |
|---|---|---|
| **Restore the `detail` page-size caps** (must-fix) | **Landed.** "On every leaf an offset index, 64 KB data pages and a 1,024-row page limit"; per view "50–90 KB"; `occurrences` likewise. Recomputed from my files under exactly those settings: 19 leaves, **≈65 KB per view** (`saved_body` 32 KB at the row limit, the fold 14 KB, `link_key` 8.5 KB, `occ_start` 4.6 KB, the rest under 2 KB each). The 16 KB pages for the key columns were not restored; the row limit now bounds them (32 KB for `saved_body`), which is why the figure is 65 rather than 49 KB. Acceptable as stated. | DM §8.1; A §16.1 |
| Queue takes URL targets only | Landed. | DM §7.7 |
| Resolution per distinct `(body, context)`, with the 1.3 factor recorded | Landed: "Links resolve once per distinct `(page body, context)` … Pages average 1.3 contexts (277,642 contexts over 214,041 good-fetched HTML and XML bodies), so about 4.2M links give *est.* 5.5M targets." Placeholder bodies' links are not resolved, which caps the worst case. | DM §7.2 |
| DM §6 should carry the caps clause | **Still not landed** (third pass). The row-group sizes in DM §6 are unconditional; the condition lives only in P §5.1 M1.3. Minor. | — |

## 2. The edits

### 2.1 B0: the one-time receipt cleanup

**Premise.** The plan's sample (150 files: 33,585 cookies and 24,375 local paths in 74,863 lines)
is consistent with my four files: every line of the Oct 4 `documents` receipt carries a cookie
header, every line of the Senate-pages and Oct 15 recovery receipts carries an absolute local
path (`/Users/…`), 100 of 195 lines (51 %) and 92 of 195 (47 %) respectively. Receipts are
public; the cleanup is right.

**Procedure** (P §6.2 B0). Remove `Set-Cookie`, `Cookie` and `Authorization` values and replace
each absolute local path with its last segment; nothing else changes. Per receipt: conditional
write to the same key (`If-Match` on the original ETag, `Content-MD5`), re-read, check every line
equals the original minus exactly those fields, write a verification record (original and
cleaned size and ETag, counts removed). Keep the private backup until every receipt is
verified, then clean it the same way. Done when every receipt has a record and a re-scan finds
nothing. Assessment:

- **Safe.** `If-Match` excludes a racing writer; `Content-MD5` verifies the upload; the re-read
  comparison verifies the transform; the records make it auditable (invariant 3, DM §5.3); the
  backup covers failure; the R-check names it as the single exception (P §3). Receipt keys do
  not change, so nothing downstream (ingest, IDs, the old-index comparison on receipt-derived
  columns) is affected; the model never read the removed fields.
- **Cost.** 2,289 files: 2,289 GETs, 2,289 conditional PUTs, 2,289 re-reads, ≈3.2 GB moved,
  a few cents, one-time, O(R).
- **Order.** B2's receipt rules → B0 → the lock is right for `receipts/`: the new writer must be
  live first so no dirty receipt lands after the re-scan, and the lock must come after the
  rewrite. It is wrong for `bodies/` and `provenance/`, which B0 never touches (§4 item 1).
- **Two small gaps.** The run is not stated to be idempotent: say it skips receipts that
  already have a verification record (the full re-hash has that rule, B10). And write the
  2,289 verification records as a few provenance files, not 2,289 objects.

### 2.2 The wider fingerprint scope

DM §6.2 now fingerprints two candidate sets: bodies at contested endpoints (148 endpoints, 297
bodies, 1.4 GB, measured) and every real body in a rendition group before the edition check,
"*est.* 20–45 GB once, then grows with new format groups". My rule-(b) measurement (same
directory and stem, two or more document extensions) gives 18,853 PDFs / 8.0 GB and 1,325 XML /
0.25 GB; rule (a), publisher groups from page links, is not in the snapshot, so 20–45 GB is a
plausible upper range with 8.3 GB as the measured floor. Bounded: the candidate set is a subset
of real files. O(change) afterwards: the work list is an anti-join on `(sha, parser, version)`
over the candidates, so only new group members are read. Two properties the text gets right:
`edition_bodies` is closed over fingerprinted copies, so a re-packaged copy of a contested
edition can no longer carry a rendition edge from an uncontested address; and "the model reads
fingerprints only for the candidates under the pinned profile", so a stale fingerprint never
changes grouping and an incrementally maintained lake groups like a clean rebuild (S has the
fixture). One consequence to name: a registry change that widens rendition groups (the
generic-stem list, `group_path` rules) widens the candidate set, and the completeness gate then
refuses publish until the new candidates are fingerprinted, hours for a large widening. Either
state that, or version the candidate rule with the fingerprint parser so a widening backfills
first and the profile moves when complete (nice-to-have).

### 2.3 The effective-filename precedence

DM §7.4: recovered name, else member basename, else `Content-Disposition` (`filename*` first),
else a `filename`/`file`/`name`/`document`/`attachment` query parameter, else the final URL's last
segment, else the requested URL's, else an older import's retained path; URL text
percent-decoded once as strict UTF-8 with `+` literal. Deterministic per capture row, and the
registry-free list is right to live in the data model. Effects:

- **Work list.** `filename_readings` is keyed by distinct `(effective filename, source URL)`
  over capture rows and recovery links (DM §6.3). A download header can give one URL several
  names across fetches, so the pair set can grow slightly beyond the 1,392,681 pairs measured
  today, but it stays bounded by distinct names observed, and the producer computes the name
  itself from raw and provenance, so the work list depends on no model decision.
- **`source_id`.** The formula is unchanged (`[logical body key, filename, source_url]`), but the
  name input changes for files whose header or query name now wins over the URL segment (P
  §6.5 says about 95,000 carry a download-header name; the snapshot cannot check it, and none
  of my 195 sample lines carries `Content-Disposition`). Those `source_id`s change; `document_id`
  (a body-set digest) and the public link keys (body digests) do not, so no public link moves.
  E4 names the cause. Correct.
- **One sentence to add.** "One name per file" (DM §7.4) means one name per capture row; rows
  of one body and URL fetched with different download names are distinct `(body, name, URL)`
  triples, hence distinct source files that the same-body edge joins into one document. Say
  that, so nobody reads "exactly one effective name" as a collapse across rows that the
  derivation does not perform.

### 2.4 `entry_index` in the endpoint

`(context_url, member_path, entry_index)` keeps two members with one name apart (A §3, DM §6.1,
§7.2, §9). Right: with the same name and different bytes they are two endpoints, not one
edition-ambiguous endpoint, so they are not wrongly contested; `source_id` still excludes
path and index, so IDs are stable. One wording nit: DM §7.10 still says occurrences are
"one row per distinct `(source_id, member_path)`"; two same-body same-name members at different
entry indexes collapse to one row there, which is harmless but should be said.

### 2.5 `text_head`

The first 2 KB of visible text (DM §6.2), so the body-marker check (challenge and soft-error
pages) runs in the model against the error-word registry without re-parsing. Consistent with
"parsers record facts, the model classifies". Cost: 2 KB × ≈214k HTML bodies ≈ 430 MB raw,
roughly 85–140 MB compressed (estimated), which makes `text_head` and `links` the bulk of a
table whose fold is 16.5 MB today; DM §6.2's size note and D2's "size with links measured"
should include it, and A §13.6's rule keeps it off hash-join build sides.

### 2.6 The component and binding structure as a plan

Principle 8 (A §4) and the 17-component table (A §6) give each component a contract, a class,
and injected adapters for the external systems only; the plan (P §2) is contract tests first,
then bind, adapt or build, one implementation per component, switch then delete; the Bindings
Note maps today's code onto each component with a fit, the adapter work and the contract test,
seeds every registry from the knowledge in that code (B §4), lists what is bound to nothing
(B §5) and the known defects in code about to be bound (B §7). As a plan this front-loads the
right risks: the body store's refusal matrix is the first contract test (B3); M1, M2 and S still
precede engine work; the reader runs against F0 and a hand-built fixture before the engine
exists; B14 goes first because the cut-off re-fetch path is the one with a known `TypeError`
(B §7). Nothing in it is superlinear or repeated: B0 is one-time O(R); grouping runs on
sampled links in M2 and once more on real links in D2 by design; B10 after B13 saves 365 GB of
reads. The cost of the structure is the up-front contract suites for 17 components, which the
rule "contract tests land before the code bound to them moves" already prices in. One
observation: the plan no longer names files (by design, B does), so a reader needs both Notes
open; that is the right split for documents that change at different rates.

### 2.7 Other edits, checked

Body identity is the content-decoded entity (A §7.1, DM §5.2), so a transfer-encoding change
never creates a new body; 206 and `Content-Range` mark incomplete fetches; fetcher refusals
(private hosts, URL credentials, out-of-scope URLs, six redirect hops) and pacing are MUSTs
with registries; credential parameters are stripped from every recorded URL and API keys move
to headers; archives expand with limits and Office packages stay whole; publisher grouping is
per `(page body, context, group_path)`, so one template under two hearings never pairs files
from both (A §9.3, DM §7.5); `url_key` normalizes percent-encoding per RFC 3986 §6.2.2, so
`a b.pdf` and `a%20b.pdf` match; the committee-code registry replaces the `hs`-only rule and
fixes the `hl` and joint forms; House meeting IDs drop all three prefixes; `recoveries` is one
row per import row with a deterministic decision pick (DM §7.8, invariant 13); `withdraw`
supersedes a review; the engine pin carries a digest per runner OS; the repeated-work list
moved from principle 4 to A §16.1. All consistent across the three documents; nothing lost.

## 3. Spot-checks

| Claim | Where | Result | Status |
|---|---|---|---|
| About 2,300 receipts to clean | P §6.2 B0 | 2,289 receipt files in the snapshot | **measured** |
| B0 sample: cookies on 45 % and local paths on 33 % of 74,863 lines | P §6.2 B0 | my four files: cookies on 100 of 195 lines (51 %), paths on 92 (47 %), `Content-Disposition` on 0 | taken; consistent with my sample |
| 277,642 contexts over 214,041 bodies, 1.3 per page | DM §7.2 | 277,202 / 214,010 in my pass (slightly different good-fetch filter) | taken; measured, consistent |
| 5.5M link targets | DM §7.2 | 4.2M × 1.3 | estimated |
| Fingerprint widening 20–45 GB | DM §6.2; P §6.4 D2 | rule-(b) members alone: 18,853 PDFs / 8.0 GB, 1,325 XML / 0.25 GB; rule (a) not in the snapshot | estimated by the owner; my 8.3 GB is a measured floor |
| Detail view 50–90 KB, about 19 pages | DM §8.1; A §16.1 | 19 leaves, ≈65 KB under the stated settings | estimated, consistent |
| About 95,000 files carry a download-header name | P §6.5 | not in the snapshot; 0 of 195 sample lines | taken |
| 17 components | A §6 | 17 rows | counted |
| 1.31M source URLs; 1,158,426 requested URLs; 287,765 HTML/XML bodies; 64 cut-off URLs; 455 occurrences in the largest document | DM, P | from the previous pass | taken (measured earlier) |
| About 40,000 source lines removed at the switch | B §5 | consistent with the 42k–47k counted in the first plan | taken |

## 4. Remaining items

1. **must-fix (plan order, one sentence).** Lock `bodies/` and `provenance/` now; only
   `receipts/` waits for B2's receipt rules and B0. The bucket lock takes per-prefix rules
   (checked against Cloudflare's docs in my first review), B0 rewrites receipts only, and
   creates stay allowed under the lock, so B13's `.pdf` copies are unaffected. As ordered now,
   the 0.70 TB of bodies stays unprotected for as long as the receipt-rule deployment and the
   cleanup take.
2. nice-to-have — B0: skip receipts that already have a verification record; write the records
   as a few provenance files.
3. nice-to-have — DM §7.4: say that different download names for one body and URL are distinct
   source files joined by the same-body edge.
4. nice-to-have — DM §6.2: add `text_head` (≈85–140 MB est.) and `links` to the size note; D2
   measures both.
5. nice-to-have — DM §6.2 / §7.1: say that a registry change widening rendition groups makes the
   gate refuse publish until the new candidates are fingerprinted, or version the candidate rule
   with the fingerprint parser.
6. nice-to-have — DM §7.10: the occurrence grain versus `entry_index`.
7. nice-to-have — DM §6: the caps clause (third pass).

## 5. Grades and verdict

**Architecture: A (94), +1.** Principle 8 and the component table make the conformance classes
concrete and testable; the three decisions are specified without a cost regression; `entry_index`,
the content-decoded identity, per-context publisher grouping and the closed `edition_bodies`
each remove a real wrong-merge or wrong-split; every new pass is linear and the repeated work is
named in one place.

**Plan: A (93), unchanged.** Contract-first with bindings is the right shape for a
dependency-injection refactor of a trial-and-error codebase, the bindings seed registries from
what the code learned instead of carrying the code, and B0 is specified like a raw operation
should be. It does not move up because the new order delays the lock on `bodies/` for no
reason B0 gives.

**Verdict: ready to build from.** Change the lock's order (item 1) when B0's ticket is cut; the
rest can land as the sections are touched.
