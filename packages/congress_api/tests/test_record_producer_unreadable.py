"""An unreadable body never stops a record producer: it becomes one valid unreadable decision.

Every record table (meeting, appearance, video, committee) stages through the shared
producer, so each is run on a body its parser cannot read. Before 2026-11-02 the decision
row carried both identity keys and free-text reason, which import_unreadable refuses, so
staging failed on the first bad body (impl-f, video_records).
"""
import gzip
from hashlib import sha256
import json
import os
import xml.etree.ElementTree as ET

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import _record_producer, appearance_records, committee_records, meeting_records, video_records
from congress_api.retention.provenance import validate_provenance
from docspec_client.client import NativeDatasets
from native_test_helpers import empty_readings, lake_readings_table


PRODUCERS = {  # every record table that stages through the shared producer; real failures where the parser raises
    'meeting_records': (meeting_records, 'congress_gov', meeting_records.build_meeting_record_row),
    'appearance_records': (appearance_records, 'house_xml', appearance_records.build_appearance_record_row),
    'video_records': (video_records, video_records.SOURCE, video_records.build_row),
    'committee_records': (committee_records, committee_records.SOURCE, committee_records.build_row),
}
NO_INLINE = video_records.NO_INLINE_SQL


@pytest.mark.parametrize('name', sorted(PRODUCERS))
def test_an_unreadable_body_is_settled_by_one_valid_decision(tmp_path, name):
    module, source, build_row = PRODUCERS[name]
    body = b'\xff\xfe\x80 not a record this parser can read'
    digest = sha256(body).hexdigest()
    raw = tmp_path / 'raw'
    path = raw / f'bodies/sha256/{digest[:2]}/{digest}.gz'
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(body, mtime=0))
    pq.write_table(pa.table({'sha256': pa.array([bytes.fromhex(digest)], pa.binary(32)), 'stored_suffix': ['.gz']}),
                   tmp_path / 'captures.parquet')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        staged = _record_producer.stage_record_table(
            parser_name=name, out_filename=f'{name}.parquet',
            candidate_sql=f"SELECT lower(encode(sha256,'hex')) AS record_sha,'{source}' AS source,stored_suffix FROM captures",
            inline_sql=NO_INLINE, build_row_fn=build_row, table_fn=module.table,
            captures=tmp_path / 'captures.parquet', engine=engine, work=tmp_path / 'stage',
            version={source: 'v-test'}, local_root=raw, decided_at='2026-11-02T12:00:00Z')
    assert staged['produced'] == 0 and staged['unreadable_key'], staged
    decisions = [__import__('json').loads(line) for line in (tmp_path / 'stage/unreadable-decisions.jsonl').read_text().splitlines()]
    assert [d['record_sha'] for d in decisions] == [digest] and 'body_sha256' not in decisions[0]
    validate_provenance('unreadable', decisions[0])


@pytest.mark.parametrize('error', [ValueError('bad'), KeyError('x'), UnicodeDecodeError('utf-8', b'', 0, 1, 'x'),
                                   __import__('xml.etree.ElementTree').etree.ElementTree.ParseError('bad xml')])
def test_every_caught_parse_error_gives_a_decision_the_import_accepts(error):
    """Both branches (file bodies and inline lines) write through unreadable_decision."""
    row = _record_producer.unreadable_decision('meeting_records', 'v1', 'a' * 64, error, '2026-11-02T12:00:00Z')
    assert validate_provenance('unreadable', row)['reason'] in {'value_error', 'key_error', 'unicode_decode_error', 'parse_error'}


# The v21 audit found no malformed body among its 6,179 House meeting rows. Its two
# empty witness lists (105459 and 111420) were valid XML. Keep that historical finding
# separate from the failure transition exercised here; it is not a current census.
TRUNCATED = b'<?xml version="1.0"?><committee-meeting meeting-id="HHRG118888"><meeting-details><meeting-title>Cut off'
HOUSE_PRODUCERS = {name: PRODUCERS[name] for name in ('meeting_records', 'appearance_records', 'committee_records')}
HOUSE_PRODUCERS['meeting_records'] = (meeting_records, 'house_xml', meeting_records.build_meeting_record_row)
REPAIR_BODIES = {
    'meeting_records': b'<committee-meeting meeting-id="HHRG118888"><heading>A & B</heading></committee-meeting>',
    'appearance_records': b'<witness-list meeting-id="HHRG118888"><panel><witness><witness-name><firstname>Jane</firstname><lastname>Smith</lastname></witness-name><organization>A & B</organization></witness></panel></witness-list>',
    'committee_records': b'<committee-meeting meeting-id="HHRG118888"><meeting-documents><meeting-document type="CA"><description>A & B</description></meeting-document></meeting-documents></committee-meeting>',
}


@pytest.mark.parametrize('build', [meeting_records.build_meeting_record_row, appearance_records.build_appearance_record_row,
                                   committee_records.build_row], ids=['meeting', 'appearance', 'committee'])
@pytest.mark.parametrize('payload', [TRUNCATED, b'<witness-list><witness></witness-list>', b'not xml'])
def test_unparseable_house_xml_is_never_a_completed_row(build, payload):
    with pytest.raises(ET.ParseError):
        build(record_sha='a' * 64, source='house_xml', payload=payload, parser_version='v')


def house_inputs(tmp_path, name, payloads):
    """Good stored captures without XML readings exercise the maintained route fallback."""
    raw = tmp_path / 'raw'
    raw.mkdir()
    family = 'house/witness-xml' if name == 'appearance_records' else 'house/meeting-xml'
    rows = []
    for payload in payloads:
        digest = sha256(payload).hexdigest()
        path = raw / f'bodies/sha256/{digest[:2]}/{digest}.gz'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(payload, mtime=0))
        rows.append(dict(sha256=bytes.fromhex(digest), stored_suffix='.gz', family=family,
                         mode='fetch', complete=True, outcome='stored', http_status=200, bytes=len(payload)))
    schema = pa.schema([('sha256', pa.binary(32)), ('complete', pa.bool_()), ('http_status', pa.int32()),
                        ('receipt_line', pa.int64()), ('bytes', pa.int64()), *[(field, pa.string()) for field in
                        ('stored_suffix', 'family', 'mode', 'outcome', 'url', 'requested_url', 'context_url',
                         'sniffed_format', 'media_type', 'member_path', 'receipt_key')]])
    path = tmp_path / 'captures.parquet'
    # Duplicate receipts for one body must not duplicate either records or failures.
    pq.write_table(pa.Table.from_pylist(rows + rows, schema=schema), path)
    return raw, path


@pytest.mark.parametrize('name', sorted(HOUSE_PRODUCERS))
def test_house_syntax_failure_is_durable_and_settled_while_empty_results_complete(tmp_path, name):
    from congress_api.retention.body_store import BodyStore, LocalAdapter

    module, _, _ = HOUSE_PRODUCERS[name]
    payloads = [TRUNCATED, b'<other/>', b'', b' \n\t', b'<witness-list meeting-id="HHRG111420"/>']
    repaired_body = REPAIR_BODIES[name]
    payloads.append(repaired_body)
    raw, captures = house_inputs(tmp_path, name, payloads)
    store = BodyStore(LocalAdapter(raw))
    versions = {'house_xml': module.current_versions()['house_xml']}
    args = dict(captures=captures, local_root=raw, raw_store=store, unreadable_store=store,
                parser_version=versions, decided_at='2026-11-06T12:00:00Z')
    if name != 'committee_records':
        args['readings'] = empty_readings(tmp_path / 'readings')
        from congress_api.lake.readings import current_version
        # A selected XML syntax error still routes by the source family/URL fallback.
        pq.write_table(lake_readings_table([dict(body_sha=sha256(TRUNCATED).digest(), parser='xml',
            parser_version=current_version('xml'), status='error', error_type='XMLSyntaxError')]), args['readings'])
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        first = module.stage(engine=engine, work=tmp_path / 'first', **args)
        assert first['work_items'] == 6 and first['produced'] == 5
        assert first['unreadable_pending'] is False
        decision_path = raw / first['unreadable_key']
        decisions = [json.loads(line) for line in decision_path.read_text().splitlines()]
        assert len(decisions) == 1
        decision = validate_provenance('unreadable', decisions[0])
        assert (decision['record_sha'], decision['parser'], decision['parser_version'], decision['reason']) == (
            sha256(TRUNCATED).hexdigest(), name, versions['house_xml'], 'parse_error')
        rows = pq.read_table(first['records']).to_pylist()
        payload_column = {'meeting_records': 'meetings', 'appearance_records': 'appearances'}.get(name, 'records')
        assert {row['record_sha'].hex() for row in rows} == {sha256(p).hexdigest() for p in payloads[1:]}
        assert all(row['status'] == 'completed' for row in rows)
        repaired_sha = sha256(repaired_body).hexdigest()
        assert all(row[payload_column] == [] for row in rows if row['record_sha'].hex() != repaired_sha)
        repaired = next(row for row in rows if row['record_sha'].hex() == repaired_sha)
        field = {'meeting_records': 'title', 'appearance_records': 'organization'}.get(name, 'description')
        assert repaired[payload_column][0][field] == 'A & B'
        # A new engine instance reads the durable imported decision, not staging state.
    inventory = [dict(key=first['unreadable_key'], path=str(decision_path))]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        repeated = module.stage(engine=engine, work=tmp_path / 'repeated', existing=first['records'],
                                unreadable_files=inventory, **args)
        assert repeated['work_items'] == 0 and repeated['produced'] == 0
        assert repeated['unreadable_key'] is None


@pytest.mark.parametrize('name', sorted(HOUSE_PRODUCERS))
def test_missing_house_body_stays_pending_until_bytes_arrive(tmp_path, name):
    module, _, _ = HOUSE_PRODUCERS[name]
    raw, captures = house_inputs(tmp_path, name, [TRUNCATED])
    digest = sha256(TRUNCATED).hexdigest()
    body = raw / f'bodies/sha256/{digest[:2]}/{digest}.gz'
    saved = body.read_bytes()
    body.unlink()
    args = dict(captures=captures, local_root=raw, parser_version={'house_xml': 'v-test'},
                decided_at='2026-11-06T12:00:00Z')
    if name != 'committee_records':
        args['readings'] = empty_readings(tmp_path / 'readings')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        with pytest.raises(FileNotFoundError, match='Missing raw body'):
            module.stage(engine=engine, work=tmp_path / 'missing', **args)
        assert not (tmp_path / 'missing/unreadable-decisions.jsonl').exists()
        body.write_bytes(saved)
        arrived = module.stage(engine=engine, work=tmp_path / 'arrived', **args)
        assert arrived['work_items'] == 1 and arrived['produced'] == 0 and arrived['unreadable_key']
