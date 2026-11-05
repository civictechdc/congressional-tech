---
id: ct-kthe
status: open
deps: [ct-h1nd]
links: [ct-j2yo, ct-x78c, ct-5w9u, ct-dx22, ct-egg6]
created: 2026-10-30T18:34:44Z
type: feature
priority: 2
assignee: mikewolfd
tags: [phase-2, senate, parsers, witnesses, etl-workflow]
---

# Find witnesses and their testimony from three Senate committee sites

Readers should be able to open the testimony a committee page assigns to a witness. The earlier Phase 2 D4 check associated 25 of 49 Intelligence testimony documents, 3 of 20 Environment documents, and none of one across 56 candidate Joint Economic Committee (JEC) pages. These counts describe that sample. The current audit traced the JEC failure.

## Root cause (2026-11-05)

The retained June 12, 2024 JEC page “Made in America: The Boom in U.S. Manufacturing Investment” shows two separate failures.

- The plain witness parser treats adjacent parts of Scott Lincicome’s title as separate people. Both anchors refer to file `D2F941B3-FF5F-4503-B354-5C8BE5D7AF3B`. The release publishes “Stiefel Trade Policy Center” as another witness with the same testimony.
- The retained page already supplies the same title and date as event `335901`. The model maps the JEC host to `jsec00`, while this event has `jjec00`. A separate candidate filter excludes the event because its chamber is null. Both rules run before the title and date checks can link the page.

The old `retention/document_links.py` diagnosis is stale. `senate_page.py` now calls `source_details_tree` directly. The actual versioning gap is that the plain parser calls `witness_names.witness` but the Senate version omits the helper. The current failure paths for Intelligence and Environment remain untraced.

## Smallest useful change

Keep a source-supported continuation in one witness card, with its title, organization, panel and evidence. Let the existing matcher consider event `335901` through the supported local JEC identity, correcting the alias and eligibility rules while keeping the date, title and ambiguity checks. Preserve source committee codes and the raw unknown chamber. Reuse existing page facts for the model repair. Trace one exact retained miss on each of the other two hosts before deciding whether admission, extraction or matching needs a change.

## Acceptance Criteria

- The JEC fixture publishes one Scott Lincicome occurrence with the complete title and the source-bound testimony, and links it to `335901`. Keep genuinely distinct witnesses that share a file, and preserve ambiguity when page evidence does not resolve a meeting.
- The retained Intelligence, Environment and JEC fixtures recover witness appearances and source-bound `document_urls`. Flat or ungrouped links stay unassigned to individuals.
- Keep the extractor independent of `retention/document_links.py` internals. Account for the shared witness helper in the Senate version before carrying readings across a helper change. A Senate-only extractor edit advances its source version while the MODS, Congress.gov and House XML versions stay stable.
- Record the exact replay scope, version and resulting lake output. Keep the three-host counts tied to their measured sample.

## Coordination and evidence

The retained JEC HTML SHA-256 is `b4c3127548dbf19424641b714dfc301050797c164a8ce20e3e11d087ecc8cc0f`. [Root-cause analysis](../docs/plans/production-mvp-root-causes-20261105.md) · [Phase 2 annex, §4.2.1](../docs/plans/phase-2-annex-20261028.md)

Use the existing Senate version work and coordinate any shared helper edit with the MODS owner. The local JEC match can ship independently of explaining chamber gaps across the release. [ct-h1nd](ct-h1nd.md) · [ct-lx67](ct-lx67.md) · [ct-opy0](ct-opy0.md)

## Notes

**2026-11-05T20:18:06Z**

Integrated the JEC continuation repair, source-specific committee matching and shared-helper version tracking. All 9,818 Senate records replayed successfully; independent comparison found exactly the named JEC list changing from five rows to four, with Scott Lincicome's role and testimony URL preserved. Intelligence discovery is fixed, but its exact detail request returned 403; the exact Environment source fixture remains unavailable. These gaps and final selected-release acceptance keep the ticket open.
