# Historical recovery reconciliation

Historical measurement at its recorded pins. The selected owner packet is now `$COORD/shared/raw-recoveries-owner-32c13ffa/`, containing the unchanged base and 57 superseding decisions. Use the current [B7 owner instructions](README.md); this earlier stage is not selected for import or parity.

The then-current canonical E1 policy stages all 24,028 accepted recovery decisions without unknown kinds or duplicate accepted mappings. The run reused the 101,953,318-byte immutable source-facts file; no receipt rescan, PDF read or live write occurred. It took 12.85 seconds on this Mac; no production speed claim is made.

Native counts are 11,596 matched mappings, 12,432 accepted-only mappings, 2,580 receipt-only body rows, 643 basis differences and 328 recovered-URL differences. These grains differ from earlier distinct-mapping counts and do not establish D1 parity.

The immutable stage selected for this historical measurement was `$COORD/shared/raw-recoveries-4bcaa112/`, with 24,028 provenance records. Its registry SHA-256 is `f2e978f69bf1ac33699fa5a1cf7baa500aba14ac7f79d47d2414d02c70ed17f7`. It admits 12,351 requests for owner import and leaves 81 unresolved: 57 category conflicts and 24 exact recovered-URL/source-time associations. All 24 time cases have body receipts: 41 candidate observations are retained in `source-time-candidates.parquet`; none was silently selected across a different URL. All 81 unresolved rows are in `unresolved-imports.parquet`.

The three copy bases use engine's explicit `import_category` policy (`4d8e94dc`). No second identity fallback remains. Missing or conflicting choices still refuse. The earlier 16-row-registry stage (`raw-recoveries-9c19d861`) is measurement evidence, not the stage selected for parity or import.

After owner qualification, rerun the B7 README's stage command with admitted registry/source facts, inspect the ready/unresolved counts, then use its owner-gated import commands. Apply provenance only after E4 parity. The six excerpt decisions remain exactly those in `excerpt-decisions.json`; no rejection was inferred.

The public-record validator checks recovery URL/value/evidence types and nullable review-note text. Malformed-record regressions failed first; the accepted focused provenance/recovery/review/import-fence run passed 92 cases, and the final explicit-policy run passed 88 cases with the new engine snapshot. Earlier staged measurements remain evidence at their recorded pins.
