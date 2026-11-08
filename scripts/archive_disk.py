"""Disk admission and retirement of declared, private native spill. Standard library only.

Budgets are operator-qualified whole-operation measurements, never inferred from
engine limits or a watchdog floor. Admission does not allocate space or exclude
unrelated writers; the runtime disk floor remains necessary.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit

METADATA_LIMIT = 8 * 1024 * 1024
DISK_FLOOR = 15 * 2**30
# A budget measured at one revision stays valid for a descendant that leaves
# these untouched: the engine, its limits, the job bindings and the installed
# dependencies. Ticket, doc and model commits keep it; the 15 GiB headroom and
# the runtime disk floor cover model drift.
RESOURCE_PATHS = ('model/docspec-runtime-pin.json', '.github/docspec-local-limits.json',
                  '.github/archive-jobs.json', 'uv.lock', 'apps/site/package-lock.json')


def metadata(path):
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(METADATA_LIMIT + 1)
    if len(raw) > METADATA_LIMIT:
        raise ValueError(f'Disk metadata exceeds {METADATA_LIMIT} bytes: {path}')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f'Expected disk metadata object: {path}')
    return value


def revision(root):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True,
                          text=True, check=True, timeout=15).stdout.strip()


def existing_parent(path):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    if not path.is_dir():
        raise ValueError(f'Expected a directory for disk admission: {path}')
    return path


def resource_pins_unchanged(root, measured, commit):
    def ok(*args):
        return subprocess.run(['git', *args], cwd=root, capture_output=True, timeout=15).returncode == 0
    return (ok('merge-base', '--is-ancestor', measured, commit)
            and ok('diff', '--quiet', measured, commit, '--', *RESOURCE_PATHS))


def admit(budgets, operation, roots, *, commit, floor=DISK_FLOOR, root=None):
    """Check each writing filesystem once, before the operation has side effects."""
    try:
        value = metadata(budgets)
    except FileNotFoundError:
        raise ValueError(f'Disk budget unavailable for {operation}: {budgets}') from None
    budget = value.get('operations', {}).get(operation)
    if value.get('version') != 1 or not isinstance(budget, dict):
        raise ValueError(f'Disk budget unavailable for {operation}: {budgets}')
    measured = budget.get('revision')
    if measured != commit and not (root is not None and isinstance(measured, str)
                                   and resource_pins_unchanged(root, measured, commit)):
        raise ValueError(f'Disk budget revision differs for {operation} in {", ".join(RESOURCE_PATHS)}')
    for field in ('measurement', 'workload'):
        if not isinstance(budget.get(field), str) or not budget[field].strip():
            raise ValueError(f'Disk budget needs {field} for {operation}')
    groups = budget.get('filesystems')
    if not isinstance(groups, list) or not groups:
        raise ValueError(f'Disk budget needs filesystems for {operation}')
    paths = {name: existing_parent(path) for name, path in roots.items()}
    covered, devices, observations = set(), set(), []
    for group in groups:
        names = group.get('roots') if isinstance(group, dict) else None
        if (not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names)
                or len(set(names)) != len(names) or set(names) - paths.keys() or covered.intersection(names)):
            raise ValueError(f'Disk budget has invalid or duplicate roots for {operation}')
        peak, headroom = group.get('peak_additional_bytes'), group.get('headroom_bytes')
        if type(peak) is not int or peak <= 0 or type(headroom) is not int or headroom < max(1, floor):
            raise ValueError(f'Disk budget needs measured additional bytes and headroom for {operation}')
        selected = {paths[name].stat().st_dev for name in names}
        if len(selected) != 1 or selected.intersection(devices):
            raise ValueError('Disk budget must group all roots on each actual filesystem exactly once')
        device = selected.pop()
        free = min(shutil.disk_usage(paths[name]).free for name in names)
        observations.append(dict(roots={name: str(roots[name]) for name in names}, device=device,
                                 free_bytes=free, required_bytes=peak + headroom,
                                 peak_additional_bytes=peak, headroom_bytes=headroom))
        covered.update(names)
        devices.add(device)
    if covered != paths.keys():
        raise ValueError('Disk budget does not cover every writing root: ' + ', '.join(sorted(paths.keys() - covered)))
    report = dict(operation=operation, revision=commit, budget_revision=measured, measurement=budget['measurement'],
                  workload=budget['workload'], filesystems=observations)
    report['status'] = 'admitted' if all(row['free_bytes'] >= row['required_bytes'] for row in observations) else 'refused'
    return report


def job_roots(operation, spec_path, *, temp, nightly_work=None, env=None):
    """Read bounded configuration metadata without importing a producer or runtime."""
    spec_path = Path(spec_path).resolve()
    env = os.environ if env is None else env
    spec = metadata(spec_path)
    def local(value, base=spec_path.parent):
        path = Path(value)
        return path if path.is_absolute() else base / path
    # RUNNER_TEMP owns reports; Python's host logs and producer-version trees
    # use tempfile's selected directory, which may be on another filesystem.
    roots = dict(work=local(spec['work']), temp=Path(temp), python_temp=Path(tempfile.gettempdir()))
    explicit_config = local(spec['engine_config']) if spec.get('engine_config') else None
    catalog = spec.get('catalog_root')
    if isinstance(catalog, str) and not urlsplit(catalog).scheme:
        roots['catalog'] = local(catalog)
    mode = operation
    if operation == 'publish':
        model_path = local(spec['model_spec']['path'])
        model = metadata(model_path)
        explicit_config = local(model['engine_config'], model_path.parent)
        roots.update(model_output=local(model['output'], model_path.parent),
                     model_scratch=local(model['scratch'], model_path.parent))
        if spec.get('daily'):
            daily_path = local(spec['daily']['path'])
            roots['daily'] = local(metadata(daily_path)['work'], daily_path.parent)
        if nightly_work is not None:
            candidate = Path(nightly_work)
            roots.update(work=candidate / 'archive-publish', model_output=candidate / 'archive-release',
                         model_scratch=candidate / 'archive-model', daily=candidate / 'archive-daily')
            resume = (roots['work'] / 'completed-model.json').exists() or (
                (roots['work'] / 'model-intent.json').exists() and (roots['model_output'] / 'manifest.json').exists())
        else:
            resume = spec.get('resume', False)
        mode = 'publish-resume' if resume else 'publish-fresh'
        if model.get('text_index'):
            roots['text_index'] = Path(env.get('CONGRESS_TEXT_INDEX_WORK') or
                                       local(model['text_index']['work'], model_path.parent))
        roots['startup'] = roots['work'].parent
    if explicit_config is not None and explicit_config.exists():
        config = metadata(explicit_config)
        if config.get('workspace'):
            roots['engine_workspace'] = local(config['workspace'], explicit_config.parent)
    for name in ('DOCSPEC_JOB_CONFIG', 'DOCSPEC_RUNTIME_CONFIG'):
        if env.get(name):
            config = metadata(env[name])
            if config.get('workspace'):
                roots[name.lower()] = local(config['workspace'], Path(env[name]).resolve().parent)
    return mode, roots


def job_admission(root, operation, spec, *, temp, nightly_work=None, env=None, commit=None, mode=None):
    env = os.environ if env is None else env
    roots = {}
    try:
        selected, roots = job_roots(operation, spec, temp=temp, nightly_work=nightly_work, env=env)
        budgets = Path(env.get('ARCHIVE_DISK_BUDGETS', Path(root) / '.cache/archive-release/disk-budgets.json'))
        return admit(budgets, mode or selected, roots, commit=commit or revision(root), root=root)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return dict(status='refused', operation=mode or operation, reason=str(error),
                    roots={name: str(path) for name, path in roots.items()})


def private_path(path, root):
    """Refuse aliases, including aliases in ancestors that do not exist yet."""
    if '..' in Path(path).parts:
        raise ValueError(f'Native spill path contains parent traversal: {path}')
    path, root = Path(os.path.abspath(path)), Path(os.path.abspath(root))
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f'Native spill escapes its owned candidate: {path}')
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f'Native spill path contains a symlink: {path}')
    return path


def referenced_paths(value, base, key=None):
    if isinstance(value, dict):
        for field, child in value.items():
            yield from referenced_paths(child, base, field)
    elif isinstance(value, list):
        for child in value:
            yield from referenced_paths(child, base, key)
    elif isinstance(value, str):
        if value.startswith('/'):
            yield key, Path(value).resolve()
        elif value.startswith('file://'):
            yield key, Path(unquote(urlsplit(value).path)).resolve()
        elif key in {'path', 'local_root', 'catalog_root', 'location', 'workspace'} and not urlsplit(value).scheme:
            yield key, (base / value).resolve()


def spill_plan(candidate):
    """Inspect only job declarations and checkpoint references in one owned candidate.

    The caller holds the nightly lock after the entire owned process group exits.
    Never descend into native spill or open payloads and native result reports.
    """
    candidate = Path(os.path.abspath(candidate))
    if candidate.is_symlink() or any(p.is_symlink() for p in candidate.parents):
        raise ValueError('Expected the original nightly candidate')
    jobs, references, metadata_bytes = [], [], 0
    for directory, dirs, files in os.walk(candidate, followlinks=False):
        parent = Path(directory)
        for name in dirs:
            if (parent / name).is_symlink():
                raise ValueError(f'Candidate contains a directory alias: {parent / name}')
        dirs[:] = [name for name in dirs if name != 'native']
        for name in ('job.json', 'completed-model.json', 'model-intent.json'):
            if name not in files:
                continue
            path = private_path(parent / name, candidate)
            metadata_bytes += path.stat().st_size
            if metadata_bytes > 64 * 1024 * 1024:
                raise ValueError('Too much metadata for bounded spill inspection')
            value = metadata(path)
            if name == 'job.json' and 'scratch' in value:
                spill = private_path(value['scratch'], candidate)
                if spill != parent / 'native':
                    raise ValueError(f'Unknown native scratch layout: {path}')
                jobs.append(spill)
                value = {k: v for k, v in value.items() if k != 'scratch'}
            references.extend((name, key, ref) for key, ref in referenced_paths(value, parent))
            if len(jobs) > 10000:
                raise ValueError('Too many native jobs for bounded spill inspection')
    targets = []
    for spill in sorted(set(jobs)):
        if any((ref == spill or ref.is_relative_to(spill) or spill.is_relative_to(ref))
               and not (name != 'job.json' and key == 'scratch' and ref == spill.parent)
               for name, key, ref in references):
            raise ValueError(f'Native spill overlaps a retained reference: {spill}')
        if spill.exists():
            if not spill.is_dir():
                raise ValueError(f'Expected a native spill directory: {spill}')
            for directory, dirs, files in os.walk(spill, followlinks=False):
                if any((Path(directory) / name).is_symlink() for name in dirs + files):
                    raise ValueError(f'Native spill contains a symlink: {spill}')
            targets.append(spill)
    return targets


def retire_spill(candidate, *, execute=False):
    # Validate every target before deleting any. A malformed/unknown job retains all.
    targets = spill_plan(candidate)
    if execute:
        for path in targets:
            shutil.rmtree(path)
    return dict(status='retired' if execute else 'dry-run', paths=[str(path) for path in targets])
