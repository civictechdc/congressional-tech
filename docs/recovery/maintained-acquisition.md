# Maintained recovery commands

`scripts/webharvest_recovery.py` promotes the sequential requests and content
checks from `recover_nara_html_continuation_04.py` and
`recover_firecrawl_nara_scaled_02.py`. It acquires only exact indexed HTML replay
URLs. It never imports, publishes, or selects new targets. Run it against an
explicitly reviewed queue; a generated plan alone does not approve acquisition.

```sh
python scripts/webharvest_recovery.py plan --queue queue.json --prior prior-receipt.json --deferred deferred.json --output dispositions.json
python scripts/webharvest_recovery.py pagination --pages retained-index-pages.json
python scripts/webharvest_recovery.py acquire --queue approved-queue.json --config acquisition-config.json --receipts run-directory
```

All paths are explicit. Queues contain groups with `original_urls` and
`candidates`; the first candidate is the approved target. Keep its source index
metadata, digest, and `match_basis`. `plan` writes one disposition per original
URL: `qualified`, `terminal-content`, `review-required`, `retryable-failure`, or
`active-reservation`. All prior attempts remain ineligible, including retryable
failures; an operator must approve a separate retry queue. Unattempted entries
have `eligible: true`. Deferred originals and body hashes remain excluded.
Use the frozen 164-entry deferred file, identified by hash in the failure ledger.

A reservation JSON file contains `process` (the exact `pid` and
`start_and_command` returned by `process_identity`) and `original_urls`.
The operating system start time and command protect against PID reuse; a file
lock prevents two workers from using one receipt directory. A missing process
is not proof that an attempted target succeeded.

Configuration example (values are review inputs, not permission to spend):

```json
{
  "provider": "firecrawl",
  "credential_env": "FIRECRAWL_API_KEY",
  "cookie_env": "WEBHARVEST_COOKIE",
  "deferred": "/explicit/path/to/accepted-files.json",
  "budget_usd": 25,
  "spent_to_date_usd": 24,
  "max_requests": 1,
  "request_ceiling_usd": 1,
  "max_body_bytes": 8388608,
  "delay_seconds": 30
}
```

Use a conservative request cost ceiling and include existing campaign spend;
configuration fails if the proposed maximum exceeds the existing $25 cap.
Credentials come only from the named environment variables. Receipts omit secret
headers and exception messages. `provider` also accepts `direct` or `retained`.
Retained queue groups add `retained` with `body_path`, `bytes`, `sha256`,
`status`, `complete`, `final_url`, `evidence`, and optionally `rendered_copy`.
Retained bodies must match the supplied length and hash. Direct bodies must
match the archive index SHA-1 digest. Rendered copies preserve their provider
and original source metadata and never claim byte identity with the archive.
Media types are rejected; no media acquisition mode exists.

Pagination pages explicitly contain `cursor`, `continuation`, and `complete`.
Start at `cursor: null`; follow every continuation to a page declaring
`continuation: null, complete: true`. Missing pages, missing metadata, or cycles
remain incomplete regardless of result count. This command checks retained
pagination evidence and performs no index queries.

`scaled01-unsuccessful-dispositions.json` inventories all 45 unsuccessful
scaled-01 groups: 17 challenges remain retryable but unapproved, 15 historical
"no prepared statement" results are terminal content, and 13 empty/short
results require review. Each entry identifies and hashes its original receipt.
