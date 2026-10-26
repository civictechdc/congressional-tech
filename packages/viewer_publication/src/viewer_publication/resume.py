"""Standard-library validation for one original publication attempt."""
import json
import re
import hashlib
from pathlib import Path

MAX_DESCRIPTOR_BYTES = 16 * 1024


def parse_resume_descriptor(raw, *, allow_preparation=False):
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ValueError('Resume descriptor exceeds 16 KiB limit')

    def unique_fields(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError('Duplicate resume descriptor field: ' + name)
            result[name] = value
        return result

    value = validate_resume_descriptor(json.loads(raw, object_pairs_hook=unique_fields))
    if value['version'] == 2 and not allow_preparation:
        raise ValueError('Incomplete checkpoint descriptor is preparation-only; it cannot authorize publication')
    return value


def resume_descriptor(artifact, run, repository):
    name = artifact.get('name', '')
    match = re.fullmatch(r'viewer-prepared-([0-9]+)-([0-9]+)-([a-f0-9]{64})', name)
    if not match or match[1] != str(run.get('id')):
        raise ValueError('Artifact name does not identify the original preparation run')
    result = {'version': 1, 'revision': run.get('head_sha'), 'run_id': str(run['id']),
              'run_attempt': match[2], 'artifact_id': str(artifact.get('id', '')),
              'artifact_digest': artifact.get('digest', '').removeprefix('sha256:'),
              'artifact_name': name, 'attempt': '-'.join(match.groups()), 'repository': repository}
    return validate_resume_descriptor(result)


def validate_resume_descriptor(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] not in (1, 2):
        raise ValueError('Unsupported resume descriptor version')
    checkpoint = value['version'] == 2
    if checkpoint and value.get('kind') != 'preparation_checkpoint':
        raise ValueError('Unsupported preparation resume kind')
    for name, pattern in (('revision', r'[a-f0-9]{40}'), ('run_id', r'[0-9]+'),
            ('run_attempt', r'[0-9]+'), ('artifact_id', r'[0-9]+'),
            ('artifact_digest', r'[a-f0-9]{64}'), ('repository', r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')):
        if not isinstance(value.get(name), str) or not re.fullmatch(pattern, value[name]):
            raise ValueError('Invalid resume descriptor field: ' + name)
    name = value.get('artifact_name')
    if not isinstance(name, str):
        raise ValueError('Invalid resume descriptor artifact name')
    prefix = 'viewer-preparation-checkpoint' if checkpoint else 'viewer-prepared'
    match = re.fullmatch(prefix + r'-([0-9]+)-([0-9]+)-([a-f0-9]{64})', name)
    if (not match or match[1] != value['run_id'] or match[2] != value['run_attempt']
            or value.get('attempt') != '-'.join(match.groups())):
        raise ValueError('Resume descriptor attempt/name/run fields differ')
    if checkpoint:
        for key in ('original_run_id', 'original_run_attempt'):
            if not isinstance(value.get(key), str) or not re.fullmatch(r'[0-9]+', value[key]):
                raise ValueError('Invalid preparation origin field: ' + key)
        if not isinstance(value.get('workflow_revision'), str) or not re.fullmatch(r'[a-f0-9]{40}', value['workflow_revision']):
            raise ValueError('Invalid preparation workflow revision')
    return value


CHECKPOINT_FILE = 'workflow-checkpoint.json'
# Match the maintained continuation's capacity, including its input binding.
MAX_CHECKPOINT_BYTES = 128 * 1024**2
# Publication inventory permits 131,072 files; retain working state alongside it.
MAX_CHECKPOINT_FILES = 131072 + 1024


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_checkpoint_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_CHECKPOINT_BYTES + 1)
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise ValueError('Preparation checkpoint receipt exceeds byte limit')
    return json.loads(raw)


def checkpoint_inventory(root):
    """Hash quiescent local work; it is evidence for resuming, never acceptance."""
    root = Path(root)
    if root.is_symlink():
        raise ValueError('Preparation checkpoint directory is a symbolic link')
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Preparation checkpoint contains a symbolic link')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Preparation checkpoint contains a special file')
        name = path.relative_to(root).as_posix()
        if name == CHECKPOINT_FILE:
            continue
        files[name] = {'bytes': path.stat().st_size, 'sha256': file_digest(path)}
        if len(files) > MAX_CHECKPOINT_FILES:
            raise ValueError('Preparation checkpoint exceeds file limit')
    return files


def require_incomplete_preparation(root, state):
    root = Path(root)
    if all((root / name).is_file() for name in ('preparation.json', 'prepared-result.json')):
        raise ValueError('Complete preparation cannot be advertised as an incomplete checkpoint')
    stages = root / 'publication.renderer-upgrade/stages.sqlite'
    if 'prepared' not in state.get('phases', {}) and (stages.is_symlink() or not stages.is_file()):
        raise ValueError('Diagnostic-only stop: preparation has no retained renderer stages')


def save_preparation_checkpoint(root, *, revision, run_id, run_attempt, repository, workflow_revision=None):
    root = Path(root)
    state = read_checkpoint_json(root / 'continuation.json')
    require_incomplete_preparation(root, state)
    binding = state['binding']
    if binding.get('provenance_revision') != revision:
        raise ValueError('Preparation checkpoint revision differs from its original code')
    if state.get('writes') or state.get('versions'):
        raise ValueError('Preparation checkpoint cannot contain publication writes')
    for key in ('code_runtime', 'source', 'viewer', 'accepted', 'native_execution'):
        if not isinstance(binding.get(key), dict):
            raise ValueError('Preparation checkpoint lacks input binding: ' + key)
    value = {'version': 1, 'status': 'incomplete_preparation', 'binding': binding,
             'custody': {'revision': revision, 'run_id': str(run_id),
                         'run_attempt': str(run_attempt), 'repository': repository,
                         'workflow_revision': workflow_revision or revision},
             'files': checkpoint_inventory(root)}
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise ValueError('Preparation checkpoint receipt exceeds byte limit')
    path = root / CHECKPOINT_FILE
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(raw)
    temporary.replace(path)
    return {'status': 'preparation_checkpoint', 'checkpoint_artifact_name':
            f'viewer-preparation-checkpoint-{run_id}-{run_attempt}-{hashlib.sha256(raw).hexdigest()}'}


def preparation_checkpoint_descriptor(root, *, artifact_id, artifact_digest):
    root = Path(root)
    receipt = read_checkpoint_json(root / CHECKPOINT_FILE)
    custody = receipt['custody']
    suffix = f"{custody['run_id']}-{custody['run_attempt']}-{file_digest(root / CHECKPOINT_FILE)}"
    return validate_resume_descriptor(dict(version=2, kind='preparation_checkpoint',
        **custody, artifact_id=str(artifact_id), artifact_digest=artifact_digest.removeprefix('sha256:'),
        artifact_name='viewer-preparation-checkpoint-' + suffix, attempt=suffix,
        original_run_id=receipt['binding']['run_id'], original_run_attempt=receipt['binding']['run_attempt']))


def verify_preparation_checkpoint(root, descriptor, *, metadata, run, revision):
    """Require the selected immutable artifact, exact code, and every saved byte."""
    descriptor = validate_resume_descriptor(descriptor)
    if descriptor['version'] != 2:
        raise ValueError('Preparation resume requires an incomplete checkpoint descriptor')
    if (revision != descriptor['revision'] or run.get('head_sha') != descriptor['workflow_revision']
            or str(run.get('id')) != descriptor['run_id']
            or run.get('head_repository', {}).get('full_name') != descriptor['repository']):
        raise ValueError('Preparation checkpoint GitHub run or revision differs')
    if (str(metadata.get('id')) != descriptor['artifact_id']
            or metadata.get('expired') is not False
            or metadata.get('name') != descriptor['artifact_name']
            or metadata.get('digest', '').removeprefix('sha256:') != descriptor['artifact_digest']
            or str(metadata.get('workflow_run', {}).get('id')) != descriptor['run_id']):
        raise ValueError('Preparation checkpoint artifact custody differs')
    root = Path(root)
    expected = preparation_checkpoint_descriptor(root, artifact_id=descriptor['artifact_id'],
        artifact_digest=descriptor['artifact_digest'])
    if expected != descriptor:
        raise ValueError('Preparation checkpoint receipt differs from selected descriptor')
    receipt = read_checkpoint_json(root / CHECKPOINT_FILE)
    state = read_checkpoint_json(root / 'continuation.json')
    require_incomplete_preparation(root, state)
    if (receipt.get('version') != 1 or receipt.get('status') != 'incomplete_preparation'
            or state['binding'] != receipt['binding'] or state.get('writes') or state.get('versions')
            or receipt['binding'].get('provenance_revision') != revision):
        raise ValueError('Preparation checkpoint original inputs or publication state differ')
    if checkpoint_inventory(root) != receipt['files']:
        raise ValueError('Preparation checkpoint saved files differ')
    # The runtime must freshly read and compare source/config/control identities
    # to this original binding before continuing. Custody alone is not acceptance.
    return receipt
