#!/usr/bin/env python3
"""Run the committed archive publish once on this Mac, from a clean checkout of origin/main.

The nightly publish runs here on a launchd schedule, not on a hosted runner (owner decision
2026-11-04, ct-ud0b). Each run updates one dedicated detached worktree to origin/main and
re-executes that worktree's copy of this script, so the code that publishes is always a pushed
commit (gate 5) in a tree with no other work. It then prepares what the hosted job's setup steps
prepare and runs `.github/scripts/run-archive-job.py publish` under its watchdog, with this
Mac's remote runtime and its credentials from `<main>/.cache/archive-release/remote-runtime/`.
When the daily step reports `backfill_required`, it runs the committed backfill job once and
publishes again. A daily stop (`pending`, `backfill_required`, `raw_custody_required`) fails
the publish step, and the run's summary names that status.

Each run keeps its log, watchdog report and publication evidence under
`<main>/.cache/archive-release/nightly/<UTC stamp>/`. One active candidate lives beside the
run directories, outside worktree cleanup. The publisher can reuse it after an interruption
or refusal. Completed and superseded candidates leave their evidence in the run directory.
A directory ending in `-retiring` contains detached work from an interrupted archive or cleanup.
It stays outside automatic reuse. An operator can reclaim it after confirming its evidence is retained.

    python3 scripts/nightly_publish.py --install        # write and load the launchd agent
    python3 scripts/nightly_publish.py --install-watch  # write and load the durable post-run watch agent
    python3 scripts/nightly_publish.py --status         # check durable status/freshness (exit 1 on failed/stale)
    python3 scripts/nightly_publish.py                  # one run now (what launchd calls)
"""
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
import plistlib
import re
import resource
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

LABEL = 'ai.spicygov.archive-nightly'
WATCH_LABEL = 'ai.spicygov.archive-nightly-watch'
DEFAULT_MAX_AGE_HOURS = 30.0
EVIDENCE_MAX_BYTES = 5 * 1024 * 1024
# launchd starts an agent with 256 open files. The model's engine holds scratch files for retained step
# results, its spill directory, the release's output files and the lake readers at once, and the first
# scheduled run to reach the end of the model failed on a late input open (2026-11-10, 'source open failed').
FILE_LIMIT = 65536
DISK = runpy.run_path(str(Path(__file__).with_name('archive_disk.py')))


def raise_file_limit(target=FILE_LIMIT):
    """Raise the soft open-file limit to `target` (or the hard limit, if lower); children inherit it.

    Returns (soft before, soft after). Never lowers a limit and never raises the hard one."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    wanted = target if hard == resource.RLIM_INFINITY else min(target, hard)
    if soft != resource.RLIM_INFINITY and soft < wanted:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (wanted, hard))
        except (ValueError, OSError):
            # macOS refuses a soft limit above kern.maxfilesperproc even under an unlimited hard limit.
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(wanted, 10240), hard))
    return soft, resource.getrlimit(resource.RLIMIT_NOFILE)[0]


def run_owned(command, **options):
    ownership = importlib.util.spec_from_file_location(
        'nightly_process_owner', Path(__file__).with_name('measure') / 'process_rss.py')
    owner = importlib.util.module_from_spec(ownership)
    ownership.loader.exec_module(owner)
    process = owner.start_owned(command, **options)
    try:
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        owner.stop_owned(process)
        if owner._group_is_live(process.pid):
            raise RuntimeError('Nightly process group is still live; retain its spill')


def git(*args, cwd, capture=True, pass_fds=()):
    run = run_owned if pass_fds else subprocess.run
    result = run(['git', *args], cwd=cwd, text=True, pass_fds=pass_fds,
                 stdout=subprocess.PIPE if capture else None)
    result.check_returncode()
    return result.stdout.strip() if capture else ''


def main_checkout(start):
    common = Path(git('rev-parse', '--path-format=absolute', '--git-common-dir', cwd=start))
    return common.parent


def update_worktree(main, worktree, *, pass_fds):
    git('fetch', '--quiet', 'origin', 'main', cwd=main, pass_fds=pass_fds)
    target = git('rev-parse', 'FETCH_HEAD', cwd=main)
    if not (worktree / '.git').exists():
        git('worktree', 'add', '--detach', str(worktree), target, cwd=main, capture=False, pass_fds=pass_fds)
        return target
    dirty = git('--no-optional-locks', 'status', '--porcelain', cwd=worktree)
    if dirty:
        raise SystemExit(f'nightly refused: {worktree} has local changes:\n{dirty}')
    git('checkout', '--quiet', '--detach', target, cwd=worktree, pass_fds=pass_fds)
    return target


def step(name, command, *, cwd, env, log, pass_fds=()):
    started = time.monotonic()
    print(f'== {name}: {" ".join(map(str, command))}', file=log, flush=True)
    code = run_owned(list(map(str, command)), cwd=cwd, env=env, stdout=log,
                     stderr=subprocess.STDOUT, pass_fds=pass_fds).returncode
    print(f'== {name}: exit {code} in {time.monotonic() - started:.0f}s', file=log, flush=True)
    if code:
        raise StepFailed(name, code)


class StepFailed(Exception):
    def __init__(self, name, code):
        super().__init__(f'{name} exited {code}')
        self.name, self.code = name, code


# Owner Decision A1 (ct-64t4): keep 24 GiB / 2 threads on purpose in remote-runtime/limits.json.
# W21 real-lake measurement proved DataFusion's FairSpillPool needs the 24 GiB pool (12 GiB query pool)
# because 12 GiB / 4 threads starved GroupedHashAggregateStream[1] on step 90 "resolved_link_targets" at
# 6.47 GiB RSS, while 24 GiB / 2 threads completed Release 2 cleanly at 9.77 GiB peak RSS — safely below
# the 14 GiB RSS watchdog in .github/archive-jobs.json.
REMOTE_RUNTIME_MEMORY_BYTES = 24 << 30
REMOTE_RUNTIME_THREADS = 2


def publish_env(main, worktree):
    remote_runtime = main / '.cache/archive-release/remote-runtime'
    credentials = json.loads((remote_runtime / 'credentials.json').read_text())
    remote = json.loads((remote_runtime / 'remote.json').read_text())
    runtime_cfg = json.loads((remote_runtime / 'runtime.json').read_text())
    limits_path = Path(runtime_cfg['limits'])
    if not limits_path.is_absolute():
        limits_path = (remote_runtime / limits_path).resolve()
    limits = json.loads(limits_path.read_text())
    if (limits.get('memory_bytes'), limits.get('compute_threads')) != (REMOTE_RUNTIME_MEMORY_BYTES, REMOTE_RUNTIME_THREADS):
        raise SystemExit(
            f'nightly refused: remote-runtime limits must stay {REMOTE_RUNTIME_MEMORY_BYTES} bytes / '
            f'{REMOTE_RUNTIME_THREADS} threads (ct-64t4); got {limits.get("memory_bytes")} / {limits.get("compute_threads")}'
        )
    account = re.fullmatch(r'https://([a-f0-9]{32})\.r2\.cloudflarestorage\.com',
                           remote['properties']['s3.endpoint']).group(1)
    env = dict(os.environ)
    for name in ('PYTHONPATH', 'VIRTUAL_ENV', 'DOCSPEC_JOB_CONFIG', 'DOCSPEC_RUNTIME_CONFIG'):
        env.pop(name, None)
    env.update(
        CLOUDFLARE_ACCOUNT_ID=account,
        R2_ACCESS_KEY_ID=credentials['DOCSPEC_S3_ACCESS_KEY_ID'],
        R2_SECRET_ACCESS_KEY=credentials['DOCSPEC_S3_SECRET_ACCESS_KEY'],
        DOCSPEC_RUNTIME_CONFIG=str(remote_runtime / 'runtime.json'),
        DOCSPEC_JOB_CONFIG=str(worktree / '.cache/local-runtime/runtime.json'),
        CONGRESS_TEXT_INDEX_WORK=str(main / '.cache/archive-release/text-index/work'),
        ARCHIVE_DISK_BUDGETS=os.environ.get('ARCHIVE_DISK_BUDGETS', str(main / '.cache/archive-release/disk-budgets.json')),
    )
    return env


def keep_small_json(output, evidence):
    if not output.is_dir():
        return
    for path in output.rglob('*.json'):
        if path.is_file() and path.stat().st_size <= EVIDENCE_MAX_BYTES:
            target = evidence / path.relative_to(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


ENGINE_LOG_CUT = b'[nightly] the start of this log was not kept; engine-logs.txt in this folder says how much\n'


def keep_engine_logs(output, evidence):
    """A failed candidate's engine logs: newest first, EVIDENCE_MAX_BYTES in all, and never an error.

    The newest log is the failed job's. The log the bound runs out in keeps its tail, where the error is,
    under one marker line; older ones are not kept. `engine-logs.txt` counts what was not kept and names
    each log that could not be read. Keeping evidence must not be able to fail a retirement.
    """
    try:
        logs, notes, kept, lost, lost_bytes, remaining = [], [], 0, 0, 0, EVIDENCE_MAX_BYTES
        for path in output.rglob('engine.log'):
            try:
                status = path.stat()
                logs.append((status.st_mtime_ns, str(path), status.st_size, path))
            except OSError as error:
                lost += 1
                notes.append(f'not kept: {path.relative_to(output)}: {type(error).__name__}: {error.strerror or error}')
        for _, _, size, path in sorted(logs, reverse=True):
            name = path.relative_to(output)
            keep = size if size <= remaining else max(remaining - len(ENGINE_LOG_CUT), 0)
            if size and not keep:  # The bound is spent: this log and every older one go unkept.
                remaining, lost, lost_bytes = 0, lost + 1, lost_bytes + size
                continue
            try:
                target = evidence / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if keep == size:
                    shutil.copy2(path, target)
                    remaining -= size
                else:
                    with path.open('rb') as source, target.open('wb') as cut:
                        source.seek(size - keep)
                        cut.write(ENGINE_LOG_CUT + source.read(keep))
                    remaining, lost_bytes = 0, lost_bytes + size - keep
                    notes.append(f'cut: {name}: the last {keep} of {size} bytes kept')
                kept += 1
            except OSError as error:
                lost, lost_bytes = lost + 1, lost_bytes + size
                notes.append(f'not kept: {name}: {type(error).__name__}: {error.strerror or error}')
        if kept or lost:
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / 'engine-logs.txt').write_text('\n'.join([
                f'[nightly] engine logs: {kept} kept, {lost} not kept; {lost_bytes} bytes not kept', *notes]) + '\n',
                encoding='utf-8')
    except Exception as error:  # Not only OSError: nothing here may stop the retirement that follows.
        print(f'nightly: engine logs not kept: {error!r}', file=sys.stderr)


def daily_summary(candidate):
    report = candidate / 'archive-daily/daily-summary.json'
    if not report.is_file():
        return {}
    value = json.loads(report.read_text())
    if not isinstance(value, dict):
        raise ValueError('Invalid nightly daily summary')
    return value


def daily_status(candidate):
    return daily_summary(candidate).get('status')


def record_daily(summary, candidate):
    """The daily status, and any html_metadata backlog carried to the next night (ct-hiec)."""
    value = daily_summary(candidate)
    summary['daily_status'] = value.get('status')
    if value.get('carried'):
        summary['daily_carried'] = value['carried']


def record_meeting_updates(summary, candidate):
    """The morning report's line (ct-rhqw): the Congress.gov meeting updates the release check cleared
    or stopped, from `meeting-updates.json` beside the gate report. The plain report
    (`meeting-updates.txt`) is kept with the run's evidence."""
    for path in sorted(candidate.glob('archive-publish/candidate-*/meeting-updates.json'),
                       key=lambda p: (p.stat().st_mtime_ns, p.name)):
        summary['meeting_updates'] = json.loads(path.read_text()).get('line')


def recoverable(candidate):
    publish = candidate / 'archive-publish'
    return (publish / 'completed-model.json').exists() or (
        (publish / 'model-intent.json').exists() and (candidate / 'archive-release/manifest.json').exists())


CAUSE_RECORD_PATHS = ('model/jobs/release-causes/', '.tickets/', 'docs/')


def only_cause_records(worktree, old, new):
    """True when two commits differ only in what a reviewed release cause adds.

    Gate 1 refuses a candidate until its cause record is committed, and that commit moves HEAD.
    The publisher's own resume checks (model definitions, daily heads, continuation identity)
    ignore these paths, so a completed model survives them (ct-n5ec). `publish.json` may differ
    only in its `release_causes` pin.
    """
    if re.fullmatch('[0-9a-f]{40}', old) is None:
        return False
    try:
        names = git('diff', '--name-only', old, new, cwd=worktree).splitlines()
        for name in names:
            if name.startswith(CAUSE_RECORD_PATHS):
                continue
            if name != 'model/jobs/publish.json':
                return False
            specs = [json.loads(git('show', f'{commit}:{name}', cwd=worktree)) for commit in (old, new)]
            for spec in specs:
                spec.pop('release_causes', None)
            if specs[0] != specs[1]:
                return False
    except (subprocess.CalledProcessError, ValueError):
        return False
    return bool(names)


def archive_candidate(candidate, evidence, *, failed=False):
    # Detach the active name before cleanup. A stopped cleanup leaves an archive
    # under this run, never a partially deleted candidate eligible for resume.
    retired = candidate.rename(evidence.with_name(evidence.name + '-retiring'))
    # Mirror relative paths for diagnostics. Absolute pins identify the former active tree.
    try:
        completed = daily_status(retired) == 'completed'
    except (OSError, ValueError):
        completed = False
    if not completed:
        keep_small_json(retired / 'archive-daily', evidence / 'archive-daily')
    for pattern in ('commit', 'inputs-changed.json', 'archive-daily/daily-summary.json',
                    'archive-release/manifest.json', 'archive-model/result.json', 'archive-model/admission/result.json',
                    'archive-publish/*model*.json', 'archive-publish/outgoing-pointer*.json',
                    'archive-publish/publication-assets.json',
                    'archive-publish/contract.json', 'archive-publish/canary.json',
                    'archive-publish/probe-*/contract.json', 'archive-publish/probe-*/canary.json',
                    'producer-proof/*/*/job.json', 'producer-proof/*/*/result.json',
                    'archive-publish/candidate-*/release-gate.json',
                    'archive-publish/candidate-*/automatic/automatic-trace.json',
                    'archive-publish/candidate-*/meeting-updates.*'):
        for path in retired.glob(pattern):
            target = evidence / path.relative_to(retired)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    if failed:
        keep_engine_logs(retired, evidence)
    shutil.rmtree(retired)


def clean_native_spill(main, *, execute=False):
    """The same nightly lock excludes live writers during dry run and retirement."""
    nightly = main / '.cache/archive-release/nightly'
    if not nightly.exists():
        return dict(status='dry-run', paths=[])
    with (nightly / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Native spill cleanup refused: another nightly process holds the lock') from None
        return DISK['retire_spill'](nightly / 'candidate', execute=execute)


def record_native_spill(candidate, report):
    try:
        result = DISK['retire_spill'](candidate, execute=True)
    except (OSError, ValueError) as error:
        result = dict(status='retained', reason=str(error))
    report.write_text(json.dumps(result, indent=2) + '\n')


def setup_roots(worktree, evidence, env):
    def tool_path(command):
        return Path(subprocess.run(command, env=env, capture_output=True, text=True, check=True,
                                   timeout=15, cwd=worktree).stdout.strip())
    browsers = env.get('PLAYWRIGHT_BROWSERS_PATH')
    if browsers == '0':
        browser_root = worktree / 'apps/site/node_modules/playwright-core/.local-browsers'
    else:
        cache = Path.home() / ('Library/Caches' if sys.platform == 'darwin' else '.cache')
        browser_root = Path(browsers) if browsers else cache / 'ms-playwright'
    roots = dict(checkout=worktree, evidence=evidence, home=Path.home(), browsers=browser_root,
                 temp=Path(env.get('TMPDIR') or tempfile.gettempdir()),
                 uv_cache=tool_path(['uv', 'cache', 'dir']), npm_cache=tool_path(['npm', 'config', 'get', 'cache']))
    model_path = worktree / 'model/jobs/publish-model.json'
    model = DISK['metadata'](model_path)
    if model.get('spicy_regs'):
        roots['spicy_regs'] = (model_path.parent / model['spicy_regs']['path']).parent
    return roots


def run(worktree, prepare_only, *, lock_fd=None):
    main = main_checkout(worktree)
    nightly = main / '.cache/archive-release/nightly'
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence = nightly / stamp
    evidence.mkdir(parents=True)
    head = git('rev-parse', 'HEAD', cwd=worktree)
    env = publish_env(main, worktree)
    env['RUNNER_TEMP'] = str(evidence)
    # One step log per run, beside its other evidence: the engine appends to this path and a passing
    # run otherwise leaves no step sizes or times.
    env.setdefault('DOCSPEC_STEP_LOG', str(evidence / 'steps.jsonl'))
    python = worktree / '.venv/bin/python'
    summary = dict(started=stamp, commit=head, worktree=str(worktree), open_files=raise_file_limit()[1])
    candidate = nightly / 'candidate'
    changed = candidate / 'inputs-changed.json'
    backfill = worktree / 'output/archive-backfill'
    lock_args = [] if lock_fd is None else ['--nightly-lock-fd', str(lock_fd)]
    pass_fds = () if lock_fd is None else (lock_fd,)
    with (evidence / 'log.txt').open('w') as log:
        def run_step(name, command, *, step_env=env):
            step(name, command, cwd=worktree, env=step_env, log=log, pass_fds=pass_fds)

        def admit_job(name, operation, *, mode=None):
            binding = DISK['metadata'](worktree / '.github/archive-jobs.json')[operation]
            admission = DISK['job_admission'](worktree, operation, worktree / binding['spec'],
                temp=evidence, nightly_work=candidate if operation == 'publish' else None,
                env=env, commit=head, mode=mode)
            (evidence / (name + '-disk-admission.json')).write_text(json.dumps(admission, indent=2) + '\n')
            print(json.dumps(dict(disk_admission=admission)), file=log, flush=True)
            if admission['status'] != 'admitted':
                raise StepFailed(name + ' disk admission', 2)

        try:
            roots = {}
            try:
                roots = setup_roots(worktree, evidence, env)
                admission = DISK['admit'](env.get('ARCHIVE_DISK_BUDGETS', main / '.cache/archive-release/disk-budgets.json'),
                    'setup', roots, commit=head, root=worktree)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                admission = dict(status='refused', operation='setup', reason=str(error),
                                 roots={name: str(path) for name, path in roots.items()})
            (evidence / 'setup-disk-admission.json').write_text(json.dumps(admission, indent=2) + '\n')
            print(json.dumps(dict(disk_admission=admission)), file=log, flush=True)
            if admission['status'] != 'admitted':
                raise StepFailed('setup disk admission', 2)
            run_step('uv sync', ['uv', 'sync', '--frozen'])
            run_step('MCP index runtime', ['uv','sync','--frozen','--python','3.12.13','--project','apps/explorer_mcp'])
            run_step('npm ci', ['npm', '--prefix', 'apps/site', 'ci'])
            run_step('browser', ['node', 'apps/site/node_modules/playwright/cli.js', 'install', '--only-shell', 'chromium'])
            run_step('local runtime', [python, 'scripts/dev.py', 'write-local-runtime', '--limits',
                                   '.github/docspec-local-limits.json', '--out', '.cache/local-runtime/runtime.json'])
            run_step('doctor', [python, 'scripts/dev.py', 'doctor'])
            run_step('spicy-regs', [python, '-I', '-m', 'viewer_publication.spicy_regs_inputs',
                                '--model-spec', 'model/jobs/publish-model.json'])
            run_step('site build', ['npm', '--prefix', 'apps/site', 'run', 'build'])
            dirty = git('--no-optional-locks', 'status', '--porcelain', cwd=worktree)
            if dirty:
                print(f'== setup left the worktree dirty, which gate 5 refuses:\n{dirty}', file=log, flush=True)
                raise StepFailed('clean tree', 1)
            if not prepare_only:
                publish = [python, '-I', '.github/scripts/run-archive-job.py', 'publish',
                           '--nightly-work', candidate, *lock_args]
                if candidate.exists():
                    commit = candidate / 'commit'
                    if changed.is_file():
                        reason = json.loads(changed.read_text())['reason']
                    elif not commit.is_file() or not (
                            commit.read_text().strip() == head or (recoverable(candidate) and only_cause_records(
                                worktree, commit.read_text().strip(), head))):
                        reason = 'Selected code commit changed'
                    elif not recoverable(candidate):
                        reason = 'Previous attempt has no completed model'
                    else:
                        reason = None
                        summary['resumed'] = True
                    if reason:
                        admit_job('fresh-candidate', 'publish', mode='publish-fresh')
                        summary['fresh_reason'] = reason
                        archive_candidate(candidate, evidence / 'previous-candidate', failed=True)
                def publish_step(name, *, initial=False):
                    resuming = recoverable(candidate)
                    admit_job(name.replace(' ', '-'), 'publish')
                    if not candidate.exists():
                        candidate.mkdir()
                        (candidate / 'commit').write_text(head + '\n')
                    step_env = env if initial else dict(env, RUNNER_TEMP=str(evidence / name.replace(' ', '-')))
                    quiescent = False
                    try:
                        run_step(name, publish, step_env=step_env)
                        quiescent = True
                    except StepFailed:
                        quiescent = True
                        if initial and changed.is_file():
                            return
                        if resuming or daily_status(candidate) != 'backfill_required':
                            raise
                    finally:
                        # step() has waited for the entire owned process group. Its
                        # inherited lock remains held through this retirement.
                        if lock_fd is not None and quiescent:
                            record_native_spill(candidate, evidence / (name.replace(' ', '-') + '-native-spill.json'))

                publish_step('publish', initial=True)
                if changed.is_file():
                    admit_job('changed-candidate', 'publish', mode='publish-fresh')
                    summary['fresh_reason'] = json.loads(changed.read_text())['reason']
                    archive_candidate(candidate, evidence / 'superseded-candidate')
                    publish_step('publish with current inputs')
                if daily_status(candidate) == 'backfill_required':
                    admit_job('before-backfill', 'backfill')
                    summary['daily_status_before_backfill'] = 'backfill_required'
                    archive_candidate(candidate, evidence / 'candidate-before-backfill')
                    if backfill.exists() or backfill.is_symlink():
                        if backfill.is_symlink():
                            raise ValueError('Expected the original nightly backfill work directory')
                        # No backfill resume is declared by this job. Preserve all
                        # prior work in durable custody instead of git-cleaning it.
                        backfill.rename(evidence / 'previous-backfill')
                        summary['retained_previous_backfill'] = str(evidence / 'previous-backfill')
                    quiescent = False
                    try:
                        run_step('backfill', [python, '-I', '.github/scripts/run-archive-job.py', 'backfill', *lock_args])
                        quiescent = True
                    except StepFailed:
                        quiescent = True
                        raise
                    finally:
                        keep_small_json(backfill, evidence / 'backfill')
                        if lock_fd is not None and quiescent:
                            record_native_spill(backfill, evidence / 'backfill-native-spill.json')
                    publish_step('publish after backfill')
                    if daily_status(candidate) == 'backfill_required':
                        raise StepFailed('publish after backfill', 2)
                record_daily(summary, candidate)
                record_meeting_updates(summary, candidate)
                archive_candidate(candidate, evidence / 'candidate')
            summary.update(status='prepared' if prepare_only else 'ok', exit=0)
        except StepFailed as failure:
            summary.update(status='failed', step=failure.name, exit=failure.code)
        except (OSError, ValueError, RuntimeError) as failure:
            summary.update(status='failed', step='wrapper', exit=2, reason=str(failure))
            print(str(failure), file=log, flush=True)
        finally:
            if not prepare_only and candidate.exists():
                summary['retained_candidate'] = str(candidate)
                try:
                    record_daily(summary, candidate)
                    record_meeting_updates(summary, candidate)
                except (OSError, ValueError) as error:
                    summary['daily_summary_error'] = str(error)
            summary['finished'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            summary_path = evidence / 'summary.json'
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
            record_run_state(nightly, summary, summary_path=summary_path, prepare_only=prepare_only)
            if not prepare_only and summary.get('exit', 1) != 0:
                notify_failure(main, summary)
    print(json.dumps(summary, sort_keys=True))
    return summary['exit']


def _atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)


def record_run_state(nightly_dir, summary, *, summary_path, prepare_only=False):
    """Persist durable latest-summary and last-failure pointers across restarts (ct-b7bv)."""
    if prepare_only:
        return
    try:
        entry = dict(summary, summary_path=str(summary_path))
        _atomic_json(nightly_dir / 'latest-summary.json', entry)
        failure_path = nightly_dir / 'last-failure.json'
        if summary.get('exit', 1) != 0:
            _atomic_json(failure_path, entry)
        else:
            failure_path.unlink(missing_ok=True)
    except OSError as error:
        print(f'nightly: run state not recorded: {error!r}', file=sys.stderr)


def _parse_utc_stamp(text):
    for fmt in ('%Y%m%dT%H%M%S.%fZ', '%Y%m%dT%H%M%SZ'):
        try:
            return datetime.datetime.strptime(text, fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    raise ValueError(f'Invalid nightly UTC stamp: {text!r}')


def _lock_is_held(lock_path):
    if not lock_path.is_file():
        return False
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock, fcntl.LOCK_UN)
        return False


def _latest_recorded_summary(nightly_dir):
    pointer = nightly_dir / 'latest-summary.json'
    if pointer.is_file():
        return json.loads(pointer.read_text(encoding='utf-8'))
    if not nightly_dir.is_dir():
        return None
    stamp_re = re.compile(r'^\d{8}T\d{6}(?:\.\d+)?Z$')
    candidates = sorted(
        (child for child in nightly_dir.iterdir()
         if child.is_dir() and stamp_re.match(child.name) and (child / 'summary.json').is_file()),
        key=lambda path: path.name,
        reverse=True,
    )
    if not candidates:
        return None
    summary_path = candidates[0] / 'summary.json'
    return dict(json.loads(summary_path.read_text(encoding='utf-8')), summary_path=str(summary_path))


def notify_failure(main, summary, *, reason=None):
    """Best-effort failure/staleness notification across webhook, command, and macOS alert (ct-b7bv)."""
    delivered = {}
    config = {}
    config_path = main / '.cache/archive-release/remote-runtime/notify.json'
    try:
        if config_path.is_file():
            loaded = json.loads(config_path.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                config = loaded
    except (OSError, ValueError) as error:
        delivered['config_error'] = f'{type(error).__name__}: {error}'

    message = reason or summary.get('reason') or f"step {summary.get('step', 'nightly')} exited {summary.get('exit', 1)}"
    payload = dict(summary, reason=message)
    webhook_url = os.environ.get('ARCHIVE_NIGHTLY_WEBHOOK_URL') or config.get('webhook_url')
    command = os.environ.get('ARCHIVE_NIGHTLY_NOTIFY_COMMAND') or config.get('command')
    macos_enabled = config.get('macos_notification', sys.platform == 'darwin')
    if os.environ.get('ARCHIVE_NIGHTLY_NO_MACOS_NOTIFY') == '1':
        macos_enabled = False

    if webhook_url:
        try:
            body = json.dumps(payload, sort_keys=True).encode('utf-8')
            request = urllib.request.Request(
                webhook_url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=15):
                delivered['webhook'] = 'sent'
        except Exception as error:
            delivered['webhook_error'] = f'{type(error).__name__}: {error}'
            print(f'nightly: webhook notification failed: {error!r}', file=sys.stderr)

    if command:
        try:
            argv = shlex.split(command) if isinstance(command, str) else list(map(str, command))
            subprocess.run(argv, input=json.dumps(payload, sort_keys=True) + '\n',
                           text=True, capture_output=True, timeout=30, check=True)
            delivered['command'] = 'sent'
        except Exception as error:
            delivered['command_error'] = f'{type(error).__name__}: {error}'
            print(f'nightly: command notification failed: {error!r}', file=sys.stderr)

    if macos_enabled and shutil.which('osascript'):
        try:
            subprocess.run(
                ['osascript', '-e',
                 'on run argv\ndisplay notification (item 1 of argv) with title "Archive nightly publish"\nend run',
                 message],
                capture_output=True, text=True, timeout=10, check=True)
            delivered['macos'] = 'sent'
        except Exception as error:
            delivered['macos_error'] = f'{type(error).__name__}: {error}'
    return delivered


def check_status(main, *, max_age_hours=DEFAULT_MAX_AGE_HOURS, notify=False, now=None):
    """Inspect durable nightly state; return (report, exit_code) where exit_code != 0 needs attention."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    nightly_dir = main / '.cache/archive-release/nightly'
    running = _lock_is_held(nightly_dir / 'lock')
    try:
        latest = _latest_recorded_summary(nightly_dir)
        if latest is not None and not isinstance(latest, dict):
            raise ValueError('latest nightly summary must be a JSON object')
        last_failure_path = nightly_dir / 'last-failure.json'
        last_failure = json.loads(last_failure_path.read_text(encoding='utf-8')) if last_failure_path.is_file() else None
        if last_failure is not None and not isinstance(last_failure, dict):
            raise ValueError('last-failure.json must be a JSON object')
        stamp = (latest.get('finished') or latest.get('started')) if latest else None
        age_hours = round((now - _parse_utc_stamp(stamp)).total_seconds() / 3600.0, 2) if stamp else None
    except (OSError, ValueError, TypeError) as error:
        reason = f'corrupt nightly state: {type(error).__name__}: {error}'
        report = dict(status='failed', running=running, max_age_hours=max_age_hours, reason=reason)
        if notify:
            report['notified'] = notify_failure(main, report, reason=reason)
        return report, 1

    if running:
        return dict(status='running', running=True, latest=latest), 0
    if latest is None:
        report = dict(status='missing', running=False, max_age_hours=max_age_hours,
                      reason='no nightly summary recorded')
        if notify:
            report['notified'] = notify_failure(main, report, reason=report['reason'])
        return report, 1

    if last_failure is not None or latest.get('exit', 1) != 0 or latest.get('status') not in ('ok', 'prepared'):
        failed = last_failure or latest
        reason = f"last nightly failed at step {failed.get('step', 'unknown')} (exit {failed.get('exit', 1)})"
        report = dict(status='failed', running=False, age_hours=age_hours, max_age_hours=max_age_hours,
                      latest=latest, last_failure=failed, reason=reason)
        if notify:
            report['notified'] = notify_failure(main, failed, reason=reason)
        return report, 1

    if age_hours is None or age_hours > max_age_hours:
        reason = f'last nightly ok summary is {age_hours}h old (max {max_age_hours}h)'
        report = dict(status='stale', running=False, age_hours=age_hours, max_age_hours=max_age_hours,
                      latest=latest, reason=reason)
        if notify:
            report['notified'] = notify_failure(main, latest, reason=reason)
        return report, 1

    return dict(status='ok', running=False, age_hours=age_hours, max_age_hours=max_age_hours, latest=latest), 0


def real_tool(name):
    found = shutil.which(name)
    if found and '/.pyenv/shims/' in found:
        found = subprocess.run(['pyenv', 'which', name], text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
    return found


def install(main, hour, minute):
    names = ('pdfinfo', 'uv', 'node', 'git')
    tools = [real_tool(name) for name in names]
    if not all(tools):
        raise SystemExit('nightly install refused: ' + ', '.join(names) + ' must be on PATH')
    path = list(dict.fromkeys([str(Path(tool).parent) for tool in tools] + ['/usr/bin', '/bin', '/usr/sbin', '/sbin']))
    logs = main / '.cache/archive-release/nightly'
    logs.mkdir(parents=True, exist_ok=True)
    agent = dict(
        Label=LABEL,
        ProgramArguments=['/usr/bin/python3', str(main / 'scripts/nightly_publish.py')],
        WorkingDirectory=str(main),
        EnvironmentVariables=dict(PATH=':'.join(path), HOME=str(Path.home())),
        StartCalendarInterval=dict(Hour=hour, Minute=minute),
        StandardOutPath=str(logs / 'launchd.out.log'),
        StandardErrorPath=str(logs / 'launchd.err.log'),
        # Standard, not Background: a background agent runs at priority 4 on the efficiency cores, which
        # made the scheduled build take 46 minutes against 25 from a shell (2026-11-10).
        ProcessType='Standard',
        SoftResourceLimits=dict(NumberOfFiles=FILE_LIMIT),
    )
    target = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
    target.write_bytes(plistlib.dumps(agent))
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], stderr=subprocess.DEVNULL)
    subprocess.run(['launchctl', 'bootstrap', domain, str(target)], check=True)
    print(json.dumps(dict(installed=str(target), schedule=f'{hour:02d}:{minute:02d} local', path=agent['EnvironmentVariables']['PATH'])))
    return 0


def install_watch(main, hour, minute, max_age_hours=DEFAULT_MAX_AGE_HOURS):
    """Install a durable launchd watcher that checks nightly freshness/outcome across app restarts."""
    git_tool = real_tool('git')
    if not git_tool:
        raise SystemExit('nightly watch install refused: git must be on PATH')
    path = list(dict.fromkeys([str(Path(git_tool).parent), '/usr/bin', '/bin', '/usr/sbin', '/sbin']))
    logs = main / '.cache/archive-release/nightly'
    logs.mkdir(parents=True, exist_ok=True)
    agent = dict(
        Label=WATCH_LABEL,
        ProgramArguments=[
            '/usr/bin/python3', str(main / 'scripts/nightly_publish.py'),
            '--status', '--notify', '--max-age-hours', str(max_age_hours),
        ],
        WorkingDirectory=str(main),
        EnvironmentVariables=dict(PATH=':'.join(path), HOME=str(Path.home())),
        StartCalendarInterval=dict(Hour=hour, Minute=minute),
        StandardOutPath=str(logs / 'watch.out.log'),
        StandardErrorPath=str(logs / 'watch.err.log'),
        ProcessType='Standard',
    )
    target = Path.home() / 'Library/LaunchAgents' / f'{WATCH_LABEL}.plist'
    target.write_bytes(plistlib.dumps(agent))
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{domain}/{WATCH_LABEL}'], stderr=subprocess.DEVNULL)
    subprocess.run(['launchctl', 'bootstrap', domain, str(target)], check=True)
    print(json.dumps(dict(installed=str(target), schedule=f'{hour:02d}:{minute:02d} local', max_age_hours=max_age_hours)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--install', action='store_true', help='Write and load the launchd agent, then exit')
    parser.add_argument('--install-watch', action='store_true',
                        help='Write and load the durable launchd post-run watcher agent, then exit')
    parser.add_argument('--status', action='store_true',
                        help='Check durable nightly status and freshness (exit 0 when healthy/running, 1 otherwise)')
    parser.add_argument('--notify', action='store_true',
                        help='With --status, send a failure/staleness notification when attention is required')
    parser.add_argument('--max-age-hours', type=float, default=DEFAULT_MAX_AGE_HOURS,
                        help='Maximum hours since the last ok summary before --status reports stale')
    parser.add_argument('--hour', type=int, default=5)
    parser.add_argument('--minute', type=int, default=30)
    parser.add_argument('--watch-hour', type=int, default=8)
    parser.add_argument('--watch-minute', type=int, default=30)
    parser.add_argument('--prepare', action='store_true', help='Run every setup step but not the publish')
    parser.add_argument('--in-worktree', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--lock-fd', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    here = Path(__file__).resolve().parents[1]
    main_root = main_checkout(here)
    if args.install:
        return install(main_root, args.hour, args.minute)
    if args.install_watch:
        return install_watch(main_root, args.watch_hour, args.watch_minute, args.max_age_hours)
    if args.status:
        report, code = check_status(main_root, max_age_hours=args.max_age_hours, notify=args.notify)
        print(json.dumps(report, sort_keys=True))
        return code
    before, after = raise_file_limit()
    if before != after:
        print(f'nightly: open-file limit raised from {before} to {after}', file=sys.stderr)
    worktree = main_root / '.claude/worktrees/nightly'
    lock_path = main_root / '.cache/archive-release/nightly/lock'
    if args.lock_fd is not None:
        if not args.in_worktree or not os.path.samestat(os.fstat(args.lock_fd), lock_path.stat()):
            parser.error('expected the inherited nightly lock')
        return run(here, args.prepare, lock_fd=args.lock_fd)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('nightly refused: another run holds the lock', file=sys.stderr)
            return 3
        if args.in_worktree:
            return run(here, args.prepare, lock_fd=lock.fileno())
        update_worktree(main_root, worktree, pass_fds=(lock.fileno(),))
        # The publishing child and watchdog keep the lock if their launcher exits first.
        return subprocess.run([sys.executable, str(worktree / 'scripts/nightly_publish.py'), '--in-worktree',
                               '--lock-fd', str(lock.fileno()), *(['--prepare'] if args.prepare else [])],
                              cwd=worktree, pass_fds=(lock.fileno(),)).returncode


if __name__ == '__main__':
    raise SystemExit(main())
