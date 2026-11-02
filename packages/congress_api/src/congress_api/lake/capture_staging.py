"""The one capture staging entry point: the mapping at bounded engine batch rows (ct-uupp).

Staging RSS grows with batch rows squared, outside the native pool: DataFusion
53.1 array_concat concatenates string views row by row (concat.rs:405-446), so
a batch holds rows x rows buffer handles. At 8192 rows the 581MB documents
assembly receipt passed 22GiB RSS without finishing; at 1024 it peaked at
6.5GiB, and staged files were byte-identical at both sizes. Every caller stages
here, whatever batch rows its runtime configures. Remove the bound when the
pinned engine passes docspec-rs ss-1rrn.
"""
import json
from pathlib import Path

from congress_api.lake import captures

STAGE_BATCH_ROWS=1024


def bounded_engine(engine,directory):
    """The same pinned runtime at no more than STAGE_BATCH_ROWS rows per batch.

    A runtime without limits cannot run a native job at all, so it passes
    through and the mapping's own admission refusals keep their order.
    """
    if getattr(engine,'limits',None) is None:return engine
    limits=json.loads(engine.limits.read_text())
    if type(limits.get('batch_rows')) is not int or limits['batch_rows']<=0:
        raise ValueError('Capture staging requires positive native batch_rows')
    if limits['batch_rows']<=STAGE_BATCH_ROWS:return engine
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'limits.json';path.write_text(json.dumps(dict(limits,batch_rows=STAGE_BATCH_ROWS),indent=2)+'\n')
    return engine.with_limits(path)


def stage_captures(files,*,engine,work,**kwargs):
    """captures.stage_captures under bounded batch rows; its derived limits sit beside work."""
    work=Path(work).resolve()
    bounded=bounded_engine(engine,work.parent/(work.name+'-limits'))
    try:
        return captures.stage_captures(files,engine=bounded,work=work,**kwargs)
    finally:
        if bounded is not engine:bounded.close()
