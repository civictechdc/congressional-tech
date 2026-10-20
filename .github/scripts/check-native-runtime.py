"""Verify explicit preinstalled native execution inputs before archive access.

This does not install a binary, connect to a provider, create a workspace or
select a namespace. The approved distribution and runtime files must already
exist on the runner; missing hosted distribution remains an execution blocker.
"""
import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
import re

from congress_api.retention.docspec import REQUIRED_LOOPBACK_CAPABILITIES, NativeDatasets


def digest(path):
    with Path(path).open('rb') as source:
        return file_digest(source, 'sha256').hexdigest()


def check(path, binary_sha256, *, expected_platform=None,
          expected_source_revision=None, required_features=(),
          required_capabilities=REQUIRED_LOOPBACK_CAPABILITIES):
    if not isinstance(binary_sha256, str) or re.fullmatch('[0-9a-f]{64}', binary_sha256) is None:
        raise ValueError('An approved native binary SHA-256 is required')
    native = NativeDatasets.from_config(path)
    verification = native.verify_runtime(
        expected_sha256=binary_sha256,
        expected_platform=expected_platform,
        expected_source_revision=expected_source_revision,
        required_features=required_features,
        required_capabilities=required_capabilities,
    )
    return dict(
        verified=True,
        binary_sha256=binary_sha256,
        platform=verification['platform'],
        source_revision=verification['source_revision'],
        build_features=list(verification['build_features']),
        required_capabilities=list(verification['required_capabilities']),
        execution_sha256={str(item): digest(item) for item in native.execution_files()},
        native_executed=False,
        provider_accessed=False,
        workspace_created=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--platform', help='Optional expected platform (e.g. linux-amd64, darwin-arm64).')
    parser.add_argument('--source-revision', help='Optional expected 40-char source commit.')
    parser.add_argument('--require-feature', action='append', default=[], help='Required build feature.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = check(
        args.config,
        args.binary_sha256,
        expected_platform=args.platform,
        expected_source_revision=args.source_revision,
        required_features=tuple(args.require_feature),
    )
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'execution_sha256'}))


if __name__ == '__main__':
    main()
