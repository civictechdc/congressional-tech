"""Raw source models retain exact bytes and constrain interpreted structures."""
from datetime import datetime, UTC
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from pydantic import ValidationError

from committee_meeting.common import Ref
from congress_api.adapters import house as adapter
from congress_api.adapters import inventory as inventory_adapter
from congress_api.adapters.common import AdapterContext
from congress_api.house import records
from congress_api.house.source import parse_house_meeting, parse_house_witnesses
from congress_api.inventory.witness_lists import parse_pdf_observation, parse_mods_observation
from congress_api.inventory import witness_lists
from congress_api.models.content import RawContent
from congress_api.models.documents import PdfWitnessObservation
from congress_api.models.house import HouseMeetingXML, HouseWitnessListXML, HouseFileXML, HouseParsedRecord, HouseFileAttributes
from congress_api.models.xml import XmlAttributes, parse_xml_element

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory'


def xml_tree(element):
    return {'tag': element.tag, 'attributes': dict(element.attrib), 'text': element.text or '',
            'tail': element.tail or '', 'children': [xml_tree(child) for child in element]}


@pytest.mark.parametrize('filename,parser,model', [
    ('house-multiple-files.xml', parse_house_meeting, HouseMeetingXML),
    ('house-amendments.xml', parse_house_meeting, HouseMeetingXML),
    ('house-removed.xml', parse_house_meeting, HouseMeetingXML),
    ('house-witnesses.xml', parse_house_witnesses, HouseWitnessListXML),
    ('house-repeated-documents.xml', parse_house_witnesses, HouseWitnessListXML),
])
def test_actual_house_xml_keeps_every_node_attribute_and_original_byte(filename, parser, model):
    raw = (FIXTURES / filename).read_bytes()
    parsed = parser(raw)
    encoded = parsed.source_dict()
    assert encoded['raw_content'] == RawContent.from_bytes(raw, 'application/xml').source_dict()
    assert {k:v for k,v in encoded.items() if k != 'raw_content'} == xml_tree(ET.fromstring(raw))
    restored = model.model_validate(encoded)
    assert restored.source_dict() == encoded
    assert restored.raw_content.body_bytes() == raw


def test_known_fields_are_typed_across_model_roundtrip():
    meeting = parse_house_meeting((FIXTURES / 'house-multiple-files.xml').read_bytes())
    meeting = HouseMeetingXML.model_validate(meeting.source_dict())
    assert meeting.attributes.congress_num == '113'
    assert meeting.details.date.calendar_date == '2013-03-05'
    assert meeting.details.capitol_location.room == 'H-313'
    assert meeting.details.committees[0].attributes.id == 'RU00'
    assert isinstance(meeting.documents[0].files[0], HouseFileXML)
    assert meeting.documents[0].filename_fields.legis_num == '933'
    witnesses = parse_house_witnesses((FIXTURES / 'house-witnesses.xml').read_bytes())
    assert witnesses.panels[0].witnesses[0].fields.firstname == 'Robert'
    assert witnesses.panels[0].witnesses[0].attributes.display_order == 'NA'
    assert witnesses.panels[0].witnesses[0].documents[1].files[0].attributes.doc_type == 'PDF'


def test_field_location_keeps_nested_state_in_typed_reading():
    raw = (FIXTURES / 'house-field-location.xml').read_bytes()
    meeting = parse_house_meeting(raw)
    location = meeting.details.field_location
    assert location.building_name == 'Founders Park'
    assert location.city == 'Islamorada'
    assert location.state.attributes.postal_code == 'FL'
    assert location.state.fullname == 'Florida'
    assert HouseMeetingXML.model_validate(meeting.source_dict()).details.field_location.source_dict() == location.source_dict()
    assert meeting.raw_content.body_bytes() == raw


def test_unknown_repeated_namespaced_fields_and_alias_collisions_remain_exact():
    raw = b'<?xml version="1.0"?><committee-meeting xmlns:x="https://example.org/v2" meeting-id="12" meeting_id="future" new-flag="literal"><!--kept in bytes--><x:extra a="1">first</x:extra>tail<x:extra a="2">second</x:extra></committee-meeting>'
    parsed = parse_house_meeting(raw)
    assert parsed.raw_content.body_bytes() == raw
    assert parsed.attributes.meeting_id == '12'
    assert parsed.attributes.source_dict() == {'meeting-id': '12', 'meeting_id': 'future', 'new-flag': 'literal'}
    assert [node.text for node in parsed.findall('{https://example.org/v2}extra')] == ['first', 'second']
    assert parsed.children[0].tail == 'tail'
    assert parse_xml_element(raw).source_dict() == xml_tree(ET.fromstring(raw))


@pytest.mark.parametrize('payload', [{'doc-url': 12}, {'doc-url': None}, {'future-attribute': True}])
def test_non_string_xml_attributes_fail_instead_of_being_coerced(payload):
    with pytest.raises(ValidationError):
        HouseFileAttributes.model_validate(payload)
    with pytest.raises(ValidationError):
        XmlAttributes.model_validate(payload)


def test_wrong_root_is_rejected_not_treated_as_empty_house_data():
    with pytest.raises(ValueError, match='committee-meeting'):
        parse_house_meeting(b'<html/>')
    with pytest.raises(ValueError, match='witness-list'):
        parse_house_witnesses(b'<committee-meeting/>')


def test_typed_house_parser_reaches_normalization_without_a_saved_file():
    parsed = records.parse_house_record((FIXTURES / 'house-multiple-files.xml').read_bytes(),
                                       (FIXTURES / 'house-witnesses.xml').read_bytes(), '', 'present')
    assert isinstance(parsed, HouseParsedRecord)
    assert parsed.source_bodies['meeting_xml'].body_bytes() == (FIXTURES / 'house-multiple-files.xml').read_bytes()
    context = AdapterContext(now=datetime.now(UTC), input_id='raw-source-test', provider='docs.house.gov', ids=lambda kind,key: kind + ':' + key)
    lookup = {(113, 'house', '100431'): Ref(kind='meeting', id='meeting')}
    typed = list(adapter.records({'100431': parsed}, context, meetings=lookup))
    legacy_import = list(adapter.records({'100431': parsed.source_dict()}, context, meetings=lookup))
    assert [row.model_dump() for row in typed] == [row.model_dump() for row in legacy_import]
    assert next(row for row in typed if row.kind == 'source_record').payload == parsed.source_dict()
    assert len([row for row in typed if row.kind == 'representation']) == 9
    assert len([row for row in typed if row.kind == 'appearance']) == 1


def test_html_fallback_preserves_body_and_typed_file_groups():
    raw = (FIXTURES / 'house-fallback.html').read_bytes()
    parsed = records.parse_house_record(None, None, raw.decode(), 'unfetched')
    assert parsed.source_bodies['page_html'].body_bytes() == raw
    assert sum(len(group.files) for group in parsed.evidence.document_groups) == 7
    payload = parsed.source_dict()
    payload['evidence']['document_groups'][0]['files'][0]['active'] = 'true'
    with pytest.raises(ValidationError):
        HouseParsedRecord.model_validate(payload)


def test_live_html_retains_original_encoding_not_replacement_text(monkeypatch):
    raw = b'<div id="DivMeetingContent">caf\xe9</div>'
    def get(session, url, **kwargs):
        return SimpleNamespace(status_code=404, content=b'absent') if url.endswith('.xml') else SimpleNamespace(status_code=200, content=raw)
    monkeypatch.setattr(records.http, 'get_with_retry', get)
    result = records.fetch({'eventId': '1', 'congress': 119, 'committees': []}, {'urls': ['https://docs.house.gov/missing.xml']})
    assert RawContent.model_validate(result['source_bodies']['page_html']).body_bytes() == raw
    assert result['last_check']['receipts'][-1]['sha256'] == result['source_bodies']['page_html']['sha256']
    assert 'content' not in result['last_check']['receipts'][-1]


def test_rejected_live_xml_retains_the_unparsed_response_in_failure_receipt(monkeypatch):
    raw = b'<html><title>Unexpected upstream page</title></html>'
    monkeypatch.setattr(records.http, 'get_with_retry', lambda *a, **k: SimpleNamespace(status_code=200, content=raw))
    check = {}
    with pytest.raises(ValueError, match='committee-meeting'):
        records.fetch({'eventId': '1', 'congress': 119, 'committees': []},
                      {'urls': ['https://docs.house.gov/meeting.xml']}, check=check)
    assert check['outcome'] == 'error'
    assert len(check['receipts']) == 3
    assert all(RawContent.model_validate(receipt['content']).body_bytes() == raw for receipt in check['receipts'])


@pytest.mark.parametrize('filename', ['witness-hubzone.pdf', 'witness-military-affiliation.pdf', 'witness-scan-agriculture.pdf', 'house-member-schedule.pdf'])
def test_pdf_model_keeps_original_file_pages_and_interpreted_people(filename):
    raw = (FIXTURES / filename).read_bytes()
    result = parse_pdf_observation(raw)
    assert result.content.body_bytes() == raw
    assert result.source_text == '\n'.join(page.text for page in result.pages)
    assert [page.number for page in result.pages] == list(range(1,len(result.pages)+1))
    assert PdfWitnessObservation.model_validate(result.source_dict()).content.body_bytes() == raw
    bad = result.source_dict(); bad['text_present'] = 'true'
    with pytest.raises(ValidationError):
        PdfWitnessObservation.model_validate(bad)


def test_mods_witness_model_reuses_native_model_and_keeps_raw_xml():
    raw = (FIXTURES.parent / 'gpo_metadata/CHRG-113hhrg21122.xml').read_bytes()
    result = parse_mods_observation(raw)
    assert result.content.body_bytes() == raw
    assert result.source_witnesses and result.people
    assert result.people[0].honorific == 'Mr.'
    assert not any(person.model_extra for person in result.people)


def test_document_models_reach_inventory_normalization_without_storage():
    pdf = parse_pdf_observation((FIXTURES / 'witness-hubzone.pdf').read_bytes())
    mods = parse_mods_observation((FIXTURES.parent / 'gpo_metadata/CHRG-113hhrg21122.xml').read_bytes())
    context = AdapterContext(now=datetime.now(UTC), input_id='documents', provider='documents', ids=lambda kind,key: kind + ':' + key)
    typed = list(inventory_adapter.records({'mods': {'one': mods}, 'witness_lists': {'two': pdf}}, context, meetings={}))
    imported = list(inventory_adapter.records({'mods': {'one': mods.source_dict()}, 'witness_lists': {'two': pdf.source_dict()}}, context, meetings={}))
    assert [row.model_dump() for row in typed] == [row.model_dump() for row in imported]
    sources = [row for row in typed if row.kind == 'source_record']
    assert {source.payload['raw_sha256'] for source in sources} == {pdf.raw_sha256, mods.raw_sha256}


def test_failed_pdf_parse_keeps_original_error_body(monkeypatch):
    raw = b'<html>Access denied</html>'
    get = lambda *a, **k: SimpleNamespace(status_code=200, content=raw)
    state = {}
    with pytest.raises(ValueError, match='not a PDF'):
        witness_lists.get_witnesses('one', 'https://example.gov/witnesses.pdf', state, 'v1', '2026-09-28', datetime.now(UTC).date(), False, get=get)
    assert state['one']['last_check']['outcome'] == 'error'
    assert RawContent.model_validate(state['one']['last_check']['content']).body_bytes() == raw


@pytest.mark.parametrize('raw', [b'\xef\xbb\xbf<root/>\r\n', b'\x00\xff\x80binary\r\n'])
def test_raw_body_roundtrip_and_corruption_rejection(raw):
    value = RawContent.from_bytes(raw, 'application/octet-stream')
    assert RawContent.model_validate(value.source_dict()).body_bytes() == raw
    invalid = value.source_dict(); invalid['body'] += 'corrupt'
    with pytest.raises(ValidationError):
        RawContent.model_validate(invalid)
