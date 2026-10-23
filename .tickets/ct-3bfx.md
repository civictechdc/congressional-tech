---
id: ct-3bfx
status: closed
deps: []
links: []
created: 2026-10-22T17:45:12Z
type: bug
priority: 0
assignee: mikewolfd
parent: ct-syem
tags: [apps, committee-youtube, inflation-gsheets, site, viewer-publication, bug, dx]
---
# Fix committee_explorer --reuse-from cache poisoning bug, InflationSource non-dataclass field() bug, hardcoded /Users/mikewolfd path, and viewer_publication -> apps/site dependency inversion

CS300 Audit Finding (Apps, Frontend & Infra Auditor - Active Bugs, Layering Inversions & Workspace Defects):
1. Silent Cache Poisoning Bug in committee_explorer --reuse-from (apps/committee_youtube/src/committee_explorer/export.py:327-332 & reuse.py:52-73):
   - export() accepts document_filenames: Path | None = None (export.py:305) and uses it at L424-441, 470 to attach saved-copy SHA-256 digests and document classifications, but omits document_filenames when calling request_key(...) at export.py:327-332 (and reuse.py:52-73 omits it from the input fingerprint). Changing or adding --document-filenames while --reuse-from is enabled falsely matches the stale input_key and copies the outdated publication!
2. dataclasses.field() Used on a Non-Dataclass in inflation_gsheets (apps/inflation_gsheets/src/sources/base.py:76-86):
   - InflationSource is a plain class without @dataclass, yet line 81 declares columns: list[str] = field(default_factory=list), making InflationSource.columns a dataclasses.Field descriptor object at runtime. Also base.py:82 defines requires_key: bool = False (overridden in bls.py:29, fred.py:62, adobe.py:33, pricestats.py:35) which is never read; fetch-inflation-sources.py:124, 135 appends to unread available_cols; fetch-cpi-convert-csv.py:13-22 uses importlib.util.spec_from_file_location to load sources/bls.py; and pyproject.toml:10 declares unused openpyxl.
3. Layering Inversion (packages/viewer_publication -> apps/site) & Hardcoded Laptop Path:
   - packages/viewer_publication/src/viewer_publication/filename_review_binding.py:19-20 and verify.py:188-194 reach up 4 parent directories into apps/site/ (parents[4] / 'apps/site/document-review-identities.json' and spawning node apps/site/scripts/verify-live-publication.mjs).
   - apps/committee_youtube/src/committee_explorer/docspec_views.py:107-108 hardcodes Path('/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/{release,debug}/docspec') in production code (and resolve_docspec_binary is duplicated verbatim in packages/congress_api/src/congress_api/retention/weekly_tables.py:203).
4. Broken Workspace & React Lifecycle Bugs:
   - apps/inflation_gsheets is missing from root pyproject.toml:25-36 [tool.uv.workspace].members; docspec-client is imported in apps/committee_youtube/src/committee_explorer/docspec_views.py:26 but missing from apps/committee_youtube/pyproject.toml:11-18 dependencies (while unused tinydb is listed at L16); apps/site/scripts/migrate-content.mjs:1-264 (wired to npm run migrate in apps/site/package.json:10) crashes immediately with ENOENT because ../website was deleted.
   - apps/site/src/components/explorer/view/request-state.tsx:10-31 (useRequest) calls setState({ status: 'loading' }) synchronously inside the React render body (L16-19); apps/site/src/components/explorer/reader/filenames/session.ts:56-76 polls window.setInterval(..., 16) waiting for window.filenameViewerApi instead of awaiting a module-scoped Promise.

## Acceptance Criteria

1. Include document_filenames in request_key() (apps/committee_youtube/src/committee_explorer/export.py:327-332 and reuse.py:52-73) and add a regression test verifying --reuse-from invalidates when document_filenames changes. 2. Fix InflationSource.columns in apps/inflation_gsheets/src/sources/base.py:81, remove unused openpyxl/available_cols/requires_key, replace _load_bls_module() in fetch-cpi-convert-csv.py:13-22 with normal import, add apps/inflation_gsheets to root pyproject.toml workspace members, and declare docspec-client (removing unused tinydb) in apps/committee_youtube/pyproject.toml. 3. Break the packages/viewer_publication -> apps/site dependency inversion (filename_review_binding.py:19-20, verify.py:188-194), remove hardcoded /Users/mikewolfd paths from docspec_views.py:107-108 (and deduplicate resolve_docspec_binary into docspec_client), and delete broken apps/site/scripts/migrate-content.mjs. 4. Fix synchronous render-body setState in apps/site/src/components/explorer/view/request-state.tsx:16-19 and replace window.setInterval polling in reader/filenames/session.ts:56-76 with a Promise.


## Notes

**2026-10-22T17:46:43Z**

Subagent Self-Review Additions (Apps, Frontend & Infra Auditor):
1. apps/site/package.json:8: 'build': 'python3 scripts/stage-document-reviews.py && astro build' invokes bare system python3 (which fails when viewer_publication is only installed in the repo .venv, unlike apps/site/scripts/generate-explorer-types.mjs:9-10 which resolves ../../.venv/bin/python), and npm run dev skips staging document reviews on fresh checkouts.
2. Root turbo.json:1-5 & apps/site/package-lock.json: Root turbo.json has empty 'tasks': {}, apps/site/package.json:34 (npm@11.19.1) conflicts with root package.json:2 (npm@11.0.0) and commits a nested apps/site/package-lock.json, and apps/committee_youtube/README.md:265-266 still documents manual python -m venv .venv && pip install -e instead of uv sync.
