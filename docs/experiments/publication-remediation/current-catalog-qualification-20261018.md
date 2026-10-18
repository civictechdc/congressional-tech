# Complete local preparation passed

The frozen publisher at `2feb8c75c69f5fc6a5c33ae6ad25197722590f3f` prepared the complete retained current catalog in one successful local run. Whole watchdog wall time was **3,155.71 seconds (52 minutes 36 seconds)**. Publisher stage time was 3,152.78 seconds; worker time, including setup and final integrity checks, was 3,155.44 seconds. Both sampled process-tree peak and publisher highwater RSS were **7,310,491,648 bytes (6.81 GiB)**, below the chosen 7 GiB local ceiling. No retry occurred.

This qualifies complete local static preparation on macOS arm64, Python 3.12.13 and PyArrow 25.0.1. It does not qualify hosted Linux execution, R2 upload, deployed readback, or ordinary unchanged-job duration/downloads. Browser usability requires its own receipt. `ct-hnxb` remains in progress until hosted/live verification; `ct-x7vx` retains the deployed no-op observation.

## Exact inputs and outputs

Catalog `469ef1ebf6864739a2c8a4c096defcc0`, generation `596f08fa2dbf4875bb8da7dc94e33847`, contains 1,241,157 document rows and 1,683,430 filename rows. Full input hashes matched before and after the run. The original retained documents, immutable selector and frozen runtime source files remained unchanged.

- Documents: 541,147,000 bytes, SHA-256 `f0bf8fb6fcf4f1067d2182372661917ed23741e47943d575f96d2fc4d44552b7`. The output preserves the complete source archive bytes; it does not decode or repack this download-only file.
- Filenames: input 546,848,353 bytes, SHA-256 `2af2dbdb100fd0d9e96ae5af76ee22406a783944bdae0166869c44bb663fa174`. Repacking verified the complete Arrow schema metadata and every ordered value. Output is 409,292,782 bytes in 249 row groups, SHA-256 `b7069c964507407b5171fd04e0e1b4bc5dac37b8e2b878ae34ea85dceac6ff4b`.
- Observations: 7,246,240 observations serialized and 7,246,240 full source verification lookups, with 4,307,909 deduplicated entries. Every reconstructed value passed; the verifier decoded 4,741 parts.
- Details: all 1,683,430 typed/derived records passed the complete framed-value check. Browse contains 1,241,157 entries.
- Reviews: 86 bound and 0 withdrawn, with review SHA-256 `fc5d361e4f2c01db8e8be90267f18cf072cc6db02bc1cd57ef5621b8aac1354c`. Binding output SHA-256 is `f70fbd4b64eded6cf143fca33fdf15663a271262388263ba1b65cc7e99f6551e`.
- The actual publisher returned `PreparedManifest`. All 270 output files, including 256 ID shards and the manifest, passed independent full size/SHA checks against their issued proofs. The complete output is 1,290,775,040 bytes. Manifest SHA-256 is `cdcd21dff8b5983abca4c041aa293c0aa2f07bb168e759b16c81a96db7a01764`.

The closed filename trailer declares a 13,073,006-byte footer, below the reader's default 32 MiB range-entry cache limit. The prior failed trial produced 2,673 groups and a 135,166,663-byte footer. This is a measured layout correction; footer size alone does not establish browser usability.

## Complete measured time

| Stage | Seconds |
| --- | ---: |
| Input verification | 1.02 |
| Catalog loading | 8.02 |
| Complete document archive copy | 0.43 |
| Filenames, including complete equality | 206.18 |
| Observations, including complete dictionary/source readback | 2,492.45 |
| Details, including complete typed/derived value verification | 437.80 |
| Navigation | 3.54 |
| Review binding | 0.004 |
| Browse | 2.72 |
| IDs | 0.61 |
| Manifest | 0.004 |

Filename writing took 111.18 seconds and its complete equality pass took 94.81 seconds. Observations and details expose combined write/readback stages; the current instrumentation does not provide an exact split. This is one complete candidate run without a baseline duration arm, so it supports no overall speed or cost savings claim.

## Limits and size tradeoffs

The run used the frozen defaults without overrides: 128 native rows, 4 MiB decoded Arrow batch target, 16 MiB actual Arrow row limit, 32 MiB Python batch estimate, 128 MiB Python row estimate, 32 MiB logical JSON value limit, and 8 MiB SQLite cache. The reviewed writer has a separate 64 MiB pending-buffer budget; its measured maximum was 66,994,998 bytes. Native buffers are distinct: the maximum returned native batch was 499,123,058 Arrow bytes with 499,123,438 buffer bytes. Admission accounting is not total decoder allocation or RSS.

The local watchdog retained its 7 GiB RSS ceiling, 180 minute deadline and 8 GiB disk-free floor. Minimum observed host disk free was 35,305,832,448 bytes. These are local qualification settings; production allocation is unchanged and unspecified by the workflow. Catalog loading had already reached 5,085,020,160 bytes highwater before filename writing, so the total process peak is not attributed to the writer's 64 MiB pending budget.

Comparison with the saved previously verified live manifest is intentionally limited to declared payload identities and sizes. All eleven declared files other than documents and filenames have identical SHA-256 values and sizes, including all observation files, details, review binding and browse. The two changed files are larger than the selected release:

| File | Saved live bytes | Candidate bytes |
| --- | ---: | ---: |
| Documents | 380,338,200 | 541,147,000 |
| Filenames | 359,714,851 | 409,292,782 |

The archive copy avoids decoding an unsupported giant source row and preserves its original digest. These two files together add 210,386,731 bytes. There is no aggregate payload savings claim. This comparison uses the saved manifest; it does not download or reverify remote payloads.

## Reproducible evidence

[Machine-readable receipt](evidence/current-catalog-qualification-20261018.json) records timings, metrics, full input/output pins, source digest, limits and raw evidence hashes. Raw evidence remains in primary ignored output:

`output/publication-remediation-20261018/rollout/local-current-catalog/trial-2feb8c7/`

It includes the worker/watchdog receipts, progress and RSS logs, output manifest, full inventory hashes and accepted static output. The fresh helper is `qualify-combined-2feb8c7.py` beside the trial directory. The earlier failed attempt and helper remain intact. The worker disabled network access, ran no classifier and acquired no source documents. No remote mutation or workflow dispatch occurred.
