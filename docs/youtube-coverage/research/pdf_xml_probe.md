# XML counterparts of collected House PDF links

Started September 27, 2026. For every distinct PDF URL in
`data/house_documents_found.csv`, try the same address with its final `.pdf`
extension changed to `.xml`. This includes external hosts linked from that
file. It does not yet cover every document in the Congress.gov meeting export
or every link on the cached House pages.

The input snapshot contains 18,170 PDF references and 17,991 distinct PDF URLs.
The first 300 checks returned three valid XML documents (all with an
`amendment-doc` root), 289 HTTP 404/410 responses, and eight HTML responses.
The user stopped the full pass after 2,007 checks: 13 valid XML documents,
1,948 missing files, 43 HTML responses, two invalid source URLs, and one network
error. The remaining 15,984 URLs were not checked. The pass remains stopped;
the later [family sample](xml_path_families.md) uses a separate bounded plan.

Run or resume:

```bash
python docs/youtube-coverage/research/scripts/pdf_xml_probe.py
```

The script uses two workers and spaces requests to each host at least 0.4
seconds apart. It pauses that host on HTTP 403/429, and leaves its remaining
URLs pending after three consecutive refusals. `--retry` also repeats
previously blocked, failed, or oversized requests. `--input` accepts another
document CSV with a `url` column and can be repeated. `--limit` bounds a sample
of the remaining URLs. A lock prevents overlapping runs in the same cache.

Results are saved under `~/hearing-text/pdf_xml_probe/`:

- `sources.json`: source paths and SHA-256 digests for the input snapshot.
- `inventory.jsonl`: every PDF URL and the rows that supplied it.
- `attempts.jsonl`: an append-only record of completed attempts.
- `results.csv`: the latest outcome for each checked PDF URL.
- `summary.json`: counts, pending URLs, inconclusive outcomes, and run status.
- `xml/`: downloaded XML files; results record their paths, digests, and root
  elements.
- `run.json` and `run.log`: the detached full pass's process receipt and output.

A successful check requires HTTP 200 and a complete XML parse. HTML and XML
error responses do not count as document XML. The parser does not load external
DTDs, expand external entities, or access the network. HTTP errors and network
failures remain separate from missing files. Downloads are bounded at 20 MiB.
The check establishes availability and XML syntax; it does not establish that
the XML's content is equivalent to the PDF.

This pass changes only the extension. For example, GovInfo may require a
different directory for XML; the probe records the literal sibling attempt
without treating it as proof that no XML exists anywhere for the document.
