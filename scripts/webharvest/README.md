# Web Harvest commands

The [Library of Congress Web Harvest](https://webharvest.gov/) saved copies of House and Senate committee websites. Committee pages and PDFs that disappeared from the live web are often still in that archive.

These commands look up those copies, fetch a bounded set of them, and decide whether a saved page is a real document. They do not import files into the raw archive and they do not publish the filename viewer. Import is a separate step under [`scripts/corpus_recovery`](../corpus_recovery/README.md).

The domain map and the notes on how a Web Harvest prefix is built live in [`docs/data/webharvest-committees/README.md`](../../docs/data/webharvest-committees/README.md). A prefix is only a place to look. A homepage capture does not prove that a PDF was saved.

Run from the repository root:

```bash
.venv/bin/python scripts/webharvest/webharvest_committee_map.py lookup \
  'https://energycommerce.house.gov/path/file.pdf' --congress 118
```

## Commands

**`webharvest_committee_map.py`** builds and queries the map from committee index pages to Web Harvest redirect prefixes. `lookup` prints candidate archive URLs for one original file URL. `build` rebuilds the map from saved pages. A lookup result is a candidate, not a verified PDF.

**`webharvest_cdx.py`** holds the CDX helpers the index commands share. A CDX row is one line in a web-archive URL index (URL, timestamp, status, digest). This file is a library for the other scripts in this folder, not a campaign you run by itself.

**`webharvest_index_remaining.py`** audits a snapshot of URLs that are still missing. It reads retained search results. It does not download, call a proxy, or edit the catalog. A complete search that found nothing counts as a negative. An incomplete search can only suggest a lead.

**`webharvest_index_leads.py`** reads a finished index audit and lists extra PDF filename leads to investigate.

**`webharvest_recovery.py`** fetches approved Web Harvest HTML into a local receipt directory. You pass an explicit queue. A URL that appeared in an older queue is not treated as done. The command plans, paginates, acquires, aggregates, and qualifies. It stops at local receipts.

**`webharvest_validation.py`** checks fetched HTML and PDFs before anyone treats them as recovered documents. HTML must look like document text rather than a challenge page, a rate-limit page, or an empty shell. A PDF must pass both a pypdf stream check and a full-page Poppler render. Passing validation still does not import the file.
