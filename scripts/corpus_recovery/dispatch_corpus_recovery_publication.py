"""Explicit publication and continuation of an imported recovery batch; no acquisition or raw writes.

Requires an actual completed import. Default mode verifies local evidence only.
The maintained catalog and viewer implementations are loaded from --runtime.
"""
import argparse
import configparser
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


class SelectedRuntime:
    """Select project sources once; refuse an already-bound foreign runtime.

    Third-party dependencies remain owned by the interpreter environment. Project
    packages and filename/control helpers must all belong to --runtime. Never
    evict modules: their callers may still hold objects from the previous owner.
    """
    PACKAGES = {'congress_api': 'packages/congress_api/src',
        'house_naming': 'packages/house-naming/src',
        'congress_shared': 'packages/congress_shared/src',
        'committee_meeting': 'packages/committee_meeting/src',
        'youtube_api': 'packages/youtube_api/src',
        'corpus_recovery': 'packages/corpus_recovery/src',
        'viewer_publication': 'packages/viewer_publication/src',
        'committee_explorer': 'apps/committee_youtube/src'}

    def __init__(self, root):
        self.root = root
        self._checked = {}
        for name, folder in self.PACKAGES.items():
            owner = root / folder / name
            initializer = owner / '__init__.py'
            if (not owner.is_dir() or not initializer.is_file()
                    or not owner.resolve().is_relative_to(root)
                    or not initializer.resolve().is_relative_to(owner.resolve())):
                raise ValueError(f'Selected runtime {root} has missing or escaping required source owner '
                                 f'{name}: expected {owner}. Select a complete runtime checkout.')
        self.sources = [root / folder for folder in self.PACKAGES.values()]
        self.sources += [root / 'apps/site/scripts', root / 'scripts']
        self.check()
        # Path precedence affects only imports that have not happened yet.
        source_paths = [str(path) for path in self.sources]
        sys.path[:] = source_paths + [path for path in sys.path if path not in source_paths]

    def owner(self, name):
        package = name.partition('.')[0]
        if package in self.PACKAGES:
            return self.root / self.PACKAGES[package] / package
        if package == 'filename_viewer':
            return self.root / 'docs/youtube-coverage/research/scripts'
        if package.startswith('filename_') or package in {'recovery_viewer_builder', 'recovery_viewer_publisher'}:
            return self.root / 'apps/site/scripts'
        if package in {'viewer_release_identity', 'publication_preflight'}:
            return self.root / 'scripts'
        if package == 'publication_cli':
            return self.root / 'scripts/publication'

    def check(self, *direct):
        """Verify cached imports and explicit-file modules, including their children."""
        pending = list(sys.modules.items()) + [(module.__name__, module) for module in direct]
        seen = set()
        while pending:
            name, module = pending.pop()
            owner = self.owner(name)
            key = name, id(module)
            if owner is None or key in seen:
                continue
            seen.add(key)
            origin = getattr(module, '__file__', None)
            package_paths = tuple(getattr(module, '__path__', ()))
            observation = module, origin, package_paths
            if self._checked.get(name) != observation:
                resolved_owner = owner.resolve()
                paths = [origin, *package_paths]
                if (not resolved_owner.is_relative_to(self.root) or not origin
                        or any(not Path(path).resolve().is_relative_to(resolved_owner) for path in paths)):
                    raise ValueError(f'Selected runtime {self.root} cannot reuse loaded module {name} '
                                     f'from {origin!r}; expected sources under {owner}. Start a fresh process with --runtime.')
                # Retain the module object too: a recycled id cannot inherit proof.
                self._checked[name] = observation
            # Explicit-file builders keep modules outside sys.modules.
            pending.extend((value.__name__, value) for value in vars(module).values()
                           if isinstance(value, type(sys)))

    def files(self):
        folders = [*self.sources, self.root / 'docs/youtube-coverage/research/scripts']
        # scripts/ contains operational evidence and tests too; pin only helpers
        # used by this route there, rather than unrelated command implementations.
        folders.remove(self.root / 'scripts')
        paths = {path for folder in folders for path in folder.rglob('*')
                 if path.is_file() and '__pycache__' not in path.parts}
        paths.add(self.root / 'scripts/viewer_release_identity.py')
        paths.add(Path(__file__).resolve())
        return paths


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cloud_clear():
    from corpus_recovery.guards import active_cloud_writers
    active_cloud_writers()


def verify_import(batch, imported, *, readiness=None):
    from corpus_recovery.admission import verify_import as verify
    return verify(batch, imported, readiness=readiness)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def publication_conditions(continuation):
    """Persist the first publication conditions separately from advancing versions."""
    conditions = continuation.value.get('publication_inputs')
    if conditions is None:
        conditions = {'previous_etag': continuation.value['versions']['viewer-publications/manifest.json'],
                      'selected_etag': continuation.value['versions']['indexes/catalog.json']}
        continuation.value['publication_inputs'] = conditions
        continuation.flush()
    if (not isinstance(conditions, dict) or set(conditions) != {'previous_etag','selected_etag'}
            or not isinstance(conditions['selected_etag'], str) or not conditions['selected_etag']
            or (conditions['previous_etag'] is not None and not isinstance(conditions['previous_etag'],str))):
        raise ValueError('Malformed original local publication conditions')
    return conditions


def run(args):
    batch, imported, runtime = args.batch.resolve(), args.imported.resolve(), args.runtime.resolve()
    if getattr(args, 'resume', False) and not args.execute:
        raise ValueError('--resume requires --execute')
    readiness = getattr(args, 'readiness', None)
    selected = SelectedRuntime(runtime) if args.execute else None
    result = verify_import(batch, imported, readiness=readiness)
    if not args.execute:
        return dict(local_preflight=True, import_verified=True, writes=False)
    import boto3
    from botocore.config import Config
    # Import the domain dependency closure before the pre-lock owner check.
    # publish_imported binds these names per invocation so injected collaborators
    # do not become cached globals; their source ownership is already checked.
    from congress_api.retention.r2 import R2Store
    from congress_api.retention.catalog_staging import WorkingCatalog
    from congress_api.cli.raw_progress import ProgressLog
    from congress_api.retention.document_index import validate_document_indexes
    from congress_api.retention.catalog_validation import validate_catalog_pair
    from congress_api.retention.raw_catalog import rebuild_catalog_in_directory
    from filename_recoveries import accepted_rows
    from viewer_publication.client import ContinuedPublicationClient
    from corpus_recovery.mappings import publish_mappings
    from viewer_publication.local import LocalContinuation as Continuation
    from corpus_recovery.guards import RecoveryGuard
    import viewer_release_identity
    import corpus_recovery.publication as publication_module
    builder = load(runtime/'apps/site/scripts/publish-filename-viewer.py', 'recovery_viewer_builder')
    publisher = load(runtime/'apps/site/scripts/publish-viewer-r2.py', 'recovery_viewer_publisher')
    selected.check(builder, publisher)
    cloud_clear()
    control_root = (getattr(args, 'control_root', None) or ROOT).resolve()
    lock_path = control_root / '.cache/local-recovery.lock'
    lock = lock_path.open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    destination = args.destination.resolve()
    parent = os.getppid()
    def report(name, value):
        continuation.save(name, (json.dumps(value, indent=2) + '\n').encode())
    def journal(event, value):
        continuation.record(event, value)
    paths = list(selected.files())
    paths += list(batch.glob('*.json')) + list((ROOT/'scripts/corpus_recovery').glob('*.py'))
    import corpus_recovery
    import corpus_recovery.inventory as inventory_module
    import corpus_recovery.acknowledge as acknowledgment_module
    import corpus_recovery.admission as admission_module
    import corpus_recovery.diagnostics as diagnostics_module
    import corpus_recovery.guards as recovery_guard_module
    import corpus_recovery.mappings as mapping_module
    import viewer_publication.client as publication_client
    import viewer_publication.continuation as publication_continuation
    import viewer_publication.local as publication_local
    paths += [Path(corpus_recovery.__file__).resolve(),
              Path(inventory_module.__file__).resolve(),
              Path(publication_client.__file__).resolve(),
              Path(publication_continuation.__file__).resolve(),
              Path(publication_local.__file__).resolve(),
              Path(publication_module.__file__).resolve(),
              Path(acknowledgment_module.__file__).resolve(),
              Path(recovery_guard_module.__file__).resolve(),
              Path(admission_module.__file__).resolve(),
              Path(diagnostics_module.__file__).resolve(),
              Path(mapping_module.__file__).resolve(),
              args.baseline.resolve(), args.config.resolve(),
              imported/'payloads/import-complete.json', imported/'events.jsonl']
    paths += [imported/'payloads'/key for key in ('indexes/captures.parquet', 'indexes/download-state.parquet')]
    if readiness is not None:
        paths += [readiness.resolve()]
        body_readback = readiness.resolve().with_name('remote-body-readback.json')
        if body_readback.exists(): paths += [body_readback]
    pins = {str(p): digest(p) for p in paths}
    binding = dict(pins=pins, batch=str(batch), imported=str(imported), runtime=str(runtime),
                   baseline=str(args.baseline.resolve()), control_root=str(control_root))
    # Include control modules imported while assembling their exact source pins.
    selected.check(builder, publisher)
    continuation = Continuation(destination, binding, resume=getattr(args, 'resume', False))
    save = continuation.save
    report('pins.json', pins)
    config = configparser.ConfigParser(); config.read(args.config); account = config['congressionalraw']
    client = boto3.client('s3', endpoint_url=account['endpoint'], region_name='auto',
        aws_access_key_id=account['access_key_id'], aws_secret_access_key=account['secret_access_key'],
        config=Config(connect_timeout=15, read_timeout=180, retries={'total_max_attempts': 1},
                      request_checksum_calculation='when_required', response_checksum_validation='when_required'))
    bucket = 'congressional-tech-raw'
    protected = ['indexes/captures.parquet', 'indexes/download-state.parquet', 'indexes/catalog.json',
                 'viewer-publications/recoveries/accepted.json', 'viewer-publications/manifest.json']
    versions = continuation.value['versions']
    if not versions:
        baseline_versions = {}
        for key in protected:
            response = client.get_object(Bucket=bucket, Key=key)
            with response['Body'] as stream: raw = stream.read()
            if len(raw) != response['ContentLength']: raise ValueError('Incomplete publication baseline')
            save('baseline/'+key, raw); baseline_versions[key] = response['ETag']
            if key in protected[:2] and raw != (imported/'payloads'/key).read_bytes():
                raise ValueError('Raw indexes changed since completed import; reconcile before publication')
        versions.update(baseline_versions)
        continuation.flush()
    if getattr(args, 'resume', False):
        continuation.reconcile(client, bucket)
    def local_check():
        selected.check(builder, publisher)
        if os.getppid() != parent or shutil.disk_usage(destination).free < 12*1024**3:
            raise RuntimeError('Publication parent or disk reserve changed')
        held, named = os.fstat(lock.fileno()), lock_path.stat()
        if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino): raise RuntimeError('Lock replaced')
    def protected_check():
        for key, version in versions.items():
            if client.head_object(Bucket=bucket, Key=key)['ETag'] != version:
                raise RuntimeError('Publication input changed: '+key)
    guard = RecoveryGuard(pins=pins, local_check=local_check, cloud_check=cloud_clear,
                          protected_check=protected_check)
    proxy = ContinuedPublicationClient(client, continuation=continuation, guard=guard, journal=journal,
                                       after_write=lambda *args: None)
    try:
        return publication_module.publish_imported(client=client, proxy=proxy, guard=guard,
            continuation=continuation, destination=destination, batch=batch,
            baseline=args.baseline, bucket=bucket, imported=result, builder=builder,
            publisher=publisher, publication_conditions=publication_conditions)
    except BaseException as error:
        try:
            observation = diagnostics_module.catalog_build_observation(destination, continuation.value['phases'])
            if observation and observation['state'] == 'incomplete_catalog_requires_reconciliation':
                report('incomplete-catalog.json', observation)
        except (OSError, ValueError) as diagnostic_error:
            error.add_note('Incomplete catalog diagnostic could not be saved: ' + type(diagnostic_error).__name__)
        journal('publication_failed_requires_reconciliation', dict(error_type=type(error).__name__, error=str(error)))
        raise
    finally: lock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['batch','imported','runtime','baseline','destination']:
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--control-root', type=Path, default=ROOT, help='Shared checkout owning the recovery lock across runtimes.')
    parser.add_argument('--config', type=Path, default=ROOT/'.cache/r2-admin/rclone.conf')
    parser.add_argument('--readiness', type=Path, help='Reconciled readiness evidence pinned by the completed import.')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Explicitly reconcile and continue this destination; requires --execute.')
    print(json.dumps(run(parser.parse_args()), indent=2))
