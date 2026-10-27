# Recovery reconciliation: local evidence and owner gates

The owner decisions are applied locally. The selected immutable stage is `codex-coord/shared/raw-recoveries-7a8c74a6/`, with manifest SHA-256 `79feffc769a14bb7257ab2464ecc04eaeb0e308e1f29a1e482fb12058dc04c16`. It preserves all 24,028 accepted mappings and stages every one of the 12,432 accepted-only imports as ready; none remains unresolved. Imports and provenance publication remain owner actions after the required parity checks.

| Reconciliation result | Count |
|---|---:|
| Accepted decisions | 24,028 |
| Matched on exact original URL and body | 11,596 |
| Accepted-only mappings needing receipt imports | 12,432 |
| Ready imports | 12,432 |
| Unresolved imports | 0 |
| Receipt-only body rows retained in the report | 2,580 |
| Accepted mappings with differing recorded bases | 643 |
| Accepted mappings with differing recovered URLs | 328 |

The native audit resolves exactly the previous 81 gaps: 57 imports take the source's recorded `requested_content_in_official_hearing` category, and 24 take the earliest valid fetch of the same body when the exact recovered URL has no valid source time. All 24 selected times and receipt locators match that minimum. The 57 corresponding decisions change from recovered-copy to excerpt kind. Existing exact-source evidence keeps priority. Invalid or date-only timestamps cannot supply a time; unknown categories still refuse staging. Recorded source category, recovery receipt category and the match basis's explicit `import_category` are distinct inputs to one registry-backed choice; a display fallback cannot invent an import category.

The stage reuses `codex-coord/shared/raw-recovery-facts-0a55702e/capture-facts.parquet`: 2,866,984 body-bearing facts, 101,953,318 bytes, SHA-256 `107cbfc394d81255bfaeb365fe1dc2b0da12b0346e3c6793e6ffba119ad15cb7`. The accepted backup is 9,638,187 bytes, SHA-256 `00922c1eb29d84cdf68b1d17fb00e050f443942f13b3d35e775192ff42b73864`. The registry is 2,551 bytes, SHA-256 `f2e978f69bf1ac33699fa5a1cf7baa500aba14ac7f79d47d2414d02c70ed17f7`. No receipts or body bytes were rescanned. Optional filename/sniff facts absent from the retained transition projection remain unknown; this stage does not establish D1/E4 semantic parity.

Local restaging took 38.95 seconds with 1,166,000,128 bytes maximum resident memory on the shared Mac, using the qualified `engine-1c2473b` snapshot. This measures reuse of retained facts, not a production-runner or full receipt-reader qualification. Native SQL performs joins, ordering and export; Python validates source metadata and serializes decisions. Expected work is linear hash joins plus candidate ordering, `O(C + A + S log S)`, with one materialized selected-source relation reused by decision and import reports. The focused project runner passed all 23 recovery import tests. Contract fixtures reproduced three failures before the change, including category precedence and missing alias times; valid exact-source priority already passed.

## Six excerpt decisions

The [decision list](excerpt-decisions.json) identifies the six qualified two-page advisory extracts. Its source is `.cache/nara-filename-estimate-20261015/waysmeans-package-final/advisory-content-recovered.json`, SHA-256 `c02a4e41d51df74b6782ebcc4a05eaea2ae3f26aa0b23a9c69476e521a7375a0`.

| Ways and Means advisory original | Transcript event/date | Excerpt SHA-256 prefix |
|---|---|---|
| `?type=document&p=397895` | 102805 / 2015-01-13 | `c578bcecd3d11c96` |
| `?type=document&p=397940` | 102843 / 2015-01-27 | `a983c2aebe9a03b1` |
| `?type=document&p=397952` | 102922 / 2015-02-03 | `97c27cad272902c1` |
| `?type=document&p=398016` | 102947 / 2015-02-11 | `2306c6201e4211fc` |
| `?type=document&p=398172` | 103155 / 2015-03-17 | `8843d2be2d2bcf33` |
| `?p=398351` | 103372 / 2015-04-22 | `19611c198e727b2f` |

The owner retains all six as “excerpt from the official hearing record” (`requested_content_in_official_hearing`). Each original is the advisory link; the recovered URL names the full transcript while the stored body is the two-page extract. The native audit finds all six with the excerpt kind and no rejection records. Generic recorded-category precedence preserves them; no per-URL exception changes the mapping.

## Exact owner commands

Set `COORD` to the coordination folder and select the immutable stage:

```sh
B7_STAGE="$COORD/shared/raw-recoveries-7a8c74a6"
```

To reproduce local staging in a fresh private directory, set `B7_NEXT_STAGE` and use the retained facts and pinned runtime:

```sh
.venv/bin/python -I -m corpus_recovery.reconcile stage --accepted /Users/mikewolfd/Work/congressional-tech/output/provenance-backup-20261024/accepted-00922c1eb29d84cdf68b1d17fb00e050f443942f13b3d35e775192ff42b73864.json --captures "$COORD/shared/raw-recovery-facts-0a55702e/capture-facts.parquet" --kind-registry model/registries/recovery-kinds.json --stage "$B7_NEXT_STAGE" --decided-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --native-config "$COORD/shared/engine-1c2473b/runtime.json"
```

From a clean application checkout with the approved raw writer identity, inspect the complete import set, then apply only after authorization. Every referenced physical key gets a HEAD; missing objects fail before their receipts. No retained body is downloaded or uploaded:

```sh
.venv/bin/python -I -m corpus_recovery.reconcile import --stage "$B7_STAGE"
.venv/bin/python -I -m corpus_recovery.reconcile import --stage "$B7_STAGE" --bucket congressional-tech-raw --apply
```

After final ingest/E4 parity, import the staged decisions:

```sh
.venv/bin/python -I -m congress_api.cli.provenance --stage "$B7_STAGE" --bucket congressional-tech-raw --apply
```

The immutable `owner-decisions-audit/` folder pins the earlier stage, owner decisions, runtime and native reports, including all 81 resolved requests. No credentials, live-storage jobs, network writes, actual imports or PDF/body reads occurred in this run.
