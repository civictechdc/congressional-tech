# Document date grounding: assumption and source probes

Status: pre-registered 2026-11-04 before any probe ran. Results are appended below; the lines above
"Results" are not edited after data collection (revisions are added with a reason).

## Decision

Which date sources and rules ct-m94a should adopt in the model's date selection:

1. Should a linked hearing's date override a contradicting filename date?
2. Should two-digit years be resolved when exactly one century fits the evidence?
3. Which unused sources are worth wiring in, in what order: GovInfo MODS held dates, listing-page dates,
   URL path tokens, PDF metadata, bill committee-activity dates?
4. Are the current policy's thresholds (30-day capture allowance, Congress window with one year of margin)
   calibrated?

## Inputs (frozen)

- Served release e4538f00 (MCP cache `~/.cache/congress-explorer-mcp/objects`): detail, meetings,
  witnesses, sources, bills.
- The release's model inputs, `.cache/archive-release/publish_v21/inputs` (the first snapshot of the
  archive tables e4538f00 was built from): captures, readings, filename_readings, appearance_records.
- Probe outputs: `.cache/archive-release/investigations/date-grounding-20261104/`.
- Not available locally: HTTP Last-Modified headers (captures carries none), MODS `dateIssued`,
  appearance_records.held_dates (added 2026-11-02, after these inputs). Raw receipts and bodies are in R2.

"Trusted hearing date" below means: the document links (meeting_keys) to exactly one hearing with a
meeting_date. It is a reference, not gold: links can be wrong (H2 checks one way they can be).

## Hypotheses, predictions and decision rules

H1 (filename vs hearing). Filename dates agree with a single linked hearing's date.
Predict >= 99% within 1 day; disagreements > 30 days are mostly misreadings (same month and day,
different year). Adopt "hearing overrides contradicting filename" if > 30-day disagreements are < 0.5%
and >= 80% of a reviewed sample are misreadings. Weakened if many are legitimate (reused documents,
documents for a different hearing).

H2 (event-ID links). A docs.house.gov URL's /YYYYMMDD/ path date equals its linked hearing's date.
Predict >= 99% equal. If not, the trusted reference itself is unreliable and H1/H3/H4/H6 weaken.

H3 (30-day allowance). For documents with a trusted hearing date, the hearing is at most 30 days after
first capture. Predict >= 99.9%. If more than 0.1% exceed 30 days, widen the allowance to the
observed 99.9th percentile.

H4 (Congress window). Trusted hearing dates fall in the tagged Congress's years +/- 1.
Predict >= 99.9%; violations are Congress-tag typos.

H5 (content dates). Content-sourced dates rarely violate the capture bound or the Congress window.
Predict < 0.5% violations. If higher, content dates need the same suspect check as filename dates.

H6 (two-digit years). Rule: a short-year token (MM.DD.YY with any separator, or compact MMDDYY) has
candidates 19YY and 20YY; accept the unique candidate that is no later than first capture + 30 days
and, when a Congress tag exists, within its window. Validate on documents with a trusted hearing date:
predict the resolved date equals the hearing date (+/- 1 day) in >= 98% of resolved cases, with
< 1% resolved to a wrong century. Adopt (as a labelled resolution) if met; otherwise no change.
Compact MMDDYY is reported separately (more ambiguous).

H6b (revision, added before any data was collected). Reason: the capture bound alone never excludes 19YY
(a 2016 capture is consistent with 1910 and 2010), so H6 resolves only Congress-tagged documents. H6b adds
a lower bound of 1994-01-01 for documents whose source is a committee website (not govinfo.gov), since
those sites did not exist earlier. Same validation and thresholds as H6; both are reported.

H7 (one date per document). Descriptive: share of documents with several date candidates and of
hearings with several sitting days. No decision rule; informs whether to publish date kinds.

H8 (undated means no evidence). Count undated documents with each kind of grounding evidence in a
priority waterfall. Predict a majority have some usable evidence. Ranks sources by yield.

H9 (MODS held dates). For CHRG packages whose MODS names a hearing event ID that exists in meetings,
the MODS held date equals the meeting date. Predict >= 98% (multi-day prints excluded or reported).
Adopt MODS held dates for printed transcripts if met.

H10 (listing pages). An HTML page with a content date that links to a document gives the hearing date.
Validate on documents with a trusted hearing date: predict >= 90% agree within 1 day when exactly one
dated page links to the document. Report coverage among undated documents.

H11 (URL path year). A /YYYY/ or /YYYY/MM/ path token matches the document's trusted year.
Predict lower agreement than H10 (upload year, site migrations). Use only as a bound if < 95%.

H12 (PDF metadata). PDF CreationDate is within 30 days before a trusted hearing date.
Bounded sample: up to 150 PDFs fetched from the public archive. Predict 50-80% (re-saves, scans).
Use only as a tie-breaker if < 95%.

H13 (bill committee activity). Documents referencing one bill can be dated by that bill's committee
hearing activity. Descriptive coverage only among undated documents; no validation (no clean reference).

Not probed (need new collection): Wayback first snapshots, Congressional Record daily digest,
committee + witness matching, HTTP Last-Modified for committee sites, MODS dateIssued.

## Held constant and bounds

Single pass over the frozen inputs above. No pipeline or model change. Network use limited to H12's
sample of at most 150 bodies from the public archive. Stop after one pass of every probe or 2 hours.

## Results

Run 2026-11-04. Scripts and raw outputs: `.cache/archive-release/investigations/date-grounding-20261104/`
(`probe.py` -> `results-run3.json`; `followup.py` -> `followup.json`; `h12_pdf.py` -> `h12_results.json`;
the first H12 run, all HTTP 403 from the default Python user agent, is kept as `h12_results-403.json`).
Peak memory 3.6 GiB, 4 s per pass. 197,240 documents have a trusted hearing date.

Availability correction: the served inputs have no `appearance_records.held_dates`, but `readings` already
holds each MODS file's held date (`content_date`, taken from `heldDate` when there is exactly one) and its
event IDs (`named_meetings`). H9 uses those; no re-parse is needed to use MODS held dates.

| Probe | Result | Pre-registered rule | Verdict |
| --- | --- | --- | --- |
| H1 filename vs hearing | 137,613 compared; 99.76% within 1 day; 118 (0.086%) differ by > 30 days, 54 of them misreading-shaped (46%) | < 0.5% and >= 80% misreadings | Not met (misreading share). Blanket override rejected |
| H2 URL path date vs hearing | 90,185 of 90,332 equal (99.84%), 99.89% within 1 day | >= 99% | Met |
| H3 30-day allowance | 0 of 197,052 documents captured before their hearing; earliest 2025+ capture is 5 days after | >= 99.9% within 30 days | Unresolved: the archive was collected after the hearings, so there are no early postings to calibrate against |
| H4 Congress window | 4 of 197,240 violate (0.002%) | >= 99.9% | Met |
| H5 content dates | 0 after capture; 14 of 34,826 outside the window (0.04%), 7 of them "2001-09-11" headings | < 0.5% | Met |
| H6 two-digit years (capture + Congress only) | resolves 100 undated documents | (see H6b) | Bounded: too few resolve |
| H6b two-digit years (+ 1994 web floor) | 96.2% (separated) / 96.1% (compact) within 1 day of hearing; 0 century errors in 6,476 | >= 98% and < 1% wrong century | Not met (agreement); century component met |
| H7 multiple dates | 2,845 documents with > 1 date candidate; 18 of 18,687 hearings span several days (1,235 documents) | descriptive | — |
| H9 MODS held date vs hearing | 3,027 of 3,043 equal (99.47%) | >= 98% | Met |
| H10 listing-page date | 95.7% within 1 day unguarded; 98.0% (15,544 / 15,861) with Congress-window + capture guard | >= 90% | Met |
| H11 URL path year | same year 80.1%; path year >= hearing year 99.94% | bound only if < 95% | Upper bound only |
| H12 PDF CreationDate | 142 of 150 have one; 64% 0-30 days before hearing; 25% after (printed transcripts) | tie-breaker if < 95% | Tie-breaker at most; not adopted |
| H13 bill committee hearing | 27% within 1 day of accepted document dates (3,408) | descriptive | Rejected as a date source |

H1 detail. Of the 118: 28 are already `suspect` (the suspect rule is precise: 28 of its 29 cases with a
trusted hearing disagree with that hearing), 26 are misreading-shaped but accepted, and 64 are not
misreadings: reused bios that keep the first hearing's date, and hearing records with wrong dates (an
113th-Congress hearing dated 2019-12-25). In those 64 the filename is right, so "hearing overrides
filename" would make them wrong. Only "hearing overrides a suspect filename date" is supported.

H6 post-hoc comparison (added after seeing results; reason: the 98% bar was set without a baseline and is
stricter than the accepted four-digit source). Four-digit filename dates on the same population (committee
website files, excluding HHRG/HMTG/HMKP/BILLS/CHRG/CRPT/CPRT/PLAW names) agree within 1 day in 97.5%
(10,405 / 10,669); their year error rate (same month and day, other year) is 0.49%, vs 0.29% for two-digit
years. Of the 248 two-digit mismatches, 153 are documents dated 2-60 days before their hearing (memos,
notices). This is post-hoc and does not convert the pre-registered verdict.

H10 detail. Unguarded misses are dominated by template dates shared across many pages (1955-08-09: 247,
2001-01-12: 61, 1865-11-15: 18). The guard only works where a Congress tag exists; an explicit
template-date exclusion is needed for untagged documents.

H8 (undated, 92,476 documents; first matching evidence):

| Evidence | Documents |
| --- | ---: |
| hearing via meeting key / via witness | 0 / 0 |
| GovInfo transcript MODS held date | 23,445 |
| other GovInfo package MODS date | 143 |
| single dated listing page | 7,888 |
| two-digit year resolved (H6b) | 15,160 |
| bill with one committee hearing (rejected, H13) | 869 |
| Congress tag only (two-year window) | 4,227 |
| URL path year only | 3,010 |
| none | 37,734 |

The "none" group is mostly unclassified (17,879) and testimony (5,804) files from committee sites.

## Decision

- Adopt (met pre-registered rules): MODS held dates for GovInfo transcripts (H9) from the `readings` MODS
  rows by package; guarded listing-page dates with a template-date exclusion (H10); "hearing overrides a
  suspect filename date" (H1, 28 documents); a Congress-window suspect check for content dates (H5).
  Expected: undated 92,476 -> about 61,000.
- Owner's call: two-digit years (H6b) failed the pre-registered agreement bar but matched the existing
  four-digit source post hoc; adoption would take undated to about 45,800.
- No change: the 30-day allowance (H3 unresolved; matters once daily capture sees early postings), URL path
  years (bound only), PDF metadata and bill hearings (rejected).
- Not probed: Wayback first snapshots, Congressional Record daily digest, committee + witness matching,
  HTTP Last-Modified, MODS dateIssued.
