# Maintained recovery commands

`scripts/webharvest_recovery.py` promotes the retained-first requests and content
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
  "workers": 5,
  "delay_seconds": 1
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

## Durable evidence and qualification

Each run writes an immutable `plan.json`, `validator/validator.json`, frozen
`validator/classifier.py`, one `downloads/<id>/started.json` before admission,
and one `downloads/<id>/download.json` after retaining the response bytes.
Each queue group then writes an immutable `requests/<id>/receipt.json`.
A completed download can finish classification after interruption without
requesting the URL again. A started request without a complete download stays
`review-required`; resuming never repeats an unknown in-flight request.
Challenge/rate-limit stops also remain stopped on resume.

Only compact `progress.json` counters change during acquisition. At exit the
command aggregates completed receipts once into `results.json`. Reconstruct
lost counters and aggregate output without acquiring anything:

```sh
python scripts/webharvest_recovery.py aggregate --receipts run-directory
```

The request receipts are authoritative; partial aggregate output is disposable.
The classifier cache key combines body SHA-256 with the frozen validator identity,
which includes classifier source and qualification configuration. Full extracted
text and links are stored once in the cache. Every result links and hashes that
cache entry. Changing a body, classifier, or configuration requires a new cache
identity; resuming an existing run uses its frozen classifier bytes. Historical
worker script bytes may change after their completed receipts were produced.

One configurable qualifier replaces dated snapshot copies:

```sh
python scripts/webharvest_recovery.py qualify --source completed-receipt.json --source another-receipt.json --deferred deferred.json --kind pdf --receipts qualification-directory
```

It verifies each source receipt's current bytes and records their SHA-256,
verifies body length and SHA-256, applies deferred URL/body exclusions, and
validates completed HTTP-200 bodies. It qualifies completed receipts without
claiming their workers finished. Use `--kind html` for the frozen HTML classifier
and source-identity checks. Output preserves original URLs, candidate/source
URLs, provider metadata, and rendered-copy provenance; the full original receipt
remains linked by path and hash. PDF qualification establishes decodable content;
source URL linkage remains explicit in the receipt and does not establish archive
byte identity or approve publication.

PDF acceptance keeps both existing checks: pypdf decodes every page's content
streams and Poppler renders every page at low resolution. `pdfinfo` must also
succeed and the terminal PDF marker must exist. `--preview` optionally renders
the first page as an image; its failure does not change acceptance. Text
extraction no longer repeats during acceptance. The retained
`numeric-operand.pdf.gz` and `malformed-text-array.pdf.gz` fixtures confirm that
historical text-parser failures can still decode/render; truncating those bytes
fails validation. No decoder checks were removed.

The validator snapshot also saves the PDF acceptance implementation as
`validator/validation.py` and hashes it into the cache identity. PDF qualification
executes that saved implementation, so maintaining current code cannot silently
change an existing qualification run. Reclassification uses a new directory and
therefore a fresh version/configuration identity.

The retained 961-group scaled-02 results require 4,650,859,909 logical JSON bytes
when every full prefix is serialized, compared with 9,074,518 bytes for one
final aggregate. This 512.5-fold comparison measures aggregate serialization
only; immutable receipts, cache files, and compact counter writes are additional
linear writes. See `acquisition-serialization-evidence.json` for the source hash
and scope. The offline write-count probe verifies one aggregate write across
20 queue groups. No wall-clock speed or physical allocation claim is made.

## Bounded parallel admission

`workers` accepts one through five. Firecrawl defaults to five workers and a
one-second minimum global request-start interval; direct and retained modes
default to one worker and a thirty-second interval. Set `delay_seconds` explicitly
for a reviewed campaign. Each worker uses its own requests session. The global
start clock applies across workers; the finite request grant counts distinct
replay URLs. Alias groups share their download and classification cache.

Both provider HTTP status and target `origin_status` can stop admission. A
refusal stops new requests, drains already admitted workers, and remains stopped
on resume. Workers waiting for their start slot record a review disposition
without sending a request. A cookie from `cookie_env` goes to the direct target
request, or into Firecrawl's target-request `headers` field. It is never attached
to the API-origin request headers or written into a receipt.

Prior aggregate files are read and hashed once per source file during planning.
Each row reuses that source digest; the offline probe checks one read for a
hundred prior receipts. Parallel classifier calls serialize per body/validator
cache key, preserving one extraction when different URLs return identical bytes.
