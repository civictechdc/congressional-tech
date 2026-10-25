**This is a substantial improvement, but it is not yet ready for the defense.** You have corrected most of the earlier failures without abandoning the architecture’s strongest choices. The remaining problems concern preservation of link context, deterministic grouping and recovery ordering, and the semantic evidence previously requested.

I reviewed `d9730967` and the permitted diff. I did not read pipeline code, other reviews, credentials, or network sources.

References below use **A** for [Architecture](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-architecture.md), **D** for [Data Model](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/engine-first-data-model.md), and **P** for [Implementation Plan](/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/simplification-plan-20261024.md). Quantities marked **[M]** were measured in this review; **[T]** come from the thesis; **[E]** are estimates. Grades are my judgment.

**Disposition of the previous findings**

“Fixed” here means corrected in the specification. It does not certify an implementation.

| Item | Verdict | Evidence and location |
|---|---|---|
| **N1 — Context-dependent cached links** | **Partly fixed** | D §6.2 now stores literal `href` and `base_href`; D §7.2 resolves links in the model. The original cache-dependency counterexample passes. However, relative base references remain incomplete, and D §7.10 still reduces a page body to its first fetch, losing the context the new resolution rule requires. |
| **N2 — Repackaged editions bridge through a shared rendition** | **Fixed** | D §7.5 extends the exclusion from `ambiguous_bodies` to matching fingerprints in `edition_bodies`; invariant 14 follows it. Rerunning the original repackaged-mirror counterexample keeps the editions separate. This meets the requested grouping fix. A separate dependency problem introduced by the broader fingerprint lookup appears below. |
| **N3 — Recovery imports suppress unfetched URLs** | **Fixed** | D §7.7 excludes only URLs matched by `mode = fetch` rows, using requested and final URLs; invariant 12 agrees. The import-only counterexample now produces a queue entry. |
| **N4 — Completeness contradicts delayed fingerprints** | **Fixed** | A §§10.3.1 and 12 put completeness before input identity and early skip. D §7.1 requires refusal when work remains, and the permission to publish with a delayed fingerprint is gone. The original incomplete candidate cannot legitimately reach early skip. |
| **N5 — Recovery keys change with aliases; alias recursion can cycle** | **Fixed** | D §8.2 hashes the exact original URL, independent of normalization and provenance. D §7.2 applies aliases once and rejects chaining. The alias-change and cycle cases now have stable or rejected outcomes, respectively. |
| **N6 — Merge precedence discards active reviewer decisions** | **Fixed** | D §7.9 applies every unsuperseded `duplicate_of` edge before grouping. Display precedence applies afterward. The independent-merge counterexample retains both requested merges under reordered input. |
| **N7 — Cutoff recovery count accepts error bodies as replacements** | **Fixed** | P §6.2, B14 now requires a complete successful copy and distinguishes missing status from success. I reproduced **64 candidate URLs [M]**, agreeing with the revised **64 [T]**. The error-response alternatives no longer discharge the work. |
| **N8 — Recovery order is not total** | **Partly fixed** | D §7.5 adds the import’s receipt coordinates, and D §8.1 uses that order. This fixes the original distinct-import tie. It does not guarantee uniqueness after the provenance join in D §7.8. |
| **Item 9 — Reference profile and semantic evidence** | **Not fixed** | P §5.3 now names the reference profile and expands the fixtures, but still lists them as future work. The submission supplies neither concrete registry contents nor the promised semantic results. Naming a deliverable more clearly does not deliver it. |

The strongest corrections are substantive: literal links restore the intended parser boundary; reviewer merges now have coherent precedence; exact-URL recovery keys remove mutable normalization from identity; and the publication sequence now rejects incomplete inputs explicitly.

**Outstanding and newly introduced problems**

**N1 remains incomplete: preserve context through resolution and occurrence selection.**

Location: D §§6.2, 7.2 and 7.10.

The revised reading is correctly independent of capture history. But the consumers do not consistently preserve that separation.

Consider the same page body fetched at:

```text
https://example.org/old/index.html
https://example.org/new/index.html
```

Its literal `report.pdf` identifies a different target at each address. D §7.2 correctly produces both targets. D §7.10 then says to reduce the page body to its first good fetch before joining occurrences. Depending on implementation order, this either loses the later-context link or attributes it to the wrong linking page. My executable rule model reproduces the loss.

Also, `base_href` is explicitly stored “as written,” but §7.2 resolves against it directly when present. A relative value such as `../assets/` must first be resolved against the page context.

**Accepted fix:** Define resolved links with their page context retained. Deduplicate repeated visits per `(page body, context endpoint)`, then select the earliest applicable link for each occurrence. Resolve a relative base reference against that context before resolving the link. Include archive-member contexts and absolute external links in the fixtures.

This is relevant to the corpus: **28,032 HTML-reading bodies occur at multiple context URLs [M]**. That is an exposure count, not a measured count of incorrect relative links.

**New A — Rendition groups combine links from different page contexts.**

Location: D §7.2 and §7.5, `same_rendition(a)`.

Resolution now expands a shared page body across its addresses, but the rendition-group key remains `(page body, group_path)`.

A constructed counterexample:

- An identical page template under `/hearing-a/` and `/hearing-b/` lists relative `report.pdf` and `report.xml`.
- Only hearing A’s PDF and hearing B’s XML have been captured successfully.
- Both enter the same body-and-group-path group.
- Their formats differ, so the rule merges unrelated documents.

The revised rules reproduce this false merge. No edition-ambiguous endpoint is required.

**Accepted fix:** Include the resolved page context in the rendition-group identity. Define directory identity completely for the fallback too, including the host and archive-member directory where applicable.

Keeping contexts does increase necessary work: link resolution grows with the sum of each body’s link count multiplied by its distinct contexts. Repeated fetches at the same context can be reduced safely; distinct contexts cannot.

**New B — Grouping can depend on previously computed fingerprints.**

Location: D §§6.2, 7.1, 7.5 and 8.3.

The fingerprint producer processes bodies at endpoints containing multiple real bodies. The new `edition_bodies` rule consults fingerprints of **every real body**. Those domains differ.

The counterexample is:

1. An earlier profile requires a fingerprint for a repackaged body because its endpoint contains another real body.
2. A registry change excludes that other body. Under the current profile, the endpoint no longer requires fingerprints.
3. An incrementally maintained lake retains the repackaged body’s fingerprint. A clean rebuild under the current profile does not produce it.
4. The new global fingerprint comparison bans its rendition edge only in the incrementally maintained lake.

Both states have empty required work lists. They have identical raw inputs and the same current profile, but different document groups. My rule model reproduces that difference.

This contradicts D §8.3’s input-identity argument. Completeness alone does not establish determinism when optional cached rows can affect output.

**Accepted fix:** Define one deterministic fingerprint domain for both production and consumption. Either restrict consumption to the current required candidate set or require completeness over a broader explicitly defined set. Add a test comparing an incrementally maintained lake with a clean rebuild after a registry change.

**N8 remains incomplete: specify the recovery row’s identity after joining provenance.**

Location: D §§7.5, 7.8 and 8.1.

Receipt coordinates uniquely identify an import entry. They do not necessarily identify an output recovery.

D §7.8 joins provenance on normalized original URL and body. Nothing requires that join to be many-to-one. Distinct unsuperseded decisions—including decisions for different original URL spellings that normalize together—can match the same import. Their exported notes or evidence can differ while every field in the new recovery ordering remains equal.

The original distinct-import test now passes. A provenance fan-out test still changes exported order when input order changes.

**Accepted fix:** State the recovery relation’s primary key and join cardinality. Either specify how the join selects one applicable decision, or preserve multiple rows and include a stable decision identity in the total order. Test uniqueness before assigning ordinals; unique ordinals cannot repair an arbitrary ordering.

**Item 9 still requires submitted evidence.**

Location: D §7.1; P §5.3.

The semantic checkpoint is well designed, but it remains a plan. Before the defense, submit:

- A concrete reference profile and identifiable registry contents.
- Executable examples covering the revised rules and the counterexamples above.
- Results from the promised labeled sample, including wrongful exclusions, inclusions and merges.

The required evidence concerns semantics. The owner’s decision to set speed targets after device measurements remains accepted.

**Specification repairs**

| Earlier repair | Verdict |
|---|---|
| First publication permits a null previous release | **Fixed:** D §8.1 and invariant 20 now agree. |
| Capture-date labels and hearing-filter membership lost normative force | **Fixed:** A §11.6 states both requirements normatively; P §6.1 cites it. |
| Incomplete `document_date_source` sentence | **Fixed:** D §7.5 completes the null case. |
| Claims that fetching never repeats and uploads grow only with change | **Fixed:** A §§4–5 distinguish scheduled refetching and whole-release uploads. |
| Sampled links described as the real graph | **Partly fixed:** P §5.2 now labels the link sample and requires a full-data join afterward. Its next bullet still says “Group the real graph,” and A §16.2 still promises real-graph grouping before construction. Label the initial grouping as sampled and explicitly repeat grouping after the full link backfill. |
| Renumbered cross-references | **Fixed in the references checked:** I found no dangling explicit cross-document section references. |

**Numerical checks and limits**

The revised measurements are more carefully framed:

- **287,765 bodies [M]** have server media types containing HTML or XML, matching D §6.2. The revised text correctly identifies this as server labeling.
- **1,313,678 distinct non-null source URLs [M]** support P §5.2’s rounded **1.31 million [T]**.
- I reproduced **1,695,040 occurrence-like rows [M]**, with a maximum of **455 per old document [M]**, by expanding the old catalog’s `source_paths`. Those match D §7.10’s figures. However, those paths include local import paths, and the calculation uses old document membership. Label these as a **catalog sizing proxy**, not measured output of the proposed occurrence rule.
- The cutoff check finds error alternatives of **214 bytes with HTTP status 520 at three URLs [M]**. The **two large alternatives with missing status [M]** still require receipt inspection, as B14 now says.
- The stored-body total is **696,357,882,380 bytes [M]**, consistent with the thesis’s rounded **0.70 TB [T]**.

I did not verify live storage charges, raw receipt contents, browser performance, or engine execution. The counterexamples are executable interpretations of the specification, not tests of the prohibited pipeline implementation. [Counterexample results](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/final-review-3/codex/revision3_counterexamples.json) and [snapshot measurements](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/final-review-3/codex/revision3_measurements.json) record the checks.

**Grades**

Scores are out of 100.

| Area | Previous | Revised |
|---|---:|---:|
| Problem framing and requirements | A− / 92 | **A− / 92** |
| Correctness | C+ / 77 | **B / 84** |
| Efficiency and complexity | B+ / 87 | **B+ / 88** |
| Simplicity | B+ / 88 | **A− / 90** |
| Data model | B− / 82 | **B+ / 87** |
| Implementation plan | B+ / 88 | **B+ / 89** |
| Specification quality | B− / 82 | **B / 85** |
| **Architecture overall** | **B / 83** | **B+ / 87** |
| **Plan overall** | **B+ / 88** | **B+ / 89** |

The grades rise because the revision resolves real failures and improves the separation of responsibilities. Correctness and specification quality remain below the stronger framing and structural work.

**Final verdict: not yet ready for the defense. Exactly these items remain:**

1. Preserve page context through link resolution, occurrence selection and rendition grouping; complete relative-base handling.
2. Make fingerprint consumption independent of the lake’s processing history.
3. Define recovery join cardinality and a genuinely total recovery order.
4. Submit the reference profile, registry contents and semantic test results previously requested.
5. Correct the remaining sampled-versus-real-graph claims and label the occurrence counts as a catalog proxy.

Keep the architecture. Finish these obligations and demonstrate that the rules compose correctly.