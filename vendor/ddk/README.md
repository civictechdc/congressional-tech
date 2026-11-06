# Frozen local DDK release

The unchanged dev6 wheel supplies the mandatory standard catalog and native
metadata API used by `viewer-publication`. It is vendored because this scoped
development release has no public package source. The relative uv source keeps
checkout installation reproducible without editable source from another tree.

- File: `data_design_kit-0.1.0.dev6-py3-none-any.whl` (329,518 bytes)
- SHA-256: `41dbccda3367ea794f0040c165abd86f43d918ecee036cbce7307a0b98b18149`
- Source: `b2637279beef7f30f23aba3ca2b8f50f7dc02d3f`
- Capture: `/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/catalog-api-dev6/`

Select `catalog` with the application's existing PyArrow 25.0.1 and explicit
BLAKE3 1.0.11 and PyParsing 3.2.5 pins. The exact Congress supplement passed 234 installed
metadata tests, typed artifact save/reload and tamper checks, and consumption of
eight retained native IPC schemas. The `native-metadata` convenience extra pins
PyArrow 26 and is not selected here. Native execution and the concrete application
producer still need their separate runtime qualification.

After `uv sync --frozen`, install the exact wheel with ordinary hash-qualified
pip through the existing development command. It reads the wheel path and hash
from `uv.lock`; CI and devcontainer setup invoke it after synchronization. uv's
local-wheel installation omits the PEP 610 archive hash required by this
development release. Do not construct installation metadata by hand:

```sh
python3 scripts/dev.py install-catalog
```

The normal installation and all ten shared runtime pins match
`catalog-api-dev6/congress-pins-supplement-02/runtime-constraints-congress.txt`.
Its handoff SHA-256 is `59cc6917c1d512c095265d27dab5c77f8ae4e27fc537620adbd2de9d31eebf38`;
all 95 evidence records were verified. The native application pin remains unchanged. Exact install
receipts, the superseded dev5 wheel and the initial Arrow 26 experiment are
retained under main's `.cache/archive-release/ddk-replacement-20261106/catalog-install-06/`.
