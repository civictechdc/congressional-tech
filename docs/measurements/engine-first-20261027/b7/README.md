# Recovery reconciliation: local evidence and owner gates

The importer and reconciliation are built. The first full local run preserved all 24,028 accepted mappings but refused provenance publication: seven mappings use five categories outside its explicit documented staging registry. No raw object was written. Engine's recovery-kind registry must supply those mappings; no unknown category was silently treated as a recovered document.

The run reused the immutable native receipt counter, SHA-256 `88fa504b16b5deb6f881d2d5b7d9e2525a3e23a2be0ffccfab048fd674783691`: 2,596,054 receipt lines. The canonical accepted backup is 9,638,187 bytes, SHA-256 `00922c1eb29d84cdf68b1d17fb00e050f443942f13b3d35e775192ff42b73864`. Python serialized source metadata; native SQL performed projection, joins, selection and export.

| Transition projection result | Count |
|---|---:|
| Accepted mappings | 24,028 |
| Matched on exact original URL and body | 11,596 |
| Accepted-only mappings needing receipt imports | 12,432 |
| Receipt-only body rows retained in the report | 2,580 |
| Accepted mappings with differing recorded bases | 643 |
| Accepted mappings with differing recovered URLs | 328 |
| Import requests with a source timestamp in this initial projection | 11,695 |
| Requests without one | 737 |

These are transition-input results, not D1 semantic parity. Receipt-only rows retain their receipt positions; their count is not the older count of distinct mappings. The implementation now also refuses malformed/date-only source times, requires original size and suffix, and preserves known filename/sniff facts. The earlier measured projection lacks those optional columns, which remain unknown when that artifact is reused.

The full projection and initial reconciliation took 803.55 seconds with 6,253,903,872 bytes maximum resident memory on this shared Mac. This does not qualify the production runner. The 2,866,984 body-bearing source facts are retained once under `codex-coord/shared/raw-recovery-facts-0a55702e/`: 101,953,318 bytes, SHA-256 `107cbfc394d81255bfaeb365fe1dc2b0da12b0346e3c6793e6ffba119ad15cb7`. Reuse that file; do not rescan receipts. The future accepted-body selection is fixture-tested only.

The five unlisted categories are `requested_content_in_official_amendment_packet` (two mappings), `same_article_publisher_text_available` (one), `official_public_statement_counterpart` (one), `official_report_counterpart_available` (two), and `related_final_report_available` (one). Exact rejected rows and native reports remain in raw scratch under `b7b8-impl/recoveries-24028/`; no success manifest or provenance file was produced.

A display kind is distinct from the category recorded on an import receipt. Basis-registry rows can name an explicit `import_category`; it must resolve to a category row with the same display kind. A recorded source category takes precedence. Without a registered choice, the import request remains unresolved even when its display kind is known. The initial source-time counts above do not establish current import readiness.

## Six excerpt decisions

The [native decision list](excerpt-decisions.json) joins the accepted backup to the six qualified two-page advisory extracts. Its exact source is `.cache/nara-filename-estimate-20261015/waysmeans-package-final/advisory-content-recovered.json`, SHA-256 `c02a4e41d51df74b6782ebcc4a05eaea2ae3f26aa0b23a9c69476e521a7375a0`.

| Ways and Means advisory original | Transcript event/date | Excerpt SHA-256 prefix |
|---|---|---|
| `?type=document&p=397895` | 102805 / 2015-01-13 | `c578bcecd3d11c96` |
| `?type=document&p=397940` | 102843 / 2015-01-27 | `a983c2aebe9a03b1` |
| `?type=document&p=397952` | 102922 / 2015-02-03 | `97c27cad272902c1` |
| `?type=document&p=398016` | 102947 / 2015-02-11 | `2306c6201e4211fc` |
| `?type=document&p=398172` | 103155 / 2015-03-17 | `8843d2be2d2bcf33` |
| `?p=398351` | 103372 / 2015-04-22 | `19611c198e727b2f` |

Verified distinction: each accepted `original_url` is the advisory link; `recovered_url` names the full transcript while the stored body is the two-page extract. Source notes say transcript pages 6–7 reproduce the advisory. The owner decides whether that recovery is appropriate for each original link. Every confirmed wrong recovery gets a new `kind: rejected` record superseding its staged decision; nothing is automatically rejected or rewritten.

## Exact owner commands

Set `B7_STAGE` to a fresh private directory, `RECOVERY_KIND_REGISTRY` to engine's explicit registry, and `DOCSPEC_JOB_CONFIG` to the approved local native runtime. `COORD` is the coordination folder. Stage with the retained source facts:

```sh
.venv/bin/python -I -m corpus_recovery.reconcile stage --accepted /Users/mikewolfd/Work/congressional-tech/output/provenance-backup-20261024/accepted-00922c1eb29d84cdf68b1d17fb00e050f443942f13b3d35e775192ff42b73864.json --captures "$COORD/shared/raw-recovery-facts-0a55702e/capture-facts.parquet" --kind-registry "$RECOVERY_KIND_REGISTRY" --stage "$B7_STAGE" --decided-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --native-config "$DOCSPEC_JOB_CONFIG"
```

Inspect unresolved requests. From a clean application checkout, the owner may explicitly import the ready subset. Every referenced physical key gets a HEAD; no PDF/body bytes are downloaded or uploaded. Missing objects fail before their receipts:

```sh
.venv/bin/python -I -m corpus_recovery.reconcile import --stage "$B7_STAGE" --ready-only
.venv/bin/python -I -m corpus_recovery.reconcile import --stage "$B7_STAGE" --ready-only --bucket congressional-tech-raw --apply
```

After final ingest/E4 parity, import the staged decisions:

```sh
.venv/bin/python -I -m congress_api.cli.provenance --stage "$B7_STAGE" --bucket congressional-tech-raw --apply
```

For owner-confirmed rejections, write explicit decision records to `OWNER_REJECTIONS`, retaining exact original URL/body and naming the earlier decision ID in `supersedes`. Stage and inspect that new batch before applying:

```sh
.venv/bin/python -I -m congress_api.cli.provenance --records "$OWNER_REJECTIONS" --kind recoveries --decided-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --stage "$B7_REJECTIONS"
.venv/bin/python -I -m congress_api.cli.provenance --stage "$B7_REJECTIONS" --bucket congressional-tech-raw --apply
```

Focused recovery/review/fetch/receipt/import-fence checks: 82 passed after the category-separation correction. One earlier doctor import timed out under contention; no preflight was bypassed. No credentials, live-storage jobs, network writes or PDF body reads occurred.
