---
id: ct-tcs4
status: closed
deps: []
links: []
created: 2026-10-22T17:34:59Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-syem
tags: [house-naming, bloat, performance, deadcode, dx]
---
# Purge 111 task notes & 9 one-off tools from house-naming sdist, decompose 740-line Extractor.extract, and make 1MB guide.json loading lazy

CS300 Audit Finding (Committee, Naming & YouTube Auditor - packages/house-naming):
1. Package & Repo Bloat: (a) packages/house-naming/notes/ contains 111 AI task-receipt files (584 KB) and packages/house-naming/MANIFEST.in:5-7 bundles both notes/ and tools/ into the production sdist; (b) packages/house-naming/build/lib/house_naming/ (1 MB stale Sep 29 build tree) and src/house_naming_guide.egg-info/ sit on disk; (c) 9 one-off migration/comparison scripts in packages/house-naming/tools/ (1,510 LOC, hardcoding local output/filename-* paths and Python 3.11+ hashlib.file_digest at compare_filename_metadata.py:19 despite pyproject.toml claiming requires-python >= 3.10) plus tests/test_research_note_paths.py:1-97; (d) 93 fragmented micro-test files in packages/house-naming/tests/ plus 3 non-test CLI scripts inside tests/.
2. Import-Time 2x 1MB JSON Load & Validation: naming.py:15 runs HOUSE_NAMING = Engine() at import time (reading, deepcopying, Draft202012Validator-validating, and compiling 1MB guide.json), while bill_codes.py:14 (_GUIDE = json.loads(...)) reads and parses 1MB guide.json a second time at import time; APPROPRIATION_SUBJECTS regex stripping is also duplicated between engine.py:46-47 and naming.py:19-20.
3. 740-Line Uncommented Procedural Monolith: packages/house-naming/src/house_naming/extraction.py is 1,501 LOC, with Extractor.extract spanning 740 lines (761-1501) with zero section comments; helper functions (lines 45-760) and compiler.py:1-145 also lack invariant documentation; house-naming has no README.md.

## Acceptance Criteria

1. Remove recursive-include notes and tools from MANIFEST.in, delete stale packages/house-naming/build/ and .egg-info/, remove or archive the 9 one-off tools/ scripts and test_research_note_paths.py, and move the 3 non-test audit/compare scripts out of tests/. 2. Make HOUSE_NAMING (naming.py:15) and BILL_CODES (bill_codes.py:14) lazy via @functools.cache sharing catalog.load_guide(), and deduplicate APPROPRIATION_SUBJECTS. 3. Decompose Extractor.extract (extraction.py:761-1501) into documented pipeline stage methods and add a package README.md.


## Notes

**2026-10-22T17:42:50Z**

Subagent Self-Review Additions:
- Deduplicate URL normalization between packages/house-naming/src/house_naming/engine.py:183-197 and extraction.py:776-789.
- Deduplicate the CLI main() error wrapper between cli.py:88-95 and filename_corpus.py:397-404.
- Declare pyarrow as an optional dependency in packages/house-naming/pyproject.toml (imported in src/house_naming/filename_corpus.py:14).

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch syem).
- Grades: proposal 82 → 82, work 87 → 87.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
