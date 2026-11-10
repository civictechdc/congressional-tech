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


## Notes

**2026-11-10T12:21:00Z**

2026-11-10 bump (MODS pin 0b58c1a2 -> e39e365b, owner decisions on joint askers and titles; measured as m8 on all 35,020 originals). Item 1 APPLIED: one sha-bound MODS_PERSON_FIELDS entry reads Shulkin as name 'David J. Shulkin', position 'Nominee, Secretary', organization 'U.S. Department of Veterans Affairs'. Item 2 APPLIED: CHRG-115shrg24586 #4 is a reviewed MODS_RECORD_ENTRIES entry naming both askers (Jon Tester, and Jerry Moran at /part[2]), record_material; the heading no longer publishes as a name. Item 3 DECLINED, left dropped: CHRG-115hhrg25242 #2 publishes no row in release 619db5f9e08e either, so nothing a reader sees is lost; a row needs an owner call on who asked (LoBiondo submitted on behalf of Mitchell: one asker with on_behalf_of, or two rows). Item 4 DECLINED, kept statement_for_record: both rows keep their organization text and have no name; ct-3aap records that the model treats the record types alike, so retyping would add two reviewed entries for a label only. Item 5 APPLIED as a test, no bump: test_a_member_printed_right_under_a_question_heading_reads_as_an_asker pins the known limit and where the list ends; accepting the risk itself stays an owner call. Item 6 APPLIED as comments: which of the three question-heading readings serves what (appearance_records.py, above _MODS_QUESTION_HEADING), and why a MODS_JOINED_LINES separator must not hold a capturing group (mods_person_fields.py). Item 7 DECLINED here: it needs a new independent measure in the raw check and its own plant confirmed by a second reviewer; it touches no parser byte, so it does not need this bump. Not in the list, same kind, unchanged and not shown in the live release either: CHRG-115shrg25981 #4 (Bill Cassidy, the next heading's asker, run into Patty Murray's line) and CHRG-112shrg25114 #3 (Boxer and Inhofe, a nameless heading row).

**2026-11-10T13:46:44Z**

Round 2 (2026-11-10). Item 3 APPLIED (owner: 'show it as submitted material, both names'): CHRG-115hhrg25242 #2 is record_material Frank A. LoBiondo and Paul Mitchell (/part[2]). Item 4 APPLIED (owner: 'label them record material'): the testifying body's own statement is record_material, organization kept; a survey of all 37 organization-only statements found exactly 3 whose organization a named witness of the print testified for: CHRG-110shrg75166 #3 (FTC), CHRG-114hhrg93962 #11 (Hunger Commission), CHRG-107shrg81998 #23 (ACLU, president Nadine Strossen testified); sha-bound 'document' entries. Item 5 NOT BUILT, options reported (owner asked to stop if no separating fact is right in principle): the 31 carried asker lines share every line shape with Member Day witness lines (3 print 'a Representative in Congress from', none carries page numbers); GPO sets no congMember role=WITNESS in any of the 35,020 originals (1,028,164 COMMMEMBER, 149 SUBMITTEDBY, 0 WITNESS), so that fact never fires (the parser's WITNESS bioguide link is dormant for MODS); committee membership misses 5 of the 31 askers (Rockefeller x3, Jeffords x2). The principled fact is the meeting's own witness list, which the model already applies (witness-precedence.sql supersedes a print statement for someone the meeting's list names); it reaches 12 of 187 named record rows today. Item 7 APPLIED in the raw check: member_unnamed, record_as_witness, person test on restored names, committee titles, signed per-row accepts with line sha256; six new built-in plants, run by the author only, need a different reviewer. Candidate accepts (96, unsigned): round-2/m2-accept-candidates-m10.json.
