# Web Harvest committee domain map

The published-prefix map covers all 20 House and Senate committee index pages linked from the [118th Congress House committee page](https://webharvest.gov/collections/congress118th/house_committees.html): Congresses **109–118**, **602 listings**, **600 distinct archive links**, and **161 distinct domains**. The sources were retrieved on October 14, 2026.

This maps the domains listed by Web Harvest. It does not inventory every domain or file held inside each collection. Listed joint committees, minority sites, commissions, and task forces are included where the source pages provide them.

## Files

- [`domain-prefixes.json`](domain-prefixes.json): `domain -> Congress number -> list of published redirect prefixes`. Lists preserve multiple prefixes for the same domain and Congress.
- [`map.json`](map.json): full records, committee names, chamber, category, exact published links, original embedded URLs, source locations and hashes. `by_domain` and `by_congress` contain record IDs into `records`.
- [`manifest.json`](manifest.json) and [`sources/`](sources/): retained HTML, response receipts, SHA-256 hashes, retrieval times and per-page counts.
- [`redirect-checks.json`](redirect-checks.json): direct header checks for one homepage per chamber/Congress, stopped on HTTP 429 after 11 successful responses.
- [`direct-sequential-checks.json`](direct-sequential-checks.json): later direct retries resolved all three tested links (118th Agriculture, 117th Appropriations, 109th Agriculture), with at least 15 seconds between attempts. Appropriations needed one retry after a connection error.
- [`observed-domain-prefixes.json`](observed-domain-prefixes.json): the smaller subset of prefixes observed in the successful direct redirects or capture headers, including the later sequential checks. This is intentionally separate from the complete published map.
- [`zyte-redirects/summary.json`](zyte-redirects/summary.json): Zyte proxy resolution stopped on a rate-limit page; no capture prefix was resolved in that run. The remaining 599 distinct links were not attempted in that run.
- [`zyte-probes/`](zyte-probes/): earlier proxy and browser diagnostics. HTTP 200 responses containing a rate-limit page are failures, not archived pages.
- [`backlog-summary.json`](backlog-summary.json): the pinned local PDF-backlog join, input hashes and unmatched-domain counts.

## How to use a prefix

Append the **complete original file URL**, including its scheme, path and query:

```text
prefix:   https://www.webharvest.gov/congress118th/3/
original: https://agriculture.house.gov/path/file.pdf
candidate:https://www.webharvest.gov/congress118th/3/https://agriculture.house.gov/path/file.pdf
```

`3`, `2014`, `2016`, and `2020` are selectors supplied by the archive, not complete capture timestamps. Fourteen-digit selectors identify a timestamp requested by the published link; Web Harvest may redirect to another capture. Older pages sometimes omit the original scheme. The map preserves that literal source text and separately records the HTTP assumption used to index it.

A homepage capture timestamp does not establish that a PDF was captured. A successful redirect only supplies another lookup location. PDF recovery still requires fetching the document, rejecting archive error/challenge pages, validating its contents, and retaining its original URL and archive provenance.

## Lookup commands

Run from the repository root with its existing Python environment:

```sh
.venv/bin/python scripts/webharvest_committee_map.py lookup \
  'https://energycommerce.house.gov/path/file.pdf' --congress 118
```

Omit `--congress` to search every mapped Congress, newest first. The file path and query remain unchanged. The listed source scheme is offered as a separately labelled variant when it differs. `--include-www` also offers separately labelled `www` variants. The lookup does not invent committee renames, rewrite filenames, or infer a document's Congress from its path.

Rebuild entirely from retained source pages:

```sh
.venv/bin/python scripts/webharvest_committee_map.py build --offline
```

Use `build --output NEW_DIRECTORY` for a fresh source snapshot. Existing retained pages are reused and checked against their hashes.

Resolve homepage redirects through Zyte into a **new directory**, using `ZYTE_TOKEN` in the environment or a supplied environment file and a trusted CA bundle that includes the Zyte certificate:

```sh
.venv/bin/python scripts/webharvest_committee_map.py resolve-zyte \
  --env-file /path/to/provider.env \
  --ca-bundle /path/to/zyte-ca-bundle.pem \
  --output output/webharvest-redirects-new
```

The resolver uses [Zyte proxy mode](https://docs.zyte.com/zyte-api/usage/proxy-mode.html) with automatic redirects disabled so it can retain each observed location. It stops on rate-limit or access-verification responses and writes a separate resolved-prefix map. It does not change the complete published map or fetch PDFs. The October 14 proxy probes, including browser mode and a U.S. proxy request, remained rate-limited.

## Local PDF-backlog result

The join read the frozen 7,451-URL local backlog and excluded the 1,386 URLs recorded in the local recovery result. This is a local snapshot, not a fresh cloud-catalog availability audit.

| Measure | Count |
| --- | ---: |
| Remaining URLs with a `.pdf` path suffix | 4,721 |
| PDF URLs whose domain appears in the map | 319 |
| Candidate archive URLs across mapped Congresses and labelled variants | 2,750 |
| PDF URLs without a listed domain match | 4,402 |
| Other remaining URLs, including extensionless downloads | 1,344 |

All 319 matched PDFs have an exact-domain match; `www` variants add lookup options without increasing that count. The largest unmatched groups are `oversightdemocrats.house.gov` (1,379), `democrats-science.house.gov` (1,145), and `d1dth6e84htgma.cloudfront.net` (912). An unmatched domain does not prove the archive lacks those documents.

Generated local outputs are in `output/webharvest-committee-lookups/`: `pdf-candidates.jsonl`, `unmatched-pdfs.jsonl`, and `lookup-summary.json`. Recreate them with:

```sh
.venv/bin/python scripts/webharvest_committee_map.py join \
  --targets .cache/document-bulk-recovery-20261014T1552Z/targets.csv \
  --exclude-recovered .cache/document-bulk-recovery-20261014T1552Z/publication-1386/recovered.json \
  --include-www --output output/webharvest-committee-lookups
```

The summary pins both input files and the map with SHA-256. No downloader, cloud catalog, or retained-source state was changed by the mapping or join.

Validation: 16 focused tests passed, including reproduction of every mapped record from retained HTML, legacy URL formats, path/query preservation, shared domains, explicit variants, exclusions, and rejection of HTTP 200 block pages.
