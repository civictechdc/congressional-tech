"""Replay complete retained receipt owners through the maintained source policy."""
from contextlib import closing
from dataclasses import dataclass
import json
from hashlib import sha256
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path

import pyarrow.parquet as pq

from . import document_index as index
from .catalog_staging import WorkingCatalog, DiskRows
from .derived_files import file_identity
from .immutable_metadata import encoded
from .raw_values import NATIVE_CAPTURE_SCHEMA
from .source_capture_inputs import SourceCaptureInputs
from .source_observations import SourceObservationTrace


def retain_source_seeds(working, values):
    """Spool ordered seed input and preserve its existing canonical fingerprint."""
    rows, digest = DiskRows(working.connection, 'requested_seeds'), sha256(b'[')
    first = True
    for value in values:
        if not first:
            digest.update(b',')
        first = False
        digest.update(encoded(value))
        rows.append(value)
    digest.update(b']')
    return rows, digest.hexdigest()


def _capture_file(path, tables):
    """Keep raw native batch boundaries as bounded Parquet row groups."""
    with pq.ParquetWriter(path, NATIVE_CAPTURE_SCHEMA, compression='zstd') as writer:
        for table in tables:
            if not table.schema.equals(NATIVE_CAPTURE_SCHEMA, check_metadata=True):
                raise ValueError('Source replay requires exact retained capture schema')
            if len(table):
                writer.write_table(table, row_group_size=len(table))
    return pq.ParquetFile(path)


@dataclass
class PreparedSourceReplay:
    working: WorkingCatalog
    before: object
    after: object
    observations: object
    old_source_ids: object
    captures: pq.ParquetFile
    trace: SourceObservationTrace
    metadata: WorkingCatalog
    directory_owner: object = None
    iteration: int = 0

    def sources(self):
        return self.working.mapping('sources').values()

    def close(self):
        self.captures.close()
        self.working.close()
        self.metadata.close()
        if self.directory_owner is not None:
            self.directory_owner.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def prepare_source_replay(store, *, snapshot, changes, observations, root, directory, read_body, seeds=(),
                          changed_dependencies=()):
    """Close old/new input owners before recomputing source facts.

    Complete receipt groups, including ambiguous/unresolved meeting lookups and
    transfer-derived sources, run through DocumentSources and collect_source_inputs.
    This function never reads snapshot.captures() or a selected catalog table.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Only metadata is scanned on retry. Payloads come from the retained replay.
    scratch = TemporaryDirectory(prefix='source-attempt-', dir=directory)
    attempt = Path(scratch.name)
    metadata = WorkingCatalog(attempt / 'scope-keys.sqlite')
    result = None
    try:
        retained_changes = DiskRows(metadata.connection, 'requested_changes')
        change_hash = sha256()
        for change in changes:
            payload = encoded(change)
            change_hash.update(len(payload).to_bytes(8, 'big'))
            change_hash.update(payload)
            retained_changes.append(change)
        dependencies = _names(metadata, 'requested_dependencies', changed_dependencies)
        seeds, seed_sha = retain_source_seeds(metadata, seeds)
        dependency_hash = sha256()
        for value in dependencies:
            dependency_hash.update(encoded(value))
        request = dict(snapshot=snapshot.identity, root=root, namespace=observations.members.routes.objects.prefix,
            max_rows=observations.max_rows, max_bytes=observations.max_bytes,
            changes_sha256=change_hash.hexdigest(), dependencies_sha256=dependency_hash.hexdigest(),
            seeds_sha256=seed_sha)
        from .source_update_proof import source_update_requirements
        request['requirements'] = source_update_requirements()
        checkpoint = directory / 'replay-complete.json'
        binding = directory / 'replay-request.json'
        if binding.exists():
            if json.loads(binding.read_bytes()) != request:
                raise ValueError('Source replay continuation inputs differ')
        else:
            _write_metadata(binding, request)
        request_digest = sha256(encoded(request)).hexdigest()
        if checkpoint.exists():
            saved = _read_checkpoint(checkpoint, request_digest)
            if saved['empty']:
                metadata.close()
                scratch.cleanup()
                return None
            for name, identity in saved['files'].items():
                if file_identity(directory / name) != identity:
                    raise ValueError('Retained source replay file differs')
            metadata.close()
            shutil.copyfile(directory / 'replay-metadata.sqlite', attempt / 'scope-keys.sqlite')
            shutil.copyfile(directory / 'replay-sources.sqlite', attempt / 'sources.sqlite')
            metadata = WorkingCatalog(attempt / 'scope-keys.sqlite')
            work = WorkingCatalog(attempt / 'sources.sqlite')
            captures = pq.ParquetFile(directory / 'replay-captures.parquet')
            return PreparedSourceReplay(work, root, saved['after'],
                metadata.mapping(saved['observations']), metadata.mapping('old_source_ids'),
                captures, SourceObservationTrace(work, retained=True), metadata, scratch)
        result = _prepare(store, snapshot=snapshot, changes=retained_changes, observations=observations,
            root=root, directory=attempt, read_body=read_body, seeds=seeds,
            changed_dependencies=dependencies, metadata=metadata, checkpoint_directory=directory,
            request_digest=request_digest)
        if result is None:
            metadata.close()
            _write_metadata(checkpoint, dict(empty=True, request_sha256=request_digest))
            scratch.cleanup()
            return None
        for work, name in ((result.working, 'replay-sources.sqlite'), (metadata, 'replay-metadata.sqlite')):
            _save_sqlite(work, directory / name)
        shutil.copyfile(attempt / f'captures-{result.iteration}.parquet', directory / 'replay-captures.parquet.tmp')
        (directory / 'replay-captures.parquet.tmp').replace(directory / 'replay-captures.parquet')
        files = {name: file_identity(directory / name) for name in
                 ('replay-sources.sqlite', 'replay-metadata.sqlite', 'replay-captures.parquet')}
        _write_metadata(checkpoint, dict(empty=False, after=result.after, request_sha256=request_digest,
            observations=result.observations.name, files=files))
        result.directory_owner = scratch
        return result
    except BaseException:
        if result is not None:
            result.close()
        else:
            metadata.close()
        scratch.cleanup()
        raise


def _write_metadata(path, body):
    if path.name in {'replay-complete.json', 'replay-progress.json'}:
        body = dict(body, binding=sha256(encoded(body)).hexdigest())
    partial = path.with_suffix('.tmp')
    partial.write_bytes(encoded(body))
    partial.replace(path)


def _save_sqlite(work, path):
    """Snapshot completed staging before handing a mutable copy to the caller."""
    partial = path.with_suffix('.tmp')
    partial.unlink(missing_ok=True)
    with sqlite3.connect(partial) as backup:
        work.connection.commit()
        work.connection.backup(backup)
    partial.replace(path)


def _read_checkpoint(path, request_digest):
    if path.stat().st_size > 1 << 20:
        raise ValueError('Retained source replay metadata exceeds its byte bound')
    saved = json.loads(path.read_bytes())
    if (saved.pop('binding', None) != sha256(encoded(saved)).hexdigest()
            or saved.get('request_sha256') != request_digest):
        raise ValueError('Retained source replay checkpoint binding differs')
    return saved


def _save_progress(directory, metadata, *, closed, candidate, iteration, request_digest):
    path = directory / f'replay-progress-{iteration}.sqlite'
    _save_sqlite(metadata, path)
    _write_metadata(directory / 'replay-progress.json', dict(request_sha256=request_digest,
        closed=closed.name, candidate=candidate, iteration=iteration, file=file_identity(path)))


def _names(metadata, name, values):
    result = metadata.mapping(name)
    result.clear()
    for value in values:
        result[value] = True
    return result


def _prepare(store, *, snapshot, changes, observations, root, directory, read_body, seeds,
             changed_dependencies, metadata, checkpoint_directory, request_digest):
    inputs = SourceCaptureInputs(store)
    progress = checkpoint_directory / 'replay-progress.json'
    if progress.exists():
        saved = _read_checkpoint(progress, request_digest)
        path = checkpoint_directory / f"replay-progress-{saved['iteration']}.sqlite"
        if file_identity(path) != saved['file']:
            raise ValueError('Retained source replay progress file differs')
        metadata.connection.commit()
        with sqlite3.connect(path) as retained:
            retained.backup(metadata.connection)
        closed, candidate, iteration = metadata.mapping(saved['closed']), saved['candidate'], saved['iteration']
        changed = metadata.mapping('changed_observations')
    else:
        with closing(WorkingCatalog(directory / 'incoming.sqlite')) as work:
            trace = SourceObservationTrace(work)
            incoming = _capture_file(directory / 'incoming.parquet',
                (table for change in changes for table in inputs.changed(snapshot, change, trace)))
            changed = _names(metadata, 'changed_observations', trace.observations())
            if not changed and not changed_dependencies and not seeds:
                incoming.close()
                return None
            with incoming:
                trace.replay(incoming, store.read, read_body, seeds=seeds, retained_capture_inputs=True)
            candidate = observations.prepare(root, trace)
        with closing(WorkingCatalog(directory / 'closure-initial.sqlite')) as work:
            closed = _names(metadata, 'closed_0', observations.affected(root, candidate, changed, working=work,
                changed_dependencies=changed_dependencies))
        iteration = 0
        _save_progress(checkpoint_directory, metadata, closed=closed, candidate=candidate,
            iteration=iteration, request_digest=request_digest)
    while True:
        work = WorkingCatalog(directory / f'replay-{iteration}.sqlite')
        captures = None
        try:
            trace = SourceObservationTrace(work)
            inputs.copy(observations, candidate, closed, trace)
            captures = _capture_file(directory / f'captures-{iteration}.parquet',
                inputs.tables(observations, candidate, closed, snapshot))
            trace.replay(captures, store.read, read_body, seeds=seeds, retained_capture_inputs=True)
            after = observations.prepare(root, trace)
            with closing(WorkingCatalog(directory / f'closure-{iteration}.sqlite')) as closure_work:
                complete = _names(metadata, f'closed_{(iteration + 1) % 2}',
                    observations.affected(root, after, changed, working=closure_work,
                                          changed_dependencies=changed_dependencies))
            if len(complete) == len(closed) and all(value in complete for value in closed):
                old_sources = metadata.mapping('old_source_ids')
                old_sources.clear()
                for observation in closed:
                    for edge in observations.members.values(root, observation):
                        dependency, access = json.loads(edge)
                        kind, value = json.loads(dependency[len('dependency:'):])
                        if kind == 'source' and access == 'write':
                            old_sources[value] = True
                complete.clear()
                changed.clear()
                return PreparedSourceReplay(work, root, after, closed, old_sources, captures, trace, metadata, iteration=iteration)
            work.close()
            captures.close()
            closed, candidate = complete, after
            iteration += 1
            _save_progress(checkpoint_directory, metadata, closed=closed, candidate=candidate,
                iteration=iteration, request_digest=request_digest)
        except BaseException:
            if captures is not None:
                captures.close()
            work.close()
            raise
