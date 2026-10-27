"""Standard-library release identity shared by early checks and publication."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import tomllib
import threading

_source_cache = {}
_source_lock = threading.RLock()

PACKAGES = ('pyarrow', 'boto3', 'botocore', 'lxml', 'duckdb', 'zstandard', 'ijson')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def source_files(root):
    root = Path(root)
    def custody_of(paths):
        values = {}
        for path in paths:
            stat = path.stat()
            values[str(path.relative_to(root))] = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        return values
    paths = set((root / 'packages/viewer_publication/src/viewer_publication').glob('filename*.py'))
    paths.update((root / 'packages/congress_shared/src/congress_shared').rglob('*.py'))
    paths.update((root / 'packages/congress_api/src/congress_api').rglob('*.py'))
    paths.update((root / 'packages/docspec_client/src/docspec_client').rglob('*.py'))
    pub_scripts = root / 'scripts' / 'publication'
    paths.update(pub_scripts / name for name in (
        'publish-filename-viewer.py', 'publish-viewer-r2.py',
        'publication_cli.py', 'prepare_workflow_resume.py'))
    paths.update(root / 'scripts' / name for name in (
        'viewer_release_identity.py', 'publication_preflight.py'))
    paths.update(root / name for name in (
        'packages/viewer_publication/src/viewer_publication/__init__.py',
        'packages/viewer_publication/src/viewer_publication/release_identity.py',
        'packages/viewer_publication/src/viewer_publication/publish_viewer_r2.py',
        'packages/viewer_publication/src/viewer_publication/publish_filename_viewer.py',
        'packages/viewer_publication/src/viewer_publication/constants.py',
        'packages/viewer_publication/src/viewer_publication/publication_cli.py',
        'packages/viewer_publication/src/viewer_publication/cli.py',
        'packages/viewer_publication/src/viewer_publication/client.py',
        'packages/viewer_publication/src/viewer_publication/native.py',
        'packages/viewer_publication/src/viewer_publication/continuation.py',
        'packages/viewer_publication/src/viewer_publication/local.py',
        'packages/viewer_publication/src/viewer_publication/attempt.py',
        'packages/viewer_publication/src/viewer_publication/plan.py',
        'packages/viewer_publication/src/viewer_publication/reconciliation.py',
        'packages/viewer_publication/src/viewer_publication/resume.py',
        'packages/viewer_publication/src/viewer_publication/verify.py',
        'apps/site/document-review-identities.json', 'apps/site/document-review-publication.json',
        '.python-version', 'pyproject.toml', 'uv.lock', '.github/actions/setup-python-project/action.yml'))
    paths = sorted(path for path in paths if path.is_file())
    custody = custody_of(paths)
    with _source_lock:
        cached = _source_cache.get(root.resolve())
        if cached is not None and cached[0] == custody:
            return dict(cached[1])
        values = {}
        for path in paths:
            with path.open('rb') as stream:
                values[str(path.relative_to(root))] = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = custody_of(paths)
        if after != custody:
            raise ValueError('Release source changed during hashing')
        _source_cache[root.resolve()] = (custody, values)
        return dict(values)


def runtime_fingerprint(packages, python=None):
    return hashlib.sha256(encoded({'python': python or platform.python_version(),
        'implementation': platform.python_implementation(), 'system': platform.system(), 'machine': platform.machine(),
        'packages': packages})).hexdigest()


def installed_runtime():
    packages = {}
    for name in PACKAGES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return runtime_fingerprint(packages)


def locked_runtime(root):
    """Expected runtime after the unchanged locked workspace setup, without installing it."""
    root = Path(root)
    with (root / 'uv.lock').open('rb') as stream:
        lock = tomllib.load(stream)
    packages = {name: None for name in PACKAGES}
    for name in PACKAGES:
        versions = {item['version'] for item in lock['package'] if item['name'] == name}
        if len(versions) > 1:
            raise ValueError('Ambiguous locked publication runtime package: ' + name)
        if versions:
            packages[name] = versions.pop()
    python = (root / '.python-version').read_text().strip()
    if python != platform.python_version():
        raise ValueError('Preflight Python differs from the locked workspace Python')
    return runtime_fingerprint(packages, python)
