# Reproducing the URL normalization audit

Start with [the findings](report.md), [the predeclared experiment](experiment.md), and [the hashed input manifest](evidence/manifest.json).

The later `reconcile_latest.py` run freezes a separate Wave 6 generation and the documents being reconciled. Its [results](evidence/reconciliation-results.json) distinguish result rows, selected targets, dispositions, and distinct body hashes. Existing snapshots are reused on rerun; the original fifteen-question experiment remains pinned to its earlier generation. `wayback_row_units.py` separately reconciles the other agent's 237 CDX rows and 88 differing originals with this audit's 145 deduplicated candidates from rejected pages.

This directory contains an investigation harness, not production fixes. `common.py` points to the retained local artifacts; `scratch-path.txt` identifies this run's database, native jobs, downloaded bodies, and logs. The small `evidence/` files preserve the results for review without copying the full corpus. The accepted `hr-4824` PDF is an unchanged copy of its retained source, accompanied by a rendered first page.

## Execution

Run Python scripts with the repository's `.venv/bin/python`. The native jobs use the pinned runtime named in `common.py`, two native threads, and a 2 GB memory cap. DuckDB uses two threads and 1 GB. Run database-writing scripts sequentially.

1. `prepare.py` prepares a **new run** and copies mutable campaign inputs. Do not run it over this audit merely to inspect results: current campaign files may now represent a different generation. The frozen prior plans and selected/state files are named in `common.py`.
2. `normalize.py` runs current and proposed native normalization; `corpus.py` performs the population and relationship comparisons.
3. `bodies.py` rehashes the complete ampersand-repair bodies, checks their receipts, and extracts first-page text. It reads about 593 MB with two workers.
4. `scheduler.py` runs isolated planner scenarios. Empty-state seed cases are explicit counterfactuals using real addresses; existing-state cases use retained rows.
5. `wayback.py` replays retained index responses against the current and experimental parser. `wayback_guards.py` tests deliberately altered fields and bytes as negative controls. `proposed_discovery.py` preserves the exact experimental implementation used.
6. `discovery_links.py` reruns the real native link SQL on pinned wrapper-page readings. `malformed.py`, `followup.py`, and `remaining_checks.py` analyze raw literals, input-route filtering, and accepted aliases.
7. `lookup.mjs` imports the actual frontend reader. Run it with the repository Node/TypeScript runtime. Its input, `lookup-sources.jsonl`, is the fixed published `sources` table projected to `url,list_row`; results are joined to `urls.parquet` on the actual frontend key. Six representative journeys use the local release server, which validates the release manifest.
8. `live_trim.py` makes **fresh network requests**: 27 paired literal/trimmed URLs, two concurrent requests, a 20-second total limit per request, and a 64 KiB response-prefix limit. `live_pdf_checks.py` then downloads the five successful PDFs completely, capped at 25 MiB per body. These results describe present availability, not historical availability.
9. `publication_summaries.py` joins aliases, changed link associations, lookup results, and the mismatched bill to published document rows. `export_evidence.py` copies bounded summaries and hashes the inputs. It omits long extracted page text and large response bodies from the review files.

The native link replay initially exceeded its memory cap when it expanded the full readings table before filtering. The completed run filters the pinned input to the relevant page hashes first. The shortened native job removes the original full-job `release_after` scheduling hints and uses unique export ordering. These were harness corrections; no production engine changes were made.

## Additional saved comparisons

`alias-membership-results.json` joins selected aliases to published source memberships by the SHA-256 embedded in `body_key`; 33 bind to one document each, two to none. `publication-link-impact.json` joins affected native keys to publisher links and current source memberships; its 58 affected associations have no published target-document membership. `lookup-different-documents.json` records alternate lookups that omit the expected document while returning other rows. Each result is derived from the pinned files in `manifest.json`; the corresponding SQL is retained in `publication_summaries.py`.
