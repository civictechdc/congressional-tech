# Recovery reconciliation: local evidence and owner gates

The corrected local stage is `codex-coord/shared/raw-recoveries-owner-32c13ffa/`, manifest SHA-256 `4378dd96e3ab017be3a9ac56179a22dd253c66450154538ed325d6c8816faaaf`. It contains the unchanged 24,028 base decisions plus 57 explicit superseding owner decisions: 24,085 physical records and 24,028 active decisions. All 12,432 accepted-only imports are ready; none remains unresolved. Actual imports and provenance publication remain owner actions.

| Result | Count |
|---|---:|
| Accepted mappings / active decisions | 24,028 |
| Physical provenance records | 24,085 |
| New superseding owner records | 57 |
| Matched on exact original URL and body | 11,596 |
| Accepted-only mappings / ready imports | 12,432 |
| Unresolved imports | 0 |
| Receipt-only body rows retained | 2,580 |
| Differing recorded bases / recovered URLs | 643 / 328 |

The 57 owner records have `decided_by = owner`, `decided_at = 2026-10-27T21:28:14Z` (the communicated correction time), `kind = requested_content_in_official_hearing`, and `supersedes` naming each earlier automated decision. The existing latest-remaining-decision mechanism selects them. Their chosen kinds satisfy the established registry admission rule. The reconciliation code and category rule are restored to their earlier definitions; no override CLI or generalized source-category rule was added.

For the 24 missing source times, one native minimum over the retained 41-row `source-time-candidates` table establishes the time. Retained source metadata is reused only when its timestamp equals that minimum and its exact receipt locator appears among the minimum candidates. Native audit reports zero timestamp or locator mismatches, zero changes to fields unrelated to the chosen source and zero duplicate requests. All 12,351 previously ready rows remain equal in every field; no row outside these 81 changes.

The base provenance file remains byte-identical: SHA-256 `9736f83636cde639d0a5bf4c829da5c5f82f4b8ee984d5ab825511d73e99cc41`. The new 57-record file is `provenance/recoveries/20261027T212814+0000.jsonl`, 48,283 bytes, SHA-256 `e515d52e5a45a590f458dbbfce2dc7e80ad9a4e326dda80049ef8af522c3294b`. The stage manifest lists both files; staged model inputs must include both.

The audit pins the original owner text (`efdef1ff5ac8ffd852b6ae638c87b3703f7d528242395348741c0d1fe8466135`) and correction (`d5d9597ffb2a3a42b1c0eac5649802c7953e5b2f5e3ea2ad6d6c8bcd7390a309`). `owner-records.jsonl` and `owner-decision-ids.parquet` expose every new ID and its superseded ID; `source-time-minima.parquet` records all 24 selected times and source locators. Earlier immutable stages `raw-recoveries-4bcaa112` and `raw-recoveries-7a8c74a6` remain historical inputs, unselected for import. Neither was imported during this work.

Local preparation took 30.45 seconds with 394,575,872 bytes maximum resident memory on the shared Mac using `engine-3746f22`. It read retained metadata only, without rescanning receipts, bodies or the 102 MB source-facts file. Python serializes explicit records through the existing provenance writer; native SQL performs selection, joins, grouping and export. The bounded tables contain at most 24,085 decision records, with expected linear joins and `O(N log N)` ordering. The focused recovery, provenance and filename group passed 95 checks in 81.07 seconds. Both existing inspection commands validate the stage with `apply = false`: 24,085 records in two provenance objects and 12,432 import requests. Production/Linux and D1/E4 parity remain separate qualifications.

## Six excerpt decisions

The [decision list](excerpt-decisions.json) identifies the six already-staged two-page advisory extracts. Its source is `.cache/nara-filename-estimate-20261015/waysmeans-package-final/advisory-content-recovered.json`, SHA-256 `c02a4e41d51df74b6782ebcc4a05eaea2ae3f26aa0b23a9c69476e521a7375a0`.

| Ways and Means advisory original | Transcript event/date | Excerpt SHA-256 prefix |
|---|---|---|
| `?type=document&p=397895` | 102805 / 2015-01-13 | `c578bcecd3d11c96` |
| `?type=document&p=397940` | 102843 / 2015-01-27 | `a983c2aebe9a03b1` |
| `?type=document&p=397952` | 102922 / 2015-02-03 | `97c27cad272902c1` |
| `?type=document&p=398016` | 102947 / 2015-02-11 | `2306c6201e4211fc` |
| `?type=document&p=398172` | 103155 / 2015-03-17 | `8843d2be2d2bcf33` |
| `?p=398351` | 103372 / 2015-04-22 | `19611c198e727b2f` |

All six already have the “excerpt from the official hearing record” kind. Their records remain unchanged; no rejection records are authored.

## Exact owner commands

Select the corrected stage:

```sh
B7_STAGE="$COORD/shared/raw-recoveries-owner-32c13ffa"
```

To reproduce its one-time local data preparation, set `B7_NEXT_STAGE` to a fresh private directory and run from the pinned checkout. The retained audit script uses the existing native job and provenance writer; the registry pin is `f2e978f69bf1ac33699fa5a1cf7baa500aba14ac7f79d47d2414d02c70ed17f7`.

```sh
.venv/bin/python -I "$B7_STAGE/owner-decisions-audit/cxb_apply_owner_correction.py" "$B7_NEXT_STAGE"
```

Inspect both consumers before any live action:

```sh
.venv/bin/python -I -m corpus_recovery.reconcile import --stage "$B7_STAGE"
.venv/bin/python -I -m congress_api.cli.provenance --stage "$B7_STAGE"
```

From a clean approved application checkout, the owner may import the retained-body references. Every physical key gets a HEAD; missing objects fail before their receipts. No retained body is downloaded or uploaded:

```sh
.venv/bin/python -I -m corpus_recovery.reconcile import --stage "$B7_STAGE" --bucket congressional-tech-raw --apply
```

After final ingest/E4 parity, import both provenance files:

```sh
.venv/bin/python -I -m congress_api.cli.provenance --stage "$B7_STAGE" --bucket congressional-tech-raw --apply
```

No credentials, live-storage jobs, network writes, actual imports or body reads occurred in this run. Optional filename/sniff facts absent from the retained transition projection remain unknown.
