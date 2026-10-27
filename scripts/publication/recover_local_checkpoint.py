#!/usr/bin/env python3
"""Explicit local adoption of the archived 33e chunks for the compact renderer."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

from congress_shared.custody import canonical_json_bytes, write_atomic_bytes
from viewer_publication import attempt, filename_native, filename_viewer, publish_viewer_r2 as publisher
from viewer_publication.filename_budget import DecodedPolicy
from viewer_publication.filename_compression import CompressionPolicy
from viewer_publication.release_identity import source_files, encoded

ORIGIN = '33e8f85230e6936962b178d064984950ae1f38dc'
COMPACT = '708955ea59197c4956a53a405b7e30428eeee263'
PRODUCER = 'packages/viewer_publication/src/viewer_publication/filename_native.py'
EXPECTED_CHUNKS = {'documents': 74, 'filenames': 106}
RECEIPT = 'checkpoint-adoption.json'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    write_atomic_bytes(Path(path), canonical_json_bytes(value, trailing_newline=True),
                       fsync=True, fsync_dir=True)


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root).strip()


def code_proof(root):
    """Only the exact reviewed compact renderer may differ in production inputs."""
    current = source_files(root)
    expected = {}
    differences = []
    for name, sha in current.items():
        old = hashlib.sha256(subprocess.check_output(
            ['git', 'show', ORIGIN + ':' + name], cwd=root)).hexdigest()
        expected[name] = old
        if old != sha:
            differences.append(name)
    if differences != [PRODUCER]:
        raise ValueError('Production changes exceed the reviewed compact renderer')
    approved = subprocess.check_output(['git', 'show', COMPACT + ':' + PRODUCER], cwd=root)
    if hashlib.sha256(approved).hexdigest() != current[PRODUCER]:
        raise ValueError('Renderer is not the exact reviewed compact implementation')
    subprocess.run(['git', 'merge-base', '--is-ancestor', COMPACT, 'HEAD'], cwd=root, check=True)
    return dict(original_revision=ORIGIN, reviewed_compact_revision=COMPACT,
        target_revision=git(root, 'rev-parse', 'HEAD').decode(),
        original_implementation=hashlib.sha256(encoded(expected)).hexdigest(),
        target_implementation=hashlib.sha256(encoded(current)).hexdigest(),
        changed_production_files=differences,
        compatibility='Only the reviewed document flat-occurrence export is omitted; retained document and observation binaries are reused.')


def verify_copy(archive, directory, inventory, copy_receipt=None):
    """Verify the existing independent clone against the retained archive receipt."""
    archive, directory = Path(archive).resolve(), Path(directory).resolve()
    copied_root = directory.parent
    if directory.name != 'run' or archive == copied_root or archive in copied_root.parents or copied_root in archive.parents:
        raise ValueError('Adoption requires a separate copied preparation root/run')
    items = json.loads(Path(inventory).read_bytes())
    mounted_archive = archive.is_dir()
    if not mounted_archive:
        if copy_receipt is None:
            raise ValueError('An unmounted archive requires the audited independent-copy receipt')
        receipt = json.loads(Path(copy_receipt).read_bytes())
        if (receipt.get('status') != 'copied_for_recovery' or receipt.get('method') != 'APFS clone copy, preserving existing hardlinks'
                or receipt.get('hardlinked') != 0 or receipt.get('source') != str(archive)
                or receipt.get('files') != len(items) or receipt.get('logical_bytes') != sum(x['bytes'] for x in items)):
            raise ValueError('Independent-copy receipt does not match the characterized archive')
    expected = {item['path']: item for item in items}
    actual = {}
    for path in copied_root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Copied preparation contains a symlink')
        if path.is_file():
            actual[str(path.relative_to(copied_root))] = path
    if set(actual) != set(expected):
        raise ValueError('Copied preparation file set differs from archive inventory')
    for name, path in actual.items():
        item = expected[name]
        b = path.stat()
        if mounted_archive:
            original = archive / name
            if original.is_symlink() or not original.is_file():
                raise ValueError('Archive inventory path is missing or unsafe')
            a = original.stat()
            if (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino):
                raise ValueError('Recovery copy shares an inode with the archive')
            if a.st_size != item['bytes']:
                raise ValueError('Archive file size differs from its receipt')
        if b.st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Copied preparation bytes differ from archive inventory: ' + name)
    return dict(inventory_sha256=digest(inventory), files=len(actual),
                bytes=sum(item['bytes'] for item in items),
                source_archive=str(archive), copied_root=str(copied_root),
                original_database_sha256=expected['run/publication.renderer-upgrade/stages.sqlite']['sha256'],
                archive_verification='mounted archive identity checks' if mounted_archive else 'existing audited APFS clone receipt',
                independent_copy_receipt_sha256=digest(copy_receipt) if copy_receipt else None)


def adopt_copy(directory, *, authorization, code, identity, requirements, copy_proof):
    """Change only the disposable copy, retaining complete origin evidence."""
    root = Path(directory)
    if not authorization.strip():
        raise ValueError('Explicit checkpoint reuse authorization is required')
    if (root / RECEIPT).exists() or (root / 'prepared-result.json').exists() or (root / 'preparation.json').exists():
        raise ValueError('Adoption needs an unaccepted, not-yet-adopted copy')
    continuation_path = root / 'continuation.json'
    old_bytes = continuation_path.read_bytes()
    continuation = json.loads(old_bytes)
    old = continuation['binding']
    if continuation['phases'] or continuation['writes'] or continuation['versions']:
        raise ValueError('Only the pre-acceptance checkpoint may be adopted')
    if old['provenance_revision'] != ORIGIN or old['code_runtime']['implementation'] != code['original_implementation']:
        raise ValueError('Archive source identity differs from the characterized origin')
    if old['code_runtime']['dependencies'] != identity['dependencies'] or old['publisher_version'] != identity['publisher_version']:
        raise ValueError('Adoption must retain the original qualified runtime')
    if identity['implementation'] != code['target_implementation']:
        raise ValueError('Current code identity differs from the reviewed source proof')
    database = root / 'publication.renderer-upgrade/stages.sqlite'
    with sqlite3.connect(database, timeout=0) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        raw, created = db.execute('SELECT binding,created FROM build').fetchone()
        old_renderer = json.loads(raw)
        if old_renderer['preparation'] != old or old_renderer['source']['selector_sha256'] != old['source']['sha256']:
            raise ValueError('Renderer and preparation source bindings differ')
        if old_renderer['requirements']['policy'] != requirements['policy'] or old_renderer['requirements']['compression'] != requirements['compression']:
            raise ValueError('Decoded policy or compression changed')
        chunks = dict(db.execute('SELECT label,count(*) FROM chunks GROUP BY label'))
        tasks = [name for name, in db.execute('SELECT task FROM progress ORDER BY task')]
        expected_tasks = {'component-registration', 'stage:component_scope'} | {
            'component-chunk:' + name for name, in db.execute('SELECT name FROM chunks')}
        if chunks != EXPECTED_CHUNKS or set(tasks) != expected_tasks:
            raise ValueError('Checkpoint does not contain exactly the completed chunk boundary')
        if db.execute('SELECT count(*) FROM discarded').fetchone()[0]:
            raise ValueError('Checkpoint has an unfinished asset deletion')
        transforms = []
        for name, raw_reference in list(db.execute('SELECT name,reference FROM chunk_assets ORDER BY name')):
            original = json.loads(raw_reference)
            files = original['document_observations']['files']
            flat = files.pop('occurrences')
            if not {'observations', 'observation_rows', 'observation_index'} <= files.keys():
                raise ValueError('Document observation binaries are incomplete')
            replacement = canonical_json_bytes(original).decode()
            transforms.append(dict(chunk=name, original_sha256=hashlib.sha256(raw_reference.encode()).hexdigest(),
                adopted_sha256=hashlib.sha256(replacement.encode()).hexdigest(), omitted_flat_asset=flat['path']))
            db.execute('UPDATE chunk_assets SET reference=? WHERE name=?', (replacement, name))
        if len(transforms) != EXPECTED_CHUNKS['documents']:
            raise ValueError('Expected one document reference per completed document chunk')
        marker = dict(version=1, kind='authorized_local_checkpoint_reuse', authorization=authorization,
            recovery_tool_sha256=digest(__file__),
            at=datetime.now(timezone.utc).isoformat(), code=code, copy=copy_proof,
            original_continuation_sha256=hashlib.sha256(old_bytes).hexdigest(),
            original_renderer_binding_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            original_preparation_binding=old,
            catalog_identity=old_renderer['source'], reused_tasks=tasks, document_reference_changes=transforms,
            retained_binary_policy='Binary assets are unchanged. Normal renderer restore rehashes them; normal reachability discards unreferenced flat exports before inventory/upload.')
        new_binding = dict(old, code_runtime=identity, provenance_revision=code['target_revision'], checkpoint_reuse=marker)
        new_renderer = dict(old_renderer, preparation=new_binding, requirements=requirements)
        # Preserve the full old input context inside the bound provenance marker.
        save(root / RECEIPT, marker)
        db.execute('UPDATE build SET binding=?', (canonical_json_bytes(new_renderer).decode(),))
        db.commit()
    continuation['binding'] = new_binding
    save(continuation_path, continuation)
    result = dict(status='adopted_local_checkpoint', directory=str(root), target_revision=code['target_revision'],
        reused_chunks=sum(EXPECTED_CHUNKS.values()), transformed_document_references=len(transforms),
        receipt_sha256=digest(root / RECEIPT), continuation_sha256=digest(continuation_path),
        database_sha256=digest(database))
    save(root / 'checkpoint-adoption-result.json', result)
    return result


@contextmanager
def authorized_continuation(directory):
    """Explicit local guard override; bind origin evidence into the final receipt."""
    root = Path(directory).resolve()
    if not (root / 'checkpoint-adoption-result.json').is_file():
        raise ValueError('Adoption was not completed; discard/reclone any incomplete copy')
    marker = json.loads((root / RECEIPT).read_bytes())
    if marker['recovery_tool_sha256'] != digest(__file__):
        raise ValueError('Local recovery tool differs from the adopted operation')
    original = attempt.Continuation
    def local_continuation(path, binding, *, resume=False):
        if Path(path).resolve() != root or not resume:
            raise ValueError('Local adoption is restricted to this exact resume directory')
        if binding.get('checkpoint_reuse', marker) != marker:
            raise ValueError('Checkpoint adoption provenance changed')
        binding['checkpoint_reuse'] = marker
        return original(path, binding, resume=resume)
    attempt.Continuation = local_continuation
    try:
        yield
    finally:
        attempt.Continuation = original


def main():
    import argparse
    from congress_api.retention.docspec import NativeDatasets
    import sys
    repo = Path(publisher.__file__).resolve().parents[4]
    sys.path.insert(0, str(repo / 'scripts/publication'))
    from prepare_local_release import make_client
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['adopt', 'resume'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--archive-inventory', type=Path)
    parser.add_argument('--authorization')
    parser.add_argument('--copy-receipt', type=Path)
    parser.add_argument('--native-config', type=Path, required=True)
    parser.add_argument('--metadata-cache', type=Path, required=True)
    parser.add_argument('--public-url', default=publisher.PUBLIC_URL)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    from viewer_publication.publication_cli import save_report
    try:
        native = NativeDatasets.from_config(args.native_config)
        old = json.loads((args.directory / 'continuation.json').read_bytes())['binding']
        from congress_api.retention.derived_files import file_identity
        actual_execution = {str(Path(path).resolve()):dict(file_identity(path)) for path in native.execution_files()}
        if actual_execution != old['native_execution']:
            raise ValueError('Native executable/configuration paths or bytes changed')
        proof = code_proof(repo)
        if args.operation == 'adopt':
            if not args.archive or not args.archive_inventory or not args.authorization:
                parser.error('adopt requires archive, archive-inventory and authorization')
            copy = verify_copy(args.archive, args.directory, args.archive_inventory, args.copy_receipt)
            dbpath = args.directory / 'publication.renderer-upgrade/stages.sqlite'
            with sqlite3.connect(dbpath.resolve().as_uri() + '?mode=ro', uri=True) as db:
                previous = json.loads(db.execute('SELECT binding FROM build').fetchone()[0])['requirements']
            requirements = filename_native.native_requirements(filename_viewer,
                DecodedPolicy(**previous['policy']), CompressionPolicy(**previous['compression']))
            result = adopt_copy(args.directory, authorization=args.authorization, code=proof,
                identity=publisher.full_release_identity(), requirements=requirements, copy_proof=copy)
        else:
            marker = json.loads((args.directory / RECEIPT).read_bytes())
            if marker['code'] != proof:
                raise ValueError('Resume source differs from adopted code')
            with authorized_continuation(args.directory):
                result = attempt.prepare(publisher, make_client(), args.directory,
                    run_id=old['run_id'], run_attempt=old['run_attempt'], public_url=args.public_url, native=native,
                    resume_preparation=True, metadata_cache_dir=args.metadata_cache,
                    stage_event=lambda event:print(json.dumps(event,sort_keys=True),flush=True))
        save_report(args.report, result)
        print(json.dumps(result,sort_keys=True),flush=True)
    except BaseException as error:
        save_report(args.report, dict(status='failed', command='local-checkpoint-' + args.operation,
            error_type=type(error).__name__, error=str(error) if isinstance(error, ValueError) else 'Local recovery failed; see traceback'))
        raise


if __name__ == '__main__':
    main()
