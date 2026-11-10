# Congress Explorer 0.6.6

Document kind filters now treat the words an archive release lists as one kind
as one. Asking `search_documents` for `testimony` also returns documents labelled
`witness-statement`, and the reverse. Before, the filter matched one word exactly,
so a `testimony` search missed witness statements filed under the other label.
Hearing bundles fill `prepared_testimony` from the same published list.

The release names its synonyms in `schema.json`. Release 77673bfb8fcf, published
2026-11-10, lists one pair: `testimony` and `witness-statement`. Other kinds still
match exactly. Later releases can add synonyms without a new server version.

The update reads the same published archive. Releases before 77673bfb8fcf list no
synonyms; with one of those selected, filters behave as in 0.6.5. A selected
release never changes on its own, so run `congress-explorer-mcp prepare` and
restart the client to adopt the current release.
