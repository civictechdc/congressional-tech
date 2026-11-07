# Recovery policy: verified originals with continuing updates

The current output needs an explicit recovery policy and its exact requirements
file. The application now refuses a missing file or a prepared capture profile
that does not match it. The required fields and acceptance checks remain intact.
The human selected: **“Include verified recovered originals and keep checking
for updates.”** For the selected historical recovery cohort, this means
`historical_exact` plus `refresh_live`. Its boundary is all 24,028 distinct
literal original targets in the two pinned historical recovery files. This is
an explicit selected cohort, not a census of every missing archive document.
The maintained planner has bound the complete cohort. Candidate acceptance remains
pending.

The maintained policy is `recovery-identity-v1`. A requirements row names one
literal `original_url`, its `target_requirement`, that `acceptance_policy`, and
an explicit `refresh_policy`. The existing campaign planner writes this shape;
the migration does not need another planner or controller.

## What the selected inputs establish

The frozen `ab97bb17` publishing specification pins eight native snapshots. It
does not select `recovery_files` or `recovery_requirements`. Its retained prepared
recovery input contains zero records: the original 50-byte compressed file
decodes to zero bytes, with unchanged recorded custody and SHA-256. This explains
the staged request; it does not establish that the archive has no recovery
evidence or that an empty production policy was intended.

Exact selectors, source identity and the bounded check are recorded in
[`policy-input-facts.json`](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ddk-replacement-20261106/capture-policy-correction-01/policy-input-facts.json).
No native table, source body or published data row was read for this decision.
The local removal-notice, ct-rie2 and combined-cause campaign files belong to
other work; none was substituted into this release.

A subsequent authorized discovery read verified the two original recovery files:
19,657,343 bytes and 24,085 historical decisions. All 57 superseded IDs resolve;
the files name 24,028 targets and 20,245 bodies. None carries version-2 acceptance
or qualification fields. Historical `recovered_document` labels therefore do not
establish acceptance under the selected policy. The bounded read took 1.01 seconds
and peaked at 92.9 MiB process RSS. Its exact pins, counts and limits are retained
in [provenance discovery](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ddk-replacement-20261106/recovery-policy-selected-01/provenance-discovery.json).

Source metadata establishes the selected captures snapshot as a direct append
descendant of the earlier audit snapshot, with 12 additional rows. That ancestry
does not identify those rows or prove recovery membership. The bounded native
query now verifies 11,596 active decisions against 12,391 complete retained
captures, preserving 12,432 unmatched decisions and 678 decisions with multiple
capture rows. Of those matches, 11,173 targets have the historical
`recovered_document` label; 423 have other relationships. Both complete outputs
fit the declared caps. The run took five seconds and peaked at 0.516 GiB sampled
RSS; [the retained result](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ddk-replacement-20261106/recovery-policy-selected-01/capture-membership-01/handoff.json)
records the exact inputs, checks and independent reviews. It read receipt metadata
only. Its `retained_import` filter does not establish absence of a usable direct
document. Selected capture membership, missing-target census and accepted-original
qualification remain distinct checks. The selected cohort includes every matched
and unmatched target; membership in this cohort does not require a missing-direct
finding. All 480 other relationships keep their original meaning.

The exact historical mapping named by those decisions was also recovered and
hash-verified: 24,028 rows in 9,638,187 bytes. Its original bytes and backup receipt
are retained beside the discovery evidence. It supplies literal target/candidate
URLs, body keys, format, basis and status. Those fields preserve historical
provenance; they do not supply current source-native identity or qualification.

## Selected behavior and input binding

| Selected field | Value | Effect |
| --- | --- | --- |
| Required recovery meaning | `historical_exact` | Require a verified recovered original, using the maintained `recovered_document` relationship and accepted evidence. |
| Continued acquisition | `refresh_live` | Keep the official target eligible for ordinary refresh even when a verified recovery exists. |
| Acceptance rules | `recovery-identity-v1` | Require the maintained identity, body qualification and complete-import checks. |

The parent chat conveyed the explicit human choice on 2026-11-07. It authorizes
scoped local implementation and qualification, not publication, production pin
promotion or unbounded acquisition. The maintained campaign planner must emit
one row per selected literal target from pinned historical target and candidate
inputs. All original provenance remains bound, including superseded source
decisions and relationships that do not satisfy `historical_exact`.
A file path alone is insufficient: the final selection must name its SHA-256,
byte size, policy identity and matching provenance population. The old empty
staged input is not the chosen population. Unrelated campaigns cannot substitute
for a missing release binding.

The requirements file can be generated while candidate acceptance remains
pending. The maintained inventory receives the complete literal target population
and explicitly unresolved direct-capture history and qualification. Its planner
then records the selected obligations using explicitly supplied candidates.
Neither the matched subset nor a claim that every target lacks a direct document
defines this boundary. Retained imports cannot stand in for ordinary direct-capture
history. No archive-wide census or source fetch is needed to author these
requirements.

The bounded preparation reused the completed 24,823-row membership table. One
native materialization removed capture multiplicity while preserving every active
decision's fields and original source line. The descriptor pins those decisions
and the full membership table beside the target and candidate tables. The final
receipt also binds all 24,085 original source records. Decision, distinct literal
target, target/body-pair and target/candidate-pair counts are checked separately.
The maintained planner produced one unresolved ledger row and one explicit
requirement per target. It created no version-2 acceptance.

The resulting requirements contain 24,028 rows in 204,427 bytes, SHA-256
`d7dbf6a186cb69b867bfdada4f1c22981659a3a409206db791c1534ac7fde245`.
The two-call run completed in 2.8 seconds at 0.493 GiB peak sampled RSS. Independent
review reconciled its native output pins, all planner counters and preserved
source arithmetic, and found no surviving process. The
[acceptance receipt](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ddk-replacement-20261106/recovery-policy-selected-01/policy-materialization-01/acceptance.json)
binds the exact inputs, jobs, results and pending obligations. No source body or
remote data was read during this preparation.

For a campaign, the maintained rules offer these meanings:

| Field value | Meaning |
| --- | --- |
| `historical_exact` | Require the recovered original document. |
| `requested_content` | Also accept the specific maintained relationships that contain the requested content. |
| `current_official_counterpart` | Also accept the maintained current-counterpart relationships. |
| `historical_only` | A qualified satisfying recovery may stop acquisition for this target. |
| `refresh_live` | Keep the target eligible for normal refresh, even when recovery evidence exists. |

Requirement level and refresh intent express the owner's purpose; they cannot
be inferred from a filename, HTTP status, snapshot summary or missing policy.
Campaign authoring can default unstated refresh intent to `refresh_live`, but
the resulting model input must contain that explicit value in every row.
The target-inventory helper has a different default (`historical_only`), so
this selected campaign must pass `refresh_live` explicitly and verify the
emitted values.

## What the existing checks include and refuse

The model preserves the literal URL and requires a supported requirement,
matching policy identity, explicit supported refresh value and exactly one
requirements row per URL. It refuses missing or invalid values and duplicates.
It does not require every URL in the archive to belong to a recovery campaign.

A satisfied URL additionally needs one active, accepted version-2 decision,
matching requirement and policy, valid evidence and qualification identities,
an allowed relationship, and a complete retained import with the matching body
identity. Superseded, ambiguous, mismatched, unqualified and live-refresh cases
remain eligible; scope exclusions remain excluded. HTTP history stays unchanged.
Repeated captures cannot multiply a decision.

The requirements file controls capture eligibility; it does not itself qualify
viewer content. Count verified originals from accepted import/decision evidence
and exact selected capture/body membership. The planner's `accepted_recovery`
disposition depends on `satisfied` URL state, so it cannot count accepted
originals that deliberately remain eligible under `refresh_live`. Existing
historical recovery rows retain their own evidence and meaning; selecting this
policy does not rewrite them or establish their qualification.

The policy-bound profiles, complete model job, local-file inventory, report policy
and enclosing adoption-definition draft have been regenerated. This
[successor handoff](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ddk-replacement-20261106/producer-authority-policy-02/final-handoff.json)
contains 52 inputs, 253 steps, 40 outputs and 23 reports, with 225 authored required
counters in seven reports. Its 44 local inputs include both original provenance
files and the requirements. The eight native selectors, observed schemas,
unchanged prepared inputs and successful proof-schema evidence are reused.
The refused 51-input request remains intact. Native schema inference for the
successor completed without input admission or row execution. It preserved all
eight observed native schemas and all 225 required counter names and types.
The old authored nullability expectations differed for 217 fields. The
[maintained policy successor](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ddk-replacement-20261106/producer-authority-inferred-03/handoff.json)
binds the inferred schemas while preserving the rule that every actual counter
must be a non-null integer zero. Producer adoption and model execution have not
run.

Metadata generation completed in 3.3 seconds at 0.199 GiB sampled RSS. Its first
attempt stopped at a missing caller-created control directory; the failed log
and partial artifacts remain in `attempt-01`. Creating that required directory
fixed the caller. The two attempts produced identical model JobSpec bytes.

Source owners: `corpus_recovery.acceptance`, `corpus_recovery.campaign`,
`viewer_publication.archive_url_state`, and `archive_model_job`. Native admission,
producer proof and publisher activation remain separate acceptance boundaries.
