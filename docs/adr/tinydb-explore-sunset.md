# Keep TinyDB exploration outside production

Status: accepted, 2026-09-30.

The weekly workflow uses `congress-meetings`; `congress-fetch` and
`congress-analyze` serve optional local exploration. Keep both script names and
old module imports, but put their implementation under `congress_api.legacy`.
Shared committee objects sit outside the fetch/analyze command packages so the
commands do not depend on each other. Production rejected-page retention moves
to `retention.rejected_pages`, with its old import retained as an alias.

No removal date or new features are planned. Root and devcontainer instructions
lead with the production mirror. Old imports remain compatibility shims for at
least one release; their eventual removal requires a separate owner decision.
No runtime deprecation warning is added to existing command output.

The known dictionary-shaped event bug in legacy `analyze.main` is unchanged and
tracked as separate bugfix work in the refactoring plan. This isolation does not
claim to repair that path or remove TinyDB: production YouTube matching still
uses YouTube TinyDB caches.
