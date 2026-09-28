"""Reuse a verified Parquet publication when its inputs and implementation match."""
from importlib import import_module, metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile

from committee_meeting.publication import PublicationManifest
from .export import encode, file_sha, sha


def implementation_digest():
    """Include adapters, schema, publication code and bundled lookup tables."""
    files = []
    for name in ('committee_explorer', 'committee_meeting', 'congress_api', 'congress_shared', 'youtube_api'):
        root = Path(import_module(name).__file__).parent
        files.extend((name + '/' + path.relative_to(root).as_posix(), file_sha(path))
                     for path in sorted(root.rglob('*'))
                     if path.is_file() and path.suffix in ('.py', '.json', '.csv'))
    versions = {name: metadata.version(name) for name in ('pydantic', 'pydantic-core', 'pyarrow')}
    return sha(encode({'files': files, 'versions': versions, 'python': list(sys.version_info[:3])}))


def request_key(*, files, youtube_dir, transcript_files, format, limit, as_of):
    # Ordinary input paths are machine-local. Transcript URIs are retained in
    # source evidence, so moving those files must also invalidate reuse.
    inputs = {name: file_sha(path) if path is not None else None for name, path in files.items()}
    inputs['youtube'] = None if youtube_dir is None else [(p.name, file_sha(p)) for p in sorted(Path(youtube_dir).glob('youtube_*.json'))]
    inputs['transcripts'] = [(Path(p).resolve().as_uri(), file_sha(p)) for p in transcript_files]
    return sha(encode({'version': 1, 'inputs': inputs, 'implementation': implementation_digest(),
                      'format': format, 'limit': limit, 'as_of': as_of.isoformat() if as_of else None}))


def state_digests(state, publication_id):
    paths = ('ids.json', 'publication.json', f'issue-history/{publication_id}.sqlite')
    return {name: file_sha(state / name) for name in paths}


def save_receipt(state, key, manifest):
    receipt = {'version': 1, 'request_key': key, 'publication_id': manifest.publication_id,
               'state': state_digests(state, manifest.publication_id)}
    temporary = state / '.reuse.json.tmp'
    temporary.write_bytes(encode(receipt))
    temporary.replace(state / 'reuse.json')


def try_reuse(output, state, retained, key):
    """Restore the original export from local or packaged copies, without models.

    The receipt is written only by a completed export. It also pins identity and
    issue-history state. Reuse preserves the original observation/import times;
    an unchanged rerun does not claim that a source was checked again.
    """
    from .browser import verify
    receipt_path = state / 'reuse.json'
    if not receipt_path.exists():
        return None
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('version') != 1 or receipt.get('request_key') != key:
        return None
    manifest_raw = (state / 'publication.json').read_bytes()
    manifest = PublicationManifest.model_validate_json(manifest_raw)
    if manifest.publication_id != receipt['publication_id']:
        return None
    expected = {'ids.json', 'publication.json', f'issue-history/{manifest.publication_id}.sqlite'}
    if set(receipt['state']) != expected:
        return None
    if any(not (state / name).is_file() or file_sha(state / name) != digest for name, digest in receipt['state'].items()):
        return None
    for directory in (output, Path(retained)):
        if not (directory / 'CURRENT.json').exists():
            continue
        _, source, available = verify(directory)
        parts = {p.path: (p.sha256, p.byte_size) for p in available.partitions}
        if any(parts.get(p.path) != (p.sha256, p.byte_size) for p in manifest.partitions):
            continue
        if directory == output and available == manifest:
            return manifest
        stage = Path(tempfile.mkdtemp(prefix='.reuse-', dir=output))
        try:
            for part in manifest.partitions:
                target = stage / part.path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / part.path, target)
            (stage / 'manifest.json').write_bytes(manifest_raw)
            release = output / 'releases' / manifest.publication_id
            release.parent.mkdir(parents=True, exist_ok=True)
            if release.exists():
                if (release / 'manifest.json').read_bytes() != manifest_raw or any(file_sha(release / p.path) != p.sha256 for p in manifest.partitions):
                    raise ValueError('Existing publication differs from the reuse receipt')
            else:
                stage.rename(release)
            pointer = {'schema_version': manifest.schema_version, 'publication_id': manifest.publication_id,
                       'manifest_path': f'releases/{manifest.publication_id}/manifest.json',
                       'manifest_sha256': sha(manifest_raw), 'media_type': 'application/json'}
            temporary = output / '.CURRENT.json.tmp'
            temporary.write_bytes(encode(pointer))
            temporary.replace(output / 'CURRENT.json')
            return manifest
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return None
