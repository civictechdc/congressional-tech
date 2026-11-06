# Frozen local DDK release

This pure-Python wheel is the qualified dev4 release used by the replacement
worktree. It is included because this local release has no public package source;
the relative uv source keeps checkout installation reproducible without depending
on another checkout's interpreter or editable Python source. It is currently a
workspace development dependency for the catalog migration,
not a dependency of the production `viewer-publication` package.

- File: `data_design_kit-0.1.0.dev4-py3-none-any.whl` (292,436 bytes)
- SHA-256: `7c4c6bb481316c95e13c5518089f90c71664ca7387c09eb1ae0f94219fe267b8`
- Implementation: `fb70ab825243235b4ecf77c5ebb8c636d0d06e2d`
- Captured release: `/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01/`

The wheel contains its license, notices, schema provenance and pinned resource
schemas. The frozen dependency graph selects its catalog extras. Native
execution requires a separately qualified runtime tuple. The wheel is reused
unchanged, not rebuilt. A future
public package source can replace this packaging location only while preserving
the chosen release identity or deliberately qualifying a successor.

After `uv sync --frozen`, use the maintained hash-qualified pip installation
recorded in `docs/replacement-ddk/README.md`. The development release requires
the wheel hash in PEP 610 installation metadata; uv's local-wheel installation
does not retain it. Do not patch DDK or construct installation metadata by hand.
