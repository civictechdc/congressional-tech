# Recovery relationship explanations

`identity_note` explains how a recovered document relates to the requested
original. Supply it only when reviewed evidence supports the explanation; omit
it or use null when no explanation is recorded. `kind` still records the
relationship, and `evidence_sha256` still identifies the evidence. An acceptance
reason such as `source_identifiers_match` supplies no additional explanation.

Accepted mappings consumed by `corpus_recovery.reconcile.reconcile` and requests
consumed by `corpus_recovery.campaign.import_candidate` accept an optional
`identity_note` string. These inputs are pinned by the existing mapping/request
digest. The producer preserves explicit explanations, converts missing or blank
notes to null, and removes the exact generated reconciliation sentence. It does
not infer an explanation from filenames, hashes, relationship kinds or successful
acceptance. The reviewer remains responsible for the explanation's evidence.

The `authored-or-null-v1` authoring policy participates in new decision identity.
An older completed stage remains immutable and can still be read through the
existing exact historical publication filter. An old campaign operation refuses
new authoring under its existing binding. Do not reacquire or reimport a body
merely to change its note.

For a selected legacy decision whose note exactly restates its own evidence pin,
`corpus_recovery.identity_notes.correct_generated_note(record, decided_at=...,
decided_by=...)` prepares a new decision with null `identity_note`, a new ID and
`supersedes` set to the old ID. It preserves all other evidence, relationship and
body fields. It refuses authored text and sentences containing another pin.
Select current decisions from the complete supported input history before using
the helper; do not supersede an older decision that an owner has already replaced.
The helper does not perform selection, adjudicate identity or write shared data.

Write the returned records as JSONL and use the maintained local staging command:

```sh
.venv/bin/python -m congress_api.cli.provenance \
  --records corrections.jsonl --kind recoveries \
  --decided-at 2026-11-06T16:00:00Z --stage correction-stage
.venv/bin/python -m congress_api.cli.provenance --stage correction-stage
```

Keep the old input bytes and their pins. Applying the stage is a separate action
for the authoritative writer. Include both old and new decisions in later model
inputs, run the maintained release checks, and verify the selected release in
Congress MCP and the site. Compare recovery counts, kinds, bodies, URLs, sizes
and document attachment before and after. This is a metadata change; it requires
no body fetch, decompression, global rehash or parser replay.
