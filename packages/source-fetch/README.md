# Congressional source fetcher

`source-fetch` provides the reqwest HTTP pool for `raw-source-sync`. Python owns
URL checks, direct-first fallback decisions, source-body validation, receipts,
retry state, and catalog rebuilding. Existing readers and recovery tests share
those rules.

```sh
cargo build --release --locked --manifest-path packages/source-fetch/Cargo.toml --bin source-fetch
raw-source-sync --fetcher-binary packages/source-fetch/target/release/source-fetch \
  --transport auto --files-per-second 60 --workers 80 --limit 5000
```

Use the existing R2 credentials and `ZYTE_TOKEN` environment variables. The
workflow builds the worker and supplies these settings. `auto` tries direct
requests first, then Zyte once for failed or unusable captures. Manual `direct`
and `zyte` overrides remain available. New files use one shared
60-starts-per-second limiter. Redirects and one fallback continue the same file
without spending another slot. `--requests-per-second` remains an alias for
`--files-per-second`, with this file-based meaning. Up to 80 source
tasks can run concurrently; archive writes and source latency may lower actual
throughput. Retained-body inspection does not fetch a publisher again.

The native process reads one JSON request per stdin line and emits one response
per stdout line, identified by a numeric request ID. Request fields are `id`,
`url`, `transport` (`direct` or `zyte`), `max_bytes`, optional `headers`, and
`new_file` (defaults to `true` for older callers). Python sets `new_file=false`
only for a file's redirects and fallback.
Responses contain metadata and a bounded body-file path in the parent-supplied
temporary directory. The parent removes each file after consumption. Tokens stay
in the inherited environment and are never serialized into this protocol.
Network failures produce capture results; process or disk failures stop the run.
The worker drains its in-flight requests when stdin closes.

Automatic redirects and retries are disabled. Python checks each redirect before
sending the next request. All requests still share the concurrency limit. Known
HTTP links on `docs.house.gov` start directly at HTTPS: receipts preserve the
original `requested_url`, record the upgraded `request_url`, and retain only
redirects actually observed. Requests have a 15-second connect timeout, a
90-second read timeout, and a 120-second total deadline. Bodies stream to disk rather than remaining
buffered for every active request in the native process. Compressed bodies are
decoded within the body-size limit while retaining the original response headers.

Run the checks:

```sh
cargo test --release --locked --manifest-path packages/source-fetch/Cargo.toml
cargo clippy --release --locked --manifest-path packages/source-fetch/Cargo.toml -- -D warnings
SOURCE_FETCH_BINARY="$PWD/packages/source-fetch/target/release/source-fetch" \
  python -m pytest -q tests/test_rust_fetch.py tests/test_rust_fetch_native.py
```

Native integration tests use only a loopback HTTP server. They exercise
concurrency, rate limiting, redirects, header retention, and body truncation.

`reqwest-fetch-bench` retains the earlier six-URL timing experiment as a separate
binary; it does not drive CI acquisition. Its settings are in `experiment.md`.
To repeat that original experiment:

```sh
ZYTE_ENV_FILE=/path/to/RefSpec/.env cargo run --release --locked \
  --manifest-path packages/source-fetch/Cargo.toml --bin reqwest-fetch-bench \
  -- .cache/reqwest-benchmark both 3
```

The benchmark output directory must be new. It records response bodies, status,
size, checksum, timings, and failures. The [reqwest client documentation](https://docs.rs/reqwest/0.13.5/reqwest/struct.Client.html)
describes its shared connection pool.
