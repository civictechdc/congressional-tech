# Read-once audit

Metadata-only measurement, 2026-10-28. No real body, receipt or bucket was read by
this audit. Native engine `48636e5` grouped the five needed columns (`sha256`,
`bytes`, `stored_bytes`, `media_type`, `fidelity`) of the owner-selected local
`captures-0.parquet`: 3,909,134 capture rows, 1,036,256 bodies, no missing sizes,
no contradictory body sizes, and nine bodies with conflicting media types.
The input file is 312,412,102 bytes; this is its file size, not measured projected
I/O. Derived facts were exported natively, SHA-256
`fb871cb83209cfa857d2d0ad59fbe55826ada8a04b92015db390a1980af5b1e9`.

## D2 counts and change

| Needed action | Bodies | Stored bytes | Evidence |
|---|---:|---:|---|
| No body read: caption | 362,208 | 211,339,202 | Consistent VTT media type and an explicit `saved-text` writer observation |
| No body read: playlist | 953 | 1,403,757 | Consistent HLS media type and `saved-text` |
| No body read: empty | 1 | 20 | Zero entity bytes |
| Full HTML read | 175,196 | 4,158,585,290 | Unique HTML/XHTML routing hint |
| Full XML read | 112,361 | 820,732,300 | Unique XML routing hint |
| Full JSON read | 666 | 551,131 | Unique JSON routing hint |
| Prefix needed | 384,871 | 691,165,270,680 | No decisive writer fact, or missing/conflicting media type |

MIME alone is a routing hint, not proof of PDF bytes or integrity. The maintained
`response_kind` explicitly returns `unverified_pdf` for a header-only PDF claim.
A page hint must still yield the format its bytes establish. An unknown prefix
that reveals a page continues through the same open source; it must not trigger
a second body fetch. Existing pinned byte facts take priority over hints.

The old two-pass baseline requires 1,036,256 prefix opens plus 288,223 page opens.
The proposed base path requires 673,094 opens: 288,223 full-page objects and
384,871 unresolved objects. This removes 651,385 opens. Its byte floor changes
from 9,708,279,139 to 8,024,872,623 bytes, using `min(stored_bytes,8192)` for a
prefix and the recorded stored size for a full page. The eliminated repeated
page prefixes alone total 1,470,663,553 bytes.

These are projected base-path counts, not measured R2 requests. Additional ZIP
inspection and bare-PDF tail/reader bytes depend on the qualified inventory and
are **not measured** here. Eight supervised worker cases verify one actual
source open, exact byte accounting, gzip, XML/JSON, and retry reuse. The unified
native producer is unfinished; no real D2 run or end-to-end release is qualified.
The count investigation stopped at its bounded checkpoint; producer integration
continues after the assigned review repairs.

## Other passes

| Consumer | Raw objects and fields needed | Count/bytes and repeat audit |
|---|---|---|
| B9 verification | One listing; body references, size, ETag/MD5 and existing verification; whole bytes only for its sampled hashes | First live baseline owner-gated. One LIST and 25 whole-body GETs; bytes are the selected objects' stored-size sum, unavailable until that listing. Reuse D1 facts rather than re-extract already ingested receipt fields. |
| D1 narrow index | Receipt pointer, run/mode/outcome/family, URLs/status/complete/time, body identity/storage facts, recovery mapping and one flat download header | Older baseline: 2,289 receipts, 2,596,054 lines, approximately 1.08 GB compressed. One semantic scan. A qualified counter is 1,663,186,512 bytes. Reuse its creation pin; a separate integrity hash is distinct qualification work, not another mapping pass. No prior/header-array/supplement expansion. |
| D3 filenames | Effective name/address pairs and recovery originals; vocabularies | Zero raw body/receipt reads. Parse each distinct pair once; old estimate 1,392,681 pairs. Shared input SQL and supervisor version repairs are in progress. |
| E2 | Pinned captures, readings, filename readings, provenance and registries | Zero body reads. Project required lake fields and materialize shared joins. Metadata admissions must be profile-pinned; no raw re-probing per source or URL. |
| Edition count | Four canonical model relations and their pins | Zero raw reads. Fingerprints come from existing readings/member facts. Missing fingerprints remain unknown; no speculative PDF pass. |
| E4 | Pinned oracle, candidate release, private document/source rows and cause relations | Zero raw reads. Compare native relations; no receipt/body fallback or unordered physical-row inference. Actual comparison input sizes await the first E2 candidate. |
| Capture | One acquired response stream, its hash/size, durable body and byte-derived sniff/archive facts | Future live runs owner-gated; request/byte totals depend on discovery. Acquired bytes must be durable before fallible inspection. Raw owns the review repair; no live validation claimed. |

Remaining risks are the unfinished producer integration, unmeasured ZIP/PDF extra
reads, and the pending B9/ingest/capture review repairs. None is a passed live
storage check. Evidence: `cx_read_once_counts`, `cx_read_once_detail`,
`cx_read_once_final_counts`, and `cx_readings_once_worker.log` in engine scratch.
