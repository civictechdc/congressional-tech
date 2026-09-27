# Sample XML availability by URL family

## Experiment plan — September 27, 2026

Decision: Identify which PDF/HTML URL families justify targeted XML retrieval.

Hypothesis: XML availability depends on the publishing route and document
family. Replacing a suffix should work for some legislative-text and witness
list families. GovInfo may require changing the format directory as well.
PDF-only attachments and committee web pages may have no XML counterpart.

Arms: Literal extension replacement; a separate format-directory replacement
for GovInfo/GPO package URLs; known meeting/witness XML routes for House event
pages. For extensionless download handlers, request the original address with
an XML Accept header and record the format actually returned.

Cases: Inventory the current Congress.gov meeting export, GPO hearing PDF/HTML
links, collected House and Senate documents, known Senate hearing pages, and
document links in cached House pages and XML. Group by host, route, document
filename family, and source format. Select at most three distinct URLs per
family by a stable hash, spreading dates/Congresses where available. Keep
malformed source URLs in the inventory, without attempting to repair them.

Held constant: Reuse the existing HTTP probe and XML validation. Two requests
to the same host start at least 0.4 seconds apart. Retain requests, outcomes,
and successful XML. Bound the run to three cases per family and no more than
600 new HTTP requests; stop a host after repeated refusals. The previously
stopped full sweep remains stopped.

Decision rule: A complete parse of a non-HTML, non-error XML response proves
availability at the tested URL. Inspect the content to distinguish document
text, meeting/witness data, and package metadata. A negative sample rules out
only those tested addresses; blocks and transport errors remain inconclusive.
Small samples diagnose route behavior and do not estimate corpus-wide rates.

## Results

The inventory contains **354,555 distinct URL strings in 157 families**:
299,608 PDF URLs, 34,559 `.htm` URLs, 8,751 meeting/hearing page URLs, and 11,637
extensionless or handler-based document URLs whose formats cannot be inferred
from their names. Counts include HTTP/HTTPS aliases and multiple hosts serving
the same document; they are URL counts, not unique-document counts.

The bounded plan selected **412 source URLs** and generated **444 candidate
checks**. Of these, **411 were attempted**: 32 returned document XML, 240
returned HTTP 404/410, 62 returned HTML, 32 returned other non-XML content, and
45 were inconclusive (15 blocked, six other HTTP errors, 24 network errors).
Another 33 candidates were deferred after repeated refusals from rules.house.gov.
At least one request was attempted for 145 families. Eleven Rules families
were wholly deferred; the remaining family contains nine malformed source URLs.

No complete inventory sweep was started. The earlier 2,007-check sweep remains
stopped. Its results appear in separate `earlier_*` columns for comparison.

| Family / route | Sample result |
|---|---|
| House event page → meeting XML from an observed document's directory | 3/3 XML, `committee-meeting` |
| Same events → witness-list XML | 2/3 XML, one 404 |
| House `billsthisweek` Rules Committee Prints | 3/3 XML, `amendment-doc` |
| House `billsthisweek` amendment filenames | 2/3 XML |
| House `billsthisweek` bill/resolution filenames | 1/3 XML |
| House meeting-directory Rules Committee Prints | 1/3 XML |
| House meeting-directory `WList` PDFs | 1/3 XML |
| House meeting-directory testimony, witness attachments, biographies, disclosures, votes, transcripts, support documents, amendments, and bills | 0/3 XML in each sampled family; 404 responses |
| Congress.gov `/{congress}/bills/{measure}/{file}.pdf` | 3/3 XML |
| Congress.gov meeting-document Rules Committee Prints | 3/3 XML |
| Congress.gov meeting-document other committee prints | 1/3 XML |
| GovInfo BILLS and CPRT package URLs: suffix change alone | 0/3 in each family; HTML responses |
| Same GovInfo BILLS and CPRT samples: change `/pdf/` to `/xml/` and `.pdf` to `.xml` | 3/3 in each family; BILLS gave `bill`/`resolution`, CPRT gave `amendment-doc` |
| GovInfo CHRG hearing HTML/PDF and CRPT reports | Neither suffix-only nor format-directory changes produced XML in the three samples per family |
| Legacy GPO `/fdsys/pkg/` BILLS URLs, changing directory and suffix | 3/3 XML after redirect to GovInfo |
| Legacy GPO CPRT URLs, changing directory and suffix | 1/2 XML after redirect to GovInfo |

The 32 successful responses contain five roots: `amendment-doc` (15), `bill`
(8), `resolution` (3), `committee-meeting` (3), and `witness-list` (3). The
GovInfo CPRT examples were inspected: they contain Rules Committee Prints with
structured legislative text, rather than package metadata.

The useful discovery is the **format-directory rule**. A failed
`/pdf/{package}.xml` is not evidence against `/xml/{package}.xml`. For example:

```
https://www.govinfo.gov/content/pkg/CPRT-118HPRT54293/pdf/CPRT-118HPRT54293.xml  → HTML error
https://www.govinfo.gov/content/pkg/CPRT-118HPRT54293/xml/CPRT-118HPRT54293.xml  → amendment-doc
```

This is consistent with GovInfo's [bill XML documentation](https://www.govinfo.gov/help/bills).
The negative samples establish only that the tested transformations failed on
those URLs. They do not prove a document is unavailable as XML through every
route. Filename families are discovery categories, not authoritative document
types. No reader or production acquisition policy was changed.

## Reproduce and inspect

```bash
# Build the inventory and bounded plan, without making network requests:
python docs/youtube-coverage/research/scripts/xml_path_families.py

# Execute that plan; reruns reuse this experiment's retained outcomes:
python docs/youtube-coverage/research/scripts/xml_path_families.py --run

# Rebuild the family table from saved results, without network requests:
python docs/youtube-coverage/research/scripts/xml_path_families.py --report
```

- [`data/xml_path_families.csv`](data/xml_path_families.csv): all 157 families,
  counts, path templates, current sample results, and separate earlier evidence.
- [`data/xml_path_family_samples.csv`](data/xml_path_family_samples.csv): each
  source URL, attempted transformation, status, root, final URL, and retained
  response location.
- `~/hearing-text/xml_path_families/`: complete inventory, source digests, cached
  input manifest, frozen request plan, append-only attempts, results, summary,
  successful XML, and error-page bodies/excerpts. Non-200 response excerpts are
  bounded at 64 KiB. `amendment_doc_urls.txt` lists the verified final URLs from
  both experiments with an `amendment-doc` root.
