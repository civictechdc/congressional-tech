# Organization entities for witness appearances

Owner decisions, 2026-11-08: organizations first (linking about 5,900 Member rows without `bioguide_id` starts the later people work); agency names and aliases from RefSpec; every org string gets an org ID after fuzzy matching; Wikidata auto-accepts only a single clear winner scoring 90+.
Evidence: `.cache/archive-release/investigations/entity-matching-measure-20261108/` (`em-*.py` and their outputs, including `wd_accept.txt` and `fuzzy_L2.json`). Release 630164505301.

## What the measurement says

- 133,627 non-member appearances, 60,165 distinct organization strings. Normalization alone gives 51,228 after dropping locations (L2) and 42,869 core segments (L3). GAO: 599 raw strings, 353 at L2, 42 at L3; acronyms and sub-units are the rest.
- The Federal Register roster (473 agencies) as-is matches 57 of 81 sampled federal strings (70%). Over house_xml rows typed `Government - Federal` it matches 446 of 1,024 strings and 2,193 of 3,662 appearances (60%).
- Wikidata: 35 of 40 auto hits correct; all 5 wrong ones tied at the top. A unique top candidate scoring 90+ was right 24/24, catching 24 of 35.
- Fuzzy (`em-fuzzy.py`):
  - **Token-bag key:** sorted non-stopword tokens, so word order, punctuation and `of`/`for`/`at` do not matter. It merges L2 strings from 51,228 to 49,912; 1,147 keys hold more than one string. None of those groups mixes two of the 15 agency patterns. A seeded 60-group sample read as one organization each.
  - **Edit-distance pairs:** token Jaccard of 0.75 or more with a Levenshtein ratio of 0.85 or more gives 903 pairs at L2; the L3 sample shows wrong ones in that range (Virginia vs West Virginia Council of Churches: 0.75, 0.85). So edit distance only queues pairs for review.
- Segment parsing fails on about 10% (sub-unit first, law-firm commas, role prefixes).

## Design rules

- **Drop nothing.** Witness rows and their `organization`/`on_behalf_of` text never change.
- **Engine first.** Model SQL; grouping by the engine's `components` step (union-find, O(E α(N))); similarity from DataFusion built-ins only: `levenshtein`, `string_to_array`, `array_intersect`, `array_union`, `cardinality`. No Jaro or trigram function exists; we add none.
- **Never all pairs** (1.3 billion at 51k strings). Auto merges are a GROUP BY key; edit distance runs only inside blocks.
- **Registry knowledge lives upstream** in RefSpec, which SpicyRegs also reads. Our decision log holds only our own judgments.

## Tables

| Table | Key | Contents |
| --- | --- | --- |
| `org_strings` (model) | `string_key` = first 16 hex of sha256(`org-string-v1`, L2 text) | L2 text, segments, `bag_key`, appearance count |
| `organizations` (release) | `org_id`, 16 hex | display name (RefSpec, else Wikidata, else most frequent string), kind, `parent_org_id`, appearance count |
| `organization_ids` (release) | (`org_id`, `scheme`, `value`) | `fr_agency`, `wikidata`, later `ein`/`lei`/`ror`; evidence (RefSpec release, receipt sha or decision id) |
| `witness_organizations` (release) | (`witness_key`, `field`, `org_id`) | `field` is `organization` or `on_behalf_of`; `method`, `score`, evidence |
| `organization_redirects` (release) | (`old_org_id`, `release`) | `org_id` and event (`merged`, `split_from`, `restored`). Append-only; an ID's latest event wins. |
| `org_decisions` (raw provenance) | `id` | see Decision log |

`method` and score: `registry` (whole segment equals a RefSpec name, abbreviation or alias; 1), `token_bag` (same bag key; 1), `wikidata_auto` (reconciliation score), `decision` (reviewed; evidence keeps the pair's Jaccard and Levenshtein).

Edit-distance pairs become links only through a decision. Every appearance with organization text gets a `witness_organizations` row.

## Pipeline

| Step | Where | Reads |
| --- | --- | --- |
| 1. Strings and bag keys | model SQL `org-strings.sql` | `appearance_records_resolved` (one GROUP BY, about 134k rows) |
| 2. Registry match | model SQL `org-registry-matches.sql` | segments; pinned RefSpec agency tables; hash equality join on whole segments, O(segments). Whole segments keep `ohio environmental protection agency` off federal EPA. |
| 3. Fuzzy review pairs | model SQL `org-fuzzy-pairs.sql` | bag groups blocked by their rarest token (by document frequency). Measured: 223,504 candidate pairs, largest block 56, so at most S×56 comparisons. Queue pairs with Jaccard ≥ 0.75 and Levenshtein ratio ≥ 0.85 unless a differing token is a place or scope word (state, county, national, north…): about 900. |
| 4. Reconcile requests | model SQL `org-reconcile-requests.sql` | bag groups with no registry link and no receipt; core segment; 10 queries per URL in canonical JSON |
| 5. Capture | `capture_schedule` campaign seeded from step 4; family `wikidata/reconcile` in `capture-scope.json`, `receipt-line-kinds.json`, `recheck-intervals.json` (no automatic recheck) | GET `wikidata-reconciliation.wmcloud.org/en/api?queries=…`, fixed anonymous User-Agent |
| 6. Reading and acceptance | model SQL `wikidata-reconcile-bodies.sql` (pattern: `youtube-api-bodies.sql`, versioned in `reading_versions`), `org-wikidata-links.sql` | `captures` for the family, candidate-SHA join first |
| 7. Decisions | model SQL `org-decisions-current.sql` (pattern: `provenance-current-reviews.sql`) | `org_decisions` |
| 8. Group | engine `components` | edges: string→bag key, bag→registry/Wikidata anchor, `same` decisions |
| 9. IDs and publish | model SQL `org-priors.sql`, `organizations.sql` | components; prior release |
| 10. Review queue | export `org_review_queue` | step 3 pairs, Wikidata review band, conflicts; ordered by appearance count |

Each release is linear in strings plus new receipts; the first capture is about 5k calls.

## RefSpec agency tables

Congressional-tech pins a RefSpec release directly, as SpicyRegs does, not through SpicyRegs. That release, being prepared on RefSpec branch `claude/agency-aliases`, covers the Federal Register roster (names, short names, parents), REF-072 successor bridges (General Accounting Office → Government Accountability Office) and a free-text alias set (`u.s. army`, `veterans health administration`, …).

The pin is a new file, `model/jobs/refspec/refspec.json`, shaped like `model/jobs/spicy-regs/spicy-regs.json`: release key, source, and per-table path, `sha256`, size and rows. Mismatched bytes are refused. Phase 2 is blocked until the release exists.

## Stable IDs and churn

An `org_id` is the first 16 hex of sha256(`org-v1`, anchor); anchors rank `fr_agency:<id>`, `wikidata:<Q>`, `decision:<id>`, `bag:<bag_key>`. A bag key is a pure function of the string, so automatic fuzzy groups never regroup between releases.

Churn has three causes, each a redirect event:
- A bag gains an anchor: `merged` into the anchored org.
- A link or decision is withdrawn: the bag's ID returns (`restored`).
- A normalization bump moves bag keys; mapping old to new through the raw strings gives kept, `merged` or `split_from`.

`org-priors.sql` reads the previous release (the `witness_key_map` pattern). A merge keeps the highest-ranked anchor; a split leaves the ID with the part holding its anchor. IDs are never reused, and redirects are rewritten each release to point straight at the current org.

The risk: about 50k bag IDs, and each later anchoring retires one; Wikidata alone could retire tens of thousands. Containment: IDs publish only after Phases 2–3, so the first public set already carries its anchors; redirects resolve forever in one hop, and MCP and site follow them; each release reports retired IDs by cause.

## Wikidata acceptance

- **Auto-accept:** the only candidate at the top score, with that score at least 90.
- **Review band:** any other candidate scoring 80 or more, queued and never published as a link.
- A `different` decision on (bag, Q) blocks that link.

24/24 still allows about 12% error, so auto links wait for the Phase 3 gate.

## Decision log

`org_decisions` is a new kind in `congress_api.retention.provenance`, beside `reviews`, with the same import stage, `supersedes` and `withdraw`. Fields: `id`, `subject` (`bag_key`, or `witness_key` for one appearance), `verdict` (`same`, `different`, `unsure`, `withdraw`), `object` (`org_id`, `bag:` or `wikidata:`), `note` (why), `reviewer` (who), `decided_at` (when), `supersedes`.

Scope: fuzzy-pair outcomes, non-agency merges and splits, Wikidata review outcomes. Agency aliases go to RefSpec.

Replay drops withdrawn and superseded rows, then takes the latest per (subject, object) by instant, then id. `same` adds an edge; `different` removes a link and blocks the pair; `unsure` holds the pair out of the queue until its evidence changes.

A component still joining two parties ruled `different` publishes unmerged and is queued as a conflict (union-find has no cannot-link; we do not hand-roll one). `witness_key` subjects resolve through `witness_key_map`.

## Exposure

- **Release:** the four tables in `release-schema.json`, identity `organizations.org_id`, relationships witnesses → `witness_organizations` → `organizations` → `organization_ids`, and an "appearances by organization" recipe.
- **MCP:** `search_entities` and `get_entity` serve any published identity, so no reader code is needed; revise the instruction "Witnesses identify appearances, not deduplicated people": organizations are linked; people are not.
- **Site:** witness rows link their organization; an organization page lists appearances and IDs and follows redirects.

## Phases and gates (epic ct-lwxs)

1. **Foundation and fuzzy (M), ct-6him.** `org_strings`, bag keys, fuzzy review pairs, `org_decisions`, components, ID priors and redirects.
   - Two clean rebuilds from raw are byte-identical.
   - Planted merge, split and restore produce the stated events.
   - A fresh hand label of 150 multi-string bag groups, stratified by appearances, finds at most 3 wrong merges.
   - `scripts/measure/org_fuzzy_raw_check.py` judges merges by witness facts the rule ignores (location, position, committee) and character trigrams, and flags a planted Virginia + West Virginia Council of Churches merge.
2. **RefSpec agencies (M), ct-w34j.** Blocked on the RefSpec release.
   - At least 90% of house_xml `Government - Federal` appearances link (60% today).
   - `org_agency_raw_check.py` finds at most 1 wrong in 100 linked rows and flags a planted state-EPA → federal-EPA link.
3. **Wikidata (L), ct-39u8.** Capture, reading, acceptance, review queue.
   - A fresh hand label of 150 auto-accepted links finds at most 3 wrong.
   - Report reach, queue size and retired IDs.
4. **Exposure (M), ct-lvdf.** Release schema, MCP note, site. Ships only after Phase 3.
   - Contract tests resolve an org, its appearances and a redirect.
   - Every prior ID resolves in one hop across two releases.

Deferred, each only on measured reach beyond Wikidata: `extend` for EIN/LEI/ROR/parent, ProPublica, LDA via SpicyRegs.

## What this design cannot see

- Identical text naming different organizations, such as generic sub-units (`planning division`). A bag merges text; it cannot split it.
- Variants sharing no rarest token never reach review; `gao` vs `government accountability office` relies on RefSpec aliases.
- Precision rests on small planner-labeled samples (40 Wikidata hits, 60 bag groups); the gates use new rows.
- A unique wrong Wikidata candidate when the right organization is absent.
- Bare `Environmental Protection Agency` from a state official links to federal EPA.
- Federal coverage is measured only on house_xml rows.
- Reconciliation drift: receipts pin what we saw, but a re-capture can flip a link.
