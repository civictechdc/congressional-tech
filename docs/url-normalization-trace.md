# Bottom-Up URL Normalization & Lifecycle Audit (Stages 1–8)

## Executive Summary

Across the 8 stages of the `congressional-tech` pipeline, URLs pass through **four distinct normalization/keying implementations** that do not agree with each other, and **one fundamental architectural split** between **literal URLs** (`url`, `target_url`, `requested_url`) and **normalized identity keys** (`url_key`, `surt`, `lookup_key`):

1. **The Literal-vs-Normalized Split (`url-normalized.sql` vs. `capture_scheduler.py` / `archive_url_state.py`)**:
   - Stage 5 (`model/sql/url-normalized.sql` + `model/sql/url-keys.sql`) unwraps archival/security wrappers (`wayback`, `loc`, `proofpoint-v2`, `lis-gpo`, `senate-notfound`) and repairs malformed query delimiters (`download-ampersand-query`: `/download/<slug>&download=1` $\rightarrow$ `/download/<slug>?download=1`), **but only uses the transformed string to compute `url_key` while keeping `url_keys.url` as the raw literal string** (`-- Literal values remain unchanged`).
   - Downstream, Stage 2 (`capture_scheduler.py:391-397`) and Stage 6 (`archive_url_state.py:70-80`) select `min(url)` / `min(l.target_url)` as `requested_url` and evaluate `capture-scope.json` against that **un-repaired literal URL**.
   - **Consequences in the corpus**:
     - **3,231 `needs_acquisition` `&download=1` URLs in `plan` (`1,668` in `plan_v2` Gen 1 after Wave 4 recovered `1,563`; `1,415` in `plan_v2` Gen 2 after Wave 5 recovered `226` Poppler-verified PDFs + `3` DOCX + `24` redirect-location corpus matches)**: In `capture_sources.parquet`, **100% (`4,062 / 4,062`) of historical HTTP 200 real-file captures with literal `&download=1` are on 4 Senate hosts (`finance`, `banking`, `appropriations`, `budget.senate.gov`), while `0 / 4,062` (`0%`) are on `*.house.gov`** (all `19` House HTTP attempts returned `410 Gone`). Across Waves 4–5, out of **1,804** `needs_acquisition` House `&download=1` targets tested by rewriting `&download=1` $\rightarrow$ `?download=1`, **1,792 (`99.33%`)** succeeded and became qualified `accepted_recovery` documents (and `10` of the remaining `12` redirected `302` to `/imo/media/doc/<Filename>.pdf`, failing only due to `0`-byte origin files or size/qualification limits).
     - **100,725 `http://` target URLs** and all wrapped links (`web.archive.org`, `webarchive.loc.gov`, `urldefense.proofpoint.com`, `lis.gov/cgi-lis/t2GPO/`) fail `capture-scope.json` when `capture-scope.json` is anchored with `^https://` and evaluated before unwrapping or `http` $\rightarrow$ `https` upgrade (and when both `http://` and `https://` exist for a `url_key`, `min(url)` picks `http://` and drops it during scope filtering).

2. **Four Distinct URL Keying Functions Across the Pipeline**:
   - **Model `url_key`** (`model/sql/url-normalized.sql` + Rust `url_resolve`/`uri_normalize_encoding`): 2-pass `url-rules.json` `wrapper` unwrap $\rightarrow$ WHATWG URL parse (strips `:80`/`:443`, lowercases scheme/host, resolves `..`, encodes spaces) $\rightarrow$ RFC 3986 unreserved percent-decode & uppercase hex $\rightarrow$ strips `^www\.`, `#fragment`, single trailing `/` (`/$`) $\rightarrow$ strips `utm_*` and `congress.gov` `q=` $\rightarrow$ sorts query params.
   - **Archive State Custody Joins vs. Provenance Attachment Joins** (`archive_url_state.py:129-166` vs. `provenance-recovery-attachments.sql`): `archive_url_state.py` intentionally enforces **exact literal string equality** (`d.original_url = r.original_url`, `c.original_url = d.original_url`, `h.requested_url = u.original_url`) to verify per-target `recovery_requirements`, `refresh_policy = 'historical_only'`, receipt custody, and unambiguous 1:1 mapping (`capture_disposition` in `{'excluded', 'satisfied', 'eligible'}` and `capture_reason` in `{'scope_exclusion', 'qualified_recovery', 'no_satisfying_recovery'}`), whereas `url_key`-alias resolution happens in candidate discovery (`stored_url_key_alias`, resolving **35** of **36** alias rows in `plan_v2`) and `provenance-recovery-attachments.sql` attaches accepted recoveries to documents via `url_key`.
   - **Corpus Recovery CDX & Wayback Validation** (`corpus_recovery/cdx.py:28-37` & `discovery.py:117-246`): Uses `surt.surt(url)` for WebHarvest CDX, but in `wayback_lookup` enforces **exact literal equality** `row['original'] != original` and treats empty JSON `[]` in `_wayback_page` as an error—causing **51 of 60 (85%) HTTP 200 Wayback CDX responses** in `track_b/b2_discovery` to fail with `invalid_index_response` (**36** empty `[]` responses and **15 of 24 non-empty hits** rejected solely because Wayback's SURT-matched `original` had `:80`, `http://`, `www.`, or `//`, discarding `88` of `237` valid snapshot rows).
   - **Public Release `DM8.2` `lookup_key`** (`archive_format.py:61-82` `_lookup_steps` & `archive.ts:25-36` `lookupUrl`): Implements the locked `DM8.2` lookup contract (first 8 bytes of `sha256('lookup:' || lookup_url)`, where `lookup_url` lowercases scheme/host and strips `www.`, `:80`/`:443`, `#fragment`, and a single trailing `/` while keeping query bytes intact). All **605,848** published rows in `sources.parquet` match their own `DM8.2` lookup entry; however, for **cross-spelling user lookups**, `lookupUrl` differs from `url_key` on URLs with raw spaces (`472` rows vs browser `%20`), uppercase hex escapes (`987` rows matching `%([0-9A-Fa-f][A-F]|[A-F][0-9A-Fa-f])` and `826` matching `%[0-9A-F][A-F]` vs lowercase user input; note `16,543` rows have numeric `%[0-9]{2}` like `%20` and `0` have lowercase hex), `&download=1` (`4,270` rows vs `913` `?download=1`), Congress.gov `?q=` (`174` rows), Wayback wrappers (`68` rows), and `utm_*` (`13` rows).

---

## Stage-by-Stage Overview Table

| Stage | Name | Primary Code Locations | Input URL Column(s) | Output URL / Key Column(s) | Mutates Literal URL? | Key Transformations Applied | Top Corpus Quantified Bug / Gap |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Link Extraction & Contextual Resolution** | `archive_readings.py:103-265`<br>`model/sql/page-contexts.sql`<br>`model/sql/link-*.sql`<br>`model/sql/publisher-links.sql` | `readings.links[].href`, `readings.base_href`, `page_contexts.origin` (`coalesce(url, requested_url)`) | `resolved_links.target_url`<br>`publisher_links.target_url`, `url_key` | **Yes** (`target_url` is resolved via `url_resolve` and split on `repair` rules) | Strips controls `[\x00-\x20]`; splits `concatenated-file-urls` (`wrappers=0`, no `[?#\s]`); WHATWG `url_resolve(target_literal, resolved_base)` | `publisher-links.sql:4` `INNER JOIN copy_url_keys` associates links with captured sources (`913,034` rows in `publish_v20`), while acquisition discovers unfetched targets via `resolved_link_targets`; `mailto:https://...` fails `^https?://`; `1,385` `publisher_links` rows contain `https?://.+https?://` |
| **2** | **Capture Scheduler & Admission** | `capture_scheduler.py:67-113, 365-413, 685-705`<br>`archive_url_state.py:63-85`<br>`capture-scope.json` | `resolved_link_targets`, `captures.requested_url`, `url_state_latest`, live HTML discovery `href` | `queue.requested_url`, `url_key` | **No** (`_safe_reference` validates; `min(url)` keeps raw literal) | `_safe_reference` validates scheme/host/length/no-credentials; `keyed_states` takes `s.requested_url` and suppresses same-key seeds; `seed_keys` picks `min(url)`; filters by `capture-scope.json` and `campaign_targets` | `min(url)` picks `&download=1` over `?download=1` (`0/4,062` House literal `&download=1` fetches succeeded; `1,792/1,804` succeeded when rewritten to `?download=1`) and picks `http://` over `https://` |
| **3** | **HTTP Fetch & Redirect Handling** | `fetcher.py:25-125`<br>`receipt_writer.py:135-210`<br>`receipt_privacy.py:36-74` | `requested_url` | `receipt.requested_url`, `receipt.url` (final or blocked redirect URL) | **Yes** on redirect (`url = urljoin(transfer.url, location)`) & `sanitize_url` | Follows up to 6 redirects (`for step in range(7)`) if `CaptureScope(target)` matches; redacts `credential-parameters.json` query params in receipts | Redirects to out-of-scope hosts fail with `excluded_redirect`; Senate 302s to `/404?notfound=...` record the 404 error URL as `url` (**337** rows in `capture_sources.parquet`) |
| **4** | **Lake Ingestion & URL Universe** | `captures.py:253-311`<br>`model/sql/capture-sources.sql`<br>`model/sql/model-url-inputs.sql` | `requested_url`, `url`, `context_url`, `original_url`, `recovered_url`, `resolved_links.target_url` | `url_inputs.url` | **No** (`trim()` only in `captures.py`) | Unions all source addresses, contexts, resolved links, recoveries, and `unnest([requested_url, url])` from `mode='fetch'` captures | `model-url-inputs.sql:7-8` ingests failed/error-redirect `url`s and legacy `assemble-20260930` literals (**53** `/404?notfound=` URLs, **1,784** concatenated `https://...https://...` URLs, and legacy `http://File URL path: ...` into `url-dispositions.parquet` totaling `1,202,155` rows) |
| **5** | **Native SQL Normalization & `url_key`** | `model/sql/url-normalized.sql`<br>`model/sql/url-keys.sql`<br>`url-rules.json`<br>`functions.rs:577-637` | `url_inputs.url` | `url_normalized(url, error, still_wrapped, base_key)`<br>`url_keys(url, url_key)` | **No** (`url_keys.url` is untouched; only `url_key` is normalized) | 2-pass `wrapper` unwrap $\rightarrow$ `uri_normalize_encoding(url_resolve(val, NULL))` $\rightarrow$ strip `^www\.`, `#frag`, single trailing `/` (`/$`) $\rightarrow$ strip `utm_*`, `q=` $\rightarrow$ sort query | `senate-notfound` (`535375d1`) lacks `"decoder":"percent"` (`%2F`) and fails to match when `#main-nav` fragment is present (**20** rows in `publisher_links.parquet`); `download-ampersand-query` lacks `(?:#.*)?$` |
| **6** | **Archive URL State & Recovery Attachment** | `archive_url_state.py:55-180`<br>`model/sql/url-state.sql`<br>`model/sql/provenance-recovery-*.sql` | `captures.requested_url`, `url_keys.url_key`, `current_recoveries.original_url` | `url_state.parquet` (7 cols in v1 `publish_v20`; 10 cols in v2 `release_v2`) | **No** | `archive_url_state.py:129-166` enforces literal `original_url` custody joins (`eligible`, `satisfied`, `excluded`); `stored_url_key_alias` mints candidate decisions for `url_key` aliases; `provenance-recovery-attachments.sql` joins on `url_key` | **35** of **36** `url_key` alias targets were resolved into `accepted_recovery` (`satisfied`, `qualified_recovery`) in `plan_v2` / `release_v2` via `stored_url_key_alias` |
| **7** | **Corpus Recovery Campaign & CDX Discovery** | `campaign.py:92-199`<br>`discovery.py:53-246`<br>`cdx.py:28-37`<br>`reconcile.py:123-299` | `targets.target_url`, `url_key` | `lookup_key` (`surt`), `candidate_url` (`web.archive.org/web/{ts}id_/{url}`) | **Yes** (constructs Wayback replay URL) | `cdx.py` computes `surt.surt(url)`; `wayback_lookup` queries CDX `matchType=exact` and checks `row['original'] != original` | **51/60 (85%)** HTTP 200 Wayback CDX calls in `b2_discovery` failed with `invalid_index_response`: **36** on empty `[]` and **15/24** non-empty hits rejected because `row['original']` had `:80`, `http://`, `www.`, or `//` |
| **8** | **Public Release & UI Lookup** | `archive_format.py:61-82, 190-211`<br>`archive.ts:25-36, 178-199`<br>`ArchiveDetail.tsx:107-120` | `document_addresses.url` (`sources.parquet`, `recoveries.parquet`) | `urls.lookup_key` (8-byte prefix of `sha256('lookup:' \|\| lookup_url)`), `link_key` | **No** (renders literal `public_url` in UI) | `_lookup_steps` / `lookupUrl`: regex parse, lowercase scheme/host, strip `^www\.`, `:80`/`:443`, `#fragment`, single trailing `/` (`DM8.2` contract) | All **605,848** `sources.parquet` rows match their own `DM8.2` key; cross-spelling user pastes differ on **472** raw-space URLs, **987** uppercase hex URLs, **4,270** `&download=1`, **174** `?q=`, **68** Wayback URLs |

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
  - `publisher_links`: `(context_url, context_key, target_url, url_key, href, split_position)` (`913,034` rows in `publish_v20/model/evidence/publisher_links.parquet`)

#### 3. Exact Transformations Applied
1. **HTML/XML/JSON Extraction (`archive_readings.py`)**:
   - **HTML (`parse_html`, lines 181–225)**: Strips `[\x00-\x20]+` from the start/end of raw `href`/`src`/`data` attributes (`_STRIP_CONTROLS_RE`). Ignores `href`s starting with `#` or matching `^(?:javascript|data|vbscript):` (`_SKIP_SCHEME_RE`, line 29) — **note that `mailto:` is NOT in `_SKIP_SCHEME_RE`**. Also extracts `<base href>` (first match) and `<meta http-equiv="refresh" content="...;url=...">`.
   - **XML (`parse_xml`, lines 228–252)**: Extracts attributes in `_XML_URL_ATTRS` (`href`, `src`, `url`, `xlink:href`) and text of leaf elements in `_XML_URL_ELEMENTS` (`url`, `link`, `file-url`, `pdf-url`, `document-url`, `target-url`, `location`) if text contains `/` or starts with `http://`/`https://`.
   - **JSON (`parse_json`, lines 255–265)**: Extracts string values starting with `https://`, `http://`, or `/` (where second char is not `/`).
2. **Page Context Filtering (`page-contexts.sql:1-11` & `archive_url_state.py:61-63`)**:
   - `page-contexts.sql` selects `WHERE h.sha256 IS NULL AND NOT coalesce(r.format = 'xml' AND r.record_role = 'listing', false)` (so `record_role = 'wrapper'` pages **are** included in `page_contexts` and `resolved_links`), while `publisher-links.sql:4` performs an `INNER JOIN` against `copy_url_keys` (already-captured sources).
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

#### 5. Architectural Distinctions, Gaps & Corpus Counts
- **Distinction 1A (`publisher-links.sql` Source Association vs. `resolved_link_targets` Acquisition Discovery)**:
  - House CreativeEngine download landing pages (e.g. `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony`, `body_sha = ae5ee73d95a8fada1e9491574799cf263d03114d3f84d830ed26a9f6e1e0934c`) are classified as `record_role = 'wrapper', is_real_file = false`.
  - In `page_facts.parquet` and `readings_full_0cb`, `ae5ee73d...` has `link_count = 87, status = 'completed'`, including `href = '//democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1'` and 4 self-fragment links (`#main-nav`, `#skip-nav`, `#`, `#`).
  - `model/sql/publisher-links.sql:4` associates resolved links with already-captured source identities via `INNER JOIN copy_url_keys`: the 4 `#fragment` links strip `#...` and match the wrapper's own captured address (`source_id = 3746c1fd...`), whereas an unfetched download target (`&download=1`) has no captured source row yet and is therefore absent from `publisher_links.parquet`.
  - Meanwhile, acquisition discovers targets independently through `resolved_link_targets` in [archive_url_state.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_url_state.py#L70-L85), where `url_state_queue` (`lines 77–85`) applies scope, `target_member_path IS NULL`, `url_key IS NOT NULL`, and `NOT EXISTS (SELECT 1 FROM url_state_fetched_keys f WHERE f.url_key = k.url_key)` filters (which excludes the 4 self-fragment links at line 84 while admitting the unfetched `&download=1` target into discovery). Keeping separate `url_key` identities for the wrapper landing page (`/download/<slug>`) and its downloadable document (`/download/<slug>?download=1`) is proper model separation, not a defect.
- **Bug 1B (`mailto:https://...` and legacy `http://File URL path: ...` receipt literals)**:
  - In HTML pages, authors occasionally write `<a href="mailto:https://www.congress.gov/116/bills/hr7045/BILLS-116hr7045ih.pdf">`. Because `mailto:` is not stripped before `url_resolve`, `url_resolve` parses scheme `mailto:`, which fails `^https?://[^/?#]+` in `link-targets.sql:21` (`invalid_target`).
  - Separately, `http://File URL path: /sites/default/files/documents/7.7.17DallinMaybeeTestimoney.pdf` in `url-dispositions.parquet` did not come from `url_resolve` (which resolves a relative `File URL path: ...` under the base host and rejects an absolute `http://File URL path: ...` with `NULL`); rather, it entered `captures` as a literal `requested_url` in legacy receipt `receipts/documents/2026-09-29/assemble-20260930.jsonl.gz` (`source_id = 59762db1...`), and `campaign.py:83` extracted `host = 'File URL path: '` via regex.
- **Bug 1C (`link-literals.sql` only repairs `wrappers = 0` without `[?#\s]`, leaving 1,385 concatenated rows in `publisher_links.parquet`)**:
  - In `publish_v20/model/evidence/publisher_links.parquet` (`913,034` rows), **1,385 rows (507 distinct `target_url`s)** still match `(?i)^https?://.+https?://` (including `http://www.congress.gov/cgi-lis/t2GPO/http://www.gpo.gov/...`, `exit.asp?link=http://...`, and concatenated URLs where one URL has a query string or space).

---

### Stage 2: Capture Scheduler & Admission (`capture_scheduler.py` & `archive_url_state.py`)

#### 1. Where the Step Lives
- [capture_scheduler.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L67-L113): `CapturePolicy` and `_safe_reference`
- [capture_scheduler.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L365-L413): `plan_queue`
- [capture_scheduler.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L685-L705): `read_discovery_payload` (in-run link extraction)
- [archive_url_state.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_url_state.py#L63-L85): `url_state_queue`
- [capture-scope.json](file:///Users/mikewolfd/Work/congressional-tech/model/registries/capture-scope.json#L1-L129)

#### 2. Input & Output Columns
- **Inputs**: `resolved_link_targets`, `url_state_latest` / `captures.requested_url`, live HTML discovery `href`, `url_rules`, `capture-scope.json`, optional `campaign_targets`.
- **Outputs**: `queue.requested_url`, `queue.url_key` (in `capture_scheduler.py`) and `url_state_queue.requested_url`, `url_state_queue.url_key` (in `archive_url_state.py`).

#### 3. Exact Transformations Applied
1. **Reference Validation (`_safe_reference`, `capture_scheduler.py:99-113`)**:
   - Pure boolean validation helper: checks `bool(value)`, `len(value) <= 16384`, no control characters (`ord(ch) < 0x20 or ord(ch) == 0x7F`), `validate_record(value)`, `urlsplit(value)` scheme in `{'', 'http', 'https'}`, hostname present when scheme is present, no `username`/`password`, and no query keys in `credential_parameters()`. (Does not mutate or call `urljoin`.)
2. **State Precedence, Key Grouping & Representative Literal Selection (`capture_scheduler.py:377-405` & `archive_url_state.py:70-85`)**:
   - Computes `url_key` via `url-normalized.sql` / `url-keys.sql` (note `url-normalized.sql` exports `(url, error, still_wrapped, base_key)`).
   - In `capture_scheduler.py:392-396`, existing `url_state_latest` rows (`keyed_states`) take `s.requested_url` directly and suppress same-`url_key` rows from `seed_urls` (`LEFT ANTI JOIN keyed_states s ON o.url_key = s.url_key`).
   - For new seeds (`seed_urls` / `queue_literals`), groups by `url_key` and selects `min(url)` (or `min(l.target_url)`) as `requested_url`.
   - In campaign mode (`capture_scheduler.py:381`), requires `EXISTS (SELECT 1 FROM campaign_targets t WHERE t.target_url = scoped.requested_url)`.
3. **Scope Filtering (`capture-scope.json`)**:
   - Evaluates `capture-scope.json` regexes against `requested_url` / `l.target_url`.

#### 4. Why It Does This
- Deduplicates the fetch queue by `url_key`, preserves attempt state history on existing `url_state` rows, and enforces domain and campaign target scoping.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 2A (Critical: `min(url)` and `keyed_states` schedule un-repaired `&download=1` and `http://` literals)**:
  - Confirmed by native reproduction: in ASCII, `'&'` (0x26) < `'?'` (0x3F), and `'http://'` < `'https://'`. When both `&download=1` and `?download=1` exist for a `url_key`, `min(url)` picks `&download=1`; when both `http://` and `https://` exist, `min(url)` picks `http://` and discards it during `^https://` scope filtering.
  - Furthermore, sorting alone cannot create `?download=1` when the only observed seed literal contains `&download=1`, and changing `seed_urls` alone leaves existing `keyed_states` rows (`s.requested_url`) untouched and must also preserve `campaign_targets` membership (`capture_scheduler.py:381`).
  - **House vs. Senate Empirical Split (`capture_sources.parquet` & `url-dispositions.parquet`)**:
    - All **4,062** distinct literal `&download=1` URLs (`4,309` capture rows) with HTTP 200 real files in `capture_sources.parquet` are on 4 Senate hosts (`finance.senate.gov`: `1,569`, `banking.senate.gov`: `1,417`, `appropriations.senate.gov`: `734`, `budget.senate.gov`: `342`); **0** are on House hosts (`19` HTTP attempts on `democrats-transportation.house.gov`, all returning HTTP `410`).
    - Across Waves 4–5, out of **1,804** `needs_acquisition` House `&download=1` targets tested by rewriting `&download=1` $\rightarrow$ `?download=1`, **1,792 (`99.33%`)** succeeded and became accepted recoveries (`1,563` `retained_candidate_repaired_download_query` + `226` `retained_candidate_repaired_download_query_poppler_verified` + `3` `retained_candidate_repaired_download_query_docx`), while `24` more were recovered via `retained_candidate_redirect_location_corpus_match`, reducing pending `&download=1` targets from `3,231` (`plan`) $\rightarrow$ `1,668` (`plan_v2` Gen 1) $\rightarrow$ `1,415` (`plan_v2` Gen 2: `1,411` House + `4` Senate).

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
1. **Pre-Flight & Redirect Scope Check (`fetcher.py:67-68, 89-112`)**:
   - Loops `for step in range(7):` (up to 6 redirects; returns `error='redirect_limit'` on `step == 6`), checking `self.scope(current)` before each hop.
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
- **Bug 3B (`spool_limit = 16 MB` in `Fetcher` and `max_input_bytes = 16 MB` in `QualificationConfig` drop large congressional hearing volumes)**:
  - Across Waves 3–6, `15` legitimate House/Senate hearing PDFs (`17 MB` to `157 MB`, e.g. `HHRG-115-IF02-20180508-SD005.pdf` at `157 MB` and `HHRG-115-IF17-Wstate-SmithR-20171003-SD013.pdf` at `83 MB`) returned HTTP 200 over Direct HTTP but failed with `outcome = 'size_limit'` until `spool_limit` and `max_input_bytes` were raised to `256 MB` in Wave 6.

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
- **Distinction 5B (Wrapper Page `/download/<slug>` vs. Downloadable Document `/download/<slug>?download=1`)**:
  - `download-ampersand-query` (`url-rules.json:82-91`) rewrites `.../download/slug&download=1` to `.../download/slug?download=1`, which gets `url_key = .../download/slug?download=1`, whereas the landing wrapper page `.../download/slug` gets `url_key = .../download/slug`.
  - Preserving separate `url_key` identities for the HTML landing wrapper (`/download/<slug>`) and its downloadable document (`/download/<slug>?download=1`) is proper model separation; what is required for acquisition is generating `/download/<slug>?download=1` as the repaired fetch candidate whenever `/download/<slug>&download=1` is queued.
- **Bug 5C (`senate-notfound` in `url-rules.json:72-81` uses `"decoder": "none"` and lacks `(?:#.*)?$`, failing on `%2F` and `#main-nav`)**:
  - In `publisher_links.parquet` (`20` rows across `3` distinct URLs), `finance.senate.gov` redirects to `https://www.finance.senate.gov/404?notfound=hearings%2Fthe-presidents-fiscal-year-2024-irs-budget-and-the-irss-2023-filing-season#main-nav` (plus `#skip-nav` and `#`).
  - First, because `url-normalized.sql` runs `wrapper` rules before stripping `#fragment` (`components`, lines 34–35), the `([^#]+)$` anchor in `url-rules.json:76` fails to match whenever a `#fragment` (like `#main-nav`) is present! The same fragment anchor gap applies to `download-ampersand-query` (`&download=1$`).
  - Second, because `senate-notfound` has `"decoder": "none"`, `$1/$2` produces `https://www.finance.senate.gov/hearings%2F...`. Since `/` is a reserved RFC 3986 character, `uri_normalize_encoding` does **not** decode `%2F`, yielding `url_key = finance.senate.gov/hearings%2F...` instead of `finance.senate.gov/hearings/...`!
  - **Fix**: Set `"decoder": "percent"` on `senate-notfound` and match `(?i)^(https?://(?:[a-z0-9-]+\.)+senate\.gov)/404\?notfound=(?:%2f|/)?([^#]+)(?:#.*)?$`.
- **Note 5D (Why Global Trailing `%20` Path Trimming `(?:%20|/)+$` Is Withdrawn)**:
  - `url::Url::parse` strips raw ASCII whitespace at the end of a URL, while preserving pre-encoded `%20` (`35` rows in `plan` and `plan_v2` match `ends_with(target_url, '%20')`).
  - However, replacing `regexp_replace(c.path, '/$', '')` (`url-normalized.sql:48`) with `(?:%20|/)+$` globally would also collapse multiple trailing slashes (`/report//` $\rightarrow$ `example.gov/report` instead of `example.gov/report/`) and merge trailing `%20` across every host without evidence. Instead, `%20` before `&download=1` is handled by `download-ampersand-query` (`(?:%20|\s)*&download=1`), and any publisher-specific trailing-space alias is handled via explicit candidate/variant rules.
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
- **Outputs**:
  - `publish_v20/release/url_state.parquet` (`capture_profile.json` v1, built with `recovery_policy=None` — 7 columns): `['requested_url', 'attempts', 'last_attempt', 'last_status', 'last_outcome', 'last_good_at', 'next_attempt_at']`.
  - `recovery_campaign_v1/release_v2/url_state.parquet` (`capture_profile.json` v2, built with `recovery_policy` enabled — 10 columns): appends `['capture_disposition', 'capture_reason', 'capture_decision_id']` from `model/registries/capture-eligibility-fields.json`.

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
- Computes the operational state (`capture_disposition` in `{'excluded', 'satisfied', 'eligible'}` and `capture_reason` in `{'scope_exclusion', 'qualified_recovery', 'no_satisfying_recovery'}`) of every queued or fetched URL while enforcing per-target `recovery_requirements`, `refresh_policy = 'historical_only'`, receipt custody (`c.original_url = d.original_url`), and unambiguous 1:1 decision mapping per `original_url`.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Architectural Design Note (`archive_url_state.py:129-166` Literal Custody Joins vs. `stored_url_key_alias` Candidate Resolution)**:
  - Because `archive_url_state.py:129-166` enforces per-target `recovery_requirements`, `refresh_policy = 'historical_only'`, receipt binding, and unambiguous 1:1 checks on `original_url`, replacing it with a bare `url_key` join would weaken those custody invariants.
  - Instead, `url_key` aliases (`36` rows in `plan/url-dispositions.parquet` with `subtype = 'retained_r2_url_key_alias'`) are resolved in the candidate discovery/reconciliation layer by minting explicit `recovery_decisions` and `retained_captures` records (`candidate_source = 'stored_url_key_alias'`), which moved **35** of those **36** rows (all except 1 `.wmv` video on Dropbox) to `disposition = 'accepted_recovery'` (`capture_disposition = 'satisfied', capture_reason = 'qualified_recovery'`) in `plan_v2` and `release_v2/url_state.parquet`.

---

### Stage 7: Corpus Recovery Campaign & CDX Discovery (`campaign.py`, `discovery.py`, `cdx.py`, `reconcile.py`)

#### 1. Where the Step Lives
- [campaign.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/campaign.py#L92-L199): `plan_campaign`
- [discovery.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/discovery.py#L53-L246): `webharvest_lookup`, `validate_wayback_replay`, `_wayback_page`, `wayback_lookup`, `acquire_candidate`
- [cdx.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/cdx.py#L28-L37): `key(url)` (`surt.surt`)
- [reconcile.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/reconcile.py#L123-L299)

#### 2. Input & Output Columns
- **Inputs**: `targets.parquet` (`target_url`, `url_key`, `host`, `disposition`, `reason`), WebHarvest CDX (`key` = SURT), Wayback CDX API (`url=original&matchType=exact`).
- **Outputs**: `candidates.parquet` / `lookup_summary.parquet` (`original_url`, `candidate_url`, `timestamp`, `source`, `cdx_complete`, `cdx_reason`), `retained_captures.parquet`.

#### 3. Exact Transformations Applied
1. **WebHarvest CDX Lookup (`cdx.py:28-37` & `discovery.py:53-115`)**:
   - Computes `surt_key = surt.surt(original_url)` and queries local DuckDB CDX index `WHERE key = ?`.
2. **Wayback CDX Lookup (`discovery.py:129-215`)**:
   - Requests `https://web.archive.org/cdx/search/cdx?url={quote(original, safe='')}&matchType=exact&output=json&fl=urlkey,timestamp,original,mimetype,statuscode,digest,length&showResumeKey=true&limit=...`.
   - Parses JSON response in `_wayback_page(body)` (`lines 129–146`) and validates rows in `wayback_lookup` (`lines 178–193`):
     - Currently raises `ValueError('Invalid Wayback JSON')` in `_wayback_page` when `data == []`.
     - Currently checks `row['original'] != original` in `wayback_lookup`, rejecting any row whose archived `original` spelling differs from `original` even when `row['urlkey']` matches the queried SURT.
3. **Wayback Replay Validation (`discovery.py:117-126` & `227-239`)**:
   - `acquire_candidate` (`line 232`) passes `candidate['original_url']` to `acquire_wayback(url, original, timestamp, ...)`, which calls `validate_wayback_replay(url, original, timestamp)` (`lines 117–126`) to enforce exact host, timestamp, and `id_/{original}` match.

#### 4. Why It Does This
- Queries WebHarvest and Internet Archive Wayback CDX indexes to discover historical 200-status captures for dead/walled URLs and construct `id_` raw replay URLs.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Bug 7A (Critical: `wayback_lookup` failed with `invalid_index_response` on 51 of 60 (85%) HTTP 200 CDX responses in `track_b/b2_discovery`!)**:
  - Inspecting all 60 HTTP 200 Wayback CDX responses in `/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-impl/cx_model_design/recovery_campaign_v1/track_b/b2_discovery/calls/*/downloaded.json`:
    1. **Empty JSON `[]` treated as fatal error (`36 / 60` responses)**: When Wayback has 0 captures for a URL, its JSON API returns HTTP 200 with body `[]\n`. In `_wayback_page` (`discovery.py:133`), `not data` raises `ValueError('Invalid Wayback JSON')`, marking the lookup `complete=False, reason='invalid_index_response'` instead of returning `([], None)` so `wayback_lookup` can finish with `complete=True, reason='complete'`.
    2. **Exact string check `row['original'] != original` rejects valid SURT-matched captures (`15 / 24` non-empty responses — 62.5% of hits, discarding `88` of `237` valid snapshot rows!)**: Wayback's `matchType=exact` matches by **SURT key (`urlkey`)**, so it returns captures whose `original` URL had port `:80`, `http://` instead of `https://`, `www.` vs non-`www.`, or `//` in the path.
       - Concrete examples from `b2_discovery` where valid HTTP 200 PDF captures were thrown away:
         - Query: `https://www.irs.gov/pub/irs-utl/20-Immigration%20and%20Taxation.pdf` $\rightarrow$ CDX returned `http://www.irs.gov:80/pub/irs-utl/20-Immigration%20and%20Taxation.pdf` (status 200, `application/pdf`) $\rightarrow$ **ABORTED!**
         - Query: `https://hcfa.house.gov/110/41994.pdf` $\rightarrow$ CDX returned `http://hcfa.house.gov/110/41994.pdf` (status 200, `application/pdf`) $\rightarrow$ **ABORTED!**
         - Query: `https://www.pgpf.org/sites/default/files/05092016_debt_limit_letter.pdf` $\rightarrow$ CDX returned `http://pgpf.org:80/sites/default/files/05092016_debt_limit_letter.pdf` (status 200, `application/pdf`) $\rightarrow$ **ABORTED!**
         - Also rejected: `nist.gov`, `piie.com`, `integration.samhsa.gov:80`, `crr.bc.edu:80`, `oregon-pip.org:80`, `archives113.transportation.house.gov//sites/...`, `help.senate.gov:80`, `aging.senate.gov:80`, `finance.senate.gov:80`, `foreign.senate.gov:80`, `judiciary.senate.gov:80`.
  - **Converged Fix for `discovery.py:129-215` (Preserving `validate_wayback_replay` Intact)**:
    - In `_wayback_page(body)`: return `([], None)` when `data == []`.
    - In `wayback_lookup`: validate a non-null `query_key = key(original)` against both `row['urlkey'] == query_key` and `key(row['original']) == query_key` (plus `_source_url(row['original'])`), preserve the requested campaign URL in `candidate['target_url'] = original`, set `candidate['original_url'] = row['original']`, and use `row['original']` in both `replay` and `ident`. Because `acquire_candidate` passes `candidate['original_url']` to `validate_wayback_replay`, `validate_wayback_replay` remains completely unchanged and passes on **237 / 237 (`100%`)** snapshot candidates.

---

### Stage 8: Public Release & UI Presentation (`archive_format.py`, `archive.ts`, `ArchiveDetail.tsx`)

#### 1. Where the Step Lives
- [archive_format.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_format.py#L61-L82): `_key_hash`, `_lookup_steps`
- [archive_format.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_format.py#L190-L211): `urls` table (`lookup_key = first 8 bytes of sha256('lookup:' || lookup_url)`)
- [document-addresses.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/document-addresses.sql#L1-L4), [document-source-input.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/document-source-input.sql#L1-L27), [document-recovery-input.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/document-recovery-input.sql#L1-L6)
- [archive.ts](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/reader/archive.ts#L25-L36): `lookupUrl(value: string)`
- [archive.ts](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/reader/archive.ts#L178-L199): `findUrl`, `findLink`
- [ArchiveDetail.tsx](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/archive/ArchiveDetail.tsx#L107-L120), [ArchiveRows.tsx](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/archive/ArchiveRows.tsx#L17-L19), [provenance.ts](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/browse/provenance.ts#L1-L9)

#### 2. Input & Output Columns
- **Inputs**: `document_addresses(document_id, url)` (union of `document_source_input.url`, `document_recovery_input.original_url`, `document_recovery_input.recovered_url`).
- **Outputs**:
  - `release/urls.parquet`: `(lookup_key FixedSizeBinary(8), list_row UINTEGER)` sorted by `lookup_key = substr(sha256('lookup:' || lookup_url), 1, 8)`.
  - `release/links.parquet` & `release/detail.parquet`: `link_key FixedSizeBinary(8)` (first 8 bytes of `body_hex` for saved bodies, or `substr(sha256('url:' || original_url), 1, 8)` for recoveries).
  - `release/sources.parquet` & `release/recoveries.parquet`: literal `url`, `original_url`, `recovered_url`.

#### 3. Exact Transformations Applied
- **Backend (`archive_format.py:61-82` `_key_hash` & `_lookup_steps`)** and **Frontend (`archive.ts:25-36` `lookupUrl`)** compute `lookup_url`:
  ```ts
  // apps/site/src/components/explorer/reader/archive.ts:25-36
  export function lookupUrl(value: string): string | null {
    try {
      const parsed = new URL(value)
      if (!/^https?:$/.test(parsed.protocol) || parsed.username || parsed.password) return null
    } catch {
      return null
    }
    const match = /^([a-zA-Z][a-zA-Z0-9+.-]*):\/\/([^/?#]*)([^?#]*)(\?[^#]*)?(?:#.*)?$/.exec(value)
    if (!match) return null
    const scheme = match[1].toLowerCase()
    const host = match[2].toLowerCase().replace(/^www\./, '')
    const authority =
      (scheme === 'http' && host.endsWith(':80')) || (scheme === 'https' && host.endsWith(':443'))
        ? host.replace(/:(80|443)$/, '')
        : host
    const path = (match[3] || '').replace(/\/$/, '')
    return `${authority}${path}${match[4] ?? ''}`
  }
  ```
- Computes the first 8 bytes of `sha256('lookup:' + lookup_url)` and performs binary search over `urls.parquet` (`findUrl` in `archive.ts:178-190`).

#### 4. Why It Does This
- Provides fast client-side 8-byte SHA-256 prefix binary search in the browser so users can paste a source URL and find the corresponding archived document without shipping `url-rules.json` or Rust UDFs to the browser.

#### 5. What It SHOULD Be (Gaps, Bugs & Corpus Counts)
- **Architectural Design Note (`DM8.2` Fixed Lookup Key vs. Alternate User Spellings)**:
  - `_lookup_steps` (`archive_format.py:65-82`, `# DM8.2's fixed lookup spelling; the query remains byte-for-byte intact`) and `lookupUrl` (`archive.ts:25-36`) implement the locked `DM8.2` release lookup key. All **605,848** published rows in `sources.parquet` match their own expected `DM8.2` lookup entry in `urls.parquet`.
  - Exact percent-encoding breakdown in `publish_v20/release/sources.parquet` (`605,848` rows):
    - **16,543** rows match `regexp_matches(url, '%[0-9]{2}')` (two numeric digits, such as `%20`).
    - **987** rows match `regexp_matches(url, '%([0-9A-Fa-f][A-F]|[A-F][0-9A-Fa-f])')` (either hex digit uppercase `A-F`; **826** match `%[0-9A-F][A-F]` where the second hex digit is uppercase `A-F`).
    - **0** rows match `regexp_matches(url, '%([0-9A-Fa-f][a-f]|[a-f][0-9A-Fa-f])')` (either hex digit lowercase `a-f`).
  - Where `findUrl` (`archive.ts:178-190`) does not match is **only on cross-spelling user pastes** where a user pastes an alternate spelling that differs from the published `sources.parquet` literal in ways `url_key` normalizes but `lookupUrl` does not (`472` raw-space URLs vs browser `%20`, `987` uppercase hex URLs vs lowercase user input, `4,270` `&download=1` vs `913` `?download=1`, `174` Congress.gov `?q=...`, `13` `utm_*`, `68` `web.archive.org`).

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
*(Representative of **3,231** `plan` `needs_acquisition` `&download=1` URLs, **1,792 / 1,804 (`99.33%`)** Wave 4–5 repaired-query recoveries, and **12** attempted House targets where `?download=1` routed to `/imo/media/doc/...` but failed qualification due to a `0`-byte origin file or size limit)*

| Stage | Behavior & Exact Column Values |
| :--- | :--- |
| **Stage 1 (Extraction & Resolution)** | A witness page links to the base URL `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony`. When that base URL was fetched (`source_id = 3746c1fd50afd3403269d7d86c854f020424bd0610181046e2f6115cae89cc86`, HTTP 200, `body_sha = ae5ee73d95a8fada1e9491574799cf263d03114d3f84d830ed26a9f6e1e0934c`), it was classified as `record_role = 'wrapper', is_real_file = false`. In `page_facts.parquet` and `readings_full_0cb`, `ae5ee73d...` has `link_count = 87, status = 'completed'`, including `href = '//democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1'` and 4 self-fragment links (`#main-nav`, `#skip-nav`, `#`, `#`). `model/sql/publisher-links.sql:4` associates links with already-captured sources (`INNER JOIN copy_url_keys`), so the 4 `#fragment` links match the wrapper's own `source_id = 3746c1fd...` (`4` rows in `publisher_links.parquet`), while the unfetched `&download=1` link is discovered by `resolved_link_targets` in `archive_url_state.py:70`. |
| **Stage 2 (Scheduler)** | Enters `url_state_queue` (`archive_url_state.py:77-85`, which excludes the 4 self-fragment links via `NOT EXISTS ... url_state_fetched_keys` at line 84 and admits the unfetched `&download=1` target). Queued with literal `requested_url = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1'`. |
| **Stage 3 (Fetch)** | Base URL `.../ashley-nunes-witness-testimony` was fetched (HTTP 200 HTML wrapper `ae5ee73d...`). The `&download=1` URL had `attempts = 0` in `publish_v20/release/url_state.parquet`. Across `capture_sources.parquet`, **100% (`4,062 / 4,062`) of historical HTTP 200 real-file captures with literal `&download=1` were on 4 Senate hosts (`*.senate.gov`), while `0 / 4,062` (`0%`) were on `*.house.gov`** (`19` HTTP attempts on `democrats-transportation.house.gov`, all returning HTTP `410`). |
| **Stage 4 (Lake & Universe)** | Base URL is in `capture_sources.parquet` with `outcome = 'stored', http_status = 200, record_role = 'wrapper', is_real_file = false`. Both the base URL and `&download=1` enter `raw_universe.parquet` and `targets.parquet`. |
| **Stage 5 (`url_key`)** | In `publish_v20` and `plan`, `url_key` was `democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1`. With `download-ampersand-query` (`url-rules.json:82-91`), `url_key` becomes `democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1` (distinct from the wrapper landing page's `url_key = democrats-science.house.gov/download/ashley-nunes-witness-testimony`). |
| **Stage 6 (URL State)** | In `release_v2/url_state.parquet` (v2 10-col schema):<br>- Base URL `.../ashley-nunes-witness-testimony`: `attempts = 1, last_status = 200, last_outcome = 'stored', capture_disposition = 'eligible', capture_reason = 'no_satisfying_recovery'`.<br>- `&download=1` URL: `attempts = 0, last_status = NULL, last_outcome = NULL, capture_disposition = 'eligible', capture_reason = 'no_satisfying_recovery'`. |
| **Stage 7 (Recovery)** | In Wave 4 (`receipts/documents/2026-10-31/track-b-wave4-20261031-a13ed292de0ec3429d9594f856c98e74fd59c9a4673dce91e0b0b1e4aa267669.jsonl.gz`), `ashley-nunes-witness-testimony&download=1` was requested via `candidate_url = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1'`. **The `?download=1` rewrite succeeded at HTTP routing**: the server redirected (`302`) to `https://democrats-science.house.gov/imo/media/doc/Ashley%20Nunes%20Witness%20Testimony.pdf` and returned `http_status = 200, outcome = 'stored'`. **However**, the PDF file hosted on the committee's origin server at that path is **`0 bytes` (`sha256 = e3b0c44...`, `sniffed_format = 'empty'`)** across all 3 rungs (`direct`, `zyte`, `firecrawl`), so `qualification_status = 'unresolved'`, it is absent from `selected_recoveries_v2_plus.parquet`, and it remains `needs_acquisition` in `plan_v2` (one of only `12` attempted House targets out of `1,804` that did not qualify, alongside `1,792` (`99.33%`) that became `accepted_recovery`!). |
| **Stage 8 (Release & UI)** | Absent from `publish_v20/release/sources.parquet` and `track_a/selected_recoveries_v2_plus.parquet` because the committee server's `/imo/media/doc/Ashley%20Nunes%20Witness%20Testimony.pdf` file is `0 bytes` (`release_v2/` contains capture control files and `url_state.parquet`, not `recoveries.parquet`). |
| **What Should Happen** | Generate `/download/<slug>?download=1` as the repaired fetch candidate for House `/download/<slug>&download=1` targets in `capture_scheduler.py` and campaign discovery while preserving `target_url` and existing `url_state` history. |

---

### Trace 3: `https://www.aging.senate.gov/404?notfound=/hearings/half-the-country-zero-hearings-meeting-the-moment-to-end-the-menopause-care-gap-in-america.xml`
*(Also `https://www.judiciary.senate.gov/404?notfound=download/01/06/2026/benton-sjq` and `https://www.finance.senate.gov/404?notfound=hearings%2F...` — **337** rows in `capture_sources.parquet`, **53** in `url-dispositions.parquet`)*

| Stage | Behavior & Exact Column Values |
| :--- | :--- |
| **Stage 1 (Extraction & Resolution)** | For `aging.senate.gov` and `judiciary.senate.gov`, 0 rows in `publisher_links` linked to `/404?notfound=...` directly. However, for `finance.senate.gov/404?notfound=hearings%2F...`, 4 captures returned `http_status = 200` on the `/404` page, and `archive_readings.py` extracted `<a href="#main-nav">`, producing **20 rows in `publisher_links.parquet`** with `target_url = 'https://www.finance.senate.gov/404?notfound=hearings%2F...#main-nav'`. |
| **Stage 2 & 3 (Scheduler & Fetch)** | When the original Senate hearing/download URL was fetched, ColdFusion responded with `302 Found` $\rightarrow$ `Location: /404?notfound=...`. In `assemble-20260930.jsonl.gz` (line 138314 for `aging.senate.gov`), the redirect target `https://www.aging.senate.gov/404?notfound=/hearings/...xml` was recorded as both `requested_url` and `url` with `http_status = 404, outcome = 'failed'`. |
| **Stage 4 (Lake & Universe)** | In `capture_sources.parquet` (**337 rows** with `/404?notfound=`), all are classified as `record_role = 'error_response'`. Because `model-url-inputs.sql:7-8` unnests `make_array(requested_url, url)` for all `mode = 'fetch'` captures regardless of `outcome = 'failed'` or `record_role = 'error_response'`, all `/404?notfound=` URLs enter `url_inputs`. |
| **Stage 5 (`url_key`)** | In `publish_v20` and `plan_v2` (built before `senate-notfound`), `url_key` was `aging.senate.gov/404?notfound=/hearings/half-the-country-zero-hearings-meeting-the-moment-to-end-the-menopause-care-gap-in-america.xml`. At commit `535375d1` (`url-rules.json:72-81`), `senate-notfound` unwraps `aging.senate.gov` and `judiciary.senate.gov`, **but fails on `finance.senate.gov/404?notfound=hearings%2F...#main-nav` for two reasons**: (1) `([^#]+)$` fails to match at all when `#main-nav` is present (since `wrapper` rules run before `#fragment` stripping in `url-normalized.sql`), and (2) `"decoder": "none"` leaves `%2F` un-decoded (`finance.senate.gov/hearings%2F...`)! |
| **Stage 6 (URL State)** | In `release_v2/url_state.parquet`, **53 `/404?notfound=` URLs** appear as standalone `requested_url` rows: **37** have `capture_disposition = 'eligible', capture_reason = 'no_satisfying_recovery'` and **16** have `capture_disposition = 'satisfied', capture_reason = 'qualified_recovery'`. |
| **Stage 7 (Recovery)** | In `plan/url-dispositions.parquet`, **52** `/404?notfound=` URLs were classified as **`needs_acquisition` (`needs_acquisition_purged_404_410`)** and **1** (`finance.senate.gov`) as **`usable_direct`** (in Waves 4–5, **32** `/404?notfound=` targets were recovered under `notfound_404_search_recovery`). |
| **Stage 8 (Release & UI)** | Excluded from `sources.parquet` (0 rows) because `record_role = 'error_response'`. |
| **What Should Happen** | 1. Exclude `record_role = 'error_response'` / `/404?notfound=` redirect targets from `model-url-inputs.sql` and `url-state.sql`.<br>2. Change `senate-notfound` in `url-rules.json:72-81` to `"decoder": "percent"` with pattern `(?i)^(https?://(?:[a-z0-9-]+\.)+senate\.gov)/404\?notfound=(?:%2f|/)?([^#]+)(?:#.*)?$`.<br>3. When recovering any historical `/404?notfound=` `requested_url`, query CDX / live origin using the unwrapped URL, not the `/404?notfound=` literal. |

---

### Trace 4: `https://web.archive.org/web/20010913024957id_/http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm`
*(And Wayback CDX `:80` captures like `http://www.irs.gov:80/pub/irs-utl/20-Immigration%20and%20Taxation.pdf` — **74** `:80` rows in `current_recoveries.parquet`, **6** `:80` rows in `url-dispositions.parquet`, **15** rejected CDX hits in `b2_discovery`)*

| Stage | Behavior & Exact Column Values |
| :--- | :--- |
| **Stage 1–4 (Ingestion & Universe)** | In `current_recoveries.parquet` (`id = 06768a003a24a46f592de7de7d4a595c6858a5be1dd99e1a036c2f4bd024fd10`), `original_url = 'https://waysandmeans.house.gov/event/h-r-586-the-fairness-for-foster-care-families-act-of-2001/fullcomm/107cong/fc-7act.htm'` and `recovered_url = 'https://web.archive.org/web/20010913024957id_/http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm'`. Also in `capture_sources.parquet`, 6 direct GPO fetches have `requested_url = 'http://www.gpo.gov:80/fdsys/pkg/CHRG-112hhrg.../pdf/...'`. |
| **Stage 5 (`url_key`)** | In `url-normalized.sql`, Pass 1 of `wrapper` rule `wayback` (`url-rules.json:4-11`) extracts `$1 = 'http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm'`. Next, `url_resolve($1, NULL)` (Rust `url::Url::parse`) strips default port `:80` (since scheme is `http`), producing `parsed = 'http://waysandmeans.house.gov/fullcomm/107cong/fc-7act.htm'` and `url_key = 'waysandmeans.house.gov/fullcomm/107cong/fc-7act.htm'`. |
| **Stage 6 (URL State & Provenance)** | `provenance-recovery-attachments.sql` joins on `original_url`'s `url_key` (`waysandmeans.house.gov/event/h-r-586-.../fullcomm/107cong/fc-7act.htm`), attaching the recovery to document `130775` (`list_row = 123613`). |
| **Stage 7 (Recovery & CDX Discovery)** | **Breaks in `discovery.py:178-184`!** While historical recoveries (`current_recoveries.parquet` has 22 `web.archive.org/...:80/` rows) were imported earlier, `corpus_recovery/discovery.py` (`wayback_lookup`) checks `if row['original'] != original: raise ValueError('CDX result outside query')`. When querying CDX for `https://www.irs.gov/pub/irs-utl/20-Immigration%20and%20Taxation.pdf`, Wayback returns `original = 'http://www.irs.gov:80/pub/irs-utl/20-Immigration%20and%20Taxation.pdf'`, causing `wayback_lookup` to throw `ValueError` and fail with `cdx_reason = 'invalid_index_response'`! Also, in `url-dispositions.parquet`, the 6 `http://www.gpo.gov:80/...` rows have `host = 'www.gpo.gov:80'` because `campaign.py` extracted `host` without stripping `:80`. |
| **Stage 8 (Release & UI)** | Published in `release/recoveries.parquet` (`list_row = 123613`) with `recovered_url = 'https://web.archive.org/web/20010913024957id_/http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm'`. In `archive_format.py:65-82` (`_lookup_steps`) and `archive.ts:25-36` (`lookupUrl`), `recovered_url` is hashed **without** unwrapping `web.archive.org`, so its `lookup_url` in `urls.parquet` is `web.archive.org/web/20010913024957id_/http://waysandmeans.house.gov:80/fullcomm/107cong/fc-7act.htm`. |

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

## Aggregated Empirical Findings Across Holistic Recovery Waves 1–6

Across Holistic Recovery Waves 1–6 (**`35,552` accepted recoveries in Waves 1–5 + `1,984` in Wave 6 = `37,536` total accepted recoveries**, reducing `needs_acquisition` from `41,111` baseline down to **`2,605`**, a **`-93.7%`** reduction), seven empirical URL parsing, normalization, candidate-generation, and qualification patterns accounted for the overwhelming majority of recoveries:

1. **Scheme Upgrade (`http://` $\rightarrow$ `https://`) & `.xml` $\leftrightarrow$ `.pdf` Representation Siblings (`17,447` in Wave 1 + `61` in Wave 6)**:
   - On `docs.house.gov/meetings/...` and `docs.house.gov/billsthisweek/...`, `http://` links failed `capture-scope.json`'s `^https://` regexes when `min(url)` picked `http://`, and `.xml` witness/bill files had already-captured `.pdf` siblings at the identical path stem (`s/\.xml$/.pdf/i`).
2. **Committee Subdomain & Majority/Minority Host Aliasing (`12,592` `v1_recovery_provenance` + `2,008` `stored_r2_exact_filename` + `1,093` Wave 6 `democrats-transportation.house.gov` witness-date matches + `31` `edlabor.house.gov` $\rightarrow$ `democrats-edworkforce.house.gov`)**:
   - Committees rename or split subdomains across Congresses while storing files in shared or parallel buckets:
     - `edlabor.house.gov/download/...&download=1` (`31` rows) $\rightarrow$ `democrats-edworkforce.house.gov/download/...?download=1` (HTTP 200 over `$0` Direct).
     - `democrats-transportation.house.gov/download/<mm>/<dd>/<yyyy>/<slug>&download=1` (`1,369` rows): `?download=1` redirects (`302`) to `//democrats-transportation.house.gov/imo/media/doc/<file>.pdf` which returns `403 Forbidden`, **but `1,093` of those witness testimonies are already captured in `capture_evidence.parquet` under the `PW` committee's `transportation.house.gov/uploadedfiles/...` and `docs.house.gov/meetings/PW/...` buckets**!
     - Drupal multisite authoring hosts (`edit-republicans.veterans.house.gov/sites/republicans.veterans.house.gov/files/...`, `222` rows; `archives-agriculture.house.gov/sites/republicans.agriculture.house.gov/files/...`, `31` rows) embed the canonical host directly inside `/sites/<canonical-host>/files/...`.
3. **Path Case-Sensitivity (`url-normalized.sql` preserves `c.path` case) vs. Case-Insensitive Committee File Servers (`174` in Wave 2 + `174` in Wave 6)**:
   - In Wave 6, **155 of 158** `https://democrats-naturalresources.house.gov/UploadedFiles/<file>.pdf` targets were already captured in `capture_evidence.parquet` under `https://naturalresources.house.gov/uploadedfiles/<file>.pdf` (lowercase `/uploadedfiles/` on the majority domain). Case-insensitive path matching in candidate discovery recovers these at `$0` without altering `url_key` case semantics globally.
4. **House `/download/<slug>&download=1` $\rightarrow$ `?download=1` (`1,792 / 1,804 = 99.33%` qualified) + Redirect-Location Filename Extraction (`25` recoveries)**:
   - Even when `/imo/media/doc/<Actual_Filename>.pdf` returns `403` or `404` on the origin host, capturing the `302` `Location` header from `/download/<slug>?download=1` reveals the true underlying filename and matches existing corpus documents (`redirect_location_corpus_match`).
5. **Deterministic Cross-Host Coordinate Rewriting (`www.congress.gov` Meeting Docs $\rightarrow$ `docs.house.gov/meetings/...`, `173` targets in Wave 6, plus `t2GPO`/`fdsys` $\rightarrow$ `govinfo.gov/content/pkg/...`)**:
   - `www.congress.gov/<cong>/meeting/house/<event_id>/.../HHRG-<cong>-<cmte><subcmte>-...-<YYYYMMDD>.pdf` encodes the exact `docs.house.gov` coordinates (`<cmte>`, `<cmte><subcmte>`, `<YYYYMMDD>`, `<event_id>`, `<filename>`), recovering authoritative PDFs over `$0` Direct HTTP.
6. **WordPress REST API Discovery Links (`/wp-json/wp/v2/...`, `578` in Waves 4–5 + `858` in Wave 6) vs. `/wp-json/oembed/1.0/embed` (`2,862` excluded)**:
   - `<link rel="alternate" type="application/json" href=".../wp-json/wp/v2/hearings/<id>">` tags on Senate committee pages yield structured JSON metadata whose `"link"` field points back to the already-captured HTML hearing page.
7. **Post-Fetch Qualification Bottlenecks Masquerading as URL/Acquisition Failures (`227` Poppler-verified owner-flagged PDFs + `3` DOCX + `3` `0`-byte origin files + `15` `>16 MB` PDFs)**:
   - Standard Adobe owner-permission flags (`encryption: yes (owner:...)`) caused `227` valid Wave 4 PDFs to be marked `qualification_status = 'unresolved'` until verified via `qpdf`/Poppler in Wave 5; `15` multi-hundred-page hearing volumes (`17 MB–157 MB`) hit `spool_limit = 16 MB` / `max_input_bytes = 16 MB` until raised to `256 MB` in Wave 6; and `3` origin files (including `ashley-nunes-witness-testimony`) are literally `0 bytes` on the committee server.

---

## Ranked Summary of Architectural Findings & Converged Fixes
*(See also the full convergence matrix and empirical verification in [docs/url-normalization-defense.md](file:///Users/mikewolfd/Work/congressional-tech/docs/url-normalization-defense.md).)*

1. **[P0 — Stage 7] Fix Wayback CDX Empty-List & SURT-Alias Handling in `discovery.py:129-215` While Preserving `validate_wayback_replay` Intact**:
   - In `_wayback_page(body)`: return `([], None)` when `data == []` so `wayback_lookup` retains prior pages' candidates/evidence/window and terminates cleanly with `complete=True, reason='complete'`.
   - In `wayback_lookup`: validate non-null `query_key = key(original)` against both `row['urlkey'] == query_key` and `key(row['original']) == query_key` (plus `_source_url(row['original'])`), preserve `candidate['target_url'] = original`, set `candidate['original_url'] = row['original']`, and use `row['original']` in both `replay` and `ident`. Leave `validate_wayback_replay` (`lines 117–126`) unchanged.

2. **[P0 — Stage 5] Fix `senate-notfound` (`%2F` + `#fragment`) and `download-ampersand-query` (`#fragment`) in `model/registries/url-rules.json:72-92`**:
   - Set `"decoder": "percent"` on `senate-notfound` with pattern `(?i)^(https?://(?:[a-z0-9-]+\.)+senate\.gov)/404\?notfound=(?:%2f|/)?([^#]+)(?:#.*)?$` so `%2F` is decoded and `#main-nav` (`20` rows in `publisher_links.parquet`) matches before `#fragment` stripping.
   - Add `(?:#.*)?$` to `download-ampersand-query`: `(?i)^(https?://(?:[a-z0-9-]+\.)*(?:house|senate)\.gov/download/[^?#]+?)(?:%20|\s)*&download=1(?:#.*)?$`.
   - Do **not** replace `/$` with `(?:%20|/)+$` in `model/sql/url-normalized.sql:48` (global trailing-space/multi-slash trim is withdrawn).

3. **[P0 — Stages 2 & 6] Generate Admissible Repaired Fetch Candidates While Preserving Existing `url_state` & Campaign Target Membership (`capture_scheduler.py` & `archive_url_state.py`)**:
   - Prefer admissible repaired candidates (`?download=1` and `https://`) while retaining the observed `requested_url` state history and `campaign_targets.target_url` membership across lone `&download=1` seeds, mixed spellings, existing `url_state_latest` rows (`capture_scheduler.py:392`), and campaign targets (`capture_scheduler.py:381`).

4. **[P1 — Stage 6] Preserve Literal `original_url` Custody Joins in `archive_url_state.py:129-166` While Resolving `url_key` Aliases in Candidate Discovery (`stored_url_key_alias`)**:
   - Keep literal `original_url` joins in `archive_url_state.py:129-166` so per-target `recovery_requirements`, `refresh_policy = 'historical_only'`, receipt custody, and unambiguous 1:1 checks remain enforced; resolve `url_key` aliases via explicit candidate decisions (`35` of `36` alias targets accepted in `plan_v2`).
