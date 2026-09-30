"""Official committee lists retain native values and update atomically."""
import gzip
import json

import pytest
from committee_explorer.export import export
from congress_api.acquisition import committees as collector
from congress_api.acquisition.meetings import API as collector_API
from test_explorer_export import NOW, native, write_meetings


def metadata(congress=115, code='hsru00', kind='Standing', parent=None):
    committee = {'systemCode': code, 'name': f'Committee {code}', 'chamber': 'House', 'committeeTypeCode': kind,
                 'url': f'https://api.congress.gov/v3/committee/house/{code}?format=json'}
    if parent:
        committee['parent'] = {'systemCode': parent}
    return {'congress': congress, 'committee': committee,
            '_url': f'https://api.congress.gov/v3/committee/{congress}', 'retrieved_at': NOW.isoformat()}


def save(path, rows):
    path.write_bytes(gzip.compress('\n'.join(json.dumps(row) for row in rows).encode()))
    return path


def test_collector_paginates_and_keeps_historical_snapshot(tmp_path, monkeypatch):
    meetings = write_meetings(tmp_path, [{**native(), 'congress': c, '_url': f'https://example.test/{c}'} for c in (113, 114, 115)])
    historical = metadata(113)
    output = save(tmp_path / 'committees.jsonl.gz', [historical, metadata(114), metadata(115)])
    calls = []

    def get(session, url, key, params=None):
        if params is None:
            return {'committee': {'systemCode': url.rsplit('/', 1)[1], 'history': []}}
        calls.append((url, params['offset']))
        congress = int(url.rsplit('/', 1)[1])
        offset = params['offset']
        return {'committees': [metadata(congress, 'hsru01' if offset else 'hsru00')['committee']],
                'pagination': {'next': 'next-page'} if not offset else {}}

    monkeypatch.setattr(collector, 'get', get)
    rows = collector.collect(meetings, output, api_key='test-key')
    assert {key: rows['113|hsru00'][key] for key in historical} == historical
    assert rows['113|hsru00']['detail']['systemCode'] == 'hsru00'
    assert len(rows) == 5
    assert calls == [(f'{collector_API}/committee/{c}', o) for c in (114, 115) for o in (0, 1)]
    assert all('test-key' not in row['_url'] for row in rows.values())
    with gzip.open(output, 'rt') as stream:
        assert len([json.loads(line) for line in stream]) == 5


@pytest.mark.parametrize('failure', ['empty', 'request', 'pagination'])
def test_failed_refresh_preserves_previous_bytes(tmp_path, monkeypatch, failure):
    meetings = write_meetings(tmp_path, [native()])
    output = save(tmp_path / 'committees.jsonl.gz', [metadata()])
    before = output.read_bytes()

    def get(*args):
        if failure == 'request':
            raise RuntimeError('request failed')
        return {'committees': [], 'pagination': {'next': 'next-page'} if failure == 'pagination' else {}}

    monkeypatch.setattr(collector, 'get', get)
    with pytest.raises((ValueError, RuntimeError)):
        collector.collect(meetings, output, api_key='test-key')
    assert output.read_bytes() == before


def test_rejected_committee_page_is_retained_without_replacing_snapshot(tmp_path, monkeypatch):
    meetings = write_meetings(tmp_path, [native()])
    output = save(tmp_path / 'committees.jsonl.gz', [metadata()])
    before = output.read_bytes()
    response = {'committees': [{'systemCode': 123, 'futureField': ['unchanged', None]}]}
    monkeypatch.setattr(collector, 'get', lambda *args: response)
    with pytest.raises(ValueError):
        collector.collect(meetings, output, api_key='test-key')
    assert output.read_bytes() == before
    rejected = json.loads(output.with_suffix(output.suffix + '.rejected.json').read_text())
    assert rejected[0]['response'] == response
    assert rejected[0]['offset'] == 0
    assert 'test-key' not in rejected[0]['url']


def test_metadata_enriches_existing_ids_and_preserves_native_evidence(tmp_path):
    meetings = write_meetings(tmp_path, [native()])
    options = dict(meetings=meetings, output_dir=tmp_path / 'public', state_dir=tmp_path / 'state', as_of=NOW)
    _, before = export(**options)
    rows = [metadata(), metadata(code='hsru01', kind='Subcommittee', parent='hsru00'),
            metadata(code='hsta00', kind='Task Force'), metadata(code='hsca00', kind='Commission or Caucus')]
    path = save(tmp_path / 'committees.jsonl.gz', rows)
    manifest, after = export(**options, committees_path=path)
    old_ids = {r.id for r in before.records if r.kind in ('committee', 'committee_term')}
    assert old_ids <= {r.id for r in after.records if r.kind in ('committee', 'committee_term')}
    terms = {r.identifiers[0].value: r for r in after.records if r.kind == 'committee_term'}
    assert terms['hsru00'].committee_type == 'standing'
    assert terms['hsru01'].source_committee_type == 'Subcommittee'
    assert terms['hsru01'].parent.id == terms['hsru00'].id
    assert terms['hsta00'].committee_type == 'task_force'
    assert terms['hsca00'].committee_type == 'commission_or_caucus'
    assert not terms['hsru00'].field_evidence[0].alternatives
    sources = [s for s in after.sources if s.provider == 'congress.gov:committees']
    assert {s.payload['committee']['systemCode'] for s in sources} == set(terms)
    assert all(s.retrieved_at == NOW for s in sources)
    assert next(s for s in manifest.source_scopes if s.provider == 'congress.gov:committees').status == 'included'


def test_limited_export_keeps_official_parent_even_without_parent_meeting(tmp_path):
    row = native()
    row['committees'] = [row['committees'][1]]
    path = save(tmp_path / 'committees.jsonl.gz', [metadata(), metadata(code='hsru01', kind='Subcommittee', parent='hsru00'), metadata(114)])
    manifest, catalog = export(meetings=write_meetings(tmp_path, [row]), committees_path=path,
                               output_dir=tmp_path / 'public', state_dir=tmp_path / 'state', as_of=NOW, limit=1)
    terms = {r.id: r for r in catalog.records if r.kind == 'committee_term'}
    assert len(terms) == 2
    child = next(r for r in terms.values() if r.parent)
    assert child.parent.id in terms
    assert next(s for s in manifest.source_scopes if s.provider == 'congress.gov:committees').status == 'partial'


@pytest.mark.parametrize('timestamp', ['not-a-date', '2026-09-27T12:00:00'])
def test_invalid_metadata_timestamp_does_not_replace_publication(tmp_path, timestamp):
    meetings = write_meetings(tmp_path, [native()])
    options = dict(meetings=meetings, output_dir=tmp_path / 'public', state_dir=tmp_path / 'state', as_of=NOW)
    export(**options)
    before = (tmp_path / 'public/CURRENT.json').read_bytes()
    path = save(tmp_path / 'committees.jsonl.gz', [{**metadata(), 'retrieved_at': timestamp}])
    with pytest.raises(ValueError):
        export(**options, committees_path=path)
    assert (tmp_path / 'public/CURRENT.json').read_bytes() == before


def test_duplicate_committee_pages_do_not_silently_overwrite_source(tmp_path, monkeypatch):
    meetings = write_meetings(tmp_path, [native()])
    output = save(tmp_path / 'committees.jsonl.gz', [metadata()])
    before = output.read_bytes()
    monkeypatch.setattr(collector, 'get', lambda *args: {'committees': [metadata()['committee']], 'pagination': {'next': 'next-page'}})
    with pytest.raises(ValueError, match='Duplicate committee'):
        collector.collect(meetings, output, api_key='test-key')
    assert output.read_bytes() == before


def test_committee_snapshot_roundtrip_is_not_a_meeting(tmp_path):
    from pydantic import ValidationError

    from congress_api.retention.committees import read as read_committees
    from congress_api.retention.committees import write as write_committees
    from congress_api.retention.jsonl import write as write_jsonl
    from congress_api.retention.meetings import read_models
    from congress_api.retention.meetings import write as write_meeting_snapshot

    row = metadata()
    path = tmp_path / 'committees.jsonl.gz'
    write_committees({'115|hsru00': row}, path)
    assert read_committees(path) == [row]
    with pytest.raises(ValidationError):
        read_models(path)

    payload = {'b': {'n': 1}, 'a': {'n': 2}}
    left, right = tmp_path / 'left.gz', tmp_path / 'right.gz'
    write_jsonl(payload, left)
    write_meeting_snapshot(payload, right)
    assert left.read_bytes() == right.read_bytes()
