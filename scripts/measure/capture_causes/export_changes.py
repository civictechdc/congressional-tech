"""Export every capture row whose refused columns differ between two generations.

    export_changes.py OLD.parquet NEW_PIN.json WORK [COLUMN,...]

COLUMNS defaults to the refused eligibility columns; pass e.g. url,context_url,recovered_url
to export the address changes instead.

One native FULL JOIN on the primary key (O(N) expected); writes changes.parquet with
both sides' eligibility values plus the narrow facts the raw judge needs to find the
raw entry (receipt key, line, capture index). good_fetch is the shared
GOOD_FETCH_CAPTURE_SQL on each side.
"""
import json
import os
import sys
from pathlib import Path

from congress_api.lake._record_producer import GOOD_FETCH_CAPTURE_SQL
from congress_api.lake.capture_comparison import GENERATION_REFUSED
from congress_api.lake.captures import PK
from congress_api.lake.tables import table_input
from congress_api.retention.provenance import parquet_output, run_job
from docspec_client.client import NativeDatasets

old, new_pin, work = sys.argv[1], json.loads(Path(sys.argv[2]).read_text()), Path(sys.argv[3])
facts = [c for c in GENERATION_REFUSED if c != 'good_fetch'] + ['attempt', 'url', 'context_url', 'recovered_url']
side = lambda alias, table: (f"SELECT c.*,coalesce({GOOD_FETCH_CAPTURE_SQL},false) AS good_fetch FROM {table} c")
on = ' AND '.join(f'o."{k}"=n."{k}"' for k in PK)
cols = [f'o."{k}" AS "{k}"' for k in PK]
cols += [f'o."{c}" AS "old_{c}",n."{c}" AS "new_{c}"' for c in facts + ['good_fetch']]
cols += ['n.family', 'n.mode', 'n.member_path', 'n.requested_url', "encode(n.sha256,'hex') AS sha", 'n.bytes',
         'n.media_type', 'n.sniffed_format']
watched = sys.argv[4].split(',') if len(sys.argv) > 4 else list(GENERATION_REFUSED)
changed = ' OR '.join(f'(o."{c}" IS DISTINCT FROM n."{c}")' for c in watched)
with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
    run_job(work, engine, inputs=[table_input('old_t', old), table_input('new_t', dict(new_pin))],
        steps=[dict(name='o', sql=side('o', 'old_t')), dict(name='n', sql=side('n', 'new_t'))],
        outputs=[parquet_output(work, 'changes', f'SELECT {",".join(cols)} FROM o JOIN n ON {on} WHERE {changed}', PK)])
print(work / 'changes.parquet')
