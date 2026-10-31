# URL normalization validation

Decision: Determine which claims in the URL normalization trace, defense, and response are supported by real corpus behavior, and which proposed repairs improve document acquisition and publication.

Hypotheses: The fifteen claims listed in the conversation predict measurable differences in real URL selection, retained content, recovery qualification, document membership, or public lookup. A regex match or changed key alone is insufficient evidence of a recovered or lost document.

Arms: Current code at cafb1b43 versus the specific proposed normalization and discovery changes, executed in isolated scratch jobs. Scheduler experiments use the actual planner and retained addresses/state. Proposed behavior is experimental; production files and active campaign artifacts are not modified.

Cases: The fixed publish_v20 release; the previously frozen campaign plans, selected recoveries, state, and Wave 4 results; retained acquisition responses and qualification evidence. Newer campaign artifacts may supplement these only with an explicit generation label. Classifications and acceptance flags are evidence to check, not independent proof of document identity.

Held constant: Input generations, URL registry versions, native binary, and query semantics. Native jobs use two threads and the existing 2 GB memory limit; DuckDB uses two threads and 1 GB. Read projected columns and reuse extracted candidate sets. New network requests, if needed, are bounded to unresolved real examples and kept separate from historical evidence.

Decision rule: Confirm a mechanism through actual execution; confirm scope through a corpus census; confirm document outcomes through retained bodies and their relationships. Reject a general claim when a real counterexample contradicts it. Record an explicit unresolved boundary where publisher configuration, missing bodies, or an unspecified implementation prevents proof. Do not turn parser-error reductions into document-recovery counts.

Coverage: (1) scheduler loss; (2) remaining House targets; (3) accepted repair bodies and novelty; (4) host/server explanation; (5) existing state and campaign behavior; (6) fragment and encoded-path rules; (7) archive alias identity; (8) archive pagination and acquisition; (9) discovery versus publisher links; (10) wrappers versus documents; (11) error-address filtering; (12) malformed literal repairs; (13) accepted aliases; (14) frontend lookup variants; (15) combined publication impact. Also retain the previous trailing-space collision result and check its recovery boundary.
