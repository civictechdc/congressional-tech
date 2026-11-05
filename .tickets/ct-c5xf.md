---
id: ct-c5xf
status: closed
deps: [ct-73oe]
links: [ct-jnm9, ct-93zs, ct-m104, ct-o7t4, ct-pocg, ct-082q]
created: 2026-10-30T14:10:02Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, congress-api, content]
---
# Use publisher-marked article and testimony content for cleaner text

The audit found 4,180 bodies with RDFa article content, including Veterans Affairs testimony pages. Current text can include navigation and other page-wide material.

User value: cleaner testimony text and useful previews, with fewer navigation words in downstream reading and analysis.

Evidence: docs/experiments/extruct-metadata-20261030/report.md and summary.json. Full extraction and comparison artifacts are under output/extruct-metadata-20261030/ (local, Git-ignored); preserve portable fixtures and manifests needed for tests rather than relying solely on these local paths.

## Design

Owner: congress_api HTML/archive parsing. Treat content:encoded and equivalent explicit article-body properties as main-content candidates. Compare them with the existing extraction before choosing one. Retain original HTML and the exact body/property selector; produce safe text rather than executing or directly rendering publisher markup. Preserve paragraph order and document links where applicable.

Keep title, short publisher description, and full article text distinct. Boilerplate, empty, partial, nested, or contradictory annotations need an explicit fallback. Store large extracted content through an existing retained/derived-content mechanism with a typed reference, not in every browser browse row. This task does not introduce a full-text search service.

## Acceptance Criteria

- A recorded representative cohort covers marked testimony, ordinary articles, multiple content candidates, boilerplate, malformed markup, and unannotated pages.
- Side-by-side review shows the selected content removes unrelated navigation without omitting testimony; failures retain the existing fallback and are counted.
- Original source bytes and exact selection evidence remain accessible. Text is safe for display and preserves meaningful order.
- Report candidate/selected/fallback counts and output sizes; presence of RDFa alone is not counted as an improvement.
- Publishable content references and bounded snippets are available to downstream mapping without duplicating full text across document rows.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-ae42a8cf7a429ba24 @ 180a49b1. Review verdict: merge, stay open for the owner's 20-page read of docs/experiments/html-metadata-20261101/content-cohort.md. Scope reduced to marked and no-content pages.

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: the 20-page side-by-side read is required before content selection is used. Under the 2026-11-02 autonomy grant, Claude reads all 20 in full and an independent reviewer repeats it; content selection ships only if neither finds dropped testimony. The owner may still read the cohort file.

**2026-11-02T10:37:30Z**

20-page read done 2026-11-02 by two independent full reads (read-green, read-red; .cache/rounds/r1b/c5xf/{green,red}.md): 0 of 20 pages lose testimony, checked against raw with a second parser; all 124 selected veterans.house.gov pages in the 850 sample also lose nothing. Verdict: ship with fixes, RDFa content:encoded path only. Fixes before use, all in parsers/main_content.py: (1) JSON-LD articleBody used raw: gov.uk f3a990b3 emits HTML markup, and a truncated JSON-LD body wins; keep that path off until it is fixed; (2) short marked blocks are dropped once one long block exists, so a long sidebar can win; (3) td/th/dt/dd/hr are not breaks ('20066,658'); (4) soft hyphens are kept; (5) hidden text is kept; (6) nothing calls select_main_content, so the trafilatura fallback and its counts don't exist; (7) content_cohort.py:47-48 counts only gained words, and the cohort is one template. Tests: dropping a middle paragraph fails none; pin the real fixture's full text. main_content.py feeds only the html_metadata version, not the release pins, so the fixes and the wiring go to Round 2 with ct-pocg/ct-93zs.

**2026-11-05T17:11:17Z**

Closed as superseded on 2026-11-05. Remaining scope, acceptance and evidence are explicitly transferred to ct-pocg. This is consolidation, not a claim that unfinished implementation or publication has passed. Original criteria and historical notes remain here. See the surviving owner and the reviewed consolidation report under .cache/archive-release/investigations/open-ticket-clusters-20261105T161237Z/consolidation-review/REPORT.md.

**2026-11-05T19:53:12Z**

Follow-up consolidation on 2026-11-05: ct-082q is now the surviving owner of the unfinished main-content scope previously transferred to ct-pocg. Its checklist retains the independent full-read conditions, safety/fallback fixes and source evidence. This ticket remains closed as superseded.
