# Retained House floor feed

The shared `spicy_docs.sources.congress.house_floor` reader turns the retained
House Atom feed into entry identities, timestamps, weekly page links and document
link occurrences. It reuses the shared XML reader and bounded HTML events. It
does not fetch the publisher or interpret scheduled consideration as a vote,
completed action or enactment.

CT's explicit `congress_api.lake.readings.stage` or `run` accepts
`parser='house_floor_feed'`. Candidate selection restricts captures to complete
successful responses for the House feed URL. A dedicated 64 MiB decoded bound
supports the retained 38,854,265-byte source without changing ordinary XML's
24 MiB bound. A successful reading retains entry hashes and original byte spans,
keeps every discovered link occurrence, and emits no document prose. The model
consumes these links with `/feed/entry/N/link/M` attribution. Failed feeds leave
ordinary reading evidence available; valid empty feeds remain distinct from failures.

SpicyRegs provides an offline
`python -m spicy_regs.pipelines.house_floor_feed --selection MANIFEST
--output-dir FRESH_DIRECTORY` command. Its manifest pins local source bytes,
source URI and capture time. It retains original bytes through the existing raw
archive and writes `house_floor_feeds`, `house_floor_entries` and
`house_floor_links`. The generation is explicitly `local-partial`; it is not
published in the public catalog. Repeated captures and entry revisions remain
separate observations.

A narrow malformed-link repair removes a leading slash from `/https://...` or
`/http://...` only when the exact absolute target is stated elsewhere in the same
complete feed. Shared tables retain the original href and ordinary resolution,
then add `repair_url` and its evidence basis separately. CT retains those fields
and uses the corroborated target for discovery. This supports the spelling
repair, not a claim that the remote target is available.

The retained October 4 capture, body SHA-256
`c90e782a00651261a9ac21ae8d30df88757b3b66ae99a5ff794f0dc8ca65336e`,
produces 2,226 entries and 65,511 link occurrences. Final actual CT model output
resolves all 65,511 occurrences in a 14-second replay with 0.67 GiB peak process
tree RSS. The Regs generation takes 8 seconds at 0.59 GiB. These are bounded
measurements of this source, not estimates of corpus throughput.

Direct source/intermediate/output review covers entries 0, 1, 1047, 1048 and
2225: first revisions, the malformed URL and its corroboration, and the final
entry. The first two entries share a weekly URL but differ in bill version and
links, so URL-only deduplication would lose data. The latest entry in the
retained source is September 15, 2026. Historical completeness and current
freshness are unestablished.

Evidence lives under the main checkout's
`.cache/archive-release/ocr-recovery-20261113/repairs/house-floor-feed-20261113/`:
`ct-replay-final`, `regs-final`, measurements, pinned fixtures and the independent
data review. Reviewers read the selected originals and actual intermediate/final
rows; automated regression tests are separate evidence. Recurring acquisition,
publisher refetch and OCR remain paused or deferred. The daily HTML metadata
pass stays unchanged; feed admission is explicit until a daily baseline and
source-freshness policy are qualified.
