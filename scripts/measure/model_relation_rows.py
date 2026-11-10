"""Rows of every model relation in one retained model build, for the repeat-cost lint.

    .venv/bin/python scripts/measure/model_relation_rows.py RUN \
        > packages/viewer_publication/tests/fixtures/model-relation-rows.json

RUN holds the build's model-scratch/job.json, steps.jsonl and model-spec.json. Steps
take their logged rows (views and queries are never scanned and are left out); lake tables the total-records
of their pinned snapshot; Parquet inputs their footers; spicy-regs tables the manifest;
JSON-lines inputs their non-blank lines, read from model-spec's source file when the
build's private copy is gone. An input it cannot count stops the script.
"""
import gzip
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

from docspec_client import metric_events


def lines(path):
    with (gzip.open if str(path).endswith('.gz') else open)(path, 'rt') as handle:
        return sum(1 for line in handle if line.strip())


def input_rows(item, sources, spicy):
    if item['kind'] == 'native_table':
        metadata = json.loads(Path(item['metadata_location']).read_text())
        [snapshot] = [s for s in metadata['snapshots'] if s['snapshot-id'] == item['snapshot']]
        return int(snapshot['summary']['total-records'])
    if item['name'] in spicy:
        return spicy[item['name']]
    if item['kind'] == 'parquet':
        return pq.ParquetFile(item['path']).metadata.num_rows
    if item['kind'] == 'json_lines':
        return sum(lines(f['path'] if Path(f['path']).exists() else sources[f['key']]) for f in item['files'])
    raise ValueError(f"cannot count input {item['name']} ({item['kind']})")


def relation_rows(run):
    run = Path(run)
    job = json.loads((run/'model-scratch/job.json').read_text())
    spec = json.loads((run/'model-spec.json').read_text())
    sources = {f['key']: f['path'] for value in spec.values() if isinstance(value, list)
               for f in value if isinstance(f, dict) and 'key' in f and 'path' in f}
    spicy = {}
    if spec.get('spicy_regs'):
        manifest = json.loads(Path(spec['spicy_regs']['path']).read_text())
        spicy = {name: table['rows'] for name, table in manifest['tables'].items()}
    rows = {item['name']: input_rows(item, sources, spicy) for item in job['inputs']}
    for event in metric_events(run/'steps.jsonl', prefix=''):
        if event['event'] == 'step' and event['storage'] not in ('view', 'query'):
            rows[event['name']] = event['rows']
    head = (run/'head.txt').read_text().splitlines() if (run/'head.txt').exists() else []
    return dict(source='.cache/' + str(run.resolve()).partition('/.cache/')[2],
                head=head[0] if head else None, uncommitted=[line.split()[-1] for line in head[1:] if line[:3].strip() in ('M', '??', 'A')],
                rows=dict(sorted(rows.items())))


if __name__ == '__main__':
    json.dump(relation_rows(sys.argv[1]), sys.stdout, indent=1)
    sys.stdout.write('\n')
