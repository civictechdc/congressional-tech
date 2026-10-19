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


def execute(tmp_path, raw, event='workflow_dispatch'):
    output = tmp_path / 'output'
    env = dict(os.environ, RESUME_DESCRIPTOR=raw, GITHUB_EVENT_NAME=event,
        GITHUB_REPOSITORY='fixture/repo', RUNNER_TEMP=str(tmp_path), GITHUB_OUTPUT=str(output))
    result = subprocess.run([sys.executable, '-I', '-S', str(SCRIPT)], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=10)
    return result, output


def test_original_identity_is_validated_without_site_packages(tmp_path):
    value = descriptor()
    result, output = execute(tmp_path, json.dumps(value))
    assert result.returncode == 0, result.stderr
    assert output.read_text().splitlines() == [
        'resume=true', 'revision=' + value['revision'], 'run_id=123', 'artifact_id=456']
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
    assert output.read_text() == 'resume=false\n'
    assert not (tmp_path / 'viewer-resume.json').exists()


def test_descriptor_bound_counts_encoded_bytes_and_refuses_duplicate_fields():
    raw = json.dumps(descriptor()).encode()
    assert parse_resume_descriptor(raw + b' ' * (16384 - len(raw))) == descriptor()
    with pytest.raises(ValueError, match='16 KiB'):
        parse_resume_descriptor(raw + b' ' * (16385 - len(raw)))
    with pytest.raises(ValueError, match='Duplicate'):
        parse_resume_descriptor(raw.replace(b'"artifact_id": "456"',
            b'"artifact_id": "456", "artifact_id": "457"'))


def workflow():
    return yaml.load((ROOT / '.github/workflows/publish-filename-viewer.yml').read_text(), Loader=yaml.BaseLoader)


def test_workflow_uses_one_validated_selection_and_keeps_unchanged_skip():
    value = workflow()
    assert set(value['on']['workflow_dispatch']['inputs']) == {'resume_descriptor'}
    steps = value['jobs']['publish']['steps']
    admission = next(i for i, step in enumerate(steps) if step.get('id') == 'resume')
    checkout = next(i for i, step in enumerate(steps) if step.get('name') == 'Check out the original preparation revision')
    setup = next(i for i, step in enumerate(steps) if step.get('uses') == './.github/actions/setup-python-project')
    restore = next(i for i, step in enumerate(steps) if step.get('name') == 'Restore explicitly selected preparation')
    verify = next(i for i, step in enumerate(steps) if step.get('name') == 'Verify complete preparation inventory')
    publish = next(i for i, step in enumerate(steps) if step.get('name') == 'Publish accepted preparation')
    assert admission < checkout < setup < restore < verify < publish
    assert steps[checkout]['with']['ref'] == '${{ steps.resume.outputs.revision }}'
    assert steps[restore]['with']['artifact-ids'] == '${{ steps.resume.outputs.artifact_id }}'
    assert steps[restore]['with']['run-id'] == '${{ steps.resume.outputs.run_id }}'
    assert '--resume --resume-descriptor "$RUNNER_TEMP/viewer-resume.json"' in steps[publish]['run']
    assert 'inputs.artifact_id' not in json.dumps(steps)
    assert steps[setup]['if'] == "github.event_name == 'push' || steps.resume.outputs.resume == 'true' || steps.preflight.outputs.status == 'preparation_required'"
    assert next(s for s in steps if s.get('id') == 'preflight')['if'] == "steps.resume.outputs.resume == 'false'"
    assert next(s for s in steps if s.get('id') == 'prepare')['if'] == "steps.resume.outputs.resume == 'false' && steps.preflight.outputs.status == 'preparation_required'"


@pytest.mark.parametrize('historical', [False, True])
def test_workflow_fixture_paths_belong_to_selected_current_or_historical_checkout(tmp_path, historical):
    steps = workflow()['jobs']['publish']['steps']
    script = next(s['run'] for s in steps if s.get('name') == 'Verify publication fidelity and recovery mapping')
    paths = [line.strip() for line in script.splitlines() if line.strip().endswith('.py')]
    expected = [('tests/' + Path(path).name) if historical else path for path in paths]
    for path in expected:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    # Exercise the actual workflow shell; replace only the final interpreter.
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    python = bindir / 'python'
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    python.chmod(0o755)
    result = subprocess.run(['bash', '-e', '-c', script], cwd=tmp_path,
        env=dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH']),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['-m', 'pytest', '-q', *expected]


def test_resume_validator_and_bootstrap_are_in_release_identity():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from viewer_release_identity import source_files
    files = source_files(ROOT)
    assert 'packages/viewer_publication/src/viewer_publication/resume.py' in files
    assert 'scripts/publication/prepare_workflow_resume.py' in files
