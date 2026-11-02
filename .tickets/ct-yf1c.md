---
id: ct-yf1c
status: open
deps: []
links: [ct-n2cy, ct-lgxk]
created: 2026-11-02T04:01:45Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [model, release, phase2]
---
# Documents publish with blank filenames

The live release has 2,901 blank filenames. review-c-explorer: 1,426 are PDFs from EPW and Small Business Files.Serve URLs with no name in the URL; 1,320 are HTML, mostly hearing pages; 169 are recovery-only; 62 PDFs and 21 XML have blank names despite named URLs because of trailing slashes or a NULL-address saved row. saved-files still selects those rows.

## Acceptance Criteria

Every listed document has a usable name or title rule, and saved-files does not select a NULL-address row.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): 1,446 Files.Serve PDFs have no name in the URL or headers; fix uses trailing-slash names and puts the named copy of the saved body first. impl-g.

**2026-11-02T13:15:40Z**

2026-11-02 (lead): impl-g Run A: about 2,764 blank filenames on base code, 1,420 of them PDFs; with the fixes, the model's missing_filenames check reports 502. impl-g is explaining all 502 from raw.

**2026-11-02T14:16:11Z**

2026-11-02 impl-g (r1b-g): the 502 missing_filenames predate this round. They are retained-import originals the filename producer never read: the model's recovery candidates include undecided imports (71cf2b2d), while the producer read decision files only (7c0eb08a). All 513 receipt lines were read. Fix a8019f6d: the producer also names undecided imports (+502 readings; catalog version unchanged). 89285289: every blank filename carries a recorded reason or the release refuses. Run B reasons: 1,492 query URLs, 3 bare hosts, 1 no address.

**2026-11-02T14:46:01Z**

2026-11-02 green-g (request changes): 1,444 of 1,496 blank filenames are named in raw by the redirect's final URL or Content-Disposition; captures.py:281 (fdb9242c) prefers record.url over final_url. impl-e1 keeps the final URL; impl-g derives names from it and h_content_disposition; the 'query URL' reason only checked for '?'. Also an undocumented saved-file ranking change moved 196 GovInfo PDFs to congress.gov filenames: justify from §7.5 or revert.

**2026-11-02T14:50:56Z**

2026-11-02 (lead): red-g: rendition titles outrank the publisher's own link text (coalesce order), and no_address tests the capture url, not the published context_url (203 documents and 124 senate/pages bodies reachable only via null-url rows). Sent to impl-g, along with e1's url = final URL decision.

**2026-11-02T15:30:02Z**

2026-11-02 impl-g: no-URL captures are named by their context address (row 941 is CHRG-117hhrg54192.pdf); the blank reason reads every capture of the saved body (03d05805); Files.Serve names come with e1's d3e49b9d (captures.url = final URL), which also names the 6 banking testimony PDFs; the ZIP member demotion is reverted (c846b0a8).

**2026-11-02T15:38:20Z**

2026-11-02 red-g2: a NULL-address source can tie or beat the addressed copy after c846b0a8 (about 6 wins and 46 ties on Run B); rank rows with neither address nor member path last. Context names in Run B are always the body's own URL, never a listing page.

**2026-11-02T21:36:15Z**

2026-11-02 inv-rca ef3a79d1: generic_titles=1 was a real Senate Aging title ('Click Here: Accessible Federal Technolog... | Senate Committee On Aging', 71 chars; the 2022-07-28 hearing). The rule in source-annotations-pages.sql reads link words only in titles up to 64 characters, but the gate used 96 (since bbf7dbd5, no reason given). The gate now uses the rule's bound, and a test runs titles through both. Model only.
