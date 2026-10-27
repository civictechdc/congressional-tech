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
COMPACT_RUNTIME = '146931b328d8af5384f8540b6b5bd3b050159815'
SOURCE_CACHE = 'fe82754f0aa26ce60dc592f0a4a2f29c1a6f67c4'
ORIGINAL_TOOL_SHA256 = '81d4977b3392bc83b6ca2d833d645cf623ba808fa262a196c746dbb6548bf4e4'
SOURCE_CACHE_FILES = (PRODUCER,
    'packages/congress_api/src/congress_api/retention/catalog_rows.py',
    'packages/congress_api/src/congress_api/retention/catalog_dependency_storage.py')
SOURCE_CACHE_RUNTIME = '3a8b9376d68215922230e447c93b2176892aa09e'
SOURCE_CACHE_TOOL_SHA256 = 'e6030ee6d4deb7d8f2c9019ee3c1360f38ae3c9de07e50a1a499b2516edba0bf'
RECOVERY_READER = 'e67e3a4a9d02f638fed934b97361df2178ac2d8f'  # Set only after the final producer commit is reviewed.
FINISHED_DATABASE_SHA256 = '4cdbd05dd02d768302ebc5a30da002ba41eb2545aad8af72ad5caf734c840f06'
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
    """Permit only explicitly pinned reviewed production trees."""
    current = source_files(root)
    def blob(revision, name):
        return hashlib.sha256(subprocess.check_output(
            ['git', 'show', revision + ':' + name], cwd=root)).hexdigest()
    def pinned(revision):
        names = set(git(root, 'ls-tree', '-r', '--name-only', revision).decode().splitlines())
        return {name:blob(revision,name) for name in current if name in names}
    origin = pinned(ORIGIN)
    compact = dict(origin, **{PRODUCER:blob(COMPACT, PRODUCER)})
    optimized = dict(compact, **{name:blob(SOURCE_CACHE, name) for name in SOURCE_CACHE_FILES})
    reader = pinned(RECOVERY_READER) if RECOVERY_READER is not None else None
    if reader is not None and current == reader:
        approved, compatibility = RECOVERY_READER, 'Exact reviewed recovery admission/retry/checkpoint code; completed renderer payload/root stages are output-equivalent.'
    elif current == compact:
        approved, compatibility = COMPACT, 'Only the reviewed document flat-occurrence export is omitted; retained document and observation binaries are reused.'
    elif current == optimized:
        approved, compatibility = SOURCE_CACHE, 'Exact reviewed compact export plus validated occurrence schema/owner-slice caching; completed binary assets and task results are unchanged.'
    else:
        raise ValueError('Production changes exceed the exact reviewed compact/source-cache implementations')
    subprocess.run(['git', 'merge-base', '--is-ancestor', approved, 'HEAD'], cwd=root, check=True)
    result = dict(original_revision=ORIGIN, reviewed_compact_revision=COMPACT,
        target_revision=git(root, 'rev-parse', 'HEAD').decode(),
        original_implementation=hashlib.sha256(encoded(origin)).hexdigest(),
        target_implementation=hashlib.sha256(encoded(current)).hexdigest(),
        changed_production_files=[name for name in current if current[name] != origin.get(name)],
        compatibility=compatibility)
    if approved == SOURCE_CACHE:
        result.update(reviewed_source_cache_revision=SOURCE_CACHE,
                      compact_implementation=hashlib.sha256(encoded(compact)).hexdigest())
    if RECOVERY_READER is not None and approved == RECOVERY_READER:
        result.update(reviewed_recovery_revision=RECOVERY_READER,
                      source_cache_implementation=hashlib.sha256(encoded(optimized)).hexdigest())
    return result


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


def table_proof(db, query):
    digest = hashlib.sha256()
    count = 0
    for row in db.execute(query):
        digest.update(canonical_json_bytes(row));digest.update(b'\n');count += 1
    return dict(rows=count, sha256=digest.hexdigest())


def rebind_copy(directory, *, authorization, code, identity, requirements):
    """One explicit old-146 to reviewed-source-cache rebind; no payload/task edits."""
    root = Path(directory)
    if not authorization.strip() or code.get('reviewed_source_cache_revision') != SOURCE_CACHE:
        raise ValueError('Rebind requires authorization and the exact reviewed source-cache code')
    if any((root / name).exists() for name in ('preparation.json','prepared-result.json',
            'publication/manifest.json','publication/recovery-prepared.json','checkpoint-rebind.json')):
        raise ValueError('Only an unaccepted, not-yet-rebound checkpoint may be rebound')
    old_bytes = (root / 'continuation.json').read_bytes()
    continuation = json.loads(old_bytes)
    old = continuation['binding']
    marker_bytes = (root / RECEIPT).read_bytes()
    marker = json.loads(marker_bytes)
    result_before = json.loads((root / 'checkpoint-adoption-result.json').read_bytes())
    if continuation['phases'] or continuation['writes'] or continuation['versions']:
        raise ValueError('Accepted phases or publication state forbid rebind')
    if (old['provenance_revision'] != COMPACT_RUNTIME or old.get('checkpoint_reuse') != marker
            or marker.get('kind') != 'authorized_local_checkpoint_reuse'
            or marker.get('recovery_tool_sha256') != ORIGINAL_TOOL_SHA256
            or marker['code'].get('original_revision') != ORIGIN
            or marker['code'].get('reviewed_compact_revision') != COMPACT
            or marker['code'].get('target_revision') != COMPACT_RUNTIME
            or marker['code'].get('target_implementation') != code['compact_implementation']
            or marker['code'].get('original_implementation') != code['original_implementation']
            or old['code_runtime']['implementation'] != code['compact_implementation']
            or result_before.get('status') != 'adopted_local_checkpoint'
            or result_before.get('target_revision') != COMPACT_RUNTIME
            or result_before.get('receipt_sha256') != hashlib.sha256(marker_bytes).hexdigest()):
        raise ValueError('Checkpoint is not the known old-146 authorized adoption')
    for key in ('source','viewer','accepted','native_execution','mode','run_id','run_attempt','publisher_version'):
        if old.get(key) != marker['original_preparation_binding'].get(key):
            raise ValueError('Original protected inputs or native execution changed')
    if (identity['implementation'] != code['target_implementation']
            or {k:v for k,v in old['code_runtime'].items() if k != 'implementation'}
               != {k:v for k,v in identity.items() if k != 'implementation'}
            or old['publisher_version'] != identity['publisher_version']):
        raise ValueError('Native dependencies/runtime/publisher or target identity changed')
    database = root / 'publication.renderer-upgrade/stages.sqlite'
    with sqlite3.connect(database, timeout=0) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute('SELECT binding,created FROM build').fetchall()
        if len(rows) != 1:
            raise ValueError('Checkpoint requires its single renderer binding')
        raw, created = rows[0]
        renderer = json.loads(raw)
        if (renderer['preparation'] != old or renderer['source'] != marker['catalog_identity']
                or renderer['source']['selector_sha256'] != old['source']['sha256']):
            raise ValueError('Preparation, catalog and original marker bindings differ')
        before_policy = {k:v for k,v in renderer['requirements'].items() if k != 'implementation'}
        after_policy = {k:v for k,v in requirements.items() if k != 'implementation'}
        if before_policy != after_policy:
            raise ValueError('Renderer policy/compression/runtime changed')
        tasks = [name for name, in db.execute('SELECT task FROM progress ORDER BY task')]
        chunks = dict(db.execute('SELECT label,count(*) FROM chunks GROUP BY label'))
        expected_tasks = {'component-registration','stage:component_scope'} | {
            'component-chunk:' + name for name, in db.execute('SELECT name FROM chunks')}
        if chunks != EXPECTED_CHUNKS or not expected_tasks <= set(tasks) or 'finished' in tasks:
            raise ValueError('Checkpoint lost required chunks or already finished publication')
        preserved = dict(
            progress=table_proof(db, 'SELECT task,result FROM progress ORDER BY task'),
            assets=table_proof(db, 'SELECT path,bytes,sha256 FROM assets ORDER BY path'),
            chunk_assets=table_proof(db, 'SELECT name,reference FROM chunk_assets ORDER BY name'))
        new_marker = dict(version=1, kind='authorized_local_checkpoint_rebind',
            authorization=authorization, at=datetime.now(timezone.utc).isoformat(),
            recovery_tool_sha256=digest(__file__), code=code,
            previous_preparation_binding=old,
            previous_marker_sha256=hashlib.sha256(marker_bytes).hexdigest(),
            previous_continuation_sha256=hashlib.sha256(old_bytes).hexdigest(),
            previous_renderer_binding_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            catalog_identity=renderer['source'], reused_tasks=tasks, preserved_state=preserved,
            compatibility='Exact reviewed fe82754f source-cache optimization. No task, asset, data or chunk-reference rows changed.')
        new_binding = dict(old, code_runtime=identity, provenance_revision=code['target_revision'], checkpoint_reuse=new_marker)
        new_renderer = dict(renderer, preparation=new_binding, requirements=requirements)
        save(root / 'checkpoint-rebind.json', new_marker)
        db.execute('UPDATE build SET binding=?', (canonical_json_bytes(new_renderer).decode(),))
        db.commit()
    # Original marker/binding remain embedded in the new bound provenance chain.
    continuation['binding'] = new_binding
    save(root / RECEIPT, new_marker)
    save(root / 'continuation.json', continuation)
    result = dict(status='rebound_local_checkpoint', directory=str(root),
        target_revision=code['target_revision'], previous_revision=COMPACT_RUNTIME,
        reused_chunks=sum(EXPECTED_CHUNKS.values()), preserved_state=preserved,
        receipt_sha256=digest(root / RECEIPT), continuation_sha256=digest(root / 'continuation.json'))
    save(root / 'checkpoint-rebind-result.json', result)
    return result


def rebind_finished_copy(directory, *, authorization, code, identity, requirements):
    """Re-finalize only control metadata for the characterized finished renderer."""
    root = Path(directory)
    if not authorization.strip() or RECOVERY_READER is None or code.get('reviewed_recovery_revision') != RECOVERY_READER:
        raise ValueError('Finished rebind requires authorization and the final reviewed recovery pin')
    if any((root / name).exists() for name in ('preparation.json','prepared-result.json',
            'publication/recovery-prepared.json','checkpoint-finished-rebind.json')):
        raise ValueError('Accepted preparation or an earlier finished rebind forbids this operation')
    old_bytes = (root / 'continuation.json').read_bytes()
    continuation = json.loads(old_bytes)
    old = continuation['binding']
    marker_bytes = (root / RECEIPT).read_bytes()
    marker = json.loads(marker_bytes)
    previous_result = json.loads((root / 'checkpoint-rebind-result.json').read_bytes())
    if continuation['phases'] or continuation['writes'] or continuation['versions']:
        raise ValueError('Accepted phases or publication state forbid finished rebind')
    if (old['provenance_revision'] != SOURCE_CACHE_RUNTIME or old.get('checkpoint_reuse') != marker
            or marker.get('kind') != 'authorized_local_checkpoint_rebind'
            or marker.get('recovery_tool_sha256') != SOURCE_CACHE_TOOL_SHA256
            or marker['code'].get('target_revision') != SOURCE_CACHE_RUNTIME
            or marker['code'].get('reviewed_source_cache_revision') != SOURCE_CACHE
            or marker['code'].get('target_implementation') != code['source_cache_implementation']
            or old['code_runtime']['implementation'] != code['source_cache_implementation']
            or previous_result.get('status') != 'rebound_local_checkpoint'
            or previous_result.get('target_revision') != SOURCE_CACHE_RUNTIME
            or previous_result.get('receipt_sha256') != hashlib.sha256(marker_bytes).hexdigest()):
        raise ValueError('Finished checkpoint is not the known source-cache adoption')
    for key in ('source','viewer','accepted','native_execution','mode','run_id','run_attempt','publisher_version'):
        if old.get(key) != marker['previous_preparation_binding'].get(key):
            raise ValueError('Protected source/native/run inputs changed')
    if (identity['implementation'] != code['target_implementation']
            or {k:v for k,v in old['code_runtime'].items() if k != 'implementation'}
               != {k:v for k,v in identity.items() if k != 'implementation'}):
        raise ValueError('Finished rebind changed dependencies/runtime/publisher or target code')
    manifest_path = root / 'publication/manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('Finished manifest must remain present for normal restore')
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    database = root / 'publication.renderer-upgrade/stages.sqlite'
    with sqlite3.connect(database, timeout=0) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        before_database_sha = digest(database)
        if before_database_sha != FINISHED_DATABASE_SHA256:
            raise ValueError('Finished database differs from the backed-up checkpoint')
        rows = db.execute('SELECT binding,created FROM build').fetchall()
        if len(rows) != 1:
            raise ValueError('Finished checkpoint requires one renderer binding')
        raw, created = rows[0]
        renderer = json.loads(raw)
        if (renderer['preparation'] != old or renderer['source'] != marker['catalog_identity']
                or renderer['source']['selector_sha256'] != old['source']['sha256']
                or manifest.get('version') != 6 or manifest['source_identity'] != renderer['source']
                or manifest['source_manifest'] != old['source']['value']
                or manifest['requirements'] != renderer['requirements']):
            raise ValueError('Finished renderer/manifest/input bindings differ')
        if ({k:v for k,v in renderer['requirements'].items() if k != 'implementation'}
                != {k:v for k,v in requirements.items() if k != 'implementation'}):
            raise ValueError('Finished rebind changed renderer policy/compression/runtime')
        asset = db.execute("SELECT bytes,sha256 FROM assets WHERE path='manifest.json'").fetchone()
        if asset != (len(manifest_bytes), manifest_sha):
            raise ValueError('Finished manifest custody differs from saved asset')
        removed = dict(db.execute("SELECT task,result FROM progress WHERE task IN ('finished','stage:inventory')"))
        if set(removed) != {'finished','stage:inventory'} or json.loads(removed['finished']) != manifest:
            raise ValueError('Finished task and manifest do not match')
        tasks = dict(db.execute('SELECT task,result FROM progress ORDER BY task'))
        root_stages = {'stage:component_metadata':'components',
                       'stage:source_preparation':'sources','stage:browse_preparation':'browse'}
        for task, name in root_stages.items():
            if task not in tasks or json.loads(tasks[task]) != manifest['roots'][name]:
                raise ValueError('A completed large-stage root differs from finished manifest')
        expected = {'component-registration','stage:component_scope','stage:component_preparation'} | {
            'component-chunk:' + name for name, in db.execute('SELECT name FROM chunks')}
        if dict(db.execute('SELECT label,count(*) FROM chunks GROUP BY label')) != EXPECTED_CHUNKS or not expected <= tasks.keys():
            raise ValueError('Finished checkpoint lost completed chunk/large stages')
        preserved = dict(progress=table_proof(db,
            "SELECT task,result FROM progress WHERE task NOT IN ('finished','stage:inventory') ORDER BY task"),
            assets=table_proof(db,'SELECT path,bytes,sha256 FROM assets ORDER BY path'),
            chunk_assets=table_proof(db,'SELECT name,reference FROM chunk_assets ORDER BY name'))
        new_marker = dict(version=1,kind='authorized_finished_renderer_rebind',
            authorization=authorization,at=datetime.now(timezone.utc).isoformat(),
            recovery_tool_sha256=digest(__file__),code=code,
            previous_preparation_binding=old,previous_marker_sha256=hashlib.sha256(marker_bytes).hexdigest(),
            previous_continuation_sha256=hashlib.sha256(old_bytes).hexdigest(),
            previous_renderer_binding_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            previous_database_sha256=before_database_sha,
            previous_manifest_sha256=manifest_sha,previous_manifest_bytes=len(manifest_bytes),
            removed_task_results=removed,preserved_state=preserved,
            catalog_identity=renderer['source'],
            reused_tasks=sorted(set(tasks)-set(removed)),
            compatibility='Only finished and stage:inventory are invalidated. All payload/root stages and asset rows remain; normal restore verifies old manifest before normal finalization replaces controls.')
        new_binding = dict(old,code_runtime=identity,provenance_revision=code['target_revision'],checkpoint_reuse=new_marker)
        new_renderer = dict(renderer,preparation=new_binding,requirements=requirements)
        save(root / 'checkpoint-finished-rebind.json',new_marker)
        db.execute('UPDATE build SET binding=?',(canonical_json_bytes(new_renderer).decode(),))
        db.execute("DELETE FROM progress WHERE task IN ('finished','stage:inventory')")
        db.commit()
    continuation['binding'] = new_binding
    save(root / RECEIPT,new_marker)
    save(root / 'continuation.json',continuation)
    result = dict(status='rebound_finished_renderer',directory=str(root),
        previous_revision=SOURCE_CACHE_RUNTIME,target_revision=code['target_revision'],
        invalidated_tasks=sorted(removed),preserved_state=preserved,
        manifest_sha256=manifest_sha,receipt_sha256=digest(root / RECEIPT),
        continuation_sha256=digest(root / 'continuation.json'))
    save(root / 'checkpoint-finished-rebind-result.json',result)
    return result


@contextmanager
def authorized_continuation(directory):
    """Explicit local guard override; bind origin evidence into the final receipt."""
    root = Path(directory).resolve()
    if not (root / 'checkpoint-adoption-result.json').is_file():
        raise ValueError('Adoption was not completed; discard/reclone any incomplete copy')
    marker = json.loads((root / RECEIPT).read_bytes())
    if marker.get('kind') == 'authorized_local_checkpoint_rebind' and not (root / 'checkpoint-rebind-result.json').is_file():
        raise ValueError('Rebind did not complete; restore the quiescent checkpoint copy')
    if marker.get('kind') == 'authorized_finished_renderer_rebind' and not (root / 'checkpoint-finished-rebind-result.json').is_file():
        raise ValueError('Finished rebind did not complete; restore the backed-up checkpoint')
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
    parser.add_argument('operation', choices=['adopt', 'rebind', 'rebind-finished', 'resume'])
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
        if args.operation in ('adopt', 'rebind', 'rebind-finished'):
            if not args.authorization:
                parser.error('adopt/rebind requires authorization')
            if args.operation == 'adopt':
                if not args.archive or not args.archive_inventory:
                    parser.error('adopt requires archive and archive-inventory')
                copy = verify_copy(args.archive, args.directory, args.archive_inventory, args.copy_receipt)
            dbpath = args.directory / 'publication.renderer-upgrade/stages.sqlite'
            with sqlite3.connect(dbpath.resolve().as_uri() + '?mode=ro', uri=True) as db:
                previous = json.loads(db.execute('SELECT binding FROM build').fetchone()[0])['requirements']
            requirements = filename_native.native_requirements(filename_viewer,
                DecodedPolicy(**previous['policy']), CompressionPolicy(**previous['compression']))
            options = dict(authorization=args.authorization, code=proof,
                identity=publisher.full_release_identity(), requirements=requirements)
            if args.operation == 'adopt':
                result = adopt_copy(args.directory, **options, copy_proof=copy)
            elif args.operation == 'rebind':
                result = rebind_copy(args.directory, **options)
            else:
                result = rebind_finished_copy(args.directory, **options)
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
