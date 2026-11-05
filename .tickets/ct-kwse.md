---
id: ct-kwse
status: open
deps: []
links: [ct-94hw]
created: 2026-11-04T20:47:30Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, correctness]
---
# Document date taken from a bill title year in the filename (Batcheller testimony dated 2019-06-23, should be 2020-06-23)

Nightly candidate ef4c1632: after the saved copy swapped, the BatchellerG statement (base: HHRG-116-II13-Wstate-BatchellerG-20200625.pdf, dated 2020-06-25 from the filename) is dated 2019-06-23 from 'Bear Protection Act of 2019' in the new filename, with status accepted. Same saved-copy swap as the package_id ticket. Evidence: .cache/archive-release/nightly/20261104T174328Z/causes/evidence/05c-possible-defect-document-date.json.

## Acceptance Criteria

A year that is part of a bill/act title is not read as a document date; the document keeps 2020-06-25 (or meeting date). Fixture with an 'Act of YYYY' filename.


## Notes

**2026-11-05T01:09:33Z**

Fixed on branch saved-copy-identity (72abdc8e, 4da601e2; not merged). Cause: document_date took the saved copy's filename date; the newer saved copy 'AFWA testimony_H.R. 2264_Bear Protection Act of 2019_6-23-20_final.pdf' read token '2019_6-23' (act title year plus month-day). Fix, model SQL only (no reader change): FILENAME_DATE in archive_annotations.py drops a date token that starts at 'act of <token>', for both shown and linked names. New step document-filename-facts.sql takes filename date and Congress from every copy of the saved bytes: a convention name (reading valid) first, then the earliest value, so identical bytes posted for several meetings date from the first meeting. Neither crawl order nor which copy is saved changes it. Fixtures: unit (document-filename-facts incl. reused bytes), phase1 annotations (Act-of name dates nothing, own or linked), end-to-end build (the Batcheller pair keeps 2020-06-25 and Congress 116). Replay over the nightly's evidence (.cache/archive-release/investigations/saved-copy-identity/): the guard fires on 3 copies (Bear Protection Act of 2019, 'Act of June 22, 1948', 'EPS Improvement Act of 2016 1-12-16'). Of the 18 document_date changes, 8 return to base (Batcheller and 7 HHRG Wstate statements). 4 move from base's later re-posting or markup date to the witness's own Wstate hearing (Vallo 2019-04-15, Lindsey 2021-03-23, Parfitt 2021-03-18, Grijalva HMKP 2020-02-06). 6 keep the candidate value where base had none (3 CHRG meeting dates, 3 plain filename dates). The 1,215 filename-to-meeting documents all return to filename: 1,211 to the base date, 4 to the earlier hearing above. Release-wide vs base: 2,052 dates change. 1,410 are documents whose identical bytes were posted for several meetings (bios, testimony re-posted as SD) and now date from the earliest convention name instead of the newest fetch. 579 are newly dated from another copy's name (HHRG Wstate names, billsthisweek folders). 59 change from meeting date to filename date. 3 null-to-meeting are the candidate's. document_date_source: 10,585 more meeting-to-filename with the same date (label only). Open: 'EPS Improvement Act of 2016 1-12-16' loses a coincidentally right date (no other copy, meeting or content date); fixing that needs a house_naming reader change (byte-hashed, backfill). CHRG-117hhrg49353 now dates 2023-06-07 from its only dated copy, a re-posted SD at a later hearing (was its 2022-06-23 meeting). Lanes: production-offline (full lane): exit 0; native-loopback (full lane): exit 0.
