# Recovery policy: production choice still required

The current output needs an explicit recovery policy and its exact requirements
file. The application now refuses a missing file or a prepared capture profile
that does not match it. The required fields and acceptance checks remain intact.
No production policy or requirements population has been selected.

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

## The decision to make

| Choice | Concrete resulting requirements | Effect |
| --- | --- | --- |
| Select the intended recovery campaigns | The maintained campaign planner emits one row per selected literal target, using pinned target/candidate inputs and the owner's chosen requirement and refresh intent. Matching recovery provenance joins the model inputs. | Qualified recovery can satisfy those historical targets. |
| Explicitly select no recovery campaigns for this release | Zero requirements rows and no recovery provenance, both expressly selected by the owner. This matches the current staged input population but is not inferred from it. | No URL is marked satisfied by recovery; existing scope exclusions and ordinary refresh remain active. |

Neither choice has been adopted. A file path alone is insufficient: the final
selection must name its SHA-256, byte size, policy identity and the matching
provenance population. A production requirements Parquet file has not been
generated from this draft.

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

Once the owner selects the input, regenerate the policy-bound profiles, complete
model job, local-file inventory, report policy and enclosing adoption definition.
The expected graph is 52 inputs, 253 steps, 40 outputs and 23 reports, with 225
required counters in seven reports, subject to native inference. Reuse the eight
original selectors, observed schemas, unchanged prepared files and successful
proof-schema evidence. Preserve the refused 51-input request and its receipts.

Source owners: `corpus_recovery.acceptance`, `corpus_recovery.campaign`,
`viewer_publication.archive_url_state`, and `archive_model_job`. Native admission,
producer proof and publisher activation remain separate acceptance boundaries.
