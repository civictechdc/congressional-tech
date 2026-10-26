# Review 8: consolidated findings on docs/engine-first-data-model.md @ 33c2cba0

Four blind reviews (full text beside this file):
- trace: review8/trace/review.md (58/100)
- data: review8/data/review.md (70/100)
- reader: review8/reader/review.md (62/100)
- storage: review8/storage/review.md (71/100)

Each finding: ID, the claim as the reviewer states it, who raised it (reviewer and finding number), and DM lines at 33c2cba0.

## A. Raw and receipt shapes

- **A1.** Congress.gov meeting records are inline JSON in receipt lines (199,156 lines under `congress/meetings`; 198,946 reference no body; 15 committee-meeting JSON bodies exist), but `meeting_records`/`appearance_records` key on `body_sha` and invariant 5 ranges over responses. All Senate meeting records and the jacket numbers exist only inline. [data F1] DM §6.5 L360, L377–378; §6.7; inv 5.
- **A2.** Only 5,587 of 12,106 `retained_import` lines carry `acquisition.prior_access_category`; 839 carry `acquisition.category` and 5,542 only `acquisition.kind` (format values); 138 neither. §7.8 "a row with neither MUST fail the build" refuses the first publish unless ~6,519 decisions exist. [data F2, trace F6] §5.2 L166; §6.1 L246; §7.8 L722.
- **A3.** 4,286 of 12,106 import lines lack `recovery_evidence.original_url`, `imported_at` and `match_basis`; their link is in `record.source_associations[].original_url` (4,286) and `acquisition.original_url` (4,148); 138 have no original URL anywhere. `recoveries.imported_at` is typed non-null. [data F3, trace F6] §5.2 L163–165; §6.1; §7.8; §8.1.
- **A4.** `file_references[]` entries carry `original_path` as a retained-file local path on 522,501 entries (279,264 absolute); §5.2 says `original_path` appears only on archive members. [data F4] §5.2 L144; §6.1 L233.
- **A5.** Time fields the mapping does not name: `_retrieved_at` (Congress.gov meeting lines), `observed_at` (some Senate caption lines), `started_at`/`checked_at` (YouTube, MODS). 2,216,421 of 2,668,607 rows without `retrieved_at` carry no time at all; §7.5 L655's explanation is wrong. [data F6] §6.1 L259; §7.5 L655.
- **A6.** ~0.55M lines have neither `url` nor `requested_url`; 1.42M body rows carry no family in entry or record; both typed non-null. [data F9] §6.1 L227–228.
- **A7.** The older retry hint is `record.retry_later.delay_seconds` (79,112 lines, all 503), not a `Retry-After` header. [data F10] §6.1 L236.
- **A8.** On 11,950 of 12,106 import lines the capture row's `url` equals `acquisition.recovered_url` (the recovered copy's address), so §7.4 creates a bodied source file at the recovered URL and §7.8 adds a bodiless one at the original link: two source files per recovery-only document. Also §7.4 clause 3 (step 1) depends on attachment (step 4): circular. [trace F5, F9] §3 L67; §7.4 L567; §7.8 L723.
- **A9.** House witnesses are in a separate `witness-list` XML body (`HouseWitnessListXML`; family `house/witness-xml`, 14,471 index rows), not the `committee-meeting` body the current-record rule selects. [trace F7] §6.7; §7.11 L761–763.
- **A10.** `group_path` is a join key between `readings.links` and `appearance_records.document_group_paths` with no formula; no code computes one; old catalog groups are names. [trace F8] §6.2 L293; §6.7 L405; §7.11.
- **A11.** Meeting/appearance producers' work lists are named by publisher, not a computable predicate; MODS appearances have no completion marker; §6 says every non-PK column is nullable but §6.5 marks `congress`, `title`, `meeting_date`, `meeting_type` etc. non-null. [trace F10, F20; storage F9] §6 L210–214; §6.5; inv 4.
- **A12.** "A House meeting ID drops its four-letter prefix (HHRG, HMKP, HMTG)": House XML `meeting-id` values are all digits (0 of 15,707 prefixed). [trace F16] §7.5 L669–670.
- **A13.** `transcript_jackets list<int>` loses a leading zero: `CHRG-118shrg049104057` exists (1 of 34,576). [trace F13] §6.5 L373; §7.11 L753.
- **A14.** A Congress.gov XML response would classify as `document` (`api_row` requires json); 0 XML API URLs today. [trace F23] §7.3 L525.

## B. Keys and vocabularies

- **B1.** `witness_key` is `fsb(8)` in `witnesses.parquet` but a `List<dict>` string in `list.witness_keys`; invariant 16 joins them; `version_keys` says hex, `witness_key` does not. [trace F1, storage F6] §7.11 L759; §8.1 L814, L826; inv 16.
- **B2.** `chamber` has no vocabulary but is in `meeting_keys`, every `witness_key` hash and the witnesses→meetings join. Inputs: URLs lowercase `house`; Congress.gov `House`/`Senate`/`NoChamber`; spicy `committees` `House`/`Senate`/`Joint`, `committee_assignments`/`roll_call_votes` `house`/`senate`, `member_terms.term_type` `rep`/`sen`; code `house|senate|joint|unknown`. [trace F2, data F13, reader F16]
- **B3.** Nomination key `{congress}-pn-{number}[-{part}]`: spicy `nominations.part_number` zero-padded (`'02'`, `'00'` for none), `citation` unpadded (`PN730-2`); `roll_call_votes.documents` is a struct list (`type='PN'`, `number='129-10'`, `congress` null on 1,681 of 9,079 entries). [trace F3, data F8, reader F7]
- **B4.** `bill_vote_references` → `roll_call_votes` join unstated; `vote_id = congress-chamber-session-roll` joins 19,766/19,766. [trace F14, data F8]
- **B5.** One package ID spelled four ways: `gpo_package_id`, `govinfo_package_id`, `package_id`, `transcript_packages`. [reader F6]
- **B6.** Meeting key encoded two ways: `'chamber:event_id'` in `list.meeting_keys`, two columns in `meetings`/`witnesses`. [reader F16]
- **B7.** Three things named `members` (§7.6 document members, §7.11 spicy members, `members.parquet`). [trace F17]
- **B8.** `document_id`'s JSON shape (flat vs nested) ambiguous; engine nests. [storage F13]

## C. What the release files tell readers

- **C1.** `list` carries `committee_name`, every other file `system_code`; names collide (47 names across 2+ codes, "Oversight and Investigations Subcommittee" = 12 codes; 287 of 589 subcommittees have no `officialName`; 55 official names collide). Committee pages cannot find documents. Blocker. [reader F1, trace F19]
- **C2.** `witness_keys` from MODS attaches every printed-hearing witness to every file of the package as "submitted". [reader F4] §7.11 L764–768.
- **C3.** Senate witnesses never reach testimony: Senate committee pages are excluded as meeting sources; the old catalog attributed 12,663 documents to witnesses by name from Senate pages; 12,486 senate.gov documents have testimony-shaped filenames. [reader F5] §6.7 L408; §6.5 L377.
- **C4.** `meetings.transcript_packages` has no index to a `list` row; only ranged `detail.govinfo_package_id`. [reader F6]
- **C5.** `nominations.vote_id` single-valued; 1,552 of 2,155 nominations with Senate votes have ≥2 (cloture + confirmation). [trace F4, reader F8]
- **C6.** `bills.floor_votes` mixes votes on the bill and votes its actions name, without a basis. [reader F11]
- **C7.** `has_captions` promises captions the release does not publish; no lake column carries the caption join key. [reader F9, trace F22]
- **C8.** A dead link resolves only if it was a recovery's original link; no URL key for other source URLs. [reader F2] §8.2.
- **C9.** No `title` in `list`: search and listings show filenames only (`index.cfm` names 342 documents). [reader F3]
- **C10.** No chamber facet. [reader F12]
- **C11.** `url_state.parquet` and `capture_scope.json` are operational files in the reader release. [reader F14]
- **C12.** Unused publisher-stated spicy links: `nominations.hearings_json`, `committees_json`, `bill_committees`, `committee_reports`; `congress_bills.subjects` read but unused. [reader F13, trace F25]
- **C13.** `list_row` stored in `sources`/`recoveries` beside `detail` ranges. [reader F15]
- **C14.** `detail` has no size estimate. [reader F17]
- **C15.** No derivation for `list.filename`, `review_note`, `review_decided_at`; `document_kind` ignores `kind_override`; invariant 16 fails after a legitimate `duplicate_of` merge at one endpoint. [trace F18, F21, F11]
- **C16.** Type mismatches: `rosters.rank` int16 vs spicy string; `term_type` rep/sen unmapped; `members.name` join rule; nullable `govinfo_package_id`/`identity_note`; `sittings.place` concatenation; which `facts` are dates. [trace F24]

## D. Engine and determinism

- **D1.** Neither DataFusion 53.1 nor docspec-rs has a compact-JSON encoder (needed by `source_id`, `document_id`, `version_keys`, `witness_key`) or URL resolution/normalization; the JSON encoder is not in ARCHITECTURE §13. ConnectedComponents reads only a pinned dataset, requires Utf8 keys, and computes `document_id` itself (`connected_components.rs:27-36, 93-155`). [storage F1]
- **D2.** Release bytes depend on unpinned engine limits (threads, batch rows, batch bytes); export flushes by bytes and writes batches as they arrive (`export/pipeline.rs:556-613`); writer settings differ from §8.1. [storage F2; data claim 60]
- **D3.** Picks without a total order: `committee_name` (12 overlapping `officialName` intervals in spicy `committees`), `govinfo_package_id`, saved-file `fidelity`, `first_fetched`/`last_fetched`, split link index. [storage F3]
- **D4.** `next_attempt_at` age bands may be measured against the publish clock. [storage F4]
- **D5.** ts→date32 time zone unstated; spicy dates are UTC instants of Eastern midnight (1,606 of 1,839 history dates at 04–05 UTC). [storage F5]
- **D6.** §6 lake writer settings unenforceable: engine row-group cap 8,192; Basin compaction rewrites; iceberg-rust 0.10.1 ignores `write.parquet.compression-*` and does not implement `delete-after-commit`; sort clause unenforced. [storage F7]
- **D7.** A kept release cannot be rebuilt after Basin expires pinned snapshots (30 days); receipt set stored only as a digest. [storage F8]
- **D8.** Lake PK uniqueness never enforced. [storage F10]
- **D9.** One input that always fails operationally blocks every publish. [storage F11]
- **D10.** Dictionary on unique-key columns; float compare in `listing_signs`; parser versions kept forever. [storage F14–F16]
- **D11.** Engine ConnectedComponents uses a String-keyed union-find (`topology.rs:86-132`), est. 1–2 GB at ~4M tokens, vs ARCHITECTURE §13.4's "dense integer IDs, 32 MB". [storage, scaling note]

## E. Document integrity and numbers

- **E1.** Stray code fence at L784 renders §7.11's notes, all of §8 and the §9 heading as one code block. [all four] (Confirmed by the lead; introduced by the lead's §7.11 edit in 33c2cba0.)
- **E2.** CBO estimates are 913–1,666 per Congress from the 108th, not 1,100–1,700. [data F7] §6.4 L347.
- **E3.** Placeholder threshold: 20 at k=50 and 11 at k=200, not 22 and 12. [data F11] §7.3 L550.
- **E4.** Cross-references: L73 "(§7.3)" should be §6.2; L885 "committee records" no longer exist; L828 "a document's ID … stay in the lake" vs `document_id` persisted nowhere; "F0" unexplained; `is_saved` with several member paths. [trace F26]
- **E5.** 16 of 422,011 `congress_bills.bill_id` do not match `^\d+-[a-z]+-\d+$` (e.g. `cen_doc_h`). [trace F26]
- **E6.** `file_references[]` reaches 22,354 per line; one bodiless file reference. [data F12]
