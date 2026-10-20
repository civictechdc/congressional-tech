"""Replay complete retained receipt owners through the maintained source policy."""
from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path

import pyarrow as pa

from . import document_index as index
from .catalog_staging import WorkingCatalog
from .raw_values import NATIVE_CAPTURE_SCHEMA
from .source_capture_inputs import SourceCaptureInputs
from .source_observations import SourceObservationTrace


def _captures(tables):
    return pa.concat_tables(tables) if tables else pa.Table.from_pylist([], schema=NATIVE_CAPTURE_SCHEMA)


@dataclass
class PreparedSourceReplay:
    working: WorkingCatalog
    before: object
    after: object
    observations: tuple
    old_source_ids: tuple
    captures: pa.Table
    trace: SourceObservationTrace

    def sources(self):
        return self.working.mapping('sources').values()

    def close(self):
        self.working.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def prepare_source_replay(store, *, snapshot, changes, observations, root, directory, read_body, seeds=()):
    """Close old/new input owners before recomputing source facts.

    Complete receipt groups, including ambiguous/unresolved meeting lookups and
    transfer-derived sources, run through DocumentSources and collect_source_inputs.
    This function never reads snapshot.captures() or a selected catalog table.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    inputs = SourceCaptureInputs(store)
    with closing(WorkingCatalog(directory / 'incoming.sqlite')) as work:
        trace = SourceObservationTrace(work)
        incoming = []
        for change in changes:
            incoming.extend(inputs.changed(snapshot, change, trace))
        changed = tuple(trace.observations())
        if not changed:
            return None
        trace.replay(_captures(incoming), store.read, read_body, seeds=seeds, retained_capture_inputs=True)
        candidate = observations.prepare(root, trace)
    with closing(WorkingCatalog(directory / 'closure-initial.sqlite')) as work:
        closed = tuple(observations.affected(root, candidate, changed, working=work))
    iteration = 0
    while True:
        work = WorkingCatalog(directory / f'replay-{iteration}.sqlite')
        try:
            trace = SourceObservationTrace(work)
            inputs.copy(observations, candidate, closed, trace)
            captures = _captures(list(inputs.tables(observations, candidate, closed, snapshot)))
            trace.replay(captures, store.read, read_body, seeds=seeds, retained_capture_inputs=True)
            after = observations.prepare(root, trace)
            with closing(WorkingCatalog(directory / f'closure-{iteration}.sqlite')) as closure_work:
                complete = tuple(observations.affected(root, after, changed, working=closure_work))
            if complete == closed:
                old_sources = set()
                for observation in closed:
                    for edge in observations.members.values(root, observation):
                        dependency, access = json.loads(edge)
                        kind, value = json.loads(dependency[len('dependency:'):])
                        if kind == 'source' and access == 'write':
                            old_sources.add(value)
                return PreparedSourceReplay(work, root, after, closed, tuple(sorted(old_sources)), captures, trace)
            work.close()
            closed, candidate = complete, after
            iteration += 1
        except BaseException:
            work.close()
            raise
