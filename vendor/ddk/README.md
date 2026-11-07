# Frozen local DDK release

The integrated SDK supplies the mandatory standard catalog and producer-proof
binding API used by `viewer-publication`. This development release is vendored;
the relative uv source keeps installation reproducible without editable source
from another checkout.

- File: `data_design_kit-0.1.0.dev6+integrated.1-py3-none-any.whl` (379,406 bytes)
- SHA-256: `fec39a284d886272131e24231550a75d617f7eb4136355e6aad8613e0823794c`
- Source: `accb5836699a5ff9c0fbb82258c620934dd57030`
- Handoff: `/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-01/build-02/sdk-only-handoff.json`

Select `catalog` with the application's existing PyArrow 25.0.1, BLAKE3 1.0.11
and PyParsing 3.2.5 pins. All 131 other installed distribution versions stayed
unchanged during this update, and all 117 installed wheel members matched
(excluding installer-managed `RECORD`). The
`native-metadata` convenience extra pins PyArrow 26.0.1 and is not selected here.

Seven application checks used original accepted and unaccepted native receipts
to verify exact producer-proof bindings and refusals. They opened five small
control files, no data payloads, and invoked no native process or network call.
Their evidence is under main's
`.cache/archive-release/ddk-replacement-20261106/retained-proof-binding-01/`;
`terminal.json` has SHA-256
`3d35bbdc2d7fe3dc383ea7fcb1fce88a27800add998b6ac1dbd2c54c6707f836`.
This qualifies those installed application bindings for the one-input fixture;
it does not exercise multiple-input ordering or refresh custody availability.
Full native execution, original Congress input admission and model acceptance
remain separate.

After `uv sync --frozen`, install the exact wheel with ordinary hash-qualified
pip through the existing development command. It reads the wheel path and hash
from `uv.lock`; CI and devcontainer setup invoke it after synchronization. uv's
local-wheel installation omits the PEP 610 archive hash required by this
development release. Do not construct installation metadata by hand:

```sh
python3 scripts/dev.py install-catalog
```

The previous dev6 package's 234 installed metadata cases remain historical
evidence under `catalog-api-dev6/congress-pins-supplement-02/`; they are not a
test count for this successor. The previous wheel and before/after installation
identities are retained with the new binding evidence. The application native
runtime pin remains unchanged.
