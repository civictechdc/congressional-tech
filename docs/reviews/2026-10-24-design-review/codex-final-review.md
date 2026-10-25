# Revised-thesis assessment

**This is a substantial improvement, but it is not yet ready for the defense.** The separation of schemas, architectural intent, and implementation work is clearer. Version selection, physical object locations, saved-file selection, and cutover dependencies are considerably stronger.

The remaining problems concern whether the specified algorithms actually preserve the stated guarantees. Several are introduced by the new link-reading, URL-alias, and review-precedence rules.

I reviewed the submission at `c3b067c4`, including the permitted diff. I did not read other reviews, pipeline source, credentials, or remote storage.

References:

- **A:** [engine-first-architecture.md](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-architecture.md)
- **D:** [engine-first-data-model.md](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md)
- **P:** [simplification-plan-20261024.md](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/simplification-plan-20261024.md)

Numerical evidence uses **[M] measured by me**, **[T] taken from the thesis**, and **[E] estimated**. Constructed counterexamples demonstrate failures permitted by the specification; they are not claims of observed production incidents.

## 1. Disposition of the earlier findings

### Required revisions

| Finding | Verdict | Evidence and remaining qualification |
|---|---|---|
| **R1 — Transitive edition merges** | **Partly fixed** | D §7.5 bans rendition edges for ambiguous bodies and correctly scopes fingerprint nodes by endpoint. P §5.3 adds the original mirror counterexample. However, repackaged equivalents can still bridge editions through `same_text`; see N2. |
| **R2 — Incomplete saved-file and override orders** | **Fixed** | D §7.5 adds `source_id` as the final saved-file tie-breaker and applies that order to alternates. D §7.9 resolves competing title overrides across merged members. These meet the fixes I requested. The broader duplicate-review rule and new recovery-file ordering have separate problems below. |
| **R3 — Incomplete computation dependencies** | **Partly fixed** | D §§6.4–6.5 add parser versions and derive recency from captures, correctly handling a response sequence A → B → A. D §§7.1–7.3 pin versions, permit corrected sniff results, and move classification out of parsers. However, `readings.base_url` introduces a new capture-dependent value into a body-keyed cache, and fingerprint completeness is contradictory. |
| **R4 — Lost attribution and physical locations** | **No longer applies** | The owner explicitly accepts attribution loss in the crash window; A §7.1 now states that limitation honestly. The separate physical-location problem is fixed by recorded suffixes and verification records: D §§5.1–5.3, 6.1, 7.5. I am not requiring pending records or object metadata. |
| **R5 — Publication versus retention race** | **Fixed under the settled operating rule** | A §§10.3.7 and 12 establish shared CI exclusion and explicitly require outside-CI operators to avoid overlap. P §§6.2 and 6.6 implement that arrangement. This is an operational guarantee, and the specification now identifies it as such. |
| **R6 — Incomplete column-level model** | **Fixed for the omissions identified** | D §6.3 preserves ambiguous scalar observations; §§7.5 and 8.1 carry review dates and typed saved-file media types; `meetings.parquet` supplies meeting display records; §7.10 defines occurrence grain and ordering. |
| **R7 — Incomplete normative specification** | **Partly fixed** | Fingerprint normalization, parser activation, archive-entry semantics, and the bodiless-row qualification are clearer. D §7.1 identifies registry categories and versioning. However, the submission still does not identify a concrete reference profile and registry contents, and P §5.3 still schedules the promised semantic evidence as future work. |
| **R8 — Missing cutover prerequisites** | **Fixed** | P §4 makes F depend on B13, which depends on protection work. P §6.6 requires recorded PDF copies, usable saved files and recoveries, final-release device targets, failed-canary behavior, and capture’s transition to `url_state`. |

### Recommended revisions

| Finding | Verdict | Evidence and remaining qualification |
|---|---|---|
| **S1 — “Once” and cost claims** | **Partly fixed** | A §4 now enumerates repeated work; P §5.2 measures intermediate join rows and bytes; the unsupported sniff-duration promise is removed. But A §5 still says fetching is not repeated, and A §4 still broadly says uploading grows with new data despite full-release uploads. |
| **S2 — Stable recovery-link identity** | **Partly fixed** | D §8.2 freezes wrapper and strip-list versions and specifies unresolved-link behavior. However, `url_key` now also applies mutable provenance aliases, which the frozen identity definition does not exclude or freeze. See N5. |
| **S3 — Input-identity validity** | **Partly fixed** | D §8.3 replaces row counts with retained input identities and gives a validity argument. A §10.3.2 defines comparison against any input record of the live release. The argument nevertheless depends on deterministic, complete readings—properties contradicted by N1 and N4. |
| **S4 — Fixture versus semantic oracle** | **Fixed** | P §6.5 explicitly compares against the original catalog pair, not F0, and requires checkable cause predicates and reviewed examples. |
| **S5 — Versioned writer settings** | **Fixed at specification level** | D §§7.1 and 8.1 make writer settings part of the pinned profile; F0 and C3 provide validation work. The settings remain proposed values until those measurements exist. |

### Minor findings

| Earlier minor | Verdict | Location |
|---|---|---|
| Incorrect filename-reader URL-list inventory | **Fixed by removal** | D §6.3 retains the correct dependency rationale without the erroneous inventory. |
| Attempts confused with capture rows | **Fixed** | A §5 distinguishes the units. |
| Incorrect canary cross-reference | **Fixed** | A §4 now points to §10.3.5. |

The revision deserves credit for these fixes. Recording physical suffixes, separating extraction facts from classifications, and comparing parity against the original catalog pair are especially useful improvements.

## 2. New problems and remaining failures

### N1. Relative links are cached under a key that does not determine their meaning

**Severity: must revise.**  
**Location:** D §6.2, especially `base_url` and `links`; §§7.10 and 8.3.

The same HTML bytes can occur at different addresses. A relative `report.pdf` link in `/old/index.html` and `/new/index.html` names different files. The proposed reading resolves both using the body’s first capture URL and stores that result once.

This has two consequences:

- The reading loses valid link targets from other capture contexts.
- If an earlier capture arrives later, incremental ingestion retains the previous base URL, while a complete rebuild chooses the newly earliest capture. Identical final inputs can then produce different readings.

I measured **28,032 bodies labeled HTML in the existing readings that occur at multiple context URLs [M]**. Examples include identical GovInfo HTML appearing directly and inside a ZIP. That does not establish that every such body has relative links; the constructed case establishes the algorithmic defect.

**Accepted fix:** Keep literal link targets and the literal `<base>` value in the body reading. Resolve them against the applicable capture or archive-member context in the model. This preserves the owner’s decision to derive links from readings and requires no `page_links` table.

### N2. Repackaged equivalents bypass the edition-body ban

**Severity: must revise; residual R1.**  
**Location:** D §7.5 and invariant 14.

The chosen ban closes the original counterexample, but not this permitted extension:

- The original endpoint served old body A and new body B with different fingerprints. Both are banned from rendition edges.
- Another endpoint served A and repackaged A′ with the same fingerprint. They connect through `same_text`; A′ is not itself an ambiguous body.
- A third endpoint similarly connects B to repackaged B′.
- A′ and B′ each receive rendition edges to the same XML body.

The resulting path is:

`A → A′ → shared XML → B′ → B`

No banned body takes a rendition edge, yet the component violates invariant 14. I reproduced this constructed graph while enforcing the specified ban.

**Accepted fix:** Propagate the restriction through the equivalence classes formed by `same_body` and `same_text` before admitting rendition edges, or supply another deterministic component-level check. Explicit reviewer merges remain permitted. This strengthens enforcement of the settled decision rather than changing it.

### N3. A recovery import can prevent an original URL from ever entering the fetch queue

**Severity: must revise.**  
**Location:** D §7.7 and invariant 12.

The historical state excludes imports, but the new queue tests whether **any capture row** requested the URL.

Consider a linked URL represented only by a `retained_import` receipt. It has never had a real fetch:

- The import produces no historical `url_state` row.
- Its presence in `captures` suppresses the queue row.
- The URL disappears from the capture schedule.

**Accepted fix:** Test queue membership against actual fetch attempts, using the same mode distinction as historical state. Add a fixture where recovery evidence exists but the original URL has never been fetched.

### N4. Fingerprints cannot be both complete at publication and deferred until the next run

**Severity: must revise.**  
**Location:** D §§7.1, 7.3, 8.3; A §10.3.1.

D §7.1 requires publication to refuse an incomplete pinned version. D §7.3 nevertheless permits a body arriving between fingerprint production and snapshot pinning to receive its fingerprint one run later.

These are incompatible when the newly included body is a fingerprint candidate.

The input-identity change makes the distinction consequential: if publication accepts incomplete fingerprints, completing them later changes neither the receipt set nor the profile. The early-skip rule could then suppress the release that should reflect the completed interpretation.

**Accepted fix:** Keep the completeness gate authoritative. Pin a consistent input boundary or refuse and retry when a late candidate makes the selected snapshot incomplete. Remove the claim that the incomplete version can participate in that publication.

### N5. Mutable URL aliases still change public keys, and alias recursion has no termination rule

**Severity: must revise; residual S2.**  
**Location:** D §§7.2 and 8.2.

`link_url_key` freezes wrapper and strip-list versions, but is defined through `url_key`, whose new final step applies provenance `url_variants`.

Adding an accepted alias from an original URL to a canonical URL can therefore change the public recovery key even though the frozen registries are unchanged.

The recursive alias rule also permits cycles. Accepted mappings A → B and B → A have no specified rejection or termination behavior.

**Accepted fix:** Separate immutable public-key normalization from current alias resolution, or retain explicit historical keys. Define active alias selection, self-map handling, and cycle rejection. Identify the frozen identity configuration so a rebuild can reproduce it.

### N6. Override precedence now accidentally governs merge edges

**Severity: must revise.**  
**Location:** D §7.9.

The new rule selects the latest record **“for each verdict”** across a document’s keys. That includes `duplicate_of`.

Suppose a document has keys A₁ and A₂. An active review joins A₁ to B, and another active review joins A₂ to C. Neither supersedes the other. Selecting only the latest duplicate verdict discards one requested merge.

There is also an ordering ambiguity: precedence refers to a document’s keys while duplicate edges help determine that document.

**Accepted fix:** Resolve active duplicate decisions per target before grouping and apply all surviving merge edges. Apply document-level precedence to display overrides and hide decisions after grouping.

### N7. The revised re-fetch count treats error responses as replacement copies

**Severity: must revise.**  
**Location:** P §6.2, B14 and its completion criteria; D §7.3.

The revised plan specifies **59 URLs [T]**.

My snapshot query finds **64 candidate URLs [M]** without another positive-size, non-truncated body recorded with a successful status and an appropriate saved/verified outcome. Ignoring HTTP status reproduces **59 [M]**.

The difference is instructive:

- **Three excluded URLs [M]** have only alternative **214-byte bodies [M]** recorded with HTTP 520.
- **Two excluded URLs [M]** have large PDF alternatives whose indexed HTTP status is null.

For example, the Finance Committee’s `rtf-report-appendix-ii-exhibits-part4&download=1` URL has the error-response alternative. It does not satisfy the thesis’s successful-file rule.

**Accepted fix:** Derive the re-fetch list from qualifying complete copies, not merely the existence of another body. Restore the error-response cases. Check the original receipts before deciding whether the status-null PDF cases need another fetch.

The authoritative final count requires that receipt check; I am not claiming that the index alone proves the final queue must contain exactly **64 [M, candidate count]**.

### N8. The new recovery file has no total order for distinct recovery records

**Severity: must revise.**  
**Location:** D §§7.5 and 8.1, `recoveries.parquet`.

The new file assigns ordinals using the recovery order:

`(kind, imported_at descending, body_sha)`

Distinct recoveries can share those values while differing in recovered URL, evidence, or identity note. Reversing tied input rows can therefore change ordinal assignment and exported bytes.

**Accepted fix:** Define a unique recovery identity and use it as the final tie-breaker. Apply the same order to recovery selection and recovery-file ordinals. Include a fixture with equal body, kind, and timestamp but different exported evidence.

## 3. Specification and evidence repairs

These are smaller than the failures above, but the final submission should correct them.

**Supply a concrete normative profile.** D §7.1 improves the registry framework, but “one versioned file beside the model SQL” does not identify the submitted rules. P §5.3 still proposes creating them and selecting thresholds. Provide a reference profile, identifiable registry artifacts, and the promised semantic fixtures and results. This is the remaining part of R7.

**Qualify the initial pointer invariant.** D §8.1 permits `previous_release_id = null` before the second flip, while invariant 20 requires both pointer values to name existing releases. Require existence only for non-null release IDs.

**Restore reader requirements that became commentary.** The capture/import date labels now live in non-normative A §9.4, which P §6.1 cites. If correct labeling is a reader conformance requirement, state it in the normative Site section. Likewise, restore the explicit requirement that hearing filtering matches membership in `meeting_keys`; the previous release-schema wording included it.

**Repair the incomplete derivation.** D §7.5 ends the `document_date_source` rule with “null when document_date is”. Complete the condition.

**Finish the cost-language cleanup.** A §5 still says fetching is not repeated. A §4’s upload-growth claim should distinguish new raw objects from complete release uploads.

**Label M2’s evidence accurately.** P §5.2 includes links parsed from a sample but promises the real graph. The **4.2-million-link figure [T, estimate]** comes from an **80-body sample [T]**. A sampled or scaled workload can test mechanisms and memory pressure; it does not establish the real graph’s component sizes or join-key distribution. Identify that limit and retain an explicit full-data check after link backfill.

I found the principal numbered cross-references consistent with the renumbering. The more important losses are changes in normative force and algorithmic meaning.

### Numerical checks

The corrected ordinary-day figures reproduce: **3,553 capture rows [M]** from **2,946 receipt-line attempts [M]**. The ambiguity counts also reproduce: **498 multi-number rows [M]**, **955 multi-date-token rows [M]**, and **2 multi-congress rows [M]**.

I measured **2,717,129 capture-index rows without a timestamp [M]**, supporting the approximate **2.7-million figure [T]**. It does not establish that the original receipt lines lack timestamps; P’s planned receipt check correctly recognizes that distinction.

The **287,765 HTML/XML body count [T]** reproduces using media-type substring matching **[M]**. Treat it as a metadata-based scope estimate until sniffing confirms formats.

The proposed **105-MB release [T, estimate]** and **70–90-KB detail read [T, estimate]** remain estimates. I did not independently validate the final engine workload, browser performance, remote catalog behavior, or current storage pricing.

Reproducible evidence is in [revision_measurements.json](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/final-review-2/codex/revision_measurements.json), [revised_number_checks.json](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/final-review-2/codex/revised_number_checks.json), and [revision_counterexamples.json](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/final-review-2/codex/revision_counterexamples.json).

## 4. Grades compared with the previous submission

| Area | Previous | Revised | Reason |
|---|---:|---:|---|
| Problem framing and requirements | A−, 92/100 | **A−, 92/100** | Clear purpose and explicit accepted limitations remain strong. |
| Correctness | C, 74/100 | **C+, 77/100** | Several important fixes, but grouping, link context, and queue semantics still fail permitted cases. |
| Efficiency and complexity | B, 84/100 | **B+, 87/100** | Better reuse of page parsing and better intermediate-result measurements. Full-history scans, sorting, and export remain deliberate costs. |
| Simplicity | B, 83/100 | **B+, 88/100** | Clearer ownership of rules and fewer independently maintained tables. |
| Data model | C+, 77/100 | **B−, 82/100** | Stronger versioning, types, physical references, and browser records; context-dependent readings remain a serious defect. |
| Implementation plan | B, 85/100 | **B+, 88/100** | Better cutover gates, parity predicates, and safety ordering; the re-fetch predicate and sampled-graph qualification need correction. |
| Specification quality | C+, 78/100 | **B−, 82/100** | Better organization and more precise derivations, with remaining contradictions and unidentified normative inputs. |

**Overall architecture: B, 83/100 — previously B−, 80/100.**  
**Overall plan: B+, 88/100 — previously B, 85/100.**

## Final verdict

**Not yet ready for defense.** The remaining requirements are specific:

1. Resolve relative links using their capture context.
2. Close the repackaged-equivalent edition bridge.
3. Keep recovery imports from suppressing unfetched URLs.
4. Enforce one consistent fingerprint-completeness rule.
5. Freeze public recovery identities completely and make alias resolution terminate.
6. Preserve every active reviewer merge.
7. Correct and substantiate the re-fetch queue.
8. Give recovery records a total order.
9. Supply the reference profile and semantic evidence, and complete the specification repairs above.

The central architecture is worth keeping. The next revision should demonstrate that these rules compose correctly; the document structure now makes those corrections much easier to express.