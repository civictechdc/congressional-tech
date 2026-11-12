"""Focused native meeting evidence: history conservation and dated held decisions.

These jobs run only maintained meeting SQL and the meeting export over hand rows.
They do not build a whole archive, invoke a parser, or read a source body.
"""
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from congress_api.retention.provenance import json_input, parquet_output, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import (
    MEETING_RECORD_FIELDS, REGISTRIES, SPICY_SCHEMAS, _normalize_meeting_rows,
    meeting_steps, selected_record_step,
)

from viewer_publication.meeting_detail_observations import EMPTY_OBSERVATIONS

ROOT = Path(__file__).parents[3]
TRANSCRIPT = 'HHRG-119-IF00-Transcript-20250701.pdf'


def _record(sha, event, status, day, updated, **fields):
    return dict(record_sha=sha * 32, source='congress_gov', parser_version='v',
        meetings=[dict(event_id=str(event), chamber='house', congress=119,
            title=f'Program {event}', meeting_date=day, updated=updated,
            status=status, meeting_type='HHRG', not_held=status in ('Canceled', 'Postponed'), **fields)])


def _identity(event, observation):
    return (event, observation['source'], observation['status'],
        str(observation['meeting_date']) if observation['meeting_date'] is not None else None,
        observation['record_sha'])


def _assert_history(rows, expected):
    actual = Counter(_identity(row['event_id'], obs) for row in rows for obs in row['publisher_status_observations'])
    missing, extra = expected - actual, actual - expected
    assert not missing and not extra, f'missing={missing}; extra={extra}'


@pytest.fixture(scope='module', params=['2020-07-17', '2020-07-18', None], ids=['same-date', 'moved-date', 'missing-date'])
def sample(tmp_path_factory, request):
    work = tmp_path_factory.mktemp('meeting-outcome-evidence')
    day = request.param
    records = [
        _record('11', 501, 'Scheduled', '2025-07-01', '2025-06-01T00:00:00Z'),
        _record('22', 501, 'Canceled', '2025-07-02', '2025-06-02T00:00:00Z'),
        _record('33', 502, 'Scheduled', '2025-07-01', '2025-06-02T00:00:00Z'),
        _record('44', 502, 'Canceled', '2025-07-02', '2025-06-02T00:00:00Z'),
        _record('55', 503, 'Canceled', '2025-07-01', '2025-06-01T00:00:00Z'),
        _record('66', 503, 'Scheduled', '2025-07-02', '2025-06-02T00:00:00Z'),
        _record('77', 504, 'Scheduled', '2025-07-01', None,
            videos=[dict(video_key='youtube:locator', url='https://youtu.be/locator', title='Locator only')]),
        _record('88', 505, 'Canceled', '2025-07-01', None),
        _record('99', 506, 'Scheduled', '2025-07-01', None,
            document_urls=['https://fixture.test/' + TRANSCRIPT]),
        _record('aa', 110924, 'Postponed', day, None),
    ]
    # This retained older parser must contribute neither current fields nor history.
    records.append(dict(_record('bb', 501, 'Unqualified', '2025-07-03', None), parser_version='old'))
    expected = Counter((event, 'congress_gov', status, observed_day, sha * 32) for event, status, observed_day, sha in [
        (501, 'Scheduled', '2025-07-01', '11'), (501, 'Canceled', '2025-07-02', '22'),
        (502, 'Scheduled', '2025-07-01', '33'), (502, 'Canceled', '2025-07-02', '44'),
        (503, 'Canceled', '2025-07-01', '55'), (503, 'Scheduled', '2025-07-02', '66'),
        (504, 'Scheduled', '2025-07-01', '77'), (505, 'Canceled', '2025-07-01', '88'),
        (506, 'Scheduled', '2025-07-01', '99'), (110924, 'Postponed', day, 'aa'),
    ])
    inputs = [json_input(work, 'meeting_records_input', _normalize_meeting_rows(records, 'v'), **MEETING_RECORD_FIELDS),
        json_input(work, 'parser_versions', [dict(parser='meeting_records.congress_gov', version='v')], parser='Utf8', version='Utf8')]
    for name in ['meeting_sources', 'recording_sources', 'meeting_status_conflicts', 'committee_codes']:
        value = json.loads((ROOT / 'model/registries' / (name.replace('_', '-') + '.json')).read_text())
        inputs.append(json_input(work, name, value, **REGISTRIES[name]))
    for name in ['spicy_bill_committee_activities', 'spicy_congress_bills', 'spicy_nominations']:
        inputs.append(json_input(work, name, [], **SPICY_SCHEMAS[name]))
    empty = {
        'meeting_detail_observations': EMPTY_OBSERVATIONS,
        'captures': "SELECT arrow_cast(NULL,'FixedSizeBinary(32)') AS sha256,cast(NULL AS VARCHAR) AS retrieved_at,cast(NULL AS VARCHAR) AS mode,cast(NULL AS BOOLEAN) AS complete,cast(NULL AS VARCHAR) AS outcome,cast(NULL AS INT) AS http_status WHERE false",
        'ordered': (
            "SELECT make_array('505') AS meeting_keys,array_slice(make_array(cast(NULL AS VARCHAR)),1,0) AS measure_keys,'print.pdf' AS filename,'pdf' AS format,cast(0 AS INT) AS list_row,"
            "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS chambers,"
            "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS committee_keys,"
            "cast(NULL AS SMALLINT) AS congress,cast(NULL AS DATE) AS document_date,cast(NULL AS VARCHAR) AS document_date_status,false AS hidden "
            "UNION ALL SELECT make_array('506') AS meeting_keys,array_slice(make_array(cast(NULL AS VARCHAR)),1,0) AS measure_keys,'" + TRANSCRIPT + "' AS filename,'pdf' AS format,cast(1 AS INT) AS list_row,"
            "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS chambers,"
            "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS committee_keys,"
            "cast(NULL AS SMALLINT) AS congress,cast(NULL AS DATE) AS document_date,cast(NULL AS VARCHAR) AS document_date_status,false AS hidden"
        ),
        'recordings_export': "SELECT cast(NULL AS VARCHAR) AS video_key,make_array(cast(NULL AS BIGINT)) AS event_ids,make_array(named_struct('body',arrow_cast(NULL,'FixedSizeBinary(32)'),'format',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))) AS tracks WHERE false",
        'retained_caption_tracks': "SELECT cast(NULL AS VARCHAR) AS video_key,arrow_cast(NULL,'FixedSizeBinary(32)') AS track_body WHERE false",
        'meeting_transcript_links': "SELECT 'CHRG-micro' AS package_id,cast(505 AS BIGINT) AS event_id",
        'details': (
            "SELECT 'CHRG-micro' AS package_id,cast(0 AS INT) AS list_row,'pdf' AS format,"
            "array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR))),1,0) AS alternates,"
            "arrow_cast(decode('0000000000000505','hex'),'FixedSizeBinary(8)') AS link_key "
            "UNION ALL SELECT cast(NULL AS VARCHAR),cast(1 AS INT),'pdf',"
            "array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR))),1,0),"
            "arrow_cast(decode('c0ffee123456789a','hex'),'FixedSizeBinary(8)')"
        ),
        'formats': "SELECT 'preference' AS kind,'pdf' AS value,cast(1 AS INT) AS rank",
        'appearance_records_resolved': "SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS name,cast(NULL AS VARCHAR) AS source,cast('listed' AS VARCHAR) AS listing_status WHERE false",
        'package_meeting_links': "SELECT 'CHRG-micro' AS package_id,cast(505 AS BIGINT) AS event_id",
        'package_mods_facts': "SELECT 'CHRG-micro' AS package_id",
    }
    def sql(name):
        return (ROOT / 'model/sql' / (name + '.sql')).read_text()
    steps = [dict(name='captures', sql=empty.pop('captures'), materialize=True),
        selected_record_step('meeting_records', 'meeting_records_input'), *meeting_steps(),
        dict(name='meeting_document_urls', sql=sql('meeting-document-urls'), materialize=True)]
    steps += [dict(name=name, sql=text, materialize=True) for name, text in empty.items()]
    steps.append(dict(name='meetings_export', sql=sql('entity-meetings'), materialize=True))
    run_job(work, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=steps,
        outputs=[parquet_output(work, 'meetings', 'SELECT * FROM meetings_export', ['event_id'])])
    rows = pq.read_table(work / 'meetings.parquet').to_pylist()
    (work / 'expected-status-observations.json').write_text(json.dumps([dict(event_id=k[0], source=k[1],
        status=k[2], meeting_date=k[3], record_sha=k[4], count=n) for k, n in expected.items()], indent=2) + '\n')
    return rows, expected, day, work


def test_status_history_conserves_retained_versions_and_source_pins(sample):
    rows, expected, _day, _work = sample
    _assert_history(rows, expected)
    for row in rows:
        assert [obs['record_sha'] for obs in row['publisher_status_observations']] == sorted(obs['record_sha'] for obs in row['publisher_status_observations'])


def test_current_field_precedence_and_stale_cancellation_remain_unchanged(sample):
    rows, _expected, _day, _work = sample
    found = {row['event_id']: row for row in rows}
    assert (found[501]['status'], str(found[501]['meeting_date']), found[501]['outcome']) == ('Canceled', '2025-07-02', 'canceled')
    assert (found[502]['status'], str(found[502]['meeting_date']), found[502]['outcome']) == ('Scheduled', '2025-07-01', 'unknown')
    assert (found[503]['status'], str(found[503]['meeting_date']), found[503]['outcome']) == ('Scheduled', '2025-07-02', 'unknown')


def test_curated_outcome_and_not_held_are_scoped_to_the_evidence_day(sample):
    rows, _expected, day, _work = sample
    row = next(row for row in rows if row['event_id'] == 110924)
    same = day == '2020-07-17'
    assert row['publisher_status'] == row['status'] == 'Postponed'
    assert row['outcome'] == ('held' if same else 'unknown')
    assert row['outcome_basis'] == ('curated_source_review' if same else 'no_outcome_evidence')
    assert row['outcome_source_reference'] == ('110924' if same else None)
    assert row['not_held'] is (not same)


def test_print_committee_transcript_and_video_locator_outcomes(sample):
    rows, _expected, _day, _work = sample
    found = {row['event_id']: row for row in rows}
    assert found[504]['outcome'] == 'unknown'
    assert (found[505]['outcome'], found[505]['outcome_basis'], found[505]['outcome_source_reference']) == (
        'held', 'printed_hearing', 'CHRG-micro'
    )
    assert (found[506]['outcome'], found[506]['outcome_basis'], found[506]['outcome_source_reference']) == (
        'held', 'committee_transcript', 'c0ffee123456789a'
    )


def test_committee_transcript_outcome_reference_stays_stable_when_list_row_shifts(tmp_path):
    records = [_record('99', 506, 'Scheduled', '2025-07-01', None, document_urls=['https://fixture.test/' + TRANSCRIPT])]
    inputs = [
        json_input(tmp_path, 'meeting_records_input', _normalize_meeting_rows(records, 'v'), **MEETING_RECORD_FIELDS),
        json_input(tmp_path, 'parser_versions', [dict(parser='meeting_records.congress_gov', version='v')], parser='Utf8', version='Utf8'),
    ]
    for name in ['meeting_sources', 'recording_sources', 'meeting_status_conflicts', 'committee_codes']:
        value = json.loads((ROOT / 'model/registries' / (name.replace('_', '-') + '.json')).read_text())
        inputs.append(json_input(tmp_path, name, value, **REGISTRIES[name]))
    for name in ['spicy_bill_committee_activities', 'spicy_congress_bills', 'spicy_nominations']:
        inputs.append(json_input(tmp_path, name, [], **SPICY_SCHEMAS[name]))

    def run_at_row(tx_row):
        sub = tmp_path / f'row-{tx_row}'
        sub.mkdir()
        empty = {
            'meeting_detail_observations': EMPTY_OBSERVATIONS,
            'captures': "SELECT arrow_cast(NULL,'FixedSizeBinary(32)') AS sha256,cast(NULL AS VARCHAR) AS retrieved_at,cast(NULL AS VARCHAR) AS mode,cast(NULL AS BOOLEAN) AS complete,cast(NULL AS VARCHAR) AS outcome,cast(NULL AS INT) AS http_status WHERE false",
            'ordered': (
                f"SELECT make_array('506') AS meeting_keys,array_slice(make_array(cast(NULL AS VARCHAR)),1,0) AS measure_keys,'{TRANSCRIPT}' AS filename,'pdf' AS format,cast({tx_row} AS INT) AS list_row,"
                "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS chambers,"
                "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS committee_keys,"
                "cast(NULL AS SMALLINT) AS congress,cast(NULL AS DATE) AS document_date,cast(NULL AS VARCHAR) AS document_date_status,false AS hidden"
            ),
            'recordings_export': "SELECT cast(NULL AS VARCHAR) AS video_key,make_array(cast(NULL AS BIGINT)) AS event_ids,make_array(named_struct('body',arrow_cast(NULL,'FixedSizeBinary(32)'),'format',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))) AS tracks WHERE false",
            'retained_caption_tracks': "SELECT cast(NULL AS VARCHAR) AS video_key,arrow_cast(NULL,'FixedSizeBinary(32)') AS track_body WHERE false",
            'meeting_transcript_links': "SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false",
            'details': (
                f"SELECT cast(NULL AS VARCHAR) AS package_id,cast({tx_row} AS INT) AS list_row,'pdf' AS format,"
                "array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR))),1,0) AS alternates,"
                "arrow_cast(decode('c0ffee123456789a','hex'),'FixedSizeBinary(8)') AS link_key"
            ),
            'formats': "SELECT 'preference' AS kind,'pdf' AS value,cast(1 AS INT) AS rank",
            'appearance_records_resolved': "SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS name,cast(NULL AS VARCHAR) AS source,cast('listed' AS VARCHAR) AS listing_status WHERE false",
            'package_meeting_links': "SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false",
            'package_mods_facts': "SELECT cast(NULL AS VARCHAR) AS package_id WHERE false",
        }
        sql = lambda name: (ROOT / 'model/sql' / (name + '.sql')).read_text()
        steps = [
            dict(name='captures', sql=empty.pop('captures'), materialize=True),
            selected_record_step('meeting_records', 'meeting_records_input'),
            *meeting_steps(),
            dict(name='meeting_document_urls', sql=sql('meeting-document-urls'), materialize=True),
            *(dict(name=name, sql=text, materialize=True) for name, text in empty.items()),
            dict(name='meetings_export', sql=sql('entity-meetings'), materialize=True),
        ]
        run_job(sub, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=steps,
                outputs=[parquet_output(sub, 'meetings', 'SELECT * FROM meetings_export', ['event_id'])])
        return pq.read_table(sub / 'meetings.parquet').to_pylist()[0]

    before, after = run_at_row(1), run_at_row(42)
    assert before['outcome_source_reference'] == after['outcome_source_reference'] == 'c0ffee123456789a'
    assert before['transcripts'][0]['list_row'] == 1 and after['transcripts'][0]['list_row'] == 42


def test_independent_multiset_check_rejects_omission_and_extra_observation(sample):
    rows, expected, _day, work = sample
    omitted = deepcopy(rows)
    row = next(row for row in omitted if row['event_id'] == 501)
    removed = row['publisher_status_observations'].pop(0)
    with pytest.raises(AssertionError, match='missing=Counter'):
        _assert_history(omitted, expected)
    extra = deepcopy(rows)
    row = next(row for row in extra if row['event_id'] == 501)
    row['publisher_status_observations'].append(deepcopy(row['publisher_status_observations'][0]))
    with pytest.raises(AssertionError, match='extra=Counter'):
        _assert_history(extra, expected)
    (work / 'observation-plants.json').write_text(json.dumps(dict(omission_rejected=True,
        removed=_identity(501, removed), duplicate_extra_rejected=True), indent=2) + '\n')
