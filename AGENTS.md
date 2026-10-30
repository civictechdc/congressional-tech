# Ticket search

Run `./scripts/tk-search sync` to refresh the local ticket index, then
`./scripts/tk-search search "describe the issue" --limit 5` for hybrid keyword
and semantic search. MiniLM runs locally on CPU. The index covers this checkout's
`.tickets/*.md`, including closed tickets; refresh it after ticket edits.

For repeated queries, `./scripts/tk-search search --stdin --limit 5` reads one
query per line and emits one JSON array per query while reusing the loaded model.
Use `--json` for a single machine-readable result, `--status open` to filter,
or `--mode fts` for keyword-only search without loading the encoder. Exact ticket
IDs bypass ranking.

Use `tk` for ticket edits, status and dependencies, and `rg` for literal lookup.
Inspect the cited passage before treating a ranked match as evidence; semantic
search can return unrelated candidates. Keep generated indexes and model weights
out of Git. See [ticket-search usage](scripts/ticket-search/README.md) for index
location, multi-repository roots and verification.
