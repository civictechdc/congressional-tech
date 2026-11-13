# Qualified reading selection and page checkpoints

`ct-55qo` and `ct-aitp` add opt-in support for mixed accepted readings and
same-policy PDF restart. The default extraction and cleanup rules are unchanged.
No production manifest has been adopted by this change. OCR remains paused;
these options do not lift the pause or change the frozen recovery checkout.

## Select actual retained readings

The producer spec (`congress_api.cli.body_text`) and export spec
(`viewer_publication.body_text_export`) accept `selection`, a path to a JSON
manifest. Both use the same selected-key rule. A manifest has these fields:

```json
{
  "version": 1,
  "baseline_versions": {
    "pdf_text": "<accepted baseline version SHA-256>",
    "html_text": "<accepted baseline version SHA-256>",
    "xml_text": "<accepted baseline version SHA-256>"
  },
  "qualification": {
    "path": "qualification.md",
    "sha256": "<SHA-256 of that report>"
  },
  "overrides": [
    {
      "body_sha256": "<source body SHA-256>",
      "parser": "pdf_text",
      "parser_version": "<actual retained recovery or corrected version>",
      "status": "completed",
      "text_sha256": "<SHA-256 of retained UTF-8 text>"
    }
  ]
}
```

The example uses placeholders; actual identities must be lowercase 64-digit
hashes. The qualification path resolves relative to the manifest. Its report
must justify baseline retention, each exception and rejected replacements; a
matching report hash proves identity, not quality. Keep that report and source
evidence durably. Parser keys must match the supported body-text parsers.

Exceptions are unique per body/parser and select an actual retained version.
Completed exceptions require exactly one matching outcome and text row, with
both the stored hash and the actual text agreeing. Error, size-limit and active
unreadable exceptions require `text_sha256: null` and no text row at that key.
Missing, conflicting or mismatched exceptions fail before a work list or export
pointer is accepted. A newer failed attempt cannot displace accepted baseline
text. Export requires the retained readings table when exceptions are supplied;
direct planner calls also require `existing_text`.

The planner still executes only its current declared policy. It separately
counts `unselected_current_attempts`: already attempted current-version rows
that are not accepted by the manifest. These remain available for qualification
without entering a repeated-extraction loop. They are not exported merely
because they are newer. Active refusal history is retained and coverage uses
the same accepted keys. A failed candidate does not supersede a prior reading.

The manifest digest, qualification identity and exception count appear in the
plan and export pointer. Historical rows retain their actual version. Physical
compaction, corpus-wide equivalence and production publication remain separate
acceptance work.

## Retain completed pages across process or batch failure

Set `page_checkpoints` in the producer spec to an explicit durable directory
under the main checkout's `.cache/archive-release/`. The recovery command also
accepts `--page-checkpoints`; do not use that command to restart paused OCR.
Batch-stage directories are rejected because their contents are transient.

The adapter uses installed spicy-docs `DocumentExtractor.extract(pages=...)`
and `PageResult`. It saves successful page observations before requesting the
next page. On restart, it verifies committed records, requests missing pages,
reassembles source order and feeds the existing `rendition_text` cleanup.
Native spans needed for font-glyph accounting survive; rasters and provider
objects do not enter the checkpoint. Valid empty pages remain completed pages.

The namespace pins source bytes, page rule/backend settings, reader/render
policy, CT implementation bytes and installed dependency versions. Built-in
native/Vision factories provide their identities; custom factories must declare
a reproducible `PageRule.checkpoint_identity`. A changed policy creates another
namespace. This first slice supports same-policy restart, not mixing alternate
recognizer policies within one document. That extension and its source-quality
qualification remain in the PDF routing/fallback tickets.

Each page is checksummed and written atomically with file/directory fsync. A
directory lock excludes another writer. Started/finished attempt records and
failed-page records preserve interruption evidence. Only an exhausted complete
page stream can produce a completed body reading. Corrupt checkpoints, malformed
metadata, lock contention or storage failures leave the body pending with
`page_checkpoint`; they do not declare the source unreadable. Preserve those
files for diagnosis. Partial writes are ignored; automatic deletion or eviction
is not implemented.

## Qualification and remaining limits

Focused checks cover the actual native planner, export CLI and worker, including
unchanged baseline, recovery, correction, rejected replacement, active refusal,
new attempts awaiting qualification and markup-only policy changes. A new
process resumes after an injected exit on page two, extracting only that page;
ordered text, byte offsets and scripted recognition provenance match a fresh
run. A real native hearing cover and valid blank page preserve cleanup records.
Changed identities and planted text/metadata corruption are rejected or isolated.

The bounded fixture result supports keeping existing declared reading versions:
this change alters selection and persistence, not extraction or GPO cleanup.
`model/reading-version-diagnostics.json` records the reviewed implementation
evidence. This is not a claim that historical PDF versions are semantically
equivalent, that all retained rows are qualified, or that real Vision restart
has passed. Real OCR remains paused; no recognizer/provider or publisher-refetch
jobs were run for these checks. Corpus checkpoint storage and bulk parse costs
still need measurement before rollout.

On 13 November 2026 the focused five-file run passed 79 tests (a partial
`production-offline` lane, not the full lane) in 29.10 seconds. The watchdog
measured 0.685 GiB peak process-tree RSS and 0.635 GiB physical memory. The
retained fixture checkpoint records totaled 71,533 bytes; the largest was
36,783 bytes. These are fixture measurements, not a corpus forecast. Earlier
attempts stopped at the 15/12 GiB disk reserves before pytest; after measuring
the prior fixture output at 78 MiB, the bounded final run retained a 10 GiB
disk reserve. No unrelated files or processes were removed.

Evidence is under the main checkout's
`.cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/`:
`final-focused.xml`, `final-verified-memory.json`, its timeline, and
`final-fixtures/`. The independent audit reviewer also compared one real native
cover through serialization and ordinary cleanup with identical results.

The producer owns checkpoint storage and supplies an extraction adapter to the
parser. The parser does not import retention code. Reading-version evidence
explicitly includes that adapter and its imports. Recovery rules without a
reproducible identity remain unqualified for checkpoint reuse after lifting a
pixel bound. These boundaries are covered by the import-fence, worker restart,
corruption, recovery and execution-trace tests; extraction meanings remain
unchanged by this dependency correction.
