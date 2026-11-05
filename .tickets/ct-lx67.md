---
id: ct-lx67
status: open
deps: []
links: [ct-dx22]
created: 2026-11-04T15:07:16Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [parser, witnesses, organizations, publication, chaos-test]
---

# Keep a witness’s full job title and correct employer together

Witness searches and employer groupings should use the affiliation the source supplies. In `e145d24c389e`, Thomas L. Farmer and Raymond J. Reese have fragments of their titles published as employers. The retained print `CHRG-112hhrg72238` identifies the Association of American Railroads and Colonial Pipeline Company, respectively.

## Root cause (2026-11-05)

The exact retained GovInfo metadata (MODS) contains both full affiliation lines. The earlier `witness_names.py` helper treated the first comma after the name as the title boundary, and the MODS caller accepted that split. The wrong employer is already present in the retained parsed appearance, before publication. The MODS version hashes this helper. At the time of the audit, the Senate page parser used the helper for plain witness lines and omitted it from its version. The audit found a missing version dependency. A published impact from a later helper edit remained unverified.

## Implementation and remaining checks

The first-wave merge `18049548` includes the MODS affiliation fix. It keeps a supported title and employer together and retains ambiguous wording in the source record. The exact staged rows show Farmer’s full security, safety and operations title at the Association of American Railroads and Reese’s corporate health, safety and security title at Colonial Pipeline Company. Reese’s record also names the Association of Oil Pipe Lines and the American Petroleum Institute as the groups he represented. The focused parser and producer checks passed 86 tests.

The MODS appearance pin advanced from `6288a5f5` to `1775aa40`. The independent replay check covers all 35,020 MODS records and found 4,835 witness lists with changed values and the same number of entries. The combined replay evidence is linked from [ct-kthe](ct-kthe.md).

After the build hold clears, the release coordinator will verify the imported pin and both corrected witness records in `witnesses.parquet` and the installed MCP. The separate sitting repair owns the old hearing-key disposition. [ct-dx22](ct-dx22.md) · [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md)

## Acceptance Criteria

- Recover the complete source-supported titles and the respective employers for Farmer and Reese, with Reese’s supplied representative context. Use independently read source facts to check a normal line, a comma-containing employer and an ambiguous line as well as the two failures.
- Publish corrected fields in `witnesses.parquet`. Preserve source occurrences and their keys when only attributes change. Leave person matching and organization aliases to their existing owners.
- Record the actual source-version changes, replay scope and authoritative lake/catalog pin. Verify the corrected fields in produced output and read both witnesses back through the installed selected release.

## Coordination and evidence

The checked witness keys are `c91a7472a2a51731` and `9fb4f01557e8b8b6`. The held PDF SHA-256 is `19397c330522ea962c88017f1e8bf496effc66fbaf306924f5fbb950d7cf11c8`. The PDF and independent reading are in `.cache/archive-release/chaos-personas-20261104/` as `CHRG-112hhrg72238.pdf` and `source-case-audit.json`. The appearance version and caller evidence is in the [root-cause analysis](../docs/plans/production-mvp-root-causes-20261105.md).

Share the source and final release where practical. The separate sitting fix owns any occasion change and resulting key change. [ct-dx22](ct-dx22.md)

## Notes

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Owner: shared GPO witness field parser packages/congress_api/src/congress_api/parsers/witness_names.py:132/160-161 and its MODS appearance caller. Preserve the complete Farmer/Reese titles and source-supported employers; preserve on-behalf-of context and raw ambiguous evidence. Do not introduce institution alias/person matching or caller-specific SQL cleanup. Add cases to maintained tests for comma-in-title, comma-in-employer, a normal line and an ambiguous line, checked against independently read retained source.

Exact invalidation matters: appearance_records.py:212-228 hashes witness_names.py in the MODS source version; the other source-scoped branches at 230-275 do not hash that helper. A helper-only edit should change MODS alone, but measure the actual digest closure after edits; shared schema/producer changes may broaden it. The two discovered rows are not an exact selective-replay predicate. Carry unaffected rows forward/re-stamp only after proving a complete affected-input predicate; otherwise replay existing MODS candidates from retained bytes under the new family pin. Select one pinned version per (record_sha,source) before interpretation and preserve literal sources/occurrence multiplicity.

Attribute-only corrections keep occurrence keys when body/locator/context/occasion stay equal. If ct-dx22 separately changes occasion, record those key/link changes as its reviewed cause, not this parser's identity policy. Parser fixtures/replay planning can run in parallel with model-only fixes; coordinate the final MODS pin/model-spec hash and authoritative lake/catalog input once. No new raw acquisition, full-source replay by default or engine change. Closure requires produced field parity and actual selected-release readback, not parser-only evidence.

**2026-11-05T20:18:06Z**

Integrated the MODS-local affiliation repair. The full bounded MODS replay completed 35,020 rows; independent comparison found 4,835 changed lists with no cardinality changes. Farmer and Reese preserve their source-supported roles and employers. House/Congress rows remain identical. Native import and final selected-release checks are held for the combined waves.
