"""Prepare, run, inspect, or explicitly resume one local recovery command.

This supervisor records actual child waits. Resume invokes the plan's separate
resume command, whose maintained phase implementation must reconcile writes.
It never infers completion from a missing process or restarts automatically.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temporary.open('x') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def identity(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'pid=,ppid=,lstart=,command='],
                            capture_output=True, text=True, check=False)
    if result.returncode or not result.stdout.strip():
        return None
    fields = result.stdout.strip().split(None, 7)
    if len(fields) != 8:
        raise RuntimeError('Process identity unavailable')
    return dict(pid=int(fields[0]), parent_pid=int(fields[1]), started=' '.join(fields[2:7]), command=fields[7])


def same_process(record):
    return bool(record) and identity(record['pid']) == record


def prepare(destination, *, cwd, command, resume_command=None, pins=(), reserve_bytes=12 * 1024**3):
    destination, cwd = Path(destination).resolve(), Path(cwd).resolve()
    if not cwd.is_dir() or reserve_bytes < 0:
        raise ValueError('Working directory or disk reserve invalid')
    for argv in [command] + ([resume_command] if resume_command else []):
        if (not isinstance(argv, list) or not argv or not all(isinstance(v, str) for v in argv)
                or not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file()):
            raise ValueError('Use an argument list with an absolute executable path')
    hashes = {str(Path(path).resolve()): digest(path) for path in pins}
    plan = dict(version=1, created_at=now(), cwd=str(cwd), command=command,
                resume_command=resume_command, pins=hashes, reserve_bytes=reserve_bytes)
    destination.mkdir(parents=True, exist_ok=False)
    atomic(destination / 'plan.json', plan)
    atomic(destination / 'plan-digest.json', dict(sha256=digest(destination/'plan.json')))
    return plan


def load_plan(destination):
    expected = json.loads((destination/'plan-digest.json').read_text())['sha256']
    if digest(destination/'plan.json') != expected:
        raise ValueError('Run plan changed')
    plan = json.loads((destination/'plan.json').read_text())
    for name, value in plan['pins'].items():
        if digest(name) != value:
            raise ValueError(f'Pinned run input changed: {name}')
    return plan


def status(destination):
    destination = Path(destination).resolve()
    load_plan(destination)
    attempts = sorted(destination.glob('attempt-[0-9][0-9][0-9][0-9]'))
    if not attempts:
        return dict(state='prepared', complete=False, attempts=0)
    latest = attempts[-1]
    start_path = latest/'dispatch.json'
    if not start_path.exists():
        return dict(state='dispatch_incomplete_requires_reconciliation', complete=False, attempts=len(attempts))
    start = json.loads(start_path.read_text())
    supervisor_alive = same_process(start['supervisor'])
    child_alive = same_process(start['child'])
    result = dict(attempt=str(latest), attempts=len(attempts), supervisor_alive=supervisor_alive,
                  child_alive=child_alive, complete=False)
    if (latest/'exit.json').exists():
        end = json.loads((latest/'exit.json').read_text())
        complete = end['actual_child_wait_exit'] == 0 and not child_alive
        result.update(state='exited' if not child_alive else 'inconsistent_requires_reconciliation',
                      complete=complete, actual_child_wait_exit=end['actual_child_wait_exit'])
    else:
        result['state'] = 'running' if supervisor_alive and child_alive else 'requires_reconciliation'
    return result


def reconcile(destination):
    result = status(destination)
    # No success marker is invented when a process disappears without a wait.
    result['reconciled_at'] = now()
    result['remote_state_verified'] = False
    result['next_action'] = ('none' if result['complete'] else
        'wait' if result.get('child_alive') or result.get('supervisor_alive') else
        'explicit_resume_command_must_reconcile_phase_evidence')
    return result


def run(destination, *, resume=False, interval=5):
    destination = Path(destination).resolve()
    plan = load_plan(destination)
    with (destination/'.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = reconcile(destination)
        if before.get('child_alive') or (before.get('supervisor_alive') and 'actual_child_wait_exit' not in before):
            raise RuntimeError('Prior run is still alive')
        if before['attempts']:
            if not resume or not plan['resume_command'] or before['complete']:
                raise RuntimeError('Prior attempt requires an explicit supported resume')
        elif resume:
            raise ValueError('No prior attempt to resume')
        if shutil.disk_usage(plan['cwd']).free < plan['reserve_bytes']:
            raise RuntimeError('Disk reserve unavailable')
        attempt = destination / f"attempt-{before['attempts'] + 1:04d}"
        attempt.mkdir()
        atomic(attempt/'preflight.json', dict(at=now(), prior=before,
               plan_sha256=digest(destination/'plan.json'), resume=resume))
        command = plan['resume_command'] if resume else plan['command']
        supervisor = identity(os.getpid())
        parent = identity(os.getppid())
        stop_reason = None
        with (attempt/'stdout.log').open('xb') as out, (attempt/'stderr.log').open('xb') as err:
            child = subprocess.Popen(command, cwd=plan['cwd'], stdout=out, stderr=err)
            child_identity = identity(child.pid)
            atomic(attempt/'dispatch.json', dict(at=now(), command=command, cwd=plan['cwd'],
                   supervisor=supervisor, child=child_identity, child_pid=child.pid, parent=parent))
            try:
                while child.poll() is None:
                    free = shutil.disk_usage(plan['cwd']).free
                    if not same_process(parent) or free < plan['reserve_bytes']:
                        stop_reason = 'parent_changed' if not same_process(parent) else 'disk_reserve'
                        atomic(attempt/'stop-request.json', dict(at=now(), reason=stop_reason))
                        child.send_signal(signal.SIGINT)
                        break
                    atomic(attempt/'status.json', dict(at=now(), free_disk_bytes=free,
                           child_running=True, child=child_identity))
                    time.sleep(interval)
                code = child.wait()
            except BaseException:
                if child.poll() is None:
                    child.send_signal(signal.SIGINT)
                code = child.wait()
                atomic(attempt/'exit.json', dict(at=now(), actual_child_wait_exit=code,
                       stop_reason='supervisor_interrupted'))
                raise
            atomic(attempt/'exit.json', dict(at=now(), actual_child_wait_exit=code, stop_reason=stop_reason))
            return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'status', 'reconcile', 'resume'])
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--cwd', type=Path)
    parser.add_argument('--command-json', help='JSON array; no shell expansion')
    parser.add_argument('--resume-command-json', help='Separate explicit reconciliation/resume command')
    parser.add_argument('--pin', type=Path, action='append', default=[])
    parser.add_argument('--reserve-gib', type=int, default=12)
    args = parser.parse_args()
    if args.action == 'prepare':
        if args.cwd is None or args.command_json is None:
            parser.error('prepare requires --cwd and --command-json')
        print(json.dumps(prepare(args.destination, cwd=args.cwd, command=json.loads(args.command_json),
            resume_command=json.loads(args.resume_command_json) if args.resume_command_json else None,
            pins=args.pin, reserve_bytes=args.reserve_gib * 1024**3), indent=2))
    elif args.action in {'run', 'resume'}:
        code = run(args.destination, resume=args.action == 'resume')
        raise SystemExit(code if code >= 0 else 128-code)
    else:
        print(json.dumps((status if args.action == 'status' else reconcile)(args.destination), indent=2))
