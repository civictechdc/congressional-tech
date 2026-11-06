# Frozen local DDK release

This pure-Python wheel is the qualified dev5 release used by the replacement
worktree. It is included because this local release has no public package source;
the relative uv source keeps checkout installation reproducible without depending
on another checkout's interpreter or editable Python source. It is currently a
workspace development dependency for the catalog migration,
not a dependency of the production `viewer-publication` package.

- File: `data_design_kit-0.1.0.dev5-py3-none-any.whl` (296,565 bytes)
- SHA-256: `b5b64cf8e670b9fb9a1546d4f3bc5aead70e47124f2acfb51cec9028286007eb`
- Implementation: `5e90d70f74ef88053a75b8d991caf262ad74bbd0`
- Captured release: `/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/managed-public-dev5/distribution/qualified-02/`

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

The local install matched all 108 code/resource/distribution members to the
qualified wheel. Only the DDK version, wheel location and digest changed in
`uv.lock`; the application's native pin is unchanged. The previous dev4 wheel
remains under main's archive-release `superseded-vendor-wheels/`, with its exact
identity recorded in `catalog-install-05/superseded-vendor.json`.
