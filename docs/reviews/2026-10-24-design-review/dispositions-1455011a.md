# Dispositions: the evolutionary-refactoring review of 1455011a

Six reviewers audited the documents at `1455011a` with the evolutionary-refactoring skill: the spec writer, the spec reviewer, the professor, the Iceberg/Parquet reviewer, the inventory reviewer and Codex. Their reports sit beside this file, named `*-evolutionary-1455011a.md`. This ledger records what happened to each finding. A = architecture, DM = data model, P = plan, B = bindings.

## Scores at 1455011a

| Reviewer | Verdict | Score |
|---|---|---|
| Professor | Ready; two one-sentence fixes | Architecture 94, plan 94 |
| Spec reviewer | Ready; one fix | Specifications 92, plan with bindings 94 |
| Codex | Not ready; six bounded fixes | Architecture 86, plan 89 |
| Spec writer | Build from it; four fixes | 86 |
| Iceberg/Parquet | Ready once one rule is fixed | 85 |
| Inventory (bindings only) | Most rows ready; two before B2 | 82 |

Mean of the six overall scores: 88. The three reviewers who also scored `9a87e119` average 91.5 here, against 91.7 then.

## Owner decisions taken in this round

- **78.** `captures` holds only what a rule reads; `fidelity` stays, and the saved file prefers the exact copy within a format.
- **79.** Senate meeting records come from Congress.gov only; Senate pages supply documents.
- **80.** The committee explorer reads committee and meeting records from the lake after the switch.
- **81.** The owner decides on widening the fingerprint candidates after S's edition count; there is no preset threshold.

## Found by several reviewers

| Finding | Reviewers | Disposition |
|---|---|---|
| New PDFs never become real files: `intact` came only from the `sniff` reading, which skips new bodies | Iceberg W1, writer 3, spec N1/S1, professor 4, Codex N1 | Fixed: the fetcher records `intact` (DM §5.2, §6.1); the model coalesces it like `format` (DM §7.3); a PDF whose `intact` is not true takes the `damaged` role, so `real_files` has no format clause; `sniff` reads an older PDF's tail from its `.pdf` copy after B13 and opens it with the bounded reader only when that fails (DM §6.2, P D2) |
| "Complete" defined twice, and the definitions disagree | Writer 1, spec S5, professor must-fix 2, Codex N2 | Fixed: one definition by length in DM §5.2, with `If-Range` on every range request so an assembly is one entity; A §7.1 and P B2 cite it; the ingest mapping derives it for older rows |
| `repair` inside `url_key` can return several URLs | Spec S3, professor 5, Codex N5 | Fixed: repair runs on each `href` before resolution (DM §7.2); `url_key` stays one-to-one |
| Rendition rule (b) hard-codes the document extensions | Writer 4, spec audit, professor 7 | Fixed: it groups the formats the format-preference registry lists |
| The registry table does not say who uses or versions each registry | Writer, spec audit 5, Codex, Iceberg W5 | Fixed: a "Versioned by" column and consumers named per row (DM §7.1); the prose above the table is gone |

## Spec writer

| Finding | Disposition |
|---|---|
| Three not-done items from the last round | Accepted by the writer |
| P E4 still said each file has one name | Fixed: a name per capture row, download header first |
| DM §6 note on the engine's write caps | Partly: kept as a marked note that goes when M1 decides, since the professor asked for it three rounds running |
| P C4 "no application logic" clause | Fixed: deleted (A §13 owns it) |
| DM §6.2 narrow-columns sentence | Fixed: deleted (A §13, item 6 owns it) |
| Bindings names that are not in A §6 | Fixed: fetcher sources and adapters start with "Fetcher", C5 is "streaming I/O and release upload", and A §6 gains "Site pages" |

## Spec reviewer

| Finding | Disposition |
|---|---|
| G1–G19, R13, R15 from the last round | 19 fixed and 2 accepted as not done, by the reviewer |
| S2: "the URLs a copy is known by" defined three ways | Fixed: `copy_urls` (DM §7.2) serves `publisher_links`, `linked_from` and recovery attachment. The queue keeps its own test, because it asks whether a URL was ever attempted, not which copy it names |
| S4: sniff is no longer one ranged read | Fixed: the tail read and the bounded reader are stated (DM §6.2); a PDF over the reader's limit is `damaged` and reported |
| N2 feeds list as documents | Fixed: a feed is a `listing` (DM §7.3) |
| N3 MODS join unstated | Fixed: by the GovInfo package ID in both URLs |
| N4 kind fallback needs a removal condition | Fixed: it goes once every import carries a category (B7) |
| N5 the shared-path sentence follows from null-safe endpoints | Declined: Codex asked for duplicate-path matching to be stated explicitly |
| N6 a queue link can carry a credential | Fixed: queue rows drop credential parameters; invariant 12 |
| N7, N8 invariants 8 and 1 | Fixed |
| N9 two producers write `fingerprint` | Fixed: each body's fingerprint comes from exactly one reading |
| N10 a re-added document reads as removed | Fixed: `removed_on` reads each hearing page at its latest good fetch |
| N11 the edition count needs text | Fixed: S fingerprints its small population (a census of about 15 bodies) |
| A §9 as a second informal home | Fixed for §9.2; §9.3–9.5 already state intent |
| The effective-filename chain as one ordered list both evaluators read | Fixed: DM §7.4 lists it once; the producer and the model evaluate the same SQL |

## Professor

| Finding | Disposition |
|---|---|
| Must-fix 1: B0 cut paths in "every string value" | Fixed: named fields only, from a read-only scan the owner confirms; the re-scan asserts no URL, link, pointer or redirect value changed (DM §5.2, P B0) |
| Older lines carry members but no `expansion` (75 GB of ZIP reads) | Fixed: the ingest mapping sets `expanded` |
| `retry_later` mapping, a ceiling, header versus deadline | Fixed: 429, 503 or any `Retry-After`; capped at the family's interval; the receipt keeps the header and the lake resolves the deadline |
| `recovered_filename` joined by `url_key` inside the producer | Fixed: by the exact URL |
| A family registry | Fixed: the source-family registry (raw writer) |
| `fidelity` read by nothing | Fixed (decision 78) |
| A §7.2 and §8.3 restate DM rules; `retained_name` has no receipt field | Fixed |
| E4 should name the 460,000 `download_state`-only rows | Fixed |
| S is a single gate for track C | Fixed: S1 before C, S2 beside it |
| `meeting_ref` takes the first source where the rest of the model keeps every value | Fixed: the union of every source |
| The candidate numbers disagree (1.4 GB against about 13 GB of PDFs and 1,368 ZIPs) | Fixed: DM §6.2 and P D2 give an estimated range that D2 measures |
| Optional: scope a sniff version's re-read | Declined: a full re-sniff is bounded (about 1.04M ranged reads) and rare |
| Links as an attribute map | Deferred: revisit if a fourth House attribute arrives |
| The lock order in four places | Fixed: B0 no longer repeats it |

## Iceberg/Parquet

| Finding | Disposition |
|---|---|
| W2 schema growth | Fixed: DM §6 "Schema growth"; A §13, item 2; P C2 and M1, item 4 |
| W3 `captures` columns nothing reads | Fixed (decision 78): `pointer`, `entry_index`, `provider_status`, `publisher_requested`, `transport`, the four header columns and `observed_capture_ts` dropped; the receipt keeps them |
| W4 three writer profiles; the detail-view estimate in three places | Fixed: whole, ranged and lookup in DM §8.1; A §10.1 and §16.1 cite it |
| W5 one digest for all registries; capture scope in the release | Partly: `capture_scope.json` ships in the release; per-registry versions stay, because a registry's version scopes which work lists its change touches |
| W6 which source wins for `recovered_url` and `evidence_sha256` | Fixed: the import row |
| W7 two meanings of `meeting_refs`; two names for one category | Fixed: the readings column is `named_meetings`; `recovery_category` is the receipt's `prior_access_category` |

## Inventory (bindings)

| Finding | Disposition |
|---|---|
| The Note cites a check that is not in the repository | Fixed: both checks are committed beside this file and cited |
| Three wrong dormant-code uses | Fixed: the document probe labels S's sample and checks B14, then goes; `archive/tools/` reviews a new catalog version; `bill_codes.py` checks `measure_keys`; `deduplicate_reading_table` is deleted and the rebuild check is engine SQL |
| Senate meeting records with no event ID | Fixed (decision 79) |
| The engine reads no JSON lines | Fixed: A §13, item 1; P C1 |
| The relist watermark lives in a state file | Fixed: from `url_state` |
| K17 and K29 seeds | Fixed |
| R1 receipt writer, R3 body store, R4 recovery importer, R5 HTML and XML parsers, R6 C3 export | Fixed: each is Build, seeded, lifting the named parts; R6 is confirmed by the C3 determinism suite |
| R2 the fetcher's memory reservation and classification retries | Fixed: deleted |
| R7 origin rules | Fixed: rules as data, applied with the platform tool |
| R8, R9, R10 | Fixed: split rows; the explorer reads the lake (decision 80); one pin file |
| B1 evaluate an RFC 3986 crate; B3 keep the union-find | Fixed; kept |
| The Note restates spec rules | Partly: the receipt writer names the code facts that break the contract; other cells still list target behaviors where the gap is the behavior itself |
| §8 repeats §3; no version-digest row; no adapter rows | Fixed |

## Codex

| Finding | Disposition |
|---|---|
| Items 1–3 from the last round | Fixed, by Codex's verdict |
| Item 4: an acceptance sheet and a decision procedure | Fixed: P §5.3 gives every fixture its expected outcome and states how the edition count is taken; the decision stays with the owner (decision 81) |
| Item 5: cleanup, bindings and references | Fixed |
| N3 aliases of one body break a rendition group | Fixed: a group counts distinct real bodies per format, with a fixture |
| N4 publisher evidence applied unevenly | Fixed: one `publisher_links` relation feeds the kind fallback (by `doc_type`, else link text), meetings and removal |
| Filename selection not total | Fixed: registry order, first occurrence |
| Plan §2 and F3 cite the wrong bindings section | Fixed |
| A bounded input for the cleanup | Fixed: the backup's receipt keys plus any written since |

## Not done

- **Declined:** spec N5 (kept for Codex); the optional sniff-version scoping.
- **Partly:** the writer's DM §6 note; Iceberg W5's single registry digest; the inventory's "no restated rules".
- **Deferred:** the links attribute map.
