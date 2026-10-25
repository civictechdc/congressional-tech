# Review of commit `1455011a`

**Not yet ready for the defense.** The earlier archive-identity, filename-input and capture-fact repairs are substantial improvements. The implementation plan also handles migration safety more convincingly. However, several new rules fail when composed with existing rules: valid new PDFs can disappear, filename aliases can prevent rendition grouping, and publisher evidence does not consistently reach the public document.

The structural problem is specific: **new facts have been added to individual sections without always tracing their production, consumption and identity through the whole system.** This calls for bounded repairs, not a redesign.

I read the four submission documents and the permitted diff, applied the requested skill in Audit mode, ran executable models of the rules, and queried the read-only snapshot. I did not read pipeline code, other reviews, credentials or network resources. These checks establish specification failures and data characteristics; they do not establish implementation behavior.

Quantities below are marked **[M] measured by me**, **[T] taken from the thesis**, or **[E] estimated**. Grades are evaluative judgments. Synthetic counterexamples are illustrative, not corpus measurements.

## 1. Disposition of the previous findings

| Previous item | Verdict | Evidence and remaining qualification |
|---|---|---|
| **1. Separate archive position from historical identity** | **Fixed** | [Architecture §3](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-architecture.md:73), DM §§6.1, 7.2 and 7.5 now distinguish `entry_index` from endpoint identity. Re-running the reordered-archive counterexample places the different editions at the same endpoint, marks their bodies ambiguous, and blocks the shared-XML bridge. A shared member path matches each member; null-safe endpoint comparison is explicit. |
| **2. Represent filename inputs and define repeated-capture behavior** | **Fixed** | [DM §§5.3 and 6.1](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:142) supply `recovered_filename`, `retained_name` and the download header. [§7.4](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:435) specifies one name per capture row and explains how different names join through the same body. The original missing-input counterexamples are resolved. A newly exposed interaction with rendition grouping remains below. |
| **3. Carry provider status, retry deadlines and archive-expansion results through the schemas** | **Fixed** | [DM §§5.2, 6.1, 6.2 and 7.7](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:173) now represent the necessary facts. The raw `Retry-After` header supports deriving the deadline; a restarted job does not fetch before it. ZIP fingerprints use captured members only following an `expanded` result. |
| **4. Deliver the reference profile and semantic results** | **Partly fixed; my earlier demand needs narrowing** | [Plan §5.3, S](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/simplification-plan-20261024.md:106) is appropriately placed before dependent engine work. **I accept that executed results belong to this build checkpoint, rather than requiring a completed implementation for a specification thesis.** What remains necessary before defense is a code-independent acceptance sheet: fixture inputs and expected outcomes, registry matching/precedence rules, and an explicit measurement and decision procedure for widening fingerprints. “If the count matters” is not yet an executable decision rule. |
| **5. Complete cleanup, binding, ordering and specification repairs** | **Partly fixed** | [Plan B0](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/simplification-plan-20261024.md:159) now uses a separate rewriter, checks credential parameters, verifies against the original backup after a crash, and preserves that backup. The JSON parser binding, `witness-document`, fingerprint-before-final-grouping order, and “§15, item 7” reference are repaired. Range completeness still contradicts the receipt schema. Renumbering also left deletion references pointing to the wrong bindings section. |

The owner’s narrower fingerprint scope is now stated honestly in DM §7.5. I accept that decision. The model also retains the current-candidate restriction, so stale fingerprints do not change the result of a maintained lake relative to a clean rebuild.

## 2. Problems that remain in the revised rules

### N1 — Valid new PDFs can be silently excluded

**Must revise.** Locations: [Architecture §8.3](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-architecture.md:320); [DM §6.2](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:215) and [§7.3](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:408); Plan D2.

The new real-file predicate requires `r[sniff].intact` for a PDF. But a new capture carrying the pinned `sniff_version` does not enter the sniff work list. Neither its receipt nor its capture row carries `intact`.

Consequently, a complete, valid, freshly fetched PDF can have:

- an empty sniff work list;
- a known PDF format;
- no `r[sniff].intact`;
- no membership in `real_files`.

My rule model reproduces that exclusion. The completeness gate does not catch it because the declared work list is already empty.

There is also an I/O contradiction: sniffing promises a read of the beginning, while `intact` requires inspecting the end or opening the PDF. Bodies with identical beginnings can have different endings and different validity.

**Acceptable fix:** define one versioned route that supplies integrity evidence for every PDF, including newly captured PDFs. It may reuse capture-time inspection or produce a reading, but the schema, work list and predicate must agree. Specify the reads needed for older compressed bodies and revise the cost estimate. Test fresh valid PDFs, damaged PDFs and readable PDFs with trailing material.

The decision to exclude broken PDFs is sound. Its evidence path is incomplete.

### N2 — Range assembly has conflicting completeness rules

**Must revise.** Locations: [Architecture §7.1](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-architecture.md:257), [DM §5.2](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:96), and Plan B2.

The architecture permits a fully assembled ranged download. The receipt schema still says `complete` is false for a `206` response or a response carrying `Content-Range`; the plan repeats that unconditional exclusion.

Furthermore, matching the declared length does not establish that the assembly represents one publisher entity. My counterexample combines the beginning of one edition with the end of another edition of equal length. The resulting length is correct, but the bytes match neither original.

**Acceptable fix:** define completeness once and reference it elsewhere. An assembly must establish correct range coverage and consistency of the entity across requests. Define the recorded status and completeness of that assembled body. If consistency cannot be established, retain the attempt as evidence and retry a whole fetch.

### N3 — Filename aliases can suppress legitimate rendition edges

**Must revise.** Locations: [DM §7.4](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:442) and [§7.5](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:460).

Consider a PDF fetched from one address under different download names, alongside an XML rendition linked by the publisher. The revised naming rule creates distinct source files for those names and joins them by body.

The rendition rule nevertheless counts **source files** when requiring different formats. The publisher group therefore contains repeated PDF formats and loses its rendition edges. My rule model leaves the XML separate.

This does not implement the settled decision about genuinely different same-format files. These are names for identical bytes.

**Acceptable fix:** evaluate rendition multiplicity over distinct real bodies, or equivalent same-body groups, before applying the one-per-format restriction. Preserve the restriction for different PDF bodies. Add the combined filename-alias/PDF/XML fixture; testing each feature separately misses the failure.

### N4 — Publisher evidence is collected but incompletely applied

**Must revise.** Locations: [DM §6.2](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:216), [§7.5](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:509), and Architecture §11.6.

There are related gaps here.

**Link text does not feed the kind rule.** The registry accepts publisher link labels and XML type codes, and readings preserve both `text` and `doc_type`. The derivation consumes only `doc_type`.

This matters in the actual catalog: **9 source rows [M]** identify `source_link_label` as their kind source. Among the inspected cases, article and op-ed labels coexist with the same generic `source_document_type = other`. A mapping that sees only that code cannot recover the distinction.

**Removal evidence depends on saved-file selection.** `removed_on` examines links to the saved file. If the committee’s original copy has removal evidence but a newer mirror becomes the saved source, the note can disappear while document membership and the historical removal remain unchanged. The rule-level counterexample reproduces that result.

**The MODS association remains underspecified.** `meeting_refs` identifies meetings. The new derivation also needs an explicit association from the metadata record to the source file or package receiving those meetings.

**Acceptable fix:** define one derived relation connecting publisher observations to source files, retaining page context, target, text, type and parsed dates. Use it consistently for kind fallback, meeting association and removal evidence across relevant document members. Specify the metadata-record association key and invalid-date behavior. This can remain inside the SQL plan; it does not require a stored `page_links` table.

### N5 — URL repair changes a key function into a multi-target operation

**Must revise.** Location: [DM §7.2](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md:342).

Previously, `url_key(url)` normalized an address into a comparison key. It now calls `repair(url)`, which can split a concatenated href into several URLs. Its callers still compare scalar keys for endpoints, recoveries, variants and queue membership.

That introduces an undefined return cardinality at a central boundary. Adding one repair entry can now change assumptions throughout the model.

**Acceptable fix:** separate href repair and expansion from scalar address normalization:

- repair an observed href into explicit targets;
- retain deterministic target identity/order;
- resolve each target;
- compute one `url_key` per resulting address.

Keep exact captured URLs as identity, as the specification already requires. Test a concatenated href whose resulting targets both exist in the archive.

## 3. Structural-erosion assessment

I applied the requested lens qualitatively. Document length and registry count are not findings by themselves.

| Decision | Evidence and bounded recommendation | Change cost saved |
|---|---|---|
| **Keep the identity distinctions; reshape rendition membership around them.** | Body, endpoint, source file and occurrence represent genuinely different things. The archive repair demonstrates their value. N3 shows where grouping still operates at the wrong level. | Another naming source should not require another exception in rendition grouping. |
| **Reshape format detection and integrity assessment.** | `sniff` has acquired an end-of-file/readability responsibility while retaining its prefix-only work contract. N1 is an actual failure, not merely an awkward name. Keep inexpensive format detection; explicitly own any additional body assessment. | A new format’s validity check can be added without silently changing the I/O and completeness assumptions for every sniffer. |
| **Keep header-first naming; make selection total.** | The precedence reflects real evidence sources. It does not need a framework. However, “a query parameter in the registry” does not select a winner for `?file=a.pdf&name=b.pdf` or repeated parameters. Specify registry priority and within-parameter selection, shared by the producer and model. | New filename parameters become data-and-fixture changes instead of opportunities for different implementations to generate different IDs. |
| **Reshape publisher evidence once, rather than extending the precedence chains independently.** | Kind fallback, removal dates and MODS meetings were added separately to §7.5. N4 shows lost evidence and dependence on saved-file choice. Give their common source-to-document association one home. | A new publisher should mainly require parser facts and registry entries, without coordinated patches to several document derivations. |
| **Keep registries and the model profile; clarify their dependencies.** | The profile earns its place through reproducibility and completeness checks. Registries keep publisher policy outside the engine. But §7.1’s blanket “applied in the model” description does not fit filename parameters, which affect a lake producer, or capture scope, which fetchers consume. State consumer, version owner and affected work list explicitly. | A registry addition has a predictable backfill/release consequence rather than requiring a search through producers and orchestration rules. |
| **Delete duplicate operative rules, not useful explanations.** | Range completeness already disagrees across the architecture, schema and plan. DM §7.2 also embeds concrete wrapper/strip-list contents alongside the versioned-registry mechanism. DM §6 includes a provisional clause making writer settings depend on a future plan experiment. Keep normative behavior in one home; move examples and proposed measurement-driven changes to informative text. | Changes stop requiring synchronized edits to several purported authorities. |
| **Keep principle 8 and the bindings separation.** | Object storage, fetch transports, the catalog and the reader are real test and replacement boundaries. Bind/adapt/build/seed is a useful migration distinction. I found no evidence that replacing this structure would help. | Implementations can change without rewriting the specifications. Do not turn the component table into a requirement for additional factories or wrapper layers. |

The narrow fingerprint policy is also worth keeping pending measurement. Its current-domain rule addresses a real determinism problem. The next improvement should be an explicit experiment, not another speculative expansion.

For S, distinguish a census from a sample. Recognizing re-packaged copies requires content evidence from outside the narrow candidate set; naming a count does not explain how to obtain it. State the examined population, how copies are recognized, the evidence retained, and how the result determines widening. Completed results can follow implementation.

## 4. Measurements, complexity and smaller repairs

The principal scale claims remain credible:

| Check | Result |
|---|---|
| Snapshot row counts | Captures **3,909,134 [M]**; filenames **1,683,430 [M]**; documents **1,241,157 [M]**. |
| Stored-body scale | **1,036,256 distinct hashes [M]**, with **696,357,882,380 stored bytes [M]** after grouping by hash. This supports approximately **0.70 TB [T]**. |
| Download-header naming | **95,664 catalog source rows [M]** carry the `content_disposition` origin, supporting the plan’s approximately **95,000 [T]**. |
| Occurrence sizing proxy | Summing source-path occurrences across each document’s catalog source files reproduces **1,695,040 [M]**, with a maximum of **455 [M]**. It remains a proxy for the revised model, appropriately labeled as such. |
| Page-context sizing | I reproduce **277,642 contexts over 214,041 bodies [M]** using successful HTTP statuses and server HTML/XML media types. That verifies a MIME/status proxy, not the full revised `good_fetch` and sniff predicates. Label it accordingly. |

I could not independently establish the current narrow fingerprint population, the proposed widening cost, cleanup findings, review-migration count, binding line references, browser performance or live storage charges. Their supporting production evidence was outside this review’s permitted inputs or has not yet been produced.

The asymptotic choices remain mostly sound:

- Hub-based grouping avoids pairwise edge construction. Union-find is effectively linear in the generated graph.
- Model sorting remains \(O(N\log N)\); work-list scans, model reconstruction and maintenance still grow with history.
- Link expansion and joins are output-sensitive: their cost depends on contexts and matching historical source files, not simply the number of stored links.
- Expensive parsing is generally cached per version. The new PDF-integrity rule needs an honest read-cost account before the “first bytes only” estimate remains defensible.

There are also small specification repairs:

- [Plan §2](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/simplification-plan-20261024.md:39) and [F3](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/simplification-plan-20261024.md:258) point deletion work to Bindings §5. That section now concerns dormant code; the deletion inventory is **Bindings §6**.
- Give cleanup a clearly bounded input inventory tied to its original backup evidence. The separate rewriter, conditional writes, verification and deletion condition are otherwise sound.
- Do not describe deferred measurements as evidence that the revised predicates already meet their targets.

## 5. Grades

| Area | Previous grade | Current grade |
|---|---:|---:|
| Problem framing and requirements | A− — 92/100 | **A− — 92/100** |
| Correctness and consistency | B — 85/100 | **B− — 82/100** |
| Efficiency and complexity | B+ — 88/100 | **B — 86/100** |
| Simplicity and maintainability | A− — 90/100 | **B+ — 87/100** |
| Data model | B+ — 87/100 | **B — 85/100** |
| Implementation plan and bindings | B+ — 88/100 | **B+ — 89/100** |
| Specification quality and testability | B — 86/100 | **B — 84/100** |
| **Overall architecture** | **B+ — 88/100** | **B — 86/100** |
| **Overall plan** | **B+ — 88/100** | **B+ — 89/100** |

The architecture grade falls because newly introduced rules have concrete correctness failures, not because the documents grew. The plan improves because cleanup, component binding and dependency ordering are clearer, and executing semantic tests is correctly front-loaded.

## Final verdict

**Not ready for the defense.** Before it, complete these bounded revisions:

1. Supply PDF-integrity evidence consistently and account for its I/O.
2. Reconcile range completeness and require assembly from one consistent entity.
3. Make filename selection deterministic and prevent same-body aliases from invalidating rendition groups.
4. Complete publisher-evidence propagation for kinds, removals and metadata-derived meetings.
5. Separate multi-target href repair from scalar URL keys.
6. Write S’s expected outcomes and measurement decision procedure, then correct the remaining authority and reference inconsistencies.

You do **not** need a completed production implementation before defending this specification. You do need rules whose required inputs exist, whose combinations preserve the stated behavior, and whose acceptance conditions another engineer can execute without inventing policy.