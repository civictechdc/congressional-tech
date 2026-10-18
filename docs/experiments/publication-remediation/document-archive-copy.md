# Keep the complete documents archive unchanged

Documents are a complete archive download. The maintained browser reads its
separate browse, detail, filename and observation files for normal interactions;
it does not require the archive to use the viewer's requested compression level.
The builder now always copies the selected documents Parquet bytes. Filenames
still undergo repacking and complete ordered Arrow equality verification.

This follows the retained-data failure after the stage-aware estimate fix:
the local documents repack refused a 43,807,597-byte Arrow row against the
unchanged 16,777,216-byte limit after 70.75 seconds. Its source remained intact.
The original worker receipt and independent design review remain under primary
`output/publication-remediation-20261018/rollout/local-documents-repack/`.
No decoder or conversion limit is raised, and no failed transform is retried.

The caller captures source custody before input verification, checks the
canonical selected raw path against `Catalog.document_path`, and reuses the
Catalog-owned reader's checked row count and catalog ID. Existing
`derived_files.copy_checked` copies in 1 MiB chunks, hashes every byte, requires
the selected manifest's size and SHA-256, fsyncs and installs the fresh output.
Source custody must remain unchanged after copying. A failed check prevents the
final manifest; source bytes and owned failure evidence remain available.

The issued destination `VerifiedFile` passes through `describe` only after
`require(path)`. This removes a redundant destination hash pass without replacing
inventory, artifact, upload or public checks. Serializing the manifest retains
hash/size facts; restoring an artifact still requires fresh inventory verification.
Altered destination bytes invalidate the issued proof and restored inventory.

Reporting distinguishes operations:

- `files.documents.encoding` declares `mode=source_passthrough` and the selected
  `source_sha256`; it does not invent a codec or compression level.
- `documents_copy` timing records complete-byte verification as
  `verification_method=complete_sha256_bytes`. It replaces `documents_repack`.
- `compression_policy.applies_to` contains only `filenames`, the output governed
  by that requested repack policy. Detail and browse writers keep their existing
  fixed settings.
- The benchmark independently binds copied timing/manifest/source facts to its
  already hashed output inventory. Document bytes must match between arms;
  only rewritten filenames may differ physically. Its exact gate is named
  `exact_filename_values_and_archive_bytes`.

There is a deliberate archive-size cost. The verified published archive is
380,338,200 bytes, SHA-256
`198a296f961eb7a2b447743d20b4502538a5c34e16849e0cbd056c74d781810a`.
The raw exact copy is 541,147,000 bytes, SHA-256
`f0bf8fb6fcf4f1067d2182372661917ed23741e47943d575f96d2fc4d44552b7`:
**160,808,800 additional bytes (+42.28%)** for this archive/download-only file.
The copy remains below the existing 5 GiB single-PUT ceiling. Existing size and
upload gates remain mandatory. This is identity preservation and elimination of
an unnecessary decode/reencode, not a compression win or a measured claim about
complete publication size, speed or memory.

Local verification passed **129** focused publication, decoded-budget,
benchmark, checked-copy and transferred-publication tests. A synthetic complete
publication contains an archive-only nested row above the unchanged Arrow row
limit, with Unicode, nulls, empty values and duplicates. Its archive iterator is
trapped, filename repack remains active, and archive bytes/schema match exactly.
Tests also cover source replacement before/during copying, wrong checked-copy
hash/size, issued-proof reuse, serialized inventory mutation and strict Python
and Arrow refusals. A reviewer-requested benchmark inventory-binding regression
then passed all **5** benchmark tests. Commands, runtime and source evidence
references are in [evidence/document-archive-copy.json](evidence/document-archive-copy.json).

Real retained-file copying and any complete publication qualification require
separate receipts. This implementation performed no real-catalog probe,
acquisition, resource increase, workflow dispatch, publication, push or merge.
