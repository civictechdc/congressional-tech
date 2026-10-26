# CS 300 review 7: Congressional Document Archive at commit 40ee51b2

Lens: systems (concurrency, crashes, retries, races; Big O; I/O and memory; raw-data safety; plan order). Documents read cold and in full; my independent pass is `cs300-professor-review7-own.md` beside this file, written before the lead's opinion was opened. Tags: **[measured]** = my `prof7_*.py` scripts here (outputs in the matching `.out` files) over the read-only snapshot, the raw receipt mirror and three public requests; **[doc]**; **[est.]**.

## 1. Score: 84 / 100

| Area | Score | Why |
|---|---|---|
| Architecture correctness | 85 | The record-role list has no arm for `warc` (M1); ambiguity is tested across formats (S3); everything else I traced holds |
| Efficiency | 86 | Every repeated path is now named and bounded (materialized steps, link-match bound, budgets); the one unstated size is the 23 GB ZIP walk (S5) |
| Failure behavior and raw-data safety | 85 | Every review-6 raw and failure finding is folded in; the budget rule parks publish behind a manual step (S2) |
| Plan | 83 | Risky measurements first; one fixture tests a shape the real data does not have (S4); the 16k-group parity cause is an artifact (S1) |

Verdict: build from these after the one-line M1 fix; S1–S5 are small rewrites that can land in the same pass.

## 2. Findings

### Must-fix

**M1. `warc` has no record role; 10,278 provider envelopes become documents and make about 10,000 endpoints edition-ambiguous.**
*Where:* DM §7.3 `record_role` list (lines 414–430); DM §6.2 format values (line 234) name `warc`; invariant 8 (line 730).
*Failure:* a WARC is a capture container, not content, but the role list's only arm for it is "`'document'` otherwise". The log holds 10,278 WARC bodies (2.44 GB, family `external/provider-responses`, one per URL: 4,756 at `.pdf` URLs, 215 at `.htm(l)`, 5,198 at extensionless page URLs) **[measured, prof7_warc_dochouse.py]**. Their capture entries carry no status of their own; under DM §6.1 (line 197) a row without its own attempt status takes the line's final-response status, the publisher's 2xx, so each is a good fetch and a real file at the publisher's URL. Each such endpoint then holds two distinct real bodies whose fingerprints can never agree, so DM §7.5 puts both in `edition_bodies`: 4,741 PDF endpoints and 5,439 page endpoints **[measured, prof7_grouping2.py, the `[pdf, zip]` and `[html, zip]` endpoint rows]**. The real PDF never joins its XML or HTML rendition, and 10,278 WARC "documents" are listed. No S1 fixture has a WARC.
*Fix (rewritten text):* in the role list, after `'playlist' when format = 'm3u8'`, add the line `'container' when format = 'warc'`; invariant 8's parenthesis becomes "(listing, wrapper, error, container, damaged or failed reading)"; S1 gains one row: "A provider's WARC envelope at a PDF's URL | `container`; the PDF's endpoint is not edition-ambiguous".

### Should-fix

**S1. "About 16,000 groups across about 32,500 documents" is an artifact of the old catalog, and E4 would file 16k differences under a predicate that never fires.**
*Where:* DM §7.5 line 545; P §6.5 E4 bullet "about 16k format groups merge (32,547 documents today)".
*Failure:* the population is docs.house.gov: 18,265 `(directory, stem)` pairs with a `.pdf` and a `.xml` source file **[measured, prof7_status_gap.py (d)]**. At docs.house.gov `.xml` URLs the captures are 40,572 rows of `text/html` with non-2xx status (21,807 bodies), 17,671 rows of one single body (the 404 page, a placeholder), and 11,218 good XML bodies **[measured, prof7_warc_dochouse.py]**; the old catalog named the 404 body `BILLS-….xml` and paired it with each PDF. Under §7.3 those rows are not good fetches, so the real same-stem (b) count on effective filenames is 1,740 groups: 1,625 draw edges over 3,250 bodies (docs.house.gov 816, congress.gov 670, frwebgate 173; 1,508 PDF+XML, 218 HTML+PDF, 9 DOCX+PDF), 2 are refused for two bodies of one format, 114 lose a format to an ambiguous body **[measured, prof7_grouping2.py]**. The large merge is rule (a) through GovInfo ZIP links: 34,140 of 34,319 ZIPs (S4).
*Fix:* line 545 → "about 1,700 same-stem groups and about 34,000 GovInfo ZIP groups today"; E4's bullet → "about 1,700 same-stem groups and about 34,000 GovInfo ZIP groups merge".

**S2. A budget overrun parks publish until a person starts a backfill.**
*Where:* A §12 "Budgets" (line 466) and the orchestration block (line 462: backfill "on demand").
*Failure:* after any import day (547k bodies [doc]) the HTML step is over budget, so publish refuses every day until someone runs the backfill by hand, and capture runs from a stale `url_state` meanwhile.
*Fix:* rewrite the bullet's last clause: "is run by the publish workflow as a backfill, in batches, before the pin; publish refuses until it is empty."

**S3. Ambiguity is tested across formats, so a page-then-file URL bars the file from every rendition group.**
*Where:* DM §7.5 `ambiguous_bodies` (line 489); A §3 "edition-ambiguous endpoint" (line 104).
*Failure:* 526 `[html, pdf]` endpoints and 15 `[html, pdf, zip]` **[measured, prof7_grouping2.py]** served a hearing page and later a PDF; their fingerprints can never match, so both go into `edition_bodies` and the PDF never joins its XML. A page and a file are not editions of each other.
*Fix:* "an endpoint holding two or more distinct real bodies of one format whose fingerprints differ or are missing"; the same four words in A §3.

**S4. The GovInfo ZIP fixture tests a shape the data does not have, and the 34,000 groups hinge on one registry entry the DM only hints at.**
*Where:* P §5.3 S1 row "A linked GovInfo ZIP holding one hearing's HTML and PDF" (line 116); DM §7.1 source-record roots row "such as MODS and PREMIS" (line 348).
*Failure:* every GovInfo ZIP holds five members, `html/*.htm`, `pdf/*.pdf`, `dip.xml`, `mods.xml`, `premis.xml` (34,028 of 34,319 exactly this; 112 lack the PDF; 179 hold several HTML or PDF members and are rightly refused) **[measured, prof7_grouping.py]**; `dip.xml`'s root element is `mets` **[measured, prof7_dip_and_status.py, one public GET]**. The one-body-per-format rule draws the `zip+html+pdf` edges only because all three XML roots are source records; only B §4 K32 names METS. A fixture with two members cannot fail when METS is left out of the registry.
*Fix:* fixture → "A linked GovInfo ZIP holding one hearing's HTML and PDF with its METS, MODS and PREMIS manifests | The ZIP, HTML and PDF form one document; the manifests are source records". Registry row → "XML roots of metadata records: METS, MODS and PREMIS".

**S5. The ZIP fingerprint step reads 23 GB, unstated.**
*Where:* DM §6.2 line 252 and 255.
*Failure:* of 685 endpoints with two distinct real ZIP bodies, 626 hold a ZIP whose members were never captured: 626 bodies, 23.2 GB to walk; 59 already decide as ambiguous because their member sets differ **[measured, prof7_grouping2.py]**. The budget of A §12 cannot be set from "up to 1,400 ZIPs fingerprinted from their members".
*Fix:* replace that phrase with "about 1,400 ZIPs, 626 of them walked (23 GB)".

### Minor

- A §11.5 line 441: "579" bodies over 100 MB; 588 by original bytes **[measured, review 6]**. Say which size is meant or use 588.
- P D1: the `assemble-*` shapes under `undated/` carry no `http_status` in `record` (0 of 5,000 lines in three files **[measured, prof7_dip_and_status.py]**), yet 1.8M of their rows have a status in the old index; the per-shape sample must name the field it comes from.
- P §5.3 edition count / §6.5 "about 960 veterans.house.gov pages saved by two archives": with only `web.archive.org` unwrapped, 2 veterans.house.gov endpoints hold two page versions; the visible page-version endpoints are docs.house.gov (198) and waysandmeans.house.gov (29) **[measured, prof7_grouping2.py]**. The second archive's wrapper must be among the URL-wrapper registry seeds (B §4 K17) or that merge does not happen; name it there.
- P §6.5 E4: add the cause "source IDs of API-fetched files change where their URLs lost credential parameters" (DM §5.2).
- DM §7.4 line 474: a recovery-only document's bodiless row now has filename `''`, which sorts first in `list`; "else the original link's last segment".
- A §6 diagram line 183: `captures` "one row per body a receipt line references" omits the bodiless-line rows (the lead's nit; agreed).
- A §8.6 / DM §6: a `readings` schema change re-reads 1.04M bodies (sniff) and 5 GB (pages); say "at D2's measured cost" so the owner can weigh a schema change.

## 3. Review-6 findings against the new text

| # | Finding | Status | Where |
|---|---|---|---|
| M1 | Cleanup removes credential parameters yet promised byte-identical URLs | RESOLVED | DM §5.2 l.158 "A recorded URL changed only by losing a credential parameter"; P B0 l.188; inv 12 l.734 "no row carries a credential parameter"; A §7.2 l.254. Key rotation withdrawn: no real credential in any receipt (reconciliation 1.1) |
| M2 | Receipts written after the backup had no original | RESOLVED | P B0 l.186 "each receipt not in the backup is copied into it before it is rewritten" |
| M3 | One inlined plan re-evaluates shared subplans | RESOLVED | A §9.1 l.326 (named steps, materialized once); A §13.1 l.478; P M2 l.96 (both forms measured) |
| S1 | 412 on a receipt write silently drops it | RESOLVED | A §7.2 l.252; DM §5.2 l.109 |
| S2 | An errored sniff yields a real file | RESOLVED | DM §7.3 l.415 null role; DM §6.2 l.233; A §8.3 l.300 |
| S3 | First weekly check re-hashes 0.7 TB | RESOLVED | A §7.4 l.268–270; P B9 l.199, B10 l.200 |
| S4 | D1 timestamp check covers only undated receipts | RESOLVED | P D1 l.238 (522,448 / 47,359 measured) |
| S5 | 404 reload can loop | RESOLVED | A §11.3 l.431; inv 21 l.746 |
| S6 | Fingerprint step unbounded in the daily run | RESOLVED, opens new S2 | A §12 l.466 |
| S7 | Backfills outside the concurrency group | RESOLVED | A §10.3.7 l.415; §12 l.465, l.472 |
| S8 | B14 before B2's spool | RESOLVED | P B14 l.204; B §8 l.192 |
| S9 | Gzip PDF with no `.pdf` copy has no rule | RESOLVED | DM §6.2 l.249; S1 fixture l.126 |
| S10 | Invariant 2's multipart clause | OPEN in text, withdrawn by evidence | DM inv 2 l.721 unchanged; two older bodies (1.09 GB, 10 MB) carry plain MD5 ETags **[measured, prof7_etag_head.py]**, the lead's 24 agree |
| m | 1,500 object operations a day | RESOLVED | A §16 l.522 "4,000–8,000" |
| m | 579 over 100 MB | OPEN | A §11.5 l.441 |
| m | Recovery-only bodiless filename unspecified | PARTLY | DM §7.4 l.474 "else `''`" (now a defined but poor value; minor above) |
| m | ZIP walk size | OPEN | DM §6.2 l.255 (now S5) |
| m | E4 cause for credential-stripped source IDs | OPEN | P §6.5 |
| m | Stale `url_state` during a publish outage | OPEN, accepted | A §12 l.468; bounded |
| m | "98k metadata records" | RESOLVED | DM §7.5 l.547 (47,643 + 103,200) |

The reconciliation's handling matches each: 4.2, 4.4, 4.6, 4.7, 5.2, 5.4, 5.7, 5.9 and 3.1 are the entries above; 4.8 refutes S10, which my own HEADs confirm.

## 4. The lead's claims

| Claim | Verdict | Evidence |
|---|---|---|
| Grade about 87 | DISAGREE, 84 | Three points sit in M1 (a rule with no arm for a format the data holds 10,278 times), S1 (a headline number reproduced from old error-page pairs) and S2 (publish parked behind a manual step) |
| Raw-data safety 9.5 | AGREE | Every raw finding of review 6 is folded in; the cleanup copies to the backup first; run IDs never reuse; the re-hash precedes the first check; two sampled ETags are MD5s |
| Grounded in data 9.5 | PARTLY, 8.5 | Most numbers reproduce (§5 below); but "16,000 groups / 32,500 documents" is an artifact (S1), the ZIP walk's 23 GB is unstated (S5), and the fixture for the biggest merge omits the manifests that decide it (S4) |
| Internal consistency 9 | PARTLY, 8.5 | No contradiction between stated rules; the gap is silence: §6.2 defines `warc`, §7.3 gives it no role (M1), and §7.5 tests ambiguity across formats where the term's own definition speaks of editions (S3) |
| Executable plan 8.5 | AGREE | Order front-loads the lock, B0, M1, M2 and S1; M1 and M2 are open as the lead says; S2 is the one executability gap I add |
| Simplicity 7 | PARTLY | Not my lens; DM §7.5 is intricate but each line earns its place on the data; the cost shows as fixtures that miss real shapes, not as excess rules |
| Readability and concision 7 | AGREE | DM is 9,929 words and the four documents 27,835 **[measured, wc]**; outside my lens |
| Holds back 1: grouping only fixture-checked | AGREE, and tested | Real data confirms: GovInfo ZIP groups (34,140 join, 179 refused), same-stem (1,625 edge groups), saved-text twins (363,361 of 363,940 share a SHA-256, so `same_body` alone collapses them), no member path ever served two bodies, only 7 bodies lack any 2xx row. Real data refutes: `warc` (M1), cross-format ambiguity (S3), the 16k estimate (S1) |
| Holds back 2: ceremony | PARTLY | Outside my lens; keep P §3's merge check, which is the raw-safety gate while the old writers run |
| Holds back 3: density | AGREE | As measured above; not a systems defect |
| Nit: A §6 diagram omits bodiless rows | AGREE | A §6 l.183 vs §8.2 l.288 |
| Nit: P §1 `stored_sha256` | AGREE | P §1 l.29 describes the old path; a reader of DM §6.1 l.218 will stumble |
| Raise 1: run S1 as an executable model on real data | AGREE | This round's slice found M1 and S3 in an afternoon; make the slice the GovInfo ZIP, WARC, docs.house.gov and page-version populations named here |
| Raise 2: cut boilerplate, concision pass on DM §7 | PARTLY | Outside my lens; do not cut the merge check or the budgets |
| Raise 3: run M1 and M2, re-grade | AGREE | Both decide the lake's shape and the model's step form |
| Already checked: invariant 2 holds for old bodies | AGREE | My two HEADs agree with the lead's 24 |

**What the lead missed:** M1 (the `warc` role gap and its 10k poisoned endpoints), S1 (the 16k-group figure is the old catalog pairing PDFs with a 404 body at `.xml` URLs), S2 (budgets park publish behind a manual backfill), S3 (cross-format ambiguity), S4 (the GovInfo fixture shape and METS), S5 (the 23 GB walk), and the minor that D1's `assemble-*` shapes carry no status in `record`.

## 5. Data checks

All scripts in this folder, run through the pinned venv with `-I`; outputs beside them.

| Script | What it settles |
|---|---|
| `prof7_inspect.py` | Old-catalog occurrence fields: `source_document_group` is a group *kind* (`meeting_xml`, `meetingDocuments`, …), not a path, so publisher groups cannot be reconstructed from the snapshot; member rows' status shape; the 455-body document is `Error.aspx` (never listed), so "largest listed document 27" is plausible; max source files at one URL is that same page |
| `prof7_occ_sample.py` | Samples of grouped occurrences: no key reproduces `group_path` |
| `prof7_receipt_shape.py` | Raw receipt shapes: old `record.links` lists are empty in the sampled families; `captures[]` entries carry `http_status` only on download shapes |
| `prof7_grouping.py` | First pass (format by URL extension, superseded where noted): GovInfo ZIP member multisets (34,028 × `[html, pdf, xml, xml, xml]`); all 34,319 GovInfo ZIPs hold ≥2 members of one format; package PDF = ZIP member PDF in 2,085 packages, differs in 83; no member endpoint holds two bodies |
| `prof7_grouping2.py` | Corrected pass (media type first, `web.archive.org` unwrapped): real-file proxy 261,361 PDF / 110,884 XML / 94,025 HTML / 45,539 ZIP bodies; edition-ambiguous endpoints by format (`[pdf]` 209, `[html]` 252, `[zip]` 685, `[html, pdf]` 526, `[pdf, zip]` 4,741 and `[html, zip]` 5,439 = WARC, `[html, untyped]` 2,268); ambiguous-body upper bounds (PDF 5,590 / 15.7 GB incl. WARC-driven; HTML 11,895); ZIP endpoints: 626 need a walk (23.2 GB), 59 ambiguous; `dip.xml`, `mods.xml`, `premis.xml` in every GovInfo ZIP; same-stem (b) on effective filenames: 1,740 groups, 1,625 edges, 3,250 bodies, by host; page-version endpoints by host |
| `prof7_status_gap.py` | Only 7 bodies have status-less rows and no 2xx row anywhere (the `attempt_status` test loses nothing); WARC rows explained; loose same-stem population: docs.house.gov 18,268 groups |
| `prof7_dip_and_status.py` | `dip.xml` root = `mets` (one public GET); `assemble-*` undated receipts: 0 of 5,000 lines carry `record.http_status` or `retrieved_at` |
| `prof7_warc_dochouse.py` | 10,278 WARC bodies, family `external/provider-responses`, status null, one per URL, 4,756 at `.pdf`; docs.house.gov `.xml` captures: 21,807 HTML error bodies, one 404 body at 17,671 rows, 11,218 good XML bodies; old catalog's 24,093 docs.house.gov `.xml` source files over 5,990 bodies |
| `prof7_savedtext.py` | 363,361 of 363,940 saved-text bodies share their SHA-256 with an exact-bytes row; the 383 URLs with a differing exact body are captions; no saved-text body is a URL's only copy |
| `prof7_etag_head.py` | Two HEADs: a 1.09 GB and a 10 MB older body carry plain MD5 ETags, `Content-Type: application/gzip`, no `Content-Encoding` |

Numbers I re-derived for the lead's "grounded in data" score: the DM's 300 PDFs / 13 GB fingerprint estimate is consistent (418 PDFs at `[pdf]` endpoints plus the 526 `[html, pdf]` ones; 15.7 GB upper bound including the WARC-driven endpoints that M1 removes); "up to 1,400 ZIPs" is 1,370 bodies at 685 endpoints; "34,095 of 34,319" GovInfo ZIPs is 34,140 by member shape; "16,000 groups / 32,500 documents" does not stand (S1).
