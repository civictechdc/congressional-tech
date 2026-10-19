"""Standard-library validation for one original publication attempt."""
import json
import re

MAX_DESCRIPTOR_BYTES = 16 * 1024


def parse_resume_descriptor(raw):
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ValueError('Resume descriptor exceeds 16 KiB limit')

    def unique_fields(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError('Duplicate resume descriptor field: ' + name)
            result[name] = value
        return result

    return validate_resume_descriptor(json.loads(raw, object_pairs_hook=unique_fields))


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
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('Unsupported resume descriptor version')
    for name, pattern in (('revision', r'[a-f0-9]{40}'), ('run_id', r'[0-9]+'),
            ('run_attempt', r'[0-9]+'), ('artifact_id', r'[0-9]+'),
            ('artifact_digest', r'[a-f0-9]{64}'), ('repository', r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')):
        if not isinstance(value.get(name), str) or not re.fullmatch(pattern, value[name]):
            raise ValueError('Invalid resume descriptor field: ' + name)
    name = value.get('artifact_name')
    if not isinstance(name, str):
        raise ValueError('Invalid resume descriptor artifact name')
    match = re.fullmatch(r'viewer-prepared-([0-9]+)-([0-9]+)-([a-f0-9]{64})', name)
    if (not match or match[1] != value['run_id'] or match[2] != value['run_attempt']
            or value.get('attempt') != '-'.join(match.groups())):
        raise ValueError('Resume descriptor attempt/name/run fields differ')
    return value
