# Shipped dependency triage and PDF cancellation candidate

The MCP app's existing `pypdf==6.21.4` update remains the accepted dependency repair. This candidate adds a hard execution boundary for saved-PDF decoding. It does not alter the active release or the archive's producer pins.

## Runtime behavior and verification

Verified saved bytes enter the existing PDF parser in a short-lived process group. An independent group leader monitors the owner's identity and deadline; it stops the decoder family even if the owner receives SIGKILL or the parser holds Python's interpreter lock. A request cancellation stops that group, including a Poppler fallback, and waits for cleanup. Document reads, citation resolution, and PDF-shaped caption bodies use the same boundary. An offline extractor instead reuses its existing supervised worker group so parsing remains inside that worker's combined memory accounting and cleanup. Fetching, digest checks, cache publication, page numbering, citations and response slicing keep their existing code. Cache writes occur outside the killed process, so interruption cannot strand its temporary cache files.

Final focused checks passed: **43 passed, 1 skipped, 6 deselected** across four of 19 MCP test files. This is a partial lane result. The skip requires the retained native phase2 fixture. Cases include stalled `PdfReader` construction, stalled page extraction, a real stalled Poppler child, scope cancellation, raw task cancellation, repeated cancellation, cancellation while queued, all three online consumers, and a subsequent benign two-page read with cache reuse. New lifecycle controls kill only the online owner while the actual parser or Poppler holds the interpreter lock, check group shutdown, refuse startup after owner loss, and assert that PDF-shaped caption parsing stays in the offline worker's group until its outer timeout. Existing integrity, decompression, response-limit, cue/citation and selected retained-text checks also passed.

`uv sync --frozen --project apps/explorer_mcp` installed this checkout's app environment. `uv build` produced an isolated candidate wheel whose decoder module bytes match source. This is packaging evidence, not a fresh installed-wheel or image acceptance claim. The prior installed-wheel and Linux arm64 saved-PDF checks remain credited to their original candidate.

No root producer parser changed. The existing text-index definition hashes the whole caption-reader file, so the initial execution-control change moves its `caption` and `playlist` definitions. Document PDF/text/HTML/XML definitions remain unchanged in the bounded comparison. The review follow-up changes no additional per-body definitions; it changes execution-source facts. Before reusing caption readings in a newly prepared release, the integration owner must record equivalence or accept the definition transition. No index or corpus rebuild ran here.

## Advisory scope and result

The November 6 GitHub Dependabot API snapshot contains 162 open alerts: 75 high, seven critical, 63 medium and 17 low. All **82 high/critical alert records** received an individual disposition. These are remote-branch alert identities; local main already contains newer app pins. Separately, `pip-audit 2.10.1` checked all 66 Python dependencies selected from the app's frozen runtime export, with **no known vulnerabilities and no skipped packages**. This does not audit the container operating system or dependencies excluded by local platform markers.

| Disposition | Alert records | Practical meaning |
| --- | ---: | --- |
| Already fixed in local app pins | 20 | Ten pypdf advisories appear against both the requirement and lock; 6.21.4 covers their declared fixes. Deployment remains separate. |
| Reachable producer paths; root update pending | 11 | Eight PDF parsing findings, compromised certificate trust, an APNG allocation path, and oversized HTTP chunk-size lines. |
| Specific maintained API not observed | 35 | An affected pin alone does not establish exposure; examples include Pillow encoders, pypdf dictionary cloning, and aiohttp server handlers. |
| Exposure precondition remains unqualified | 9 | Google certificate/client internals and several urllib3 proxy/decompression flows require further evidence. These are not dismissed. |
| Site build tool or unreached API | 7 | Static Pages has no Astro server. No untrusted image-optimizer, dynamic slot-name or browser Zod-validation consumer was found. No Astro migration is warranted by this evidence. |

The maintained producer paths support these root-lock priorities:

| Package | Local root pin | Smallest identified security target | Actual consumer / advisory |
| --- | --- | --- | --- |
| certifi | 2025.11.12 | >=2026.10.19 | Requests/HTTP client CA trust; [compromised emSign intermediates](https://github.com/advisories/GHSA-6q48-6c7w-9gw2). App already uses 2026.10.23. |
| pypdf | 6.19.0 | 6.21.4 | `witness_pdf` and recovery qualification parse saved PDFs; [xref EOF loop](https://github.com/advisories/GHSA-5849-834g-hvw5), [page-tree memory use](https://github.com/advisories/GHSA-cggf-277g-3q54), and six related parsing findings. |
| urllib3 | 2.6.2 | 2.8.0 | Raw requests streaming reads chunk-size lines before application byte limits; [unbounded chunk-size line](https://github.com/advisories/GHSA-vxq7-64xx-v4gw). |
| Pillow | 12.3.0 | 13.0.0 | `image_tools._read` allows PNG; [APNG allocation](https://github.com/advisories/GHSA-5xm2-6676-qcp9) occurs during open before frame checks. Existing child limits mitigate resource use but do not patch the library. |

The DDK worktree owns active root `pyproject.toml`/`uv.lock` edits; its inspected pins still had these versions. This candidate does not independently rewrite that lock. The owner must resolve compatible updates, run actual producer checks, and coordinate reading-version evidence with `ct-deh9`; an app-only patch does not establish producer compatibility. Remaining advisory-declared targets include pyasn1 0.6.5, aiohttp 3.14.4, filelock 4.2.1, httplib2 0.32.0, lxml 6.1.0 and protobuf 6.33.5 if their unresolved routes are admitted or the shared refresh includes them.

## Durable evidence and remaining acceptance

Evidence lives under `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/implementation/reviewed-non-news-20261106/ct-680z/`: `ADVISORY-DISPOSITIONS.md` lists every high/critical record and its advisory link; `evidence/high-critical-triage.json` supplies machine-readable dispositions; `evidence/dependabot-open.json` retains the authoritative snapshot; `evidence/app-runtime-audit.json` and the frozen requirements retain the separate runtime audit. Focused logs, source hashes, reading-definition comparison and the isolated wheel are retained there too.

The independent four-skill review identified the offline nested-group regression and the online owner-death gap before final acceptance. Both were repaired in a new commit, preserving the original commits and evidence. Review follow-up logs, rebuilt candidate, source receipt and verdict live under `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-680z/`. The group-leader code adapts the existing `scripts/measure/process_rss.py` lifetime pattern without importing repository-only machinery into the shipped wheel.

`ct-680z` stays open. Root dependency fixes, unresolved transitive exposure, final Linux amd64 image checks, and deployed/installed-client acceptance remain outstanding. This patch is a separate app candidate: the release owner decides its integration and version. It must not silently replace already-prepared 0.6.2 assets. No merge, push, publication, deployment, shared catalog write or data cleanup occurred.
