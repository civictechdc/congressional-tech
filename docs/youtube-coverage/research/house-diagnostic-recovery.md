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

The research script `scripts/probe_house_sites.py --requests manifest.json --output-dir new-evidence-directory` uses the shared HTTP client and discovery parser. It makes one top-level attempt per request, groups work by host, and retains response prefixes and their completeness flags in a new directory. It preserves the full request through interpretation and keys body files by URL and POST body. It does not write collection state, follow discovered targets, or import responses into the archive.

For an explicitly authorized collection recovery, add `--retry-requests manifest.json` to the existing House collector invocation with its normal committee directory, state directory, output directory, workers and rate. Stop any other collector using that state first. This mode:

- Requires every target to match an exact saved failure in an official committee site.
- Uses the existing scheduler, transport, parser, receipts and exports.
- Adds no seeds, follows no newly discovered requests, and leaves unrelated failures alone.
- Leaves discovery completion dates and pagination fingerprints unchanged.
- Preserves pending targets when a budget or graceful stop ends a run. Resume with the same manifest; an ordinary crawl or changed manifest is rejected while that bounded queue remains pending.
- Skips already resolved targets when the same manifest is reused. A completed target that failed again is not repeated when resuming the remaining pending targets.

The result reports `failed` for the selected targets and `retained_failed` for all failures on their sites. Historical failures on other sites do not determine the bounded run's outcome. Retry mode cannot be combined with `--site`, `--offline` or `--reparse`. Applying parser changes to existing bodies is a separate offline reparse operation.

The shared listing predicate recognizes the terminal `/committee-activity` route. It prevents child-card dates and the generic page heading from becoming an event identity. Explicit event IDs and child detail routes remain eligible. During offline reparse, these listings move into retained discovery sources with their original bodies and receipts; their false event rows and associated event-document rows disappear from exports. Literal links remain in the retained HTML. This correction is not a recovery of new events.
