**Not yet ready for the defense.** The earlier context, fingerprint-history, and recovery-order failures are now corrected. The component/binding separation also improves the plan. However, the new archive identity introduces another route for merging editions, several new requirements lack the data fields needed to implement them, and the promised reference profile and semantic results remain undelivered.

I reviewed the submission at `9a87e119`. I did not inspect pipeline code, the referenced inventory, other reviews, or credentials. Binding line references and implementation claims are therefore assessed as planning assertions.

References: **A** = [Architecture](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-architecture.md), **D** = [Data Model](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md), **P** = [Plan](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/simplification-plan-20261024.md), **B** = [Bindings](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/bindings-20261025.md).

Quantities marked **[M]** were measured by me, **[T]** are taken from the thesis, and **[E]** are estimates. Grades are instructor judgments.

**Verdicts on the previous final list**

| Item | Verdict | Location and result |
|---|---|---|
| **1. Preserve page context through resolution, occurrences and grouping** | **Fixed for the original finding** | D §§7.2, 7.5 and 7.10 now retain `(page body, context)`, resolve relative base references first, and scope publisher groups by context. The relative-link, wrong-attribution and cross-hearing-template counterexamples now pass. The newly introduced archive-position issue is separate, described below. |
| **2. Make fingerprint consumption independent of processing history** | **Fixed** | D §6.2 defines the current candidate domain and excludes fingerprints left over from earlier profiles. D §7.5 uses that domain. The maintained-lake versus clean-rebuild counterexample now produces the same grouping. The broader scope also requires the previously missing rendition-member fingerprints before publication. |
| **3. Define recovery cardinality and total ordering** | **Fixed** | D §7.8 establishes one recovery per import row and chooses one applicable decision by `(decided_at, id)`. Its primary key makes the receipt-coordinate tie-breaker in §7.5 sufficient. Reordering matching decisions no longer changes the selected recovery. |
| **4. Submit the reference profile, registries and semantic results** | **Not fixed** | P §5.3 still schedules these deliverables. B §4 identifies sources from which to build them, but supplies neither the reference profile nor test results. Sources for evidence are not the requested evidence. |
| **5. Correct sampled-graph claims and occurrence-count labels** | **Fixed** | P §5.2 explicitly uses sampled links and repeats grouping after the full backfill; A §16.2 acknowledges the later real-link measurement. D §7.10 labels occurrence volume as an estimate sized from the old catalog. |

These verdicts concern the specification. My executable rule models do not certify the implementation.

**What is stronger**

The binding approach is sound in principle. A §4, principle 8, and P §2 separate domain rules from storage, transport and catalog implementations. B’s distinction between binding, adapting, building and retaining behavior as fixtures gives implementers a useful starting point without making existing code the authority.

The expanded fingerprint domain is also a justified response to the edition problem. The specification now distinguishes cached computation from evidence that the current model may consume. That distinction is essential to reproducibility.

The cleanup sequence in P §4 is sensible: prevent new sensitive receipts, clean the older receipts, verify them, then lock. Conditional replacement, readback comparison and retaining the backup through verification are meaningful protections.

**Must revise before defense**

**A. Archive position is not a stable identity across editions.**

Location: A §3; D §§6.1, 7.2, 7.5 and 7.10.

Adding `entry_index` distinguishes duplicate names within an archive. Using it in the historical endpoint key creates a different problem.

Consider a ZIP at a stable URL. Its `report.pdf` contains edition A. After repacking, that path contains edition B but occupies a different archive position. Under the revised endpoint definition, these are different endpoints, so the PDF bodies never become edition-ambiguous. Mirrors can then pair each PDF with the same XML and merge them transitively.

I reproduced this counterexample. Fingerprinting every rendition member does not prevent it: the exclusion rule first needs an ambiguous endpoint to identify the contested edition. Ambiguity of the ZIP container itself does not propagate automatically to its members.

The index also stops short of the public model:

- D §7.10 still defines occurrence grain without `entry_index`.
- The occurrence release schema omits it.
- A relative link names a member path, not an archive position; the rule does not say how it selects among duplicate paths.

**Accepted fix:** Separate physical entry identity from historical path identity. An exact archive entry can use the container body and entry index; edition comparison must retain history across changes in position. Define duplicate-path link ambiguity explicitly, and carry sufficient identity through occurrence joins. Add a reordered-ZIP fixture with the shared-XML mirrors.

**B. The filename rule requires inputs absent from the declared schemas.**

Location: D §§5.3, 6.1, 6.3 and 7.4; B §4, recovered-filename and effective-filename rows.

The header-first rule has a clear implementation path through `h_content_disposition`. Other branches do not:

- “The recovered name if provenance says so” has no corresponding field in the recovery provenance schema.
- The older import’s retained basename has no dedicated column in `captures`. `member_path` is defined for archive members, not local import paths.
- The filename work list and model are specified in terms of capture rows and provenance, so those missing inputs cannot simply be assumed available.

This matters in the supplied data: **12,891 catalog rows use `retained_path` naming, all without a source URL [M]**.

**Accepted fix:** Add the retained import basename and recovered-name override to the appropriate schemas, with selection rules connecting them to the filename work list. Also state whether “one name per file” applies per capture or across repeated captures whose headers change; the current distinct-triple derivation retains separately observed names.

The owner’s header-first decision stands. The revision must make every branch of that decision computable.

**C. New capture requirements are not carried through the data model.**

Location: A §§7.1–7.2; D §§5.2, 6.1, 6.2 and 7.7.

The clearest failure is `Retry-After`. The fetcher must honor it, and receipts now retain the header. But `captures` has no retry deadline, while `url_state` makes retryable outcomes due at `last_attempt`.

A server can request a delay extending beyond the next daily run. A restarted capture job reads the release, sees the URL as due, and has no recorded deadline with which to honor that request. My scheduling counterexample reproduces this conflict.

Other new required facts lack defined fields:

- The fetching provider’s status must be recorded separately, but its destination is unspecified.
- A refused archive expansion must have an entry outcome, but the entry schema defines none. The lake’s `outcome` is inherited from the receipt line.
- Fingerprinting chooses between captured members and reading the archive, yet there is no explicit indication that captured expansion was complete.

**Accepted fix:** Define the provider status, archive expansion result and retry deadline in the raw and derived schemas where needed. Make scheduling respect the deadline across process restarts. Permit captured-member fingerprints only when the required expansion is known complete. Add contract tests for these transitions.

**D. Complete the promised semantic submission.**

Location: P §5.3; B §4.

The bindings Note improves traceability, but this remains the same unmet defense requirement. Submit the concrete reference profile, registry contents, adversarial results and labeled-sample results.

The committee-code registry is a better design than the previous prefix formula. Its examples and seed locations still do not establish its coverage or correctness. The same applies to file shapes, error markers, listing thresholds and capture scope.

The submitted evidence must show the behavior of the revised rules, including the new archive, naming and retry cases. Device speed targets may remain subject to the owner-approved measurement process.

**Plan and specification repairs**

These are smaller than the correctness findings, but should be completed in the final document set.

- **Make the cleanup’s temporary binding explicit.** P B0 and B §3.1 use the body store for conditional replacement; P B3 defines its permanent refusal of non-create-only writes. B0 precedes B3, so the authorized exception is feasible. Name the temporary migration interface and its removal instead of leaving the distinction implicit. Specify that restart verification uses the original backup baseline after a crash between replacement and recording verification.

- **Align cleanup verification with the stated invariant.** D invariant 3 prohibits credential parameters in every receipt, while B0’s transformation and final scan cover headers and local paths. Establish whether older receipts satisfy the broader condition. I found **no listed credential-parameter names in the snapshot’s `context_url` column [M]**; that does not inspect requested URLs, redirects or nested receipt fields. I cannot certify the cleanup’s reported cookie/path totals from the supplied index.

- **Finish the binding map.** A §6 includes a general JSON reading producer, but B §3.2 does not give it a binding. Committee and meeting JSON producers do not cover every JSON reading required by D §6.2.

- **Keep parser rules in the specification.** B §3.2 says to add `witness-document` as a grouping ancestor; D §6.2’s ancestor list omits it. Put the rule in its authoritative location.

- **Reconcile Range resume with completeness.** B §3.1 retains Range resume, while A §7.1 treats a response with partial-content status or `Content-Range` as incomplete. Specify how a validated assembled entity becomes complete, or remove resume from the promised binding.

- **Order the final graph measurement after fingerprints.** P D2 currently places repeated grouping with the link backfill, before its fingerprint step. Candidate-group construction can happen there; final edition-sensitive grouping requires the completed fingerprint inputs.

- **Repair the reference to A §15.7.** P B11 and B §2 mean §15, item 7; no subsection §15.7 exists.

The binding structure earns credit for exposing these handoffs. It does not yet establish that every handoff is complete. No dependency-injection framework is necessary; explicit inputs, outputs, error behavior and composition are sufficient.

**Measurements and efficiency**

The numerical checks mostly support the revised scale discussion:

| Claim | Check |
|---|---|
| About **95,000** catalog rows carry a download-header name **[T]** | **95,664 rows [M]** have `content_disposition` among their filename origins. |
| **277,642 contexts over 214,041 bodies [T]** | Reproduced exactly **[M]** using HTTP-success status and HTML/XML media-type labels. These remain index proxies: they do not establish the target’s complete-fetch, mode and pinned-sniff predicates. |
| Old-catalog occurrence sizing | Reproduced **1,695,040 rows**, maximum **455 per old document [M]**. The revised estimate label is appropriate. |
| Stored body volume | **696,357,882,380 bytes [M]**, consistent with rounded **0.70 TB [T]**. |
| Wider fingerprint reads | **20–45 GB [T, estimate]** remains unverified. The final candidate set requires the missing profile and resolved-link data. |

The wider fingerprint scope is accepted. Its cost grows with newly admitted candidate bytes, although a policy change can admit historical bodies. Link resolution grows with links multiplied by distinct contexts; sorting remains superlinear, and the model still scans history each run. The revision generally states those costs honestly.

The estimated target count obtained by multiplying average contexts by estimated links should remain an estimate: pages with many links may also have unusually many contexts.

[Counterexample results](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/final-review-4/codex/final4_counterexamples.json) and [snapshot measurements](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/final-review-4/codex/final4_measurements.json) record my checks. I did not verify live storage charges, receipt contents, binding implementation accuracy or deletion estimates.

**Grades**

Scores are out of 100.

| Area | Previous | Revised |
|---|---:|---:|
| Problem framing and requirements | A− / 92 | **A− / 92** |
| Correctness | B / 84 | **B / 85** |
| Efficiency and complexity | B+ / 88 | **B+ / 88** |
| Simplicity | A− / 90 | **A− / 90** |
| Data model | B+ / 87 | **B+ / 87** |
| Implementation plan, including bindings | B+ / 89 | **B+ / 88** |
| Specification quality | B / 85 | **B / 86** |
| **Architecture overall** | **B+ / 87** | **B+ / 88** |
| **Plan overall** | **B+ / 89** | **B+ / 88** |

The architecture improves because the earlier failures are genuinely corrected. The plan gains useful implementation mapping but also introduces an irreversible migration and new obligations whose interfaces remain incomplete.

**Final verdict: not ready for the defense. What remains is explicit:**

1. Separate archive entry identity from edition-history identity, and complete archive link and occurrence semantics.
2. Represent every input required by the filename rule and clarify naming across repeated captures.
3. Carry retry deadlines, provider status and expansion results through the required schemas and tests.
4. Submit the reference profile, registry contents and semantic results previously required.
5. Finish the cleanup binding and verification procedure, reconcile the listed binding/specification discrepancies, and correct the measurement ordering and references.