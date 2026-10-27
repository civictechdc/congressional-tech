"""Original-attempt selection works before installed packages or mutation clients."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from viewer_publication.resume import parse_resume_descriptor

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'scripts/publication/prepare_workflow_resume.py'


def descriptor():
    return dict(version=1, revision='a' * 40, run_id='123', run_attempt='2',
        artifact_id='456', artifact_digest='b' * 64,
        artifact_name='viewer-prepared-123-2-' + 'c' * 64,
        attempt='123-2-' + 'c' * 64, repository='fixture/repo')


def execute(tmp_path, raw, event='workflow_dispatch', workflow_revision='a' * 40):
    output = tmp_path / 'output'
    env = dict(os.environ, RESUME_DESCRIPTOR=raw, GITHUB_EVENT_NAME=event,
        GITHUB_REPOSITORY='fixture/repo', GITHUB_SHA=workflow_revision, RUNNER_TEMP=str(tmp_path), GITHUB_OUTPUT=str(output))
    result = subprocess.run([sys.executable, '-I', '-S', str(SCRIPT)], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=10)
    return result, output


def test_original_identity_is_validated_without_site_packages(tmp_path):
    value = descriptor()
    result, output = execute(tmp_path, json.dumps(value))
    assert result.returncode == 0, result.stderr
    assert output.read_text().splitlines() == [
        'resume=true', 'preparation_resume=false', 'revision=' + value['revision'], 'run_id=123', 'artifact_id=456']
    assert json.loads((tmp_path / 'viewer-resume.json').read_bytes()) == value


@pytest.mark.parametrize('at_limit', [False, True])
def test_retained_descriptor_preserves_admitted_multibyte_bytes(tmp_path, at_limit):
    value = dict(descriptor(), annotation='é' * 5000)
    raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
    if at_limit:
        raw += b' ' * (16384 - len(raw))
    result, output = execute(tmp_path, raw.decode('utf-8'))
    assert result.returncode == 0, result.stderr
    assert output.read_text().startswith('resume=true\n')
    retained = (tmp_path / 'viewer-resume.json').read_bytes()
    assert retained == raw
    assert parse_resume_descriptor(retained) == value


@pytest.mark.parametrize('raw', [
    '{', '[]', 'null', 'x' * (16 * 1024 + 1),
    json.dumps(descriptor()).replace('"version": 1', '"version": 1, "version": 1'),
    json.dumps(dict(descriptor(), repository='other/repo')),
    json.dumps(dict(descriptor(), revision='main')),
    json.dumps(dict(descriptor(), run_id='999')),
    json.dumps(dict(descriptor(), artifact_id=['456', '457'])),
    json.dumps(dict(descriptor(), artifact_name=['ambiguous'])),
])
def test_invalid_selection_never_emits_checkout_authority(tmp_path, raw):
    result, output = execute(tmp_path, raw)
    assert result.returncode != 0
    assert not output.exists()
    assert not (tmp_path / 'viewer-resume.json').exists()


def test_resume_requires_explicit_dispatch_and_does_not_replace_retained_descriptor(tmp_path):
    result, output = execute(tmp_path, json.dumps(descriptor()), 'schedule')
    assert result.returncode != 0 and not output.exists()
    retained = tmp_path / 'viewer-resume.json'
    retained.write_bytes(b'original evidence')
    result, output = execute(tmp_path, json.dumps(descriptor()))
    assert result.returncode != 0 and not output.exists()
    assert retained.read_bytes() == b'original evidence'


def test_scheduled_fresh_path_needs_no_descriptor_or_package_import(tmp_path):
    result, output = execute(tmp_path, '', 'schedule')
    assert result.returncode == 0, result.stderr
    assert output.read_text() == 'resume=false\npreparation_resume=false\n'
    assert not (tmp_path / 'viewer-resume.json').exists()


def test_descriptor_bound_counts_encoded_bytes_and_refuses_duplicate_fields():
    raw = json.dumps(descriptor()).encode()
    assert parse_resume_descriptor(raw + b' ' * (16384 - len(raw))) == descriptor()
    with pytest.raises(ValueError, match='16 KiB'):
        parse_resume_descriptor(raw + b' ' * (16385 - len(raw)))
    with pytest.raises(ValueError, match='Duplicate'):
        parse_resume_descriptor(raw.replace(b'"artifact_id": "456"',
            b'"artifact_id": "456", "artifact_id": "457"'))










def test_resume_validator_and_bootstrap_are_in_release_identity():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from viewer_release_identity import source_files
    files = source_files(ROOT)
    assert 'packages/viewer_publication/src/viewer_publication/resume.py' in files
    assert 'scripts/publication/prepare_workflow_resume.py' in files




def test_retired_resume_workflow_cannot_dispatch_mutations():
    assert not (ROOT / '.github/workflows/publish-filename-viewer.yml').exists()
    value = yaml.load((ROOT / '.github/workflows/archive-jobs.yml').read_text(), Loader=yaml.BaseLoader)
    assert set(value['on']['workflow_dispatch']['inputs']) == {'operation'}
    assert 'resume_descriptor' not in json.dumps(value)
