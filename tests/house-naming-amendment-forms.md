# Preserve explicit amendment-form wording

Decision: expose recurring preamble, resolving-clause, title and substitute
amendment phrases that currently remain only inside free text.

Hypothesis: one supplemental catalog rule can retain these exact phrases without
changing any prior readings, assigning an official amendment number, or declaring
the document's contents verified. The native parser and current House parser both
miss this finer wording in observed examples such as
`S. Con. Res. 10 Preamble Amendment.pdf`.

Arms: accepted `native-refinements` extraction, frozen native/strict `drafts-final`
comparison, and the proposed rule. Keep the complete 333,368-filename corpus,
adapter and comparison tools fixed. This is reused development data.

Before editing production code, inventory every candidate and its existing field
ownership; retain exact expected additions and excluded cases. Review source
associations for representative forms. Capture the whole literal phrase as
`label`. Existing manager's-amendment labels and concrete person/amendment slots
must remain intact. An overlapping `amendment_marker` can coexist with the longer
phrase; amendment identifiers cannot be reinterpreted. Do not infer authorship,
passage, current bill status, or exclusive document categories.

Include word-fragment, Unicode, percent-escape, query, numbered-reference,
repeated-phrase and protected-slot controls. Preserve spelling, separators and
exact spans. No new dependencies, downloads, classification engine or source-code
copy is needed.

Accept only the pre-reviewed additions, with every prior complete extraction
otherwise identical and all focused, full-suite, corpus, typed-adapter, strict
and native-omission checks passing. Preserve failed trials and investigate any
unexpected change. Each full run has a 30-minute bound; stop this experiment once
the decision is settled.
