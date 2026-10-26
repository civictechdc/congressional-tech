"""Reject bad XML per package while flushing valid work and retaining retry evidence."""

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from congress_api.acquisition import gpo as fetch
from congress_api.matching.gpo_committees import clean_rows
from congress_api.parsers.gpo import parse_mods_document, parse_package_manifest
from congress_api.parsers.gpo_hearings import parse_mods
from congress_api.retention import gpo as evidence

FIXTURES = Path(__file__).parent / 'fixtures' / 'gpo_metadata'
MODS = (FIXTURES / 'CHRG-113hhrg21122.xml').read_bytes()
METS = (FIXTURES / 'package_manifests' / 'CHRG-116hhrg43625-dip.xml').read_bytes()
FAILED = 'CHRG-113hhrg11111'
VALID = 'CHRG-113hhrg22222'
MODIFIED = '2026-10-01T00:00:00Z'


@pytest.mark.parametrize(('document', 'rejected'), [
    ('mods', b'<metadata><file></metadata>'),  # mismatched tag
    ('manifest', b'<metadata><file></metadata>'),
    ('mods', b'<metadata><unbound:file/></metadata>'),  # unbound prefix
    ('manifest', b'<metadata><unbound:file/></metadata>'),
    ('mods', b'<html>Temporary upstream error</html>'),  # well-formed, wrong document
    ('manifest', b'<html>Temporary upstream error</html>'),
    ('manifest', requests.HTTPError('temporary METS failure')),
])
@pytest.mark.parametrize('has_history', [False, True])
def test_rejected_xml_keeps_history_flushes_neighbor_and_retries(
    tmp_path, monkeypatch, document, rejected, has_history,
):
    output, retained = tmp_path / 'hearings.csv', tmp_path / 'evidence.jsonl.gz'
    previous = {
        'package_id': FAILED,
        'parser_version': 'previous-parser',
        'mods': evidence.observation(MODS, 'https://example.gov/mods.xml', 'application/xml',
                                     retrieved_at='2026-09-01T00:00:00Z'),
        'mods_document': parse_mods_document(MODS).record_dict(),
        'manifest': evidence.observation(METS, 'https://example.gov/mets.xml', 'application/xml',
                                         retrieved_at='2026-09-01T00:00:00Z'),
        'manifest_files': [f.source_dict() for f in parse_package_manifest(METS).files],
        'transcripts': {'https://example.gov/prior.htm': evidence.observation(
            b'Previously captured transcript', 'https://example.gov/prior.htm', 'text/html')},
    }
    if has_history:
        row = asdict(parse_mods(FAILED, MODS, '2026-09-01T00:00:00Z'))
        row.update(parser_version='previous-parser', title='Last valid parsed title', text_read='')
        rows = {FAILED: row}
        clean_rows(rows)
        evidence.write_csv(rows, output)
        old_row = evidence.read_csv(output)[FAILED]
        evidence.write({FAILED: previous}, retained)

    first = True
    calls, transcript_calls = [], []

    def listing(since, key):
        return [
            {'packageId': FAILED, 'lastModified': MODIFIED},
            {'packageId': VALID, 'lastModified': '2026-10-15T00:00:00Z'},
        ] if first else []

    def get(session, url):
        calls.append(url)
        is_mods = url.endswith('/mods.xml')
        assert is_mods or url.endswith('/mets.xml')
        bad_document = is_mods if document == 'mods' else not is_mods
        if first and FAILED in url and bad_document and isinstance(rejected, requests.RequestException):
            raise rejected
        raw = rejected if first and FAILED in url and bad_document else MODS if is_mods else METS
        return SimpleNamespace(content=raw)

    def transcript(session, row, captured):
        transcript_calls.append(row['package_id'])
        return {'hearing_dates': '', 'committee_name': '', 'text_read': 'yes'}

    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', listing)
    monkeypatch.setattr(fetch, 'get_with_retry', get)
    monkeypatch.setattr(fetch, 'read_transcript', transcript)

    with pytest.raises(SystemExit) as error:
        fetch.main(output, min_congress=113, nthreads=2, refresh_limit=10, evidence_path=retained)
    assert error.value.code == 1
    rows, saved = evidence.read_csv(output), evidence.read(retained)
    assert VALID in rows and VALID in saved
    assert saved[VALID]['manifest_files']
    assert transcript_calls == [VALID]  # failed rows also stay out of transcript backfill
    if has_history:
        assert rows[FAILED] == old_row
        for field in ('manifest', 'manifest_files', 'transcripts'):
            assert saved[FAILED][field] == previous[field]
        if document == 'mods':
            for field in ('mods', 'mods_document', 'parser_version'):
                assert saved[FAILED][field] == previous[field]
    else:
        assert FAILED not in rows
        assert 'manifest' not in saved[FAILED] and 'manifest_files' not in saved[FAILED]
        if document == 'mods':
            assert 'mods' not in saved[FAILED] and 'mods_document' not in saved[FAILED]
    failed = saved[FAILED][f'failed_{document}']
    assert evidence.body_bytes(failed) == (b'' if isinstance(rejected, requests.RequestException) else rejected)
    assert failed['error'] and failed['retrieved_at'] and failed['acquisition'] == 'http'
    assert failed['url'].endswith('/mods.xml' if document == 'mods' else '/mets.xml')
    pending = Path(str(retained) + '.pending.json')
    assert json.loads(pending.read_text()) == {FAILED: MODIFIED}

    # The valid newer package moves the listing window past the failed one.
    # With no listing results and no stale-row budget, only pending work retries.
    first = False
    calls.clear()
    fetch.main(output, min_congress=113, nthreads=2, refresh_limit=0, evidence_path=retained)
    assert len(calls) == 2 and all(FAILED in url for url in calls)
    saved = evidence.read(retained)[FAILED]
    assert 'failed_mods' not in saved and 'failed_manifest' not in saved
    assert evidence.body_bytes(saved['mods']) == MODS
    assert evidence.body_bytes(saved['manifest']) == METS
    assert evidence.read_csv(output)[FAILED]['last_modified'] == MODIFIED
    assert json.loads(pending.read_text()) == {}


def test_malformed_mods_without_retained_evidence_still_flushes_valid_work(tmp_path, monkeypatch):
    output = tmp_path / 'hearings.csv'
    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', lambda *args: [
        {'packageId': package, 'lastModified': MODIFIED} for package in (FAILED, VALID)
    ])
    monkeypatch.setattr(fetch, 'get_with_retry', lambda session, url: SimpleNamespace(
        content=b'<mods>' if FAILED in url else MODS))
    monkeypatch.setattr(fetch, 'read_transcript', lambda *args: {
        'hearing_dates': '', 'committee_name': '', 'text_read': 'yes',
    })
    with pytest.raises(SystemExit) as error:
        fetch.main(output, min_congress=113, nthreads=2, refresh_limit=0)
    assert error.value.code == 1
    assert set(evidence.read_csv(output)) == {VALID}
    assert json.loads(Path(str(output) + '.pending.json').read_text()) == {FAILED: MODIFIED}


@pytest.mark.parametrize('parser', ['parse_mods_document', 'parse_package_manifest'])
def test_unexpected_parser_errors_remain_visible(tmp_path, monkeypatch, parser):
    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', lambda *args: [
        {'packageId': FAILED, 'lastModified': MODIFIED},
    ])
    monkeypatch.setattr(fetch, 'get_with_retry', lambda session, url: SimpleNamespace(
        content=MODS if url.endswith('/mods.xml') else METS))

    def broken_parser(data):
        raise AssertionError('unexpected parser defect')

    monkeypatch.setattr(fetch, parser, broken_parser)
    with pytest.raises(AssertionError, match='unexpected parser defect'):
        fetch.main(tmp_path / 'rows.csv', min_congress=113, nthreads=1,
                   evidence_path=tmp_path / 'evidence.jsonl.gz')
