# Unclassified filename pattern discovery

Decision: Which recurring filename families should be reviewed first to resolve missing document kinds?

Hypothesis: Normalized templates and character/word TF-IDF similarity expose recurring families across unclassified documents. Similarity grouping adds useful review coverage beyond exact templates. This is weakened if groups mostly reflect generic tokens, opaque identifiers, or unrelated document types.

Arms: Exact normalized templates (baseline); weighted character 3–5-gram and word 1–2-gram TF-IDF with cosine similarity groups; HDBSCAN as an exploratory comparison. Preserve ungrouped records.

Cases: Freeze the current public catalog selection and verify the matching local Parquet pair. Select grouped document records with no document kind, retain literal filenames, source IDs, document IDs, URLs, and scoped publisher evidence. Account separately for metadata/capture records, missing names, and opaque names. Counts are not assumed to equal the conversational estimate of 7,500.

Held constant: The frozen input, normalization, and features. No source document downloads, classification changes, publication, or rule adoption. Fixed random seed 42 where needed. Bound: one complete run of each arm, plus repairs for correctness; review up to 25 leading groups and a deterministic sample of the tail.

Decision rule: Rank groups by distinct-document coverage, descriptive content, and within-group similarity. Inspect representative and unusual members before proposing document kinds. Recommend a method only with its observed grouping coverage and review limitations. Group membership is not a verified kind. If existing context cannot establish a kind, specify the missing evidence. Report group overlap rather than adding overlapping coverage counts.

Validation: Verify immutable source hashes and catalog IDs; reconcile every selected document with exactly one primary review disposition; preserve all group memberships and examples; check normalization against date, bill-reference, opaque-ID, and generic-name counterexamples. No precision/recall claim or automatic classification rule without independently reviewed labels and held-out evaluation.

## Scope reconciliation and recorded settings

The published selection contained 53,222 distinct nonempty preferred filenames across 657,103 unclassified document groups. The estimate of 7,500 was not reproducible without an additional filter. A clarification was requested; the run proceeded across the named population with media/generic groups accounted for separately. No Congress or saved-only filter was silently assumed. Another 99,866 unclassified document groups have no preferred filename and cannot enter filename NLP.

Actual settings: 65% character and 35% word TF-IDF; minimum anchor cosine 0.72; at most 40 nearest lexical strings per anchor; HDBSCAN with minimum cluster size 5 and minimum samples 3 after 50-dimensional SVD, seed 42. These are exploratory settings, not tuned on verified kind labels. Similarity groups use a shared anchor rather than transitive chains. All source names are preserved; identical normalized lexical strings are weighted once during clustering.

Interpretation note: The descriptive bucket means a filename has remaining alphabetic text, not that its document type is interpretable. It includes opaque acronyms and metadata names such as dip.xml. Rank and review must therefore consider format and source context. Document IDs are catalog groups, not a guarantee of unique underlying content.

Additional diagnostic: Seven illustrative filenames were passed to the current local filename extractor after grouping to check whether obvious patterns were already classified. All seven returned no kind. This selected probe is not a corpus-wide parser evaluation and did not change the catalog.
