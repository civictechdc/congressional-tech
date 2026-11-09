# Congress Explorer 0.6.5

Caption transcripts now open on speech. A caption read without a cursor skips up to
256 segments that hold no cue and names them in `skipped_segments`. Hearing 338785 used
to return three empty pages first; one call now reaches its first spoken cue.
Continuation cursors still read 32 segments per page and keep their meaning.

Meeting records, hearing bundles and transcript inventories carry `captions`
`{advertised, archived, basis}`. It separates captions a publisher advertises,
usually in YouTube metadata, from caption tracks the archive retained. An empty
caption list then explains itself.

The update uses the same published archive and requires no local data refresh.
