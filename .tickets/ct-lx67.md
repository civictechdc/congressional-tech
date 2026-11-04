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
# Keep comma-containing job titles out of witness.organization

On live release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd, two MODS-derived witnesses in CHRG-112hhrg72238 have job-title fragments published as their organization. Thomas L. Farmer (witness_key c91a7472a2a51731) has position='Assistant Vice President for Security' and organization='Safety, and Operations, Association of American Railroads:'. Raymond J. Reese (9fb4f01557e8b8b6) has position='Corporate Health' and organization beginning 'Safety, and Security Leader, Colonial Pipeline Company, On Behalf ...'. These fields silently fragment employer grouping and misstate affiliations in witness lookup. This is a parsing bug distinct from person deduplication, organization alias normalization and the same package's wrong-sitting attachment.

The independently read, hash-verified PDF contents (physical page 3 / printed III) states 'Assistant Vice President for Security, Safety, and Operations, Association of American Railroads' and 'Corporate Health, Safety, and Security Leader, Colonial Pipeline Company, On Behalf of The Association of Oil Pipe Lines and the American Petroleum Institute'. Body SHA256 19397c330522ea962c88017f1e8bf496effc66fbaf306924f5fbb950d7cf11c8; 524,902 bytes; immutable document link_key=19397c330522ea96 at the release above. Only these two witnesses were adjudicated; this is not a claimed corpus-wide error count.

Evidence: .cache/archive-release/chaos-personas-20261104/source-case-audit.json, independent-table-audit.json, pdf-source.json, pdf-page3.png and CHRG-112hhrg72238.pdf. Exact original live query and body requests: accountability/calls.jsonl calls 20 and 21. A separate current-endpoint check on 2026-11-04 at 14:50:10 UTC found Congress.gov and GovInfo serve the same archived PDF bytes (investigation-accountability/network-requests.json).

Read-only reproduction: SELECT witness_key,name,position,organization,source,source_locator FROM witnesses WHERE witness_key IN ('c91a7472a2a51731','9fb4f01557e8b8b6'); compare each title/employer boundary with the printed contents. Do not use first-comma splitting as an independent oracle.

## Design

Owning path inspected at checkout 730a2d8e0c55880fc058d13cc74d265fc315f41f: packages/congress_api/src/congress_api/parsers/witness_names.py:witness splits all commas at line 132 and returns rest[0] as position and the remaining fragments as organization at lines 160-161. packages/congress_api/src/congress_api/lake/appearance_records.py:1126-1144 uses this parser for MODS witness lines. The observed live split matches this mechanism; a byte-for-byte replay of the exact pinned MODS input was not performed in the investigation. Preserve publisher-native affiliation evidence, use structured source fields where supplied, and avoid guessing a title/employer boundary when evidence is ambiguous. Repair at the maintained shared parser/extraction owner rather than adding organization cleanup to SQL callers. Follow parser-version and affected-input qualification rules before publishing changed extraction semantics. No code, tests, data, pins or publication were changed when filing.

## Acceptance Criteria

- Fixed fixtures from the two named source lines retain the complete Farmer/Reese job titles as position and start organization with the actual employers (Association of American Railroads / Colonial Pipeline Company), preserving the supplied on-behalf-of context without treating job-title fragments as employers.
- Include a normal comma-free title, a comma-containing employer and an ambiguous source line; preserve raw evidence/uncertainty rather than inventing an organization. Independent source reading confirms the named boundaries.
- Explain required parser-version/input replay scope, preserve appearance identity and the separate date-assignment decision, and verify that the corrected fields reach produced witnesses.parquet.
- After qualification/publication, read both immutable witness references through the installed selected release and record the new release ID. Local parser tests or source changes alone are not live completion.


## Notes

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Owner: shared GPO witness field parser packages/congress_api/src/congress_api/parsers/witness_names.py:132/160-161 and its MODS appearance caller. Preserve the complete Farmer/Reese titles and source-supported employers; preserve on-behalf-of context and raw ambiguous evidence. Do not introduce institution alias/person matching or caller-specific SQL cleanup. Add cases to maintained tests for comma-in-title, comma-in-employer, a normal line and an ambiguous line, checked against independently read retained source.

Exact invalidation matters: appearance_records.py:212-228 hashes witness_names.py in the MODS source version; the other source-scoped branches at 230-275 do not hash that helper. A helper-only edit should change MODS alone, but measure the actual digest closure after edits; shared schema/producer changes may broaden it. The two discovered rows are not an exact selective-replay predicate. Carry unaffected rows forward/re-stamp only after proving a complete affected-input predicate; otherwise replay existing MODS candidates from retained bytes under the new family pin. Select one pinned version per (record_sha,source) before interpretation and preserve literal sources/occurrence multiplicity.

Attribute-only corrections keep occurrence keys when body/locator/context/occasion stay equal. If ct-dx22 separately changes occasion, record those key/link changes as its reviewed cause, not this parser's identity policy. Parser fixtures/replay planning can run in parallel with model-only fixes; coordinate the final MODS pin/model-spec hash and authoritative lake/catalog input once. No new raw acquisition, full-source replay by default or engine change. Closure requires produced field parity and actual selected-release readback, not parser-only evidence.
