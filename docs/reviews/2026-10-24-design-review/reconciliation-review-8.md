# Reconciliation of Review 8: the data model, end to end

**Bottom line.** Four blind reviewers scored `docs/engine-first-data-model.md` at 33c2cba0 58–71 (mean 65). Three validators re-derived their data and code claims independently: about 50 findings stand, four were wrong, and the lead re-checked the validators' disagreements. Every confirmed finding is folded into the four documents; four engine gaps are spicy-stack tickets.

## Who reviewed and how they scored

Reviewers saw only the document, the code and the data (the 2026-10-02 index, the receipts mirror, spicy-regs' published tables); not earlier reviews or the lead's views. Validators re-derived every load-bearing claim with their own scripts.

| Lens | Model | Score of the data model | Accuracy, as validators scored it |
|---|---|---|---|
| End-to-end trace (`trace-review8.md`) | Fable | 58 | keys 92, raw 78 |
| Data claims (`data-review8.md`) | Opus | 70 | keys 92, raw 72 |
| Reader value (`reader-review8.md`) | Opus | 62 | keys 80 |
| Storage and engine (`storage-review8.md`) | Opus | 71 | engine 82, keys 82, raw 90 |

Validations: `validate-raw-review8.md` (A1–A14, E2, E3, E6), `validate-keys-review8.md` (B2–B4, C1, C3, C5, C9, C12, D3, D5, E5), `validate-engine-review8.md` (D1, D2, D6–D9, D11). Findings by ID: `review8-findings.md`. Scripts: `measurements/review8-20261026/`.

The score fell from review 7's 84 because these reviewers traced real data end to end, and because the lead's last two commits (cross-links, then spicy-regs inputs) added material no one had walked through: the broken code fence, the CBO range, one vote per nomination, the nomination part padding, the captions flag and the MODS "submitted" credit were all the lead's.

## Root causes

1. **Rules written against the shapes the receipts were expected to have** (A1–A8), as in review 7. Congress.gov meeting records are inline receipt JSON (18,140 meetings, about 11 copies each), 54% of recovery lines carry no category, every recovery's original link is in `source_associations[0]`, `file_references[].original_path` is a local path, a recovery row's `url` is the recovered copy's address, and House witnesses live in a separate witness-list body. Fix of the cause: M2 commits a field-presence census the ingest mapping must cover (plan §5.2).
2. **One key, two spellings** (B1–B8): witness keys binary in one file and hex in another; chamber spelled seven ways; nomination parts padded on one side; the vote join unstated; one package ID under four names.
3. **New links not walked through a reader's journey** (C1–C9): documents carried committee names that collide (47 names over 116 codes), printed-hearing witnesses were credited with every package file, a transcript had no row to open, nominations had one vote where 1,552 have several.
4. **Engine reality behind the rules** (D1, D2, D6, D11): no `json_array`, no URL functions, a ConnectedComponents that computes IDs itself (with a file-path fallback) and needs *est.* 1.65 GiB, an export whose bytes follow batch sizes.
5. **Reproducibility and operations** (D7–D9): releases unrebuildable after snapshot expiry, duplicates never refused, one unreadable input blocking every publish.

## Owner decisions (2026-10-26)

- **Senate witnesses:** Senate committee hearing pages are an appearance source, the page their occasion; their layout puts 90.7% of senate.gov testimony files in a witness's card, so no name matching is needed.
- **Titles in `list`:** title override, reading title, heading, else the publisher's link label (46% of documents); A11's phone heap test can move it back to `detail`.
- **Dead links:** `urls.parquet` indexes every source URL of a listed document's real files and every recovery's original link, by a fixed `lookup_url` normalization, so a pasted dead link always finds its documents and spicy-regs maps its links through it.
- **Apply all confirmed fixes and file engine tickets.**

## Lead calls, stated to the owner

- `has_captions` dropped: the release publishes no captions; video links and `video_key` stay, and caption text stays parked.
- Links resolve by the WHATWG URL parser, as browsers do; the `url` crate is already locked.
- A meeting is keyed by `event_id` alone (no ID names two chambers, now invariant 16); `chamber` is an attribute, and Congress.gov `NoChamber` maps to null, not joint (its committees are j 1,814, h 14, s 14).
- Congress.gov records are keyed by `record_sha` (the compact JSON of `record`, keys sorted), ranked by `updateDate`, not by receipt line.
- Recovery kind falls back to the match basis through the registry, not to a blanket kind; the 123 `direct_official_package` lines are logged for the owner (plan §8).
- Lookup keys live in their own file, so `links.parquet` keeps "one key, one row".

## Verdicts

**Applied:** A1–A6, A8–A11, A13 (the validator's fix: match jackets as integers), A14 noted, B1–B8, C1–C10, C12 (`bill_committees`, `nominations.committees_json` and `hearings_json`; `committee_reports` too sparse), C15, C16, D1 (ARCH §13.8), D3 (half-open Eastern intervals and tie-breaks), D4, D5, D6, D7 (content-addressed receipt-key list; kept releases keep their table versions), D8, D9 (the validator's mechanism: a pre-read byte bound and a person's `unreadable` decision), D10, D11 (ARCH §13.4), E1–E6.

**Rejected, with reasons:**
- **A7:** all 79,112 `retry_later` lines carry the publisher's `Retry-After: 15`; `delay_seconds` is the fetcher's own backoff.
- **A12:** House XML `meeting-id` values carry the prefix (fixture `HHRG106245`; a live record `HMTG110741`); the trace reviewer and the raw validator counted values already stripped upstream. The rule stays; the binding now notes that today's code strips only `HMKP`.
- **C11:** `url_state` and `capture_scope.json` stay in the release by design: capture reads its schedule from the live release, and the reader never loads them.
- **C13, C14:** `list_row` beside the ranges keeps invariant 18 checkable; `detail`'s size is measured with F0.
- **D2's stopgap** (pinning threads in the profile) would tie a release to one runner class; the engine fix is ss-iwqu.
- **D3's `first_fetched` part:** a min and max over a defined set cannot tie.

## Engine tickets (spicy-stack, under ss-oxg1)

- ss-e53d: `json_array` SQL function over arrow-json's encoder, with golden vectors.
- ss-6jg6: ConnectedComponents over an in-job relation, label only, interned IDs, node cap, true heap.
- ss-iwqu: byte-deterministic export.
- ss-7qz3: WHATWG resolution and percent-encoding normalization as SQL functions.

ss-vhi2 (the spicy-regs integration) gained a note: map its meeting-document URLs through `urls.parquet`.

## Word counts

| Document | Before | After |
|---|---|---|
| Architecture | 7,433 | 7,655 |
| Data model | 11,853 | 13,179 |
| Plan | 7,148 | 7,483 |
| Bindings | 5,697 | 5,789 |

The growth is the inline-record, Senate-page, lookup-key, work-list and nomination rules; counts no rule reads were trimmed.
