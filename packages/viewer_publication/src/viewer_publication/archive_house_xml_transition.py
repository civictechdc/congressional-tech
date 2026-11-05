"""Advance the House XML meeting version when Act citations affect none of its URLs."""
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import unquote

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.lake import meeting_records, tables
from congress_api.retention.provenance import file_pin, parquet_output, run_job, validate_provenance
from congress_api.retention.writer_identity import writer_identity
from docspec_client.client import NativeDatasets
from house_naming.extraction import ACT_CITATION
from viewer_publication.archive_model_job import _local, _pin, _selector
from viewer_publication.producer_proof import BACKFILL, ROOT, record

OLD = dict(congress_gov='ecc51fcdb572b426da01a9135b467bf3f9a85e91d268ff895a56e2dda5ef716e',
           house_xml='d0ee8e7c35edf620c0aaf1b46c2c7bc4145619cb9abd1c6e45e8aa5b658f9089')
NEW = dict(OLD, house_xml='8a2417a2c876b2cd3f202ed92dfbc48bca580f7fa2848d6644310771484617c8')


def load_transition(value, *, base):
    if (set(value) != {'version', 'work', 'engine_config', 'house_xml_version_transition'}
            or type(value['version']) is not int or value['version'] != 1):
        raise ValueError('House XML transition requires version 1, work and a read engine config')
    model = value['house_xml_version_transition']
    _pin(model, {'path', 'sha256', 'size'})
    return dict(value, work=_local(value['work'], base), engine_config=_local(value['engine_config'], base),
                house_xml_version_transition=dict(model, path=_local(model['path'], base)))


def _pinned_bytes(item):
    data = Path(item['path']).read_bytes()
    if len(data) != item['size'] or sha256(data).hexdigest() != item['sha256']:
        raise ValueError('House XML transition input differs from its pin: ' + item['path'])
    return data


def _unreadable_counts(files):
    rows = [validate_provenance('unreadable', json.loads(line)) for item in files
            for line in _pinned_bytes(item).splitlines()]
    superseded = {row.get('supersedes') for row in rows}
    active = [row for row in rows if row['id'] not in superseded]
    old_house = sum(row['parser'] in {'meeting_records', 'meetings', 'meeting_records.house_xml'}
                    and row['parser_version'] == OLD['house_xml'] for row in active)
    if old_house:
        raise ValueError(f'House XML transition has {old_house} active unreadable decisions under the old version')
    return dict(files=len(files), decisions=len(rows), active=len(active), active_old_house_xml=old_house)


def _advance_rows(rows):
    keys = rows.select(['record_sha', 'source'])
    sources = keys['source'].to_pylist()
    versions = rows['parser_version'].to_pylist()
    if (set(zip(sources, versions)) != set(OLD.items()) or set(rows['status'].to_pylist()) != {'completed'}
            or None in keys['record_sha'].to_pylist() or len(set(zip(keys['record_sha'].to_pylist(), sources))) != rows.num_rows):
        raise ValueError('House XML transition requires one completed reading per record and source at the reviewed versions')
    house = pc.equal(rows['source'], 'house_xml')
    urls = {url for row in rows.filter(house)['meetings'].to_pylist()
            for meeting in row for url in meeting['document_urls']}
    for url in urls:
        # Mirror the URL-to-basename boundary of the sole house_naming caller in meeting_records.
        basename = unquote(url.strip()).split('?', 1)[0].rsplit('/', 1)[-1].replace(' ', '')
        if ACT_CITATION.search(basename):
            raise ValueError('House XML transition found a document basename that requires replay: ' + url)
    advanced = rows.set_column(rows.schema.get_field_index('parser_version'), rows.schema.field('parser_version'),
                               pa.array([NEW[source] for source in sources], type=rows.schema.field('parser_version').type))
    return advanced, dict(rows=rows.num_rows, house_xml=sources.count('house_xml'),
                          congress_gov=sources.count('congress_gov'), urls_checked=len(urls))


def execute_transition(spec, *, runtime_factory=None):
    if meeting_records.current_versions() != NEW:
        raise ValueError('House XML transition only supports the reviewed Act citation dependency change')
    writer = writer_identity(ROOT, BACKFILL)
    model_pin = spec['house_xml_version_transition']
    model = json.loads(_pinned_bytes(model_pin))
    if model['parser_versions']['meeting_records'] != OLD:
        raise ValueError('House XML transition requires the reviewed prior meeting versions')
    base = _selector(model['meeting_records'], Path(model_pin['path']).parent)
    if base['kind'] != 'native_table' or base['snapshot'] is None:
        raise ValueError('House XML transition requires an immutable meeting snapshot')
    unreadable = _unreadable_counts(model['unreadable_files'])

    work = Path(spec['work'])
    work.mkdir(parents=True, exist_ok=False)
    exported = work / 'base'
    keys = list(tables.TABLE_SPECS['meeting_records']['primary_key'])
    factory = runtime_factory or NativeDatasets.from_config
    with factory(spec['engine_config']) as reader:
        reader.verify_runtime()
        run_job(exported, reader, inputs=[tables.table_input('base', {k: v for k, v in base.items() if k != 'kind'})],
                steps=[], outputs=[parquet_output(exported, 'meeting-records', 'SELECT * FROM base', keys)])
    before = pq.read_table(exported / 'meeting-records.parquet')
    advanced, counts = _advance_rows(before)
    output = work / 'meeting-records.parquet'
    pq.write_table(advanced, output)
    result = pq.read_table(output)
    if not result.equals(advanced) or not result.drop_columns(['parser_version']).equals(before.drop_columns(['parser_version'])):
        raise ValueError('House XML transition changed meeting values')
    if writer_identity(ROOT, BACKFILL) != writer:
        raise ValueError('House XML transition writer changed during execution')

    selector = dict(kind='parquet', path=str(output), **file_pin(output))
    report = dict(status='tables_built', executed=True, base=base, selector=selector, model_spec=model_pin,
                  prior_versions=OLD, parser_versions=NEW, predicate=ACT_CITATION.pattern,
                  unreadable=unreadable, recomputed=0, **counts)
    proof = work / 'house-xml-transition.json'
    proof.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    producer = work / 'meeting_records.json'
    value = record(producer, input='meeting_records', selector=selector, job=BACKFILL)
    value.update(recorded='with production', reused_rows=counts['rows'], appended=0,
                 house_xml_transition=dict(path=str(proof), **file_pin(proof)))
    producer.write_text(json.dumps(value, indent=1, sort_keys=True) + '\n')
    return dict(report, producer=dict(path=str(producer), **file_pin(producer)))
