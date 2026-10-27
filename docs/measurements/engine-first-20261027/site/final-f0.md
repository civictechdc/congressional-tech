# Final F0 local acceptance

The corrected F0 release `62bddc6379e29f7f93a4f2c90e446962fdd708713f68d28624e66d81a25f9234` passes the shared reader and real built site locally. It has 1,241,157 list/detail rows. This clears the final-F0 dependency; real-device targets and live publication remain owner-gated.

| Evidence | Result |
| --- | --- |
| Indexed reader | Pass, including different pages and page-zero revisit with a one-byte evictable data cache |
| Node canary | Pass in 10.617 seconds; real stored copy, empty recovery-file decode, text search, facets, detail/link/source ranges, URL state, actual pointer headers and stale-pointer reread |
| Built browser contract | Pass at 1440×1000 and 390×844, plus changed-release 404 reload and delayed Back cancellation |
| Native hand/shard contracts | 2 pass with the new `engine-76968f7` C6 snapshot |
| Full offline lane at `9eb923c2` | 11,382 passed; 33 failures and 3 errors; all 36 baseline identities unchanged |
| Final named-label fixtures | 16 supported labels, including 15 canonical kinds; 7 rendered narrow-claim cases; 10 unit and 4 rendering checks pass |

Final-release browser startup was 2.85–2.92 seconds on this desktop. The two contract profiles sampled 406–410 MB of page-plus-worker heap. An additional phone-profile measurement sampled 606 MB; the Node canary sampled 635 MB. These are sampled maxima, not exhaustive peaks or real-phone measurements. The phone profile still runs desktop Chromium. Earlier development-F0 runs and rejected 256/384 MiB Node cap/yield trials remain retained; no memory or speed improvement is attributed to source changes from these different runs.

The native snapshot is a local debug fixture engine, not Linux or publication qualification. The runtime/profile checks used the reader at `534d8f54`; the subsequent `9eb923c2` change adds only two display strings, covered by fixtures and independent review. Full regression used `9eb923c2` and the C6 snapshot.

Selected receipts, the baseline comparison and a phone screenshot are shared immutably in `codex-coord/shared/site-evidence-9eb923c2/` under the coordination scratchpad. Full logs remain in `codex-site/`. Commands and owner gates are in [the local-method note](README.md). The shared target file remains `owner-gated`; engine owns CI/publish wiring and switch/deletion work. No live storage or network writes were performed, and Docker was not used.
