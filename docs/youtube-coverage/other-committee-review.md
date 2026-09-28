# Review of committees classified Other

Reviewed September 28, 2026 against published snapshot `a28ed92136c815512f99ef4a`, its retained inputs, current collector code, and official sources. The starting publication contained **31 Congress-specific Other records representing five bodies**. The expanded 106–119 metadata also exposes the historical Medicare Commission, reviewed below. Official-site checks establish concrete gaps; they are not an exhaustive census of every historical event.

The highest-value correction is to connect documents we already retain. A blanket relabeling of Other would introduce errors. One organizational-category adjustment is supported: the Senate Drug Caucus can use our `commission_or_caucus` category while retaining Congress.gov's exact `Other` value.

The inventory below records the original published gaps. The implementation following this review fixes the shared collection and linking rules and keeps source-backed exceptions in a small reviewed table. Original source names, classifications, dates, and files remain inspectable.

## Inventory and decisions

| Body / source code | Retained committee Congresses | Retained meetings | Classification decision and metadata adjustments |
| --- | --- | ---: | --- |
| Senate Indian Affairs — `slia00` | 112–119, eight records | 100 | Keep Other. Permanence does not establish Standing. Preserve the source name and add classification context rather than forcing Select or Standing. |
| Senate Caucus on International Narcotics Control — `scnc00` | 112–119, eight records | 13 | Use our Commission or Caucus category; preserve `source_committee_type=Other`. Its statutory standing-committee status should remain visible as a separate fact. |
| Committee of the Whole — `hshf00` | 112–118, seven records | 0 | Keep Other. Prefer display name “Committee of the Whole House on the State of the Union”; preserve the API name. Add the missing 119th Congress record with official evidence. |
| Congressional Oversight Panel — `jocp00` | 112, one record | 0 | Keep Other; retain joint chamber identity. Record termination on April 3, 2011 and its official archive. Connect existing documents. |
| Senate National Security Working Group — `sowg00` | 112–118, seven records | 0 | Keep Other. Add the missing 119th Congress record with official evidence. Do not infer inactivity or closed access from absent meeting data. |

Indian Affairs' own history distinguishes its original select status, permanent status from 1984, and 1993 name change. Both the [112th Senate calendar](https://www.govinfo.gov/content/pkg/CCAL-112scal-2012-07-16/html/CCAL-112scal-2012-07-16-pt3.htm) and [119th calendar](https://www.govinfo.gov/content/pkg/CCAL-119scal-2026-02-19/html/CCAL-119scal-2026-02-19-pt3.htm) place it in the combined Other, Select and Special section. That does not establish a more specific normalized category. [Committee history](https://www.indian.senate.gov/about/)

The Senate identifies the Drug Caucus as its legally recognized caucus. Its own history describes standing-committee status and the change from Commission to Caucus in 1985. The proposed category describes its organizational form; it must not discard those powers or the original API value. [Senate directory](https://www.senate.gov/committees/), [Caucus history](https://www.drugcaucus.senate.gov/about/)

The House describes the Committee of the Whole as the House conducting floor business in committee form. Its [January 14, 2026 FloorCast](https://live.house.gov/?date=2026-01-14) establishes 119th Congress activity despite its absence from the retained 119th committee list. This is not an ordinary standing committee hearing feed. [House committee history](https://history.house.gov/Records-and-Research/Committees-Bibliography/Committee-History/)

The National Security Working Group is likewise active in the 119th Congress: a Senate report discusses its continuing authority and funding, and an April 2025 appointment confirms current membership. These sources support adding the missing term; they do not establish a complete public meeting archive. [Senate Report 119-38](https://www.govinfo.gov/content/pkg/CRPT-119srpt38/html/CRPT-119srpt38.htm), [official appointment](https://www.schiff.senate.gov/news/press-releases/news-sen-schiff-appointed-to-u-s-senates-national-security-working-group/)

## 1. Connect the documents already retained

All **571 Government Publishing Office (GPO) transcript packages** for these five bodies are present in the published materials table. **510 have no committee or meeting association.** This is a relationship gap, not a failed download.

| Body | Retained GPO packages | Without committee links | Can attach to an existing committee term now | Need older committee terms first |
| --- | ---: | ---: | ---: | ---: |
| Indian Affairs | 533 | 473 | 170 | 303 |
| Drug Caucus | 11 | 10 | 0 | 10 |
| Congressional Oversight Panel | 27 | 27 | 2 | 25 |
| Committee of the Whole | 0 | 0 | 0 | 0 |
| National Security Working Group | 0 | 0 | 0 | 0 |
| **Total** | **571** | **510** | **172** | **338** |

The 338 historical packages predate the retained committee metadata's 112th Congress boundary. The existing GPO source rows retain `committee_code` and `congress`; the adapter currently links only through a verified meeting event ID. Consequently, a retained transcript with a known committee but no Congress.gov event disappears from committee navigation and committee-type filters.

The minimal repair is to create a direct document-to-committee association using the explicit source code and Congress. `MaterialLink.subject` already permits `committee_term`. Do not fabricate meeting IDs or claim that a committee association proves a specific meeting match. Extend committee metadata coverage to the Congresses already represented by the documents, and expose directly associated documents on committee detail pages.

Relevant implementation points:

- `packages/congress_api/src/congress_api/adapters/gpo.py`: currently associates packages through `event_id` only.
- `apps/committee_youtube/src/committee_explorer/export.py`: supplies meeting lookups but no committee lookup to the GPO adapter.
- `apps/committee_youtube/src/committee_explorer/parquet.py`: must carry direct committee associations into material `committee_ids` independently of meeting links.
- `apps/site/src/components/explorer/parquet-source.js` and `Explorer.tsx`: committee details currently browse meetings/issues, not directly associated documents.

Concrete example: the Oversight Panel's two 112th Congress hearings are already published as materials with HTML/PDF files, but both have empty `committee_ids` and `meeting_ids`:

| Date | Package / existing material ID | Official evidence |
| --- | --- | --- |
| February 4, 2011 | `CHRG-112shrg65083` / `83d06a3c-95db-410e-85b2-7cc02afcf056` | [Commercial real estate hearing](https://www.govinfo.gov/content/pkg/CHRG-112shrg65083/pdf/CHRG-112shrg65083.pdf) |
| March 4, 2011 | `CHRG-112shrg65276` / `e7bb2827-2bac-493d-9787-76972a0aa98c` | [TARP assessment hearing](https://www.govinfo.gov/content/pkg/CHRG-112shrg65276/html/CHRG-112shrg65276.htm) |

Its [final report, appendix C](https://www.govinfo.gov/content/pkg/CPRT-112JPRT64832/html/CPRT-112JPRT64832.htm) lists these hearings. [Treasury testimony](https://home.treasury.gov/news/press-releases/tg1091) identifies the final hearing and April 3 termination; the [Senate archive gateway](https://www.senate.gov/general/common/generic/COP_redirect.htm) preserves the panel's historical status. A retained `witness_count=0` does not establish no witnesses: these transcripts contain testimony.

## 2. Fix source collection before adding individual missing witnesses

### Drug Caucus

`scnc00` is absent from `senate.pages.SITE`, so the committee's official hearing pages are not part of the 21-site collector. All 13 retained meetings have witnesses unchecked and there are zero associated witness appearances. Twelve have documents and transcripts unchecked. These are collection gaps, not confirmed absences at the source.

A bounded probe of the [June 24, 2026 cartel hearing](https://www.drugcaucus.senate.gov/hearings/beyond-our-shores-the-global-reach-of-mexican-drug-cartels-and-risks-to-u-s-national-security/) found three witness names in the current parser, but blank positions and zero documents. Testimony links lead to attachment pages at `/media-center/files/...`, while the file recognizer expects direct file/download paths. Those pages link to working PDFs: [Chris Urben](https://www.drugcaucus.senate.gov/media-center/files/chris-urben-testimony/), [Michael Brown](https://www.drugcaucus.senate.gov/media-center/files/michael-brown-testimony/), [Vanda Felbab-Brown](https://www.drugcaucus.senate.gov/media-center/files/vanda-felbab-brown-testimony/).

Add the site, preserve role text, and follow these explicit attachment links. Do not infer that one successful name parser covers the site's documents, dates, and complete archive.

### Indian Affairs

The current parser skips witnesses already present in HTML. On the [August 4, 2026 prediction-markets roundtable](https://www.indian.senate.gov/hearings/roundtable-titled-tracking-prediction-markets-exponential-growth-tribal-implications-and-beyond/), five names are present, but `witnesses()` returns zero. Names use `h4.jet-listing-dynamic-field__content`; the parser requires `h3`. The code comment that newer lists require browser rendering is inaccurate for this sample.

The publication contains 341 witness appearances across 100 Indian Affairs meetings. Fifty-five meetings have witness coverage unchecked; that is not a claim that all 55 should have witness lists. Fix and replay the parser against retained/live page evidence, rather than manually creating names from the coverage count.

## 3. Admit official events that have no Congress.gov meeting

At least three official events are absent from the entire published meeting table, not merely hidden by a committee filter:

| Body | Date | Official event |
| --- | --- | --- |
| Drug Caucus | October 27, 2022 | [Deadly Distribution field hearing](https://www.drugcaucus.senate.gov/hearings/u-s-senate-drug-caucus-to-hold-field-hearing-in-des-moines/), with a [transcript](https://www.drugcaucus.senate.gov/wp-content/uploads/2022/11/Transcript.pdf) and five witnesses |
| Indian Affairs | August 26, 2026 | [Native Hawaiian housing roundtable](https://www.indian.senate.gov/hearings/roundtable-to-discuss-how-native-hawaiian-serving-stakeholders-are-using-innovative-approaches-partnerships-and-advocacy-to-build-housing-supply-with-federal-and-state-funds/) |
| Indian Affairs | August 27, 2026 | [NAGPRA implementation roundtable](https://www.indian.senate.gov/hearings/roundtable-to-discuss-advancing-the-promise-of-the-native-american-graves-protection-and-repatriation-act-and-to-identify-ways-congress-can-improve-its-implementation-for-the-native-hawaiian-community/) |

The present Senate reader discovers pages to enrich an existing Congress.gov meeting. It needs a way to retain an official-site event under its own source identity when no such meeting exists. A backfill restricted to existing meeting IDs cannot recover these events.

There are also no retained meetings for either body in Congresses 112–115. The Senate reader cuts off listings before June 2019. Earlier pages remain available, including [Indian Affairs, April 7, 2011](https://www.indian.senate.gov/hearings/business-meeting-consider-s-675-s-676/) and [Drug Caucus, April 6, 2011](https://www.drugcaucus.senate.gov/hearings/senate-caucus-on-international-narcotics-control-hearing-on-dangerous-synthetic-drugs/). Treat this as a declared collection boundary until historical events are imported.

## Manual adjustment safeguards

- Preserve the **March 2, 2022** date of Drug Caucus meeting `92fe366f-ed69-496f-b74a-5f37ff3ddfde`. Its [webpage](https://www.drugcaucus.senate.gov/hearings/the-150-billion-drug-market-a-dive-into-the-economics-of-cartels/) shows March 4; the [stenographic transcript](https://www.drugcaucus.senate.gov/wp-content/uploads/2022/03/113902.pdf) dates the proceeding March 2. Associate the page/materials without changing the hearing date to the webpage date.
- Preserve both type assertions for Indian Affairs meeting `9842da13-3756-449f-a315-2ab301cc0250`: Congress.gov says Hearing; the committee says Roundtable. Add a supported normalized Roundtable category before preferring the committee's description; retain the original value and evidence.
- Do **not** delete an alleged current Indian Affairs Investigations subcommittee. The retained data has no standalone `slia01` term. It embeds that historical name in parent metadata for Congresses 112–118, but not 119. The current Senate directory's “None” does not contradict our published 119th hierarchy.
- Keep source values immutable. Record curated categories, display names, added Congress-specific terms, lifecycle dates, and source-backed associations separately with reasons and citations.

## Recommended order

1. Connect the 172 retained transcripts to existing committee terms, and show those documents on committee pages.
2. Add Drug Caucus collection and repair both witness/document parsers.
3. Add the two missing 119th committee terms and three confirmed missing events using their actual official source identities.
4. Apply the small metadata adjustments above; retain four of the five bodies as Other.
5. Extend historical metadata and event collection, starting with the 338 already-retained transcripts whose committee terms are absent.

Suggested coverage text should distinguish the cases: “Floor proceedings are outside this collection” for the Committee of the Whole; “Terminated April 3, 2011; historical records available” for the Oversight Panel; and “No meetings collected; public meeting coverage not established” for the National Security Working Group. None of these means the source had no activity.


## Implementation and verification

The GPO adapter now links documents directly to a committee term using the retained source code and Congress. Official committee metadata covers Congresses 106–119; three explicitly identified terms absent from those lists are retained from GPO evidence. The original audit confirmed associations for all 571 packages reviewed here and 34,511 packages overall. All 48 remaining packages were then reviewed against raw MODS, document covers and corroborating official sources. Eleven had a rejected alphanumeric code, twenty-eight had IDs in constituent metadata, and nine need cited manual assignments. See the [individual decisions](manual-source-review.md). A committee link does not resolve a missing meeting association.

The reviewed bodies use the cited decisions in `packages/congress_api/src/congress_api/adapters/committee_adjustments.py`. Native values remain in source evidence and `source_committee_type`; display normalization does not create a false unresolved conflict. The Committee of the Whole and National Security Working Group gain supported 119th Congress terms. The Oversight Panel's end date and archive remain visible.

The Senate collector adds the Drug Caucus, parses current Indian Affairs witness headings and role text, and follows explicit attachment pages to their files. Historical collection for these two sites is bounded from January 3, 2011. Official pages can establish a meeting under their own URL when they provide an event title and date and no supported native meeting association exists. Ambiguous candidates remain unlinked. Roundtable selection keeps the committee's evidence and the original Congress.gov description. The March 2, 2022 date correction cites the transcript and preserves the webpage's conflicting date.

Committee detail pages show directly associated documents with the existing category filters, links to their subcommittees, and source-backed lifecycle and collection notes. With All Congresses selected, terms sharing an explicit committee code and chamber appear in one row with Congress buttons. Each button opens that exact term; grouping does not merge source identities or assume names and classifications stayed constant. Unhelpful hierarchy definition rows are hidden from the summary while their evidence remains available.

The bounded backfill fetched 431 pages, admitting 312 additional official events with 990 witness appearances and 1,142 document links. All 24 withheld Indian Affairs pages now connect to 19 existing native events using their exact identifiers; no duplicate events are created for component pages. The other 20 Senate sites remain unchanged. Historical embedded-recording extraction was not checked by this backfill; its coverage remains unchecked.

The expanded official committee lists also include `jcfm00` (Medicare Commission Committee) in Congress 106, with native type Other. A [Federal Register notice, page 2237](https://www.govinfo.gov/content/pkg/FR-1999-01-13/pdf/FR-1999-01-13.pdf) identifies the National Bipartisan Commission on the Future of Medicare and its January 26, 1999 meeting. The normalized category is Commission or Caucus for that retained term; the native name and Other label remain available. The notice does not establish an exact termination date or a complete meeting collection, so neither is inferred.

Final full-data preservation checks, browser checks, and publication receipts are recorded after the bounded collection and export complete.
