# Filename viewer interface review

Reviewed against catalog `5330fee64ba94373ab508b051f7140dc` on October 14, 2026.

The visual direction is a calm, compact archive workspace: readable document names, clear source evidence, and quiet technical detail. The content order is search and results, document summary, provenance, filename findings, then the complete recorded fields. Opening the inspector, pending-result feedback, and hover/focus feedback provide restrained motion; reduced-motion preferences disable transitions.

## Changes and user value

| Area | Finding | Refinement |
|---|---|---|
| Results | Three sparsely populated columns compete with filenames. | Combine Congress, committee codes, and measures under **Filename clues**. Preserve their filename-derived meaning. |
| Results | Long monospace filenames and routine HTTP 200 labels slow scanning. | Use readable proportional type; keep technical identifiers in monospace and show HTTP failures when relevant. |
| Search | Search-field selection takes a full row on phones. | Keep search, scope, and saved status prominent; move search-field selection to More filters and show the active field in its caption. |
| Filters | Long saved-status options clip at phone widths. | Use **Saved** and **None saved**, with an explicit group-level explanation. |
| Inspector | One-line headings hide most of a filename. | Show two lines with a full-filename disclosure, preserving the original value. |
| Classification | Source-page readings are buried even when they disagree with filename classification. | Show a distinct Source-page kind, including whether it was inferred. |
| Provenance | Raw URLs obscure which website supplied the link. | Lead with the recorded title or hostname, then the exact path. Preserve hearing-to-page-to-file relationships without inventing titles. |
| Saved files | Storage paths and access explanations repeat in a separate section. | Explain access once in the summary; keep object keys in Download and storage. |
| Filename findings | Partial dates, arbitrary identifiers, and unmatched text read like facts. | Keep descriptive findings prominent and route parser fragments to their original searchable fields. |
| Grouped sources | Multiple records are labeled as distinct URLs even when URLs repeat. | Say **source records** and preserve each original record. |
| All fields | A flat list mixes source context, parser output, and storage metadata. | Group fields by purpose, preserving labels, raw keys, values, empty-value controls, and JSON export. |
| Loading/errors | Stale results remain actionable, and failures lack a direct retry. | Disable old results during a query; provide retry actions and hide stale pagination. |
| Recovery | Accepted URL variants must be recognizable without rewriting original failures. | Show **Recovered**, the recovered format and URL, and the original fetch outcome separately. |

## Field coverage

The [field guide](filename-viewer-field-guide.csv) inventories all **347 existing catalog fields** and their presentation decisions:

- 12 identity and classification fields.
- 53 source and provenance fields.
- 15 download and storage fields.
- 8 saved-content findings.
- 259 filename interpretation fields, including 173 parser fragments kept out of the primary filename-findings section.

The additional computed `recovery` object belongs with Download and storage. No source values or naming rules are changed by this interface pass. Reviewing the schema and representative values does not constitute revalidating every record in the corpus.

## Verification

Visual checks cover desktop and phone results; primary and advanced filters; empty searches; saved, unsaved, API, conflicting, and unavailable entries; transitive hearing provenance; source switching; searchable raw fields; and local saved-text expansion. Real catalog records cover the normal and provenance paths. Explicitly labeled local fixtures cover error and saved-content paths unavailable through the public static viewer.

Regression tests cover exact preservation of original fields, source pairing, contradictory classifications, recovery labels, asynchronous selection, empty/error recovery, filter discoverability, and existing group-level saved-response semantics. Production publication and its live checks are recorded separately from local review evidence.

The freshness check also detects recovery-status changes within the same catalog, so an open viewer can offer the updated status without waiting for a new catalog ID.


## Follow-up mobile review — October 14, 2026

Visual thesis: a quiet reading surface with the file identity, saved status, and source trail visible before optional evidence.

Content plan: concise facts first, hearing and website relationships second, useful filename clues third, then raw fields. Empty findings and repeated publisher text become disclosures.

Interaction thesis: retain the short drawer entrance and action hover feedback; use native disclosures for evidence, and let an expanded filename scroll away so it cannot monopolize a small screen. Reduced motion remains supported.

The deployed 390px view still repeated the filename as subject text, placed several evidence controls after each source, and used verbose per-field notes. It also called unverified URLs a publisher copy and presented pending fetch state as if it were live. The follow-up removes the redundant summary heading, abbreviates routine evidence labels, consolidates source evidence into one disclosure, collapses filename analysis when it has no independent findings, and labels links and fetch state explicitly. Original field values and the proven hearing-to-file chain are retained.

## Deployed-app review after the serving-layout release — October 14, 2026

Reviewed the published results at 390px and 1440px, plus mobile details for the UN hearing-to-article chain, Schondelmeyer testimony, a recovered Judiciary transcript, and the Finance record with 12,147 observations. The revision keeps the same quiet surface and native disclosures, with website and saved-copy actions first, provenance next, and detailed evidence on demand.

- Original and saved links now have separate, aligned touch targets. The original shows its hostname; the saved copy identifies the R2 archive and any recovery. Failed responses say **Open saved response**, so a stored error page does not look like a usable document.
- Routine saved status appears beside the action instead of repeating in the facts. Missing copies, conflicting completeness, and unusable responses still receive explicit explanations.
- **Where it came from** preserves the hearing → intermediate page → file chain. Direct page dates appear only when the recorded page/date association is unambiguous. Repeated “Found on” captions are consolidated.
- Recovery locations are labeled **Saved copy recovered from**. Additional pre-recovery URLs remain under Source evidence, and missing referring pages remain explicitly unknown.
- Multiple classifications and committee names start collapsed, with the original readings and their basis available inside. They no longer read as one definitive description of the file.
- Counts say **source records**, and records without a URL or filename receive an explicit label instead of a blank source selector.

Local verification: 31 UI tests and 11 catalog/publication tests pass; the production build passes. Screenshots cover 320px, 390px, and 1440px. Normal and recovered saved-copy endpoints return HTTP 200 with PDF content types. Opening the detail view still leaves technical metadata unloaded. This is a presentation change; no catalog, recovery mapping, or published data object is rewritten. Browser evidence is under `output/playwright/` in the viewer worktree.
