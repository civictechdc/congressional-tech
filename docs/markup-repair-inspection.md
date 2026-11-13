# Inspect a retained malformed XML body

The offline command below preserves one pinned original and asks SpicyDocs for
a bounded recovery candidate. It writes the original bytes, candidate XML,
ordered markup observations, resulting text, parser diagnostics and file hashes
into a new directory. It uses no OCR or source requests and writes no reading
tables, selection manifests or publication state.

```sh
.venv/bin/python -m congress_api.retention.markup_repair \
  --input /absolute/path/to/retained.xml \
  --sha256 <original-sha256> \
  --output-dir /absolute/path/to/new-review-directory \
  --source-gap-note 'Direct observation of the missing or damaged source content'
```

Run the command under the repository watchdog for large inputs. `--max-bytes`
and `--max-candidate-bytes` bound the selected input and candidate separately.
An existing output directory refuses rather than overwriting earlier evidence.
Keep the review directory under the main checkout's `.cache/archive-release/`.

Read `original.raw`, `repair.json`, `candidate.xml`,
`candidate.events.jsonl` and `candidate.txt` directly. Check concrete names,
numbers, order, omitted or altered attributes, and where the source ends. Byte
positions from the candidate's events address `candidate.xml`; they do not
address the original after rewriting. The metadata's `source_gap_note` is a
reviewer's observation, not a parser inference.

Every altered result is `partial` and `not_qualified_for_selection`. Exit zero
means the inspection packet was written, not that the document is complete.
A refusal also leaves an inspectable packet and exits two. The ordinary CT
reading path remains strict, so this command cannot turn a source gap into an
accepted reading.

The retained S. CON. RES. 5 original
`4cad751b9ec4c7584d60e1d5059b70d29672853056fd789766b9decad7092498`
ends mid-attribute in its table of contents, after “TITLE II—Reconciliation.”
Recovery closes open XML elements and discards the unfinished attribute. Its
text is useful for reviewing the retained prefix; the missing resolution text
remains unavailable. Refetching remains deferred.
