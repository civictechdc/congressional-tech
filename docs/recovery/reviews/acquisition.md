# Independent acquisition review — T6/T7

**Verdict: APPROVE for local adoption at a3ee633.** No unresolved blocker in the reviewed acquisition scope. This is an offline code and retained-evidence review; provider throughput and additional recovery remain live acceptance work.

## Scope and trace

Reviewed `scripts/webharvest_recovery.py`, `scripts/webharvest_validation.py`, their classifier dependencies and focused tests. The root reviewer was independent of the acquisition implementation agent. The review follows the semi-formal code-review method: trace inputs to effects, state invariants, examine failure paths, then use focused probes.

- `plan` (webharvest_recovery.py:101) reads each prior aggregate once, records its hash, preserves failures and deferred exclusions, and distinguishes live reservations by process identity. It does not equate a previous attempt with recovery.
- `acquire` (:320) locks one receipt directory, binds queue/config/exclusions, reconstructs completion from immutable receipts and groups replay aliases before bounded admission. Requests have a durable started marker. A completed download can finish classification without another request; a started request with no completed receipt requires review.
- `fetch` (:192) admits exact indexed HTTPS Web Harvest identity URLs. Direct requests carry target cookies only to the target; Firecrawl carries them in target headers rather than the provider session. Media and oversized responses are excluded. Qualification binds bytes, returned replay URL, content class and either archival digest or explicitly rendered provenance.
- `refused` (:314) stops further admission on provider/origin refusal, Retry-After or challenge content. Existing in-flight work drains. Resume with a saved refusal does not restart admission. Tests exercise provider and origin refusal separately.
- `freeze`, `classify_cached` and `validate_pdf_frozen` (webharvest_validation.py:40,76,160) bind qualification to retained classifier/validator bytes and configuration. Concurrent identical bodies share one extraction. Text/links stay in one digest-bound cache. PDF parsing and all-page rendering remain acceptance checks; optional preview cannot reverse successful acceptance.

## Invariants and evidence

The focused probes cover no repeat download, interruption after retained download, unknown request refusal, process reuse, source/digest exclusions, explicit pagination termination, target-cookie routing, global start spacing, worker/request ceilings, alias deduplication, refusal drain, concurrent cache reuse and malformed/truncated PDFs. The implementation agent's acquisition suite passed 39 tests; root's integrated suite passed 160 tests plus 6 subtests, including the acquisition/classifier tests. The integrated run log is `output/recovery-mvp-final-pytest.log` (later source-preparation correction will receive a focused rerun).

Earlier review concerns about cookie placement, refusal handling, configured concurrency and repeated full-aggregate hashing were resolved by 4950d11, integrated as a3ee633. No paid or live provider request was used for this review.

## Limits and operator responsibilities

- Pagination verification consumes explicit retained page metadata; it is not a new CDX discovery client.
- This command processes an explicitly selected queue. Cross-run exclusion of already-published work and authorization of retries remain planning responsibilities; separate directories are not a global queue lock.
- The dollar ceiling depends on a conservative caller-supplied request cost and prior spend. Account credits and current provider limits must be checked before a new paid pass; no automatic purchases are authorized.
- Interrupted uncertain requests remain visible for reconciliation. The implementation deliberately makes no claim that they completed or that every archive route is exhausted.
