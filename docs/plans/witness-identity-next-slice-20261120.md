# A witness’s role at one appearance

On November 20, 2026, a manual review of eight witness-linked House biographies in release `0e7084cde775` supported seven role attributions. One attachment named a different person. The bounded next slice is a reviewer’s record of a role stated in an archived biography, attached to one appearance. The first consumer is a congressional-tech identity reviewer investigating a possible correction. The qualification ledger is the first batch.

## What the reviewer records

1. Start from a published appearance with a live `witness_key` and a linked `witness-biography` document in `detail.parquet`. Open the archived text for that document’s body digest. The witness row supplies the occasion, record digest and source locator. The document has its own key and body digest.
2. Read the subject and the passage that states the role and organization. Check the full name, stated initial or suffix, organization in context, and time relative to the hearing. A filename, reciprocal document link or matching agency alone cannot establish the subject. Treat a former office, cited author, client or represented association according to the language of the source.
3. Accept a fact only when the text identifies this appearance’s subject and states the role. Retain the release, witness and observed person keys, record digest and locator, occasion, document key and digest, text parser/version and text digest. Record the exact subject and role spans as half-open UTF-8 byte offsets into that text, with their verbatim contents. The date describes what the source supported at the appearance. Extending a role to another occasion requires evidence there.
4. If the attachment names someone else, the role is unclear or the evidence supports multiple people, record an unresolved outcome and its reason. An unresolved item contributes no role. A re-extraction with different text bytes needs new spans and review.

## Three options tested on the release

| Option | Source read | Decision |
| --- | --- | --- |
| Role at an appearance | The 2015 Howard Shelanski biography names his current Office of Information and Regulatory Affairs post and separately dates his former Federal Trade Commission office. | Qualify the current role for the 2015 appearance. A time-scoped source fact can be checked without changing a person key. |
| Reviewed organization aliases | Two Lee Zeldin biographies name the same federal agency and the same swearing-in date. The appearances use different organization spellings and have different person keys. Two hearing prints expand “ABA” to different organizations. | Feed reviewed equivalents from the organization plan into the reviewer’s affiliation context. Keep the source field, review evidence and organization ID. A bare acronym remains ambiguous. |
| `possible_same_person` across organizations | Shelanski’s 2015 biography dates the earlier FTC job that the 111th Congress hearing identifies. Two witnesses called Robert Smith both worked in law, but the biographies supply no comparable bridge. | A reviewer could flag the Shelanski pair as uncertain. Retain both appearance keys, evidence on each side, the reason for the suggestion and the unresolved status. Leave the two lawyers unresolved. Defer producing candidate lists. |

The existing person rule still groups Members by Bioguide ID and other eligible witnesses by exact normalized name and full organization. Its middle-initial and suffix rules keep competing stated values apart. An organization alias supplies context only. Neither an alias nor an uncertain pair can write a `person_key`, create a redirect or participate in a transitive group. SpicyRegs can cite a congressional-tech appearance for a separate cross-source decision.

## Qualification and wrong-identity controls

The review used the seven accepted biographies for Robert Smith at Brigham Young University, Robert Smith at the San Diego VA, Robert Smith at the National Federation of Independent Business, Roger Pielke Jr., Howard Shelanski and two Lee Zeldin appearances. The eighth biography was attached to Laurie Hall. Four archived hearing prints provided separate comparison evidence. Each biography was joined by the current document’s witness keys. Each print was joined through the witness’s GovInfo package and read at the passage naming the witness.

| Proposed attribution | Evidence that decides it | Outcome |
| --- | --- | --- |
| Give the San Diego VA directorship to the BYU witness | The published appearances both say Robert Smith. Their own biographies specify Robert **M** Smith, M.D., and Robert **T**. Smith, a lawyer. Their career histories overlap. | Reject the swap. |
| Combine the two Roger Pielkes on their Colorado affiliation | The biography names Jr. The print identifies Sr. as a senior research scientist. Both name the University of Colorado. | Reject the merge. |
| Assign the bankers’ organization to William Shepherd from “ABA” | The print identifies Shepherd as a member appearing for the American Bar Association and a partner at Holland & Knight. Edward Yingling’s print spells out American Bankers Association. | Reject the organization substitution. |
| Apply the 2015 administrator role to Shelanski’s 111th Congress appearance | The earlier hearing introduces an FTC deputy director. The 114th Congress biography identifies him as administrator and dates his earlier FTC service to 2009–2011. | Reject the role transfer. Retain the two dated sources. |
| Give Laurie Hall the Government Publishing Office directorship | The release links the biography to Hall, and its filename says Hall. The text names Hugh Nathanial Halpern as director. | Withhold the fact. The attachment’s subject remains unresolved for Hall. |
| Identify the BYU and NFIB lawyers as one person | Their published names and profession agree. The NFIB biography supplies no matching middle initial or prior BYU role. | Unresolved pair. |

The reviewer accepted **7 of 8** biography facts and accepted **0 of 5** deliberately wrong proposals. One biography and one additional possible-person pair remain unresolved. The slice made **0 person merges and 0 false merges**. These are counts for a purposive case review by one reader. They qualify the review procedure on these cases. They do not estimate corpus-wide accuracy.

Two lookups reproduce the acceptance boundary. For Shelanski, witness `ea3c178e609c773d` links to document `0b6776c44b88c87b`. Bytes [0, 19) name the subject and [20, 118) state the office. For Hall, witness `c296c1036831a501` links to `1bc2131f1721fd6f`, but bytes [0, 22) name Halpern. The ledger identifies the exact text digest in each case.

## Corrections, access and replay

The reviewer can start at the existing Explorer `?person=` page or call `get_entity` on `people`, then inspect the linked witness and document. The current person corrections are accepted or revoked entries in `model/registries/person-decisions.json`. A reviewer who establishes a merge, split or hide uses that process, retaining the evidence and historical keys. The model carries aliases in `person_aliases.parquet`. The site and API follow unambiguous aliases and surface ambiguity or unresolved keys. A role correction revises the source annotation with the original release and evidence retained. It does not authorize a person correction.

The baseline is the joint witness plan, sections 2 and 6, and the person identity draft, section 7, under `.cache/archive-release/investigations/`. The `ct-ha10` closeout records a separate check on risky groups and 200 random people, including a planted false merge. This qualification reuses that infrastructure. It covers document attribution and deliberately wrong roles, affiliations and identities. The batch required no new acquisition, public table or automated text extraction.

The machine-readable ledger is `<main checkout>/.cache/archive-release/long-tail-20261120/senate-id/ct-kt2o-qualification.json`. Its cases include full source and text digests, exact offsets, quotes and live keys. From this checkout, run the adjacent `read_identity_sources.py` with the archive watchdog and then `qualify_identity.py` with the worktree Python. The first reads locally retained text by the full body digests in the release. The second verifies the document and appearance joins, checks every text digest and reconstructs every span.
