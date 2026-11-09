# Organization entities for witness appearances

Owner decision, 2026-11-08: match organizations first; people come later.
Linking about 5,900 Member rows that lack a `bioguide_id` is the first people step, not part of this plan.
Evidence: `.cache/archive-release/investigations/entity-matching-measure-20261108/` (scripts `em-*.py`, outputs `fed_agency.json`, `org_score.json`, `org_variants.json`, `org_labels.json`, `org_hand_check.txt`). Release 630164505301.

## What the measurement says

- 133,627 non-member appearances, about 60.2k distinct organization strings. Cheap rules collapse them to 42.9k (a 29% lower bound on variants).
- The Federal Register roster (473 agencies) as-is matches 57 of 81 sampled federal strings (70%). Over house_xml rows typed `Government - Federal` it matches 446 of 1,024 strings and 2,193 of 3,662 appearances (60%). Misses are military branches, VHA/VBA, CRS and similar: an alias list of 30–50 entries.
- Wikidata reconciliation: 187 of 300 sampled strings have a name-agreeing candidate. Hand check: 35 of 40 auto hits correct. All 5 wrong hits had a tie at the top score; none of the 24 correct hits with a unique top candidate scoring 90 or more was wrong (24/24; `em-wd-accept.py` → `wd_accept.txt`, same inputs).
- ProPublica EIN helps only nonprofits, with a state check; GLEIF is not worth it; LDA was not measured (SpicyRegs already publishes `lobbying_clients`).
- Segment parsing fails on about 10%: sub-unit first, law-firm commas, role prefixes.

## Design rules

- **Drop nothing.** Witness rows and their `organization`/`on_behalf_of` text never change. Organizations are a separate layer.
- **Match strings, not rows.** Every rule works on distinct normalized strings (about 60k), never pairwise. Within-corpus fuzzy matching (O(S²), 3.6 billion pairs) is out. Strings join only through a shared anchor: a Federal Register agency, a Wikidata item, or a reviewed decision.
- **Engine first.** Derivation is model SQL; grouping is the engine's `components` step (union-find, O(E α(N))). Outside responses enter only as capture receipts.
- **One decision mechanism.** Aliases, review verdicts and corrections are all rows in one append-only log.

## Tables

| Table | Key | Contents |
| --- | --- | --- |
| `org_strings` (model) | `string_key` = first 16 hex of sha256(`org-string-v1`, normalized text) | normalized text, segments, appearance count. Normalization is lowercase, punctuation, `&`→`and`, leading articles and `u.s.`. |
| `organizations` (release) | `org_id`, 16 hex | display name (agency name, else Wikidata label, else most frequent string), kind, `parent_org_id`, appearance count |
| `organization_ids` (release) | (`org_id`, `scheme`, `value`) | schemes `fr_agency`, `wikidata`, later `ein`, `lei`, `ror`; source and evidence (receipt sha or decision id) |
| `witness_organizations` (release) | (`witness_key`, `field`, `org_id`) | `field` is `organization` or `on_behalf_of`; `method` (`fr_agency`, `wikidata_auto`, `decision`); score; evidence |
| `organization_redirects` (release) | `old_org_id` | `org_id`, `kind` (`merged`, `split_from`), first release. Append-only, carried forward forever. |
| `org_decisions` (raw provenance) | `id` | see below |

`witness_organizations` is rebuilt each release from string links, so it follows `witness_key` churn without its own map.

## Stable IDs

An `org_id` is minted once as the first 16 hex of sha256(`org-v1`, anchor), where the anchor is `fr_agency:<id>`, else `wikidata:<Q>`, else `decision:<id>`. After that it is read, not recomputed, following the `witness_key_map` pattern: `org-priors.sql` reads the previous release's `organizations`, `organization_ids` and `organization_redirects`.

- A component holding one prior ID keeps it.
- A component holding several (merge) keeps the one whose anchor ranks first (agency, Wikidata, decision; then earliest release, then smallest ID). The others get `merged` redirects.
- A prior ID whose members fall into two components (split) stays with the component holding its anchor. The other component mints a new ID with a `split_from` redirect.
- IDs are never reused or deleted. The gate: every prior `org_id` resolves to a live org or a redirect chain ending at one.

## Pipeline

| Step | Where | Reads |
| --- | --- | --- |
| 1. Strings | model SQL `org-strings.sql` | `appearance_records_resolved` (one GROUP BY over about 134k rows) |
| 2. Agency match | model SQL `org-agency-matches.sql` | segments; `spicy_agencies`; current alias decisions. Hash equality join on whole segments, O(segments). A whole-segment rule keeps `ohio environmental protection agency` off federal EPA. |
| 3. Reconcile requests | model SQL `org-reconcile-requests.sql` | strings with no agency link and no retained receipt; core segment; 10 queries per URL in canonical JSON |
| 4. Capture | `capture_schedule` campaign with step 3 as seed file; new family `wikidata/reconcile` in `capture-scope.json`, `receipt-line-kinds.json`, `recheck-intervals.json` (no automatic recheck) | GET `wikidata-reconciliation.wmcloud.org/en/api?queries=…` with the fixed anonymous User-Agent |
| 5. Reading | model SQL `wikidata-reconcile-bodies.sql` (pattern: `youtube-api-bodies.sql`), versioned in `reading_versions` | `captures` filtered to the family, candidate-SHA join first |
| 6. Acceptance | model SQL `org-wikidata-links.sql` | readings; current decisions |
| 7. Decisions | model SQL `org-decisions-current.sql` (pattern: `provenance-current-reviews.sql` and `reviews-review-selected.sql`) | `org_decisions` raw |
| 8. Group | engine `components` step | edges: accepted string→anchor links plus `same` decisions |
| 9. IDs and publish | model SQL `org-priors.sql`, `organizations.sql` | components; prior release |
| 10. Review queue | model export `org_review_queue` | review-band links, conflicts; ordered by appearance count |

Each release is linear in strings plus new receipts; only cores without a receipt are requested (first run about 4.3k calls: 43k cores, 10 per call).

## Federal agency table

SpicyRegs vendors RefSpec's agency registry (REF-038 projection, REF-072 bridges and current successors, pinned by sha256 in `spicy_regs/ontology/agencies.py`). It does not yet publish the full 473-agency roster with names, short names and parents as a table. Phase 2 asks SpicyRegs to publish an `agencies` generation. Congressional-tech then pins it in `model/jobs/spicy-regs/spicy-regs.json` as `spicy_agencies`, as it does `spicy_members` today. REF-072 successor bridges supply renames such as General Accounting Office → Government Accountability Office.

Aliases (`u.s. army`, `veterans health administration`, `congressional research service`, …) are `same` decisions from a normalized string to `fr_agency:<id>`, seeded from `fed_agency.json` `top_unmatched`. Legislative-branch bodies missing from the roster (CRS, JCT, CBO if absent) get decision-anchored orgs.

## Wikidata acceptance

A candidate is **auto-accepted** when it is the only candidate at the top score and that score is at least 90. Measured: 24/24 correct, catching 24 of the 35 correct hits. **Review band:** any other candidate scoring 80 or more, including ties. These are queued, never published as links. Below 80, nothing is queued. A `different` decision on (string, Q) blocks that link in later releases.

24/24 has a 95% upper error bound of about 12%, so auto-accepted links publish only after the Phase 3 gate.

## Decision log

`org_decisions` is a new kind in the existing append-only provenance (`congress_api.retention.provenance`, beside `reviews`). It uses the same import stage, `supersedes` and `withdraw`. Fields: `id`, `subject` (`string_key`, or `witness_key` for one appearance), `verdict` (`same`, `different`, `unsure`, `withdraw`), `object` (`org_id` or `scheme:value`), `note` (why), `reviewer` (who), `decided_at` (when), `supersedes`. Replay: drop withdrawn and superseded rows, then take the latest per (subject, object) by instant and then id. `same` adds an edge. `different` removes the matching link or edge. `unsure` keeps the item out of the queue until new evidence arrives. When a component still joins two parties ruled `different`, it is published unmerged and listed in `org_review_queue` as a conflict. (Union-find cannot enforce cannot-link; we do not hand-roll it.) `witness_key` subjects resolve through `witness_key_map`.

## Exposure

- **Release:** the four release tables in `release-schema.json`, with identity `organizations.org_id` and relationships witnesses → `witness_organizations` → `organizations` → `organization_ids`. Add a recipe "appearances by organization".
- **MCP:** `search_entities` and `get_entity` work on any table with a published identity, so organizations need no reader code. Update the server instruction "Witnesses identify appearances, not deduplicated people": organizations are linked; people are not.
- **Site:** witness rows link their organization; an organization page lists appearances and IDs and follows redirects.

## Phases and gates (epic ct-lwxs)

1. **Foundation (M).** (ct-6him) `org_strings`, `org_decisions` kind and replay, components step, ID priors and redirects, empty release tables. Gate: two clean rebuilds from raw are byte-identical. A planted merge and a planted split produce the stated redirects.
2. **Federal agencies (M).** (ct-w34j) `spicy_agencies` pin, agency match, alias decisions. Gate: at least 90% of house_xml `Government - Federal` appearances link (baseline 60%). A raw check (`scripts/measure/org_agency_raw_check.py`, AGENTS raw-check rules) on 100 linked rows finds at most 1 wrong, and it flags a planted state-EPA → federal-EPA link.
3. **Wikidata (L).** (ct-39u8) Capture family, reading, acceptance, review queue. Gate before auto links publish: a fresh hand label of 150 auto-accepted links, stratified by appearance band, finds at most 3 wrong. Report reach by appearances and by strings, and the queue size.
4. **Exposure (M).** (ct-lvdf) Release schema, MCP note, site pages. Gate: the MCP and site contract tests resolve an org, its appearances and a redirect. Every prior `org_id` resolves across two consecutive releases.

Deferred, each only on measured reach beyond Wikidata: `extend` for EIN/LEI/ROR/parent, ProPublica, LDA via SpicyRegs.

## What this design cannot see

- Precision rests on 40 auto hits from one labeler. The 24/24 rule was chosen after seeing those labels, so the Phase 3 gate must use new rows.
- A unique wrong candidate when the right organization is not in Wikidata.
- A segment that parses wrongly and still matches, such as `Human Resources, NC State` → `Human Resources`.
- Federal coverage is measured only on house_xml rows; other sources have no `witness_type`.
- Bare `Environmental Protection Agency` from a state official links to federal EPA. Whole-segment equality cannot tell.
- Reconciliation answers drift as Wikidata changes. Receipts pin what we saw, but a re-capture can flip a link. There is no automatic recheck.
- An organization line says who a witness spoke for, not that the organization endorsed the testimony.
- Most strings stay unlinked until reviewed (the auto rule took 24 of 60 hand-checked), so counts by organization undercount.
