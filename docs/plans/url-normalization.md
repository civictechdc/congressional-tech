# URL normalization implementation plan

Implement the corrections supported by the [reconciled findings](../url-normalization-defense.md), [lifecycle trace](../url-normalization-trace.md), and [real-data validation](../experiments/url-normalization-validation-20261031/report.md).

**Status: proposed implementation with acceptance checks.** Production readiness has not been demonstrated. The six work items below preserve the evidence requirements and limits established by the audit.

## 1. Correct Wayback discovery while retaining exact replay checks

In [discovery.py](../../packages/corpus_recovery/src/corpus_recovery/discovery.py):

- Return `([], None)` when the parsed CDX page is an empty list, letting the caller preserve prior candidates, evidence, and query bounds.
- Validate the query's non-null SURT against both the returned `urlkey` and the validated returned `original`.
- Preserve the observed campaign target in `target_url`; put the returned archived spelling in `original_url`, the replay URL, and deduplication identity.
- Leave `validate_wayback_replay` exact. Preserve status, time-window, completeness, redirect, and digest checks. Digest verification occurs during replay acquisition; do not claim the index row itself validates the body.

**Acceptance:** retain the 120-response replay outcomes, pagination preservation, and rejection of wrong SURT, original, timestamp, status, final URL, incomplete responses, and body digest. A repaired parser must not turn page-limited or rate-limited queries into complete coverage. [Experimental implementation and guards](../experiments/url-normalization-validation-20261031/README.md).

## 2. Correct the two targeted URL rules

In [url-rules.json](../../model/registries/url-rules.json), use the experimentally checked patterns:

```json
{
  "id": "senate-notfound",
  "pattern": "(?i)^(https?://(?:[a-z0-9-]+\\.)+senate\\.gov)/404\\?notfound=(?:%2f|/)?([^#]+)(?:#.*)?$",
  "replacement": "$1/$2",
  "decoder": "percent"
}
```

```json
{
  "id": "download-ampersand-query",
  "pattern": "(?i)^(https?://(?:[a-z0-9-]+\\.)*(?:house|senate)\\.gov/download/[^?#]+?)(?:%20|\\s)*&download=1(?:#.*)?$",
  "replacement": "$1?download=1",
  "decoder": "none"
}
```

These are changed fields, not complete replacement registry records. Preserve the existing rule kind, provenance, and other required fields.

**Acceptance:** reproduce the four Senate and 30 ampersand-fragment changes, preserve observed literals, and inspect affected associations. The zero changed published-source keys reported by the audit compare the **current nine-rule implementation with the proposed correction**. The older published release used seven rules; this comparison does not substitute for rebuilding from that older publication policy to the final implementation.

## 3. Carry repaired candidates through scheduler state and campaign membership

In [capture_scheduler.py](../../packages/congress_api/src/congress_api/acquisition/capture_scheduler.py) and the relevant acquisition path, keep the observed target and attempt history while selecting an admissible fetch candidate. Cover lone malformed seeds, mixed spellings, existing bad state, and campaign mode. The model's `url_normalized` output is `(url, error, still_wrapped, base_key)`; internal `u.value` is not a public fetch-address output.

**Acceptance:** run the seven retained-address scenarios and demonstrate that repaired requests remain bound to the original target, eligibility, requirements, and capture profile. Do not drop existing history, satisfy an unrelated target, or retry an already satisfied target merely because its candidate spelling changed.

## 4. Qualify content identity and document gains separately

Retain literal recovery custody checks. Preserve original bodies and receipt bindings even when a publisher filename is misleading. The `hr-4824`/H.R. 4755 example requires a decision about the intended document; silently counting it as correct bill recovery is unsupported. Future validation should compare available bill identifiers, witness/hearing context, versions, and timestamps as appropriate, and explicitly preserve uncertainty when those checks cannot establish identity.

**Acceptance:** demonstrate both positive cases and the actual mismatched-bill negative case. Report target acceptance, distinct bodies, semantic identity, and publication additions separately. Keep PDF readability, owner-permission handling, and size-limit changes separate from semantic correctness.

## 5. Handle additional address repairs and lookup aliases within their demonstrated scope

The six malformed-prefix cases support narrowly defined candidate generation before HTTP link admission. The five successful `%20` candidates support address repair without establishing new documents. Keep repeated-slash identity behavior separate. Nested-HTTP matching alone must not trigger blanket splitting or unwrapping.

The public lookup results support an explicit alias design if alternate-spelling lookup is desired. That design must preserve distinct wrapper/content rows and temporal representations and must specify whether an alias can return multiple associated records. It should not replace the fixed lookup key with model identity by assumption.

## 6. Verify the final publication and consumer behavior

Build the final combined implementation against pinned inputs and compare document membership, source/recovery association, eligibility, and exact/alternate lookup behavior. Include the old seven-rule publication baseline, not just the current nine-rule comparison. Current evidence bounds some normalization effects but is not a full combined publication run.

**Acceptance boundary:** publisher server internals, historical scheduler-caused loss totals, all new Wave 6 semantic matches, and full combined publication behavior remain unproved. These limits belong in the release decision. The validated mechanisms justify implementation; the available evidence does not justify calling it production ready.
