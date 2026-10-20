"""Replay complete retained receipt owners through the maintained source policy."""
from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path

import pyarrow.parquet as pq

from . import document_index as index
from .catalog_staging import WorkingCatalog
from .raw_values import NATIVE_CAPTURE_SCHEMA
from .source_capture_inputs import SourceCaptureInputs
from .source_observations import SourceObservationTrace


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

    def sources(self):
        return self.working.mapping('sources').values()

    def close(self):
        self.captures.close()
        self.working.close()
        self.metadata.close()

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
    metadata = WorkingCatalog(directory / 'scope-keys.sqlite')
    try:
        result = _prepare(store, snapshot=snapshot, changes=changes, observations=observations,
            root=root, directory=directory, read_body=read_body, seeds=seeds,
            changed_dependencies=changed_dependencies, metadata=metadata)
        if result is None:
            metadata.close()
        return result
    except BaseException:
        metadata.close()
        raise


def _names(metadata, name, values):
    result = metadata.mapping(name)
    result.clear()
    for value in values:
        result[value] = True
    return result


def _prepare(store, *, snapshot, changes, observations, root, directory, read_body, seeds,
             changed_dependencies, metadata):
    inputs = SourceCaptureInputs(store)
    with closing(WorkingCatalog(directory / 'incoming.sqlite')) as work:
        trace = SourceObservationTrace(work)
        incoming = _capture_file(directory / 'incoming.parquet',
            (table for change in changes for table in inputs.changed(snapshot, change, trace)))
        changed = _names(metadata, 'changed_observations', trace.observations())
        if not changed and not changed_dependencies:
            incoming.close()
            return None
        with incoming:
            trace.replay(incoming, store.read, read_body, seeds=seeds, retained_capture_inputs=True)
        candidate = observations.prepare(root, trace)
    with closing(WorkingCatalog(directory / 'closure-initial.sqlite')) as work:
        closed = _names(metadata, 'closed_0', observations.affected(root, candidate, changed, working=work,
            changed_dependencies=changed_dependencies))
    iteration = 0
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
                return PreparedSourceReplay(work, root, after, closed, old_sources, captures, trace, metadata)
            work.close()
            captures.close()
            closed, candidate = complete, after
            iteration += 1
        except BaseException:
            if captures is not None:
                captures.close()
            work.close()
            raise
