---
id: ct-0odd
status: closed
deps: []
links: [ct-aia9, ct-ec91, ct-te1p, ct-3ttc, ct-gi01, ct-8kl2, ct-2yl5, ct-bwac, ct-84xa]
created: 2026-10-22T04:03:02Z
type: task
priority: 1
assignee: mikewolfd
external-ref: ss-55jg
parent: ct-8kl2
tags: [docspec, ci, r2, runtime, viewer_publication]
---
# Build and publish linux-amd64 docspec 4b29482 runtime artifact to R2 and update DOCSPEC_RUNTIME_ARTIFACT

Local darwin-arm64 QUALIFIED_DOCSPEC_RUNTIME in packages/docspec_client/src/docspec_client/docspec.py is pinned to docspec-rs commit 4b294826649edd2625513f9b5d3e30d92080a695. GitHub Actions ubuntu-24.04 workflows (.github/workflows/publish-filename-viewer.yml via .github/scripts/setup-native-runtime.py) install the linux-amd64 binary described by vars.DOCSPEC_RUNTIME_ARTIFACT from R2.

## Design

1. Build docspec-rs at 4b294826649edd2625513f9b5d3e30d92080a695 on linux-amd64 with 'cargo build --release --features remote'.
2. Compute exact byte size and SHA-256 digest of target/release/docspec.
3. Upload binary to R2 bucket at key 'runtime/docspec/4b294826649edd2625513f9b5d3e30d92080a695/linux-amd64/<sha256>/docspec'.
4. Update GitHub Actions repository variable DOCSPEC_RUNTIME_ARTIFACT JSON (version=1, platform='linux-amd64', source_revision='4b294826649edd2625513f9b5d3e30d92080a695', bucket, key, bytes, sha256, build_features=['remote'], required_capabilities=['request-deadline','owned-stdin-eof']).

## Acceptance Criteria

1. .github/scripts/setup-native-runtime.py succeeds in CI against the updated DOCSPEC_RUNTIME_ARTIFACT descriptor.
2. .github/workflows/publish-filename-viewer.yml completes preparation and ExportPin publication using the 4b29482 linux-amd64 runtime.

