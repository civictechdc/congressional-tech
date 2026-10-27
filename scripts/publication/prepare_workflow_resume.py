"""Validate explicit workflow resume before checkout or workspace setup."""
import importlib.util
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
# Keep bootstrap usable with python -I -S before the workspace is installed.
spec = importlib.util.spec_from_file_location('workflow_resume_validation',
    ROOT / 'packages/viewer_publication/src/viewer_publication/resume.py')
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


def prepare(environment):
    raw = environment.get('RESUME_DESCRIPTOR', '')
    if not raw:
        return {'resume': 'false', 'preparation_resume': 'false'}
    if environment['GITHUB_EVENT_NAME'] != 'workflow_dispatch':
        raise ValueError('Resume descriptor requires an explicit workflow dispatch')
    admitted = raw.encode('utf-8')
    descriptor = validation.parse_resume_descriptor(admitted, allow_preparation=True)
    if descriptor['repository'] != environment['GITHUB_REPOSITORY']:
        raise ValueError('Resume descriptor repository differs from this workflow')
    if descriptor['version'] == 2 and environment.get('GITHUB_SHA') != descriptor['revision']:
        raise ValueError('Dispatch preparation resume at the original code revision; a newer workflow head cannot produce its accepted artifact')
    path = Path(environment['RUNNER_TEMP']) / 'viewer-resume.json'
    # Preserve admitted bytes: JSON re-encoding can expand Unicode or whitespace
    # beyond the same byte limit that the original CLI enforces on this file.
    with path.open('xb') as stream:
        stream.write(admitted)
    checkpoint = descriptor['version'] == 2
    return {'resume': str(not checkpoint).lower(), 'preparation_resume': str(checkpoint).lower(),
        **{name: descriptor[name]
        for name in ('revision', 'run_id', 'artifact_id')}}


def github_json(route):
    raw = subprocess.check_output(['gh', 'api', route], timeout=60)
    if len(raw) > 2 * 1024**2:
        raise ValueError('GitHub checkpoint metadata exceeds byte limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('GitHub checkpoint metadata must be an object')
    return value


def revision():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, timeout=10).strip()


def verify_checkpoint(root, environment):
    descriptor = validation.parse_resume_descriptor(
        (Path(environment['RUNNER_TEMP']) / 'viewer-resume.json').read_bytes(), allow_preparation=True)
    repository = descriptor['repository']
    if repository != environment['GITHUB_REPOSITORY']:
        raise ValueError('Preparation checkpoint repository differs')
    if environment.get('GITHUB_SHA') != descriptor['revision']:
        raise ValueError('Dispatch preparation resume at the original code revision')
    return validation.verify_preparation_checkpoint(root, descriptor,
        metadata=github_json(f"repos/{repository}/actions/artifacts/{descriptor['artifact_id']}"),
        run=github_json(f"repos/{repository}/actions/runs/{descriptor['run_id']}"), revision=revision())


def verify_completed_preparation(root, environment):
    """Use the complete verifier before accepting a stop-boundary result."""
    with tempfile.TemporaryDirectory(prefix='preparation-boundary-', dir=environment['RUNNER_TEMP']) as directory:
        proof = Path(directory) / 'verified.json'
        subprocess.run([sys.executable, str(ROOT / 'scripts/publication/publish-viewer-r2.py'),
            'verify-prepared', '--directory', str(root), '--report', str(proof)],
            cwd=ROOT, env=environment, check=True, timeout=1200)
        verified = json.loads(proof.read_bytes())
    if verified.get('status') != 'verified_prepared':
        raise ValueError('Stop-boundary preparation did not pass complete verification')
    receipt = validation.read_checkpoint_json(root / 'preparation.json')
    producer = receipt.get('artifact_producer', receipt['binding'])
    if (str(producer['run_id']) != environment['GITHUB_RUN_ID']
            or str(producer['run_attempt']) != environment['GITHUB_RUN_ATTEMPT']):
        raise ValueError('Completed preparation belongs to another producer; use its original accepted artifact')
    result = validation.read_checkpoint_json(root / 'prepared-result.json')
    if result.get('status') != 'prepared' or result.get('artifact_name') != verified.get('artifact_name'):
        raise ValueError('Stop-boundary preparation result differs from verification')
    return result


def run_preparation(root, report, *, environment, deadline_seconds=7800, grace_seconds=120):
    """Stop before the job timeout, then freeze partial work for an explicit run."""
    start = json.loads((Path(environment['RUNNER_TEMP']) / 'publication-job-start.json').read_text())['time']
    deadline = start + deadline_seconds
    if deadline <= time.time():
        raise ValueError('Preparation job budget exhausted before launch')
    command = [sys.executable, str(ROOT / 'scripts/publication/publish-viewer-r2.py'),
        'prepare', '--native-config', environment['DOCSPEC_RUNTIME_CONFIG'],
        '--directory', str(root), '--report', str(report)]
    if environment.get('PREPARATION_RESUME') == 'true':
        # Recheck custody immediately before invoking the runtime. The runtime
        # freshly compares inputs and rebases completed output to this run.
        verify_checkpoint(root, environment)
        command.append('--resume-preparation')
    child_env = dict(environment)
    child_env.pop('GITHUB_OUTPUT', None)  # Only the supervisor may authorize later steps.
    if deadline <= time.time():
        raise ValueError('Preparation job budget exhausted before launch')
    stopped = False
    forced = False
    process = subprocess.Popen(command, cwd=ROOT, env=child_env, start_new_session=True)
    try:
        process.wait(timeout=max(0, deadline - time.time()))
    except subprocess.TimeoutExpired:
        stopped = True
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass  # The producer may complete between the deadline and signal.
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            forced = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=30)
    if forced:
        raise ValueError('Preparation did not stop gracefully; checkpoint acceptance refused')
    # No descendants may mutate SQLite or output while it is hashed/uploaded.
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        pass
    else:
        os.killpg(process.pid, signal.SIGKILL)
        raise ValueError('Preparation left running descendants; checkpoint acceptance refused')
    if stopped and all((root / name).is_file() for name in ('preparation.json', 'prepared-result.json')):
        result = verify_completed_preparation(root, child_env)
        report.write_text(json.dumps(result, indent=2) + '\n')
        return result
    if process.returncode == 0 and not stopped:
        result = json.loads(report.read_bytes())
        if result.get('status') not in ('prepared', 'unchanged'):
            raise ValueError('Preparation did not return a complete result')
        return result
    if not stopped:
        raise ValueError('Preparation failed before its bounded stop; inspect the command outcome')
    result = validation.save_preparation_checkpoint(root, revision=revision(),
        run_id=environment['GITHUB_RUN_ID'], run_attempt=environment['GITHUB_RUN_ATTEMPT'],
        repository=environment['GITHUB_REPOSITORY'], workflow_revision=environment['GITHUB_SHA'])
    report.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='admit', choices=('admit', 'run', 'describe-checkpoint'))
    parser.add_argument('--directory', type=Path, default=Path('viewer-preparation'))
    parser.add_argument('--report', type=Path, default=Path('viewer-publication.json'))
    args = parser.parse_args(argv)
    if args.command == 'admit':
        outputs = prepare(os.environ)
    elif args.command == 'run':
        outputs = run_preparation(args.directory.resolve(), args.report.resolve(), environment=os.environ)
    else:
        outputs = validation.preparation_checkpoint_descriptor(args.directory,
            artifact_id=os.environ['ARTIFACT_ID'], artifact_digest=os.environ['ARTIFACT_DIGEST'])
        args.report.write_text(json.dumps(outputs, indent=2) + '\n')
        print(json.dumps(outputs, indent=2))
        return
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for name in ('resume', 'preparation_resume', 'revision', 'run_id', 'artifact_id',
                         'status', 'artifact_name', 'attempt', 'preparation_sha256', 'checkpoint_artifact_name'):
                if name in outputs:
                    stream.write(f'{name}={outputs[name]}\n')


if __name__ == '__main__':
    main()
