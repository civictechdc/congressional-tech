"""Disk admission and retirement of declared, private native spill. Standard library only.

Budgets are operator-qualified whole-operation measurements, never inferred from
engine limits or a watchdog floor. Admission does not allocate space or exclude
unrelated writers; the runtime disk floor remains necessary.
"""
from hashlib import sha256
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
        explicit_config = local(model['engine_config'], model_path.parent) if model.get('engine_config') else None
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


def _file_digest(path):
    digest = sha256()
    size = 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return dict(sha256=digest.hexdigest(), bytes=size)


def _tree_digests(folder):
    entries = {}
    if not folder.is_dir():
        return entries
    for directory, _dirs, files in os.walk(folder, followlinks=False):
        parent = Path(directory)
        for name in sorted(files):
            item = parent / name
            entries[item.relative_to(folder).as_posix()] = _file_digest(item)
    return dict(sorted(entries.items()))


def retire_model_build(build, *, execute=False):
    """Record release/evidence digests and remove private output/scratch of a model-only build (ct-arlk)."""
    raw = Path(build)
    if raw.is_symlink() or not raw.is_dir():
        raise ValueError(f'Expected an existing model-only build directory, not a symlink: {build}')
    build = Path(os.path.abspath(raw))
    if build.is_symlink() or any(p.is_symlink() for p in build.parents):
        raise ValueError(f'Model-only build path contains a symlink: {build}')
    for forbidden in ('archive-publish', 'archive-daily'):
        entry = build / forbidden
        if entry.exists() or entry.is_symlink():
            raise ValueError(f'Expected a model-only build folder, not a publish or daily candidate: {build}')
    spec_path = private_path(build / 'model-spec.json', build)
    if not spec_path.is_file():
        raise ValueError(f'Model-only build folder lacks model-spec.json: {build}')
    spec = metadata(spec_path)
    if (
        not isinstance(spec.get('output'), str)
        or not isinstance(spec.get('scratch'), str)
        or private_path(spec['output'], build) != build / 'archive-release'
        or private_path(spec['scratch'], build) != build / 'archive-model'
    ):
        raise ValueError(f'model-spec.json does not own archive-release and archive-model inside {build}')

    targets = []
    reclaimable = 0
    for name in ('archive-model', 'archive-release', 'ledger', 'workspace'):
        target = build / name
        if target.is_symlink():
            raise ValueError(f'Model build target is a symlink: {target}')
        if not target.exists():
            continue
        if not target.is_dir():
            raise ValueError(f'Expected a directory in model build: {target}')
        for directory, dirs, files in os.walk(target, followlinks=False):
            parent = Path(directory)
            for child in dirs + files:
                member = parent / child
                if member.is_symlink():
                    raise ValueError(f'Model build contains a symlink: {member}')
            for child in files:
                reclaimable += (parent / child).stat().st_size
        targets.append(target)

    digest_path = private_path(build / 'retired-build-digests.json', build)
    prior = metadata(digest_path) if digest_path.is_file() else {}
    release_dir = build / 'archive-release'
    model_dir = build / 'archive-model'
    release_id = prior.get('release_id')
    if (release_dir / 'manifest.json').is_file():
        manifest = metadata(private_path(release_dir / 'manifest.json', build))
        release_id = manifest.get('release_id', release_id)

    keep_steps = (model_dir / 'steps.jsonl').is_file() and not (build / 'steps.jsonl').exists()
    if keep_steps:
        reclaimable = max(0, reclaimable - (model_dir / 'steps.jsonl').stat().st_size)

    if execute and targets:
        record = dict(
            version=1,
            release_id=release_id,
            archive_release=_tree_digests(release_dir) if release_dir.is_dir() else prior.get('archive_release', {}),
            evidence=_tree_digests(model_dir / 'evidence') if (model_dir / 'evidence').is_dir() else prior.get('evidence', {}),
            artifacts={
                name: _file_digest(model_dir / name)
                for name in ('job.json', 'result.json')
                if (model_dir / name).is_file()
            } or prior.get('artifacts', {}),
        )
        if keep_steps:
            steps_dst = private_path(build / 'steps.jsonl', build)
            shutil.copy2(model_dir / 'steps.jsonl', steps_dst)
        fd, tmp_name = tempfile.mkstemp(prefix='.retired-build-', suffix='.json', dir=build)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(record, handle, indent=2, sort_keys=True)
                handle.write('\n')
            os.replace(tmp_name, digest_path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        for target in targets:
            shutil.rmtree(target)

    return dict(
        status='retired' if execute else 'dry-run',
        build=str(build),
        release_id=release_id,
        paths=[str(path) for path in targets],
        reclaimable_bytes=reclaimable,
        digests=str(digest_path) if digest_path.is_file() else None,
    )
