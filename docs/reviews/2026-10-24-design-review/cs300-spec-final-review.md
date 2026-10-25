# CS 300 Final Review: Congressional Document Archive specifications (commit c3b067c4)

Reviewed 2026-10-24 against `c3b067c4` ("give each spec rule one home and apply the final
reviews") in `/Users/mikewolfd/Work/wt/ct-ticket-audit`: `docs/engine-first-architecture.md`
(A, 558 lines), `docs/engine-first-data-model.md` (DM, 664 lines),
`docs/plans/simplification-plan-20261024.md` (P, 288 lines). The earlier rounds are the
committed `cs300-spec-review.md` (finding IDs M/S/N) and my re-review (IDs NP1–NP22).

Method. I read all three documents in full (a restructure cannot be judged from a diff),
kept the diff from `39ae52d2` beside me (`specfinal_docs.diff`, 1,906 lines), walked every
cross-reference in the three documents, checked each invariant against the derivation it
names, and re-measured every number this round introduced or changed on the read-only
2026-10-19 snapshot with DuckDB through the project venv (`specfinal_numbers.py`, output in
`specfinal_numbers.out`). Nothing outside this scratch folder was written.

## Verdict

The restructure worked. Every schema, derivation, order and registry now has one home in the
data model; the architecture explains intent and cites it; the plan only lists work. Of the
roughly fifty cross-references I followed, all resolve to the section they describe. Every
one of my 24 open items is closed (23 fixed, one no longer applies), and the fixes are the
ones I said I would accept. The new parts are mostly right: the record-role derivation is a
single, ordered, testable rule; the model profile with its completeness gate is the correct
way to make "newest complete version" a refusal rather than a hope; the input-identity
argument is sound except for one column; `stored_suffix`/`saved_suffix` close the physical-key
question with an invariant that is checkable against the bucket; the edition guard is
stated so that invariant 14 follows from it.

What remains is small and specific. One new must-fix: `readings.base_url` is derived from
`captures` at parse time, which makes a reading not a function of its body and version, so
invariant 1, principle 1 and the §8.3 identity argument are false as written. Two should-fix
holes that would merge or lose documents: links with a null `group_path` are not excluded
from forming a rendition group, and the `url_state` queue takes links only from real and
listing pages, so URLs discovered through meeting XML records and API JSON have no stated way
into the queue. The rest is wording and stale sizing numbers.

**Ready to build from once the must-fix and the two holes below are written in; each is a
few lines. M1, M2, F0 and tracks A–C can start now; S should absorb the should-fix list.**

## Regrade

| Area | Re-review | Now | Why |
|---|---|---|---|
| Correctness and completeness | B+ (87) | A− (90) | All prior items closed; one new must-fix (`base_url`), two narrow holes (null `group_path`; XML/API-discovered URLs) |
| Efficiency (Big O) | A− (92) | A (94) | Links stored once per body, not per fetch; identity no longer scans partitions; `recoveries` ranged; a sniff-version bump re-sniffs everything (stated nowhere) |
| Determinism and failure behavior | A− (90) | A− (91) | Completeness gate, frozen `link_url_key` registries, `source_id` tie-break, review precedence; `base_url` non-reproducibility; gate vs. fingerprint race |
| Data model quality | B+ (87) | A− (90) | One home per rule, PKs carry `parser_version`, sentinels and nullability settled; `detail` fold's `r.*` now includes `links`; occurrences sized at the old grain |
| Specification craft | B+ (88) | A (93) | Clean cross-references, A §9 non-normative, registries tabled, invariants realigned; `page_shaped` polarity and two unlabeled numbers |
| Plan | A− (90) | A− (92) | Parity against the pinned pair, switch checklist, B10 after B13, M1.3 concrete; stale 4.7M and 1.7M in M2 |

**Overall, the two specifications: A− (91), up from B+ (88). The plan: A− (92), up from A− (90).**

**Counts over the 24 open items (NP1–NP22, S8, N4): 23 fixed, 1 no longer applies (N4), 0 partly, 0 not fixed.**

## Verdicts per open item

| ID | Finding | Verdict | Location and note |
|---|---|---|---|
| NP1 | Listing rule defined two ways, in the wrong layer | **Fixed** | DM §6.2 "Parsers record facts, not classifications"; `record_role` is no longer a readings column; DM §7.3 `listing_signs` is one predicate (minimum link count and link-text share, both in the listing-thresholds registry); A §9.2 is non-normative and gives no competing definition. The fix I asked for. |
| NP2 | `role_from_format` admitted failed parses | **Fixed** | DM §7.3: `null when format in (html, xml, json) and reading.status <> 'completed'`, and "a parsed format whose reading did not complete has no role". An *absent* reading is excluded only by the §7.1 completeness gate, not by the text (minor, F17). |
| NP3 | Completion-row granularity, missing sentinels, required columns | **Fixed** | `page_links` and `links_scanned` are gone, so that half no longer applies. DM §6: `committee_records` and `meeting_records` PKs carry `parser_version`; zero-value sentinels; "every non-PK column of these two tables is nullable". |
| NP4 | `filename_readings` work list depended on the attachment rule | **Fixed** | DM §6.3: pairs "of every capture row and of every provenance recovery's original link … the work list depends on no model decision"; A §8.4 agrees. |
| NP5 | Listed-document estimate ignored the listing exclusion | **Fixed** | A §5 and DM §7.5: "*est.* 0.5–0.7M … and the listing pages among about 200k HTML rows". The 200k reproduces (203,336 HTML-typed rows). |
| NP6 | "174,323 source files" did not reproduce | **Fixed** | The number is gone; DM §7.3 keeps only what reproduces (18/22/12; 87,161 URLs; 57-byte caption file). |
| NP7 | `alternates` "one per format" had no pick rule | **Fixed** | DM §7.5 `alternates := for each other format, its first real source file in the saved-file order`; invariant 10 asserts it. |
| NP8 | "Two checks" with three bullets | **Fixed** | A §9.2 rewritten as non-normative prose; the predicate list lives only in DM §7.3. |
| NP9 | 368,748 undated saved files survive the backfill | **Fixed** | DM §7.5: "About 30% of listed documents are expected to have no capture date: 2.7M of 3.9M capture rows come from older receipt lines that carry no time"; P §6.4 D1 checks the receipts' JSON. Both numbers reproduce. |
| NP10 | Two `schema_version`s; bootstrap `previous_release_id` | **Fixed** | The pointer holds `release_id` and `previous_release_id` "(null until the second flip)" (DM §8.1); A §10.3.7 "From the second flip on"; only the release manifest carries `schema_version` (A §11.4). |
| NP11 | Compact-JSON escaping unstated | **Fixed** | DM §3 names exactly what Python's `json.dumps(ensure_ascii=False, separators=(",", ":"), allow_nan=False)` escapes, lowercase `\u00xx` included; matches `schemas.py:377`. |
| NP12 | Two recoveries for one link share a key | **Fixed** | DM §8.2 "for each distinct original link"; refusal only for keys "derived from different inputs (two bodies, two link URL keys, or a body and a link URL key)". |
| NP13 | Diagram showed `<run>.jsonl.gz` | **Fixed** | A §6 shows `<run>-<seq>.jsonl.gz`. |
| NP14 | MUST inside non-normative §5 | **Fixed** | A §5 "are the per-item work that is not repeated". |
| NP15 | Normative text leaned on the informative Note | **Fixed** | A §8.7 states the fallback without citing the plan; the only plan citations are in non-normative §16.2 and in the plan itself. |
| NP16 | Registry naming drift | **Fixed** | DM §7.1 is the single registry table (13 entries); P §5.3 cites it; "policy table" is gone. |
| NP17 | Duplicate bodiless row | **Fixed** | DM §7.4 "plus, if not already present, one bodiless row per recovery that needs a document of its own". |
| NP18 | Identity re-ran the model during backfills | **Fixed** | DM §8.3: receipt keys, provenance keys and ETags, and the profile; readings partitions are no longer counted. |
| NP19 | `in_archive_since` date source unstated | **Fixed** | DM §7.1 import-run registry holds "`run_id` and date"; DM §7.4 `in_archive_since` is "the registry date of its earliest import run". |
| NP20 | Rubric sentence contradicted `same_body`/`same_text` | **Fixed** | P §5.3: "identical bytes, the same text at one address, or one text in different formats". |
| NP21 | Invariant 22 bundled two assertions | **Fixed** | Non-empty `list` is in invariant 17; "no listing page is a real file" follows from invariant 8's "a body whose `record_role` is not `document`". |
| NP22 | "Archive members" listed as a format | **Fixed** | A §8.3 and DM §7.3 name formats only. |
| S8 | Completion rows (partly, from round 1) | **Fixed** | As NP3. |
| N4 | `links_scanned` (partly, from round 1) | **No longer applies** | The column and `page_links` were removed; the queue (DM §7.7) replaces the need. |

## New problems

### Must fix

**F1. `readings.base_url` is derived from `captures`, so a reading is no longer a function of
its body and version, and three statements that depend on that become false.** DM §6.2
defines `base_url` as "the page's `<base href>`, else the URL of the body's first capture
row in the order `(retrieved_at nulls last, receipt_key, receipt_line, capture_index)`", and
resolves every `links[].child_url` against it. The "first capture row" is a property of the
`captures` table *at parse time*: a late receipt (which the weekly check appends, A §8.2) or
a backfill in a different order can give the same body an earlier first row, so a re-run of
the same parser version on the same body yields different `child_url`s. That contradicts
invariant 1 ("a parser version re-run on a sample of its inputs reproduces its rows, links
included"), principle A §4.1 (every layer derivable from raw plus versioned code), DM §6.2's
own "parsers record facts", and the §8.3 argument that "every other lake row the model reads
is a deterministic function of a body … and of a version". It is also the wrong answer for a
body served at several URLs: relative links on a mirrored page resolve differently per URL,
and the model, not the parser, knows every URL the body was at. *Fix I would accept:* the
parser stores each link's `href` as written plus the page's `<base href>` (a fact of the
body, nullable); the model resolves `href` against `<base href>`, else against each
occurrence's `context_url`, inside `url_key`. `base_url` as a readings column goes. If a
single resolution is kept for cost, define it from the body only and say in §8.3 that
relative links on multi-URL pages resolve against one of them. Practical frequency is low;
the reason it is must-fix is that it makes a stated invariant false and the identity
argument unsound.

### Should fix

**F2. Links with a null `group_path` must form no rendition group.** DM §6.2 says
`group_path` is "the indexed path of the nearest grouping ancestor … or null". DM §7.5 (a)
draws "one node per (page body, group_path)". A `GROUP BY` puts every ungrouped link on a
page into one node; the one-file-per-format rule stops a page of ungrouped PDFs from
merging, but a page with one ungrouped PDF and one ungrouped XML of different documents
(a press release and an unrelated bill text) merges them as renditions. *Fix:* "links with a
null `group_path` join no group"; add it to invariant 14 or 10.

**F3. `page_shaped(locator)` is stated with inverted polarity.** The registry (DM §7.1)
holds "regular expressions over the locator that mark a link as *file-shaped*"; `real_files`
requires `page_shaped(locator)` for HTML; DM §7.3 says only "`page_shaped(locator)` is the
page-shape registry". An implementer who reads that literally applies the registry as a
match and keeps exactly the HTML bodies the rule means to drop. *Fix:* "`page_shaped(locator)`
is true when no page-shape registry pattern matches the locator."

**F4. The completeness gate and the fingerprint race contradict each other.** DM §7.1:
"Publish MUST refuse when a pinned version's work list is not empty at the pinned snapshot."
DM §7.3: "`real_files` is evaluated twice per publish … A body that lands between the two
gets its fingerprint one run later." A body that lands between the `fingerprint` step and the
pin puts a row on the pinned `fingerprint` version's work list, so the gate refuses rather
than deferring. Within one publish job nothing appends between the two steps (maintenance
shares the concurrency group, A §10.3.7), so the race needs an on-demand backfill or a
second writer; still, the two sentences cannot both be true. *Fix:* either exempt
`fingerprint` from the gate (a missing fingerprint only loses a `same_text` edge for one
run) or delete the "one run later" sentence and let the gate refuse.

**F5. The queue cannot see URLs discovered through meeting XML records or API JSON.**
DM §7.7: "Each child URL in the links of a real page or listing page that matches the
capture-scope registry …". Meeting XML records are `source_record` (DM §7.3), so their
document lists, which DM §7.5 reads for `meeting_ref`, feed no queue row; API JSON has no
`links` at all (DM §6.2 emits links "in an HTML or XML page"). A §12 says capture "builds its
queue from the live release's `url_state`". Either `url_state` is the whole queue and these
URLs are lost, or fetchers keep their own discovery and A §12 overstates. *Fix:* include
`source_record` readings' links in the queue, say how API-discovered URLs enter it (the JSON
parser can emit `links` too), and state in A §12 whether `url_state` is capture's only queue.

**F6. The HTML-signal invariant was lost in the restructure.** The previous invariant 5
required every HTML real file to carry `title`, `heading`, `text_bytes`, `link_count` and
`link_text_bytes`. Now a *completed* HTML reading with null `text_bytes` evaluates
`error_signs` and `listing_signs` to null, falls through to `'document'`, and becomes a real
file silently. *Fix:* restore the requirement as an invariant on completed HTML readings, or
define `status = 'completed'` to imply those columns are set.

**F7. The `detail` fold's "the saved file's reading (`r.*`)" now includes `links` and
`fields`.** `links` is a nested list of structs; a saved HTML page with hundreds of links
would fold them as strings, and the fold is supposed to hold display-only scalars. This is
also the likeliest cause of the unexplained jump in the `detail` estimate from 30–50 MB to
55–70 MB (DM §8.1) with no note. *Fix:* enumerate the reading columns the fold carries
(title, heading, text sizes, content date, format) and exclude `links` and `fields`.

**F8. `occurrences` changed grain but kept its old size.** DM §7.10 defines one row per
distinct `(source_id, member_path)` of a listed document's members; P §5.2 still sizes M2
with "the 4.7M `occurrences`" and DM §8.1 keeps "20–30 MB". Measured over every source file,
the new grain gives about 1.7M rows (1,683,430 source files, of which 679,405 archive-member
rows expand to 691,015 member paths); the listed subset is smaller. *Fix:* re-derive the
count and size at the new grain.

### Minor

- **F9.** DM §7.7 "1,158,426 rows" excludes the queue rows it just defined ("16,753 such
  URLs wait today"); say about 1.18M.
- **F10.** P §5.2 "about 4.2M links against 1.7M source URLs": source files are 1.68M, but
  distinct source URLs are 1,313,678 (measured). The join is against 1.3M URLs.
- **F11.** DM §7.10 "`outcome` is the latest attempt's outcome at that endpoint" names no
  order; cite §7.7's `(retrieved_at nulls first, receipt_key, receipt_line)`.
- **F12.** The model profile (DM §7.1) pins "the model SQL version" without saying what it
  is; define it as the digest of the SQL files, like a registry's.
- **F13.** `link_url_key` (DM §8.2) depends on registry versions "fixed when link keys were
  first published"; name those frozen versions in the profile so the identity covers them.
- **F14.** DM §6.2's `sniff` work list ("every body whose capture rows carry no sniff at the
  pinned sniff version") means a sniff-version bump re-sniffs 1.04M+ bodies by ranged read;
  state it as a cost consequence, since A §4.4 names every other repeated pass.
- **F15.** `alternates` and `recoveries` carry a `suffix` (DM §7.5, §7.8, §8.1) whose
  derivation is stated only for `saved_suffix`; say "by the `saved_suffix` rule".
- **F16.** DM §7.5 (b) "the same directory and filename stem": say whether the directory is
  compared on `url_key` or on the raw URL.
- **F17.** DM §7.3 `null when … reading.status <> 'completed'` does not cover an absent
  reading; write "no reading or"; the gate makes absence impossible only while it holds.
- **F18.** DM §6.4 `parent_system_code` lost its "nullable" annotation; the §6 paragraph
  covers it, but the table style elsewhere marks nullability per column.
- **F19.** "Embedded PDF titles are not read; names stay filename-based" (an owner decision)
  left A §8.3 in the restructure; it is implied by "no full reading" but was a rule.
- **F20.** DM §6.2 "287,765 HTML and XML bodies" reproduces exactly by *server media type*
  (175,197 HTML + 112,569 XML distinct bodies), the classifier the spec forbids; label it as
  a sizing estimate by media type.
- **F21.** `base_url` for an archive member resolves relative links against the container's
  URL (DM §6.2); folds into F1.
- **F22.** A §9.2 (non-normative) summarizes the real-file rule without "not a placeholder";
  harmless, but the summary should not drop a condition.

## Numbers checked this round

| Claim | Where | Result | Status |
|---|---|---|---|
| Normal day: 3,553 capture rows from 2,946 receipt lines on 2026-10-16 | A §5 | 3,553 / 2,946 | measured, exact |
| 59 URLs whose only copy was cut off at 64 MiB (was 62) | P §6.2 B14 | 59 of 207 URLs with a 64 MiB row have no other body | measured, exact |
| 287,765 HTML and XML bodies | DM §6.2, P §6.4 | 287,765 distinct bodies by server media type | measured, exact (F20) |
| 498 / 955 / 2 source rows with several measure numbers / date tokens / congresses | DM §6.3 | 498 / 955 / 2 | measured, exact |
| About 200k HTML rows in the old catalog | DM §7.5 | 203,336 | measured |
| 2.7M of 3.9M capture rows without a time; about 30% of documents undated | DM §7.5 | 2,717,129 rows; 368,748 of 1,227,627 old saved bodies | measured |
| 4.7M occurrences | P §5.2, DM §8.1 | about 1.7M at the new grain (1,683,430 source files; 691,015 member paths) | stale (F8) |
| 1.7M source URLs | P §5.2 | 1,313,678 distinct source URLs | wrong (F10) |
| 16,753 queued URLs | DM §7.7 | not reproducible without parsed links (old state has 23,897 `pending`) | from the spec |
| About 1,300 list requests; about 105 MB per changed day; about 0.7 GB per week | A §7.4, §16.1, §10.3.7 | (1,036,256 + 261,055) / 1,000 ≈ 1,297; 96–127 MB from DM §8.1 sizes; 7 × 105 | arithmetic consistent |
| 19 page reads per detail view | A §10.1, §16.1, DM §8.1 | 19 leaves in the typed core plus the fold's two | consistent |
| `detail` 55–70 MB | DM §8.1 | unexplained rise from 30–50 MB | estimate (F7) |
| 18 / 22 / 12 placeholders; 87,161 URLs; 57-byte caption | DM §7.3 | unchanged, exact | measured earlier |
| Compact JSON and ID formulas | DM §3, §7.4, §7.5 | match `schemas.py:377`, `bipartite.py:165–205` | verified earlier |

## Checks that passed

- Every cross-reference I followed resolves: A §3 → DM §4, §7.1–7.3, §7.5, §8.2, §8.3; A §7–8 →
  DM §5.1–5.3, §6, §6.1–6.5; A §9 → DM §7; A §10.1 → DM §8.1; A §10.3.1 → DM §8.3; A §11.5 →
  DM §7.5; A §13.5 → §7.1, §10.3.4; A §16.2 → P §5; DM §5–8 internal references; P → A §7.1–7.2,
  §8.1, §8.7, §9.4, §10.3.5, §10.3.7, §11, §12 and DM §5.2, §6, §6.6, §7, §7.1, §8.1.
- Invariants 4, 5, 8, 10, 11, 12, 13, 14, 16, 17, 18, 19 and 20 match the derivations they
  name (gate, completion rows, record roles, saved-file order and alternates, dates, queue,
  attachment, edition guard, ranges, link keys, pointer).
- The restructure orphaned no rule I could find: every MUST or rule that A §9 lost has a
  normative home in DM §5–8 (media type never classifies, archive members by their own
  path, same-format files stay apart, recovery exclusions, unmapped codes and largest
  components reported, URLs still wrapped reported).
- The three documents agree on the five lake tables, the six site files, the removal of
  `links` from receipts, the three-retry conflict rule, the shared concurrency group with its
  stated exception to "no CI dependence", and the renumbered sections.

## What remains before building

1. F1: make links a fact of the body (store `href` and `<base href>`; resolve in the model).
2. F2 and F3: two sentences in DM §7.5 and §7.3.
3. F5: decide whether `url_state` is capture's only queue and give meeting-XML and API
   links a way in.
4. F4, F6, F7, F8 during S and F0, where the sample, the parser and the first export make
   them concrete.
