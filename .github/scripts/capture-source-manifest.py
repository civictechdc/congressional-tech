"""Record the exact project source and native binary used by a capture runner."""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
from congress_api.retention.writer_identity import writer_identity


def manifest(root):
    identity = writer_identity(root, 'capture')
    paths = set()
    for package in ('congress_api', 'congress_shared', 'committee_meeting', 'house-naming'):
        paths.update(p for p in (root / 'packages' / package / 'src').rglob('*')
                     if p.is_file() and p.suffix != '.pyc'
                     and not any(part == '__pycache__' or part.endswith(('.egg-info', '.dist-info'))
                                 for part in p.parts))
        paths.add(root / 'packages' / package / 'pyproject.toml')
    paths.update(root / 'packages/source-fetch' / name for name in ('main.rs', 'Cargo.toml', 'Cargo.lock'))
    sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    digest = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return dict(code_revision=identity['commit'], lockfile_digest=identity['lockfile_digest'],
                source_sha256=sources, source_digest=digest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--output',type=Path,default=Path('raw-capture-source-manifest.json'))
    parser.add_argument('--native-binary',type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    result = manifest(root)
    result['runtime_versions'] = {name: version(name) for name in
                                  ('pyarrow', 'pypdf', 'Pillow', 'boto3', 'botocore', 'aiobotocore', 'lxml', 'pydantic')}
    binary = args.native_binary or root / 'packages/source-fetch/target/release/source-fetch'
    if binary.exists():
        result['native_binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'source_sha256'}), flush=True)


if __name__ == '__main__':
    main()
