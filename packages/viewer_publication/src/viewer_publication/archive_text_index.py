"""Attach the complete MCP text derivative before model checkpoint identity is frozen."""
from contextlib import closing
from hashlib import sha256, md5
import json
from pathlib import Path
import re
import sqlite3
import subprocess

from congress_shared.custody import write_atomic_bytes

INDEX_NAME = 'search_index.sqlite'


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def source_data_id(manifest):
    value = {key: value for key, value in manifest.items() if key not in ('release_id', 'text_index', 'published_at')}
    value['files'] = [item for item in manifest['files'] if item['name'] != INDEX_NAME]
    return sha256(_encoded(value)).hexdigest()


def validate_policy(value, base):
    fields = {'python', 'work', 'archive_origin', 'definition', 'body_timeout', 'memory_mb', 'max_work_bytes'}
    if not isinstance(value, dict) or not fields<=value.keys() or set(value)-fields-{'min_free_bytes','snapshot_mode','large_memory_mb'}:
        raise ValueError('text_index requires an explicit app interpreter, work, origin, definition and resource policy')
    from urllib.parse import urlsplit
    origin = urlsplit(value['archive_origin'])
    if origin.scheme != 'https' or not origin.netloc or origin.path not in ('', '/') or origin.query or origin.fragment or origin.username or origin.password:
        raise ValueError('text_index archive_origin requires an HTTPS origin without credentials')
    if not re.fullmatch('[a-f0-9]{64}', str(value['definition'])):
        raise ValueError('text_index requires a portable preparation policy or qualified runtime definition SHA-256')
    if type(value['memory_mb']) is not int or not 128 <= value['memory_mb'] <= 16384:
        raise ValueError('text_index child memory must be 128..16384 MiB')
    if type(value['body_timeout']) not in (int, float) or not 1 <= value['body_timeout'] <= 600:
        raise ValueError('text_index body timeout must be 1..600 seconds')
    if type(value['max_work_bytes']) is not int or value['max_work_bytes'] < 512 << 20:
        raise ValueError('text_index requires a positive explicit work disk budget')
    if type(value.get('min_free_bytes',15<<30)) is not int or value.get('min_free_bytes',15<<30)<0:
        raise ValueError('text_index free-space floor must be a nonnegative byte count')
    if value.get('snapshot_mode','freeze') not in ('freeze','copy'):
        raise ValueError('text_index snapshot mode requires freeze or explicitly admitted copy')
    # Preserve the venv executable symlink: resolving it selects another package runtime.
    executable = str((Path(base) / value['python']).absolute())
    if not Path(executable).is_file():
        raise ValueError('text_index app interpreter is unavailable')
    return dict(value, python=executable, work=str((Path(base) / value['work']).resolve()),min_free_bytes=value.get('min_free_bytes',15<<30),snapshot_mode=value.get('snapshot_mode','freeze'),large_memory_mb=value.get('large_memory_mb',4096))


def _command(policy):
    return [policy['python'],'-m','congressional_explorer_mcp.cli','index-text',
        '--work',policy['work'],'--archive-origin',policy['archive_origin'],'--definition',policy['definition'],
        '--body-timeout',str(policy['body_timeout']),'--memory-mb',str(policy['memory_mb']),
        '--large-memory-mb',str(policy.get('large_memory_mb',4096)),
        '--max-work-bytes',str(policy['max_work_bytes']),'--min-free-bytes',str(policy.get('min_free_bytes',15<<30)),
        '--snapshot-mode',policy.get('snapshot_mode','freeze')]


def _admit(policy):
    plan=subprocess.run([*_command(policy),'--plan'],capture_output=True,text=True,check=True)
    definition=json.loads(plan.stdout)['definition']
    if policy['definition'] not in (definition['sha256'],definition.get('policy_sha256')):
        raise ValueError('Pinned MCP app extraction definition changed before text preparation')
    return definition


def semantic_policy(policy):
    # Admission precedes the publication input digest and durable intent. A portable
    # policy may admit distinct qualified runtimes; actual facts stay explicit.
    definition=_admit(policy)
    facts=definition.get('facts',{})
    return dict({key:policy[key] for key in ('definition','body_timeout','memory_mb','max_work_bytes')},
        large_memory_mb=policy.get('large_memory_mb',4096),runtime_definition=definition['sha256'],
        runtime={key:facts[key] for key in ('python','sqlite','pypdf','fonttools','pdf_reader') if key in facts})


def validate_attachment(manifest, directory, expected_definition=None):
    info = manifest.get('text_index')
    if not info or info.get('source_data_id') != source_data_id(manifest):
        raise ValueError('Required corpus text index is missing or identifies different source data')
    if expected_definition is not None and expected_definition not in (info.get('definition'),info.get('policy_definition')):
        raise ValueError('Corpus text index extraction definition differs from the publication profile')
    entry = next((item for item in manifest['files'] if item['name'] == INDEX_NAME), None)
    if entry is None or entry.get('producer') != 'verified-corpus-text-index':
        raise ValueError('Required corpus text index asset is missing or has no derived origin')
    path = Path(directory) / INDEX_NAME
    if path.is_symlink() or not path.is_file():
        raise ValueError('Corpus text index asset is unavailable or a symlink')
    with closing(sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True)) as db:
        row = db.execute("SELECT value FROM meta WHERE key='artifact'").fetchone()
    artifact = json.loads(row[0]) if row else {}
    if artifact.get('state') != 'complete' or artifact.get('pending_bodies') != 0 or artifact.get('source_data_id') != info['source_data_id'] or artifact.get('definition', {}).get('sha256') != info['definition']:
        raise ValueError('Corpus text index has incomplete or mismatched preparation evidence')
    return info


def finish_text_index(model_spec, directory):
    policy = model_spec.get('text_index')
    manifest_path = Path(directory) / 'manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    if policy is None:
        return manifest
    if manifest.get('text_index'):
        validate_attachment(manifest, directory, policy['definition'])
        return manifest
    actual_definition=_admit(policy)
    command=[*_command(policy),'--manifest',str(manifest_path)]
    artifact_path = Path(directory) / INDEX_NAME
    if artifact_path.exists():
        # A process may die after writing the immutable snapshot but before attachment.
        with closing(sqlite3.connect(f'file:{artifact_path}?mode=ro&immutable=1', uri=True)) as db:
            report = json.loads(db.execute("SELECT value FROM meta WHERE key='artifact'").fetchone()[0])
    else:
        result = subprocess.run([*command, '--output', str(artifact_path)], capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
    if report['source_data_id'] != source_data_id(manifest) or report['state'] != 'complete' or report['pending_bodies'] != 0 or report['definition']['sha256'] != actual_definition['sha256']:
        raise ValueError('Prepared corpus index differs from the exact native model outputs')
    # Reuse the app owner's close/hash result while custody remains exact.
    accepted=report.get('artifact')
    if accepted:
        stat=artifact_path.stat()
        current=[stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns]
        if accepted.get('stamp')!=current or accepted.get('size')!=stat.st_size or not re.fullmatch('[a-f0-9]{64}',str(accepted.get('sha256',''))) or not re.fullmatch('[a-f0-9]{32}',str(accepted.get('md5',''))):
            raise ValueError('Prepared text index custody changed after its owner pinned the closed bytes')
    digest, checksum = sha256(), md5()
    if accepted is None:
        with artifact_path.open('rb') as source:
            while block := source.read(1 << 20):
                digest.update(block); checksum.update(block)
        accepted=dict(sha256=digest.hexdigest(),md5=checksum.hexdigest())
    manifest['files'].append(dict(name=INDEX_NAME, sha256=accepted['sha256'], md5=accepted['md5'],
        size=artifact_path.stat().st_size, rows=0, producer='verified-corpus-text-index', coverage=report['coverage']))
    manifest['text_index'] = dict(version=1, source_data_id=report['source_data_id'], definition=actual_definition['sha256'],policy_definition=actual_definition.get('policy_sha256',actual_definition['sha256']),
                                  coverage=report['coverage'], origin='verified archived bodies and retained caption resources')
    from viewer_publication.archive_format import release_identity
    manifest['release_id'] = release_identity(manifest['schema_version'], manifest['files'])
    validate_attachment(manifest, directory, policy['definition'])
    write_atomic_bytes(manifest_path, _encoded(manifest), fsync_dir=True)
    return manifest
