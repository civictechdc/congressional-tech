# Owner's settled decisions (as of 2026-10-26)

Question a decision only with evidence that it harms readers or raw data.

## Ground rules
- Greenfield: there are no users yet. Only the raw data (bodies, receipts, provenance in the R2 bucket) is sacred; everything above it can be rebuilt or deleted. Never build on a broken pattern; rebuild instead.
- Engine-first: congressional-tech always uses the docspec-rs engine; no application code overlaps an engine capability, and a missing primitive is added to the engine generically.
- Specs stay concise: a fix rewrites the rule it changes, never appends a note beside it.

## Architecture
- Per-step engine commits; DocSpec's news_lake keeps its own backend; publishing pins its inputs; raw safety by the R2 bucket lock; the bucket's public r2.dev address stays open.
- Pages are document pages only (no per-copy pages); 16-hex public IDs; phones are supported; one content per document; recoveries are labeled.
- Release files carry only what a reader acts on; relationships are keys on rows that the browser looks up; forensic detail stays in the lake.
- spicy-regs is owned and trusted: committees, members, terms, rosters, bills, CBO estimates, floor votes and nominations are read directly from its pinned immutable generations, and spicy-regs will read the archive's releases instead of capturing meetings itself (spicy-stack ticket ss-vhi2).
- Witnesses are keyed per occasion, never matched by name; a witness bio table comes later.
- Senate committee hearing pages are a witness source; document titles are in `list` (a phone heap test may move them back to `detail`); every source link is indexed for dead-link lookup (`urls.parquet`).
- Accepted lead calls: no captions flag; links resolve by the WHATWG URL parser; a meeting is keyed by event ID alone, Congress.gov `NoChamber` maps to a null chamber.

## Implementation
- Two phases: phase 1 is the documents-only switch; phase 2 adds hearings, witnesses, the spicy-regs entities and the large one-time raw jobs.
- Leverage existing data; defer any major re-parsing or re-hashing unless actually necessary. Per-item results are borrowed with their basis recorded; old cross-item decisions are only parity oracles.
- PDF integrity checks are borrowed, including those resting only on 2026-10-01 receipt lines; the 3,104 PDFs no check has reached are listed as documents ("unchecked") until the phase-2 PDF copy job (B13) reads them.
- Chosen simplifications: byte-identical output only on one pinned runner class in phase 1 (ss-iwqu later); no separate fingerprint parser; no review forms in phase 1 (a script carries the 86 existing reviews over).
- Considered and not chosen: replacing Iceberg with Parquet files plus a manifest (M1 still decides), switching the site before rebuilding capture, a lighter F0 fixture, cutting the recovery importer, trimming M2.
- Pushing, the bucket lock and other owner actions wait for the owner.
