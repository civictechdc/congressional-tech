# Final review of the specs, plan and bindings at 9a87e119

Mode: audit, read-only. Read at 9a87e119: the full diff of A = `docs/engine-first-architecture.md` and D = `docs/engine-first-data-model.md` from d9730967; P = `docs/plans/simplification-plan-20261024.md` and B = `docs/plans/bindings-20261025.md` in full; A §4–6 in full. Line numbers for A and D refer to 9a87e119 where read directly, otherwise to the diff hunks. No scripts run beyond `grep` for identifier and name checks; nothing here is a measurement.

## Verdict

**Build from it.** The remaining items from the recheck are closed (8 fixed, 1 harmless partly). The separation worked: the plan names no existing files, the bindings Note is the only place code paths appear, the component table in A §6 is the one home for component names, and nothing material was lost in the move. Four things to fix before track B starts, one of them a real contradiction: invariant 3 asserts no receipt line carries a credential parameter, but the B0 cleanup removes only cookies and local paths, so older receipts with API keys in recorded URLs would fail it while staying public.

## 1. Remaining items from the recheck

| Item | Verdict | Where |
|---|---|---|
| Principle 4 enumerated implementation | **Fixed** | A:156 is two sentences and cites §16.1; the repeated-work list sits once, non-normative, at the end of §16.1. |
| Fingerprint order stated four times | **Fixed** | A §12 "Order" owns it; A §8.3 says "runs after the other parsers (§12)"; §16.1's list mentions it once as a cost. |
| A:476 "only publish ingests captures" vs the weekly check | **Fixed** | §12 Order now reads "Only publish and the weekly check ingest captures, and they never overlap (§10.3.7)". |
| "Registry change never re-parses" in three places | **Fixed** | A §8.3 and D §6.2 now say only "the model classifies them (§7.3)"; D §7.1 keeps the consequence once. |
| A:434 stale "long occurrence ranges" sentence | **Fixed** | Removed from §11.1. |
| D:294 ingest-mapping sentence bolted onto the profile | **Fixed** | Now a rule: a new mapping is a new `captures` table named by its version, dropped once neither live nor last-good profile names it (D §7.1). Residual: A §8.7 Maintenance does not mention that drop, and the plan's M1 tests whether a drop purges files; one clause in §8.7 would give the drop an operational owner. |
| P:168 B14 pasted investigation note | **Fixed** | P:180 is one sentence. |
| Lock sentence in A §7.4 and §14 | Partly | Unchanged (A §7.4 and §14 both say the lock is what stops deletion). Harmless. |
| A:232 "The 201 bodies" | **Fixed** | Now "Bodies that older runs cut off". |

Totals: fixed 8, partly 1.

## 2. The separation

### 2.1 Existing-code facts left in the specifications and plan
- **`house-naming`** is named as an implementation in A §8.4 (A:333) and six times in D §6.3 (D:230–243: "house-naming version", "house-naming matches some rules on it", "house-naming returns exactly one value", "house-naming's literal strings"). It is the one binding that leaks into the specs: the Filename reader component's contract should speak of "the filename catalog" (the term `catalog_version` already does), with `house-naming` bound in B §3.2. One terminology entry in A §3 ("filename catalog: the naming library the filename reader applies; today `house-naming`") would also do, if the owner prefers the familiar name.
- **hyparquet's `useOffsetIndex` and `usePageIndex`** in A §11.1 and P:138: library API names in a spec. The owner decided hyparquet stays, so this is tolerable, but the Reader row of B §3.4 is where the library belongs; A §11.1 could say "page reads through the Parquet offset index and point lookups through the column index".
- **A §12 Pinned engine:** "recorded in the application repository rather than in the binary's own descriptor" contrasts with today's defect (B §7). The contrast clause is history; "recorded in the application repository" is the rule.
- P:29 ("Already in place", with `accepted.json` and `stored_sha256`), P:172 (`uv.lock`, `packages/`, `scripts/`) and P:181 (a raw receipt key) name data files, repository paths and raw keys, not code. Acceptable for a plan; P's own rule is "names no existing files" and these are not source files.
- D §3's compact-JSON definition cites Python's `json.dumps` arguments. It is load-bearing for the golden vectors and defines bytes, so it stays.

No source-file paths or line numbers remain in A, D or P (checked by grep for `.py`, `.ts`, `.rs`, `.mjs` and the old identifiers).

### 2.2 Lost in the move
- Nothing material. Every "replaces at the switch", writer list, deletion row, keep-list entry and C0 detail from the previous plan is present in B §3 or §5, with updated counts.
- One small loss: the previous keep list named `derive_body_key` and its golden tests. B §7 now lists `physical_body_object_key` as defective, and `derive_body_key` appears nowhere. The logical-body-key string is fixed in D §3 and covered by the ID golden vectors (B §3.4), so the rule is safe; the function's own tests just need a row in B §3.1 (Body store, "Bind: `derive_body_key` and its golden tests") or an explicit drop.

### 2.3 Does the bindings Note restate spec rules?
- **B §2 "Binding Rules":** rules 3–7 paraphrase A principles 3, 5 and 8 and D §7.1 in "what went wrong" framing (rule 4 "Policy is data" = D §7.1; rule 5 "Platform primitives replace bookkeeping" = principle 3; rule 6 "Raw is write-once" = §7 and A §7.2's cleanup sentence; rule 7 = principle 5; rule 2 = principle 8's adapter list). Only rule 3 cites its source (A §15.7). This is the one place the Note restates instead of citing. Change: keep rules 1, 2 and 8 (binding-specific) and the sentence "Every binding is proven by the component's contract test", and turn 3–7 into one line: "Principles 3, 5 and 8 and [[DATA-MODEL]] §7.1 apply; [[INVENTORY]] §6.1 and §6.3 record where today's code broke them."
- **B §3 adapter-work cells** restate target rules as gap lists ("412 = `unchanged` with no download", "206 or `Content-Range` is incomplete", "scalars to one value, the typed keys"). That is the Note's job (what changes to meet the contract), and the Contract column of A §6 points at the rule, so it is acceptable; cells could start "to A §7.1:" to make the direction explicit.
- **B §4 and §7** cite rather than restate. Good.

### 2.4 Is A §6 the one home for component names?
- Yes for the seventeen components it lists. Plan tracks and B §3 use those names, with three drifts:
  - P D4/D5 say "Committee parser" and "Meeting parser"; A §6 and B §3.2 say "Committee and meeting parsers" (one component). Use the table's name in P.
  - B §3.2 splits A's one row "Parsers (sniff, html, xml, json, fingerprint)" into "Sniff parser", "HTML and XML parsers" and "Fingerprint parser", and **has no row for the JSON parser**. D §7.3 makes a JSON body with no json reading roleless and so never a real file, so the json parser must be built or adapted; B must say which.
  - B §3 has rows that are not A §6 components: Engine pin check, PDF copier (one-off), Receipt cleaner (one-off), F0 converter (migration tool), Origin rules, ID golden vectors (seed). The one-offs and seeds are fine as labeled. "Engine pin check" (A §12) and "Origin rules" (A §11.7) are target behaviors; either add them to A §6 or mark them in B as "behaviors of the publish job and the origin, not components".
- P's track A title "Reader, Canary and Site" uses "site", which A §6 does not; A §6 has "Reader" and "Canary and contract test". Minor.

## 3. New duplication, bolted-on wording, over-engineering

### 3.1 Must fix: the B0 cleanup does not remove what invariant 3 forbids
- D §10 inv. 3 (diff hunk at D:~650): "No receipt line carries a credential parameter in a recorded URL, a cookie or a local file path, and every cleaned older receipt has a verification record." P:157 (B0 rule): "remove recorded `Set-Cookie`, `Cookie` and `Authorization` values, and replace every absolute local path with its last segment. Nothing else changes." D §5.2's cleanup sentence and A §7.2's say the same: cookies and paths only.
- B §4 K1 shows that today's committee fetcher put the API key in URLs (`ca/acquisition/committees.py:23-29`), so older receipts can carry `api_key=` in `requested_url`, `url` or `redirects[]`. Those lines are public and the invariant fails on them.
- Change: add credential parameters (per the credential-parameter registry) to B0's rule, D §5.2's cleanup sentence and the verification record's counts; or, if the owner accepts leaving them, scope inv. 3's credential clause to new lines and say so in A §7.2. Given "receipts are public and permanent" (A §7.2), the first.

### 3.2 Should fix: the B0 fact has two normative homes
- A §7.2 ("Older receipts were cleaned once, before the bucket lock … That is the only rewrite of raw history") and D §5.2 ("Older receipts were cleaned once before the bucket lock: … Each cleaned receipt has a verification record") state the same fact and the same rule contents; P B0 states the rule a third time as the procedure. D §5.2 is the record-level home; A §7.2 can keep one clause ("the one-time cleanup of [[DATA-MODEL]] §5.2 is the only rewrite of raw history") and P B0 can cite D §5.2 for what is removed and keep only the procedure and the safety net.
- B0 itself is proportionate: conditional write on the original ETag, re-read and field-by-field comparison, a verification record per file, backup kept until verified. It is the right amount of care for the only rewrite of the precious layer. Not over-engineered.

### 3.3 Should fix: registries that have no row
- D §7.1 names the credential-parameter and host-pacing registries in prose ("Two registries serve the raw writer instead and are versioned with its code") but not in the table. B §4 seeds them as registries. Give them rows with "Used by: fetcher, receipt writer" and a note that their version belongs to the raw writer's code, not the profile.
- A §7.2 "Archives" says expansion "has limits (archive, member and total size, member count, and one level of nesting)" with no values and no registry; B §4 K6 seeds "Archive expander limits" from code. Policy without a home. Add an "archive limits" row to the same table, or state the values in D §5.2.
- D §7.4's effective-filename chain hard-codes the query-parameter names (`filename`, `file`, `name`, `document`, `attachment`). By the registry doctrine (D §7.1, B rule 4) that list is a registry entry; today it is the one list left in a derivation.

### 3.4 Minor duplication
- Principle 8's last clause ("no production path carries a test-only branch") is also §15.7, B rule 3 and P:177. The principle can end at "tests run the production code against local adapters" and cite §15.7.
- A §6 table: Review recorder's adapter is "object store", but P:169 routes "every raw write" through the body store and B §3.1 has the recovery importer write provenance through it. The review recorder writes provenance (raw). Its adapter should be "body store".
- A §7.1 "Fetching" is a fetcher paragraph under the Bodies heading; §7.2's "Archives" is likewise about the archive expander. Both read fine; a §7.0 "Fetching" would be tidier, but renumbering is not worth it now.

### 3.5 Over-engineering check on the additions
- **Component table (A §6):** seventeen rows, four columns, and it is what principle 8 and the bindings hang on. It replaced scattered "what survives" prose with one list that the plan, the bindings and the contract tests all key on. Earns its keep.
- **Principle 8:** one paragraph, no new mechanism beyond what the component table and the ratchet already require. Fine, with the clause trimmed (3.4).
- **B0:** see 3.2; proportionate.
- **Binding rules (B §2):** the one over-built piece. Eight rules, five of them restatements. See 2.3.
- **Fingerprint every rendition-group member (D §6.2):** the paragraph is now long because it carries the incremental-equals-rebuild guarantee ("the model reads fingerprints only for the candidates under the pinned profile, so a fingerprint left over from an earlier profile never changes grouping"). That guarantee is a real invariant and belongs in §10 as a test ("grouping under a profile is identical for a clean rebuild and an incrementally maintained lake"); the plan already lists the fixture (P:118). Moving it would shorten §6.2 and give it a test.
- **Link targets (D §7.2):** the resolution rule now carries contexts, relative `<base href>`, archive members and counts. It is dense but each clause closes a fixture in P §5.3; not padding.
- **Effective filename (D §7.4):** seven-step precedence. Each step is a real source observed in the data (B §4 K29–K30); the owner decision (header first) is stated once. Fine, apart from the hard-coded parameter list (3.3).

### 3.6 Citations
All followed citations resolve: A §6 table rows to A §7–§13 and D §5–§8; A §7.2 to P B0; D §7.1 to §7.3, §7.5, §7.7, §7.8; D §7.4 to [[RFC6266]] (added); P to A §8.1, §8.7, §10.3.5, §10.3.7, §11, §11.5, §11.6, §12, §13, §15.7 and D §5.2, §5.3, §6, §6.6, §7, §7.1, §7.9, §8.1, §10; B to A §12, §15.7, D §6.3 and the inventory. No wrong citation found.

## 4. Final verdict

Sound enough to build from, and better separated than before: the specifications say what the target must do, the plan orders work by component, and the bindings Note is the only place today's code appears. Fix 3.1 before track B (it is a public-data correctness gap, not a wording issue), give the JSON parser a binding row, and add the three missing registry rows; the rest is a short tidy. The next change in each direction has one home: a new rule lands in D, a new component in A §6, a new binding in B §3.

Coverage: full diff of A and D from d9730967; P and B in full; A §4–6 in full; identifier and component-name greps across all four. Not run: any script, test or build.
