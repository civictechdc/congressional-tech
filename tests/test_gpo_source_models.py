"""Native source structure/bytes survive before legacy GPO row extraction."""
from dataclasses import asdict
import html
import json
from pathlib import Path
import re
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from congress_api.gpo import evidence, fetch, transcripts
from congress_api.gpo.source import parse_mods_document, parse_transcript_html
from congress_api.models.gpo import GpoCollectionPage, GpoEvidenceObservation, ModsDocument

FIXTURES = Path(__file__).parent / 'fixtures' / 'gpo_metadata'


@pytest.mark.parametrize('path', sorted(FIXTURES.glob('*.xml')), ids=lambda p: p.stem)
def test_mods_model_roundtrips_every_element_and_original_bytes(path):
    raw = path.read_bytes()
    source = parse_mods_document(raw)
    restored = ModsDocument.model_validate_json(source.model_dump_json(by_alias=True))
    assert restored.raw_xml == raw
    native_nodes = list(ElementTree.fromstring(raw).iter())
    model_nodes = list(restored.xml.iter())
    assert len(native_nodes) == len(model_nodes)
    for native, model in zip(native_nodes, model_nodes):
        assert (native.tag, native.attrib, native.text or '', native.tail or '') == (
            model.tag, model.attrib, model.text, model.tail)
    assert asdict(fetch.parse_mods(path.stem, source, 'unchanged')) == asdict(
        fetch.parse_mods(path.stem, raw, 'unchanged'))
    assert fetch.mods_witnesses(source) == fetch.mods_witnesses(raw)


def test_mods_native_nominee_and_roles_are_available_without_implying_attendance():
    source = parse_mods_document((FIXTURES / 'CHRG-116shrg42251.xml').read_bytes())
    assert source.root.nominees[0].names[0].text == 'The Honorable Russell T. Vought'
    assert source.root.nominees[0].positions == ['To Be Director of the Office of Management and Budget']
    assert source.root.nominees[0].state == 'VA'
    assert source.root.is_nomination == ['true']
    assert source.root.chambers == ['SENATE']
    assert source.root.source_types == ['N']
    assert any(term.text == 'publisher' for agent in source.root.agents for role in agent.roles for term in role)


def test_mods_unknown_fields_repetitions_namespaces_and_lexical_bytes_survive():
    raw = b'''<?xml version="1.0"?><m:mods xmlns:m="http://www.loc.gov/mods/v3" xmlns:x="urn:future">
<!-- original comment --><m:extension><m:bill congress="119" number="01" type="HR" context="BODY" future="x"/>
<m:heldDate> 2026-01-01 </m:heldDate><m:heldDate/>
<x:new attr="A &amp; B">first<x:nested/>tail</x:new><x:new>second</x:new></m:extension></m:mods>'''
    model = parse_mods_document(raw)
    assert model.root.bills[0].source_dict() == {
        'congress': '119', 'number': '01', 'type': 'HR', 'context': 'BODY', 'future': 'x', 'text': None}
    assert model.root.held_dates == [' 2026-01-01 ', None]
    assert [n.text for n in model.xml.iter('{urn:future}new')] == ['first', 'second']
    restored = ModsDocument.model_validate_json(model.model_dump_json(by_alias=True))
    assert restored.raw_xml == raw  # prefixes, comments and entity spelling included


def test_collection_preserves_unknown_keys_nulls_and_source_alias_collisions():
    payload = {'packages': [{'packageId': 'CHRG-119hhrg1', 'lastModified': 'verbatim',
        'package_id': 'publisher-extension', 'title': None, 'future': {'items': [None, False, 0]}}],
        'count': 1, 'nextPage': None, 'next_page': 'another extension', 'new': []}
    source = GpoCollectionPage.model_validate(payload)
    assert source.packages[0].package_id == 'CHRG-119hhrg1'
    assert source.source_dict() == payload
    with pytest.raises(ValidationError):
        GpoCollectionPage.model_validate({'packages': [{'packageId': 123, 'lastModified': 'x'}]})


def test_evidence_source_bytes_and_native_unknowns_roundtrip(tmp_path):
    raw = b'<html>caf\xe9</html>'
    native = evidence.observation(raw, 'https://www.govinfo.gov/source', 'text/html')
    native['future'] = {'items': [1, None]}
    model = GpoEvidenceObservation.model_validate(native)
    assert model.body_bytes() == raw
    assert model.source_dict() == native
    path = tmp_path / 'source.json'
    evidence.write_observation(model, path)
    assert json.loads(path.read_text()) == native


def test_html_model_keeps_full_source_and_existing_text_extraction():
    raw = (FIXTURES / 'CHRG-119hhrg64429.htm').read_bytes()
    model = parse_transcript_html(raw)
    assert model.source.body_bytes() == raw
    assert model.text == html.unescape(re.sub(r'<[^>]+>', '', raw.decode()))
    latin = b'<pre>caf\xe9\r\n</pre>'
    model = parse_transcript_html(latin, decoded_text=latin.decode('latin-1'))
    assert model.text == 'caf\xe9\r\n'
    assert model.source.body_bytes() == latin


def test_transcript_download_retains_short_source_even_when_no_text_is_published(tmp_path, monkeypatch):
    package = 'CHRG-119hhrg64429'
    row = tmp_path / 'rows.csv'
    row.write_text(f'package_id,html_url\n{package},https://www.govinfo.gov/short.htm\n')
    raw = b'<html><pre>Title only</pre></html>'
    monkeypatch.setattr(transcripts, 'get_with_retry', lambda *a: SimpleNamespace(content=raw, text=raw.decode()))
    out = tmp_path / 'out'
    transcripts.main(out, row, nthreads=1)
    capture = GpoEvidenceObservation.model_validate_json((out / 'source' / f'{package}.json').read_text())
    assert capture.body_bytes() == raw
    assert capture.acquisition == 'http' and capture.retrieved_at
    assert not (out / f'{package}.txt').exists()


def test_existing_plain_text_is_skipped_without_inventing_original_html(tmp_path, monkeypatch):
    row = tmp_path / 'rows.csv'
    row.write_text('package_id,html_url\nCHRG-119hhrg1,https://www.govinfo.gov/1.htm\n')
    (tmp_path / 'CHRG-119hhrg1.txt').write_text('Existing derived text')
    monkeypatch.setattr(transcripts, 'get_with_retry', lambda *a: pytest.fail('existing TXT must retain skip behavior'))
    transcripts.main(tmp_path, row, nthreads=1)
    assert not (tmp_path / 'source').exists()


def test_real_short_complete_markup_is_saved_but_unavailable_stub_is_not(tmp_path, monkeypatch):
    packages = ['CHRG-115hhrg33061', 'CHRG-113hhrg88163']
    row = tmp_path / 'rows.csv'
    row.write_text('package_id,html_url\n' + ''.join(
        f'{package},https://www.govinfo.gov/{package}.htm\n' for package in packages))
    def response(session, url):
        raw = (FIXTURES / url.rsplit('/', 1)[-1]).read_bytes()
        return SimpleNamespace(content=raw, text=raw.decode())
    monkeypatch.setattr(transcripts, 'get_with_retry', response)
    out = tmp_path / 'out'
    transcripts.main(out, row, nthreads=1)
    text = (out / 'CHRG-115hhrg33061.txt').read_text()
    assert len(text) < transcripts.MIN_TEXT_CHARS
    assert 'at 11:06 a.m.' in text and 'at 11:09 a.m.' in text
    assert 'Committee Resolution 115-19' in ' '.join(text.split()) and 'Mr. Brady.' in text
    assert not (out / 'CHRG-113hhrg88163.txt').exists()
    assert all((out / 'source' / f'{p}.json').exists() for p in packages)


def test_real_special_committee_name_retains_native_descriptor():
    raw = (FIXTURES / 'CHRG-114shrg51750.htm').read_text()
    assert fetch.committee_on_title_page(raw) == 'Special Committee on Aging'
    assert fetch.committee_on_title_page('SELECT COMMITTEE ON INTELLIGENCE\nUNITED STATES SENATE') == 'Select Committee on Intelligence'
    assert fetch.committee_on_title_page('JOINT COMMITTEE ON TAXATION\nHOUSE OF REPRESENTATIVES') == 'Joint Committee on Taxation'


def test_real_addendum_part_name_reaches_rendition_metadata_without_changing_title():
    path = FIXTURES / 'CHRG-116shrg63315.xml'
    model = parse_mods_document(path.read_bytes())
    assert model.constituents[1].titles[0].part_name == 'Addendum 1'
    row = fetch.parse_mods(path.stem, model, '')
    files = json.loads(row.file_metadata)
    supplement = [fields for url, fields in files.items() if '-add1' in url]
    primary = [fields for url, fields in files.items() if '-add1' not in url]
    assert len(supplement) == len(primary) == 2
    assert all(f['part_name'] == 'Addendum 1' for f in supplement)
    assert all('part_name' not in f for f in primary)
    assert {f['title'] for f in files.values()} == {'OVERSIGHT OF THE CROSSFIRE HURRICANE INVESTIGATION: DAY 2'}
