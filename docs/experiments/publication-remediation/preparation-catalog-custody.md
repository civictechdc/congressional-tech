# Catalog preparation custody and validation

Local implementation evidence, 2026-10-18. No production rebuild or publication ran.

The catalog writer performs the complete SQLite-backed reference check on its owned temporary pair. Its process-local proof follows the owned rename into the final build paths. `raw_catalog._publish_result` and `publish_catalog` require that proof instead of repeating the reference scan. The publication stage binds the validated semantics to exact file sizes and SHA-256 digests before upload. Recovery admission may reuse that content proof only after hashing the selected local pair, checking metadata and required body coverage. A fresh process has no issued proof and runs the reference checker again.

`CatalogPairValidation` and reference/content/file proofs use an issuance registry with weak references. JSON, dictionary copies and copied dataclasses retain facts but cannot grant reuse. File proofs bind device, inode, size, modification time and change time. Validator identity binds the function/code objects, its source file identity, Python runtime and PyArrow version; this local binding complements the outer release dependency/source pins and does not replace them.

Recovery staging owns immutable local source names through its publication attempt. It retains verified files using exclusive hard links on the same filesystem; cross-filesystem retention uses the existing checked-copy route. Each directory owner removes only its own names. Linking changes file change time, so this narrowly owned operation refreshes the originating proof after checking the inode, size and modification time. Ordinary later alias removal or rewriting conservatively invalidates proof reuse. LocalStore publication still copies bytes: its caller can later rewrite a legacy build pathname, and a hard link would allow that rewrite to corrupt selected local data.

Measured bounded fixtures:

- Normal raw-catalog rebuild: one complete reference-validator invocation across writing, history retention and selection (previously three).
- Exact selected-copy handoff: the initial reference scan plus selected byte/hash/metadata checks issues one pair proof without a second reference scan. Copied/forged proof objects fail.
- 29-byte owned recovery file: retention copies zero payload bytes and hashes zero additional payload bytes, compared with a second 29-byte copy/hash. Scratch holds two directory entries for the same inode while the owned partial exists, rather than a second 29-byte payload allocation. The fixture asserts identical inode and exact retained bytes after the original name is removed.
- 700-byte upload: issued file proof performs zero additional SHA-256 byte work in `R2Store.put_derived_file`; transport MD5 still reads all 700 bytes and validates Content-MD5/ETag. Plain restored hash dictionaries retain the SHA-256 pass. Rewriting the source rejects the old proof before upload.

Capabilities are explicit: publication requires conditional selector and exclusive derived-file methods before generation writes. Local small-object immutable installation uses an exclusive hard link, never check-then-replace. Catalog selectors have a 1 MiB read budget; missing and partial-read behavior remains explicit. Local key iteration streams unless ordering is requested; receipt replay and metadata consumers explicitly sort where their meaning requires it.

Validation command used the primary `.venv` interpreter with this worktree's `packages/congress_api/src`, `packages/congress_shared/src`, `apps/site/scripts`, `tests`, and `scripts` at the front of `PYTHONPATH`: 134 focused tests and five continuation subtests passed. Covered suites: catalog pair validation, staging, publication, raw catalog, catalog files, R2 archive store, and recovery publication dispatch. These fixtures establish local behavior and work counts, not production runtime or memory savings.
