"""Committee detail capture preserves full payloads and historical list meaning."""
import gzip
import json
from datetime import datetime
from pathlib import Path

import pytest
from congress_api.acquisition import committees as collector
from congress_api.acquisition.meetings import API as collector_API
from test_committee_metadata import metadata, save
from test_explorer_export import NOW, native, write_meetings
from test_explorer_material_adapters import context


@pytest.mark.parametrize('chamber,code', [('house', 'hsju00'), ('senate', 'ssju00')])
def test_full_details_fetched_once_and_preserved_through_normalization(tmp_path, monkeypatch, chamber, code):
    from congress_api.adapters import committee_metadata as adapter
    detail = json.loads((Path(__file__).parent / f'fixtures/source_models/committee-{chamber}-{code}.json').read_text())['committee']
    detail['futureField'] = {'absentIsDifferent': None, 'literal': '007', 'empty': []}
    detail['history'][0]['futureHistory'] = 'retained'
    meetings = write_meetings(tmp_path, [{**native(), 'congress': c, '_url': f'https://example.test/{c}'} for c in (113, 114, 115)])
    historical = metadata(113, code, kind='Select')
    endpoint = f'{collector_API}/committee/{chamber}/{code}'
    historical['committee']['url'] = endpoint + '?format=json'
    historical['committee']['chamber'] = chamber.title()
    output = save(tmp_path / 'committees.jsonl.gz', [historical])
    detail_calls = []

    def get(session, url, key, params=None):
        if params:
            return {'committees': [{**historical['committee'], 'committeeTypeCode': 'Standing'}]}
        detail_calls.append(url)
        return {'committee': detail}

    monkeypatch.setattr(collector, 'get', get)
    rows = collector.collect(meetings, output, api_key='secret')
    assert detail_calls == [endpoint]
    assert rows[f'113|{code}']['committee'] == historical['committee']
    assert rows[f'113|{code}']['retrieved_at'] == historical['retrieved_at']
    with gzip.open(output, 'rt') as stream:
        stored = [json.loads(line) for line in stream]
    assert all(row['detail'] == detail and row['detail_url'] == endpoint for row in stored)
    assert len({row['detail_retrieved_at'] for row in stored}) == 1
    assert datetime.fromisoformat(stored[0]['detail_retrieved_at']).tzinfo is not None
    records = list(adapter.records(stored, context('congress.gov:committees'), {}))
    assert [r.payload for r in records if r.kind == 'source_record'] == stored
    assert next(r for r in records if r.kind == 'committee_term' and r.congress == 113).committee_type == 'select'
    assert {r.id for r in records if r.kind != 'source_record'} == {
        r.id for r in adapter.records([{k: v for k, v in row.items() if not k.startswith('detail')} for row in stored],
                                      context('congress.gov:committees'), {}) if r.kind != 'source_record'}


def test_reuse_historical_detail_and_refresh_current_detail(tmp_path, monkeypatch):
    meetings = write_meetings(tmp_path, [{**native(), 'congress': c, '_url': f'https://example.test/{c}'} for c in (113, 114, 115)])
    old = metadata(113, 'hszz00')
    old.update(detail={'systemCode': 'hszz00', 'history': [], 'isCurrent': False},
               detail_url=collector.detail_url(old['committee']), detail_retrieved_at=NOW.isoformat())
    current = metadata(115)
    current.update(detail={'systemCode': 'hsru00', 'history': []},
                   detail_url=collector.detail_url(current['committee']), detail_retrieved_at=NOW.isoformat())
    output = save(tmp_path / 'committees.jsonl.gz', [old, metadata(114), current])
    calls = []
    def get(session, url, key, params=None):
        if params:
            return {'committees': [metadata()['committee']]}
        calls.append(url)
        return {'committee': {'systemCode': 'hsru00', 'history': [{'officialName': 'New name'}]}}
    monkeypatch.setattr(collector, 'get', get)
    rows = collector.collect(meetings, output, api_key='secret')
    assert calls == [current['detail_url']]
    assert rows['113|hszz00'] == old
    assert rows['115|hsru00']['detail']['history'] == [{'officialName': 'New name'}]


@pytest.mark.parametrize('failure', ['transport', 'missing', 'invalid', 'wrong-identity'])
def test_failed_detail_preserves_snapshot_and_can_be_retried(tmp_path, monkeypatch, failure):
    meetings = write_meetings(tmp_path, [native()])
    output = save(tmp_path / 'committees.jsonl.gz', [metadata()])
    before = output.read_bytes()
    bad = {'missing': {}, 'invalid': {'committee': {'systemCode': 'hsru00', 'history': 'unexpected'}},
           'wrong-identity': {'committee': {'systemCode': 'hsru01'}}}.get(failure)
    retry = False
    def get(session, url, key, params=None):
        if params:
            return {'committees': [metadata()['committee']]}
        if retry:
            return {'committee': {'systemCode': 'hsru00', 'history': []}}
        if failure == 'transport':
            raise RuntimeError('Request failed')
        return bad
    monkeypatch.setattr(collector, 'get', get)
    with pytest.raises((RuntimeError, ValueError, KeyError)):
        collector.collect(meetings, output, api_key='secret')
    assert output.read_bytes() == before
    if bad is not None:
        rejected = json.loads(output.with_suffix(output.suffix + '.rejected.json').read_text())
        assert rejected[0]['response'] == bad
        assert rejected[0]['url'] == collector.detail_url(metadata()['committee'])
    retry = True
    rows = collector.collect(meetings, output, api_key='secret')
    assert rows['115|hsru00']['detail'] == {'systemCode': 'hsru00', 'history': []}


@pytest.mark.parametrize('url', [None, 'https://example.test/hsru00',
    'https://api.congress.gov/v3/committee/house/other',
    'https://api.congress.gov/v3/committee/house/hsru00/bills'])
def test_detail_endpoint_must_match_publisher_identity(url):
    with pytest.raises(ValueError):
        collector.detail_url({'systemCode': 'hsru00', 'url': url})


def test_joint_detail_url_uses_publisher_chamber_and_omits_query_credentials():
    endpoint = f'{collector_API}/committee/joint/jsec00'
    assert collector.detail_url({'systemCode': 'jsec00', 'url': endpoint + '?api_key=secret&format=json'}) == endpoint
