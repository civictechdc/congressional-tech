# Scale and cost

Sizes an implementation must handle, measured on the 2026-10-19 snapshot, and the expected cost of each step. Moved from [ARCHITECTURE](../../engine-first-architecture.md) §5 and §16; rules that depend on a number state it themselves.

| Quantity | Measured |
|---|---|
| Receipt lines, capture rows | 2.6M lines in 2,289 receipt files; 3.9M capture rows |
| Distinct bodies | 1.04M, 0.70 TB stored (PDF 365 GB, ZIP 286 GB, untyped 37 GB, HTML 4.5 GB, XML 0.8 GB) |
| Distinct URLs | 1.16M |
| Source files | 1.68M |
| Listed documents | *est.* 0.5–0.7M |
| Normal day | a few thousand capture rows (3,553 from 2,946 receipt lines on 2026-10-16); 258–1,595 new bodies |
| Import day | up to 708,626 receipt lines (745,456 capture rows), 547k new bodies |
| Largest body | 1.19 GB; none above 5 GB |
| Bodies referenced by one receipt line | up to 22,354 |
| Link matching | about 696k (link, source file) pairs; the most real files at one address is 47, the members of one GovInfo ZIP (a top-level URL holds at most 3) |

At this scale, recomputing the model from the lake each run is cheaper than maintaining it incrementally: a narrow relational proxy ran in 3.7 s with 1.75 GB of memory, and connected components over the 4M-node graph took 1–2 s.

| Step | Cost | Expected |
|---|---|---|
| Capture | O(new attempts), network | Bounded by politeness to sources |
| Captures ingest | O(new receipts) to read; the work list scans the keys already ingested | Seconds |
| Readings | O(new bodies in scope × parse cost) | Minutes daily; backfills in background |
| Filename readings | O(new pairs) | Under a second daily; 7–18 minutes per catalog version |
| Model + export | O(N log N) sorting plus scans and joins over every row; linear grouping | Seconds for the narrow plan |
| Publish | O(release size) | About 95 MB of uploads on a day with changes |
| Detail view | One page per leaf | One round trip after the once-per-session fetch of ARCHITECTURE §11.1 |
| Raw check | O(history) object metadata | About 1,300 list requests, no body bytes |

A normal day moves about 4,000–8,000 object operations and 2 GB, inside R2's free tier at today's scale.
