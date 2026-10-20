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

from congress_api.retention.docspec import NativeDatasets


def digest(path):
    with Path(path).open('rb') as source:
        return file_digest(source, 'sha256').hexdigest()


def check(path, binary_sha256):
    if not isinstance(binary_sha256, str) or re.fullmatch('[0-9a-f]{64}', binary_sha256) is None:
        raise ValueError('An approved native binary SHA-256 is required')
    native = NativeDatasets.from_config(path)
    binary = Path(native.binary)
    if not binary.is_file() or not os.access(binary, os.X_OK) or digest(binary) != binary_sha256:
        raise ValueError('The configured native binary is missing or differs from its approved SHA-256')
    return dict(verified=True, binary_sha256=binary_sha256,
                execution_sha256={str(path): digest(path) for path in native.execution_files()},
                native_executed=False, provider_accessed=False, workspace_created=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = check(args.config, args.binary_sha256)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'execution_sha256'}))


if __name__ == '__main__':
    main()
