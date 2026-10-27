# Architecture Review: the Explorer MCP server at the archive and spicy-regs seam

Semi-formal architecture review, 2026-10-26. It covers the proposed Unified Congressional Explorer MCP server and its eight data-coverage tasks, read against what the server needs, the archive's engine-first plan and spicy-regs. Both MCP documents are untracked in the primary checkout.

## 0. Coverage And Observation Log

### Artifacts read

| Artifact | O-IDs | Key observations |
| --- | --- | --- |
| `congressional-tech/docs/youtube-coverage/committee-explorer-mcp-design.md` (untracked) | O1–O10 | O1: the goal is one read-only interface across people, institutions, legislation, proceedings, documents and "work around Congress" (§intro, §Product scope). O2: each dataset declares its sources, Congresses, dates, freshness and limits, and installed data is told apart from data still to collect (§Required design changes 1; §Meaning of bounded…). O3: a fixed, verified local selection; a `snapshot_id` hashed from the input identities; cursors bound to it; serving works offline (§Process and data flow). O4: records connect by source IDs and Congress; unresolved identities are kept; a witness is not a person; flattened lists are never cross-joined (§Required design changes 3; §Query behavior). O5: a missing capability is reported explicitly and never as an empty result; "missing columns never become false facts" (§Process; §Delivery and acceptance). O6: it reads two publications, the committee explorer's `CURRENT.json` (six tables) and the filename viewer manifest at `viewer-publications/manifest.json` (viewer format 5, a 1,087,995,353-byte catalog pair) (§Existing data). O7: the filename half peaks at about 1.72 GB, and warm search takes about 5.7 s (§Implemented). O8: a reviewed category never silently replaces the baseline (§Query behavior). O9: lobbying and campaign finance are listed as expansion areas, not installed (§Product scope, last row). O10: witness-document ownership cannot be rebuilt from a shared meeting, and today's materials lack `appearance_ids` (§Existing data). |
| `…/congressional-explorer-mcp-data-coverage-tasks.md` (untracked) | O11 | O11: all eight tasks change "the Explorer export" or its preparation (items 1–8). |
| `congressional-tech/apps/explorer_mcp/` (untracked) | O12–O13 | O12: it imports `congress_api.retention.catalog_publication.read_catalog` (`filenames.py:86`) and `viewer_publication.filename_viewer` (`filenames.py:268`, `filename_sql.py:101,266`), and reads `CURRENT.json` (`selection.py:18`). O13: 3,263 lines; it depends on `viewer-publication` and `congress-youtube` (`pyproject.toml`). |
| Archive plan, worktree `ct-ticket-audit` at `47c35f57` | O14–O19, O26–O28 | O14: BINDINGS §6 deletes `catalog_publication` (the "Python rebuild path" row) and the v6 reader branch at the switch. O15: the release takes over the pointer `viewer-publications/manifest.json` (DM §8.1 pointer row). O16: the manifest holds `schema_version`, `files[]`, `facet_counts` and `release_id`; a release "MAY omit the entity files or carry `meetings` with keys only; the manifest lists what it has" (DM §8.1). That covers files, not relation state. O17: phase-1 releases leave `witness_keys` and transcript links empty and carry meetings as keys only (PLAN §4). O18: `witness_keys` come only from document links the source states; there is no name matching (DM §7.11). O19: the committee explorer is outside the target and reads the lake in phase 2 (BINDINGS §7; PLAN F3); no document names an MCP consumer (a search for "MCP" in the four docs finds nothing). O26: the release ID hashes every file's digest, and `inputs/<digest>.json` records the pinned snapshots, the provenance set and the spicy-regs generation digests (DM §8.1, §8.3). O27: a `kind_override` review replaces `document_kind`; `detail` has `document_date_source` but no source for the kind (DM §7.9, §8.1). O28: captions get the record role `caption` (DM §7.3); meetings carry `video_key` (DM §6.5); no release file lists caption bodies (DM §8.1); PLAN §7 parks captions together with transcript assembly. |
| spicy-regs MCP, `list_sources` (live, 2026-10-26) | O20–O22 | O20: the congress tables include `amendments` (7,119, window), `bill_cosponsors` (2,105,469), `congress_bills` (422,011), `roll_call_votes`, `member_votes` (10.56M), `members`, `member_terms`, `member_party_affiliations`, `committees`, `committee_assignments`, `committee_meetings` (6,098, sampled), `hearing_transcripts`, `nominations` and `treaties`. There are relationship views such as `meeting_witnesses`, `meeting_witness_documents`, `meeting_documents`, `meeting_bills` and `vote_amendments`, each with `_occurrences`, `_pairs` and `_field_states`. O21: there are lobbying, campaign-finance, GAO and CRS subjects. O22: no table holds Congress or session dates or chamber party control. |
| `spicy-regs/README.md` | O25 | O25: the hosted read-only server is at `mcp.spicy-regs.dev/mcp` (README:77). A stdio install exists (README:450). A local mode, `SPICY_REGS_DATA_DIR`, reads only the tables in a named directory, offline, and refuses an invalid directory; immutable DocSpec export bindings are supported; the SQL write guard applies (README:407–415). |
| `spicy-stack/.tickets/ss-vhi2.md` | O23 | O23: item 4 has spicy-regs read the archive's release files (meetings, witnesses, sources), pinned by `release_id`, and retire its own meeting capture. |
| `congressional-tech` primary checkout, `git status` and `.venv` | O24 | O24: `pyproject.toml` and `uv.lock` have uncommitted changes adding `apps/explorer_mcp` to the workspace (+613/−9, which re-lock `certifi` and `idna`). `fastmcp` is installed in the live `.venv`. |

### Artifacts not read

- **The spicy-regs MCP source code.** Its tool descriptions, README and live `list_sources` establish its capabilities. Whether its local mode can serve the archive's release files as-is is FINDING 2's first step, not an assumption.
- **The committee explorer's export code and `coverage.json` states.** The reshape changes where that data comes from, not how the export is built today.
- **The explorer MCP's tests and qualification notes.** Its working state is not in question.

### Hypotheses

- H1: CONFIRMED. The server's needs are mostly met by the archive release plus spicy-regs, and the task list targets the wrong layer (O11 against O16–O18, O20).
- H2: CONFIRMED. The server binds to code and a publication format that the plan deletes or replaces (O12, O14, O15).
- H3: CONFIRMED, at the depth of docs and live tools. spicy-regs' MCP already has the general discovery, coverage, relationship-occurrence and local, offline, guarded SQL the design asks for (O20, O21, O25).
- H4: CONFIRMED. The release's manifest cannot tell a SQL consumer which relations are populated (O5, O16, O17).

## 1. Artifact Summary

- **Path:** the two untracked documents above, plus `apps/explorer_mcp`.
- **Stated problem:** assistants cannot explore congressional data across people, institutions, legislation, proceedings and documents through one interface.
- **Stated decision:** a local FastMCP server with DuckDB over the committee explorer's export and the filename catalog, extended by eight export changes.
- **Category:** product surface.
- **Subsystems touched:** the committee explorer's export, the viewer publication, the archive's release, spicy-regs.
- **Prior artifacts the design should have cited but did not:** the archive's release contract (DM §8), spicy-regs' MCP (README), ss-vhi2.
- **Implementation status:** the committee and filename slices are partly built locally; the eight tasks are not started.

PREMISES:
- P1: one interface across all of these areas (O1).
- P2: every dataset declares its sources, Congresses, dates, freshness and limits (O2).
- P3: a fixed, verified selection with cursors bound to it, served offline (O3).
- P4: records connect only by stated identifiers, and unresolved identities are kept (O4).
- P5: an absent capability is never reported as an empty fact (O5).
- P6: bounded memory and latency (O7, and the design's bounded-execution table).

## 2. Lineage And Relationship

### Lineage

| Prior artifact | Type | Relation | Citation |
| --- | --- | --- | --- |
| Archive release contract | parent of the document data | replaces both publications the server reads | DM §8.1; BINDINGS §6 |
| ss-vhi2 | sibling plan | spicy-regs reads the archive release | spicy-stack `.tickets/ss-vhi2.md` |
| spicy-regs MCP | sibling | already serves the entity, discovery and SQL scope | spicy-regs README:77, 407–415, 450 |
| Owner doctrine | constraint | reuse a solution already built in a sibling repo of the same platform | `~/.claude/CLAUDE.md`, working doctrine |

### Relationships

| Component or seam | Owner | Depends on | Depended on by | Seam named? |
| --- | --- | --- | --- | --- |
| Release files and manifest | archive publisher | lake, spicy-regs generations | site, canary, capture, spicy-regs (ss-vhi2), explorer MCP | Partly: DM §8 names the site and capture, not spicy-regs or the MCP |
| Viewer format 5 and `catalog_publication` | old pipeline | old catalog | explorer MCP | No; deleted at the switch (O14) |
| Committee explorer `CURRENT.json` | committee explorer | old meeting tables, then the lake | explorer MCP | No |
| spicy-regs MCP | spicy-regs | spicy-regs generations, local export bindings | assistants | Yes (README) |

### Stated intent against actual shape

- **Intent:** one interface across congressional data (P1).
- **Shape:** a second MCP stack over two publications that the plan replaces (O6, O12, O14, O15). Its own expansion areas, lobbying and campaign finance (O9), already exist in the sibling MCP (O21).
- **Divergence:** MAJOR. P1 is not served by adding a second interface (O20, O21, O25).

## 3. Invariants And Commitments

INVARIANT 1:
- **Statement:** each fact has one authority. The archive owns documents, saved copies, meetings and witnesses; spicy-regs owns bills, members, votes and committees.
- **Source:** ARCH §8.5 ("the split runs both ways"); DM §6.4.
- **Status:** tasks 2 and 6 would BREAK it.
- **Evidence:** O11, O20.
- **Failure mode:** sponsors, amendments and Congress data are re-exported in the committee export as a second, drifting copy. Exercised by the explorer MCP's SQL (O12).

INVARIANT 2:
- **Statement:** release content is deterministic, with no run-time values.
- **Source:** ARCH §10.2.
- **Status:** RELIED-UPON by FINDING 4.
- **Evidence:** O26.
- **Failure mode:** a coverage block stamped with the publish time would change the release ID on every run.

INVARIANT 3:
- **Statement:** a consumer can tell an absent relation from an empty one.
- **Source:** the MCP design (O5); the archive's own reader rule ("offers a connection only when its file is present", DM §8.1).
- **Status:** NEWLY-INTRODUCED for SQL consumers, and BROKEN by phase 1 at the column level.
- **Evidence:** O16, O17.
- **Failure mode:** phase-1 releases carry empty `witness_keys`, which a SQL reader takes to mean "no witness submitted this". Exercised by spicy-regs' read of the release (O23) and by the MCP's `query_sql` (O12).

INVARIANT 4:
- **Statement:** reuse the solution a sibling repo has already built.
- **Source:** owner doctrine (`~/.claude/CLAUDE.md`).
- **Status:** BROKEN.
- **Evidence:** O20, O21, O25 against O13.
- **Failure mode:** two MCP servers with two coverage vocabularies and two selection models. Exercised by every assistant that installs both.

INVARIANT 5:
- **Statement:** the primary checkout is never modified; it backs live jobs.
- **Source:** PLAN §3 ("Work in a separate worktree and venv").
- **Status:** BROKEN.
- **Evidence:** O24.
- **Failure mode:** live recovery jobs import from a re-locked `.venv`.

## 4. User-Value Analysis

- **Outcome:** an assistant answers questions across the archive's documents and the congressional entities through one tool, with file links it can read itself.
- **Beneficiary:** researchers using an assistant.
- **Debt added by the current shape:** a second MCP stack; bindings to code deleted at the switch; eight export changes made in a layer the plan replaces.
- **Debt paid down by the reshape:** one interface, one coverage vocabulary, one selection identity (release ID plus pinned generations); the catalog pair's memory cost goes (O7 against `list` at 6–7 MB, DM §8.1).
- **Falsifiability:** six months on, an assistant still cannot answer the design's six example questions (§What the current server answers) from one server.
- **Smaller shape:** spicy-regs' local mode reads the archive release as another pinned source (O25, O23). Still open: whether it can bind the release's files without code changes.
- **Greenfield-first check:** rebuilt today, there would be one MCP, reading both publishers. NO, the current contract would not look the same.

## 5. Counterfactual Analysis

- **Kill criterion:** spicy-regs' MCP cannot serve a pinned, offline archive release, or the owner wants congressional data kept out of spicy-regs.
- **Counter-decision:** the explorer MCP becomes the one interface and reads the archive release plus spicy-regs' files. It would have to rebuild spicy-regs' coverage, relationship-occurrence and SQL-guard machinery (O20, O25).
- **Removal probe:** deleting `apps/explorer_mcp` breaks no published consumer, since it is untracked and local (O24).
- **Sibling subsumption:** substantial for the entities, discovery, SQL and local mode (O20, O21, O25). Not yet for the archive's documents, which ss-vhi2 item 4 already plans to read (O23).
- **Six-month critic:** "Why are there two congressional MCP servers whose coverage claims disagree?"

OPPOSITE-VERDICT PROBE:
- **If the opposite verdict were correct,** that a separate explorer MCP is the right shape, evidence would exist that spicy-regs' MCP lacks local or offline serving, SQL, coverage declarations or relationship occurrences, or a decision would exist to keep the two apart.
- **Searched for:** spicy-regs `list_sources` and its tool descriptions; spicy-regs README for MCP, local, stdio and offline; spicy-stack `DECISIONS.md` and congressional-tech docs for "MCP".
- **Found:** spicy-regs has all four (O20, O25), and no decision separates them (a search of `DECISIONS.md` for "mcp" found nothing). ss-vhi2 already moves the archive's meetings into spicy-regs (O23).
- **Conclusion:** REFUTED.

## 6. Findings

FINDING 1:
- **Severity:** BLOCKER
- **Category:** named-seam
- **Location:** `apps/explorer_mcp/filenames.py:86`; BINDINGS §6; DM §8.1
- **Description:** The filename half reads `catalog_publication` and viewer format 5 behind the pointer that the switch replaces. No document names this consumer, so the switch breaks it silently.
- **Evidence chain:** O12, O14, O15, O19.
- **Exercised by:** plan F5's deletions and the first flip.
- **Recommendation:** RESHAPE. DM §8 names every release consumer (the site, the canary, capture, spicy-regs and any MCP), and each reads by `schema_version`. The document half reads `list`, `detail`, `links`, `urls`, `sources` and `recoveries`, and nothing reads the catalog pair after F5.

FINDING 2:
- **Severity:** CONCERN
- **Category:** sibling-conflict
- **Location:** the MCP design, §intro and §Required design changes 1–2 and 5
- **Description:** The product scope is already spicy-regs' MCP, which has discovery with coverage kinds, pins, relationship occurrences, guarded SQL, and hosted and local offline modes. The archive's documents are the one missing source.
- **Evidence chain:** P1; O1, O2, O9, O20, O21, O25; INVARIANT 4.
- **Exercised by:** any assistant using both servers.
- **Recommendation:** RESHAPE.
  - Make one interface: spicy-regs' MCP adds the archive release as a pinned source, which extends ss-vhi2 item 4 from meetings, witnesses and sources to `list`, `detail`, `links`, `urls` and `recoveries`.
  - Keep the explorer MCP as a named, temporary shim over today's publications: frozen at its two slices, with none of the eight tasks done in the old export.
  - Retire it when spicy-regs' MCP answers the design's six example questions from an archive release.

FINDING 3:
- **Severity:** CONCERN
- **Category:** intent-vs-shape
- **Location:** tasks 1, 3, 7 and 8
- **Description:** Tasks 1, 3 and 7 are already designed into the release: panels, order and source-given member IDs (DM §6.7); `witness_keys` from stated links only (DM §7.11); recoveries and reviews (DM §7.8–§7.9). Doing them in the export builds each twice.
- **Evidence chain:** P4; O10, O11, O17, O18.
- **Exercised by:** the committee explorer export (O6).
- **Recommendation:** REVERSE in the export; take them from the release. Task 8's ledger becomes FINDING 4's manifest block, not a hand-kept list.

FINDING 4:
- **Severity:** CONCERN
- **Category:** unstated-assumption (in our spec)
- **Location:** DM §8.1, manifest row
- **Description:** The manifest declares files, not which relations are populated. A phase-1 release's empty `witness_keys` and keys-only meetings therefore read as facts.
- **Evidence chain:** P2, P5; O5, O16, O17; INVARIANT 3, INVARIANT 2.
- **Exercised by:** spicy-regs' read of the release (O23), and any SQL consumer.
- **Recommendation:** RESHAPE. The manifest gains `coverage`, computed from the release's own rows so it stays deterministic:
  - per file, and per derived list column (`witness_keys`, `meeting_keys`, `measure_keys`, `transcripts`), its state: `present`, `keys_only` or `absent`;
  - per entity file, its source families, Congress range and latest capture date.

FINDING 5:
- **Severity:** CONCERN
- **Category:** ownership
- **Location:** tasks 2 and 6
- **Description:** These tasks belong to spicy-regs, not the archive.
  - Sponsors with names and IDs, amendments and cosponsors already exist there (O20).
  - Congress and session dates and chamber control exist nowhere (O22).
  - Committee YouTube accounts and archive routes are capture inputs, not user datasets: recordings reach users through `meetings.videos`, and scope through `capture_scope.json`.
- **Evidence chain:** O11, O20, O22, O28; INVARIANT 1.
- **Exercised by:** the committee export, if done there.
- **Recommendation:** RESHAPE.
  - Sponsors and amendments: served by spicy-regs as it is.
  - File a spicy-regs ticket for Congress and session dates and chamber control.
  - No archive dataset for YouTube accounts or routes.

FINDING 6:
- **Severity:** CONCERN
- **Category:** user-value (in our plan)
- **Location:** PLAN §7, the caption bullet; DM §6.5 and §8.1
- **Description:** Captions are in raw and keyed by `video_key`, but no release file links a recording to its caption files. The plan parks this together with transcript assembly. That bundling hides a cheap, high-value relation: an assistant can read a caption file itself.
- **Evidence chain:** O28; task 5 (O11).
- **Exercised by:** assistants asking what was said at a hearing, and the site's recording links.
- **Recommendation:** RESHAPE. In phase 2, each `meetings.videos` element gains `captions` (body, suffix, format), matched by the identifier in the caption's source URL. Transcript assembly stays parked.
- **Data check:** how many caption bodies resolve to a `video_key`. The plan's "99% of Senate meeting videos" figure suggests most do.

FINDING 7:
- **Severity:** CONCERN
- **Category:** ownership (operations)
- **Location:** the `congressional-tech` primary checkout
- **Description:** The MCP work edited the live checkout's `pyproject.toml` and `uv.lock`, and installed `fastmcp` into its `.venv`, re-locking `certifi` and `idna`.
- **Evidence chain:** O24; INVARIANT 5.
- **Exercised by:** the live recovery jobs that import from that `.venv` (PLAN §3).
- **Recommendation:** RESHAPE, for the owner to do: move `apps/explorer_mcp` and its lock change to a worktree branch, then restore the primary's `pyproject.toml`, `uv.lock` and `.venv`.

FINDING 8:
- **Severity:** OPTIONAL
- **Location:** DM §8.1, `detail`
- **Description:** `document_kind_source` (filename, publisher or review), like `document_date_source`, gives the baseline-versus-reviewed provenance the design wants (O8). No overlay identity is needed, because reviews are already pinned in the release's input identity (O26).
- **Evidence chain:** O8, O26, O27.
- **Recommendation:** KEEP the applied review; add the source column.

FINDING 9:
- **Severity:** OBSERVATION
- **Description:** The selection identity maps cleanly. One `release_id` plus its inputs record's spicy-regs generation digests gives a consistent pair of publishers. The design's catalog, sidecar and overlay verification reduces to recomputing the release ID and checking each file's SHA-256 (O3, O26).
- **Evidence chain:** O3, O26.

## 7. Verdict

DEFINITIONS:
- **D1, APPROVE:** no finding above OBSERVATION, and every checked invariant is preserved or relied upon.
- **D2, RECONSIDER:** a CONCERN or BLOCKER has a concrete reshape that keeps the intent.
- **D3, REJECT:** no reshape keeps the intent, or a sibling fully subsumes the artifact.
- **D4, NEEDS DISCUSSION:** exactly one open question gates the verdict.

**VERDICT: RECONSIDER, by D2.** D3 fails because the archive's documents are not yet served by the sibling (O23). D4 fails because no single open question gates the verdict.

Justification:
- **Intent against shape:** DIVERGES (FINDING 2; O1, O20).
- **User-value claim:** SUPPORTED for one interface; WEAK for a second server (FINDINGS 2, 3).
- **Commitment status:** BROKEN (INVARIANTS 1, 3, 4 and 5; FINDINGS 1, 4, 5 and 7).
- **Conceptual debt:** the current shape ACCRETES it; the reshape PAYS IT DOWN (FINDINGS 2 and 3).
- **Sibling subsumption:** PARTIAL, and large (FINDING 2).
- **Opposite-verdict probe:** REFUTED.
- **Confidence:** MEDIUM-HIGH. spicy-regs' MCP code was not read; its local mode's fit is FINDING 2's first step.

Required reshape:
1. **The archive release becomes a source of spicy-regs' MCP.** Extend ss-vhi2 item 4.
2. **The archive spec names its release consumers** and adds the manifest `coverage` block, the caption relation and `document_kind_source` (FINDINGS 1, 4, 6 and 8).
3. **Tasks 2 and 6 go to spicy-regs.** Tasks 1, 3 and 7 come from the release. The explorer MCP is frozen as a shim and retired at the stated condition (FINDINGS 2, 3 and 5).
4. **The primary checkout is restored** (FINDING 7).
