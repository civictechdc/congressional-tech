"""Inventory acquisition seams and complete offline joins, with network forbidden."""
import datetime as dt
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from congress_api.acquisition import gaps as acquisition
from congress_api.acquisition.gaps import get_witnesses as witness_lists_get_witnesses
from congress_api.acquisition.gaps import probe_day as captions_probe_day
from congress_api.cli.inventory import main
from congress_api.matching import completeness
from congress_api.parsers import witness_pdf as witness_lists
from congress_api.retention.tables import read_csv, read_state, write_state

TODAY = dt.date(2026, 9, 30)
FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory'


def never_get(*args, **kwargs):
    pytest.fail('Unexpected network acquisition')


def test_probes_keep_completed_days_but_not_partial_failures():
    probes, calls = {}, []
    def get(session, url, **kwargs):
        assert session is None and kwargs == {'method': 'HEAD', 'allowed': (200, 404)}
        calls.append(url)
        if len(calls) == 10:
            raise RuntimeError('503')
        return SimpleNamespace(status_code=404)
    with pytest.raises(RuntimeError, match='503'):
        acquisition.probe_days([('ag', '2020-01-01'), ('ag', '2020-01-02')], probes, TODAY, get=get)
    assert list(probes) == ['ag|2020-01-01']
    assert probes['ag|2020-01-01'] == {'urls': [], 'checked': '2026-09-30', 'source': 'HEAD'}
    assert acquisition.probe_days([('ag', '2020-01-01'), ('ag', '2026-09-29')], probes, TODAY, offline=True, get=never_get) == 0
    with pytest.raises(RuntimeError, match='Missing saved Senate probe: ag\\|2020-01-02'):
        acquisition.probe_days([('ag', '2020-01-02')], probes, TODAY, offline=True, get=never_get)


def test_compatibility_calls_delegate_to_acquisition(monkeypatch):
    monkeypatch.setattr(acquisition, 'timestamp', lambda: '2026-09-30T12:00:00+00:00')
    body = (FIXTURES / 'witness-hubzone.pdf').read_bytes()
    def get(session, url, **kwargs):
        assert session is None and kwargs == {'allowed': (200, 404)}
        return SimpleNamespace(status_code=200, content=body)
    before, after = {}, {}
    args = ('key', 'https://example.gov/witness.pdf')
    people = acquisition.get_witnesses(*args, before, 'v1', '2020-01-01', TODAY, False, get=get)
    assert witness_lists_get_witnesses(*args, after, 'v1', '2020-01-01', TODAY, False, get=get) == people
    assert before == after
    assert captions_probe_day('ag', '2020-01-01', get=lambda *a, **k: SimpleNamespace(status_code=404)) == []


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr('requests.sessions.Session.request', never_get)
    meetings = [
        {'eventId': '1', 'congress': 119, 'date': '2026-03-01', 'chamber': 'House', 'type': 'Hearing',
         'title': 'Witness testimony', 'meetingStatus': 'Scheduled', 'committees': [],
         'meetingDocuments': [{'name': 'Witness List', 'url': 'https://example.gov/witness.pdf'}]},
        {'eventId': '2', 'congress': 116, 'date': '2020-01-02', 'chamber': 'Senate', 'type': 'Meeting',
         'title': 'Closed briefing', 'meetingStatus': 'Scheduled', 'committees': [{'systemCode': 'ssaf00'}]},
    ]
    path = tmp_path / 'meetings.jsonl.gz'
    path.write_bytes(gzip.compress(''.join(json.dumps(m) + '\n' for m in meetings).encode(), mtime=0))
    for name, header in {'gpo': 'package_id', 'videos': 'package_id,status', 'channels': 'systemCode',
        'recordings': 'event_id,recording', 'house_documents_found': 'event_id,kind,url',
        'senate_documents_found': 'event_id,kind,url', 'senate_hearing_pages_found': 'event_id,title',
        'house_witnesses_found': 'event_id,name', 'senate_witnesses_found': 'event_id,name'}.items():
        (tmp_path / f'{name}.csv').write_text(header + '\n')
    from congress_api.matching.committees import codes_of
    from congress_api.matching.recordings import senate_comms
    comm, = senate_comms(meetings[1], codes_of(meetings[1]))
    state = {'probes': {f'{comm}|2020-01-02': {'urls': [], 'checked': '2026-09-29', 'source': 'HEAD'}},
             'witness_lists': {'https://example.gov/witness.pdf': witness_lists.pdf_observation((FIXTURES / 'witness-hubzone.pdf').read_bytes())}}
    write_state(tmp_path / 'inventory.json.gz', state)
    return dict(meetings=path, state_dir=tmp_path, output_dir=tmp_path,
                gpo_path=tmp_path / 'gpo.csv', videos_path=tmp_path / 'videos.csv', tinydb_dir=tmp_path,
                recordings=tmp_path / 'recordings.csv', channels_csv_path=tmp_path / 'channels.csv',
                as_of=TODAY, offline=True)


def test_inventory_offline_reads_actual_pdf_observation_and_is_repeatable(inputs, tmp_path):
    main(**inputs)
    people = read_csv(tmp_path / 'meeting_witnesses.csv')
    assert [p['name'] for p in people] == ['Hannibal “Mike” Ware', 'Mansooreh Mollaghasemi', 'Shirley Bailey', 'William B. Shear']
    assert {p['source'] for p in people} == {'witness list document'}
    rows = read_csv(tmp_path / 'meeting_completeness.csv')
    assert next(r for r in rows if r['event_id'] == '1')['witnesses'] == '4'
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.suffix == '.csv' or p.name == 'inventory.json.gz'}
    main(**inputs)
    assert before == {name: (tmp_path / name).read_bytes() for name in before}


def test_offline_missing_witness_leaves_previous_outputs_and_saves_state(inputs, tmp_path):
    main(**inputs)
    previous = (tmp_path / 'meeting_completeness.csv').read_bytes()
    state = read_state(tmp_path / 'inventory.json.gz')
    state.pop('witness_lists')
    write_state(tmp_path / 'inventory.json.gz', state)
    with pytest.raises(RuntimeError, match='Missing saved witness source'):
        main(**inputs)
    assert (tmp_path / 'meeting_completeness.csv').read_bytes() == previous
    assert read_state(tmp_path / 'inventory.json.gz')['probes'] == state['probes']


def test_completeness_uses_saved_mods_without_acquisition(monkeypatch):
    monkeypatch.setattr('requests.sessions.Session.request', never_get)
    package = 'CHRG-113hhrg21122'
    observation = witness_lists.mods_observation((FIXTURES.parent / 'gpo_metadata' / f'{package}.xml').read_bytes())
    meeting = {'eventId': '1', 'congress': 113, 'chamber': 'House', 'type': 'Hearing', 'date': '2013-07-23'}
    index = {'1': dict(gpo_packages=package, committees='', title='Hearing', youtube_ids='', senate_urls='',
                       other_recordings='', text_source='gpo', rescheduled_to='', not_held='')}
    rows, people = completeness.build([meeting], index, [], [], [],
        {'1': package}, {}, {package: observation}, {})
    assert people and rows[0]['witness_source'] == 'gpo'
    assert {p['name'] for p in people} == {p['name'] for p in observation['people']}
