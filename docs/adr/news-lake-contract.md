# News-lake contract authority and repo fit

Status: proposed, 2026-10-20.

The [Political News Lake design packet](../../packages/news-lake/docs/packet.md) defines
a politician-aware news corpus contract: thirteen record kinds (C1–C9), an Iceberg
profile (I1–I6), a Draft 2020-12 JSON Schema, and six implementation slices. The
offline implementation lives in [`packages/news_lake`](../../packages/news_lake/README.md);
the docs directory is the proposed contract authority and the shipped schema copy is kept
byte-identical by test.

This ADR proposes the packet as the news-lake contract authority, with the pilot's
audited 30-day coverage/latency report (packet.md §Outcome and scope) as the
ratification gate. Until that report lands, the contract remains a proposed project
contract — the packet's own tier — not a W3C-style publication.

## Fit with the repo's columnar direction

`docs/data-warehouse-design.md` records this repo's columnar direction: publish
Parquet and query it directly from the browser, and "a schema lands with a caller,
or it doesn't land." The lake does not replace that idiom; it sits upstream of it:

- The lake owns acquisition, evidence retention, replay identity, pinned releases
  and retention (Iceberg features static publication files do not provide).
- Public-facing consumers should reuse the repo's static-Parquet publication idiom
  (`apps/site/FILENAME-VIEWER.md`, the explorer's Hyparquet reader) rather than
  reading the lake catalog directly.
- The pilot is the caller that satisfies the caller rule: it exercises hourly
  acquisition, identity, selection and views against live providers before any
  scale-out or public projection is built.

## Repo enrollment

`packages/news_lake/tests` is enrolled in `test-suites.toml`
(`[lanes.production-offline].roots`) and `news_lake` in `[environment.imports]`, so
`dev.py inventory`, `doctor`, and the production-offline lane cover it like the
other maintained members. A policy-deletion path (`Coordinator.abandon_cycle`) is
the named remediation for failed publication cycles; full retention/expiry
enforcement on export remains deferred, as the packet states.

## What is deliberately out of scope

Live provider HTTP wiring, the production extractor choice (the stdlib HTML→text
extractor is a placeholder), real credential handling beyond URL redaction,
catalog migration to production storage, and the pilot's five-politician roster.
These are named in the packet's own "Still to implement" list.
