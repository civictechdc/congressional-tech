---
id: ct-imdo
status: closed
deps: []
links: []
created: 2026-10-22T17:43:35Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-syem
tags: [congress-shared, source-fetch, congress-api, bug, duplication, deadcode, dx]
---
# Fix congress_shared auth.py sys.argv hijacking, copy_checked 4x full-RAM hashing, identical write_bound_receipt/write_atomic_json clones, and delete dead source-fetch benchmark.rs & 109 stale congress_api/build/ files

CS300 Audit Finding (Congress API, Shared & Source-Fetch Auditor):
1. Hidden sys.argv Hijacking in Library Auth Loader (packages/congress_shared/src/congress_shared/auth.py:6-13):
   - _load_api_key instantiates argparse.ArgumentParser(description='API Key Loader') and calls parser.parse_known_args() whenever api_key is None. Because add_help=True by default, calling load_congress_api_key() or load_youtube_api_key() in any process or test runner passing -h/--help hijacks stdout and calls sys.exit(0).
2. 4x SHA-256 Hashing & Unbounded Full-File RAM Read in copy_checked (packages/congress_shared/src/congress_shared/custody.py:375-407):
   - copy_checked calls verify_local_file(src) (streaming hash #1 at L388-392), immediately re-opens src and loads the entire file into memory via raw = b''.join(chunks) (L394-398) and hashes raw a second time (L399), then calls write_atomic_bytes(dst, raw) (L402) which hashes raw a third time (L250) and calls verify_local_file(dst) (L274, hash #4 on disk).
3. 100% Identical Cloned Functions & Duplicate Attributes in custody.py:
   - write_bound_receipt (packages/congress_shared/src/congress_shared/custody.py:284-312) and write_atomic_json (custody.py:315-343) have the exact same 10 parameters, defaults, return type (VerifiedFile), and 16-line implementation body.
   - VerifiedFile.__init__ (custody.py:93-97) stores duplicate alias attributes (self.pid/self.process and self.identity/self.custody) and registers every instance in a class-global WeakValueDictionary (custody.py:40, 98).
4. Dead Code in packages/source-fetch & Stale packages/congress_api/build/ Tree:
   - packages/source-fetch/benchmark.rs:1-249 (binary reqwest-fetch-bench in Cargo.toml:13-15), cases.json:1-27, and experiment.md:1-11 are a dead 2026-10-01 experiment ('No production adoption'), pulling in 3 Cargo dependencies unused by main.rs (base64 = '0.22' at Cargo.toml:24, dotenvy = '0.15' at L25, sha2 = '0.10' at L31). Also packages/source-fetch/main.rs:1-390 has zero /// doc comments on Request (L55-70), Response (L72-91), RateLimit (L28-53), or fetch_once (L145-305).
   - packages/congress_api/build/lib/congress_api/ (plus build/bdist.macosx-11.0-arm64/) contains 109 stale Python files (13,803 LOC) from 2026-09-30 (78 diverged from src/, plus deleted parsers/speaker_names.py:1-265 still cited in packages/congress_api/README.md:707).
5. Undeclared Dependencies, CLI Type Bugs & Cross-Package Utility Duplication:
   - packages/congress_shared/pyproject.toml:6 declares dependencies = [] while storage.py:108,144 imports boto3/botocore and re-exports S3 helpers in __init__.py:18-27 (contradicting packages/congress_shared/README.md:5,87 which claims __init__.py is empty).
   - packages/congress_shared/src/congress_shared/cli.py:32-38 (--channels-csv) and L55-58 (--output) register type=str with Path defaults, returning Path when omitted and str when passed; paths.py:9-15 sets DEFAULT_OUTPUT_DIR = PACKAGE_DIR / 'data' inside the source tree; globals.py:1-15 has 0 prod callers.
   - Congress year math (1789 + 2 * (congress - 1)) is hardcoded in 4 files (senate_events.py:74, committee_metadata.py:47, legislators.py:103,107-108, gpo_hearings.py:231) and UTC ISO-8601 timestamp parsing is duplicated in 5 files (parsers/observations.py:14-25, adapters/common.py:78-84, transcripts/context.py:154-160, youtube_api/interpretation.py:20-31, corpus_recovery/govinfo.py:47-55).

## Acceptance Criteria

1. Remove argparse.ArgumentParser from congress_shared/auth.py:6-13; fix cli.py:32-38,55-58 to use type=Path; declare boto3 under [project.optional-dependencies] in congress_shared/pyproject.toml; update congress_shared/README.md:5,87; delete dead congress_shared/globals.py:1-15. 2. Deduplicate write_bound_receipt (custody.py:284) and write_atomic_json (custody.py:315), and rewrite copy_checked (custody.py:375-407) to stream-copy and hash in a single pass without reading the full file into RAM. 3. Add congress_shared/dates.py with year_to_congress, congress_to_years, and parse_utc_timestamp, replacing the 4 hardcoded 1789 formulas and 5 ISO timestamp parsers. 4. Delete packages/congress_api/build/ (109 stale files) and packages/source-fetch/{benchmark.rs,cases.json,experiment.md} plus reqwest-fetch-bench and unused crates (base64, dotenvy, sha2) in packages/source-fetch/Cargo.toml:13-15,24,25,31, and add /// doc comments to packages/source-fetch/main.rs:28-91,145-350.


## Notes

**2026-10-22T17:47:24Z**

Subagent Self-Review Additions (Congress API & Shared Auditor):
1. Cross-Package congress_shared.custody Adoption (Finding #5 & AC #2):
   - Switch packages/youtube_api/src/youtube_api/tables.py:28-39 (AtomicJSONStorage.write -> write_atomic_bytes), packages/corpus_recovery/src/corpus_recovery/govinfo.py:97-100 (_verify_zip) and transfer.py:109-120 (verify_pair -> verify_local_file), and packages/congress_api/src/congress_api/adapters/common.py:49-50 (digest) and retention/document_index.py:855-856 (compact -> canonical_json_bytes / sha256_bytes) to use congress_shared.custody.
2. Stale parsers.speaker_names Doc Reference (AC #4):
   - Update packages/congress_api/README.md:707 (parsers.speaker_names -> matching.speaker_names).

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch syem).
- Grades: proposal 74 → 74, work 74 → 74.
- Problem: Behavior change: `parse_utc_timestamp` converts to UTC and rejects naive input.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:91
- Not covered by a plan workstream.
- See docs/reviews/2026-10-24-ticket-audit/README.md
