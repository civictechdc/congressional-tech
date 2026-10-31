# Bottom-Up URL Normalization & Lifecycle Audit (Stages 1–8)

## Executive Summary

Across the 8 stages of the `congressional-tech` pipeline, URLs pass through **four distinct normalization/keying implementations** that do not agree with each other, and **one fundamental architectural split** between **literal URLs** (`url`, `target_url`, `requested_url`) and **normalized identity keys** (`url_key`, `surt`, `lookup_key`):

1. **The Literal-vs-Normalized Split (`url-normalized.sql` vs. `capture_scheduler.py` / `archive_url_state.py`)**:
   - Stage 5 (`model/sql/url-normalized.sql` + `model/sql/url-keys.sql`) unwraps archival/security wrappers (`wayback`, `loc`, `proofpoint-v2`, `lis-gpo`, `senate-notfound`) and repairs malformed query delimiters (`download-ampersand-query`: `/download/<slug>&download=1` $\rightarrow$ `/download/<slug>?download=1`), **but only uses the transformed string to compute `url_key` while keeping `url_keys.url` as the raw literal string** (`-- Literal values remain unchanged`).
   - Downstream, Stage 2 (`capture_scheduler.py:391-397`) and Stage 6 (`archive_url_state.py:70-80`) select `min(url)` / `min(l.target_url)` as `requested_url` and evaluate `capture-scope.json` against that **un-repaired literal URL**.
   - **Consequences in the corpus**:
     - **3,231 `needs_acquisition` House download URLs** ending in `&download=1` are requested literally with `&download=1` in the URL path instead of `?download=1` in the query string (returning 403/404 or remaining unfetched), while **3,213** of their base `/download/<slug>` URLs already returned HTTP 200 HTML download wrappers (`record_role = 'wrapper'`) that were never linked via `url_key`!
     - **100,725 `http://` target URLs** and all wrapped links (`web.archive.org`, `webarchive.loc.gov`, `urldefense.proofpoint.com`, `lis.gov/cgi-lis/t2GPO/`) fail `capture-scope.json` (whose 16 regexes are all anchored with `^https://`) because scope is checked before unwrapping or `http` $\rightarrow$ `https` upgrade.

2. **Four Incompatible URL Keying Functions**:
   - **Model `url_key`** (`model/sql/url-normalized.sql` + Rust `url_resolve`/`uri_normalize_encoding`): 2-pass `url-rules.json` `wrapper` unwrap $\rightarrow$ WHATWG URL parse (strips `:80`/`:443`, lowercases scheme/host, resolves `..`, encodes spaces) $\rightarrow$ RFC 3986 unreserved percent-decode & uppercase hex $\rightarrow$ strips `^www\.`, `#fragment`, trailing `/` $\rightarrow$ strips `utm_*` and `congress.gov` `q=` $\rightarrow$ sorts query params.
   - **Archive State / Provenance Joins** (`archive_url_state.py:131-134, 166`): Uses **exact literal string equality** (`h.requested_url = u.original_url`) instead of `url_key` when checking whether a recovery satisfies an eligible URL (`35` rows in `url-dispositions.parquet` needed a post-hoc `retained_candidate_stored_url_key_alias` workaround).
   - **Corpus Recovery CDX & Wayback Validation** (`corpus_recovery/cdx.py:28-37` & `discovery.py:117-126, 165-189`): Uses `surt.surt(url)` for WebHarvest CDX, but in `wayback_lookup` enforces **exact literal equality** `row['original'] != original` and treats empty JSON `[]` as an error—causing **51 of 60 (85%) HTTP 200 Wayback CDX responses** in `track_b/b2_discovery` to fail with `invalid_index_response` (including **15 of 24 non-empty hits** rejected solely because Wayback's `original` had `:80`, `http://`, `www.`, or `//`).
   - **Public Release `lookup_key`** (`archive_format.py:65-82` `_lookup_steps` & `archive.ts:25-36` `lookupUrl`): Lowercases scheme/host and strips `www.`, `:80`/`:443`, `#fragment`, and trailing `/`, **without** `uri_normalize_encoding`, wrapper unwrapping, `utm_*`/`q=` stripping, or query sorting—diverging from `url_key` on **22,453 rows** in `publish_v20/release/sources.parquet` (`16,543` lowercase hex escapes, `4,270` `&download=1`, `913` `?download=1`, `472` raw spaces, `174` `congress.gov` `?q=`, `68` Wayback wrappers, `13` `utm_*`).

---

## Stage-by-Stage Overview Table

| Stage | Name | Primary Code Locations | Input URL Column(s) | Output URL / Key Column(s) | Mutates Literal URL? | Key Transformations Applied | Top Corpus Quantified Bug / Gap |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Link Extraction & Contextual Resolution** | `archive_readings.py:103-265`<br>`model/sql/page-contexts.sql`<br>`model/sql/link-*.sql`<br>`functions.rs:577-587` | `readings.links[].href`, `readings.base_href`, `page_contexts.origin` (`coalesce(url, requested_url)`) | `resolved_links.target_url`<br>`publisher_links.target_url`, `url_key` | **Yes** (`target_url` is resolved via `url_resolve` and split on `repair` rules) | Strips controls `[\x00-\x20]`; splits `concatenated-file-urls` (`wrappers=0`, no `[?#\s]`); WHATWG `url_resolve(target_literal, resolved_base)` | `page-contexts.sql:5` excludes `record_role='wrapper'` (**3,213** stored HTML download wrappers ignored); `mailto:https://...` fails `^https?://`; `1,385` `publisher_links` rows still contain `https?://.+https?://` |
| **2** | **Capture Scheduler & Admission** | `capture_scheduler.py:67-113, 365-413, 685-705`<br>`archive_url_state.py:63-85`<br>`capture-scope.json` | `publisher_links.target_url`, `captures.requested_url`, live HTML discovery `href` | `queue.requested_url`, `url_key` | **Only `_safe_reference`** (`urljoin` + space $\rightarrow$ `%20`); keeps `min(url)` literal! | `_safe_reference` rejects schemes not in `{'','http','https'}`; groups by `url_key` and picks `min(literal_url)`; filters by `capture-scope.json` on **literal** URL | Schedules raw `&download=1` (**3,231** `needs_acquisition` rows fail/unfetched); `capture-scope.json` requires `^https://` and runs on literal URLs, dropping `http://` (**100,725** targets) and wrapped URLs |
| **3** | **HTTP Fetch & Redirect Handling** | `fetcher.py:25-125`<br>`receipt_writer.py:135-210`<br>`receipt_privacy.py:36-74` | `requested_url` | `receipt.requested_url`, `receipt.url` (final or blocked redirect URL) | **Yes** on redirect (`url = urljoin(transfer.url, location)`) & `sanitize_url` | Follows up to 10 redirects if `CaptureScope(target)` matches; redacts `credential-parameters.json` query params in receipts | Redirects to `http://` or out-of-scope hosts fail with `excluded_redirect`; Senate 302s to `/404?notfound=...` record the 404 error URL as `url` (**337** rows in `capture_sources.parquet`) |
| **4** | **Lake Ingestion & URL Universe** | `captures.py:253-311`<br>`model/sql/capture-sources.sql`<br>`model/sql/model-url-inputs.sql` | `requested_url`, `url`, `context_url`, `original_url`, `recovered_url`, `resolved_links.target_url` | `url_inputs.url` | **No** (`trim()` only in `captures.py`) | Unions all source addresses, contexts, resolved links, recoveries, and `unnest([requested_url, url])` from `mode='fetch'` captures | `model-url-inputs.sql:7-8` ingests failed/error-redirect `url`s (**53** `/404?notfound=` URLs, **1,784** concatenated `https://...https://...` URLs, and host `'File URL path: '` into `url-dispositions.parquet`) |
| **5** | **Native SQL Normalization & `url_key`** | `model/sql/url-normalized.sql`<br>`model/sql/url-keys.sql`<br>`url-rules.json`<br>`functions.rs:577-637` | `url_inputs.url` | `url_keys.url` (literal), `url_keys.url_key` (normalized) | **No** (`url_keys.url` is untouched; only `url_key` is normalized) | 2-pass `wrapper` unwrap $\rightarrow$ `uri_normalize_encoding(url_resolve(val, NULL))` $\rightarrow$ strip `^www\.`, `#frag`, trailing `/` $\rightarrow$ strip `utm_*`, `q=` $\rightarrow$ sort query | `publish_v20` & `plan_v2` built without `senate-notfound` / `download-ampersand-query`; `&download=1` $\rightarrow$ `?download=1` still doesn't match base `/download/<slug>` (**8,023** pairs); `senate-notfound` lacks `"decoder":"percent"` (`%2F`); trailing `%20` (**38** URLs) |
| **6** | **Archive URL State & Recovery Attachment** | `archive_url_state.py:55-180`<br>`model/sql/url-state.sql`<br>`model/sql/provenance-recovery-*.sql` | `captures.requested_url`, `url_keys.url_key`, `current_recoveries.original_url` | `url_state.parquet` (`requested_url`, `capture_disposition`, `capture_reason`) | **No** | `provenance-recovery-attachments.sql` joins on `url_key`, **but** `archive_url_state.py:131-134, 166` joins on literal `requested_url = original_url` | Exact literal join in `archive_url_state.py` misses recoveries attached via `url_key` aliases (**35** `retained_candidate_stored_url_key_alias` rows in `url-dispositions.parquet`) |
| **7** | **Corpus Recovery Campaign & CDX Discovery** | `campaign.py:92-199`<br>`discovery.py:53-204`<br>`cdx.py:28-37`<br>`reconcile.py:123-299` | `targets.target_url`, `url_key` | `lookup_key` (`surt`), `candidate_url` (`web.archive.org/web/{ts}id_/{url}`) | **Yes** (constructs Wayback replay URL using query `original`) | `cdx.py` computes `surt.surt(url)`; `wayback_lookup` queries CDX `matchType=exact` and checks `row['original'] != original` | **51/60 (85%)** HTTP 200 Wayback CDX calls in `b2_discovery` failed with `invalid_index_response`: **36** on empty `[]` and **15/24** non-empty hits rejected because `row['original']` had `:80`, `http://`, `www.`, or `//` |
| **8** | **Public Release & UI Lookup** | `archive_format.py:65-82, 190-211`<br>`archive.ts:25-36, 178-199`<br>`ArchiveDetail.tsx:107-120` | `document_addresses.url` (`sources.parquet`, `recoveries.parquet`) | `urls.lookup_key` (`sha256(lookup_url)`), `document_rows.link_key` | **No** (renders literal `public_url` in UI) | `_lookup_steps` / `lookupUrl`: regex parse, lowercase scheme/host, strip `^www\.`, `:80`/`:443`, `#fragment`, trailing `/` | Diverges from `url_key` on **22,453** `sources.parquet` rows (no percent-encoding normalization, no wrapper unwrap, no `utm_*`/`q=` strip, no query sort) |

---

## Detailed Stage-by-Stage Lifecycle Walkthrough

### Stage 1: Link Extraction & Contextual Link Resolution

#### 1. Where the Step Lives
- **Python Parser Extraction**:
  - [archive_readings.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/parsers/archive_readings.py#L103-L155): `extract_links`, `meta_refresh_links`, `json_url_strings`
  - [archive_readings.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/parsers/archive_readings.py#L181-L265): `parse_html`, `parse_xml`, `parse_json`
  - [readings.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/lake/readings.py#L32-L44): `LINK_STRUCT` (`href`, `rel`, `source_element`, `text`) and `readings` parquet table writer.
- **Model SQL Link Resolution Pipeline**:
  - [page-contexts.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/page-contexts.sql#L1-L11)
  - [link-inputs.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/link-inputs.sql#L1-L12)
  - [link-contexts.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/link-contexts.sql#L1-L14)
  - [link-literals.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/link-literals.sql#L1-L14)
  - [link-parts.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/link-parts.sql#L1-L4)
  - [link-targets.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/link-targets.sql#L1-L24)
  - [link-errors.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/link-errors.sql#L1-L3) & [resolved-links.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/resolved-links.sql#L1-L10)
  - [publisher-links.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/publisher-links.sql#L1-L12)
- **Rust Native UDF**:
  - [functions.rs](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/job/functions.rs#L577-L587): `url_resolve(reference, base)`

#### 2. Input & Output Columns
- **Inputs**:
  - `readings.links` (`LIST<STRUCT<href VARCHAR, rel VARCHAR, source_element VARCHAR, text VARCHAR>>`) and `readings.base_href` (`VARCHAR`).
  - `capture_sources.url` and `capture_sources.requested_url` combined as `coalesce(url, requested_url) AS origin` in `page_contexts`.
- **Outputs**:
  - `resolved_links`: `(context_url, href, base_href, split_position, target_url)`
  - `publisher_links`: `(context_url, context_key, target_url, url_key, href, split_position)`

#### 3. Exact Transformations Applied
1. **HTML/XML/JSON Extraction (`archive_readings.py`)**:
   - **HTML (`parse_html`, lines 181–225)**: Strips `[\x00-\x20]+` from the start/end of raw `href`/`src`/`data` attributes (`_STRIP_CONTROLS_RE`). Ignores `href`s starting with `#` or matching `^(?:javascript|data|vbscript):` (`_SKIP_SCHEME_RE`, line 29) — **note that `mailto:` is NOT in `_SKIP_SCHEME_RE`**. Also extracts `<base href>` (first match) and `<meta http-equiv="refresh" content="...;url=...">`.
   - **XML (`parse_xml`, lines 228–252)**: Extracts attributes in `_XML_URL_ATTRS` (`href`, `src`, `url`, `xlink:href`) and text of leaf elements in `_XML_URL_ELEMENTS` (`url`, `link`, `file-url`, `pdf-url`, `document-url`, `target-url`, `location`) if text contains `/` or starts with `http://`/`https://`.
   - **JSON (`parse_json`, lines 255–265)**: Extracts string values starting with `https://`, `http://`, or `/` (where second char is not `/`).
2. **Page Context Filtering (`page-contexts.sql:1-11`)**:
   - Selects only `capture_sources` where `record_role = 'page' AND format IN ('html', 'xml', 'json') AND intact`.
3. **Base URL Resolution (`link-contexts.sql:5`)**:
   - `coalesce(url_resolve(nullif(base_href, ''), origin), origin) AS resolved_base`.
4. **Concatenated Link Repair (`link-literals.sql:1-14` & `link-parts.sql:1-4`)**:
   - Counts how many `url_rules WHERE kind = 'wrapper'` match `href` (`wrappers`).
   - Applies `url_rules WHERE kind = 'repair'` (`concatenated-file-urls`: `(?i)(https?://)` $\rightarrow$ `\n$1`) **only when**:
     ```sql
     l.wrappers = 0
     AND regexp_like(l.href, '(?i)^https?://.+https?://')
     AND NOT regexp_like(l.href, '[[:space:]?#]')
     ```
   - `link-parts.sql` splits `repaired_literal` on `chr(10)` (`\n`) with 1-based `split_position`.
5. **WHATWG URL Resolution & Target Validation (`link-targets.sql:1-24`)**:
   - Calls Rust UDF `url_resolve(p.target_literal, c.resolved_base)`:
     ```rust
     // /Users/mikewolfd/Work/spicy-stack/docspec-rs/src/job/functions.rs:577-587
     fn resolve(reference: &str, base: Option<&str>) -> Option<String> {
         let base = match base {
             Some(value) => Some(Url::parse(value).ok()?),
             None => None,
         };
         Url::options().base_url(base.as_ref()).parse(reference).ok().map(String::from)
     }
     ```
   - Validates `resolved`:
     - Must match `^https?://[^/?#]+` (otherwise `target_error = 'invalid_target'`).
     - If `repaired = true` (`split_position` from a split link), every split part must also match `(?:[/?#]|^)(?:[^/?#]+\.)+(?:<extensions>)(?:$|[?#])` from `file_shapes.json` (otherwise `target_error = 'unrecognized_repair_part'`, and `resolved-links.sql` drops **all** parts of that `href` via `RIGHT ANTI JOIN` on `link_errors`).

#### 4. Why It Does This
- Resolves relative links against `<base href>` / page origin and repairs accidental CMS/HTML-to-text concatenations like `https://...BILLS-115s585rfh.xmlhttps://...BILLS-115s585es.xml` without falsely splitting Wayback/Proofpoint wrappers (`l.wrappers = 0`).

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 1A (`page-contexts.sql:5` drops links inside `record_role = 'wrapper'` pages)**:
  - House CreativeEngine download landing pages (e.g. `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony`, `body_sha = ae5ee73d95a8fada1e9491574799cf263d03114d3f84d830ed26a9f6e1e0934c`) contain `Download will begin shortly... <a href=".../download/ashley-nunes-witness-testimony&download=1">`.
  - `model/sql/record-roles.sql:22` classifies these pages as `record_role = 'wrapper'` (via `download_wrapper` in `model/registries/page-signals.json:51-54`).
  - Because `page-contexts.sql:5` filters `WHERE record_role = 'page'`, links inside all `record_role = 'wrapper'` pages (**3,213** stored HTTP 200 HTML wrapper pages for `needs_acquisition` `&download=1` targets in `capture_sources.parquet`) are completely excluded from `resolved_links` and `publisher_links` unless the same body hash also appeared under a `'page'` capture!
  - **Fix**: Change `page-contexts.sql:5` to `WHERE record_role IN ('page', 'wrapper')`.
- **Bug 1B (`mailto:https://...` and XML `<file-url>File URL path: /sites/...</file-url>` are not repaired before resolution)**:
  - In HTML pages, authors frequently write `<a href="mailto:https://www.congress.gov/116/bills/hr7045/BILLS-116hr7045ih.pdf">`. Because `mailto:` is not stripped before `url_resolve`, `url_resolve` parses scheme `mailto:`, which fails `^https?://[^/?#]+` in `link-targets.sql:21` (`invalid_target`).
  - In XML feeds (`parse_xml`, line 250), `<file-url>File URL path: /sites/default/files/documents/7.7.17DallinMaybeeTestimoney.pdf</file-url>` contains `/` so it is extracted literally; when resolved against an `http://` base URL, WHATWG `Url::parse` treats `File URL path:` as the relative path or host (`http://File URL path: /sites/...`, which actually appears in `url-dispositions.parquet` with `host = 'File URL path: '`!).
- **Bug 1C (`link-literals.sql` only repairs `wrappers = 0` without `[?#\s]`, leaving 1,385 concatenated rows in `publisher_links.parquet`)**:
  - In `publish_v20/model/evidence/publisher_links.parquet`, **1,385 rows (507 distinct `target_url`s)** still match `(?i)^https?://.+https?://` (including `http://www.congress.gov/cgi-lis/t2GPO/http://www.gpo.gov/...`, `exit.asp?link=http://...`, and concatenated URLs where one URL has a query string or space).
  - Furthermore, `link-literals.sql` does **not** repair `/download/<slug>&download=1` $\rightarrow$ `/download/<slug>?download=1` at the `target_url` level, so `resolved_links.target_url` retains the broken `&download=1` path literal.

---

### Stage 2: Capture Scheduler & Admission (`capture_scheduler.py` & `archive_url_state.py`)

#### 1. Where the Step Lives
- [capture_scheduler.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L67-L113): `CapturePolicy` and `_safe_reference`
- [capture_scheduler.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L365-L413): `plan_queue`
- [capture_scheduler.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L685-L705): `read_discovery_payload` (in-run link extraction)
- [archive_url_state.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_url_state.py#L63-L85): `url_state_queue`
- [capture-scope.json](file:///Users/mikewolfd/Work/congressional-tech/model/registries/capture-scope.json#L1-L129)

#### 2. Input & Output Columns
- **Inputs**: `publisher_links.target_url` (or `seed_rows`: `captures.requested_url` + `readings.links[].href`), `url_rules`, `capture-scope.json`.
- **Outputs**: `queue.requested_url`, `queue.url_key` (in `capture_scheduler.py`) and `url_state_queue.requested_url`, `url_state_queue.url_key` (in `archive_url_state.py`).

#### 3. Exact Transformations Applied
1. **In-Run Link Resolution (`_safe_reference`, `capture_scheduler.py:99-113`)**:
   - Strips leading/trailing whitespace, rejects schemes not in `{'', 'http', 'https'}`, calls `urlsplit(urljoin(base_url, cleaned))`, rejects URLs without scheme/netloc or with credentials, and replaces raw spaces `' '` with `'%20'` in path and query.
2. **Key Grouping & Representative Literal Selection (`capture_scheduler.py:390-396` & `archive_url_state.py:70-80`)**:
   - Computes `url_key` via `url-normalized.sql` / `url-keys.sql`.
   - Groups by `url_key` and picks **`min(url)`** (or `min(l.target_url)`) as the literal `requested_url`:
     ```sql
     -- capture_scheduler.py:391-395
     keyed_seeds AS (
         SELECT s.url, k.url_key
         FROM seed_rows s
         JOIN url_keys k ON k.url = s.url
         WHERE k.url_key IS NOT NULL
     ),
     seed_keys AS (
         SELECT url_key, min(url) AS url FROM keyed_seeds GROUP BY url_key
     )
     ```
     ```sql
     -- archive_url_state.py:70-80
     scoped_targets AS (
         SELECT DISTINCT l.target_url
         FROM publisher_links l
         WHERE (regexp_matches(l.target_url, ...)) -- capture-scope.json
     ),
     publisher_queue AS (
         SELECT k.url_key, min(l.target_url) AS url
         FROM scoped_targets l
         JOIN url_keys k ON k.url = l.target_url
         WHERE k.url_key IS NOT NULL
         GROUP BY k.url_key
     )
     ```
3. **Scope Filtering (`capture-scope.json`)**:
   - Evaluates 16 regexes (every single one anchored with `^https://`) against the **literal** `requested_url` / `l.target_url`.

#### 4. Why It Does This
- Deduplicates the fetch queue so multiple literal URLs with the same `url_key` are only fetched once, and enforces domain scoping (`*.senate.gov`, `*.house.gov`, `www.congress.gov`, `www.govinfo.gov`, `www.gpo.gov`, `www.gao.gov`, `crsreports.congress.gov`).

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 2A (Critical: `min(literal_url)` schedules un-repaired `&download=1` and wrapped URLs as `requested_url`)**:
  - Because `url-normalized.sql` only uses `u.value` (the unwrapped/repaired URL) to compute `url_key` while leaving `url_keys.url` as the raw literal string, `min(url)` selects the broken literal `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1` instead of `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1`!
  - **Corpus impact**: In `url-dispositions.parquet`, **3,231 `needs_acquisition` URLs** end in `&download=1` (`1,808` `walled_403_or_unattempted`, `1,391` `purged_404_410`, `32` `legacy_or_unreachable`), and **0** of them have ever been requested with `?download=1`.
- **Bug 2B (Critical: `capture-scope.json` is evaluated against the raw literal URL instead of the unwrapped/scheme-upgraded URL)**:
  - All 16 patterns in `model/registries/capture-scope.json` require `^https://`.
  - Any `http://` link literal (**100,725** targets in `url-dispositions.parquet` start with `http://`!) or any link wrapped in `web.archive.org`, `webarchive.loc.gov`, `urldefense.proofpoint.com`, or `lis.gov/cgi-lis/t2GPO/` fails `scoped_targets` (`archive_url_state.py:70-75`) and `policy.sql('requested_url')` (`capture_scheduler.py:397`), even when its unwrapped `url_key` is an in-scope `.gov` document!
- **Bug 2C (`min(url)` lexicographical ordering prefers `http://` over `https://` and `&download=1` over `?download=1`)**:
  - In ASCII, `'&'` (0x26) < `'?'` (0x3F), and `'http://'` < `'https://'`. Whenever both a broken `&download=1` and a valid `?download=1` (or `http://` and `https://`) map to the same `url_key`, `min(url)` deterministically chooses the **worse** literal (`&download=1` and `http://`)!

---

### Stage 3: HTTP Fetch & Redirect Handling (`fetcher.py` & `receipt_writer.py`)

#### 1. Where the Step Lives
- [fetcher.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/fetcher.py#L25-L41): `CaptureScope`
- [fetcher.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/fetcher.py#L64-L125): `Fetcher._attempt`
- [receipt_writer.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/receipt_writer.py#L135-L210): `ReceiptWriter`
- [receipt_privacy.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/receipt_privacy.py#L36-L74): `sanitize_url`

#### 2. Input & Output Columns
- **Input**: `requested_url` (`str`).
- **Outputs**: `FetchAttempt(requested_url, url, status, headers, body, error, ...)` written to JSONL receipts with `sanitize_url(requested_url)` and `sanitize_url(url)`.

#### 3. Exact Transformations Applied
1. **Pre-Flight & Redirect Scope Check (`fetcher.py:67-68, 92-95, 112`)**:
   - Before each hop (up to `_MAX_REDIRECTS = 10`), checks `self.scope(current)`.
   - On HTTP `301, 302, 303, 307, 308`, resolves `target = urljoin(transfer.url, location)`.
   - On the next iteration, if `not self.scope(target)`, returns `FetchAttempt(requested_url=url, url=target, error='excluded_redirect')`.
2. **Credential Sanitization (`receipt_privacy.py:36-74`)**:
   - Strips userinfo from netloc and removes query parameters matching `model/registries/credential-parameters.json` before writing JSONL receipts.

#### 4. Why It Does This
- Prevents SSRF / out-of-scope crawling on redirects and ensures session tokens or API keys are never persisted into receipts.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 3A (Senate ColdFusion `/404?notfound=` Soft-404 Redirects)**:
  - When a Senate ColdFusion page or file is missing, `*.senate.gov` returns `302 Found` with `Location: /404?notfound=<original_path>`.
  - Because `https://<committee>.senate.gov/404?notfound=...` matches `capture-scope.json`, `Fetcher` follows the redirect and records `url = 'https://<committee>.senate.gov/404?notfound=...'`.
  - In `capture_sources.parquet`, there are **337 rows** with `/404?notfound=` (**333** with `http_status = 404, outcome = 'failed'`, and **4** with `http_status = 200, outcome = 'stored'`, all classified as `record_role = 'error_response'`). Worse, in historical `assemble-20260930.jsonl.gz` receipts, the redirect target `/404?notfound=...` was written into **`requested_url`** itself (**53** distinct URLs)!

---

### Stage 4: Lake Ingestion & Model URL Universe Construction

#### 1. Where the Step Lives
- [captures.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/lake/captures.py#L253-L311): `_trimmed_string`, `receipt_record`
- [source-url-inputs.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/source-url-inputs.sql#L1-L4) & [source-reference-targets.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/source-reference-targets.sql#L1-L11)
- [capture-sources.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/capture-sources.sql#L1-L17)
- [source-files.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/source-files.sql#L1-L34) & [source-addresses.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/source-addresses.sql#L1-L12)
- [model-url-inputs.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/model-url-inputs.sql#L1-L8)

#### 2. Input & Output Columns
- **Inputs**: Raw JSONL receipts (`requested_url`, `url`, `context_url`, `original_url`, `recovered_url`), `resolved_links.target_url`, `current_recoveries.original_url`.
- **Outputs**:
  - `capture_sources`: `(id, requested_url, url, source_url, record_role, ...)` where `source_url = coalesce(url, requested_url)`.
  - `source_addresses`: `(body_sha, url)` for `record_role = 'document'`.
  - `url_inputs`: `(url)` — the master universe of URLs fed into Stage 5 `url-normalized.sql`.

#### 3. Exact Transformations Applied
- `captures.py:253-255` applies `.strip()` (`_trimmed_string`) to all receipt URL fields.
- `source-reference-targets.sql:1-11` checks `uri_normalize_encoding(url_resolve(u.url, NULL))` for `context_url` and assigns `reference_error = 'invalid_url'` if NULL or not `^https?://[^/?#]+`.
- `model-url-inputs.sql:1-8` builds the URL universe:
  ```sql
  SELECT url FROM source_addresses WHERE url IS NOT NULL
  UNION
  SELECT context_url AS url FROM capture_source_contexts WHERE context_url IS NOT NULL
  UNION
  SELECT target_url AS url FROM resolved_links WHERE target_url IS NOT NULL
  UNION
  SELECT original_url AS url FROM current_recoveries WHERE original_url IS NOT NULL
  UNION
  SELECT unnest(make_array(requested_url, url)) AS url
  FROM captures
  WHERE mode = 'fetch' AND outcome NOT IN ('reference', 'saved-record');
  ```

#### 4. Why It Does This
- Ensures every URL referenced by a stored document, page context, resolved link, recovery, or fetch attempt gets an entry in `url_keys`.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 4A (`model-url-inputs.sql:7-8` and `raw_universe` pollute the URL universe with failed redirect destinations and historical corrupted `requested_url`s)**:
  - Unnesting `make_array(requested_url, url)` for all `mode = 'fetch'` captures regardless of `outcome = 'failed'` or `record_role = 'error_response'` injects error redirect URLs (`https://www.aging.senate.gov/404?notfound=...`, `https://www.govinfo.gov/content/pkg/BILLS-115s585rfh/xml/BILLS-115s585rfh.xmlhttps:`) into `url_inputs` and downstream campaign planning.
  - **Corpus impact in `url-dispositions.parquet`**:
    - **53** Senate `/404?notfound=...` error URLs (`52` marked `needs_acquisition_purged_404_410`, `1` marked `usable_direct`).
    - **1,784** concatenated `https?://.+https?://` URLs (`1,341` `out_of_scope`, `273` `needs_acquisition`, `170` `usable_direct`).
    - Malformed hosts in `url-dispositions.parquet`: `'File URL path: '`, `'https'`, `'edworkfhttps:'`, `'waysandmeans.hohttp'`, and `'www.gpo.gov:80'` (6 rows).

---

### Stage 5: Native SQL URL Normalization & Key Generation (`url-normalized.sql`, `url-keys.sql`, `url-rules.json`)

#### 1. Where the Step Lives
- [url-normalized.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/url-normalized.sql#L1-L53)
- [url-keys.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/url-keys.sql#L1-L26)
- [url-rules.json](file:///Users/mikewolfd/Work/congressional-tech/model/registries/url-rules.json#L1-L93)
- [functions.rs](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/job/functions.rs#L577-L637): `url_resolve`, `uri_normalize_encoding`, `percent_decode_utf8`

#### 2. Input & Output Columns
- **Input**: `url_inputs(url)` (and `url_rules`).
- **Outputs**:
  - `url_normalized(url, parsed, authority, path, query)`
  - `url_keys(url, url_key)`

#### 3. Exact Transformations Applied
1. **Two Passes of `url_rules WHERE kind = 'wrapper'` (`url-normalized.sql:1-25`)**:
   - Evaluates matching `wrapper` rules in `url-rules.json`:
     - `wayback`: `^https?://web\.archive\.org/web/(?:[0-9]+|\*)(?:[a-z]{2}_)?/(https?://.+)$` $\rightarrow$ `$1` (`decoder: none`)
     - `loc`: `^https?://webarchive\.loc\.gov/all/(?:[0-9]+|\*)(?:[a-z]{2}_)?/(https?://.+)$` $\rightarrow$ `$1` (`decoder: none`)
     - `proofpoint-v2`: `^https?://urldefense\.proofpoint\.com/v2/url\?(?:[^#]*&)?u=([^&#]+).*$` $\rightarrow$ `$1` (`decoder: proofpoint_v2`, replacing `-` with `%`, `_` with `/`, then UTF-8 percent-decoding)
     - `lis-gpo`: `^https?://(?:www\.)?lis\.gov/cgi-lis/t2GPO/(https?://.+)$` $\rightarrow$ `$1` (`decoder: none`)
     - *(Uncommitted in working tree `url-rules.json:72-91`, absent from `publish_v20` & `plan_v2`)*:
       - `senate-notfound`: `^(https?://(?:[^/?#]+\.)?senate\.gov)/404\?notfound=/?([^#]+).*$` $\rightarrow$ `$1/$2` (`decoder: none`)
       - `download-ampersand-query`: `^(https?://[^/?#]+/download/[^?#]*?)\s*&download=1([&#].*)?$` $\rightarrow$ `$1?download=1$2` (`decoder: none`)
2. **WHATWG Parse + RFC 3986 Percent-Encoding Normalization (`url-normalized.sql:28`)**:
   - `uri_normalize_encoding(url_resolve(u.value, NULL)) AS parsed`
   - First, `url_resolve(u.value, NULL)` calls Rust `url::Url::parse`:
     - Lowercases scheme and ASCII host.
     - **Strips default ports** (`:80` for `http://`, `:443` for `https://`).
     - Resolves `.` and `..` path segments.
     - Percent-encodes raw spaces as `%20`.
   - Second, `uri_normalize_encoding` (`functions.rs:607-637`):
     - Walks `%XX` sequences: if the byte is RFC 3986 unreserved (`A-Z`, `a-z`, `0-9`, `-`, `.`, `_`, `~`), decodes it to its literal ASCII char; otherwise uppercases the two hex digits (`%2f` $\rightarrow$ `%2F`).
3. **Authority, Path & Fragment Normalization (`url-normalized.sql:40-49`)**:
   - Validates `regexp_like(parsed, '^https?://[^/?#]+')` (drops non-HTTP(S) schemes!).
   - Strips scheme (`https?://`), leaving authority + path + query.
   - Strips leading `www.` from authority: `regexp_replace(raw_authority, '^www\.', '')`.
   - Strips `:80` and `:443` from authority (redundant with `url::Url::parse` unless non-standard).
   - Strips `#fragment` (`regexp_extract( parsed, '^https?://[^/?#]+([^?#]*)', 1)`).
   - Strips trailing slash(es) from path: `regexp_replace(raw_path, '/+$', '')`.
4. **Query Parameter Filtering & Sorting (`url-keys.sql:1-26`)**:
   - Splits `query` on `'&'`, discards empty pairs (`pair <> ''`).
   - Anti-joins against `url_rules WHERE kind = 'strip'`:
     - `utm` (`authority_pattern = NULL`, `pattern = '^utm_.*$'`)
     - `congress-search-q` (`authority_pattern = '^(?:www\.)?congress\.gov$'`, `pattern = '^q$'`)
   - Re-aggregates remaining query parameters in **lexicographical order**: `string_agg(pair, '&' ORDER BY pair)`.
   - Concatenates `authority || path || CASE WHEN q.query IS NOT NULL THEN '?' || q.query ELSE '' END AS url_key`.
   - Preserves `n.url` (the original input literal) alongside `url_key`.

#### 4. Why It Does This
- Computes a scheme-agnostic, `www.`-agnostic, wrapper-unwrapped, query-sorted identity key (`url_key`) for joining links, captures, documents, and recoveries while keeping original URL literals intact for provenance.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 5A (`publish_v20` and `recovery_campaign_v1/plan_v2` were compiled BEFORE `senate-notfound` and `download-ampersand-query` were added)**:
  - Verified in `publish_v20/model/registries/url_rules.jsonl.gz` and `recovery_campaign_v1/key_prep/url_rules.jsonl.gz`: both artifacts only contain the 7 previously committed rules (`wayback`, `loc`, `proofpoint-v2`, `lis-gpo`, `concatenated-file-urls`, `utm`, `congress-search-q`).
- **Bug 5B (Critical: Even with `download-ampersand-query`, `/download/<slug>&download=1` and `/download/<slug>` produce DIFFERENT `url_key`s!)**:
  - `download-ampersand-query` (`url-rules.json:82-91`) rewrites `.../download/slug&download=1` to `.../download/slug?download=1`, which gets `url_key = .../download/slug?download=1`.
  - Meanwhile, the base URL `.../download/slug` gets `url_key = .../download/slug` (no `?download=1`).
  - **Corpus impact**: In `url-dispositions.parquet`, **8,023 distinct `&download=1` URLs** have a sibling base `/download/<slug>` URL in `url-dispositions.parquet`, including **all 3,231 `needs_acquisition` `&download=1` URLs**! Because their `url_key`s differ (`?download=1` vs no query), the pipeline treats them as two unrelated resources!
  - **What it should be**:
    1. For **literal repair** (so the HTTP fetcher requests the actual file rather than the HTML landing wrapper), `/download/<slug>(?:%20|\s)*&download=1` must be repaired to `/download/<slug>?download=1`.
    2. For **`url_key` identity**, either `download=1` on `/download/` paths should be stripped in `url-keys.sql` (so `/download/<slug>`, `/download/<slug>?download=1`, and `/download/<slug>&download=1` share the same `url_key`), OR `record_role = 'wrapper'` captures at `/download/<slug>` must not be marked `usable_direct` while `/download/<slug>?download=1` is fetched for the document body.
- **Bug 5C (`senate-notfound` in `url-rules.json:72-81` uses `"decoder": "none"`, failing on percent-encoded slashes `%2F`)**:
  - In `publisher_links.parquet` (`20` rows), `finance.senate.gov` redirects to `https://www.finance.senate.gov/404?notfound=hearings%2Fthe-presidents-fiscal-year-2024-irs-budget-and-the-irss-2023-filing-season`.
  - Because `senate-notfound` has `"decoder": "none"`, `$1/$2` produces `https://www.finance.senate.gov/hearings%2F...`. Since `/` is a reserved RFC 3986 character, `uri_normalize_encoding` does **not** decode `%2F`, yielding `url_key = finance.senate.gov/hearings%2F...` instead of `finance.senate.gov/hearings/...`!
  - **Fix**: Set `"decoder": "percent"` on `senate-notfound` and match `notfound=(?:%2[fF]|/)?([^#]+)`.
- **Bug 5D (Trailing `%20` in URL paths is not stripped by `url_resolve` or `url-normalized.sql` — 38 URLs in `url-dispositions.parquet`)**:
  - `url::Url::parse` strips raw ASCII whitespace at the end of a URL, **but not pre-encoded `%20`**!
  - In `url-dispositions.parquet`, **38 URLs** end in `%20` (e.g., `https://democrats-transportation.house.gov/download/09/09/2020/flynn-testimony%20` is `usable_direct` with 25 links, while `https://democrats-transportation.house.gov/download/09/09/2020/flynn-testimony &download=1` is `needs_acquisition` with 18 links; and `download-ampersand-query` only strips raw `\s*` before `&download=1`, not `(?:%20|\s)*`!).
- **Bug 5E (Missing wrapper rules for `congress.gov/cgi-lis/t2GPO/` and House `exit.asp?link=`)**:
  - `lis-gpo` (`url-rules.json:52-60`) only matches `(?:www\.)?lis\.gov/cgi-lis/t2GPO/`, missing `http://www.congress.gov/cgi-lis/t2GPO/http://www.gpo.gov/fdsys/pkg/...` (3 rows in `url-dispositions.parquet`).
- **Bug 5F (`r.kind = 'repair'` is not applied in `url-normalized.sql`)**:
  - Concatenated URLs that entered via `captures` (`BILLS-115s585rfh.xmlhttps://...BILLS-115s585es.xml`) are never split or rejected in `url-normalized.sql` because `url-normalized.sql` only applies `r.kind = 'wrapper'`.

---

### Stage 6: Archive URL State & Recovery Eligibility (`archive_url_state.py`, `url-state.sql`, `provenance-*.sql`)

#### 1. Where the Step Lives
- [archive_url_state.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_url_state.py#L55-L180): `state_steps` (`fetched_keys`, `url_state_queue`, `url_state_history`, `url_state_decisions`)
- [url-state.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/url-state.sql#L1-L18)
- [provenance-recovery-candidates.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/provenance-recovery-candidates.sql#L1-L15) & [provenance-recovery-attachments.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/provenance-recovery-attachments.sql#L1-L6)

#### 2. Input & Output Columns
- **Inputs**: `captures`, `url_keys`, `publisher_links`, `current_recoveries`, `recovery_decisions`.
- **Outputs**: `url_state.parquet` (`requested_url`, `attempts`, `first_seen_at`, `last_seen_at`, `last_status`, `last_outcome`, `last_error`, `body_sha`, `capture_disposition`, `capture_reason`).

#### 3. Exact Transformations Applied
- `provenance-recovery-attachments.sql:1-6` attaches recoveries to provenance candidates by joining on **`url_key`**:
  ```sql
  SELECT DISTINCT c.document_id, r.id
  FROM provenance_recovery_candidates c
  JOIN recovery_original_keys k ON k.url_key = c.url_key
  JOIN current_recoveries r ON r.original_url = k.original_url
  ```
- **In contrast**, `archive_url_state.py:124-175` determines whether a URL in `url_state_history` is satisfied by a recovery using **exact literal string equality**:
  ```sql
  -- archive_url_state.py:131-134
  FROM recovery_decisions d
  JOIN recovery_requirements r ON d.original_url = r.original_url
  JOIN captures c ON c.original_url = d.original_url
  ...
  -- archive_url_state.py:166
  FROM url_state_history h
  LEFT JOIN unambiguous u ON h.requested_url = u.original_url
  ```

#### 4. Why It Does This
- Computes the operational state (`satisfied`, `eligible`, `exhausted`, `excluded`) of every queued or fetched URL to drive acquisition and recovery campaigns.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 6A (Literal Join vs. `url_key` Join in `archive_url_state.py:131-134, 166`)**:
  - When a recovery is recorded with `original_url` differing from `h.requested_url` in scheme (`http://` vs `https://`), `www.`, or wrapper/query normalization—even though both share the exact same `url_key`—`LEFT JOIN unambiguous u ON h.requested_url = u.original_url` fails to match!
  - As a result, `url_state_decisions` marks the URL `capture_disposition = 'eligible', capture_reason = 'no_satisfying_recovery'` even when a valid recovery is already attached in `provenance-recovery-attachments.sql`!
  - In `recovery_campaign_v1/plan_v2/url-dispositions.parquet`, the campaign planner had to add special post-hoc disposition buckets (`retained_candidate_stored_url_key_alias`: **35 rows**, and `retained_r2_url_key_alias`) specifically to catch recoveries that were missed by literal `original_url` joins.

---

### Stage 7: Corpus Recovery Campaign & CDX Discovery (`campaign.py`, `discovery.py`, `cdx.py`, `reconcile.py`)

#### 1. Where the Step Lives
- [campaign.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/campaign.py#L92-L199): `plan_campaign`
- [discovery.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/discovery.py#L53-L204): `webharvest_lookup`, `validate_wayback_replay`, `acquire_wayback`, `wayback_lookup`
- [cdx.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/cdx.py#L28-L37): `key(url)` (`surt.surt`)
- [reconcile.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/reconcile.py#L123-L299)

#### 2. Input & Output Columns
- **Inputs**: `targets.parquet` (`target_url`, `url_key`, `host`, `disposition`, `reason`), WebHarvest CDX (`key` = SURT), Wayback CDX API (`url=original&matchType=exact`).
- **Outputs**: `candidates.parquet` / `lookup_summary.parquet` (`original_url`, `candidate_url`, `timestamp`, `source`, `cdx_complete`, `cdx_reason`), `retained_captures.parquet`.

#### 3. Exact Transformations Applied
1. **WebHarvest CDX Lookup (`cdx.py:28-37` & `discovery.py:53-115`)**:
   - Computes `surt_key = surt.surt(original_url)` and queries local DuckDB CDX index `WHERE key = ?`.
2. **Wayback CDX Lookup (`discovery.py:149-204`)**:
   - Requests `https://web.archive.org/cdx/search/cdx?url={quote(original, safe='')}&matchType=exact&output=json&fl=timestamp,original,statuscode,mimetype,digest`.
   - Parses JSON response (`discovery.py:167-189`):
     ```python
     rows = json.loads(page.body.decode())
     if not isinstance(rows, list) or not rows:
         raise ValueError('Empty or non-list Wayback JSON')
     header, *entries = rows
     ...
     for entry in entries:
         row = dict(zip(header, entry, strict=True))
         if (
             row['original'] != original
             or not row['timestamp'].isdigit()
             or len(row['timestamp']) != 14
         ):
             raise ValueError('CDX result outside query')
         if row['statuscode'] == '200':
             replay = f"https://web.archive.org/web/{row['timestamp']}id_/{original}"
     ```
3. **Wayback Replay Validation (`discovery.py:117-126`)**:
   - Checks `match = _WAYBACK_REPLAY_RE.match(candidate_url)` and raises `ValueError` if `target != original`.

#### 4. Why It Does This
- Queries WebHarvest and Internet Archive Wayback CDX indexes to discover historical 200-status captures for dead/walled URLs and construct `id_` raw replay URLs.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 7A (Critical: `wayback_lookup` failed with `invalid_index_response` on 51 of 60 (85%) HTTP 200 CDX responses in `track_b/b2_discovery`!)**:
  - Inspecting all 60 HTTP 200 Wayback CDX responses in `/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-impl/cx_model_design/recovery_campaign_v1/track_b/b2_discovery/calls/*/downloaded.json`:
    1. **Empty JSON `[]` treated as fatal error (`36 / 60` responses)**: When Wayback has 0 captures for a URL, its JSON API returns HTTP 200 with body `[]\n`. In `discovery.py:168`, `if not isinstance(rows, list) or not rows: raise ValueError('Empty or non-list Wayback JSON')` catches `not rows`, marking the lookup `complete=False, reason='invalid_index_response'` instead of `complete=True, candidates=(), reason='complete'`!
    2. **Exact string check `row['original'] != original` rejects valid SURT-matched captures (`15 / 24` non-empty responses — 62.5% of hits!)**: Wayback's `matchType=exact` matches by **SURT key (`urlkey`)**, so it returns captures whose `original` URL had port `:80`, `http://` instead of `https://`, `www.` vs non-`www.`, or `//` in the path. Every single time a row has any of those differences, `row['original'] != original` throws `ValueError('CDX result outside query')` and discards the **entire** CDX response!
       - Concrete examples from `b2_discovery` where valid HTTP 200 PDF captures were thrown away:
         - Query: `https://www.irs.gov/pub/irs-utl/20-Immigration%20and%20Taxation.pdf` $\rightarrow$ CDX returned `http://www.irs.gov:80/pub/irs-utl/20-Immigration%20and%20Taxation.pdf` (status 200, `application/pdf`) $\rightarrow$ **ABORTED!**
         - Query: `https://hcfa.house.gov/110/41994.pdf` $\rightarrow$ CDX returned `http://hcfa.house.gov/110/41994.pdf` (status 200, `application/pdf`) $\rightarrow$ **ABORTED!**
         - Query: `https://www.pgpf.org/sites/default/files/05092016_debt_limit_letter.pdf` $\rightarrow$ CDX returned `http://pgpf.org:80/sites/default/files/05092016_debt_limit_letter.pdf` (status 200, `application/pdf`) $\rightarrow$ **ABORTED!**
         - Also rejected: `nist.gov`, `piie.com`, `integration.samhsa.gov:80`, `crr.bc.edu:80`, `oregon-pip.org:80`, `archives113.transportation.house.gov//sites/...`, `help.senate.gov:80`, `aging.senate.gov:80`, `finance.senate.gov:80`, `foreign.senate.gov:80`, `judiciary.senate.gov:80`.
  - **Fix for `discovery.py:167-190` and `117-126`**:
    - If `rows == []`, return `DiscoveryOutcome(original_url=original, source='wayback', complete=True, reason='complete', candidates=())`.
    - Compare `cdx.key(row['original']) == cdx.key(original)` (or `url_key` equality) instead of `row['original'] != original`.
    - Construct `replay = f"https://web.archive.org/web/{row['timestamp']}id_/{row['original']}"` using `row['original']`, and in `validate_wayback_replay`, validate `cdx.key(target) == cdx.key(original)`.

---

### Stage 8: Public Release & UI Presentation (`archive_format.py`, `archive.ts`, `ArchiveDetail.tsx`)

#### 1. Where the Step Lives
- [archive_format.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_format.py#L65-L82): `_lookup_steps`
- [archive_format.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_format.py#L190-L211): `urls` table (`lookup_key = sha256(lookup_url)`)
- [document-addresses.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/document-addresses.sql#L1-L4), [document-source-input.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/document-source-input.sql#L1-L27), [document-recovery-input.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/document-recovery-input.sql#L1-L6)
- [archive.ts](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/reader/archive.ts#L25-L36): `lookupUrl(value: string)`
- [archive.ts](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/reader/archive.ts#L178-L199): `findUrl`, `findLink`
- [ArchiveDetail.tsx](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/archive/ArchiveDetail.tsx#L107-L120), [ArchiveRows.tsx](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/archive/ArchiveRows.tsx#L17-L19), [provenance.ts](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/browse/provenance.ts#L1-L9)

#### 2. Input & Output Columns
- **Inputs**: `document_addresses(document_id, url)` (union of `document_source_input.url`, `document_recovery_input.original_url`, `document_recovery_input.recovered_url`).
- **Outputs**:
  - `release/urls.parquet`: `(lookup_key BLOB, list_row UINTEGER)` sorted by `lookup_key = sha256(lookup_url)`.
  - `release/document_rows.parquet`: `(list_row, ..., public_url, link_key BLOB)` where `link_key = sha256(public_url)`.
  - `release/sources.parquet` & `release/recoveries.parquet`: literal `url`, `original_url`, `recovered_url`.

#### 3. Exact Transformations Applied
- **Backend (`archive_format.py:65-82` `_lookup_steps`)** and **Frontend (`archive.ts:25-36` `lookupUrl`)** compute `lookup_url`:
  ```ts
  // apps/site/src/components/explorer/reader/archive.ts:25-36
  export function lookupUrl(value: string): string | null {
    const trimmed = value.trim()
    const match = trimmed.match(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\/([^/?#]+)([^?#]*)(?:\?([^#]*))?/)
    if (!match) return null
    const authority = match[1].toLowerCase().replace(/^www\./, '').replace(/:(80|443)$/, '')
    const path = (match[2] || '').replace(/\/+$/, '')
    const query = match[3] ? `?${match[3]}` : ''
    return `${authority}${path}${query}`
  }
  ```
- Hashes `lookup_url` with SHA-256 (`sha256(lookup_url)`) and performs binary search over `urls.parquet` (`findUrl` in `archive.ts:178-190`).
- Meanwhile, `findLink` (`archive.ts:192-199`) hashes the **exact trimmed `public_url` literal** (`sha256(value.trim())`) against `document_rows.link_key`.

#### 4. Why It Does This
- Provides fast client-side SHA-256 binary search in the browser so users can paste a source URL and find the corresponding archived document without shipping `url-rules.json` or Rust UDFs to the browser.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 8A (`_lookup_steps` / `lookupUrl` diverges from Model `url_key` on 22,453 rows in `publish_v20/release/sources.parquet`)**:
  - Unlike `url-normalized.sql` + `url-keys.sql`, `_lookup_steps` and `lookupUrl`:
    1. Do **not** normalize percent-encoding (`16,543` rows in `sources.parquet` have lowercase hex escapes like `%20` vs `%2f` vs `%e2%80%99`; `472` rows have raw unencoded spaces `' '`).
    2. Do **not** repair `&download=1` (`4,270` rows in `sources.parquet` have `&download=1` vs `913` with `?download=1`).
    3. Do **not** strip `congress.gov` `?q=...` (`174` rows in `sources.parquet`) or `utm_*` (`13` rows).
    4. Do **not** unwrap `web.archive.org` (`68` rows in `sources.parquet`, plus all Wayback `recovered_url`s in `recoveries.parquet`).
    5. Do **not** sort query parameters.

---

## Concrete End-to-End Trace of 5 Representative Real URLs

### Trace 1: `mailto:https://www.congress.gov/116/bills/hr7045/BILLS-116hr7045ih.pdf`
*(Also applies to sibling rows `BILLS-116hr6237ih.pdf`, `BILLS-116hr5040ih.pdf`, `BILLS-116hr6636ih.pdf`)*

| Stage | Behavior & Exact Column Values |
| :--- | :--- |
| **Stage 1 (Extraction & Resolution)** | Extracted by `parse_html` (`archive_readings.py:213`) because `_SKIP_SCHEME_RE` (`line 29`) only skips `javascript:`, `data:`, and `vbscript:` (not `mailto:`). In `link-targets.sql:6`, `url_resolve('mailto:https://...', resolved_base)` returns `'mailto:https://www.congress.gov/116/bills/hr7045/BILLS-116hr7045ih.pdf'`. At `link-targets.sql:21`, `NOT regexp_like(resolved, '^https?://[^/?#]+')` sets **`target_error = 'invalid_target'`**. Dropped from `resolved_links` and `publisher_links` (**0 rows**). |
| **Stage 2 (Scheduler)** | Rejected by `_safe_reference` (`capture_scheduler.py:107`: `parts.scheme.lower() not in {'', 'http', 'https'}`). Never scheduled by live scheduler. |
| **Stage 3 (Fetch)** | Never fetched over HTTP. Exists in raw receipts only via legacy assembly import `receipts/documents/undated/assemble-20260930.jsonl.gz` (lines 183639–183642) with `mode = 'fetch'`, `outcome = 'reference'`, `http_status = NULL`, `body_sha = NULL`. |
| **Stage 4 (Lake & Universe)** | Present in `capture_sources.parquet` (4 rows) with `outcome = 'reference'`, `record_role = NULL`. Excluded from `model-url-inputs.sql:8` because `WHERE mode = 'fetch' AND outcome NOT IN ('reference', 'saved-record')`. |
| **Stage 5 (`url_key`)** | Absent from `url_inputs` and `url_keys`. (Even if fed to `url-normalized.sql`, `WHERE regexp_like(parsed, '^https?://[^/?#]+')` at line 48 would drop it.) |
| **Stage 6 (URL State)** | Absent from `url_state.parquet` (**0 rows**). |
| **Stage 7 (Recovery)** | Absent from `url-dispositions.parquet` (**0 rows**). |
| **Stage 8 (Release & UI)** | Absent from `sources.parquet`, `urls.parquet`, and `document_rows.parquet`. |
| **What Should Happen** | Add a `repair` or `wrapper` rule `^(?i)mailto:(https?://.+)$` $\rightarrow$ `$1` in `url-rules.json` (and apply `repair` rules before `url_resolve` in `link-literals.sql` and `url-normalized.sql`) so the erroneous `mailto:` prefix is stripped and the valid Congress.gov bill PDF URL (`congress.gov/116/bills/hr7045/BILLS-116hr7045ih.pdf`) is resolved and captured. |

---

### Trace 2: `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1`
*(Representative of **3,231** `needs_acquisition` and **8,023** total `&download=1` House CreativeEngine URLs)*

| Stage | Behavior & Exact Column Values |
| :--- | :--- |
| **Stage 1 (Extraction & Resolution)** | A witness page links to the base URL `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony`. When that base URL was fetched (`receipts/house/pages/2026-10-12/download-20261012T141417Z-fe374e92a5ee-000005.jsonl.gz`, line 148, HTTP 200, `body_sha = ae5ee73d95a8fada1e9491574799cf263d03114d3f84d830ed26a9f6e1e0934c`), it returned an HTML CreativeEngine wrapper page containing `<a href="https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1">`. **However**, `record-roles.sql:22` classifies `ae5ee73d...` as **`record_role = 'wrapper'`** (not `'page'`). Because `page-contexts.sql:5` requires `record_role = 'page'`, the link inside `ae5ee73d...` is **excluded from `resolved_links` and `publisher_links` (0 rows)**! |
| **Stage 2 (Scheduler)** | During the 2026-10-12 crawl, `capture_scheduler.py:685-705` (`read_discovery_payload`) parsed the HTML body in-memory before `record_role` classification and extracted `href = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1'`. Because `url-normalized.sql` does not mutate literal URLs, it was queued with literal `requested_url = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1'`. |
| **Stage 3 (Fetch)** | Base URL `.../ashley-nunes-witness-testimony` was fetched (HTTP 200 HTML wrapper `ae5ee73d...`). The `&download=1` URL has `attempts = 0` in `url_state.parquet` (and on sibling House servers when fetched with literal `&download=1` in the path, returns HTTP 403 or 404 because ColdFusion/CreativeEngine expects `?download=1` as a query string). |
| **Stage 4 (Lake & Universe)** | Base URL is in `capture_sources.parquet` with `outcome = 'stored', http_status = 200, record_role = 'wrapper', is_real_file = false`. Both the base URL and `&download=1` enter `raw_universe.parquet` and `targets.parquet`. |
| **Stage 5 (`url_key`)** | In `publish_v20` and `plan_v2`, `url_key` is `democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1`. Even with the uncommitted working-tree rule `download-ampersand-query` (`url-rules.json:82-91`), `url_key` becomes `democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1` — which **still does not match** the base URL's `url_key` (`democrats-science.house.gov/download/ashley-nunes-witness-testimony`)! |
| **Stage 6 (URL State)** | In `url_state.parquet`:<br>- Base URL `.../ashley-nunes-witness-testimony`: `attempts = 1, last_status = 200, last_outcome = 'stored', capture_disposition = 'satisfied', capture_reason = 'stored'` (even though only the HTML wrapper was stored, not the PDF!).<br>- `&download=1` URL: `attempts = 0, last_status = NULL, capture_disposition = 'eligible', capture_reason = 'no_satisfying_capture'`. |
| **Stage 7 (Recovery)** | In `url-dispositions.parquet`:<br>- Base URL: `disposition = 'usable_direct', reason = 'usable_direct_baseline'`.<br>- `&download=1` URL: `disposition = 'needs_acquisition', reason = 'needs_acquisition_walled_403_or_unattempted'`, `candidate_count = 0`. |
| **Stage 8 (Release & UI)** | **Completely missing from `document_rows.parquet` and `sources.parquet` (0 rows)**! Because the base URL is `record_role = 'wrapper'` (not `'document'`) and `?download=1` was never fetched, the witness testimony PDF was never published. |
| **What Should Happen** | 1. Rewrite `/download/<slug>(?:%20|\s)*&download=1` $\rightarrow$ `/download/<slug>?download=1` in `link-literals.sql` **and** in `capture_scheduler.py` / `archive_url_state.py` so `requested_url` has `?download=1`.<br>2. Include `record_role IN ('page', 'wrapper')` in `page-contexts.sql:5` so links inside stored download wrapper pages are extracted into `publisher_links`. |

---

### Trace 3: `https://www.aging.senate.gov/404?notfound=/hearings/half-the-country-zero-hearings-meeting-the-moment-to-end-the-menopause-care-gap-in-america.xml`
*(Also `https://www.judiciary.senate.gov/404?notfound=download/01/06/2026/benton-sjq` and `https://www.finance.senate.gov/404?notfound=hearings%2F...` — **337** rows in `capture_sources.parquet`, **53** in `url-dispositions.parquet`)*

| Stage | Behavior & Exact Column Values |
| :--- | :--- |
| **Stage 1 (Extraction & Resolution)** | For `aging.senate.gov` and `judiciary.senate.gov`, 0 rows in `publisher_links` linked to `/404?notfound=...` directly. However, for `finance.senate.gov/404?notfound=hearings%2F...`, 4 captures returned `http_status = 200` on the `/404` page, and `archive_readings.py` extracted `<a href="#main-nav">`, producing **20 rows in `publisher_links.parquet`** with `target_url = 'https://www.finance.senate.gov/404?notfound=hearings%2F...#main-nav'`. |
| **Stage 2 & 3 (Scheduler & Fetch)** | When the original Senate hearing/download URL was fetched, ColdFusion responded with `302 Found` $\rightarrow$ `Location: /404?notfound=...`. In `assemble-20260930.jsonl.gz` (line 138314 for `aging.senate.gov`), the redirect target `https://www.aging.senate.gov/404?notfound=/hearings/...xml` was recorded as both `requested_url` and `url` with `http_status = 404, outcome = 'failed'`. |
| **Stage 4 (Lake & Universe)** | In `capture_sources.parquet` (**337 rows** with `/404?notfound=`), all are classified as `record_role = 'error_response'`. Because `model-url-inputs.sql:7-8` unnests `make_array(requested_url, url)` for all `mode = 'fetch'` captures regardless of `outcome = 'failed'` or `record_role = 'error_response'`, all `/404?notfound=` URLs enter `url_inputs`. |
| **Stage 5 (`url_key`)** | In `publish_v20` and `plan_v2` (built before `senate-notfound`), `url_key` was `aging.senate.gov/404?notfound=/hearings/half-the-country-zero-hearings-meeting-the-moment-to-end-the-menopause-care-gap-in-america.xml`. In the working-tree `url-rules.json:72-81`, `senate-notfound` unwraps `aging.senate.gov` and `judiciary.senate.gov` to `aging.senate.gov/hearings/...` and `judiciary.senate.gov/download/01/06/2026/benton-sjq`, **but fails on `finance.senate.gov/404?notfound=hearings%2F...`** because `"decoder": "none"` leaves `%2F` un-decoded (`finance.senate.gov/hearings%2F...`)! |
| **Stage 6 (URL State)** | In `url_state.parquet`, **53 `/404?notfound=` URLs** appear as standalone `requested_url` rows (`last_status = 404, last_outcome = 'failed', capture_disposition = 'exhausted'`). |
| **Stage 7 (Recovery)** | In `url-dispositions.parquet`, **52** `/404?notfound=` URLs are classified as **`needs_acquisition` (`needs_acquisition_purged_404_410`)** and **1** (`finance.senate.gov`) as **`usable_direct`**! If `discovery.py` queries Wayback/WebHarvest CDX for `target_url = 'https://www.aging.senate.gov/404?notfound=...'`, it queries the 404 error URL instead of the unwrapped hearing URL! |
| **Stage 8 (Release & UI)** | Excluded from `sources.parquet` (0 rows) because `record_role = 'error_response'`. |
| **What Should Happen** | 1. Exclude `record_role = 'error_response'` / `/404?notfound=` redirect targets from `model-url-inputs.sql` and `url-state.sql`.<br>2. Change `senate-notfound` in `url-rules.json:78` to `"decoder": "percent"` with pattern `^(https?://(?:[^/?#]+\.)?senate\.gov)/404\?notfound=(?:%2[fF]|/)?([^#]+).*$`.<br>3. When recovering any historical `/404?notfound=` `requested_url`, query CDX using the unwrapped URL, not the `/404?notfound=` literal. |

---

### Trace 4: `https://web.archive.org/web/20010913024957id_/http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm`
*(And Wayback CDX `:80` captures like `http://www.irs.gov:80/pub/irs-utl/20-Immigration%20and%20Taxation.pdf` — **74** `:80` rows in `current_recoveries.parquet`, **6** `:80` rows in `url-dispositions.parquet`, **15** rejected CDX hits in `b2_discovery`)*

| Stage | Behavior & Exact Column Values |
| :--- | :--- |
| **Stage 1–4 (Ingestion & Universe)** | In `current_recoveries.parquet` (`id = 06768a003a24a46f592de7de7d4a595c6858a5be1dd99e1a036c2f4bd024fd10`), `original_url = 'https://waysandmeans.house.gov/event/h-r-586-the-fairness-for-foster-care-families-act-of-2001/fullcomm/107cong/fc-7act.htm'` and `recovered_url = 'https://web.archive.org/web/20010913024957id_/http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm'`. Also in `capture_sources.parquet`, 6 direct GPO fetches have `requested_url = 'http://www.gpo.gov:80/fdsys/pkg/CHRG-112hhrg.../pdf/...'`. |
| **Stage 5 (`url_key`)** | In `url-normalized.sql`, Pass 1 of `wrapper` rule `wayback` (`url-rules.json:4-11`) extracts `$1 = 'http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm'`. Next, `url_resolve($1, NULL)` (Rust `url::Url::parse`) strips default port `:80` (since scheme is `http`), producing `parsed = 'http://waysandmeans.house.gov/fullcomm/107cong/fc-7act.htm'` and `url_key = 'waysandmeans.house.gov/fullcomm/107cong/fc-7act.htm'`. |
| **Stage 6 (URL State & Provenance)** | `provenance-recovery-attachments.sql` joins on `original_url`'s `url_key` (`waysandmeans.house.gov/event/h-r-586-.../fullcomm/107cong/fc-7act.htm`), attaching the recovery to document `130775` (`list_row = 123613`). |
| **Stage 7 (Recovery & CDX Discovery)** | **Breaks in `discovery.py:178-184` and `117-126`!** While historical recoveries (`current_recoveries.parquet` has 22 `web.archive.org/...:80/` rows) were imported earlier, the new `corpus_recovery/discovery.py` (`wayback_lookup`) checks `if row['original'] != original: raise ValueError('CDX result outside query')`. When querying CDX for `https://www.irs.gov/pub/irs-utl/20-Immigration%20and%20Taxation.pdf`, Wayback returns `original = 'http://www.irs.gov:80/pub/irs-utl/20-Immigration%20and%20Taxation.pdf'`, causing `wayback_lookup` to throw `ValueError` and fail with `cdx_reason = 'invalid_index_response'`! Also, in `url-dispositions.parquet`, the 6 `http://www.gpo.gov:80/...` rows have `host = 'www.gpo.gov:80'` because `campaign.py` extracted `host` without stripping `:80`. |
| **Stage 8 (Release & UI)** | Published in `release/recoveries.parquet` (`list_row = 123613`) with `recovered_url = 'https://web.archive.org/web/20010913024957id_/http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm'`. In `archive_format.py:65-82` (`_lookup_steps`) and `archive.ts:25-36` (`lookupUrl`), `recovered_url` is hashed **without** unwrapping `web.archive.org`, so its `lookup_url` in `urls.parquet` is `web.archive.org/web/20010913024957id_/http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm` (where `:80` is not even stripped because `:80` is inside the path of `web.archive.org`, not the authority!). |

---

### Trace 5: `https://www.gpo.gov/fdsys/pkg/BILLS-115s585rfh/xml/BILLS-115s585rfh.xmlhttps://www.gpo.gov/fdsys/pkg/BILLS-115s585es/xml/BILLS-115s585es.xml`
*(Representative of concatenated file URLs — **1,784** rows in `url-dispositions.parquet`)*

| Stage | Behavior & Exact Column Values |
| :--- | :--- |
| **Stage 1 (Extraction & Resolution)** | Extracted from `https://www.congress.gov/115/bills/s585/BILLS-115s585rfh.xml` (`context_url`). In `link-literals.sql:2-14`, `wrappers = 0`, matches `(?i)^https?://.+https?://`, and has no `[[:space:]?#]`, so `concatenated-file-urls` inserts `\n` before each `https://`. `link-parts.sql` splits it into:<br>- `split_position = 1`: `https://www.gpo.gov/fdsys/pkg/BILLS-115s585rfh/xml/BILLS-115s585rfh.xml`<br>- `split_position = 2`: `https://www.gpo.gov/fdsys/pkg/BILLS-115s585es/xml/BILLS-115s585es.xml`<br>Both pass `file_shapes` validation in `link-targets.sql:22` and enter `publisher_links.parquet` as two clean URLs. |
| **Stage 2 & 3 (Scheduler & Fetch)** | Because `capture_scheduler.py:371` (`seed_rows`) also seeds from `captures.requested_url` and in-run discovery (`read_discovery_payload`) which does **not** run `link-literals.sql`, the un-split concatenated URL was fetched 3 times! Even worse (`capture_sources.parquet` has **18 rows** for `BILLS-115s585rfh`):<br>1. `https://www.gpo.gov/fdsys/pkg/BILLS-115s585rfh/xml/BILLS-115s585rfh.xmlhttps://www.gpo.gov/fdsys/pkg/BILLS-115s585es/xml/BILLS-115s585es.xml` $\rightarrow$ 2 attempts HTTP 500 `failed`, plus 1 legacy `assemble-20260930` row with `http_status = NULL, outcome = 'stored', body_sha = 7e2591ac..., record_role = 'document'`!<br>2. Redirected to `https://www.govinfo.gov/content/BILLS-115s585rfh/xml/BILLS-115s585rfh.xmlhttps:/www.gpo.gov/fdsys/pkg/BILLS-115s585es/xml/BILLS-115s585es.xml` $\rightarrow$ 3 attempts HTTP 500 `failed`!<br>3. Truncated `https://www.govinfo.gov/content/pkg/BILLS-115s585rfh/xml/BILLS-115s585rfh.xmlhttps:` $\rightarrow$ 6 rows (`filename = 'BILLS-115s585rfh.xmlhttps:'`, `record_role = 'error_response'`)! |
| **Stage 4 (Lake & Universe)** | All 3 corrupted URL variants enter `url_inputs` via `model-url-inputs.sql` (`source_addresses` and `captures`). |
| **Stage 5 (`url_key`)** | Because `url-normalized.sql` only runs `r.kind = 'wrapper'` (and never `r.kind = 'repair'`), all 3 corrupted URLs receive `url_key`s in `url_keys`:<br>- `gpo.gov/fdsys/pkg/BILLS-115s585rfh/xml/BILLS-115s585rfh.xmlhttps://www.gpo.gov/fdsys/pkg/BILLS-115s585es/xml/BILLS-115s585es.xml`<br>- `govinfo.gov/content/BILLS-115s585rfh/xml/BILLS-115s585rfh.xmlhttps:/www.gpo.gov/fdsys/pkg/BILLS-115s585es/xml/BILLS-115s585es.xml`<br>- `govinfo.gov/content/pkg/BILLS-115s585rfh/xml/BILLS-115s585rfh.xmlhttps:` |
| **Stage 6 & 7 (URL State & Recovery)** | All 3 corrupted URLs appear in `url_state.parquet`. In `url-dispositions.parquet`, the concatenated URL `https://www.gpo.gov/...BILLS-115s585rfh.xmlhttps://...BILLS-115s585es.xml` is marked `usable_direct` (`usable_direct_baseline`) because of the legacy `7e2591ac...` stored row! |
| **Stage 8 (Release & UI)** | The clean split URLs are published in `document_rows.parquet` (`list_row = 45963` for `BILLS-115s585rfh.xml`, `list_row = 45961` for `BILLS-115s585es.xml`), while `url_state.parquet` retains the 3 corrupted rows. |

---

## Ranked Summary of Architectural Findings & Exact Fixes

1. **[P0 — Stage 7] `wayback_lookup` rejects 85% (51/60) of HTTP 200 Wayback CDX responses (`packages/corpus_recovery/src/corpus_recovery/discovery.py:117-126, 167-190`)**:
   - **Fix**:
     - Treat `rows == []` as an empty result (`complete=True, reason='complete', candidates=()`), not `ValueError('Empty or non-list Wayback JSON')`.
     - Replace `row['original'] != original` with `cdx.key(row['original']) != cdx.key(original)` (or normalized `url_key` comparison).
     - Build `replay = f"https://web.archive.org/web/{row['timestamp']}id_/{row['original']}"` using `row['original']`, and relax `validate_wayback_replay` to compare `cdx.key(target) == cdx.key(original)`.

2. **[P0 — Stages 1, 2, 5] House `&download=1` URLs (3,231 `needs_acquisition` rows; 8,023 total pairs) are never repaired in `requested_url` and do not share `url_key` with their base `/download/<slug>` URL**:
   - **Fix**:
     - Apply `download-ampersand-query` (`^(https?://[^/?#]+/download/[^?#]*?)(?:%20|\s)*&download=1([&#].*)?$` $\rightarrow$ `$1?download=1$2`) to the **literal target URL** in `link-literals.sql` and `capture_scheduler.py` / `archive_url_state.py` so the HTTP client actually requests `?download=1`.
     - Update `page-contexts.sql:5` from `WHERE record_role = 'page'` to `WHERE record_role IN ('page', 'wrapper')` so `<a href="...&download=1">` links inside the **3,213** stored HTML download wrapper pages are extracted into `publisher_links`.
     - Strip trailing `(?:%20)+` at the end of URL paths in `url-normalized.sql` (**38** URLs affected).

3. **[P1 — Stage 2 & 6] `capture-scope.json` and `min(url)` run on raw literal URLs instead of unwrapped, `https://`-upgraded URLs (`capture_scheduler.py:390-397`, `archive_url_state.py:70-80`)**:
   - **Fix**:
     - Evaluate `capture-scope.json` against the unwrapped URL (`u.value` from `url-normalized.sql`), or allow `^https?://` in `capture-scope.json` (**100,725** `http://` targets currently fail scope).
     - When selecting the representative fetch URL per `url_key`, prefer `https://` over `http://` and `?download=1` over `&download=1` (`min(u.value)` after wrapper/repair rules) instead of `min(raw_literal_url)`.

4. **[P1 — Stage 6] `archive_url_state.py:131-134, 166` joins recoveries on exact literal `original_url` instead of `url_key`**:
   - **Fix**: Join `url_state_history` to `unambiguous` via `url_keys` (`h.url_key = u.url_key`), matching `model/sql/provenance-recovery-attachments.sql:3`.

5. **[P2 — Stages 4 & 5] Senate `/404?notfound=` soft-404 redirects (`337` capture rows, `53` disposition targets), `mailto:https://...`, and concatenated URLs (`1,784` disposition targets)**:
   - **Fix**:
     - In `url-rules.json:72-81`, change `senate-notfound` to `"decoder": "percent"` with pattern `^(https?://(?:[^/?#]+\.)?senate\.gov)/404\?notfound=(?:%2[fF]|/)?([^#]+).*$`.
     - Add `^(?i)mailto:(https?://.+)$` $\rightarrow$ `$1` and expand `lis-gpo` to `^https?://(?:www\.)?(?:lis|congress)\.gov/cgi-lis/t2GPO/(https?://.+)$`.
     - Filter `record_role = 'error_response'` out of `model-url-inputs.sql:7-8` when unnesting redirect `url`s.

6. **[P2 — Stage 8] Public release `_lookup_steps` (`archive_format.py:65-82`) and `lookupUrl` (`archive.ts:25-36`) diverge from `url_key` on 22,453 `sources.parquet` rows**:
   - **Fix**: Index `urls.parquet` by `sha256(url_key)` (from `url_keys`) and align `lookupUrl` in `archive.ts` (percent-encoding normalization, query param sorting, `utm_*`/`q=` stripping, and wrapper unwrapping).