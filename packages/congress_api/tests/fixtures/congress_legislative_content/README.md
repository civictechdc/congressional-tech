# Congress.gov legislative wrapper fixtures

These gzip files preserve complete retained publisher pages. Their SHA-256
identities after decompression are pinned in `test_congress_legislative_content.py`.
No download occurred during this change. The accompanying text files are actual
outputs of `congress-gov-legislative-wrappers/002`, read in full against the complete
legislative body and its exact selected fragment before becoming expected files.

| Fixture | Source | Direct review |
| --- | --- | --- |
| `pl118-68` | Congress.gov H.R. 1240, 118th Congress, Public Law 118–68 | Both sections, all three tract descriptions, gaming prohibition, approval and legislative history |
| `hr1709-engrossed` | H.R. 1709, 111th Congress, House engrossed June 8, 2009 | Three sections, nested strategic-plan and annual-report clauses, Clerk and repeated endorsement |
| `hr3916-introduced` | H.R. 3916, 110th Congress, introduced October 22, 2007 | Sponsor list, six complete sections, all nested research/report clauses and original preformatted lines |
| `hres487-engrossed` | H.Res. 487, 110th Congress, House engrossed July 16, 2007 | All whereas clauses, eleven examples, seven benefits, seven resolved clauses and Clerk |

The durable source/candidate review is under the main checkout's
`.cache/archive-release/ocr-recovery-20261113/repairs/corpus-assessment-20261113/triage-current-20261114/ct-g4yz-wrapper-selection-20261115`.
It also preserves a deliberately incomplete public-law output missing the whole
gaming prohibition for independent review. The 3 MB H.R. 2500 preformatted example
stays there: its full byte span and layout are checked mechanically, but only
declared opening, interior and closing contexts were read manually. These fixtures
do not establish whole-corpus acceptance or coverage of other wrapper families.
