# Verdict

**A strong architectural direction, but not yet ready for defense. Architecture: B−, 80/100. Implementation plan: B, 85/100.**

The submission makes several sound systems decisions: permanent evidence is separate from rebuildable interpretations, expensive extraction is cached by input, publication uses immutable releases, and the browser’s access pattern shapes its files. The plan also puts meaningful experiments ahead of major construction.

The weakness is precision at the boundaries. Some advertised guarantees do not follow from the specified algorithms. In particular, grouping can reconnect different editions, selection is not fully deterministic, and maintenance can delete a release that publication subsequently selects. These require design revisions and executable counterexamples before the defense.

I read the documents in the requested order at `39ae52d2`. I checked the supplied snapshot and `house-naming`; I did not inspect pipeline source, earlier reviews, file history, credentials, or remote storage.

References below use:

- **A:** [docs/engine-first-architecture.md](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-architecture.md)
- **D:** [docs/engine-first-data-model.md](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md)
- **P:** [docs/plans/simplification-plan-20261024.md](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/simplification-plan-20261024.md)

Numerical evidence is marked **[M] measured by me**, **[T] taken from the thesis**, or **[E] estimated**. Grades are my assessment.

## Grades

| Area | Grade | Assessment |
|---|---:|---|
| Problem framing and requirements | **A− — 92/100** | Clear purpose, beneficiaries, preservation boundary, and product decisions. |
| Correctness | **C — 74/100** | Important invariants are identified, but several algorithms do not enforce them. |
| Efficiency and complexity | **B — 84/100** | Sensible bounded recomputation and avoidance of pairwise graph edges; incomplete accounting for joins and repeated work. |
| Simplicity | **B — 83/100** | Good removal of competing authorities. Some physical tuning is more precise than the underlying semantics. |
| Data model | **C+ — 77/100** | Strong separation of evidence and interpretations; gaps in versioning, multiplicity, observation time, and browser fields. |
| Implementation plan | **B — 85/100** | Good risk ordering and migration discipline; cutover prerequisites and acceptance criteria need tightening. |
| Specification quality | **C+ — 78/100** | Useful conformance classes and invariants, but unresolved references and contradictory qualifications prevent independent implementation. |

**Overall architecture, including the data model: B− — 80/100.**  
**Overall implementation plan: B — 85/100.**

## Evidence checked

Most of the important scale claims withstand inspection.

| Check | Result |
|---|---|
| Capture index | **3,909,134 rows [M]**, representing **2,596,054 receipt lines [M]** across **2,289 receipt keys [M]**. |
| Distinct bodies and storage | **1,036,256 bodies [M]**; deduplicated indexed stored sizes total **696.36 GB [M]**. Largest indexed stored object: **1.188 GB [M]**. These support A §5’s approximate figures. |
| Catalog pair | **1,683,430 source files [M]** and **1,241,157 documents [M]**. |
| Filename-reading workload | **1,392,681 distinct filename/URL pairs [M]**. |
| Multi-valued facets | **24,202 source files with multiple kinds [M]**, **3,637 with multiple families [M]**, and **5,229 with multiple committee codes [M]**. |
| Occurrences | **4,727,694 occurrences [M]**; largest document has **33,479 [M]**. |
| Shared bodies in the old catalog | **141,762 body keys occur in multiple documents [M]**, confirming the difficulty addressed by F0 and E4. |
| Placeholder threshold | The specified threshold of **100 URLs [T]** selects **18 bodies [M]**. The sensitivity counts at the other stated thresholds also match. |
| Truncation | **201 distinct bodies [M]** have the specified incomplete outcomes at **64 MiB [T]**. |

The PDF storage estimate is credible: grouping bodies identified by PDF media types gives **403.25 GB of original bytes [M]**, close to the thesis’s **403 GB [T]**. This is a metadata-based check, not independent format verification. Existing stored bodies plus those copies would occupy approximately **1.10 TB [E]**, before subsequent growth and other objects.

The proposed **$72/year PDF-copy cost [T]** is arithmetically consistent with that volume at the implied tariff; I did not verify current pricing.

I did **not** independently reproduce the narrow model’s **3.7-second runtime and 1.75-GB memory use [T]**, the proposed **2.2-MB list [T, estimate]**, or the approximately **90-MB release [T, estimate]**. The final wide model, browser working set, and remote catalog behavior remain qualification work.

Queries and results are retained in [measurements.json](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/final-review/codex/measurements.json) and [semantic_measurements.json](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/final-review/codex/semantic_measurements.json).

## Strengths

**The preservation boundary is well chosen.** Raw bodies, receipts, and human decisions are permanent; tables and releases can be rebuilt. That gives parser corrections and model changes a recoverable foundation. The explicit acceptance of provider-side loss also makes the durability claim understandable. Keeping raw data on R2 alone is a settled constraint, not a deficiency in this review. **Evidence: A §§4, 7; P §§1–3.**

**The design distinguishes observations from interpretation.** Fetch attempts, bodies, source files, documents, recoveries, and reviews have different meanings. Preserving unsuccessful attempts and keeping recovery timestamps separate from capture dates prevents misleading historical claims. The snapshot’s incomplete bodies demonstrate why these distinctions matter. **Evidence: A §§8.2, 9.2, 9.4, 9.6; D §§5–7.**

**The filename-reading cache uses the right principal inputs.** Including the exact source URL is justified: the allowed package actually tests exact URLs when applying publisher-specific rules. Preserving multiple facet values is likewise supported by the measured corpus. **Evidence: A §8.4; D §6.3; `house-naming`’s `Engine.extract` and source-qualified matching.**

**The browser layout follows actual access patterns.** A compact searchable list, positional detail access, separate public-link lookup, and paged occurrences avoid making every search load provenance-heavy records. The measured occurrence distribution supports separating these concerns. **Evidence: A §§10.1, 11.1; D §8.1.**

**The plan front-loads meaningful uncertainty.** M1 tests catalog maintenance and conflicting appends; M2 tests wide joins and the actual graph; S tests semantics; F0 exercises the reader before the replacement pipeline exists. This is substantially stronger than a plan organized only around implementing components. **Evidence: P §5.**

**The migration preserves evidence when parity fails.** A fact found only in derived tables blocks cutover until someone explicitly decides its disposition. That is the right response to an imperfect historical system. **Evidence: P §§6.4–6.5, 9.**

## Findings: must revise before defense

### R1. The local edition guard does not prevent a global edition merge

**Location:** A §9.3; D §7.4 and invariant 20; P §5.3.

**Problem and evidence:** Connected components take the transitive closure of all accepted edges. Blocking rendition edges *at an edition-ambiguous endpoint* does not guarantee that different editions remain in separate components.

A constructed counterexample satisfies the written rules:

- An original URL has an old PDF and a new PDF with different text.
- One mirror groups the old PDF with an XML file.
- Another mirror groups the new PDF with the same XML bytes.
- Each mirror endpoint is individually unambiguous, and each rendition group contains one file per format.

The shared XML connects the old and new PDFs indirectly. No rendition edge at the original endpoint is necessary. I reproduced this on a small constructed graph; this is not a claim that I observed that mismerge in the corpus.

**Acceptable revision:** Define an automatic grouping rule that prevents incompatible editions from entering the same component, including through mirrors and transitive edges. Specify deterministic handling of conflicting rendition evidence and how an explicit reviewer merge overrides that restriction. Add this case to S. Also state that fingerprint helper nodes are scoped by endpoint, not merely by fingerprint.

### R2. The saved-file “total order” is not total

**Location:** A §§9.4, 10.3; D §§7.4, 7.8.

**Problem and evidence:** The selection key ends with the body hash. Different source files can share the same body, format, and first-fetch time while having different filenames and filename readings.

For example, differently named identical PDFs within one ZIP receive the same receipt time. The specified key cannot choose between them, yet that choice determines the displayed filename and facets. The snapshot contains **78,359 bodies associated with multiple filenames [M]**, so filename variation is a material concern.

There is another unresolved selection conflict: two files with different active title overrides can later merge. “Apply overrides to the resulting document” does not choose the winning override.

**Acceptable revision:** Add a final stable source-file tie-breaker, such as `source_id`, and specify selection within each alternate format. Define precedence among reviews targeting different members of a merged document. Test reordered inputs containing these ties, not just inputs whose keys are already unique.

### R3. “Compute once” requires complete dependency keys

**Location:** A §§8.3–8.7, 10.4.1; D §§2, 6.2–6.6, 7.2.

**Problem and evidence:** Several stored results depend on inputs missing from their keys or activation rules:

- `committee_records` and `meeting_records` have no parser version, so a corrected parser cannot append a corrected interpretation under the stated uniqueness rules.
- Those tables store `retrieved_at` while processing each body only once. If responses arrive as **A, B, A**, the last observation of A does not update its stored timestamp. Selecting by that timestamp can incorrectly keep B current.
- Listing thresholds and XML-root registries affect stored `record_role`, but D §2 says a registry change is a model-version change. Existing readings would retain the previous classification.
- `coalesce(c.sniffed_format, r[sniff].format)` permanently prefers the fetcher’s recorded classification, even after a corrected sniff parser exists.
- Filename catalog versions lack an explicit equivalent of the parser’s “newest complete version” selection rule.

**Acceptable revision:** Document each derived result’s full dependencies and version them accordingly. Keep extraction facts keyed by body and parser version; derive observation recency from captures. Define activation for a complete parser/catalog profile and verify its coverage against the exact capture snapshot used for publication.

### R4. The crash procedure preserves bytes but can lose their source history

**Location:** A §§7.1–7.4; D §§5.1–5.3, 6.1.

**Problem and evidence:** The described crash window is real: a body PUT succeeds, then the writer dies before its receipt. Rehashing that orphan proves its identity, but does not recover the requested URL, time, or source context. If the publisher changes the content before retry, the retry receipt will describe another body.

Physical storage identity is also incomplete. A single logical body can have an older `.gz` object, a `.pdf` copy, and a new unsuffixed object. The lake drops `body_key`, but the specification does not fully define how to reconstruct each physical object’s location, encoding, and verification record.

**Acceptable revision:** Specify a durable capture-binding procedure that survives this crash—for example, a pending raw record binding the attempt, URL, body hash, and intended object key, followed by completion. Distinguish pending records from successful captures. Record or derive physical representations through an explicit rule that covers old objects, copies, new writes, and orphan recovery.

### R5. Retention can delete a release immediately before it becomes live

**Location:** A §§10.4.4–10.4.7, 12; D invariant 17.

**Problem and evidence:** Re-reading the pointer immediately before deletion does not coordinate maintenance with publication.

A constructed execution is:

1. An old, unselected release still exists.
2. A publisher reproduces that release and its canary passes.
3. Maintenance reads the current pointer and deletes the old release.
4. The publisher’s pointer compare-and-swap succeeds because maintenance never changed the pointer.

The live pointer now names missing files. The stale-tab reload rule cannot repair that state. Serializing publishers through CI does not serialize maintenance, and A §12 says correctness must also hold outside CI.

**Acceptable revision:** Give publication and retention a shared exclusion or retirement protocol that covers candidates through promotion, including reused release IDs and local execution. Add a test that pauses publication after the canary while retention runs.

### R6. Complete the column-level model before calling it implementable

**Location:** D §§6.3, 7.3–7.4, 7.8, 8.1; A §§9.5, 11.5.

**Problem and evidence:**

- The snapshot has **498 source rows with multiple `measure_number` values [M]**, **955 with multiple `date_token` values [M]**, and **2 with multiple `congress` values [M]**. The proposed columns are scalar. Running the current filename reader on `BILLS-1117s2126-SUS.pdf` reproduces `congress = ["111", "1117"]`; no scalar-resolution rule is supplied.
- Meeting titles, dates, types, and committees are required browser content, but the release schema carries meeting identifiers without specifying where the joined display records are exported.
- The hidden-document page requires the review’s date, but its release representation is not specified.
- `saved_media_type` sits in the display-only fold even though the reader uses it to open decompressed content. That contradicts D §4’s native-column rule.
- `occurrences` has columns and a range invariant, but lacks a complete row-grain and ordinal derivation.

**Acceptable revision:** Preserve observed lists and explicitly define any scalar selection; ambiguity must not cause silent value selection. Trace each required browser behavior to an exported field. Define occurrence identity, deduplication, ordering, and aggregation. Separate source-file grain from its potentially multiple endpoint/member-path observations.

### R7. The normative rules are not yet sufficiently self-contained

**Location:** D §§2, 6.2, 7.1–7.2, 10; A §§8.3, 9.2; P §5.3.

**Problem and evidence:** The submission incorporates registries “by reference” without identifying exact files or revisions for most of them. Several lists and thresholds are explicitly still to be chosen. Normalized text fingerprints also lack a reproducible normalization algorithm and failure behavior.

There are contradictory qualifications:

- D §7 excludes completion rows from every input, but §7.6 needs them to compute `links_scanned`.
- D invariant 3 requires every new row to have a sniffed format, although line-only failed attempts have no body to sniff.
- A §8.3 calls ZIP members separate attempts, while the receipt and capture definitions represent them as entries within a shared attempt.

**Acceptable revision:** Supply identifiable normative registry artifacts and precise fingerprint rules, including empty extraction and parse failure. Resolve these contradictions and map requirements to responsible conformance classes. The semantic checkpoint should produce executable examples and classification results before the defense.

### R8. The cutover dependencies omit required preparation

**Location:** P §4 dependency table; §§6.1–6.2, 6.6.

**Problem and evidence:** Track F depends on A and E. Track A’s completion language explicitly allows legacy PDF opening to wait for B13. Therefore the dependency graph permits cutover before the copies required by the reader exist.

The completion criteria also do not consistently require the real-device measurements described in A11: “phone-sized profile” is not the same evidence as a real phone.

**Acceptable revision:** Make the switch depend explicitly on the required raw-protection work and completion/readback of the legacy PDF representations. Require the final engine-built release to meet the targets established on real devices. Give F a concrete acceptance checklist covering reader compatibility, saved-file availability, publication failure behavior, and capture’s transition to `url_state`.

## Efficiency assessment

The design mostly makes a sensible trade: expensive extraction is incremental, while relational interpretation is recomputed. That is defensible at the measured scale. It is not a system whose total cost grows only with new data.

Let \(N\) be historical input rows, \(K\) processed computation keys, \(V\) graph nodes, and \(E\) emitted edges.

| Work | Complexity and consequence |
|---|---|
| Work-list construction | Expected \(O(N+K)\) scans/hash operations. A no-change run still examines history before the early skip. |
| Body and filename extraction | Incremental by unseen input/version, subject to the dependency corrections above. |
| Model sorting and export | \(O(N\log N)\) sorting plus scans and output writing. |
| Connected components | Near-linear in \(V+E\) with an appropriate implementation. Helper nodes correctly avoid generating pairwise cliques. |
| Link/context joins | Expected input-linear **plus result cardinality**. A key with \(a\) captures and \(b\) link observations can produce \(ab\) rows if joined before reduction. |
| Release upload | Proportional to the complete changed release, not just changed documents. |
| Browser search | Generally linear in the downloaded list unless separately indexed. A worker moves computation off the UI thread; it does not change that complexity. |
| Weekly verification | Linear in historical object metadata, plus the sampled body reads. |

With steady arrivals, repeating a full-history pass every run produces quadratic cumulative scan work in the number of runs. That is an asymptotic observation, not a prediction that this corpus is currently too large.

## Findings: should revise

### S1. Narrow the “do each thing once” and cost claims

**Location:** A §§4, 7.1, 16; P §§5.2, 6.4.

Repeated fetches must hash the bytes again to discover that they are unchanged. The proposed create-only PUT path also does not establish that duplicate attempts incur no upload work. Filename and URL derivations, work-list scans, and the full export recur.

**Accepted fix:** State that expensive *derived extraction* is cached by input/version, and enumerate the accepted repeated work. In M2, measure intermediate join cardinalities and bytes as well as runtime and memory. Reduce repeated page-link observations before joins where the output needs only one selected observation. The “under an hour” sniff backfill **[T]** implies approximately **288 completed body requests per second [E]**; treat that as a benchmark claim requiring evidence.

### S2. Separate stable recovery-link identity from evolving join normalization

**Location:** A §§9.7, 10.1; D §§7.1, 8.2.

Recovery link keys hash `url_key(original_url)`, but wrapper and stripping rules are versioned and intended to change. A normalization correction can therefore change an already published recovery link.

**Accepted fix:** Freeze the normalization used for public identity, or retain aliases for previously published keys. Keep join normalization independently revisable. Also specify what happens to existing public links when later classification changes exclude a previously listed body.

### S3. Give input identity an explicit validity argument

**Location:** A §§10.4.1–10.4.3; D §§8.1, 8.4.

Partition row counts are progress indicators, not general content digests. They can support the skip optimization under strict append-only and deterministic-rebuild assumptions, but those assumptions need to be stated and enforced. The specification also allows several input records per release without defining exactly which record supplies “the live release’s” input identity.

**Accepted fix:** Define the comparison procedure, table-rebuild behavior, and immutable input set—including provenance—used for each run. Explain why equal identities imply equivalent model inputs.

### S4. Preserve the distinction between a reader fixture and a semantic oracle

**Location:** P §§5.4, 6.5.

F0 deliberately chooses one destination for shared body links. That is useful for exercising the reader, but it loses distinctions that matter to semantic comparison.

**Accepted fix:** Keep E4’s source-evidence comparison grounded in the original pinned catalog pair and retain the many-to-many correspondence. Require each “known cause” to have a checkable predicate and independently reviewed examples. A broad cause label must not conceal unrelated regressions.

### S5. Put physical tuning in a measured writer profile

**Location:** A §§10.1–10.3; D §8.1; P F0 and C3.

The specification precisely fixes page sizes and batch settings while leaving some semantic selections unresolved. These settings may prove correct, but their detail should follow the browser experiment.

**Accepted fix:** Keep required capabilities and determinism normative; place measured tuning values in a versioned writer profile. This retains reproducibility while making later tuning less disruptive.

## Findings: minor

- **Correct the filename-reader inventory.** D §6.3 reports **25 exact URLs in 7 lists [T]**. I found **25 URL entries in 9 rule lists [M]** in the specified package. The argument for retaining exact URLs remains valid.
- **Keep attempt and capture-row units consistent.** For the snapshot’s October 16 capture-date partition, I measured **2,946 distinct receipt-line attempts [M]** and **3,553 capture rows [M]**. A §5’s normal-day wording should identify the unit used.
- **Repair the canary cross-reference.** A principle 6 points to §10.4.6, which describes the flip; the canary is §10.4.5.

## Questions for the defense

1. **Show that editions stay apart under transitive grouping.** Walk through the shared-XML mirror counterexample. Which exact rule rejects the incorrect merge, and is the result independent of edge-processing order?

2. **Show that the same retained evidence produces the same interpretation.** Walk through response sequence A → B → A, a corrected parser, a registry change, and an interrupted catalog backfill. Which versions and observations does publication select?

3. **Show the complete failure boundary of publication and capture.** Pause a writer after its body PUT and a publisher after its canary. What durable records let the system recover source attribution and prevent maintenance from leaving the live pointer broken?