# B2 local component checks

The focused offline group passed 114 tests in 3.32 seconds at `be8605b0`: the new fetcher, receipt writer and archive expander, existing archive-member and sniff cases, and the responsibility import fences. Adapters used local files and fake HTTP responses; no live capture, storage write, credentials or Docker were used. This is component evidence; F2 switching and native transport qualification remain separate.

The large-transfer fixture retained 70 MiB using reads of at most 1 MiB. It checks byte retention and chunk size, not peak process memory. Provider JSON and decoded bytes share the explicit disk quota. A read-only mapping lets the standard JSON parser validate bounded provider metadata while base64 chunks decode to disk; ordinary JSON stream parsers emit a whole string and cannot bound that scalar.

Run the same group with:

```sh
.venv/bin/python scripts/dev.py test --path packages/congress_api/tests/test_raw_fetcher_contract.py --path packages/congress_api/tests/test_receipt_writer_contract.py --path packages/congress_api/tests/test_archive_expander_contract.py --path packages/congress_api/tests/test_archive_members.py --path packages/congress_api/tests/test_engine_first_sniff.py --path packages/congress_api/tests/test_congress_api_imports.py production-offline
```

The initial contract run had 30 expected missing-component failures. One implementation checkpoint also failed two provider mmap-close checks; `c5d61d9e` releases the regex iterator's exported buffer and the accepted rerun passes. Earlier commit messages misstated source line counts: the actual `sniff.py` change was 182 to 200 lines, and `c5d61d9e` changed `raw_adapters.py` from 209 to 216 lines. No prior commit was rewritten.

DM §5.2 now names optional stable-code fields: line `error_type` and capture `sniff_error`. Resource failures still propagate for retry; they never become PDF damage verdicts. Provider redirect control and already-decoded response bytes follow the [Zyte HTTP API reference](https://docs.zyte.com/zyte-api/usage/reference).
