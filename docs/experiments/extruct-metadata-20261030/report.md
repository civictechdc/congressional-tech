# Retained HTML metadata audit

2026-10-30 · `extruct==0.18.0` · analysis only

**Adopt `extruct` as an additional extraction step. The clearest benefit is better hearing-listing interpretation, followed by richer article, update, identity, and preview metadata.** Keep the existing domain-specific parsing and preserve disagreements between the metadata and the displayed page.

This audit examined **185,698 distinct retained HTML bodies, totaling 14.36 GB**, from the selected archive snapshot. It also inspected archived web responses. The current congressional parser uses **lxml**, rather than BeautifulSoup, and already retains raw HTML and JSON-LD script text. The gap is partly interpretation and normalization, not loss of the original evidence.

## Most valuable findings

### 1. Hearing microformats expose a current listing-parser problem

Microformats are semantic annotations in ordinary HTML classes. `extruct` found `h-event` on **51 bodies** across Appropriations, Banking, Budget, and Finance in the Senate, plus House Budget. The 49 Senate bodies contain **1,225 event entries representing 1,022 distinct declared event URLs**. These are retained versions, not 1,225 newly discovered hearings.

Running the current Senate listing parser on those same 49 bodies produced this comparison:

| Check | Entry occurrences |
|---|---:|
| Microformat entries matched to an existing parsed URL | 1,191 |
| Matching date | 253 |
| Date disagreement | 938 |
| Disagreements where the microformat date agrees with the displayed row date | **936** |
| Entries with room information in the existing listing-details parser | 883 |
| Entries with time information in that parser | **0** |

A retained [Appropriations listing](https://www.appropriations.senate.gov/hearings) shows the practical failure. The education hearing is April 28, 2026. The following Sergeant at Arms/Capitol Police hearing is April 22. The current parser assigns April 28 to that second entry; the row text and microformat both say April 22. Its row-specific logic looks for a particular table-cell class, misses this template, and falls back to proximity to another date.

This affects listing discovery dates, cutoff filtering, and potentially pagination. It does **not** establish that stored hearing identities have those wrong dates: the acquisition code separately requires the hearing page's own event date.

Metadata also has defects. Across the Senate sample, **177 time elements encode an hour before noon while their visible text says PM**. For example, `datetime="2026-04-22T03:00"` accompanies `04/22/26 03:00PM`. These timestamps have no timezone. Two microformat dates also disagree with the visible row date.

**Recommended change:** use the semantic event boundary to associate each link, date, location, and time. Compare encoded timestamps with displayed text, retain conflicts, and apply source-specific timezone rules only when justified. This is a focused improvement to listing extraction, not a reason to trust every encoded date.

Evidence: body SHA-256 `01d7cbfd2adc71286e7de804014766ab08e5e2b81867499519d6b500ddd8c7e6`; [comparison results](../../../output/extruct-metadata-20261030/hearing-microformat-comparison.json); [current listing parser](../../../packages/congress_api/src/congress_api/parsers/senate.py); [acquisition consumer](../../../packages/congress_api/src/congress_api/acquisition/senate.py).

### 2. Explicit article/testimony boundaries are available

**4,180 bodies not flagged as error responses contain RDFa article content**, principally `content:encoded`. RDFa attaches named properties to HTML elements. On Veterans' Affairs witness-testimony pages, it identifies the testimony content and its title, apart from site navigation. For example, [Ms. Rose Elizabeth Lee's testimony](https://veterans.house.gov/witness-testimony/ms-rose-elizabeth-lee-0) carries a titled content block.

The words already exist in retained HTML and may already appear in extracted text. The additional value is the publisher-declared content boundary, useful for cleaner testimony text and document classification. This audit establishes availability; it does not measure improvement over every current text-extraction path.

Evidence: body `0000cc0e4a394b6b6a7e16845ba1f8ce511ade463eedfdcab585a568069981da`; [RDFa examples](../../../output/extruct-metadata-20261030/rdfa-content-examples.json).

### 3. Preserve page identity, updates, and classification explicitly

Counts below apply to bodies not flagged by the HTTP-status/title error checks. Fields overlap, and their presence does not mean they are new facts.

| Available information | Bodies | Practical use and limitation |
|---|---:|---|
| Open Graph `article:modified_time` | 5,603 | Publisher-declared page update; separate from hearing date |
| JSON-LD `dateModified` | 2,236 | Same use; may reflect a site migration or template update |
| Canonical link or Open Graph page URL | 25,868 | URL identity evidence; validate redirects and host changes |
| Organization social links | 2,017 | Committee identity and related channels |
| Structured Article/NewsArticle/BlogPosting | 78 | Distinguish advisories and press releases from hearing pages |
| Repeated Open Graph keys | 140 | Preserve all values, including multiple subject tags |
| Open Graph image | 55,856 | Preview candidates; many are generic site images |
| Twitter card fields | 56,733 | Additional preview declarations |

Canonical links and generic Twitter/citation meta tags were collected by a small supplementary lxml pass. They are not all separate formats supported directly by `extruct`.

An [Indian Affairs oversight page](https://www.indian.senate.gov/hearings/oversight-hearing-high-risk-indian-programs-progress-and-efforts-addressing-gaos/) declares publication in 2017, modification in 2025, and committee social accounts. The current parser correctly gets the hearing date and four witnesses, while retaining the JSON-LD as an uninterpreted string. Normalizing the update and organization fields would add useful information without changing the event date.

A [Ways and Means hearing advisory](https://waysandmeans.house.gov/hearing-advisory-chairman-brady-announces-hearing-on-the-2013-medicare-trustees-report/) declares `Article`, section `Hearing Advisory`, publication date, word count, and author `admin`. The section is useful; `admin` is not a witness. Another House Intelligence page declares URLs on an `admin-intelligence.house.gov` host. Publisher declarations need validation before becoming preferred URLs or people.

The current generic archive reader already discovers many links and some publication dates. The additional value is retaining their types, relationships, multiplicity, and source, rather than claiming all these values were previously absent.

### 4. Some apparently rich metadata mostly corroborates existing extraction

- **Person microformats on 2,042 bodies:** Banking's Powell hearing includes committee officials alongside the witness. The current parser already identifies Jerome H. Powell, his title, and organization. Promoting every `h-card` to a witness would introduce false witnesses.
- **Video microdata on 39 bodies and broadcast events on seven:** useful retained fallbacks for duration, thumbnails, and broadcast times. The YouTube API path already stores duration and live-streaming details.
- **JSON-LD Event:** the sole such body in the filtered set is an external OHCHR Universal Periodic Review page, not a congressional hearing. Most congressional JSON-LD describes WebPage, WebSite, and Organization.
- **GovInfo transcript HTML:** 34,783 bodies in that family yielded almost no embedded metadata. Only two had any of the six formats. Transcript text and the existing structured GovInfo sources remain the useful inputs.
- **RDFa and microformat noise:** RDFa frequently repeats Open Graph or accessibility roles. Microformat extraction also interprets CSS classes such as `h-full` and `h-px` as types. Nonempty output is not automatically useful semantic data.

## Format coverage

Counts are distinct body versions, not unique hearings or URLs. Formats overlap. “Not flagged” excludes pages whose known HTTP statuses are all errors, plus recognized error-page titles; it is not a guarantee of valid content.

| Format | All HTML bodies | Not flagged as errors |
|---|---:|---:|
| RDFa | 97,819 | 64,601 |
| Open Graph | 66,044 | 59,664 |
| Dublin Core | 54,724 | 54,088 |
| Microformats | 5,049 | 5,038 |
| JSON-LD | 3,112 | 2,341 |
| Microdata | 59 | 54 |

Overall, **104,927 bodies contain at least one extracted format**. Of the 185,698 HTML bodies, 114,270 passed the error-page screening. Many retained HTML responses are access-denied or missing-page responses, including responses to document URLs. Counting their metadata as substantive congressional coverage would overstate the result.

The archive families overlap. The scan includes 11,144 Senate-page bodies, 21,937 House-page bodies, 34,783 GovInfo transcript bodies, 143,430 document-family bodies, player/watch pages, provider responses, and archived pages. [summary.json](summary.json) includes the full family/domain breakdown.

## What to reuse from Keeplist

I inspected Keeplist backend at commit `35e2fdd6a1b9a1ccb581319439ddb7ef5f5b4ffa`, including `keeplist_io/scrape/parsers/extruct.py`, raw-data persistence, and the canonical normalization pipeline.

Its extraction call uses `get_base_url(html, url)`, `uniform=True`, and **`with_og_array=True`**. The last option preserves repeated Open Graph values. It moves CPU work off the async event loop, preserves raw extracted data separately from normalization, and keeps document-icon/content-image fallbacks separate from publisher metadata. Its normalization pipeline treats sources independently and retains unknown properties and conflicts.

Reuse those principles in a thin congressional adapter. This audit uses the default raw format instead of uniform output; Open Graph remains an ordered list of property/value pairs, so repeated values are preserved. Keep a small head-tag pass for metadata outside extruct's six formats.

One additional requirement is demonstrated here: isolate extraction failures by format. Eight bodies hit microformat recursion errors. One large transcript timed out during all-format extraction; its other five formats were recovered separately, leaving RDFa unavailable. The final results contain **nine partial extractions and no wholly unprocessed candidate HTML bodies**. Do not silently turn an unavailable format into an empty result.

Package reference: [official extruct documentation](https://github.com/scrapinghub/extruct).

## Coverage, provenance, and repeatability

The starting point was the selected retained archive, not fresh requests to congressional sites:

- Selected capture index: **3,909,134 references**, represented by 281 Parquet files. Selector SHA-256: `4773ba6bcf55404cfbbb01242df8e25c931e5e5454ae2e5072ce23addc4afcd6`.
- Main selection used HTML media types, raw-HTML pointers, and known page families: **196,152 candidate bodies**. Of the selected references, **443 have no body key** and could not be examined.
- A supplementary pass checked HTML-looking filenames/URLs and all 10,278 retained WARC/ARC bodies. Their 5,489 HTML response records added one new body after deduplication; two otherwise unclassified loose HTML files brought the total to **196,155 candidates**.
- Byte inspection excluded **10,457 non-HTML candidates**. Every examined stored body passed its recorded SHA-256 and decoded-length check. Downloading missing retained objects required no publisher refetch.
- Capture manifest hashes and row continuity were checked. Some upstream Parquet “digests” identify **path and size**, not content; the audit verified that convention and recorded fresh downloaded SHA-256 hashes. They are not presented as upstream content hashes.
- **10,228 HTML bodies lack a capture URL.** For domain grouping, 3,939 have a usable page-declared URL; this is an inference, not acquisition provenance. Relative URLs in extraction remain unresolved where no base is known. Identical bodies were extracted once with one representative capture URL; all recorded URL contexts remain available.

This covers identifiable HTML in the selected retained snapshot, including archived responses. It does not prove coverage of unindexed sources or bodies with neither HTML indicators nor a recognized page/file classification.

The audit preserved originals and wrote only experimental scripts and outputs. It did not change production parsing, source records, or package dependencies. Congressional code examined: `558fe9028bc9f80cf04492fefd86fb2eb3ab13b8`; relevant file hashes are recorded in [summary.json](summary.json).

### Artifacts and replay

- [Compact findings and code/source identities](summary.json)
- [Full extracted metadata, compressed JSON Lines](../../../output/extruct-metadata-20261030/all-metadata.jsonl.gz)
- [Detailed counts, fields, types, examples, and errors](../../../output/extruct-metadata-20261030/findings.json)
- [Pinned input inventory](../../../output/extruct-metadata-20261030/inventory.json) and [HTML body manifest](../../../output/extruct-metadata-20261030/bodies.jsonl)
- [Archived-response coverage](../../../output/extruct-metadata-20261030/additional/html-summary.json)
- [Senate listing comparison](../../../output/extruct-metadata-20261030/hearing-microformat-comparison.json)

The `output/` artifacts are local and ignored by Git. Keep them with the analysis if moving this experiment. No archive-access credentials are included in the report or result files.

From the repository root, recompute aggregate findings and the listing comparison without network access:

```sh
python3 docs/experiments/extruct-metadata-20261030/analyze.py \
  output/extruct-metadata-20261030/all-metadata.jsonl.gz \
  --output output/extruct-metadata-20261030/findings.json

uv run --python 3.14 python docs/experiments/extruct-metadata-20261030/compare_listings.py \
  output/extruct-metadata-20261030
```

`inventory.py` pins the main retained selection; `download.py` reads only listed missing archive objects using the existing local rclone connection. `archive_html.py` consumes the recorded supplementary manifest. To repeat extraction from the existing body manifest into a new output directory:

```sh
uv run --script docs/experiments/extruct-metadata-20261030/extract.py \
  --manifest output/extruct-metadata-20261030/bodies.jsonl \
  --output output/extruct-replay --workers 4
```

Run the supplementary `additional/html-bodies.jsonl` similarly. The one timed-out body's separate recovery is retained in `timeout-recovery.json`; a fresh all-format replay may reproduce its timeout. The frozen combined results include that recovery explicitly.

Verification included source digest/length checks, unique-result checks, all six extraction formats, non-HTML/UTF-16 detection, the actual 49-page listing comparison, Python compilation, and linting of the experiment scripts. Unannotated transcript pages bypass extruct's expensive DOM conversion only when no format markers exist. Nine format-level failures remain visible in the results.
