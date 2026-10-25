# Evolutionary review 5: the documents at 1455011a

Mode: audit, read-only. Read: the full diff of A (`docs/engine-first-architecture.md`), D (`docs/engine-first-data-model.md`) and P (`docs/plans/simplification-plan-20261024.md`) from 9a87e119 to 1455011a; B (`docs/plans/bindings-20261025.md`) in full; the D §7.1 registry table and A §6 component table as they stand. Line references are to 1455011a where read directly, else to the diff hunk. Commands run: `git diff`, `awk`/`grep` over the tables. Not run: anything else.

## Verdict and score

**Build from it. Score: 86/100.**

After five rounds the three documents hold their shape: one home per rule in nearly every case, the plan names no code, the bindings Note is the only place code appears, and a change in each direction lands in one section. The lost points are for sediment that the last two rounds of reviewer-driven patches left behind: a format-specific carve-out in the real-file rule, one hard-coded list that escaped the registry doctrine, two wording inconsistencies between documents, a plan hedge inside a spec, and five bindings rows whose names are not in A §6. None of it blocks the first steps; all of it is cheap now and more expensive after track D exists.

## 1. The three not-done items

| Item | Decision | Reason |
|---|---|---|
| Track A title keeps "Site" | **Accept, with one change** | The plan builds site pages, and B §3.4 now has a "Site pages" row. The inconsistency is that A §6 has no such component, so the title names something the component table does not. Add a "Site pages" row to A §6 (class reader; contract §11.5–11.6; adapter: reader). Then the title, B and A agree. |
| No §7.0 heading | **Accept** | Renumbering costs every cross-reference; the two paragraphs read fine where they are. |
| Lock in A §7.4 and §14 | **Accept** | §7.4 states the mechanism; §14 lists it among the security controls. Two mentions of one fact in two legitimate contexts, not two rules. |

## 2. Structural erosion

Each finding names the mechanism of harm or the change it makes expensive, and a verdict: keep, reshape or delete.

### 2.1 `intact` is a format-specific carve-out inside `real_files` — reshape
- D §7.3, the new clause `and (format <> 'pdf' or r[sniff].intact)`; D §6.2 `intact` column; A §9.2's broken-PDF sentence.
- Mechanism: `real_files` was "good fetch, non-empty, not a placeholder, role = document, and HTML not file-shaped". Every other reason a body is not a document (error page, listing, caption, API) flows through the `record_role` ladder. A broken PDF is the first reason that bypasses the ladder and adds a format test to the predicate. The next integrity check (a truncated ZIP, an empty DOCX, a WARC with no records) adds another clause here instead of one ladder line.
- Change: give the ladder a role for it, `'broken' when format = 'pdf' and not sniff.intact` (above `'document'`), and leave `real_files` as it was. Invariant 8's list ("so no listing page, error page or failed reading") then covers it without a new clause. A §9.2's sentence stays as intent.

### 2.2 Completeness has two definitions that disagree — reshape
- A §7.1 "Nothing is cut off": a 206 or `Content-Range` response "is incomplete, unless the fetcher assembles the whole entity from ranges and its length matches the declared length". D §5.2 `complete`: "Body fully received; false for a 206 response or one with `Content-Range`." B §3.1 Fetcher keeps Range resume.
- Mechanism: the D column note is the field's definition and it forbids what A allows. A fetcher built from D records an assembled body as incomplete; one built from A records it complete. The "unless" clause is the shape of a patch for one reviewer.
- Change: define completeness once, in D §5.2: "`complete` is true when the stored entity's length equals the declared length and every byte was received, whether in one response or assembled from ranges; a lone partial response is incomplete." A §7.1 then says "a body is stored only when complete ([[DATA-MODEL]] §5.2)" and drops the exception sentence.

### 2.3 One hard-coded list escaped the registry doctrine — reshape
- D §7.5 `same_rendition` (b): "document extensions (pdf, xml, htm, html, doc, docx, txt)".
- Mechanism: D §7.1 and B rule "policy is data" moved every other list into a registry this round (filename parameters, URL repairs, publisher kinds, feed roots). This list still lives in the derivation, so adding a format (see §3.2 below) edits SQL and bumps the model version instead of a registry.
- Change: the format-preference registry already orders formats for the saved file; add a column or a second registry, "document extensions", and have (b) read it. One line in D §7.1, one word in §7.5.

### 2.4 Registry versioning is a rule in prose beside a table that should carry it — reshape
- D §7.1: 22 registries in the table; above it, prose says "The three raw-writer registries are versioned with the raw writer's code, not the model profile. Fetchers use the capture-scope version of the live release's profile."
- Mechanism: the table's "Used by" column implies the versioning but does not state it; the next raw-writer registry needs a table row and a prose edit, and a reader cannot tell from the row which version governs it. The count grew from 13 to 22 across three rounds, so this is the active axis of variation.
- Change: add a "Versioned by" column (profile / raw writer / both) and delete the two prose sentences. The registry abstraction itself earns its keep: every row replaced a hard-coded list, each has a sample test, and a change is one file plus a profile hash. Keep it.

### 2.5 "One name per file" versus "one name per capture row" — reshape
- D §7.4: "One name per capture row. When fetches of one body at one URL offered different names, each name is its own source file, and they join through the same-body edge." P §6.5 E4: "each file has one name, so the files today's catalog lists under several names … collapse to one, with different `source_id`s."
- Mechanism: the plan's parity cause describes the previous rule. Someone writing the parity predicate from P will count differently from the model built from D.
- Change: P E4 says "each capture row has one name ([[DATA-MODEL]] §7.4), so rows today's catalog lists under several names collapse to one each; a body offered different names at one URL becomes several source files joined by its body".

### 2.6 A plan hedge inside the data model — delete
- D §6 Writer settings: "These sizes assume the engine's remote write caps are removed; if [[IMPLEMENTATION-PLAN]] M1 keeps them, the sizes change."
- Mechanism: a spec stating that it may change depending on a measurement is plan content; P §5.1 item 3 already says exactly this. Two homes for a contingency.
- Change: delete the sentence from D.

### 2.7 Small bolted clauses — delete or keep
- P §6.3 C4 row "with no application logic in the engine": the engine-wide rule of A §13 and §15.7 restated in one capability row to answer a reviewer. Delete the clause.
- D §6.2 size note "The model reduces readings to the narrow columns its rules need before any join, so neither reaches a hash table": a restatement of A §13 capability 6 at a column note. Keep one; A §13 is the home.
- D §7.2 "Endpoint comparisons are null-safe (`IS NOT DISTINCT FROM`)": an implementation detail, but it is the one SQL fact that silently breaks every top-level-page join if missed. Keep.
- A §7.2 "where a host takes a key only in the query, the fetcher adds it from configuration at fetch time": a real rule with a real consequence (recorded URLs stay fetchable). Keep.
- D §7.5 "A re-packaged copy that never shared an endpoint with another real body has no candidate fingerprint and is not recognized": an honest limitation of the narrow candidate rule, and the thing S counts. Keep.

### 2.8 Rules with more than one home (residual)
- Pages fingerprinted by their own parser: A §8.3 bullet, D §6.2 parser bullet and D §6.2 fingerprint bullet. Three statements of one fact; D §6.2's fingerprint bullet is the home. Trim the parser bullet to "and write the page's fingerprint (below)".
- The committee-removed document: D §6.2 `remove_date` (fact), D §7.5 `removed_on` (derivation), A §11.6 (label, normative), A §9.5 (intent). Four places but each a different layer; this is the pattern the documents are built on. Keep.
- `Retry-After`: A §7.1 (honor it, record the deadline), D §5.2 header allowlist, D §6.1 `retry_after`, D §7.7 `next_attempt_at`. Same pattern. Keep.

### 2.9 Abstractions
- **Registries:** earn their keep (2.4). **Model profile:** earns its keep; it now also maps the `captures` table label to its digest, which is the right place. **Component table:** earns its keep; see §4 for name drift. **Principle 8:** one paragraph, trimmed; keep.
- **Missing:** a single definition of "complete" (2.2). Otherwise none.

## 3. Change cost for the next likely changes

| Change | Sections touched | Verdict |
|---|---|---|
| A new publisher (source family) | D §7.1 registry files only: capture scope, host pacing, recheck interval, and where needed file shapes, error words, publisher kinds, URL repairs; S adds sample tests. The profile hash moves by itself. | Cheap. One registry commit. |
| A new file format | D §6.2 `format` values (a sniff version bump and backfill, as D §7.1 prescribes); D §7.3 ladder only if the format has a non-document role; D §7.5's hard-coded extension list (2.3); format-preference registry; and, if the format has an integrity check, a new `real_files` clause (2.1). | Four to five edits today; two after 2.1 and 2.3 (sniff version plus one registry). |
| A new registry entry | One file plus its sample test; publish rebuilds via the profile hash; if it widens fingerprint candidates, publish refuses until they exist (D §6.2), which is the intended gate. | Cheap. |
| A new receipt shape | D §7.1 (new ingest-mapping version, new `captures` table), A §8.7 (who drops the old one), P M1 (drop purge test), B §3.2 (mapping sample). | Four places, each a different concern, and the rebuild is minutes. Acceptable. |
| A new review verdict | D §5.3 enum, D §7.9 rule, B review recorder. | Cheap. |

## 4. The rewritten bindings Note

- **Over-built?** No. §2 is three rules plus one citing line (down from eight). §5 Dormant code is new and matches the owner's standing rule that dormant code gets a use or a reason. The Status section says it is a snapshot at two commits and that line numbers hold only there; function names are given as the durable handle. That is the right honesty for a Note that will drift.
- **Restates spec rules?** Only as gap lists in the adapter-work cells ("count 200–299 as success", "map outcomes to the six of [[DATA-MODEL]] §5.2"), each pointing at the rule's home. §4 and §8 cite rather than restate. Acceptable.
- **Names versus A §6:** five rows carry names A §6 does not have: "Meeting-inventory fetchers" (§3.1), "Receipt rewriter (one-off, B0)" (§3.1), "Site pages" (§3.4), "Workflows (orchestration)" (§3.4), and C5 labeled "release upload" where A §13 capability 5 is "Streaming I/O". The labeled one-offs and configuration rows are fine. Change: fold "Meeting-inventory fetchers" into the Fetcher row as its House and Senate sources; add "Site pages" to A §6 (see §1); name the C5 row "C5 streaming I/O and release upload"; label "Workflows" as orchestration of the publish job and capture scheduler, which it already is in parentheses. The plan's D4/D5 now use the A §6 name. Good.

## 5. Scoring

| Area | Score | Why |
|---|---|---|
| One home per rule | 22/25 | Holds everywhere except 2.2 (two definitions of complete), the plan hedge in 2.6 and the triple statement in 2.8. |
| Resistance to erosion | 18/20 | 2.1, 2.3 and 2.4 are the three places a sixth round would add a clause instead of a row. |
| Change cost | 20/25 | Publisher, registry and review changes are one edit; a new format is four or five edits until 2.1 and 2.3 land. |
| Separation and bindings | 18/20 | Clean split; five name drifts between B and A §6. |
| Cross-document consistency | 8/10 | Two inconsistencies (2.2, 2.5), both one-sentence fixes. |

Total 86. Fixing 2.1–2.6 is under an hour of editing and would put it at 93; the rest is sound and should be left alone.

## 6. Must-fix before track B and D

1. 2.2: one definition of `complete` in D §5.2; A §7.1 cites it.
2. 2.5: align P E4's parity cause with D §7.4's per-row rule.
3. 2.1: move the broken-PDF test into the `record_role` ladder.
4. 2.3: the document-extension list into a registry.

Coverage: the full diff since 9a87e119, B in full, the two tables in full; P and A read in the parts the diff touched. Not run: any script, test or build.
