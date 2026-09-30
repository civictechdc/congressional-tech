"""Recover JSON-only failures from XML without losing source or prior captures."""
import json
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from congress_api.acquisition import meetings
from congress_api.models.content import RawContent
from congress_api.parsers.congress import meeting_from_xml, parse_congress_xml
from congress_api.retention.meetings import read as meetings_read
from congress_api.transport import http
from test_explorer_material_adapters import context
from test_meeting_collection import pending, setup

RAW = (Path(__file__).parent / 'fixtures/source_models/meeting-116-senate-326051.xml').read_bytes()


def test_retained_xml_reaches_source_model_and_normalization_without_coercing_identifiers():
    from congress_api.adapters import meetings as adapter
    source = parse_congress_xml(RAW)
    meeting = meeting_from_xml(source)
    assert meeting.congress == 116 and meeting.eventId == '326051'
    assert len(meeting.committees) == 1
    assert len(meeting.relatedItems.bills) == 8
    assert meeting.relatedItems.bills[0].number == '1102'
    assert meeting.relatedItems.nominations[0].part == '00'
    assert meeting.relatedItems.nominations[0].number == 5
    assert meeting.source_xml.body_bytes() == RAW
    records = list(adapter.records([meeting], context('congress.gov')))
    retained = next(r for r in records if r.kind == 'source_record')
    assert retained.payload == meeting.source_dict()
    assert RawContent.model_validate(retained.payload['_source_xml']).body_bytes() == RAW
    assert len([r for r in records if r.kind == 'meeting_subject']) == 13


def test_xml_lists_and_unknown_values_keep_their_evidence():
    raw = b'''<api-root><committeeMeeting><eventId>001</eventId><congress>119</congress><chamber>House</chamber>
<committees><item><systemCode>hsru00</systemCode></item><item><systemCode>hsru01</systemCode></item></committees>
<witnesses/><meetingDocuments><item><documentType>Witness Statement</documentType><future>007</future></item></meetingDocuments>
<future attr="kept">literal</future></committeeMeeting></api-root>'''
    result = meeting_from_xml(parse_congress_xml(raw))
    assert result.eventId == '001'
    assert len(result.committees) == 2 and result.witnesses == []
    assert result.meetingDocuments[0].source_dict() == {'documentType': 'Witness Statement', 'future': '007'}
    assert result.source_dict()['future'] == 'literal'
    assert result.source_xml.body_bytes() == raw


@pytest.mark.parametrize('reason', [500, 'invalid-json'])
def test_failed_json_detail_recovers_xml_and_clears_pending(tmp_path, monkeypatch, reason):
    path, url, old = setup(monkeypatch, tmp_path)
    raw = (RAW.replace(b'<eventId>326051</eventId>', b'<eventId>old</eventId>')
           .replace(b'<congress>116</congress>', b'<congress>112</congress>', 1)
           .replace(b'<chamber>Senate</chamber>', b'<chamber>House</chamber>', 1))
    def get(session, address, key, params=None):
        if params:
            return {'committeeMeetings': [{'url': url}]} if address.endswith('112/house') else {'committeeMeetings': []}
        if reason == 500:
            raise http.HttpRequestError('Failed JSON', 500)
        raise ValueError('Invalid JSON')
    calls = []
    def xml(session, address, **kwargs):
        calls.append((address, kwargs))
        return SimpleNamespace(content=raw)
    monkeypatch.setattr(meetings, 'get', get)
    monkeypatch.setattr(meetings, 'get_with_retry', xml)
    meetings.main(path, nthreads=1)
    saved = meetings_read(path)[url]
    assert saved['eventId'] == 'old' and saved['relatedItems']['nominations'][0]['part'] == '00'
    assert RawContent.model_validate(saved['_source_xml']).body_bytes() == raw
    assert pending(path) == []
    assert calls == [(url, {'params': {'api_key': 'private-key', 'format': 'xml'}, 'attempts': 5})]
    assert 'private-key' not in json.dumps(saved)


@pytest.mark.parametrize('body', [b'<html>Access denied</html>', b'<api-root>broken',
    RAW.replace(b'<congress>116</congress>', b'<congress>bad</congress>', 1),
    RAW.replace(b'<committees><item>', b'<committees><unexpected>', 1).replace(b'</item></committees>', b'</unexpected></committees>', 1)])
def test_unusable_xml_keeps_prior_meeting_and_failed_bytes_for_retry(tmp_path, monkeypatch, body):
    path, url, old = setup(monkeypatch, tmp_path)
    def get(session, address, key, params=None):
        if params:
            return {'committeeMeetings': [{'url': url}]} if address.endswith('112/house') else {'committeeMeetings': []}
        raise http.HttpRequestError('Failed JSON', 500)
    monkeypatch.setattr(meetings, 'get', get)
    monkeypatch.setattr(meetings, 'get_with_retry', lambda *a, **k: SimpleNamespace(content=body))
    with pytest.raises(SystemExit):
        meetings.main(path, nthreads=1)
    assert meetings_read(path)[url] == old and pending(path) == [url]
    failed = json.loads(path.with_suffix(path.suffix + '.pending.json').read_text())
    assert RawContent.model_validate(failed['responses'][url]['_source_xml']).body_bytes() == body


@pytest.mark.parametrize('status', [403, 404, 429, 503, 'request error'])
def test_other_transport_failures_do_not_trigger_xml_fallback(tmp_path, monkeypatch, status):
    path, url, old = setup(monkeypatch, tmp_path)
    def get(session, address, key, params=None):
        if params:
            return {'committeeMeetings': [{'url': url}]} if address.endswith('112/house') else {'committeeMeetings': []}
        raise http.HttpRequestError('Request failed', status)
    monkeypatch.setattr(meetings, 'get', get)
    monkeypatch.setattr(meetings, 'get_with_retry', lambda *a, **k: pytest.fail('Unexpected XML request'))
    with pytest.raises(SystemExit):
        meetings.main(path, nthreads=1)
    assert meetings_read(path)[url] == old and pending(path) == [url]


def test_http_failure_exposes_status_without_query_secrets(monkeypatch):
    monkeypatch.setattr(http.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(http, '_next', defaultdict(float))
    with pytest.raises(http.HttpRequestError) as failure:
        http.get_with_retry(SimpleNamespace(request=lambda *a, **k: SimpleNamespace(status_code=500)),
                            'https://api.congress.gov/v3/committee-meeting/119/house/1?api_key=secret')
    assert failure.value.status == 500
    assert 'secret' not in str(failure.value)


def test_recovery_rejects_a_different_meeting_but_retains_xml(tmp_path, monkeypatch):
    path, url, old = setup(monkeypatch, tmp_path)
    def get(session, address, key, params=None):
        if params:
            return {'committeeMeetings': [{'url': url}]}
        raise http.HttpRequestError('Failed JSON', 500)
    monkeypatch.setattr(meetings, 'get', get)
    monkeypatch.setattr(meetings, 'get_with_retry', lambda *a, **k: SimpleNamespace(content=RAW))
    with pytest.raises(SystemExit):
        meetings.main(path, nthreads=1)
    assert meetings_read(path)[url] == old and pending(path) == [url]
    failed = json.loads(path.with_suffix(path.suffix + '.pending.json').read_text())['responses'][url]
    assert RawContent.model_validate(failed['committeeMeeting']['_source_xml']).body_bytes() == RAW


def test_json_success_does_not_fetch_xml(tmp_path, monkeypatch):
    path, url, old = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(meetings, 'get', lambda session, address, key, params=None:
                        {'committeeMeetings': [{'url': url}]} if params else {'committeeMeeting': old})
    monkeypatch.setattr(meetings, 'get_with_retry', lambda *a, **k: pytest.fail('Unexpected XML request'))
    meetings.main(path, nthreads=1)
    assert '_source_xml' not in meetings_read(path)[url]


def test_empty_xml_objects_remain_empty_objects():
    raw = b'<api-root><committeeMeeting><eventId>1</eventId><congress>119</congress><chamber>House</chamber><location/><relatedItems/></committeeMeeting></api-root>'
    result = meeting_from_xml(parse_congress_xml(raw)).source_dict()
    assert result['location'] == result['relatedItems'] == {}
