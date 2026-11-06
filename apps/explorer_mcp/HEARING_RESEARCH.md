# Hearing research and passage citations

`get_hearing_bundle(event_id)` returns the meeting, committees, current witness
appearances, prepared testimony, official and committee transcript references,
caption references, recording observations, and published coverage. Use `include`
to choose sections. Each section can return a `next` request with its own offset.
The complete response fits the server's 128 KiB response limit.

Recordings retain the original observation and its source reference. An
association with `scope=package_context` relates a recording to a printed hearing
package; it does not prove that the recording covers this particular sitting.
Witnesses use the published `superseded_by IS NULL` rule. Names never establish
document ownership. Prepared testimony uses the published testimony material
kinds; it does not treat every witness-related document as testimony.

## Discover a source, then read it

Call `get_transcript(event_id=338785)` for an inventory. Sources have separate
`kind` values: `official`, `committee`, and `captions`. The response preserves the
package or recording association, retained body digest, archive URL, format,
language, production, and a stable source reference.

Pass a returned `reference` to `get_transcript` to read that exact source:

```json
{"event_id":338785,"kind":"captions","source_id":"<returned source_id>","release_id":"<returned release_id>","limit":25}
```

Without a `source_id`, `offset` and `limit` page the inventory. With a document
source, `page` selects a one-based PDF page, `offset` counts characters, and
`max_chars` bounds the text window. With captions, `offset` counts cues and
`limit` bounds returned cues. Follow `next_cursor` to continue without rescanning
earlier segments. Choose either an initial cue offset or a continuation cursor.

Caption reads resolve supported subtitle media playlists on the server. Every
fetch goes to the configured content-addressed archive, and every returned body
is SHA-256 verified. Publisher URLs explain the source context; the reader never
fetches them. `caption_resources.parquet` retains the winning root address,
ordered child declarations, successful redirected child fetches, missing children,
and the pinned playlist reading version.

`complete_snapshot` describes a retained playlist with an end marker and no
declared missing resources. It does not prove that a recording covers the entire
hearing. A live snapshot has `partial_live_snapshot` coverage. Missing, corrupt,
unsupported, or unreadable resources are reported explicitly. Older releases
without the resource map still expose playlist references and report server-side
assembly as unavailable. Caption calls read at most 32 segments and 32 MiB of
decoded text, then return a continuation where possible.

WebVTT cues preserve identifiers, settings, local timestamps and any
`X-TIMESTAMP-MAP`. MPEG timestamps remain a separate timebase, following
[RFC 8216 section 3.5](https://www.rfc-editor.org/rfc/rfc8216.html#section-3.5).
Cue text and repeated occurrences remain in source order. Plain SRT and explicit
paragraph-timed TTML are supported. Encryption, byte ranges, separate
initialization data, nested master playlists and relative TTML parent timing
need another reader and return an explicit unavailable result.

## Cite and reopen the original passage

Body text windows, text matches, publisher-selected text and caption cues return
a `citation`. Pass it unchanged to `resolve_citation(citation)`.

The citation identifies the release, document or transcript source, root body,
reading version, exact page/offset or segment/cue location, and the passage's
text digest. Caption cues also identify the segment body and original timing.
Publisher-selected passages retain their selector and selected-block digest.
An unambiguous published witness occurrence is included when present; multiple
associations stay labelled ambiguous.

Resolution uses the currently selected release. Select the citation's original
release to reopen it. A different selected release returns `unavailable`; a
different body, reading definition, selected block or passage returns
`different_source`. A missing source returns `unavailable`. The reader does not
silently substitute a newer source or choose a witness by name.
