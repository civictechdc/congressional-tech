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
