# Congressional Document Archive: Implementation Plan

**Note, 2026-10-24**

## Abstract

- **Goal:** build the system of [[ARCHITECTURE]] and [[DATA-MODEL]] from today's congressional-tech and docspec-rs code, beside the old pipeline, then switch and delete what is bound to nothing (§2). Work runs in dependency order, with no schedule or effort estimates.
- **Two phases (§4):** phase 1 switches the site to an engine-built release of documents, rebuilt from raw, reusing every per-item result raw or legacy data already settles; phase 2 adds hearings, witnesses, the spicy-regs entities and the large one-time raw jobs.
- **First:** the lock on `bodies/` and `provenance/`, then B0, then the lock on `receipts/`; then M1, M2 and S1 (§4–5).
- **Open (§8):** Basin file growth (M1); memory and the older receipts (M2); the rules on real data (S1); the widest is the model (track E).
- **Owner actions:** the bucket lock (B1); confirm B0's field list; review six recovery excerpts (B7); decide on facts only the old index or derived tables hold (D1, E4); decide whether to widen fingerprint candidates (S2).
- **Detail:** behavior in [[ARCHITECTURE]]; schemas, derivations, registries and invariants in [[DATA-MODEL]]; code in [[BINDINGS]].

## Status of This Document

A Note, not a specification: it carries no normative requirements, cites contracts rather than restating them, and names no existing files.

## Table of Contents

1. [Introduction](#1-introduction)
2. [Strategy](#2-strategy)
3. [Constraints and Rules](#3-constraints-and-rules)
4. [Order of Work](#4-order-of-work)
5. [First Steps](#5-first-steps)
6. [Tracks](#6-tracks)
7. [Parked](#7-parked)
8. [Uncertainties and Tests](#8-uncertainties-and-tests)
9. [References](#9-references)

## 1. Introduction

The raw log already exists: bodies, receipts and provenance in the R2 bucket `congressional-tech-raw`, backed up on 2026-10-24. Its bodies keep their stored form; the only changes are uncompressed copies of older gzip PDFs (B13) and the one-time cleanup of older receipts (B0), as [[ARCHITECTURE]] §7.1–7.2 specify. Everything above raw is rebuilt.

Already in place: the hosted setup refuses an engine revision other than the qualified one; today's capture index carries `stored_sha256` from the receipt and never derives it; the gzip-deleting path is gone; and the 12,431 recoveries that existed only in `accepted.json` have a write-once backup under `provenance/recoveries/`. The bucket lock is pending with the owner.

## 2. Strategy

**Contracts first.** Each component's contract suite ([[ARCHITECTURE]] §4, principle 8) is written before any code is bound to it.

**Bind, adapt or build,** as [[BINDINGS]] §1 defines and records for each component. Code that carries a broken pattern is not adapted: the component is built with only its sound parts lifted. Hard-won behavior becomes registry seeds and fixtures rather than code paths.

**One implementation per component** ([[BINDINGS]] §2, rule 1): where today has several, the binding picks one and the rest are deleted. External systems are the only variation, injected as adapters ([[ARCHITECTURE]] §4, principle 8).

**Reuse before re-reading.** A per-item result that raw or legacy data already settles is borrowed, with its basis recorded, and only the gaps are read; an old decision across items (grouping, matching, roles) is never borrowed, only used as a parity oracle. Measured on the 2026-10-16 snapshot (`measurements/phase1-inventory-20261026/`):
- PDF integrity: 258,021 of 261,125 older PDFs already carry it, from their capture check (lines from 2026-10-02 on) or the old reader's successful open, so only about 18,600 (*est.* 124 GB) are read whole and the PDF copies wait;
- ZIP fingerprints: the member hashes are in `captures`;
- run fresh because they are small or the old data cannot serve: `sniff` (about 1.04M short range reads; old formats cover 36% in other categories), the page readings (289,179 bodies, 5 GB; old readings hold no titles, text sizes or links), the filename readings (7–18 minutes; parser changed since the old catalog, which becomes their diff oracle) and the receipt ingest (all local, about a minute);
- deferred: the full re-hash (one listing records every older body's size and ETag until then) and the PDF copies.

**Switch, then delete.** The target components are built beside the old pipeline. At the switch the publish path binds to them; the old layers are then bound to nothing and are deleted whole, as [[BINDINGS]] §6 lists them. Until the switch, the old capture job keeps writing raw data and reading the raw index, and gets raw-safety fixes only; its whole-leaf index rewrites continue until then, which is accepted.

## 3. Constraints and Rules

**What must survive:** objects in `congressional-tech-raw` under `bodies/`, `receipts/` and `provenance/`. Everything else can be rebuilt, and nothing uses it yet.

**Rules for every step**

- One conceptual move per PR. Contract tests land before the code bound to them moves. Behavior changes go in their own PRs.
- Run checks only through the project runners: `.venv/bin/python scripts/dev.py test <lane>` in congressional-tech and `scripts/check` in docspec-rs. Never use a tool from `PATH`. Say this in every agent and reviewer brief.
- Work in a separate worktree and venv. The primary checkout backs live recovery jobs.
- Report before and after `wc -l` in every PR that deletes code.
- Each step names its evidence: a contract test, or a measurement committed under `docs/`, never in the gitignored `output/`. A change to a rule names the fixtures it re-ran.
- Create the ticket before the first code commit. An epic closes only after its children. Acceptance criteria name an observable behavior and the test or measurement that shows it. Performance work records a baseline on real data and the decision rule first. A deletion closes only when the old path is gone.

**Merge check**

1. Before and after each merge that touches a raw-writer component, list `receipts/` and `bodies/` read-only. Every earlier key is still there with the same size and ETag; only additions are allowed. B0's one-time receipt cleanup is the single exception, and its verification records account for every change.
2. Every receipt-referenced body exists.
3. After the bucket lock: read the lock rules back after any infrastructure change.

## 4. Order of Work

**Phase 1, the documents-only switch:** the site serves an engine-built release of documents, saved copies, sources, recoveries and dead-link lookups, rebuilt from raw; capture runs from it; the old pipeline is deleted.
1. The bucket lock on `bodies/` and `provenance/` (owner, B1), at once; then the old writers patched and B0; then the lock on `receipts/`.
2. M1, M2 and S1; S2's document fixtures and the labeled sample beside track C.
3. F0 and the hand-built fixture; C0; track A and track B's items 2–9 and 12.
4. Track C, then D (items 1–3 and 5), then E (the document core, [[DATA-MODEL]] §7.1–7.10, and `urls`), then F (items 1, 2 and 5).

Phase 1 releases carry `meetings.parquet` with keys only and omit the other entity files ([[DATA-MODEL]] §8.1): hearings are filtered by key, committees show system codes, and a document dated only by its meeting shows no date.

**Phase 2, connections and one-time raw jobs,** each adding files or facts without changing the document core:
- hearings and witnesses: B15, D4, and the meeting and appearance relations ([[DATA-MODEL]] §7.11), cheap: about 60k bodies (9 GB) plus the 199,156 inline records already in the receipts;
- the spicy-regs entities (committees, members, rosters, bills, CBO estimates, floor votes, nominations), with their pin lists and the committee explorer's move (F3–F4), after spicy-stack ss-vhi2's retention change;
- the large raw jobs: B13 (PDF copies), B10 (full re-hash), B14 (cut-off re-fetches), B16 (wrapped files), S2's edition-count widening, and the memory work of ss-6jg6.

| Track | Components | Depends on |
|---|---|---|
| A | Reader, canary and contract test, site | F0 and the hand-built fixture |
| B | Raw-writer components | §4, item 1 |
| C | Engine | M1, M2, S1 |
| D | Lake producers | C2, B2; B13 for D2; B15 for D4 |
| E | Model | S1, S2, C1, C3, C4, D |
| F | Publish job, capture scheduler, switch | A, E, B13 |

A and B can run beside C.

## 5. First Steps

M1, M2 and S settle the lake format, the receipt reader, the model's memory and step form, and the rules; F0 gives the reader its fixture.

### 5.1 M1: Basin Catalog Under Maintenance

**Decides:** Iceberg stays if the rows read back unchanged and the file and manifest counts, projected to ten years at the measured growth, keep a full scan of `captures` under a minute on the smallest runner. Otherwise the lake tables move to dated Parquet files with an `If-Match` manifest per table: the same atomicity, without time travel. The fallback changes the scope of C1, C2 and D.

All three tests run on scratch tables, with Basin's catalog-level compaction and snapshot expiration on.

1. **Guarded commits.** An append whose base snapshot a second client's commit has moved fails rather than being rebased, recomputes its work list and lands within three retries; two ingest runs on the same receipts leave exactly one copy of each row. A second client's commit stands in for Basin's maintenance, which cannot be timed.
2. **Growth, expiration and drops.** With snapshot expiration at its shortest age, append day-sized batches (about 315 KB) across at least ten Basin maintenance runs.
   - After each run, count the current snapshot's data files and manifests and the bytes expiration removed, check that the rows read back equal those appended, and read a compacted file's footer for its codec.
   - Read the table through iceberg-datafusion 0.10.1's static provider with a partition filter, and confirm the filter reaches scan planning.
   - Then drop the table with purge and list what remains.
3. **The engine's remote write caps.** Measure scan and commit cost with and without the engine's 2 MiB file and 2,048-row group caps. [[DATA-MODEL]] §6 assumes they go; if they measurably help, that section changes instead.

### 5.2 M2: Wide Joins and Grouping in a Throwaway DataFusion Harness

**Decides:** the receipt reader, the size of track C, the model's step form, and whether DataFusion handles the wide joins within the pool. The harness is deleted afterwards.

The engine cannot run the full export until C1, C3 and C4 exist, so a short standalone DataFusion program measures first, using S's draft rules.

- **Inputs:**
  - all 2,289 receipts, read with the receipt reader of [[ARCHITECTURE]] §13 and the draft ingest mapping, with a sample of each older shape ([[DATA-MODEL]] §6.1), and its rows compared with the pinned capture index (`db033173…`, 3,909,134 rows). Record the reader's time, its peak memory on the 188 MB line, and the conflicts it nulls per receipt, and commit a field-presence census (each field's line count per receipt family and shape) that the ingest mapping must cover: review 8 found rules written against shapes the receipts do not have;
  - the pinned catalog generation `596f08fa…`, with today's filename readings;
  - links parsed from a sample of pages.
- **Joins:** run the model's joins, including `url_key`, link resolution and the link join (about 4.2M links, scaled from the sample, against 1.31M source URLs), filename readings, `detail` and `sources` (up to 1.7M rows).
  - Report every intermediate join's row count and bytes and every hash-join build's size, as well as time and peak memory.
  - The links are sampled, so this tests mechanisms and memory; D2's full link backfill repeats the join on real data.
- **Step form:** run the model twice, as inlined steps and as named steps with the components and documents materialized once. Compare `EXPLAIN ANALYZE`, time and peak memory, including memory the pool does not account for.
- **Grouping:** group the graph with the specified rule, using the sampled links; D2 repeats the grouping on real links. Record time, peak memory and the largest components.
- **Runner:** `ubuntu-24.04` (4 vCPU, 16 GB), the smallest runner class.

### 5.3 S: The Semantic Checkpoint

S writes every rule as SQL with its fixtures (E1), in two parts:

- **S1, before track C** (M2 and the engine depend on it): the real-file and grouping SQL with their fixtures, marked S1 below;
- **S2, beside track C:** the rest of the SQL and fixtures, the labeled sample, the edition count and the raw-only check.

- **What S writes (E1):** the reference model profile; every registry as a versioned file with its first contents and sample tests, seeded as [[BINDINGS]] §4 lists.
- **Fixtures first:** each fixture below is written with its expected outcome before any SQL, so the table is the acceptance sheet. S adds a row for each format of [[DATA-MODEL]] §6.2 the table does not yet name.
- **An executable model:** S1's fixtures run as the draft SQL over fixture tables and over real slices (the GovInfo ZIPs, the End of Term lines, docs.house.gov's `.xml` URLs, the pages saved twice in one fetch and the short-page sample), before any further change to the rules they cover.

| Part | Fixture | Expected outcome |
|---|---|---|
| S1 | A PDF replaced while its XML stays, with historical pages linking both | Three documents: each PDF edition alone, and the XML alone |
| S1 | Two editions served at one address, and two mirrors that each pair one of them with the same XML | No document holds both editions |
| S1 | Re-packaged copies of each edition, each paired with one XML, never at a shared address | The known limit: such a copy can join the XML; the edition count measures how often |
| S1 | A ZIP repacked so `report.pdf` moves to another position, with mirrors pairing each edition with the same XML | One edition-ambiguous endpoint; the editions stay apart |
| S1 | Two archive members with one name and different bytes | An edition-ambiguous endpoint; neither member takes a rendition edge |
| S1 | A linked GovInfo ZIP holding one hearing's HTML and PDF with its METS (`dip.xml`), MODS and PREMIS manifests; a linked ZIP holding two different PDFs | The ZIP, HTML and PDF form one document and the manifests join none; no rendition edges |
| S1 | Several same-format files listed together; unrelated files on one page outside any list item | Each stays its own document; the unlisted files get no publisher group |
| S1 | One PDF body under two download names, listed with its XML | One document with both names and the XML; the group counts one PDF body |
| S1 | One page template under two hearings, where only hearing A's PDF and hearing B's XML were captured | No rendition edge between them |
| S1 | One page saved by a direct attempt and a provider retry with different page furniture; an archived page also imported as a rendered recovery | One document each: equal main-content fingerprints; the recovery attaches as labeled evidence |
| S1 | A page with relative links saved in two directories; a relative `<base href>`; a page whose relative links point at sibling archive members | Each copy's links resolve against its own address and base; member links target endpoints in the same container |
| S1 | A concatenated `href` whose two targets both exist | Two links, in `href` order, one target each |
| S1 | URLs written with raw spaces and with `%20` | One `url_key` |
| S1 | A placeholder page at thousands of addresses | Not a real file; it connects nothing, and its links are not resolved |
| S1 | A short real hearing page; a short soft-error page; a near-empty page; a "your download will begin" page | `document`; `error_response`; `error_response`; `wrapper`, with its file link queued |
| S1 | A broken PDF; a valid PDF with trailing bytes after its end marker; a new valid PDF; a PDF over the reader's limit with no end marker in its tail; an older gzip PDF with no verified copy | `damaged`; real; real, from the `intact` its capture recorded; `damaged` and reported; read whole from its `.gz`, real when intact, and reported |
| S1 | An Office file; an End of Term `.warc.gz` or `.arc.gz` envelope stored beside its payload | One body, no members; `envelope`, and the payload's endpoint holds one real body |
| S1 | An older line with outcome `html` and a 2xx response; a site home page or "Under Maintenance" page served at a `.pdf` URL | A good fetch; not a real file (file-shaped), reported by error type |
| S1 | A feed page | `listing`, and no link context |
| S1 | A response with no declared length read to a clean end; a body assembled from ranges of one entity; ranges whose entity changed in between | Complete; complete; not complete |
| S1 | A cut-off direct attempt and a complete provider retry in one fetch | The retry's body is real; the cut-off body is not |
| S1 | A recovered file that a real fetch also saved | A real body and link key; the recovery attaches as labeled evidence |
| S1 | An incrementally maintained lake and a clean rebuild, after a registry change and after a table rebuilt at a new schema | Byte-identical releases |
| S2 | One body under two filenames | Two source files in one document, which shows the saved file's name |
| S2 | Two editions served at one address | Two documents sharing a `version_keys` entry |
| S2 | A House witness list with two panels, a member witness and witness documents; one witness name at two meetings | Two panels; the member keeps the source's `bioguide_id`; each document carries its witness's `witness_key`; two keys for the name, not matched |
| S2 | One Congress.gov meeting record copied on 11 receipt lines, and a second version with a later `updateDate` | One `record_sha` per version; the later version is current |
| S2 | A Senate hearing page whose witness cards hold their testimony links | Appearances with the page as occasion; each testimony carries its witness's `witness_key` |
| S2 | A postponed meeting on a bill, recorded by House XML and Congress.gov | The House XML record is current; `status` postponed; the bill in `subject_keys` |
| S2 | A Senate hearing transcript whose MODS record lists witnesses and names no meeting | Appearances keyed by the package; the transcript's page lists them, and no document is credited to them |
| S2 | A Senate meeting whose Congress.gov record names a transcript jacket whose MODS record lists witnesses | The witnesses attach to the meeting, one `witness_key` each; the meeting's `transcripts` gives the transcript's list row |
| S2 | A joint (`NoChamber`) meeting's jacket held only as a `jhrg` package, and jacket 49104057 held as `CHRG-118shrg049104057` | Both resolve; the meeting's `chamber` is null |
| S2 | A Senate meeting video and a House YouTube video | `video_key`s `senate:{filename}` and `youtube:{id}` |
| S2 | A bill with one floor vote naming it and one named only in its actions; a nomination with a hearing, a cloture vote and a confirmation vote; one confirmed by voice vote | Two `floor_votes`, basis `vote_record` then `bill_action`; the nomination's two votes in order; the voice vote only in `latest_action_text` |
| S2 | An older recovery line with no category and no `recovery_evidence`, recovering a link a document was fetched from | Kind from its match basis; original link and import date from its fallbacks; one source file for its original link |
| S2 | A dead link pasted as `http://www.…/a.pdf/` for a document fetched from `https://…/a.pdf` | One lookup key finds it |
| S2 | A committee renamed on a boundary day; two subcommittees sharing a name | The half-open interval gives one name per day; `committee_keys` keep them apart |
| S2 | A bill named by a filename and by a meeting's related items | One `bill_id`; both find its title, sponsor and stage in the pinned `congress_bills` |
| S2 | A publish after spicy-regs moves a family's pointer | The new generation is pinned, recorded in `inputs/`, and changes the input identity |
| S2 | A kept release whose bills generation is four generations old | Spicy-regs' retention plan keeps it, citing the archive's pin list |
| S2 | A file named only by its download header; a URL with `?file=a.pdf&name=b.pdf` | The header's name (`filename*` first); `a.pdf` |
| S2 | An exact copy and a provider's saved-text copy at one URL | The exact copy is the saved file |
| S2 | A file whose kind only the publisher gives, by `doc_type`, and another by link text only | Each gets the publisher-kind registry's kind |
| S2 | A committee-removed document; one removed and later re-added | `removed_on` set; null |
| S2 | A meeting named only by a GovInfo MODS record; a meeting with no record | The package's source files carry the meeting; the meeting is listed by key with null details |
| S2 | A `Retry-After` beyond the family's recheck interval; a URL whose latest line has no time | `next_attempt_at` capped at the interval; due now |
| S2 | An API list URL whose latest attempt failed after a good fetch | The relist window starts at `last_good_at` |
| S2 | A queue link carrying a credential parameter | The queue row has it removed |
| S2 | A recovery at an edition-ambiguous link; a recovery import for a linked URL never fetched | A document of its own each; the URL enters the queue |
| S2 | A recovery-only link that later downloads | Its link URL key opens the document that now holds the download, where the recovery attaches |
| S2 | Two recoveries equal in kind, time and body; decisions that match one recovery row twice; a recovery whose decision rejects it | Both shown, in receipt order; one recovery, from the latest decision; no recovery |
| S2 | Two merged documents with different title overrides; two active merges on one document; a hide and its withdrawal | The latest override by `(decided_at, id)`; both merges applied; visible again |

- **The labeled sample** sets the page thresholds and the final file-shape list. It is the sample of [[ARCHITECTURE]] §15, item 2, and its rubric is [[ARCHITECTURE]] §9.2–9.3.
  - It is a hand-labeled stratified sample of a few hundred files, starting from the responses already labeled by hand and the 2026-10-25 short-page sample ([[BINDINGS]] §4).
  - It covers short real pages, challenge, soft-error and download pages, archive members, landing pages, listing pages, files listed together on one page and widely mirrored real documents.
  - It includes a listing page captured in two places and pages whose links sit outside any list item.
- **The edition count**, for the owner's decision:
  - every real body that shares a rendition group with a body in `edition_bodies` and is not itself a fingerprint candidate is fingerprinted (*est.* about 15 bodies and 1.4 MB by the same-stem groups; publisher groups are counted again after D2's link backfill), and the count is of those whose text equals such a body's;
  - S reports the count with examples; the owner then decides whether to widen the candidates to every rendition-group member (*est.* 8–45 GB of reads once).
- **The raw-only check:** every rule can be computed from raw, with nothing borrowed from the old derived tables.

### 5.4 F0: The First Release, Converted From the Pinned Catalog

- A converter writes the pinned catalog pair in the release format ([[DATA-MODEL]] §8.1) with the final writer settings. It uses the engine's RunSpec where it can.
- This release is the reader's fixture (track A). Its manifest records that it came from the pinned catalog. It does not go live: the explorer waits for the engine-built release.
- **It fills what it can:** meeting keys from URLs, document dates from the old metadata, link labels from the old occurrences, and committee names from today's committee file. It keeps all 1.24M of today's catalog rows, so it is about twice the target `list`.
- **It cannot show** format groups, meeting titles, other versions or the new recovery kinds, so a small hand-built fixture release covers them: one document with PDF and XML alternates, one titled hearing in `meetings`, two versions of one address, one of each recovery kind and one hidden document. The contract test runs both.
- **It assumes nothing unique about old bodies:** 141,762 body keys appear in several old documents, so F0 resolves each link key to the first document in list order.
- The converter is a migration tool, deleted at the switch.

## 6. Tracks

[[BINDINGS]] §3 says which existing code is bound to each component and what changes.

### 6.1 Track A: Reader, Canary and Site

1. **Reader** to [[ARCHITECTURE]] §11, with hyparquet's `useOffsetIndex` for `detail` ([[ARCHITECTURE]] §11.1) and `usePageIndex` for `links`.
2. **Links** resolve through `links` ([[ARCHITECTURE]] §10.1).
3. **Canary** ([[ARCHITECTURE]] §10.3.5), run by the publish job against the uploaded candidate.
4. **Contract test** ([[ARCHITECTURE]] §15, item 5), against F0 and the hand-built fixture until track E exists.
5. **Saved copies** ([[ARCHITECTURE]] §11.5).
6. **Dates:** the document date and capture date in list rows, so same-filename editions read apart; on the document page, the labels of [[ARCHITECTURE]] §11.6.
7. **Recoveries** ([[ARCHITECTURE]] §11.5; [[DATA-MODEL]] §8.1), each on the page the attachment rule gives it.
8. **Sources:** where the document was published and which page listed it, from `sources`.
9. **Connections** (phase 2, except hearing keys and versions): filter by hearing, bill, member and witness, and sort by document date; a hearing's witnesses with what each submitted, its status, sittings and recordings; a document's other versions; a member's terms, committees, appearances and documents; a committee's current roster, hearings and documents; a bill's title, sponsor, status, hearings and documents; link out to the GPO record, the bill and the member.
10. **Removed by review** ([[DATA-MODEL]] §7.9).
11. **Speed, measured then fixed:** measure startup, search, detail and heap on real phones and desktops with F0, then write those targets into the canary and contract test. F0's size makes these targets conservative; re-measure on the first engine-built release.

**Done when:** the site loads F0 locally on desktop and in a phone-sized profile, and the canary passes against F0 in under a minute.

### 6.2 Track B: Raw-Writer Components

These components survive, so they are bound now.

0. **Clean the older receipts, once, before `receipts/` is locked** ([[DATA-MODEL]] §5.2). A full scan on 2026-10-25 found 534,733 recorded cookies on 242,438 lines and local paths in many fields, including 279,549 absolute `file_references[].original_path` values.
   - **First, stop the old writers adding more:** today's capture and import writers drop cookies, credential parameters and local paths. No import runs between the cleanup and the lock on `receipts/`.
     - 241,328 of the 530,081 lines in the mirror's last two weeks, 2026-10-03 to 2026-10-16, carry a `Set-Cookie`, and the newest import runs a path on every line.
   - **The fields:** the read-only scan lists, by field, the values that look like local paths, including paths inside JSON key names.
     - Its list is committed with B0, the owner confirms it before the run, and no other field is touched.
     - The input is the receipt keys in the 2026-10-24 backup plus any written since; each receipt not in the backup is copied into it before it is rewritten.
   - **The tool** is a one-off rewriter outside the body store, with its own credential, deleted once B0 is verified. The body store stays create-only throughout.
   - **The run,** for each receipt without a verification record:
     1. write the cleaned bytes to the same key with `If-Match` on the original ETag and `Content-MD5`;
     2. re-read it and check that every line equals the original minus exactly the listed values and key names, that no recorded URL changed except by losing a credential parameter, that no `links[]` value changed, and that every `pointer` still resolves to the same entry (a listed key that a `pointer` passes through is left uncut and reported to the owner);
     3. record the result, with the fields [[DATA-MODEL]] §5.3 lists, in a few batched verification files.

     A rerun skips receipts already recorded, and after a crash it verifies against the backup's original.
   - **Done when:** every receipt under `receipts/` has a verification record and a re-scan finds no cookie, credential parameter or local path in the listed fields.
1. **Bucket lock** (owner), per prefix: `bodies/` and `provenance/` at once, `receipts/` after B0.
2. **Fetcher, receipt writer and archive expander** to [[ARCHITECTURE]] §7.1–7.2 and [[DATA-MODEL]] §5.2, proven by their contract suites.
3. **One body store.**
   - Write the refusal matrix first, as the body store's contract test: a write that is not create-only under `bodies/`, `receipts/` or `provenance/`, or a receipt line with a credential parameter in a recorded URL, is refused before any I/O.
   - Then bind one body store with an R2 adapter and a local-disk adapter, and route every raw write through it, including the writers that lay out bodies themselves.
4. **Ingest policy set once,** where capture builds its store. The raw-intake exclusion gate is deleted.
5. **Body existence by key** ([[ARCHITECTURE]] §7.1), never by an index lookup.
6. **Code identity for receipt writers and recovery imports:** the commit (HEAD of a clean tree) plus the SHA-256 of `uv.lock`, refusing uncommitted application code.
7. **Recovery importer:** reconcile `accepted.json` with the receipts, so recoveries become provenance records the model reads, each with its kind.
   - New imports write date-shaped receipts with their recovery category, and provenance, through the receipt writer and the body store, with no guards or upload loop of their own.
   - Six accepted recoveries attach a 2-page excerpt to full 95–196-page transcripts; the owner reviews them, and each one confirmed wrong gets a `rejected` decision.
8. **Review recorder:** the review forms record provenance verdicts that target link keys ([[DATA-MODEL]] §5.3, §7.9). The 86 published assistant reviews of document kinds carry over as `kind_override` records on their files' link keys, with the assistant as reviewer.
9. **Raw verifier** ([[ARCHITECTURE]] §7.4, §10.3.7), in the maintenance job, first run after B10. It joins to the old capture index until D1 exists.
10. **The one-time full re-hash** (phase 2; [[ARCHITECTURE]] §7.4), after B13, skipping the keys B13 and phase 1's whole reads verified. Until then one listing gives each older body's verification baseline ([[DATA-MODEL]] §5.3).
11. **A ratchet test:** no test-only branch or test-only input substitution may appear in a surviving component; tests inject adapters instead ([[ARCHITECTURE]] §15, item 7).
12. **Owed while the old capture path runs:** repair wrong `stored_sha256` index rows in place, and confirm the daily capture writes correct values. These matter only until the switch.
13. **Uncompressed copies of older gzip PDFs** (phase 2; after B1 and B3), by the PDF copier of [[BINDINGS]] §3.1. Running it before B10 saves B10 about 365 GB of reads.
    - **Candidates:** older bodies whose media type or the old catalog's sniff says PDF (about 261,125). A copy is written only when the decompressed bytes begin `%PDF-` (about 950 candidates are HTML by the readings sniff; the test decides the 33,369 never sniffed).
    - **Size:** the largest raw write in the plan, so the lock and the refusal matrix come first: about 260,175 uploads and 403 GB once decompressed (about $72 a year of storage under the lock).
14. **Re-fetch the cut-off files** (phase 2; after B2, through the spooled fetcher): every URL with a copy cut off at 64 MiB and no complete 2xx copy, 62 to 64 by the snapshot index depending on how a complete copy is counted; the receipts decide. The cut-off copies stay in raw.
15. **Meeting fetches through the fetcher** (phase 2) like every other fetch: the Congress.gov meeting API, the House meeting and witness-list XML, Senate committee hearing pages and the meeting inventories; committees come from spicy-regs ([[DATA-MODEL]] §6.4) ([[ARCHITECTURE]] §7.2, §8.5; [[DATA-MODEL]] §6.5). An incremental relist takes its window from the `last_good_at` of the API list URL it pages through, and pages to the end of the list.
16. **Fetch the wrapped files** (phase 2; after D2, from the wrapper pages' `html` readings): the file links of download-wrapper pages, *est.* 8,800 testimony and statement PDFs that were never fetched, ahead of the model's queue.

**Done when:**
- every older receipt is cleaned and verified;
- the refusal matrix passes;
- the lock is on all three prefixes;
- one capture run's `stored` lines carry MD5s that match the stored ETags, and every line carries its stored suffix;
- every older body has a verification record, a listing baseline at least;
- in phase 2, every older gzip PDF has a recorded copy and every cut-off URL a complete copy or a recorded reason.

### 6.3 Track C: Engine

**C0, first moves on engine main** (beside M1): the C0 cleanup of [[BINDINGS]] §3.3. The engine's digest for every runner OS, Linux included, is recorded and checked as [[ARCHITECTURE]] §12 says.

**Then the capabilities of [[ARCHITECTURE]] §13, C*n* being its item *n*, each with its contract test:**

| # | Capability | Contract test |
|---|---|---|
| C1 | Multi-input SQL jobs | A job joining two tables, a file and a receipt holding a type conflict, read whole with the value nulled and its raw line kept; a partition filter visible in the Iceberg scan |
| C2 | Table operations | M1's commit and drop tests |
| C3 | Deterministic export (spicy-stack ss-iwqu) | Byte equality across threads, input orders, batch sizes and a forced spill; after a row group's first view through the reader's byte cache, a `detail` view is one round trip |
| C4 | Connected components (ss-6jg6) | M2's graph within its heap budget, labels equal across threads and input orders; a refusal test |
| C5 | Streaming I/O | Request counts in a test |
| C6 | Bounded resources | A join at the pool limit fails clearly; M2's build sizes; every hash-join build `EXPLAIN` shows is the smaller input and carries no wide column |
| C7 | Thin interface | The M2 export as a job spec |
| C8 | URL and JSON functions (ss-7qz3, ss-e53d) | The WHATWG URL test suite and golden vectors from today's fetcher's URL handling; `json_array` against Python `json.dumps`; M2's `url_key` timing |

**Not needed any more:** the lifecycle store's commit requirements, lifecycle-store compaction on R2, copy-on-write measurement and insert-if-absent. Close them unless another consumer needs them.

**Done when:** one CLI job runs the full export from Basin tables on the smallest runner and passes C3's test.

### 6.4 Track D: Lake Producers

Each producer is built to [[ARCHITECTURE]] §8 and [[DATA-MODEL]] §6.

1. **Captures ingest:**
   - backfill from all 2,289 receipts (1.08 GB compressed), including the non-date segments ([[ARCHITECTURE]] §7.2), with a test sample of each older receipt shape ([[DATA-MODEL]] §6.1);
   - the backfill restores the HTTP status on the about 37,000 bodiless lines that record one (`http_status` or `status_code`; `capture_status` and `meetingStatus` are not HTTP statuses);
   - it maps a fetch time from every receipt shape: 522,448 rows in dated receipts have no time in the snapshot, and 500,689 of them carry one on their own entry or line;
   - the rebuild-equivalence test;
   - **compare with the pinned old capture index** (3,909,134 rows) on receipt-derived columns, with written transformation rules for the expected differences:
     - statuses restored on bodiless lines;
     - the 5,587 lines of the 2026-10-15 recovery run read as recoveries rather than fetches;
     - completeness per attempt;
     - `stored_md5` and `stored_suffix` new, `stored_sha256` gone.

     A row that exists only in the old index is a fact raw does not hold, and it blocks the switch until the owner decides (§8).
2. **Parsers:**
   - first `sniff` over every older body: about 1.04M short ranged GETs, timed in the run; a PDF's integrity is borrowed where §2 says, and only about 18,600 PDFs are read whole;
   - then the main-content extractor, chosen by measurement on the ~2,250 pages saved twice in one fetch and on the labeled sample;
   - then HTML, XML and JSON (about 5 GB), with the table's size (links and `text_head` included) measured. There is no PDF parser for now;
   - then `fingerprint` for the other candidates, measured here;
   - then M2's link join and grouping, repeated on the real links and fingerprints.
3. **Filename reader:** a producer that runs the filename parser over its work list and appends through the engine.
4. **Meeting parsers** (phase 2; needs B15): once per input and version, over the meeting-source registry's work list, with completion rows:
   - Congress.gov records, the 199,156 inline receipt records (18,140 meetings, keyed by `record_sha`) and response bodies alike, and House `committee-meeting` XML, into `meeting_records`;
   - House witness lists, Congress.gov records, Senate hearing page cards and the `mods.xml` records already in raw into `appearance_records`, each witness with its name key and document links.
5. Enable Basin's catalog-level compaction and snapshot expiration.

**Done when:** every lake table exists with complete backfills at the pinned versions, and both `captures` comparisons pass.

### 6.5 Track E: Model

1. **The rules, written in S** (§5.3). The file-shape list starts from the broader list; the roughly 27k bodies between it and the narrow list (16,775) are sampled before it is fixed.
   - The broader list has 44,047 file-shaped bodies: the narrow list's `.pdf`, `.zip`, `.doc`, `.docx`, `.xml`, `/download/`, `download=1` and `file_id=`, plus `/files/`, `/uploadedfiles/`, `/media/doc/` and more extensions.
2. **The model SQL:** every relation and release file of [[DATA-MODEL]] §7–8, with the invariants of §10 as its test suite.
3. **Golden vectors** for `source_id` and `document_id`, generated from today's ID code with its compact-JSON serialization and checked in the engine's tests.
4. **Parity against the pinned catalog pair**, the oracle (not F0, which picks one document per shared body), on browser-visible fields, compared many-to-many and keyed by source evidence: the files and URLs each document holds. IDs match today's wherever their inputs match.
   - **Expected, explained changes:**
     - about 615k catalog rows (captions, metadata records, playlists and API responses; [[DATA-MODEL]] §7.5) and the listing pages leave the list;
     - documents lose soft-error and wrapper pages, and about 4,900 lose Senate landing pages, from their body sets, while short real pages and real web pages now count;
     - cut-off copies, damaged PDFs and pages whose reading failed (reported by format and error type) drop out of body sets, and feed pages become listings;
     - the 3,690 recovered files that a real fetch also saved become real bodies;
     - about 2,250 pages saved twice in one fetch (a direct attempt and a provider retry) merge by main content, and 999 veterans.house.gov pages from the End of Term archive gain their webharvest.gov copies as attached recoveries;
     - document kinds now also come from the publisher's link labels where the filename gives none;
     - a file's name comes from each capture row, download header first: about 95,000 files carry a download-header name and change `source_id`, and a body offered several names keeps one source file per name in one document;
     - about 460,000 rows today named only from `download_state` are saved-text duplicates of exact copies at the same URL, and collapse into their twins; where a URL's copies differ (532 URLs), the exact copy becomes the saved file;
     - about 34,100 GovInfo ZIP groups and about 560 same-stem groups merge; the old catalog's about 19,500 multi-format same-stem groups were mostly (about 17,400) PDFs paired with one docs.house.gov 404 body saved at `.xml` URLs, a placeholder that is no good fetch;
     - `document_id` keeps today's formula, but its inputs now include real web pages and untyped bodies;
     - source IDs change where B0 removed a credential parameter from a source URL;
     - link-label coverage changes, because labels now come from saved pages; labels that came only from scraper records inside receipts are their own cause;
     - capture dates change where receipts lack times.
   - **The comparison reports by cause, not by document:** each known cause has a checkable predicate, its count and a few reviewed examples, and every difference that fits no known cause is listed separately. Only that last group needs reading one by one.
   - **Classify each unexplained difference:** a rule change (fine, recorded with the rule); an old-pipeline error (the new model wins); or a fact that exists only in derived tables (a blocker, §8).

**Done when:** every known cause has its predicate, count and examples, every unexplained difference is classified with no blocker left, and the model runs as a CLI job on the smallest runner.

### 6.6 Track F: Publish Job, Capture Scheduler and Switch

1. **Workflows** ([[ARCHITECTURE]] §12): the capture job; the publish job, backfills and the maintenance job in one CI concurrency group. The disabled viewer workflow and its 30-minute cron are deleted.
2. **Capture scheduler:** capture reads `url_state` from the live release, including its queue of linked-but-unfetched URLs, stops reading the raw index, and drops its replay mode.
3. **The committee explorer** (phase 2) reads meeting and witness records from the lake and committees, members and rosters from the pinned spicy-regs generations ([[ARCHITECTURE]] §8.5), not from the fetchers' state files.
4. **Generation pins** (phase 2): publish and the maintenance job keep `pins/spicy-generations.json` and the receipt-key lists ([[ARCHITECTURE]] §10.3.4, §10.3.7). The spicy-regs side (its retention reading that list, `nomination_id`, the nominations backfill, and reading the archive's releases instead of capturing meetings) is spicy-stack ss-vhi2.
5. **Delete what is bound to nothing,** one PR per group as [[BINDINGS]] §6 lists them, measured again at cut.

**Done when** the switch checklist holds:
- the explorer serves an engine-built release, and the reader opens saved files, alternates and recoveries from it;
- the canary and contract test pass the speed targets set on real devices, against that release;
- a failed canary is shown to leave the previous release live;
- capture runs from `url_state` with no raw-index read;
- in phase 2, the committee explorer reads the lake, every older gzip PDF's copy is recorded (B13), and spicy-regs' retention plan keeps every generation a kept release pins;
- the old workflows are gone, and the deleted line counts are recorded.

## 7. Parked

- **news_lake** keeps the DocSpec backend and the engine's lifecycle store. No work until it adopts the three layers.
- **The freeze:** no browser or engine performance work beyond this plan until there is a user or a measured failure on real data.
- **Committee explorer and weekly retention onto incremental tables:** the approach conflicts with the design. Re-scope it before starting.
- **Considered, not chosen,** so not re-proposed without new information: showing the original link's last status (36,768 documents' URLs last returned 404 or 410), showing saved-file size (2,467 files over 50 MB), and saving resolved links between publishes (revisit only if a measured reprint shows link resolution is the slow step).
- **Parquet variant for the folds:** revisit when all three hold:
  - an iceberg-rust release writes variant through its Parquet writer (0.10.1, the pinned release, has none; 0.11 is expected to add it);
  - Basin Catalog accepts format-version 3 tables;
  - DataFusion core or a maintained crate can query variant.

  The candidates are nested, mixed-type readings such as Congress.gov API JSON and MODS or meeting XML trees.
- **Caption text as a spoken transcript:** the captions are linked by `video_key` and held in raw (99% of Senate meeting videos in the 118th–119th Congresses); assembling them into timestamped, searchable text is full-text work beside `pdf_text`.
- **Full-text extraction of every PDF:** one later read of about 403 GB into `pdf_text` ([[DATA-MODEL]] §6.6). It gives page counts and text fingerprints for every PDF, which makes dedupe across sites cheap to revisit.

## 8. Uncertainties and Tests

Each row names an unknown, the step that settles it and what it decides, and closes only with its measurement. The widest is the model (track E), bounded unless parity finds facts only derived tables hold.

| Uncertainty | Settled by | Decides |
|---|---|---|
| Basin compacts only files not yet compacted, so a table's file and manifest counts may grow with every run | M1 | Iceberg, or dated Parquet files with an `If-Match` manifest |
| DataFusion's wide joins, grouping and named steps fit the smallest runner's memory pool | M2, then D2 on real links | The model's step form and the size of track C |
| The receipt reader and ingest mapping read every older shape: 2.96M of 3.9M rows carry no outcome, 1,420 receipts mix types on a path, one line is 188 MB | M2's receipt step, then D1's comparison with the old index | The reader, the outcome and mode table, and any fact that exists only in derived tables (the owner records it as provenance or accepts losing it) |
| The rules give the right documents on real data, not only on fixtures and proxies | S1 on real slices; the labeled sample (S2) | Rule changes, the page thresholds and the final file-shape list |
| Re-packaged editions join the wrong XML | S2's edition count | The owner widens fingerprint candidates, or not |
| Which maintained extractor gives stable main content | D2, on the pages saved twice in one fetch | The `fingerprint` parser |
| How many links pages hold (*est.* 4.2M, from 80 pages) and how large the link join is | D2's link backfill | The link-join budget and M2's memory verdict |
| The 33,369 never-sniffed PDF candidates are PDFs | Phase 1's `sniff` | The copy count |
| Borrowed PDF checks agree with a fresh read (198,676 agree today, 3 disagree) | A sample read whole in phase 1 | Whether the borrowed basis stands |
| No older body beyond the 61 known has a multipart ETag | Phase 1's listing baseline | Nothing, unless the count changes |
| The numbers in the specifications reproduce: each review round found 10–20 of about 370 wrong | Each load-bearing number re-derived from its committed script before a rule relies on it | Corrections in place |
| Speed and heap targets on real phones and desktops | A11 | The canary's and contract test's thresholds |
| Whether `list` with titles fits the phone heap budget (*est.* 17–30 MB more; 46% of documents have a publisher label) | A11, on F0 | Titles stay in `list`, or move back to `detail` |
| Roster history: spicy-regs keeps the current Congress only | A spicy-regs change publishing its captured rosters as dated history | Rosters show current seats until then |
| How often one printed hearing covers several meetings, leaving its MODS witnesses on the package | D4, counting packages that more than one meeting's jackets resolve to | Whether multi-day hearings need a per-day rule |
| Whether the 123 `direct_official_package` import lines are recoveries or fetches | The owner, on S2's sample of them | Their kind, or a move into `mode = fetch` by the ingest mapping |
| Senate card coverage by committee site (judiciary 98.6%, hsgac 64.8%, indian 54.8%, jec 0%) | D4, on every Senate hearing page | Which sites need a second page layout |
| Event IDs never name two chambers (observed on 18,140, not promised by the publishers) | Invariant 16 at every publish | The meeting key, if one ever does |
| Nominations before the 119th Congress | spicy-stack ss-vhi2's backfill | How far back nomination pages reach |
| How often one witness gets two keys at one meeting (spelling, titles, initials) | A sample of House and Congress.gov witness lists in S2 | What the later witness table must match |

## 9. References

**[ARCHITECTURE]**
: *Congressional Document Archive: Architecture.* Editor's Draft, 2026-10-24. `docs/engine-first-architecture.md`.

**[DATA-MODEL]**
: *Congressional Document Archive: Data Model.* Editor's Draft, 2026-10-24. `docs/engine-first-data-model.md`.

**[BINDINGS]**
: *Congressional Document Archive: Implementation Bindings.* Note, 2026-10-25. `docs/plans/bindings-20261025.md`.
