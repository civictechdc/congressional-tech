# Recheck of the specs at d9730967

Mode: audit, read-only. Read in full at d9730967: A = `docs/engine-first-architecture.md` (571 lines), D = `docs/engine-first-data-model.md` (675), P = `docs/plans/simplification-plan-20261024.md` (296), plus `git diff c3b067c4 d9730967 -- docs/`. Line numbers are from d9730967. No scripts run; nothing here is a measurement.

## Verdict

**Build from it.** All eight must-fix items from the final review are addressed; six are fully fixed and two are partly fixed because one clause in Principle 4 (A:156) still restates the fingerprint ordering that A §12 now owns. Every citation I followed resolves. One new inconsistency appeared with the fixes: A:476 says only publish ingests captures, but A:285 has the weekly check appending late receipts. That is a one-sentence correction. Nothing blocks M1, M2 and S; the two wording fixes should land before track D.

## 1. The eight must-fix items

| # | Item | Verdict | Fix location |
|---|---|---|---|
| 1 | `base_url` fallback made a reading depend on `captures` | **Fixed** | D:205 `base_href` as written; D:206 `href` as written, "the model resolves each `href` (§7.2)"; D:211 "A reading depends only on its body and its parser version"; D:343 resolution by [[RFC3986]] §5 against `base_href`, else each good-fetch context, in the model; A:294 prose agrees; A:496 adds the engine capability (C8, P:189) the resolution needs. |
| 2 | D:388 contradicted the publish-refuse rule | **Fixed** | Sentence gone; D:391 replaces it with a reporting rule; A:476 states why nothing lands between the lake steps and the pin (but see new item 1). |
| 3 | Refuse rule in two normative homes; fingerprint order in four | **Partly** | Refuse: D:298 is the one MUST; A:400 "apply the completeness gate at them ([[DATA-MODEL]] §7.1)"; D:574 restates it as explanation with a cite, acceptable. Order: A:476 owns it; A:296 cites §12. But A:156 (Principle 4) still says "the `fingerprint` producer evaluates the real-file rule once more before the pin". |
| 4 | Concurrency group as a correctness dependency without a named race | **Fixed** | A:426 names the race: a re-created older release reuses its content-digest prefix, and retention could delete it between canary and flip. The exception at A:483 is now justified. |
| 5 | `link_url_key` froze registry versions | **Fixed** | D:566 keys the exact `original_url`; D:345 lists link URL keys among the identities that MUST NOT use `url_key`; D:568 updates the collision rule. |
| 6 | Failed or missing reading silently dropped a body | **Fixed** | D:361 "missing or not completed"; D:391 the model reports bodies with no role by format and error type; P:227 adds it as a parity cause. |
| 7 | Small duplicates | **Fixed** (one soft residual) | A:291 now one clause, D:191 owns; A:302 states the consequence only, D:241 owns the mechanism; re-hash once at A:261, A:234 cites §7.4; not-found notice only at A:454 (P:136 lists it as work); A:89 cites for profile contents; P:126 and P:145 no longer repeat the "twice the target" figure. Residual: the consequence "a registry change rewrites nothing / re-parses nothing" is still in A:291, D:191 and D:300. |
| 8 | Bolted-on wording | **Partly** | A:224–230 Write is a three-step rule; A:236 cites D §5.3 for the copy's verification record; A:261 rewritten; D:238 counts removed. Not done: A:156 Principle 4 grew (it gained "a release upload is the whole release on any day with a change") instead of shrinking. |

Totals for items 1–8: fixed 6, partly 2, not fixed 0.

## 2. Earlier partly-fixed items

| Item | Verdict | Now |
|---|---|---|
| Finding 3 (fingerprint ordering repeated) | Partly | Owner is A:476; residual clause at A:156. |
| Finding 4 (refuse rule two homes) | Fixed | D:298 owns; A:400 cites. |
| Finding 18 (non-sizing numbers) | Partly | D:238 counts gone. A:232 "The 201 bodies" remains; it is a count of evidence, not a size. |
| Bolted-on A:255 lock/§14 | Partly | Unchanged: A:259 and A:504–506 both say the lock is what stops deletion. Harmless. |
| Bolted-on A:325 effective filename | Fixed | A:302. |
| Bolted-on A:514 / P twice-target | Fixed | P:126 once; P:145 says "F0's size". |

Totals for the six carried items: fixed 3, partly 3.

## 3. New problems

### 3.1 A:476 contradicts A:285 (must fix, one sentence)
- A:476: "Captures are ingested only by publish, so nothing lands between the lake steps and the pin." A:285 (§8.2 Ingest): "The weekly check lists everything and appends anything a late receipt left behind." P:163 lists that append in the maintenance job.
- Mechanism: the sentence was added to close item 2, but maintenance also ingests. The property it wants is still true, because publish and maintenance share a concurrency group (A:426) and so never overlap.
- Change: "Only publish and the weekly maintenance job ingest captures, and they never overlap (§10.3.7), so nothing lands between the lake steps and the pin."

### 3.2 A:156 Principle 4 still enumerates implementation (should fix)
- It now lists six repeated-work items including the fingerprint clause that duplicates A:476, and a new clause about release-upload size that duplicates §10.2's last sentence (A:394) and §16.1 (A:533).
- Change: keep the principle in two sentences ("Fetching, parsing and storing grow with what is new. The repeated work the design accepts is listed in §16.1, and none of it re-reads stored bodies."); move nothing, since §12 and §16.1 already hold the details.

### 3.3 Rules still stated in more than one place (minor)
- "A registry change never re-parses a body / rewrites nothing in the lake": A:291, D:191, D:300. Keep D:300 (it sits with the registry definition) and D:191's first clause; A:291 can end at "the model classifies them".
- Profile moves when the new version's work list is empty: A:298 and D:297. A cites; acceptable as is.

### 3.4 Stale or bolted-on wording (minor)
- A:434 "Long occurrence ranges are read a page at a time." With occurrences now one row per `(source_id, member_path)` and a largest document of 455 rows (D:536) under a 1,024-row page limit (D:553), every range is one page; the sentence describes the old 33,479-row case. Delete it.
- D:294 "A fix to the ingest mapping is a new `captures` table, rebuilt from the receipts in minutes." A rebuild policy appended to the profile definition. It belongs in A §8.2 beside the rebuild check, or can go, since inv. 1 already requires rebuild equivalence.
- P:168 (B14): "The snapshot index gives 64; the receipts decide the two whose status the index lost. Other bodies at those URLs, such as 214-byte HTTP 520 error pages, are not complete copies." reads as a pasted investigation note. "Every URL with a cut-off copy and no complete 2xx copy (64 by the snapshot index, confirmed against receipts)" is enough.
- A:259 and A:504–506 both carry the lock-not-token sentence (carried from before).

### 3.5 Citations
Every citation followed resolves to the right section after the renumbering and the new A §11.6: A:158→§10.3.5; A:344→§11.6; A:400→D §7.1 and §8.3; A:426→§12; A:450→D §7.5 (`saved_suffix` is defined there, D:444 and D:489); A:483→§10.3.7; A:493→§7.1 and §10.3.4; A:496→[[RFC3986]] (added at A:555); D:137→§6.3; D:140→§7.5; D:206→§7.2; D:260→§7.3 (`good_fetch`); D:315→§7.4; D:343→§7.3; D:345→§8.2; D:444→§5.3; D:533→§7.7; D:554→§7.5 (recovery order); P:92→D §6; P:94→A §8.7; P:135→A §11; P:139→A §11.5; P:140→A §11.6; P:189→RFC 3986 §5.4; P:275→D §6.6. No wrong citation found.

### 3.6 Meaning changes checked and accepted
- `good_fetch` (D:352) is defined once and used at D:260, D:343, D:502 and D:534; `real_files` is a restriction of it. Equivalent to the previous predicate.
- `edition_bodies` (D:417) extends the no-rendition rule to same-text copies of a contested edition; inv. 14 (D:637) and A:336 agree.
- Reviews (D:524–527): every remaining `duplicate_of` is an edge; latest-wins applies only to `hide` and overrides. This fixes the earlier precedence that could drop a merge.
- The queue (D:502) now excludes URLs matched by a fetch row's final URL as well as its requested URL, and only `mode = fetch` rows count, so a recovery import cannot hide a never-fetched URL; inv. 12 (D:635) agrees.
- `detail` page sizing (D:551) replaced byte page sizes with a 1,024-row page limit and 65,536-row groups; A:379 and the 70–90 KB per-view figure agree. `links` keeps 16 KB pages (D:552).
- Occurrences grain (D:531) and counts (D:536, D:553, P:101, A:533) changed together and consistently.
- The sniff-version note (D:212) and the "ingest mapping" in the profile (D:294) are new facts, each stated once.

### 3.7 Over-engineering check on the additions since c3b067c4
- C8 generic URL functions (A:496, P:189): necessary once resolution moved into the model, and generic (RFC 3986 reference resolution and percent-decoding), so it respects the engine-first boundary. Fine.
- Recovery order extended with receipt coordinates (D:438–440): needed for a total order. Fine.
- `edition_bodies`: one extra relation that closes a real transitive-merge hole. Fine.

## 4. Final verdict

The structure holds: every schema, derivation, order and registry has one home in D; A explains and cites; P lists work; the citations are correct; the next change (a new parser version, registry, release file or URL rule) lands in one place. Fix A:476 and trim A:156 before track D; the rest of §3 is a few minutes of tidying and does not affect what gets built.

Coverage: all three files read in full at d9730967, plus the diff from c3b067c4. Not run: any script, test or build.
