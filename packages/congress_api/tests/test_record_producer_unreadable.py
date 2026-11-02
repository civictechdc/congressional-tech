"""An unreadable body never stops a record producer: it becomes one valid unreadable decision.

Every record table (meeting, appearance, video, committee) stages through the shared
producer, so each is run on a body its parser cannot read. Before 2026-11-02 the decision
row carried both identity keys and free-text reason, which import_unreadable refuses, so
staging failed on the first bad body (impl-f, video_records).
"""
import gzip
from hashlib import sha256
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import _record_producer, appearance_records, committee_records, meeting_records, video_records
from congress_api.retention.provenance import validate_provenance
from docspec_client.client import NativeDatasets

def failing(build_row):
    """The registered parser, failing as any parser can (the house_xml, mods and senate_page
    parsers return a row even for unreadable bytes, so their failure path needs a real raise)."""
    def build(**kwargs):
        raise ValueError('parser could not read this body')
    return build


PRODUCERS = {  # every record table that stages through the shared producer; real failures where the parser raises
    'meeting_records': (meeting_records, 'congress_gov', meeting_records.build_meeting_record_row),
    'appearance_records': (appearance_records, 'house_xml', failing(appearance_records.build_appearance_record_row)),
    'video_records': (video_records, video_records.SOURCE, video_records.build_row),
    'committee_records': (committee_records, committee_records.SOURCE, failing(committee_records.build_row)),
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


# The house_xml (and mods, senate_page) parsers return a 'completed' row with no records for
# bytes they cannot parse, so an unreadable candidate body would look like a meeting with no
# witnesses. Measured 2026-11-02 on the v21 inputs: 0 such bodies (all 6,179 house_xml meeting
# rows hold a meeting; the 2 empty house_xml witness rows are real empty <witness-list> bodies,
# read in full), and candidates route by a successful XML reading. Deferred (proposed ticket);
# strict, so these flip to failures once the parsers raise into unreadable_decision().
TRUNCATED = b'<?xml version="1.0"?><committee-meeting meeting-id="HHRG118888"><meeting-details><meeting-title>Cut off'


@pytest.mark.xfail(strict=True, reason='house_xml parsers stamp unparseable XML completed (proposed ticket, deferred)')
@pytest.mark.parametrize('build', [meeting_records.build_meeting_record_row, appearance_records.build_appearance_record_row,
                                   committee_records.build_row], ids=['meeting', 'appearance', 'committee'])
def test_unparseable_house_xml_is_never_a_completed_row(build):
    with pytest.raises((ValueError, __import__('xml.etree.ElementTree').etree.ElementTree.ParseError)):
        build(record_sha='a' * 64, source='house_xml', payload=TRUNCATED, parser_version='v')
