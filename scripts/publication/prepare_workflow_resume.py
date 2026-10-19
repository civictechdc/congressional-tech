"""Validate explicit workflow resume before checkout or workspace setup."""
import importlib.util
import os
from pathlib import Path


def prepare(environment):
    raw = environment.get('RESUME_DESCRIPTOR', '')
    if not raw:
        return {'resume': 'false'}
    if environment['GITHUB_EVENT_NAME'] != 'workflow_dispatch':
        raise ValueError('Resume descriptor requires an explicit workflow dispatch')
    root = Path(__file__).resolve().parents[2]
    # Load only the maintained standard-library validator, before packages exist.
    spec = importlib.util.spec_from_file_location('workflow_resume_validation',
        root / 'packages/viewer_publication/src/viewer_publication/resume.py')
    validation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validation)
    admitted = raw.encode('utf-8')
    descriptor = validation.parse_resume_descriptor(admitted)
    if descriptor['repository'] != environment['GITHUB_REPOSITORY']:
        raise ValueError('Resume descriptor repository differs from this workflow')
    path = Path(environment['RUNNER_TEMP']) / 'viewer-resume.json'
    # Preserve admitted bytes: JSON re-encoding can expand Unicode or whitespace
    # beyond the same byte limit that the original CLI enforces on this file.
    with path.open('xb') as stream:
        stream.write(admitted)
    return {'resume': 'true', **{name: descriptor[name]
        for name in ('revision', 'run_id', 'artifact_id')}}


def main():
    outputs = prepare(os.environ)
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
        for name, value in outputs.items():
            stream.write(f'{name}={value}\n')


if __name__ == '__main__':
    main()
