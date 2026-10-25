# CS 300 Final Review: Congressional Document Archive specifications (commit 9a87e119)

Reviewed 2026-10-25 against `9a87e119` ("separate the code bindings from the specs and the
plan") in `/Users/mikewolfd/Work/wt/ct-ticket-audit`: `docs/engine-first-architecture.md`
(A, 603 lines), `docs/engine-first-data-model.md` (DM, 699 lines),
`docs/plans/simplification-plan-20261024.md` (P, 284 lines) and the new
`docs/plans/bindings-20261025.md` (B, 184 lines). My previous round is the recheck of
`d9730967` (finding IDs R1–R15).

Method. I read all four documents in full, kept the diff from `d9730967` beside me
(`specfin_docs.diff`, 1,119 lines), checked the new derivations against the invariants that
name them, and re-measured every number the edits introduced or changed on the read-only
2026-10-19 snapshot with DuckDB through the project venv (`specfin_numbers.py`,
`specfin_names.py`, `specfin_names2.py`, outputs beside them). I also read the four code
locations the bindings cite for the committee-code, effective-filename, meeting-ID and API-key
seeds, read-only. Nothing outside this scratch folder was written.

## Verdict

**Ready to build from. No must-fix item remains.** Thirteen of my fifteen recheck items are
fixed as I asked (R1 restores a 64 KB page byte limit beside the row limit and re-derives the
per-view figure; R2 fingerprints every rendition-group member, with the cost stated; R3–R5
settle the queue, the relative base and the placeholder links), one is partly fixed (R13: the
plan still says 64 cut-off URLs where the index gives 62 under either definition) and one minor
is not (R15: the `detail` 55–70 MB figure still has no stated basis).

The code-inventory additions are the right kind of change: receipts now exclude credentials,
cookies and local paths by rule and by invariant; the body is the content-decoded entity;
206 means incomplete; archive members carry an entry index; the file name comes from the
download header first with an exact decoding rule; committee codes are a registry; and
the one sanctioned rewrite of raw history (the receipt cleanup) has a rule, a verification
record and a safety net. They also added surface, and seven should-fix items sit in that
surface: the effective-filename rule is circular about which fetch's header names a file; the
cleanup rule and invariant 3 disagree about credential parameters, and the cleanup does not
name the fields or the path recognizer it rewrites; `entry_index` in endpoint matching makes
every archive-member link target unmatchable; and three new facts ("the entry's outcome" for
a refused expansion, "the recovered name if provenance says so", a provider's status
"recorded apart") name fields that do not exist. Two of these should be settled before B0
runs, because B0 is irreversible once the lock is on.

One concern I carried into this round dissolved under measurement: 460,273 source files
(27%) are named today only from `download_state`, which the new precedence drops, but
460,257 of those names equal the URL's last path segment, so the new rule reproduces them.

## Regrade

| Area | Recheck | Now | Why |
|---|---|---|---|
| Correctness and completeness | A− (92) | A− (92) | R1–R12, R14 closed; new gaps are narrow: filename grain, `entry_index` in link matching, two cleanup-rule mismatches |
| Efficiency (Big O) | A (93) | A (94) | Page byte limits back; placeholder links skipped; contexts measured at 1.3 per page; fingerprint cost stated and conservative |
| Determinism and failure behavior | A (94) | A (93) | Cleanup verified by re-read and record; `withdraw` defined; but which fetch's header names a file is unspecified |
| Data model quality | A (93) | A− (92) | Four new facts lack a field: expansion outcome, recovered filename, provider status, `recovered_url` on import rows |
| Specification craft | A (94) | A (94) | Components table and principle 8 fit the one-home rule; one normative citation of the plan (A §7.2 → B0) |
| Plan and bindings | A (93) | A (94) | Work ordered by component, code named only in the bindings Note, B0 procedure with a safety net; the 64 does not reproduce |

**Overall, the two specifications: A (93), unchanged. The plan with its bindings Note: A (94), up from A (93).**

**Counts over the 15 recheck items (R1–R15): 13 fixed, 1 partly (R13), 1 not fixed (R15, minor), 0 no longer apply.**

## Verdicts per recheck item

| ID | Finding | Verdict | Location and note |
|---|---|---|---|
| R1 | Page byte limits dropped from `detail`/`occurrences` | **Fixed** | DM §8.1: "on every leaf an offset index, 64 KB data pages and a 1,024-row page limit; write batches of 1,024 rows"; `occurrences` likewise; per-view figure re-derived to 50–90 KB (DM §8.1, A §16.1). With both limits a `saved_body` page is 32 KB and a fold page at most 64 KB uncompressed, so 19 pages at 50–90 KB is consistent. |
| R2 | `edition_bodies` could not reach unfingerprinted copies | **Fixed** | DM §6.2 candidates now include "every real body that is a member of a rendition group before the edition check"; DM §7.5 `edition_bodies` over candidate bodies; A §8.3; P D2; owner decision. Cost stated as *est.* 20–45 GB once (see G17: conservative). |
| R3 | API-discovered URLs had no way into capture | **Fixed** | A §12: capture "follows what its fetchers discover in the same run, such as the documents an API response lists"; `url_state` is the schedule plus the page-derived queue. |
| R4 | Relative `<base href>` unresolved | **Fixed** | DM §7.2: "a relative `base_href` is first resolved against the context". |
| R5 | Link targets multiplied by contexts for mirrored bodies | **Fixed** | DM §7.2: "Placeholder bodies' links are not resolved. Pages average 1.3 contexts (277,642 contexts over 214,041 good-fetched HTML and XML bodies)". Reproduces within 0.2%. |
| R6 | "Ingested only by publish" | **Fixed** | A §12 "Only publish and the weekly check ingest captures, and they never overlap (§10.3.7)". |
| R7 | Context column unnamed | **Fixed** | DM §7.2 "its `context_url` for a top-level page". |
| R8 | `detail.link_key` for several recovery spellings | **Fixed** | DM §8.1 "the link URL key of its first recovery in the recovery order". |
| R9 | `good_fetch` includes import runs, unstated | **Fixed** | DM §7.3 "(import-run rows included; capture dates exclude them, §7.4)". |
| R10 | No way to withdraw a review | **Fixed** | DM §5.3 `withdraw` verdict; §7.9 "A `withdraw` record supersedes one and applies nothing". |
| R11 | Dropped review edges unreported | **Fixed** | DM §7.9 "The model reports a review whose target or value no longer resolves to a document". |
| R12 | "1,024-value write batches" | **Fixed** | DM §8.1 "write batches of 1,024 rows". |
| R13 | 64 cut-off URLs did not reproduce | **Partly** | P B14 now reads "64 by the snapshot index, confirmed against the receipts". The index gives 62 under both definitions I can state (no 2xx row of another body: 62; only cut-off copies: 59). The plan rightly defers to the receipts; the 64 should be re-measured or its definition written. |
| R14 | "455" at a different grain | **Fixed** | DM §7.10 "sized from today's catalog (1,695,040 rows; its largest document has 455)". |
| R15 | `detail` 55–70 MB without a basis | **Not fixed** (minor) | DM §8.1 keeps the figure with no basis; the fold now holds four reading columns, so the number should be re-derived in F0 or its basis stated. |

## New problems

### Should fix

**G1. The effective-filename rule is circular about which fetch names a file.** DM §7.4
derives the name per capture row, with the `Content-Disposition` header third in precedence,
and then says "A file has exactly one effective name; the other names it was offered stay in
its capture rows." But a source file is *defined* as `(body, effective filename, source URL)`,
and the header varies per fetch: one fetch of a URL may carry `Content-Disposition` and the
next may not, or carry a different name. Nothing says which row's header wins, so two rows of
one `(body, endpoint)` can yield two source files, which is what "one name per file" means to
prevent. Measured: 95,664 source files carry a header-derived name today and 94,635 of them
also carry a URL-path name; P §6.5 E4 expects them to collapse, so the rule that collapses
them must exist. *Fix I would accept:* define the effective name per `(body, context_url,
member_path, entry_index)` as the first precedence item that any of its good-fetch rows
supplies, taking the header from the latest good fetch in `url_state`'s attempt order when
several rows carry one; then the source file is `(body, that name, source URL)`.

**G2. The cleanup rule and invariant 3 disagree about credential parameters.** P §6.2 B0
removes "`Set-Cookie`, `Cookie` and `Authorization` values" and local paths, "nothing else";
DM §5.2 says the same; invariant 3 says "No receipt line carries a credential parameter in a
recorded URL, a cookie or a local file path", which covers older lines too. Measured on the
snapshot's recorded `context_url`s: no `api_key`, `apikey`, `access_token` or `token`
parameter anywhere, and 6 rows (2 distinct YouTube URLs) with a `key=` parameter, so the gap
is small, but the one sanctioned rewrite happens once and the lock follows. *Fix:* add the
credential-parameter registry to B0's rule and to DM §5.2's cleanup sentence, with the
removed count in the verification record, or scope invariant 3's credential clause to new
lines and have the B0 re-scan assert the older ones. Settle it before B0 runs.

**G3. The cleanup does not name what it rewrites.** "Replace every absolute local path with
its last segment" (P B0) and "every line equals the original minus exactly those fields"
(the verification step) presuppose a list of fields and a recognizer for a local path
(`/Users/…`, `/home/…`, `/tmp/…`, a drive letter), yet neither is written. Member paths,
`pointer` JSON paths and URL paths look like paths and must be untouchable. *Fix:* name the
fields B0 may touch (the old import lines' local-path fields and the `download_state` row)
and the recognizer, as a one-off registry with samples, so the re-read check is exact.
Settle it before B0 runs.

**G4. `entry_index` in endpoint matching makes archive-member link targets unmatchable.**
DM §7.2 says endpoint matching compares `(url_key(context_url), member_path, entry_index)`,
and DM §7.10 matches `linked_from` "by `url_key`" to the occurrence's endpoint. A link target
resolved against a member path (DM §7.2, "an endpoint in the same container") has a member
path but no entry index, so it never equals an endpoint that has one; no member occurrence
gets `linked_from`, and no same-container link ever joins. *Fix:* link-target matching
compares `(url_key(context_url), member_path)` and ignores `entry_index`; `same_text` and
`ambiguous_bodies` keep the full triple, which is where two same-named members must stay
apart. Say also that `occurrences`' grain `(source_id, member_path)` omits `entry_index` on
purpose.

**G5. "A refused expansion is recorded as the entry's outcome" names a field that does not
exist.** A §7.2. `outcome` is a line field with a closed enum (DM §5.2); the `captures[]`
entry has no outcome, and none of the six values means "expansion refused". *Fix:* an entry
field (`expansion`: `expanded`, `refused_size`, `refused_count`, `refused_nesting`, `none`) in
DM §5.2 and §6.1, or record refusal on the container line in a named field.

**G6. "The recovered name if provenance says so" has no source field.** DM §7.4's first
precedence item reads a filename from provenance, but the `recoveries` record (DM §5.3)
carries `original_url`, `recovered_url`, `body_sha256`, `kind`, `match_basis`,
`evidence_sha256`, `identity_note` and no filename. B §4 K23 ("recovered filenames for legacy
cache names") says the seed exists. *Fix:* add `filename` (nullable) to the `recoveries`
provenance record.

**G7. A provider's status is "recorded apart" (DM §5.2 `http_status`) in no named field.**
*Fix:* `provider_status` on the line, or inside `prior_attempts`, and say which the direct
try and the provider try occupy.

### Minor

- **G8.** `recoveries` (DM §7.8) emits `recovered_url`, `evidence_sha256` and `identity_note`
  for every import row, with the decision nullable, but the `captures` import columns
  (DM §6.1) hold neither `recovered_url` nor `evidence_sha256`; add them, or mark the three as
  null when no decision matches.
- **G9.** The capture-scope registry is in the model profile and also drives fetchers
  (A §7.1, DM §7.1 "Used by: `url_state`; fetchers"); say which version a fetcher applies
  (its own code's, or the live release's profile).
- **G10.** Recorded URLs lose their credential parameters (A §7.2); for a host that accepts a
  key only in the query, say that capture re-adds it from configuration when it fetches a
  recorded URL, or the queue row is not re-fetchable.
- **G11.** `url_key` could also strip the credential-parameter registry, so an older URL with
  a key and its clean successor join; two URLs today, so minor.
- **G12.** `text_head` (DM §6.2) adds about 575 MB raw (287,765 × 2 KB) to `readings`; the
  size note ("16.5 MB, before links") should say so.
- **G13.** A §16.1's repeated-work list says the `fingerprint` producer "evaluates the
  real-file rule once more"; with the new candidate set it also evaluates link resolution and
  rendition grouping before the pin.
- **G14.** `recoveries.parquet` (DM §8.1) has a 1,024-row page limit but not the 64 KB byte
  limit the other ranged files have.
- **G15.** A §7.2 cites "[[IMPLEMENTATION-PLAN]] B0" from normative text; cite DM §5.2 and
  §5.3 instead.
- **G16.** B0 uses "the body store's conditional write" while B3, later, writes the body
  store's refusal matrix that forbids any non-create-only write; say the cleaner uses a
  one-off `If-Match` rewrite that the matrix forbids afterwards.
- **G17.** The fingerprint cost estimate (DM §6.2, P D2: *est.* 20–45 GB) is conservative:
  the same-directory same-stem proxy over today's catalog gives 17,085 bodies and 7.0 GB
  (12,359 PDFs averaging 0.42 MB, 5.2 GB); publisher-grouped members add an unmeasured
  amount. Fine as an upper bound; label it so.
- **G18.** "one level of nesting" (A §7.2): say whether an archive inside an archive is an
  entry only or is itself expanded.
- **G19.** The query-parameter names in the precedence (`filename`, `file`, `name`,
  `document`, `attachment`) include generic ones; `?name=` carries non-filenames. Put a case
  in the labeled sample.

## Numbers checked this round

| Claim | Where | Result | Status |
|---|---|---|---|
| 277,642 contexts over 214,041 good-fetched HTML and XML bodies | DM §7.2 | 277,268 contexts, 214,014 bodies (server media type, 2xx, complete, members at their container URL) | measured, within 0.2% |
| About 95,000 (95,664) files carry a download-header name | P §6.5 E4 | 95,664 source files with a `content_disposition` name origin; 94,635 also have a URL-path name | measured, exact |
| 64 cut-off URLs with no complete 2xx copy | P §6.2 B14 | 62 (no 2xx row of another body, any resolution); 59 with only cut-off copies | approximate (R13) |
| Credential parameters in recorded URLs today | DM §5.2, invariant 3 | 0 `api_key`/`apikey`/`access_token`/`token`; 6 rows, 2 distinct YouTube URLs with `key=` | measured (G2) |
| Names the new precedence cannot produce | DM §7.4 | 460,273 source files named only from `download_state`; 460,257 equal the URL's last segment, 15 have an empty segment, 1 differs | measured; passes |
| Fingerprint candidates in rendition groups, *est.* 20–45 GB | DM §6.2, P D2 | same-stem proxy: 17,085 bodies, 7.0 GB, of which 12,359 PDFs, 5.2 GB; average PDF body 1.54 MB over 261,056 | estimate, conservative (G17) |
| `text_head` storage | DM §6.2 | 287,765 × 2 KB ≈ 575 MB raw | arithmetic (G12) |
| 1,695,040 occurrences; largest document 455 | DM §7.10 | unchanged, labeled | measured earlier |
| B0 sample: 33,585 cookies and 24,375 paths in 74,863 lines of 150 receipt files | P §6.2 B0 | not checkable from the snapshot (no raw receipts) | from the plan |
| 50–90 KB per detail view, 19 pages | DM §8.1, A §16.1 | consistent with 64 KB pages and a 1,024-row limit | consistent |

## Checks that passed

- Bindings seeds exist where cited: `matching/house.py` carries the `hl` form with the
  `hlig00 ↔ IG00` example DM §7.5 uses; `index/sources.py` decodes a URL basename with strict
  UTF-8 and a literal `+`, as DM §7.4 states, and its name order (member, header, URL path,
  query names, retained path) is the one DM §7.4 adopts; `index/records.py:483` strips only
  `HMKP`, the defect B §7 lists and DM §7.5 corrects; the committee fetcher builds its detail
  URL "without query credentials", which matches the absence of API keys in recorded URLs.
- Invariants 3, 13 and 14 match the derivations they name (new-line field requirements;
  one recovery per import row with a nullable decision; `edition_bodies` over candidate
  bodies). Invariant 1's parser-reproducibility clause still holds: `base_href` and `href`
  are stored as written.
- Cross-references the edits touched resolve: A §3 → DM §7.1–7.3, §7.5, §8.2–8.3; A §6 table
  → §7–13 and DM §5–8; A §7.1 → DM §5.1, §7.1; A §7.2 → DM §5.2 and P B0; DM §5.3 → §7.5,
  §7.8, §7.9; DM §6.2 → §7.3, §7.5; DM §7.4 → [[RFC6266]]; P → A §6, §7.1–7.2, §8.1, §8.7,
  §10.3.5, §10.3.7, §11, §11.5–11.6, §12, §13, §15.7 and DM §5.2–5.3, §6, §7, §7.1, §8.1;
  B → [[INVENTORY]] by section.
- The three documents agree on five lake tables, six site files, the content-decoded body
  identity, 206 as incomplete, the entry index, the header allowlist with
  `Content-Disposition` and `Retry-After`, the two raw-writer registries outside the profile,
  the one-time cleanup as the only rewrite, and the digest-versioned parsers and catalog.
- The separation holds: the specifications name no existing code; the plan orders work by
  component and cites contracts; the bindings Note carries every path and line number.

## What remains before building

1. Before B0 runs: G2 (credential parameters in the cleanup rule or out of invariant 3) and
   G3 (the fields and the path recognizer), since the rewrite is irreversible under the lock.
2. Before S fixes the rules: G1 (which fetch names a file) and G4 (`entry_index` out of
   link-target matching).
3. Before D1 and B7: G5, G6, G7 and G8, which are one field each.
4. The minors whenever the documents are next touched; R15 in F0.
