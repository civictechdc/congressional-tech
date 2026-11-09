---
id: ct-gfo7
status: open
deps: []
links: [ct-3aap, ct-zs48]
created: 2026-11-09T23:05:48Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [congress_api, mods, witnesses]
---
# MODS record-entry residuals for the next MODS bump (after ct-zs48, ct-3aap)

Left over from the three reviews of claude/ct-mods-zs48-3aap (2026-11-09). None is a regression and none blocks that branch. Items 1-4 and 6 change appearance_records.py, a byte-hashed parser file, so take them in ONE intentional MODS bump, not one at a time. Rows below are as read in the m7 candidate (MODS pin 0b58c1a2), checked with DuckDB against candidate-generation.parquet; whether the live release reads them the same was not checked.

1. Wrong fields. CHRG-115shrg24586 #2, raw 'Shulkin, Hon, David J., M.D., Nominee, Secretary, U.S. Department of Veterans Affairs' (the print has 'Hon,' with a comma), reads name 'Shulkin', position 'David J.', organization 'M.D., Nominee, Secretary, ...'. Smallest fix: one sha-bound MODS_PERSON_FIELDS entry.
2. Heading as a name. CHRG-115shrg24586 #4, raw 'Response to posthearing questions submitted by: Hon. Jon Tester......49,55 Hon. Jerry Moran', is a statement_for_record row whose name is the whole heading. Line 3 of the same print (the same askers, no heading) is record_material named Jon Tester. Run-on heading whose tail the rule rejects.
3. Dropped line. CHRG-115hhrg25242 #2, raw 'Responses to questions for the record from the following Representatives: Hon. Frank A. LoBiondo of New Jersey, submitted on behalf of Hon. Paul Mitchell of Michigan', publishes no row. Decide: a record_material row, or leave it dropped and say so.
4. Type a little loose. Two statement_for_record rows are the testifying body's own document, and the type means 'submitted by someone who did not testify': CHRG-110shrg75166 #3 'The Federal Trade Commission, prepared statement' (Kovacic and Leibowitz of the FTC testified) and CHRG-114hhrg93962 #11 'National Commission on Hunger, submitted report' (its co-chair Chilton testified). Neither has a name, so no witness is lost. Decide: record_material, or keep.
5. Shared blind spot (test only, no bump). After a question heading, a Member-style witness line ('Hon. Jane Doe, a Representative in Congress from the State of Ohio', 'Doe, Hon. Jane', a bare 'Hon. Jane Doe') would be typed record_material, and the raw check would also count it an asker. 0 such lines in 35,019 prints; all 31 lines typed only by the carried state are real Member askers. Add a regression test on a Member Day shape, or record the accepted risk.
6. Plainness. Question headings are recognised in three places (the 'responses to ... questions ... by/from' clause of _RECORD_OPENING, _MODS_QUESTION_HEADING, and the 'answers to questions' phrase skip); fold them or say in a comment which serves what. MODS_JOINED_LINES separators are regexes unpacked into two parts, so a pattern with a capture group raises at unpack; one comment.
7. Raw check weakness. In scripts/measure/mods_name_fields_raw_check.py the paged-asker clause of question_asker_as_witness has the rule's own shape, so it is close to a restatement. Give it a measure the rule does not use.

Evidence: <main checkout>/.cache/archive-release/implementation/mods-zs48-3aap-20261109/ (review-r2/findings.txt, r2_survey.txt, r2_survey2.txt; review-r3/findings.txt; fix-r3/m7/candidate-generation.parquet).

## Acceptance Criteria

Items 1-4 each applied or declined with a stated reason; at most one MODS bump (publish-model.json parser_versions, publish.json model_spec pin, pinned test hash); item 5 has a test or a recorded risk decision; the raw check is re-run on the new candidate with a planted wrong value confirmed by a reviewer other than the rule's author.

