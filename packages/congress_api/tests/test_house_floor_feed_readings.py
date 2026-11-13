"""Retained House feed through supervised readings and the model's link consumer."""
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings
from congress_api.parsers.house_floor_feed import reading_row
from congress_api.retention.provenance import json_input, run_job
from docspec_client.client import NativeDatasets
from native_test_helpers import lake_readings_table

FIXTURE = Path(__file__).parent / 'fixtures/house_floor/retained-entries.xml'
URL = 'https://docs.house.gov/BillsThisWeek-RSS.xml'
STAMP = '2026-10-04T23:25:36.224562Z'
ROOT = Path(__file__).resolve().parents[3]


def inputs(directory, body):
    directory.mkdir()
    raw = directory / 'raw'
    captures, inventory, sniff = [], [], []
    for name, data, format, url in [
        ('feed', body, 'xml', URL),
        ('other', body + b'<!-- another source -->', 'xml', 'https://example.invalid/feed.xml'),
        ('pdf', b'%PDF-1.7\nfixture', 'pdf', 'https://docs.house.gov/bill.pdf'),
    ]:
        digest = hashlib.sha256(data).digest()
        key = f'bodies/sha256/{digest.hex()[:2]}/{digest.hex()}'
        path = raw / key; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        captures.append(dict(sha256=digest, bytes=len(data), url=url, requested_url=url, complete=True, http_status=200))
        inventory.append(dict(body_sha=digest, physical_key=key, relative_path=key, stored_bytes=len(data)))
        sniff.append(dict(body_sha=digest, parser='sniff', parser_version=readings.current_version('sniff'),
                          status='completed', format=format))
    cap, inv, existing = [directory / (name + '.parquet') for name in ('captures', 'inventory', 'existing')]
    pq.write_table(pa.Table.from_pylist(captures, schema=pa.schema([
        ('sha256', pa.binary(32)), ('bytes', pa.int64()), ('url', pa.string()), ('requested_url', pa.string()),
        ('complete', pa.bool_()), ('http_status', pa.int32()), ('sniffed_format', pa.string()),
        ('sniff_version', pa.string()), ('intact', pa.bool_())])), cap)
    pq.write_table(pa.Table.from_pylist(inventory, schema=pa.schema([
        ('body_sha', pa.binary(32)), ('physical_key', pa.string()), ('relative_path', pa.string()),
        ('stored_bytes', pa.int64())])), inv)
    pq.write_table(lake_readings_table(sniff), existing)
    return dict(captures=cap, body_inventory=inv, local_root=raw, existing=existing,
                decided_at=STAMP, engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))


def test_derived_pass_selects_only_feed_and_reuses_completed_reading(tmp_path):
    args = inputs(tmp_path / 'inputs', FIXTURE.read_bytes())
    staged = readings.stage(**args, work=tmp_path / 'first', parser='house_floor_feed', parser_workers=1)
    result = pq.read_table(staged['readings']).to_pylist()
    assert staged['work_items'] == 1 and staged['pending_reads'] == 0
    assert len(result) == 1 and result[0]['status'] == 'completed'
    assert result[0]['link_count'] == 104 and result[0]['text_bytes'] == 0 and result[0]['text_head'] is None
    fields = {item['field']: item['value'] for item in result[0]['fields']}
    assert fields['body_role'] == 'feed'
    assert json.loads(fields['entry:0'])['weekly_url'] == json.loads(fields['entry:1'])['weekly_url']
    current = tmp_path / 'current.parquet'
    pq.write_table(lake_readings_table(pq.read_table(args['existing']).to_pylist() + result), current)
    args['existing'] = current
    repeat = readings.plan(**args, work=tmp_path / 'again', parser='house_floor_feed')
    assert repeat['work_items'] == 0


def test_failed_and_valid_empty_feed_remain_distinct():
    body = FIXTURE.read_bytes()
    assert reading_row(body[:-20])['status'] == 'error'
    empty = reading_row(body.split(b'<entry>')[0] + b'</feed>')
    assert empty['status'] == 'completed' and empty['links'] == []
    assert json.loads(next(v['value'] for v in empty['fields'] if v['field']=='feed'))['entry_count'] == 0


def test_large_route_bound_does_not_relax_generic_xml():
    data = b'x' * (readings.PAGE_PARSE_MAX_BYTES + 1)
    readings._bound_page_parse(data, 'house_floor_feed')
    with pytest.raises(MemoryError): readings._bound_page_parse(data, 'xml')


def test_model_discovers_embedded_links_and_preserves_revision_attribution(tmp_path):
    from viewer_publication.archive_model import link_steps, registry_inputs
    body = FIXTURE.read_bytes(); digest = hashlib.sha256(body).digest()
    feed = dict(reading_row(body), body_sha=digest, parser='house_floor_feed',
                parser_version=readings.current_version('house_floor_feed'))
    # A generic XML reading is kept as historical evidence; its flattened links
    # must not duplicate the successful structured feed discovery occurrences.
    generic = dict(feed, parser='xml', parser_version=readings.current_version('xml'),
                   links=[dict(feed['links'][0], href='https://wrong.invalid/flattened.pdf')])
    selected = tmp_path / 'selected.parquet'
    pq.write_table(lake_readings_table([generic, feed]), selected)
    inputs_ = registry_inputs(tmp_path / 'registries')
    inputs_.append(dict(name='selected_readings', kind='parquet', path=str(selected)))
    fetch = tmp_path / 'fetch.parquet'
    pq.write_table(pa.Table.from_pylist([dict(sha256=digest, context_url=URL, member_path=None, retrieved_at=STAMP,
        receipt_key='retained/feed', receipt_line=1, capture_index=0)], schema=pa.schema([
        ('sha256', pa.binary(32)), ('context_url', pa.string()), ('member_path', pa.string()),
        ('retrieved_at', pa.string()), ('receipt_key', pa.string()), ('receipt_line', pa.int64()),
        ('capture_index', pa.int64())])), fetch)
    inputs_.append(dict(name='good_fetches', kind='parquet', path=str(fetch)))
    inputs_.append(json_input(tmp_path, 'record_roles', [dict(receipt_key='retained/feed', receipt_line=1,
        capture_index=0, format='xml', record_role='listing')], receipt_key='Utf8', receipt_line='Int64',
        capture_index='Int64', format='Utf8', record_role='Utf8'))
    steps = [dict(name='page_facts', sql="SELECT * FROM selected_readings WHERE parser='xml'"),
             dict(name='placeholders', sql='SELECT sha256 FROM good_fetches WHERE false')]
    steps += [dict(name=name.replace('-', '_'), sql=(ROOT / 'model/sql' / (name + '.sql')).read_text(), materialize=True)
              for name in ('house-floor-feed-readings', 'page-contexts', 'link-inputs')]
    result = run_job(tmp_path / 'model', NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=inputs_, steps=steps + link_steps(), outputs=[], queries=[dict(name='links', sql=
            'SELECT target_url,group_path,link_index FROM resolved_links ORDER BY link_index')])['links']
    assert len(result) == 104
    assert all('wrong.invalid' not in row['target_url'] for row in result)
    assert result[0]['target_url'] == result[7]['target_url']  # same weekly page in the next update
    assert result[0]['group_path'] != result[7]['group_path']
    assert any(row['target_url'].startswith('http://docs.house.gov/floor/Download.aspx?') for row in result)
