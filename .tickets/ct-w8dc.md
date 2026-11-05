---
id: ct-w8dc
status: closed
deps: [ct-5w9u, ct-c5xf]
links: [ct-93zs, ct-m104, ct-t915, ct-5kto, ct-gi01, ct-082q]
created: 2026-10-30T14:10:02Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, congress-api, committee-meeting]
---
# Map page metadata to meeting and material fields with source evidence

Extracted fields need clear meaning before they become user-facing facts. A webpage update is not a hearing date, and an organization/person annotation is not proof of witness participation.

User value: users see accurate dates and document descriptions without mixing committee officials, authors, witnesses, or site maintenance events.

Evidence: docs/experiments/extruct-metadata-20261030/report.md and summary.json. Full extraction and comparison artifacts are under output/extruct-metadata-20261030/ (local, Git-ignored); preserve portable fixtures and manifests needed for tests rather than relying solely on these local paths.

## Design

Owners: congress_api/adapters and committee_meeting. Populate existing scheduled_start/location, Material.published_at/source_modified_at, SourceRecord source timing, ReportedTime, provenance, and DataIssue facilities. Add one optional Material.description for an eligible publisher-supplied summary, with source evidence and generic/template-description rejection.

Retain publisher document labels and article sections separately from normalized categories. Resolve conflicts using explicit source/context rules; preserve alternatives. Canonical URLs are declarations to validate, not automatic cross-host identity merges. Person cards require role/context evidence before witness mapping. Map main-content references from the content task into the maintained text/representation model rather than inventing a second material system.

## Acceptance Criteria

- The 2017 Indian Affairs hearing with a 2025 page modification keeps its event date and separately records the page update.
- The Banking Powell example retains the actual witness without adding committee officials from their person cards; publisher author admin is not a witness.
- Advisory/press-release labels, material descriptions, publication times, and main-content references preserve citations to the exact reading/source location.
- Internal admin-host canonical declarations and conflicting dates do not silently rewrite established document/meeting identity.
- Date-only and unzoned values retain their precision; model/schema/generated-client compatibility and old-record round trips pass with the optional description field.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-ae42a8cf7a429ba24 @ 180a49b1. Review verdict: merge. Real material-page data waits on ct-pocg; one context per run is required.

**2026-11-05T17:11:18Z**

Closed as superseded on 2026-11-05. Remaining scope, acceptance and evidence are explicitly transferred to ct-93zs. This is consolidation, not a claim that unfinished implementation or publication has passed. Original criteria and historical notes remain here. See the surviving owner and the reviewed consolidation report under .cache/archive-release/investigations/open-ticket-clusters-20261105T161237Z/consolidation-review/REPORT.md.

**2026-11-05T19:53:12Z**

Follow-up consolidation on 2026-11-05: ct-082q is now the surviving owner of the unfinished HTML mapping scope previously transferred to ct-93zs. Its checklist retains field semantics, exact source citations, date precision, identity controls and compatibility. This ticket remains closed as superseded.
