"""Native build-blocking checks for the one document rule (ct-3l1c, ct-c6b0, ct-fh62)."""
import os

import pytest

from congress_api.lake.receipt_metadata import EMPTY_SHA256
from congress_api.retention.provenance import json_input, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import entity_track_checks, evidence_checks, evidence_steps


def count(tmp_path, table, rows, check, extra=()):
    inputs = [json_input(tmp_path, 'fixture', rows, sha='Utf8', bytes='Int64', http_status='Int32')]
    steps = [dict(name=table, sql="SELECT decode(sha,'hex') AS sha256,bytes,http_status FROM fixture"), *extra]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        return run_job(tmp_path, engine, inputs=inputs, steps=steps, outputs=[],
                       queries=[dict(name='n', sql=f'SELECT {check} AS n')])['n'][0]['n']


GOOD = dict(sha='ab' * 32, bytes=10, http_status=200)


@pytest.mark.parametrize(('defect', 'expected'), [
    (None, 0), (dict(bytes=0), 1), (dict(sha=EMPTY_SHA256), 1), (dict(http_status=202), 1), (dict(http_status=404), 1)])
def test_non_document_good_fetches_counts_each_defect(tmp_path, defect, expected):
    rows = [GOOD, dict(GOOD, **defect)] if defect else [GOOD]
    step = next(step for step in evidence_steps() if step['name'] == 'non_document_good_fetches')
    assert count(tmp_path, 'good_fetches', rows, evidence_checks()['non_document_good_fetches'], [step]) == expected


@pytest.mark.parametrize(('sha', 'expected'), [('ab' * 32, 0), (EMPTY_SHA256, 1)])
def test_empty_body_tracks_counts_an_empty_track(tmp_path, sha, expected):
    rows = [GOOD, dict(GOOD, sha=sha)]
    assert count(tmp_path, 'recording_track_candidates', rows, entity_track_checks()['empty_body_tracks']) == expected


@pytest.mark.parametrize(('defect', 'expected'), [
    (None, (0, 0, 0)),
    ('segment', (1, 0, 0)),
    ('unread', (0, 1, 0)),
    ('duplicate_label', (0, 0, 1)),
])
def test_playlist_track_checks_flag_each_bad_output_independently(tmp_path, defect, expected):
    track = 'ab' * 32
    segment = 'cd' * 32
    output = [dict(body=track, production='live')]
    if defect == 'segment':
        output.append(dict(body=segment, production='live'))
    if defect == 'duplicate_label':
        output.append(dict(body=track, production='caption'))
    inputs = [
        json_input(tmp_path, 'output_tracks', output, body='Utf8', production='Utf8'),
        json_input(tmp_path, 'parser_versions', [], parser='Utf8', version='Utf8'),
        json_input(tmp_path, 'active_unreadable', [], record_sha='Utf8', body_sha256='Utf8', parser='Utf8', parser_version='Utf8'),
    ]
    steps = [
        dict(name='recording_tracks', sql="""SELECT 'senate:video' AS video_key,
            array_agg(named_struct('body',decode(body,'hex'),'production',production)) AS tracks FROM output_tracks"""),
        dict(name='recording_segment_bodies', sql=f"SELECT decode('{segment}','hex') AS sha256"),
        # This eligible parent is independent of recording_track_candidates.
        dict(name='recording_fetch_candidates', sql=f"SELECT decode('{track}','hex') AS sha256,true AS playlist_candidate"),
        dict(name='selected_playlist_records', sql=f"SELECT decode('{track}','hex') AS record_sha,'completed' AS status"
             + (' WHERE false' if defect == 'unread' else '')),
    ]
    names = ['segment_tracks', 'unread_track_playlists', 'duplicate_track_bodies']
    checks = entity_track_checks()
    sql = 'SELECT ' + ','.join(f'{checks[name]} AS {name}' for name in names)
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        result = run_job(tmp_path, engine, inputs=inputs, steps=steps, outputs=[], queries=[dict(name='counts', sql=sql)])
    assert tuple(result['counts'][0][name] for name in names) == expected
