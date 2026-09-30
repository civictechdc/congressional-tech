"""Native types, unknown fields and source identity survive parser boundaries."""
import ast
import importlib
import json
import pkgutil
from pathlib import Path

import pytest
from congress_api import models
from congress_api.adapters import meetings as adapter
from congress_api.models.congress import CommitteeMeeting, parse_response
from congress_api.parsers.congress import parse_congress_xml
from congress_api.parsers.legislators import parse_legislators
from pydantic import BaseModel, ValidationError
from test_explorer_material_adapters import context

FIXTURES = Path(__file__).parent / 'fixtures'


def assert_declared(value):
    """Known real samples may not hide their fields in generic extra storage."""
    if isinstance(value, BaseModel):
        assert not value.model_extra
        for name in type(value).model_fields:
            assert_declared(getattr(value, name))
    elif isinstance(value, dict):
        for item in value.values():
            assert_declared(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_declared(item)


@pytest.mark.parametrize('name', ['committee-house-hsju00', 'committee-senate-ssju00', 'committee-meeting-119-house', 'committees-119'])
def test_real_response_has_declared_fields_and_exact_roundtrip(name):
    raw = json.loads((FIXTURES / 'source_models' / f'{name}.json').read_text())
    source = parse_response(raw)
    assert source.source_dict() == raw
    assert_declared(source)


def test_native_meeting_fields_and_adapter_work_without_csv():
    for raw in json.loads((FIXTURES / 'congress_meetings/native-relations-documents.json').read_text()):
        model = CommitteeMeeting.model_validate(raw)
        assert model.source_dict() == raw
        assert_declared(model)
        legacy = list(adapter.records([raw], context('congress.gov')))
        typed = list(adapter.records([model], context('congress.gov')))
        assert typed == legacy


def test_real_field_address_and_cross_chamber_committees_reach_normalization():
    raw_records = json.loads((FIXTURES / 'source_models/meeting-field-address-and-joint.json').read_text())
    for raw in raw_records:
        result = list(adapter.records([CommitteeMeeting.model_validate(raw)], context('congress.gov')))
        assert next(r for r in result if r.kind == 'source_record').payload == raw
        if raw['eventId'] == '100094':
            location = next(r for r in result if r.kind == 'occurrence').location
            assert (location.building, location.city, location.region) == ('Texas State Capitol', 'Austin', 'TX')
            assert '1100 Congress Avenue, Room E1.010' in location.label
            assert '78701' in location.label
        else:
            assert {r.identifiers[0].value: r.chamber for r in result if r.kind == 'committee_term'} == {
                'hspw00': 'house', 'ssev00': 'senate',
            }


def test_location_keeps_literal_unstructured_addresses_and_no_empty_location():
    assert adapter.meeting_location({'address': 'City Hall, room 01'}).label == 'City Hall, room 01'
    assert adapter.meeting_location({'address': '{}'}) is None
    assert adapter.meeting_location({'building': 'Main site', 'address': '{"building_name": "Other site"}'}).building == 'Main site'


def test_unknowns_nulls_empty_values_and_alias_collisions_stay_literal():
    raw = {'eventId': '00012', 'congress': 119, 'chamber': 'Future Chamber',
           'type': None, 'meetingDocuments': [], 'location': {'address': '{ "room": "01" }'},
           'source_url': 'a new publisher field', 'future': {'blank': '', 'missing': None, 'values': [1, 1]}}
    source = CommitteeMeeting.model_validate(raw)
    assert source.source_url is None  # Native source_url is not the local _url alias.
    assert source.source_dict() == raw
    assert 'date' not in source.source_dict()
    with pytest.raises(ValidationError):
        CommitteeMeeting.model_validate({**raw, 'congress': '119'})
    with pytest.raises(ValidationError):
        CommitteeMeeting.model_validate({**raw, 'congress': True})


def test_legislator_native_fields_all_declared_and_literal():
    data = (FIXTURES / 'source_models/legislators.json').read_bytes()
    records = parse_legislators(data)
    assert [r.source_dict() for r in records] == json.loads(data)
    assert_declared(records)


def test_xml_parser_keeps_every_byte_attribute_and_repeated_element():
    raw = b'<?xml version="1.0"?><api-root><committeeMeeting source="x"><eventId>00012</eventId><extra a="1">A</extra><extra a="2">B</extra></committeeMeeting></api-root>'
    parsed = parse_congress_xml(raw)
    assert parsed.content.body_bytes() == raw
    assert parsed.xml.children[0].attrib == {'source': 'x'}
    assert [node.text for node in parsed.xml.children[0].findall('extra')] == ['A', 'B']


def test_real_xml_keeps_native_text_types_and_distinct_list_element_names():
    path = FIXTURES / 'source_models'
    meeting_bytes = (path / 'meeting-116-senate-326051.xml').read_bytes()
    meeting = parse_congress_xml(meeting_bytes)
    assert meeting.content.body_bytes() == meeting_bytes
    related = meeting.xml.find('committeeMeeting').find('relatedItems')
    assert len(related.find('bills').findall('bill')) == 8
    assert len(related.find('treaties').findall('item')) == 4
    assert related.find('nominations').find('item').find('part').text == '00'
    committee_bytes = (path / 'committee-house-hsju00.xml').read_bytes()
    committee = parse_congress_xml(committee_bytes)
    assert committee.content.body_bytes() == committee_bytes
    assert committee.xml.find('committee').find('isCurrent').text == 'True'
    assert len(committee.xml.find('committee').find('subcommittees').children) == 15


@pytest.mark.parametrize('package,chamber', [('CHRG-119hhrg64429', 'house'), ('CHRG-116shrg42251', 'senate')])
def test_package_only_transcription_uses_native_title_and_chamber(monkeypatch, package, chamber):
    from congress_api.transcripts import context as metadata
    raw = (FIXTURES / 'gpo_metadata' / f'{package}.xml').read_bytes()
    monkeypatch.setattr(metadata, 'fetch', lambda url: raw)
    monkeypatch.setattr(metadata, 'meetings', lambda: {})
    monkeypatch.setattr(metadata, 'roster_for', lambda *args, **kwargs: {})
    monkeypatch.setattr(metadata, 'legislators_current', lambda: {})
    result = metadata.context_for_event('', package)
    assert result.header.chamber == chamber
    assert result.header.title
    if chamber == 'house':
        assert result.header.title == 'FULL COMMITTEE BUSINESS MEETING'


def test_mods_fills_witness_affiliation_without_replacing_role(monkeypatch):
    from congress_api.models.transcription import Person
    from congress_api.parsers.witness_names import person_key
    from congress_api.transcripts import context as metadata

    key = person_key('Jane Witness')
    meeting = {
        'eventId': '1', 'congress': 118, 'chamber': 'House', 'title': 'Hearing',
        'committees': [{'systemCode': 'hsju00', 'name': 'Judiciary'}], 'date': '2024-01-01T15:00:00Z',
        'witnesses': [{'name': 'Jane Witness', 'organization': '', 'position': ''}],
        'videos': [],
    }
    mods_member = Person(name='Jane Witness', role='member', organization='Acme Corp',
                         position='CEO', party='D', state='VA', bioguide_id='W000001', surname='Witness')

    monkeypatch.setattr(metadata, 'meetings', lambda: {'1': meeting})
    monkeypatch.setattr(metadata, 'mods_people', lambda package_id: ({key: mods_member}, {
        'title': 'MODS Title', 'serial': '', 'held_date': '2024-01-01', 'congress': '118',
        'session': '1', 'chamber': 'house', 'committee': 'Judiciary', 'committee_code': 'hsju00',
        'subcommittee': ''}))
    monkeypatch.setattr(metadata, 'roster_for', lambda *a, **k: {})
    monkeypatch.setattr(metadata, 'legislators_current', lambda: {})

    result = metadata.context_for_event('1', package_id='CHRG-118hhrg1')
    person = result.participants[key]
    assert person.role == 'witness'
    assert person.organization == 'Acme Corp'
    assert person.position == 'CEO'
    assert person.party == 'D'
    assert person.state == 'VA'
    assert person.bioguide_id == 'W000001'


def test_source_models_do_not_depend_on_io_or_normalization_and_export_schema():
    forbidden = {'requests', 'csv', 'tinydb', 'pyarrow', 'committee_meeting'}
    for entry in pkgutil.iter_modules(models.__path__):
        module = importlib.import_module(f'{models.__name__}.{entry.name}')
        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            imports = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            assert not any(name.split('.')[0] in forbidden for name in imports)
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, models.SourceModel):
                json.dumps(value.model_json_schema(by_alias=True))
