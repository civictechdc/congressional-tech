# Exhaustive shared-token boundary check on the retained corpus

Decision: close the untested negative space in the shared-token regex inventory.
The existing gate checks all expected token/rule pairs and selected boundary
controls, but does not evaluate rules against filenames where their token is
absent from the expected lexer output.

Hypothesis: the generated regexes match exactly the independently tokenized
word, ASCII number and ASCII CamelCase-part spans for every retained filename.
Compare the House generator to the frozen native generator on every saved rule.
Then compare regex matches to a character-based lexer that imports neither
production tokenization helper nor its boundary regex.

Avoid an unnecessary 88,227-by-333,368 brute-force loop by indexing each literal
variant in a prefix tree. Check every literal occurrence, including occurrences
inside larger words and numbers, with the actual compiled regex. This pruning is
valid only after verifying that each serialized rule consumes exactly one of
those literals and that its surrounding expressions consume no characters.
Reject unsupported pattern shapes rather than assuming the index covers them.
Compare the indexed execution to direct all-rule scanning on a bounded sample
and constructed counterexamples before using it for the full corpus.

Success requires every shared rule to match the saved declaration and native
generator, no missed or extra spans on all 333,368 inputs, no new dependencies,
and hashes tying the run to exact inputs and implementations. Verify the
independent character classification across Unicode code points. Include weak
boundary controls, matching substrings inside words/numbers, repeated tokens,
Unicode letters, case variants and query/extension exclusion.

Use the accepted `native-refinements` extraction and `bracket-numbers-corpus`
rule inventory. Preserve the existing stem boundary as an input to this check;
this experiment does not independently requalify extension/query parsing. It
tests literal token recurrence, not document categories or semantic meanings.
Retain failures. Start with 1,000 corpus names to measure cost, then run the
full check if it fits a 30-minute execution bound and 1 GiB of new artifacts.
Use a 1,000-name benchmark only for execution cost, never as full-corpus proof.
