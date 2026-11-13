# HTML body-text qualification for ct-chc4

The reader passed all three acceptance criteria for ct-chc4. A private run of the maintained archive export produced all 2,929 original saved HTML texts. The independent audit found zero retained script or CSS fragments and preserved the normalized visible text, including order and repeated segments. Publishing the complete body-text export and search index belongs to ct-m704.

## Reader and data checked

- Spicy-docs 0.84.0 removed script, style, noscript and template content and added an unchanged Ways and Means opening statement as a regression fixture. The fix is `57aaf146` and the release is `12baaaa0`. Congressional Tech vendored it in `77f2b3a1` and advanced `html_text` to `e1928f25e2803cd6bc8546d1673ff7ba01a11ae861c322165c78af9d32380941`.
- Verification ran at Congressional Tech `1c3e9c6d0addfd3c4d15654c3cdb7bba54677a29` with spicy-docs 0.85.0, wheel SHA-256 `d7fe6b185440f0f70330fcce7c5d236f94009d267c05af3619ad0a05c1b08e1f`. The HTML and Web ARChive (WARC) reader files are byte-identical to 0.84.0. The successful nightly associated with live archive release `6c46b8f7a606` pinned the same wheel. The [live body-text pointer](https://congressional-data.spicygov.ai/derived/body_text/current.json) returned HTTP 404 during the closure check.
- The frozen prefix-0 slice reconciled 12,079 bodies to 12,065 texts and 14 named invalid UTF-8 errors. All 12,032 historical texts have current texts. The reader recovered 20 previous parser errors and read 13 bodies that had previously lacked size metadata.
- The complete fixed HTML input reconciled 192,959 bodies to 192,728 texts and 231 named invalid UTF-8 errors, with zero pending. Each error was checked from the archived source and retains its SHA-256, URL and first invalid byte offset. The broader run establishes reading coverage. The 2,929 saved pages are the denominator for the script/CSS acceptance criterion.

## Independent checks

The audit verified archived source hashes, used libxml2 to parse the original HTML independently of the production reader, and compared source code fragments and visible text with the private native export. The same detector found fragments in 2,850 historical saved texts and zero current texts. It probed all 8,942 nonempty script blocks and 577 nonempty style blocks in the saved cohort. For 2,819 pages the normalized visible stream matched exactly. The other 110 retained every visible segment in order alongside additional text. No saved page was near-empty. The export SHA-256 is `31b9037b9f60fd0be162f8eb65b323cb294dae99064053bf2a1b7a9bca8b2c6f`.

A second reviewer verified the original opening statement and reran three planted changes. Reintroducing its JSON-LD script or CSS block triggered the corresponding leak check. Deleting the second occurrence of a visible label triggered the ordered text check. The unmodified rendition passed. The reviewer also independently verified the 231 encoding errors and the HTML/WARC outcome counts.

The maintained producer excludes WARC envelopes following ct-0hay (`1d9bf2d6`). Zero of the 1,768 envelopes matched a saved-body selection. A document captured through WARC uses the extracted payload's own body hash. All 96 historical slice envelopes passed a direct reread, and the audit found zero script or CSS fragments in their rendered payloads.

## Retained evidence

The archive checkout retains the work under `.cache/archive-release/implementation/ct-finish-20261112T2054/`. Verify the principal artifacts with `shasum -a 256 -c evidence.sha256` from its `ct-chc4` directory.

| Artifact | Evidence |
| --- | --- |
| `ct-chc4/freeze.json` and `full-disposition.parquet` | Frozen source identities and outcome for each HTML body and WARC envelope |
| `ct-chc4/native-saved-export/export.parquet` and `raw-audit.jsonl` | Maintained export, saved-body coverage and independent row-level checks |
| `ct-chc4/all-html-error-source-facts.json` and `all-slice-reviewed-short-outputs.jsonl` | All 231 encoding errors and the short-output review |
| `ct-chc4/review/0f75d7721866/plant-receipt.json` and `final-review/html-plant-check.json` | Original, mutated outputs and independent results |
| `final-review/html-disposition-check.json` and `final-review/REVIEW.md` | Independent reconciliation and acceptance |
| `ct-chc4/focused-tests.log` and `storage-loopback.log` | 59 focused producer, reader and export tests and 37 tests in the full storage loopback lane |
