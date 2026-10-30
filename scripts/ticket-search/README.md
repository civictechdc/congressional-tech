# Local ticket search

Search tk Markdown with local MiniLM embeddings and embedded LanceDB. Hybrid
search combines keyword and semantic rankings. Results include ticket status,
source path, line number and matching passage; Markdown remains authoritative.

Run from the repository root with `uv` installed:

```sh
./scripts/tk-search sync
./scripts/tk-search search "canceled searches keep blocking new requests" --limit 5
./scripts/tk-search search "object storage stream retries" --json
./scripts/tk-search search ct-84x7
./scripts/tk-search search "GetObject" --mode fts
```

The default index covers this checkout's `.tickets/*.md`, including closed
tickets. Use `--status open` to filter. Nested archives and other repositories
require explicit roots. The index lives under the already ignored
`.cache/ticket-search/`. Searches read the last synced snapshot; run `sync` after
ticket changes. Unchanged syncs skip embedding and table writes.

## Repeated queries

Keep one foreground process open to reuse the loaded encoder:

```sh
./scripts/tk-search search --stdin --limit 5 <<'QUERIES'
canceled searches keep blocking new requests
object storage stream retries
QUERIES
```

Each nonempty input line produces one JSON array, flushed immediately. EOF ends
the process; errors exit nonzero. Query options apply to every line. The first
semantic query loads the model; later queries reuse it. Exact IDs and keyword-only
search skip model loading. There is no daemon or network listener.

## Runtime and index

The launcher uses an isolated `uv` script environment with Python 3.13, separately
from the repository's Python 3.12 environment. Direct dependencies are pinned in
`ticket_search.py`. The encoder is `sentence-transformers/all-MiniLM-L6-v2`, pinned
to revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, on CPU with four threads.
It reuses the Hugging Face model cache. Initial setup downloads only missing
dependencies or weights. Inference runs locally; ticket text stays on this machine.

Long tickets use overlapping passages with title context and original line
locations. Sync hashes each source, embeds only changed tickets, replaces obsolete
passages and removes deleted files. Missing roots, invalid input and embedding
failures stop before ticket rows change. A local lock prevents simultaneous sync
writers. A later sync repairs a missing or incomplete keyword index.

The index records the model configuration and selected roots. Changing either
requires a new `--db` directory. Indexes are disposable and retain historical
versions; remove one only when no command is using it. Keep indexes and model
weights out of Git.

## Multiple repositories

Choose one checkout per repository and repeat `--tickets` when creating a separate
index. These are placeholder paths:

```sh
./scripts/tk-search --db /tmp/my-ticket-index sync \
  --tickets /path/to/first/.tickets --tickets /path/to/second/.tickets
./scripts/tk-search --db /tmp/my-ticket-index search "retry failed imports"
./scripts/tk-search --db /tmp/my-ticket-index sync
```

Sync remembers those roots and refuses to refresh when one is unavailable.
Identical IDs in different roots remain distinct results.

## Limits and verification

`--mode vector` selects semantic-only search; `--mode fts` selects keyword-only
search. Exact IDs bypass ranking. `--limit` counts distinct source tickets.
Semantic search ranks candidates even when none is relevant, so inspect the
source. This is a small-corpus prototype: changed passages are embedded in memory
and vector comparison is exhaustive. A new process pays startup cost; use stdin
mode for repeated lookups. Source edits during sync are picked up on the next sync.

To verify installation, sync, inspect a real search result, and repeat sync.
`embedded_passages` should be zero when tickets have not changed. The summary
reports the configured roots, changed/deleted files and passage counts.

The search engine is copied unchanged from `spicy-stack` commit
`e08e7a142baa98d56eb37141533132c436531609`. The source implementation's focused
tests cover incremental refresh, deletion, input failures, writer locking,
duplicate IDs across repositories, streamed queries and model reuse. Its encoder
comparison used Spicy Stack tickets; it does not establish search quality on this
repository's tickets.
