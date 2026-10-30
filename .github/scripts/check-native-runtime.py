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

from docspec_client.docspec import (
    REQUIRED_LOOPBACK_CAPABILITIES,
    RUNTIME_PIN_FILE,
    NativeDatasets,
    load_runtime_pin,
    runtime_pin_digest,
)


def digest(path):
    with Path(path).open('rb') as source:
        return file_digest(source, 'sha256').hexdigest()


def check(path, binary_sha256=None, *, expected_platform=None,
          expected_source_revision=None, required_features=(),
          required_capabilities=REQUIRED_LOOPBACK_CAPABILITIES,
          pin_file=RUNTIME_PIN_FILE):
    if binary_sha256 is None:
        pin = load_runtime_pin(pin_file)
        config_payload = json.loads(Path(path).read_text(encoding='utf-8'))
        platform_name = expected_platform or config_payload.get('platform')
        if not isinstance(platform_name, str) or not platform_name:
            raise ValueError('An explicit platform or runtime.json platform is required to resolve the committed pin')
        binary_sha256 = runtime_pin_digest(platform_name, pin_path=pin_file)
        if expected_platform is None:
            expected_platform = platform_name
        if expected_source_revision is None:
            expected_source_revision = pin['source_revision']
        if not required_features:
            required_features = tuple(pin['build_features'])
        required_capabilities = tuple(pin['required_capabilities'])
    if not isinstance(binary_sha256, str) or re.fullmatch('[0-9a-f]{64}', binary_sha256) is None:
        raise ValueError('An approved native binary SHA-256 is required')
    native = NativeDatasets.from_config(path)
    verification = native.verify_runtime(
        expected_sha256=binary_sha256,
        expected_platform=expected_platform,
        expected_source_revision=expected_source_revision,
        required_features=required_features,
        required_capabilities=required_capabilities,
        pin_file=pin_file if binary_sha256 is None else None,
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
    parser.add_argument('--binary-sha256', default=None, help='Optional SHA-256 override; defaults to committed pin file.')
    parser.add_argument('--pin-file', type=Path, default=RUNTIME_PIN_FILE, help='Committed engine runtime pin file.')
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
        pin_file=args.pin_file,
    )
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'execution_sha256'}))


if __name__ == '__main__':
    main()
