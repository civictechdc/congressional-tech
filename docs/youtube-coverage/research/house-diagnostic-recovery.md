# House diagnostic recovery

Probe a reviewed list of literal requests before deciding which saved failures to retry. A successful HTTP response establishes availability; it does not establish a new event, a unique event, or a verified document file.

Both the probe script and `house_sites --retry-requests` accept a JSON list:

```json
[
  {
    "site": "energycommerce.house.gov",
    "request": {
      "url": "https://energycommerce.house.gov/api/events",
      "kind": "calendar_api",
      "body": {"limit": 20, "offset": 1120, "sort": ["startDatetime:asc"]},
      "discovered_from": "https://energycommerce.house.gov/api/events"
    }
  }
]
```

Copy the entire original `errors[key].request`, including its parent and POST body. Extra review fields alongside `site` and `request` are allowed. Never reconstruct a request from its URL alone: calendar offsets share a URL.

For a retained HTTP 404/410 observation without an error row, use its source URL and kind and the exact POST body encoded in its source key. The collector validates that this key identifies the saved unavailable observation; it does not create a synthetic failure to admit it.

The research script `scripts/probe_house_sites.py --requests manifest.json --output-dir new-evidence-directory` uses the shared HTTP client and discovery parser. It makes one top-level attempt per request, groups work by host, and retains response prefixes and their completeness flags in a new directory. It preserves the full request through interpretation and keys body files by URL and POST body. It does not write collection state, follow discovered targets, or import responses into the archive.

For an explicitly authorized collection recovery, add `--retry-requests manifest.json` to the existing House collector invocation with its normal committee directory, state directory, output directory, workers and rate. Stop any other collector using that state first. This mode:

- Requires every target to match a saved failure or unavailable observation in an official committee site.
- Uses the existing scheduler, transport, parser, receipts and exports.
- Adds no seeds, follows no newly discovered requests, and leaves unrelated failures alone.
- Leaves discovery completion dates and pagination fingerprints unchanged.
- Preserves pending targets when a budget or graceful stop ends a run. Resume with the same manifest; an ordinary crawl or changed manifest is rejected while that bounded queue remains pending.
- Skips completed targets when the same manifest is reused, including those still unavailable or failed. A different reviewed manifest can explicitly select another pass after the first queue drains.
- Reports excluded document and malformed routes without fetching their files.

The result reports `failed` for the selected targets, `retained_failed` for all failures on their sites, and `excluded` for targets rejected by existing page-admission rules. Historical failures on other sites do not determine the bounded run's outcome. Retry mode cannot be combined with `--site`, `--offline` or `--reparse`. Applying parser changes to existing bodies is a separate offline reparse operation.

For authorized proxy recovery, add `--zyte-fallback`. This preserves direct acquisition first and makes at most one explicit Zyte attempt after a transport failure or unsuccessful publisher response. Direct HTTP 200 skips the proxy. Existing direct transport retries and global pacing remain in force. This flag is mutually exclusive with `--zyte`, which retains its existing forced-proxy behavior.

Both transports leave receipts with their original URL, POST body, response bytes, and selected-response flag. Provider API status is separate from publisher status. A failed provider call cannot replace a complete direct 404/410; a successful publisher response through Zyte can. Refusals remain failures. The selected receipt supplies the retained body's digest and timestamp. Bounded retries preserve distinct previous source and page bodies in `sources[key].content_history`, and record `retry_request` and `retry_selection` to resume without repeating completed requests. They do not download document links, merge event identities, or follow newly discovered pages.

If a selected failure fails again, its exact previous diagnostic moves into `error_history[key]`; the new diagnostic remains current in `errors[key]`. This preserves error history without claiming that a recurring failure was resolved.

The shared listing predicate recognizes the terminal `/committee-activity` route. It prevents child-card dates and the generic page heading from becoming an event identity. Explicit event IDs and child detail routes remain eligible. During offline reparse, these listings move into retained discovery sources with their original bodies and receipts; their false event rows and associated event-document rows disappear from exports. Literal links remain in the retained HTML. This correction is not a recovery of new events.
