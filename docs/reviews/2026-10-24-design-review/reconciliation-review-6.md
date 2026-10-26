# Reconciliation: the fresh review round of 2026-10-25

Six reviewers read a frozen copy of the four documents cold: Codex, the spec reviewer, the systems professor, the editor, the Iceberg/Parquet reviewer and the bindings reviewer. The frozen copy was HEAD (`4e75b069`) plus an uncommitted concision pass, taken before the 64 restore edits. This file merges their findings, groups them by root cause and records how each was validated. The pass of 2026-10-25 applied it, with the owner's five decisions: lake schema changes rebuild, near-duplicate pages compare main content, short pages are judged by what they say and their wrapped files are fetched, the relist stays incremental, and `Retry-After` is capped at the recheck interval.

**Who found it:** Cx Codex, Sp spec reviewer, Pr professor, Ed editor, Ic Iceberg/Parquet, Bi bindings.
**Verdict:** ✓ confirmed by data, ⚙ confirmed in code or vendor docs, 📄 confirmed in the current text, ◐ partly, ✗ refuted, ✔ already fixed.

## Scores

| Reviewer | Verdict | Score |
|---|---|---|
| Bindings | Approve with changes | 85 |
| Editor | Sound and close | 78 |
| Professor | Three small edits away | 77 |
| Iceberg/Parquet | Build after two fixes | 75 |
| Spec reviewer | Raw track can start; model not yet | 74 |
| Codex | Not ready (architecture 70, plan 77) | 73.5 |
| **Mean** | | **77** |

About 146 raw findings reduce to about 70.

## How it was validated

Five validation passes ran on real data, code and history, each in its own folder under the session scratchpad:

- **Receipt scan** (all 2,289 receipt files, 2,596,054 lines, from the local mirror): credentials, local paths, cookies, declared lengths.
- **Page versions** (3,750 addresses, 1,123 sampled, 2,177 bodies fetched): whether documents change at one URL.
- **Short pages** (89,730 successful HTML bodies, 3,021 fetched, 289 read by hand): what pages under 2 KB of visible text are.
- **Data findings** (nine reasoned findings re-measured over every receipt line).
- **Code claims** (eleven claims re-read against the pinned sources) and **text and history** (32 reasoned text findings, three root causes, against the current documents and git).

## Patterns and verdicts

### 1. A rule changed without re-checking the rules that read it

| # | Finding | Who | Verdict | Evidence | Proposal |
|---|---|---|---|---|---|
| 1.1 | Cleanup removes credential parameters yet says every URL stayed byte-identical | Cx, Pr | 📄 | No real credential exists in any receipt; the only `key=` (3,944,944 YouTube caption URLs) is one 3-character constant | "A recorded URL changes only by losing a registry credential parameter"; bare `key` stays out of the registry; no key rotation |
| 1.2 | `copy_urls` lets a ZIP link match its members | Cx, Sp | ◐ | 34,319 GovInfo ZIPs are linked; 34,095 hold one hearing's same-named HTML and PDF, a wanted merge; about 104 hold other mixes | Define the source URL (2.1); link joins match endpoints `(url_key, member_path)`, then expand |
| 1.3 | `complete` needs a declared length | Sp, Cx | ✓ | Of 58,230 successful HTML lines, 62% declare no length and 99.97% are content-encoded, so a declared length is the compressed size | Complete = the transport signalled the entity's end without error and decoding succeeded; judged per attempt (1.11) |
| 1.4 | A honors `Retry-After` across runs; DM caps it | Cx | 📄 | — | Owner chose the cap: A says the deadline is honored within the family's recheck interval |
| 1.5 | Filename and recovery pick a decision by different rules | Cx, Sp | 📄 | — | One decision (§7.8), matched on the exact original URL and body |
| 1.6 | A recovered file later fetched normally collides with "recovery bodies are never keys" | Cx, Sp | ✓ | 3,558 of 11,044 recovered files (32%) also arrived in a normal 2xx fetch | A recovery alone never makes a real file or key; a qualifying fetch of the same bytes does |
| 1.7 | Columns added inside a list element are unreadable | Ic | ⚙ | Also: added root columns of list, map, fixed, time or uuid type are unreadable over old files; only primitive or struct roots fill with null | Owner question (schema growth) |
| 1.8 | The sniff tail read assumes a `.pdf` copy | Cx, Pr | 📄 | — | Read the tail of the recorded uncompressed object or verified copy; a gzip PDF with no copy is `intact = false` |
| 1.9 | The recovery-kind fallback "goes" once imports carry categories | Cx, Ed | 📄 | Older receipts are immutable | The fallback is permanent |
| 1.10 | Completion rows for "every producer" | Ed | ✔ | Fixed by the restore edits | — |
| 1.11 | **New:** `complete` is a line field, so a cut-off attempt inherits its line's flag | (validation) | ✓ | 126 of 135 non-HTML addresses with two bodies are a cut-off direct attempt plus a complete provider retry in one fetch; per attempt, the disputed addresses fall from 135 to 8; 13 of 67 cut-off PDFs still end in `%%EOF` | `complete` per capture entry; this also closes the `intact` hole for truncated PDFs |

Root-cause test (history): 8 to 9 of pattern 1's 10 findings were introduced by `4e75b069` or the concision pass; across all must-fixes the share is 36–44%.

### 2. Core terms undefined or overloaded

| # | Finding | Who | Verdict | Proposal |
|---|---|---|---|---|
| 2.1 | "Source URL" undefined (18 uses) | Sp | 📄 | Final URL of a top-level row; null for an archive member |
| 2.2 | Record role has three grains | Sp | 📄 | Per capture row; a body is real when any row is a real file |
| 2.3 | "Meeting page" undefined; "up to 9 meetings" | Sp | ✓ the 270 maximum is the House `Error.aspx?Code=404` page, which is never listed | Define meeting page by the two meeting URL patterns or a House meeting XML record; drop the number |
| 2.4 | "Candidate" defined only in passing | Ed | ◐ | Define "fingerprint candidate" once |
| 2.5 | "Import row" vs "import run" | Ed | 📄 14 uses, never defined | "Recovery row" |
| 2.6 | "Catalog" in three senses | Ed | 📄 | A terminology entry for "catalog version"; no rename |
| 2.7 | `n_members`/`member_count`; five names for the weekly job; "contested edition" | Ed | 📄 | One name each |
| 2.8 | Nullability incomplete; no empty-filename fallback | Cx, Sp | 📄 | Complete the tables; fallback `''` |
| 2.9 | List and fold order unfixed | Sp, Cx | 📄 | One ordering sentence |
| 2.10 | `saved_media_type` has no derivation | Sp | 📄 | A fixed map from the saved format, else the capture's media type |
| 2.11 | "Recovery body", "older line", "creating line" undefined | (validation) | 📄 | Define or replace |

### 3. Platform behavior and today's code (rebuild, don't adapt broken patterns)

| # | Finding | Who | Verdict | Proposal |
|---|---|---|---|---|
| 3.1 | DataFusion inlines CTEs; its cache sits outside the memory pool | Pr, Ic | ⚙ | One job of named steps; components and documents held once in the pool; M2 measures both forms |
| 3.2 | Default dictionary pages put about 1.4–1.8 MB under each ranged read; docspec writers also disable the offset index | Ic | ✓ ⚙ | Dictionaries only on `dict` columns; an offset index on every leaf of ranged and lookup files; detail estimate 100–200 KB |
| 3.3 | M1 cannot see compaction growth | Ic | ⚙ | Ten or more maintenance runs at the shortest expiration; count data files and manifests; drop with purge |
| 3.4 | iceberg-rust rebases a stale commit | Ic | ⚙ | "Every commit asserts the snapshot its work list was read at"; the engine's guard is the mechanism |
| 3.5 | Basin ignores `write.target-file-size-bytes` | Ic | ⚙ (vendor docs) | Delete it; catalog-level maintenance |
| 3.6 | Join build side chosen by statistics; builds cannot spill | Ic | ⚙ | The engine builds the side the plan names |
| 3.7 | The engine's table reader pushes no filters and reads serially | Ic | ⚙ | Rebuild C1 on filter pushdown (iceberg-datafusion's static provider does it) |
| 3.8 | The fetcher's scope check is a denylist that refuses the API hosts; the provider path checks only the first URL; API clients bypass it | Bi | ◐ ⚙ | Rebuild: the capture-scope registry as an allowlist, checked on every hop of every transport |
| 3.9 | `put_file` returns only true or false, discards its MD5, and re-downloads on a 412 | Bi | ⚙ | Rebuild the body store: outcome, suffix, MD5 and size; a 412 is `unchanged` with no download |
| 3.10 | The local-disk adapter can leave a partial file | Cx | ✓ | Write a temporary file, then link it into place without replacing |
| 3.11 | ZIP handling loads whole archives; ODF found by name or media type; redirect loop follows 5, not 6 | Bi | ⚙ | Rebuild: stream from the spooled file, detect Office packages by content, count six redirects |

### 4. Raw safety while the old system keeps running

| # | Finding | Who | Verdict | Evidence | Proposal |
|---|---|---|---|---|---|
| 4.1 | The old writers keep writing cookies and paths | Sp | ✓ | 241,328 of 530,081 lines in the last two weeks carry a `Set-Cookie`; the newest import runs carry a path on every line | Patch the old writers first; no imports between B0 and the lock |
| 4.2 | Receipts written after the backup have no original | Cx, Pr | 📄 | — | Copy each into the backup before rewriting it |
| 4.3 | B0's field list | (validation) | ✓ | 40+ path fields across all receipts, some inside key names; 85 path and 15 cookie locations in the last two weeks alone | The read-only scan's full list, key names included, confirmed by the owner |
| 4.4 | A 412 on a receipt or provenance write | Pr | 📄 (silence) | — | Run IDs are never reused; a 412 there fails the run |
| 4.5 | B13 trusts an existing `.pdf` copy | Cx | 📄 | — | Compare the existing ETag with the expected MD5 |
| 4.6 | B14 runs on the capped old path | Pr, Sp | 📄 | — | B14 after B2's spooled fetch |
| 4.7 | The first weekly check would re-hash everything | Pr | ✓ | No receipt records an MD5: all 1,036,256 bodies (0.696 TB) | The full re-hash (B10) runs before the first weekly check |
| 4.8 | Invariant 2's multipart clause | Pr | ✗ | The cited multipart path is the engine's release upload; body writers never use it | No change |
| 4.9 | **New:** six recoveries attach a 2-page excerpt to full 95–196-page transcripts by "accepted URL variant" | (validation) | ✓ | — | Owner review; a `rejected` recovery decision drops each one confirmed wrong (a `withdraw` retracts only a review) |

### 5. Determinism, evaluation order and scheduling

| # | Finding | Who | Verdict | Evidence | Proposal |
|---|---|---|---|---|---|
| 5.1 | Provenance not frozen with the snapshots | Cx | 📄 | — | Pin provenance keys and ETags with the snapshots |
| 5.2 | A failed sniff falls through to `document`; a transient error becomes permanent | Pr, Cx | 📄 | — | Null role for a missing or failed sniff; operational failures leave work open |
| 5.3 | Recovery attachment, recovery link keys and component order form a cycle | Cx | ◐ | Reviews are ordered; the recovery cycle is not | State the order |
| 5.4 | Backfills outside the concurrency group; a registry change can balloon the fingerprint step | Pr | ✓ 9,523 bodies, 89 GB ceiling | — | Backfills join the group; an over-budget step runs as a backfill and publish refuses early |
| 5.5 | Null `last_attempt` makes old URLs due at once | Sp | ✓ | 19,316 requested URLs have no time on their latest attempt | Define `next_attempt_at` for a null `last_attempt` |
| 5.6 | The incremental relist needs the last good fetch | Cx | ✓ | A full relist is about 110 requests (90 meeting pages, about 20 committee pages) | Owner question: relist fully each run |
| 5.7 | The 404 reload can loop | Pr | 📄 | — | Re-read once; the same release means not found |
| 5.8 | First publish has no pointer; a meeting can be referenced before its record | Cx | 📄 | — | Conditional create; keep the key with null metadata |
| 5.9 | **New:** timeless rows in dated receipts | Pr | ✓ | 522,448 in dated receipts; 47,359 have a time on the line that the snapshot dropped | D1 checks every receipt shape |

### 6. Restatement and drift (editorial)

| # | Finding | Who | Verdict |
|---|---|---|---|
| 6.1 | A §9 restates DM §7 and has drifted | Ed | 📄 |
| 6.2 | The plan restates contracts (A1, A3, A5, A6, A10, B2, B13, C0, the C table, D2) | Ed | ◐ partly fixed by the restore |
| 6.3 | Registry contents copied into DM | Ed | 📄 |
| 6.4 | Other second homes; new drift: A §16.2 says M2 tests determinism, P §5.2 moved it to C3 | Ed, (validation) | ◐ |
| 6.5 | Fourteen appended clauses | Ed | 📄 |

The editor estimates 2,371 words saved. Root-cause test (history): the documents grew in almost every fix round (A+DM+P +28% from `c3b067c4` to HEAD), no committed round removed a second copy, and only the concision and restore passes did.

### 7. Content rules the data reshapes

| # | Finding | Who | Verdict | Evidence | Proposal |
|---|---|---|---|---|---|
| 7.1 | "Under 2 KB of visible text is an error" | Cx | ✓ wrong both ways | 13% of successful HTML is short: 67% "please wait, your download will begin" pages, 11% hearing pages, 11% GovInfo cover-only pages, 9% soft errors, about 2% real documents (about 205) | A rule on what the page says: an error word in the title or heading, an error URL, a challenge marker, the download-page marker, or under about 128 bytes; scored on its own sample at 99.6% caught and no real document dropped |
| 7.2 | Download pages hide missing files | (validation) | ✓ | Only 12 of 407 sampled download pages have their PDF captured: *est.* 8,800 testimony and statement PDFs | Treat download pages as wrappers and queue their `download=1` targets |
| 7.3 | Web-page versions multiply documents | Sp | ✗ as stated | Of 3,736 addresses with two HTML bodies, 2,696 are one fetch saved twice (identical text), 959 are one old veterans.house.gov page saved by two archives (menus differ), 1 is two live fetches | About 960 near-duplicates remain, a fixed set; owner question |
| 7.4 | Hearing pages wrongly marked as errors | (validation) | ✓ | 35% of sampled Senate hearing pages are under 2 KB | Fixed by 7.1 |

### 8. Numbers

| Claim | Validated value |
|---|---|
| 1,695,040 occurrences | Confirmed (catalog rows × archive paths); "largest document 455" is the House error page, the largest real document has 27 |
| 36,137 dead-link documents | Not reproducible: 36,768 by latest attempt |
| About 34,000 HTML archive members | Confirmed: 34,446 captures |
| 3,042 over 50 MB; 579 over 100 MB | Confirmed as catalog rows and stored size; 2,467 distinct files over 50 MB |
| 98k metadata records | Refuted: 47,643 source records, 103,200 GovInfo metadata files labelled as documents |
| 1,500 object operations a day | 4,000–8,000 (Pr) |
| "At most 5 bodies per URL" | Refuted: 34,084 addresses have 6 (GovInfo packages), the maximum is 735 (an error page), the largest real one 50; the link join totals about 696k pairs |
| 33,585 recorded cookies | 534,733 on 242,438 lines |
| `list` 2–3 MB; detail view 50–90 KB | About 4–5 MB; 100–200 KB after 3.2 |

### 9. Refuted or explained

| Finding | Who | Why it does not stand |
|---|---|---|
| The link-to-file join is quadratic | Cx | About 696k pairs in total today; bounded in practice. A stated bound and a refusal cap cover the tail. |
| `document_id` is not today's formula | Sp | Same formula; today's inputs exclude web pages. P E4 lists it. |
| Rotate exposed API keys | Pr | No real credential appears in any receipt. |
| Page versions grow with rechecks | Sp | Almost nothing has been rechecked; see 7.3. |
| Invariant 2's multipart clause is false | Pr | See 4.8. |

## Conflicts resolved

- **Schema growth:** last round asked for list-element additions; the pinned stack cannot read them (owner question).
- **Completeness:** last round chose a declared length; the receipts show it fails almost every page. Data wins.
- **Registry contents in DM:** keep one "such as" example each.
- **DM §6's engine-caps note:** plan state; delete it from DM (P M1 carries it).
- **Retry-After:** the owner chose the recheck-interval cap.
- **Quadratic join:** data shows it bounded.

## Root causes

1. **Fixes are not executed.** A fix changes one rule and breaks a reader of it. Confirmed for pattern 1 (8 to 9 of 10 from the latest round). Remedy: run the S1 acceptance sheet as a small executable model before more prose fixes; each fix names the rules it re-checked.
2. **Primitives are not defined first.** Confirmed, and long-standing: source URL, meeting page, import row, recovery body, candidate, catalog and record role. Remedy: define them once in DM §3 before any rule uses them.
3. **Platform claims and today's code are trusted, not checked.** Confirmed in code for every Iceberg and bindings claim but one partial. Remedy: each engine, catalog and reader claim cites code or vendor docs; broken patterns in today's code are rebuilt, not adapted.
4. **The changeover is under-specified.** Confirmed: the old writers still write cookies and paths today. Remedy: the plan's first step makes them raw-safe.
5. **Fixes grow the text.** Confirmed as growth; "every fix adds a copy" overstates it. Remedy: one home per rule, fold fixes, and one committed script for the numbers.
6. **Rules were written without looking at the data.** New in this round: the short-page rule, the page-version worry and completeness were all settled by data in minutes. Remedy: every content rule cites the measurement that set it.
