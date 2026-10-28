"""No-op persistence and bounded ZIP buffers preserve failure evidence."""
import builtins
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from congress_api.acquisition import gpo as fetch
from congress_api.retention import gpo as evidence
from congress_api.transport import zip_member
from test_zip_member_transport import MEMBER, URL, XML, RangeSession

FIXTURES = Path(__file__).parent / 'fixtures' / 'gpo_metadata'
VERSION_A = '2026-10-01T00:00:00Z'
VERSION_B = '2026-10-02T00:00:00Z'


def collector_fixture(tmp_path, monkeypatch, package='CHRG-110shrg41912'):
    raw = (FIXTURES / f'{package}.xml').read_bytes()
    state = dict(mods=raw, listing=[{'packageId': package, 'lastModified': VERSION_A}],
                 transcript=b'first transcript')
    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', lambda *args: state['listing'])
    monkeypatch.setattr(fetch, 'get_with_retry', lambda *args: SimpleNamespace(content=state['mods']))
    monkeypatch.setattr(fetch, 'read_zip_member', lambda session, url, member: SimpleNamespace(
        data=f'<mets xmlns="http://www.loc.gov/METS/" OBJID="{package}"/>'.encode(),
        source={'url': url, 'member': member}))

    def transcript(session, row, captured):
        captured['https://fixture.invalid/transcript'] = evidence.observation(
            state['transcript'], 'https://fixture.invalid/transcript', 'text/html',
            retrieved_at=VERSION_A)
        return dict(hearing_dates='', committee_name='', text_read='yes')

    monkeypatch.setattr(fetch, 'read_transcript', transcript)
    output, retained = tmp_path / 'rows.csv', tmp_path / 'evidence.jsonl.gz'

    def run():
        fetch.main(output, min_congress=110, nthreads=1, refresh_limit=1, evidence_path=retained)

    return state, output, retained, run


def track_evidence_writes(monkeypatch, retained):
    writes = []
    original = evidence.write_atomic_bytes

    def write(path, data, **kwargs):
        if path == retained:
            writes.append(len(data))
        return original(path, data, **kwargs)

    monkeypatch.setattr(evidence, 'write_atomic_bytes', write)
    return writes


def test_settled_evidence_skips_write_but_success_failure_and_retry_persist(tmp_path, monkeypatch):
    package = 'CHRG-110shrg41912'
    state, output, retained, run = collector_fixture(tmp_path, monkeypatch, package)
    run()
    state['listing'] = []
    writes = track_evidence_writes(monkeypatch, retained)
    before = retained.read_bytes()
    run()
    assert writes == []
    assert retained.read_bytes() == before

    rows = evidence.read_csv(output)
    rows[package]['parser_version'] = 'older-parser'
    evidence.write_csv(rows, output)
    run()
    assert len(writes) == 1
    assert evidence.read_csv(output)[package]['parser_version'] == fetch.PARSER_VERSION
    assert evidence.read(retained)[package]['parser_version'] == fetch.PARSER_VERSION

    previous = evidence.read(retained)[package]
    old_row = evidence.read_csv(output)[package]
    state['listing'] = [{'packageId': package, 'lastModified': VERSION_B}]
    state['mods'] = b'<mods>'
    with pytest.raises(SystemExit) as error:
        run()
    assert error.value.code == 1 and len(writes) == 2
    failed = evidence.read(retained)[package]
    assert evidence.body_bytes(failed['failed_mods']) == b'<mods>'
    assert failed['mods'] == previous['mods']
    assert evidence.read_csv(output)[package] == old_row
    pending = Path(str(retained) + '.pending.json')
    assert json.loads(pending.read_text()) == {package: VERSION_B}

    state.update(listing=[], mods=(FIXTURES / f'{package}.xml').read_bytes())
    run()
    assert len(writes) == 3
    assert 'failed_mods' not in evidence.read(retained)[package]
    assert evidence.read_csv(output)[package]['last_modified'] == VERSION_B
    assert json.loads(pending.read_text()) == {}


def test_transcript_backfill_changes_are_persisted_then_settle(tmp_path, monkeypatch):
    package = 'CHRG-113hhrg21122'
    state, output, retained, run = collector_fixture(tmp_path, monkeypatch, package)
    run()
    previous = evidence.read(retained)[package]
    state.update(listing=[], transcript=b'newly read transcript')
    rows = evidence.read_csv(output)
    rows[package]['text_read'] = ''
    evidence.write_csv(rows, output)
    writes = track_evidence_writes(monkeypatch, retained)
    run()
    assert len(writes) == 1
    saved = evidence.read(retained)[package]
    assert saved['mods'] == previous['mods']
    assert evidence.body_bytes(saved['transcripts']['https://fixture.invalid/transcript']) == state['transcript']
    assert evidence.read_csv(output)[package]['text_read'] == 'yes'
    run()
    assert len(writes) == 1


def test_missing_empty_evidence_is_initialized_once(tmp_path, monkeypatch):
    state, output, retained, run = collector_fixture(tmp_path, monkeypatch)
    state['listing'] = []
    writes = track_evidence_writes(monkeypatch, retained)
    run()
    assert len(writes) == 1 and evidence.read(retained) == {}
    run()
    assert len(writes) == 1


def test_equivalent_transcript_backfill_skips_evidence_write(tmp_path, monkeypatch):
    package = 'CHRG-113hhrg21122'
    state, output, retained, run = collector_fixture(tmp_path, monkeypatch, package)
    run()
    state['listing'] = []
    before = retained.read_bytes()
    rows = evidence.read_csv(output)
    rows[package]['text_read'] = ''
    evidence.write_csv(rows, output)
    writes = track_evidence_writes(monkeypatch, retained)
    run()
    assert writes == [] and retained.read_bytes() == before
    assert evidence.read_csv(output)[package]['text_read'] == 'yes'


def test_failed_evidence_persistence_does_not_advance_csv_or_clear_pending(tmp_path, monkeypatch):
    package = 'CHRG-110shrg41912'
    state, output, retained, run = collector_fixture(tmp_path, monkeypatch, package)
    run()
    before = output.read_bytes(), retained.read_bytes()
    state['listing'] = [{'packageId': package, 'lastModified': VERSION_B}]

    def refuse(*args):
        raise OSError('evidence persistence refused')

    monkeypatch.setattr(evidence, 'write', refuse)
    with pytest.raises(OSError, match='evidence persistence refused'):
        run()
    assert (output.read_bytes(), retained.read_bytes()) == before
    assert json.loads(Path(str(retained) + '.pending.json').read_text()) == {package: VERSION_B}


@pytest.mark.parametrize('case', ['success', 'oversized', 'interrupted', 'wrong-range', 'changed-etag'])
def test_zip_freezes_each_received_buffer_once_and_retains_rejection_bytes(monkeypatch, case):
    copies, delivered = [], []

    def freeze(value=b'', *args, **kwargs):
        if isinstance(value, bytearray):
            copies.append(len(value))
        return builtins.bytes(value, *args, **kwargs)

    monkeypatch.setattr(zip_member, 'bytes', freeze, raising=False)

    def mutate(response, call, body):
        if case == 'oversized':
            body = b'x' * 100000
        if case == 'wrong-range':
            response.headers['Content-Range'] = 'bytes 0-0/2'
        if case == 'changed-etag' and call > 1:
            response.headers['ETag'] = '"changed"'
        if case == 'interrupted':
            def chunks(chunk_size):
                yield body[:8192]
                yield body[8192:16384]
                raise requests.exceptions.ChunkedEncodingError('interrupted fixture stream')
            response.iter_content = chunks
        delivered.append(body)
        return body

    session = RangeSession(mutate=mutate)
    if case == 'success':
        result = zip_member.read_zip_member(session, URL, MEMBER)
        assert result.data == XML
        assert len(copies) == len(session.calls) == 4
        assert sum(copies) == sum(r['bytes'] for r in result.source['requests']) == 65680
    else:
        with pytest.raises(zip_member.ZipMemberReadError) as error:
            zip_member.read_zip_member(session, URL, MEMBER)
        expected = delivered[-1][:16384] if case == 'interrupted' else delivered[-1][:65557]
        assert error.value.data == expected
        assert len(copies) == len(session.calls)
        if case == 'oversized':
            assert error.value.source['requests'][-1]['truncated']
        if case == 'changed-etag':
            assert 'ETag changed' in str(error.value)
    assert all(response.raw.closed for response in session.responses)
