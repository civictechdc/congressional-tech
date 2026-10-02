"""Regressions from retained committee pages and native PDF content."""
from copy import deepcopy
from pathlib import Path
import json

import re

import pytest

from congress_api.parsers.senate import parsed
from congress_api.retention.document_index import DocumentSources, fill_document_kind
from congress_api.retention.document_evidence import enrich_document_covers
from test_document_link_resolution import documents, source

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory'
PAGE = 'https://www.aging.senate.gov/hearings/example'


def indexed(page, url):
    context = DocumentSources()
    context.add_senate({'aging.senate.gov': {'pages': {PAGE: page}}})
    row = context.for_url(url)
    fill_document_kind(row)
    return row


@pytest.mark.parametrize('blank', ['<p><b>\u00a0 </b></p>', '<p><strong> </strong></p>', '<h3> </h3>'])
def test_empty_heading_cannot_erase_real_section(blank):
    page = parsed(f'<section><h2>Legislation</h2>{blank}<a href="/download/opaque">File</a></section>', PAGE)
    assert page['documents'][0][0] == 'legislative text'
    assert page['document_metadata'][page['documents'][0][2]]['occurrences'][0]['headings'] == ['Legislation']


def test_real_unknown_heading_still_stops_inheritance():
    page = parsed('<section><h2>Legislation</h2><p><b>Related Files</b></p>'
                  '<p><b> </b></p><a href="/download/opaque">File</a></section>', PAGE)
    assert page['documents'][0][0] == 'other'


@pytest.mark.parametrize('name', ['Wanda and Samuel Ickes', 'Angie and Jonathan Platt',
    'Stephen and Rita Shiman', 'Melanie and Joe Swoboda', 'Mary and Thomas Ward'])
def test_joint_participant_label_preserves_card_without_inventing_individuals(name):
    raw = re.sub(r'Stephanie\s+Blunt', name, (FIXTURES / 'senate-aging-witness-sections.html').read_text())
    page = parsed(raw, PAGE)
    url = 'https://www.aging.senate.gov/download/sca_-blunt_6_17_21_update'
    occurrence, = page['document_metadata'][url]['occurrences']
    assert occurrence['witness_card']['name'] == name
    assert occurrence['witness_indexes'] == []
    row = indexed(page, url)
    assert row['document_kind'] == ['witness-statement']
    assert row['source_participant_label'] == [name]
    assert not row.get('source_witness_name')


@pytest.mark.parametrize('filename,expected', [('biography.pdf', 'witness biography'),
    ('questions-for-the-record.pdf', 'questions for the record'), ('transcript.pdf', 'transcript')])
def test_joint_card_does_not_override_explicit_document_form(filename, expected):
    raw = re.sub(r'Stephanie\s+Blunt', 'Wanda and Samuel Ickes', (FIXTURES / 'senate-aging-witness-sections.html').read_text())
    raw = raw.replace('sca_-blunt_6_17_21_update', filename)
    page = parsed(raw, PAGE)
    assert next(d for d in page['documents'] if d[2].endswith(filename))[0] == expected


def test_explicit_amendment_beats_broad_legislation_section():
    page = parsed('<section><h2>Legislation</h2><p><b> </b></p><p><b>'
        '<a href="../../../download/loeffler-amendment-fo-s3235">Loeffler Amendment fo S.3235</a>'
        '</b></p></section>', PAGE)
    assert page['documents'][0][0] == 'committee amendment'
    assert page['document_metadata'][page['documents'][0][2]]['occurrences'][0]['headings'] == ['Legislation']


def test_bill_topic_in_supporting_material_is_not_bill_text():
    page = parsed('<a href="/download/opaque">Statement supporting the Agriculture Bill</a>', PAGE)
    assert page['documents'][0][0] != 'legislative text'


def test_absolute_dot_segments_join_without_losing_source_urls_or_context():
    canonical = 'https://www.veterans.senate.gov/download/loeffler-amendment-fo-s3235'
    alias = canonical.replace('/download/', '/../../../download/')
    context = DocumentSources({canonical, alias})
    context.add_url(canonical, {'source_link_label': {'Loeffler Amendment fo S.3235'},
                                'source_original_page_url': {'https://www.veterans.senate.gov/2020/8/example'}})
    assert context.for_url(alias) == context.for_url(canonical)
    rows = [source(alias), source(canonical, 'retained-pdf')]
    result, = documents(rows)
    assert result['source_urls'] == sorted([alias, canonical])
    assert result['document_id'] == documents([rows[1]])[0]['document_id']
    assert len(documents([source(canonical+'?id=1'), source(canonical+'?id=2')])) == 2


def test_dot_segments_in_literal_absolute_anchor_keep_the_section():
    url = 'https://www.aging.senate.gov/a/../download/opaque'
    page = parsed(f'<section><h2>Legislation</h2><a href="{url}">File</a></section>', PAGE)
    # Old saved tuples can predate the section reader; retained metadata is
    # sufficient to refine them without rewriting the source URL.
    page['documents'] = [('other', label, target) for _, label, target in page['documents']]
    row = indexed(page, url)
    assert row['source_link_heading'] == ['Legislation']
    assert row['source_link_url'] == [url]
    assert row['document_kind'] == ['legislative-text']


@pytest.mark.parametrize('fixture,kind', [('stenographic', 'transcript'), ('coverless', 'transcript'),
    ('opening', 'opening-statement'), ('paper-questions', 'questions-and-answers'),
    ('bill', 'legislative-text'), ('substitute', 'amendment'), ('testimony', 'witness-statement')])
def test_native_document_forms_survive_to_flat_catalog_fields(fixture, kind):
    data = (FIXTURES / 'document-covers' / (fixture+'.pdf')).read_bytes()
    rows = [dict(filename='opaque.pdf', body_key='body', media_type=['application/pdf'])]
    enrich_document_covers(rows, read_body=lambda _: data)
    fill_document_kind(rows[0])
    assert rows[0]['content_document_kind'] == [kind]
    assert rows[0]['document_kind_source'] == ['content']
    assert rows[0]['document_kind'] == [kind]
    if fixture == 'bill':
        assert rows[0]['content_congress'] == ['117']
        assert rows[0]['content_citation'] == ['S. 2599']
    if fixture == 'substitute':
        assert rows[0]['content_citation'] == ['S. 3235']
        assert rows[0]['content_amendment_type'] == ['substitute']


@pytest.mark.parametrize('fixture', ['letter', 'email'])
def test_judiciary_correspondence_does_not_become_testimony(fixture):
    data = (FIXTURES / 'document-covers' / (fixture+'.pdf')).read_bytes()
    rows = [dict(filename='opaque.pdf', body_key='body', media_type=['application/pdf'])]
    enrich_document_covers(rows, read_body=lambda _: data)
    assert not rows[0].get('content_document_kind')


def test_content_kind_does_not_confirm_candidate_source_association():
    row = dict(filename='opaque.pdf', body_key='body', media_type=['application/pdf'], source_occurrences=[{
        'source_association_basis': ['collector_recovery_candidate'], 'source_document_type': ['witness statement']}])
    before = deepcopy(row['source_occurrences'])
    enrich_document_covers([row], read_body=lambda _: (FIXTURES/'document-covers/testimony.pdf').read_bytes())
    fill_document_kind(row)
    assert row['document_kind'] == ['witness-statement']
    assert row['document_kind_source'] == ['content']
    assert row['source_occurrences'] == before


@pytest.mark.parametrize('record', json.loads((FIXTURES/'document-covers/aging-text.json').read_text()),
                         ids=lambda r: r['filename'])
def test_named_opening_statements_and_gao_testimony(record):
    from congress_api.parsers.document_cover import document_page_fields
    fields = document_page_fields(*record['first_pages'])
    expected = 'witness-statement' if record['filename'].startswith('SCA_GAO') else 'opening-statement'
    assert fields['content_document_kind'] == [expected]


@pytest.mark.parametrize('text', [
    'My report discusses an Opening Statement before the United States Senate Committee on Aging.',
    'Dear Senators,\nThis letter supports the bill. Testimony before the United States Senate Committee on Aging shows why.',
    'Related Files\nStenographic Transcript\nCommittee on Armed Services\nUnited States Senate',
    'S. 123\nIN THE SENATE OF THE UNITED STATES\nOur letter supports this bill.',
    'A BILL\nS. 123\nThis article discusses a bill.',
    'OPENING REMARKS\nWe should amend S. 3235.\nAMENDMENT IN THE NATURE OF A SUBSTITUTE',
])
def test_content_topic_and_reference_controls(text):
    from congress_api.parsers.document_cover import document_page_fields
    assert document_page_fields(text) == {}


@pytest.mark.parametrize('path,expected', [
    ('/../../../download/a', '/download/a'), ('/a/./b/../c', '/a/c'),
    ('/a/.', '/a/'), ('/a/..', '/'), ('/a//b', '/a//b'),
    ('/a/%2E%2E/b', '/a/%2E%2E/b'), ('/a%2Fb', '/a%2Fb'),
])
def test_url_normalization_preserves_escaped_paths_and_queries(path, expected):
    from congress_api.parsers.document_links import http_url
    assert http_url('https://example.test'+path+'?id=1&id=2') == 'https://example.test'+expected+'?id=1&id=2'


def test_member_cards_using_witness_layout_remain_member_statements():
    raw = (FIXTURES/'senate-member-cards.html').read_text()
    page = parsed(raw, 'https://www.armed-services.senate.gov/hearings/example')
    assert page['documents'] and {d[0] for d in page['documents']} == {'member statement'}


def test_readable_pdf_with_empty_user_password_retains_substitute_metadata():
    from congress_api.parsers.document_cover import document_cover
    fields = document_cover((FIXTURES/'document-covers/substitute-original.pdf').read_bytes())
    assert fields['content_document_kind'] == ['amendment']
    assert fields['content_amendment_type'] == ['substitute']
    assert fields['content_congress'] == ['116']


def test_password_required_pdf_abstains():
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from congress_api.parsers.document_cover import document_cover
    writer=PdfWriter()
    writer.add_page(PdfReader(FIXTURES/'document-covers/bill.pdf').pages[0])
    writer.encrypt('test-password')
    stream=BytesIO();writer.write(stream)
    assert document_cover(stream.getvalue()) == {}


def test_source_refresh_keeps_native_publisher_evidence_not_repeated_by_reader(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.document_index import SOURCE_SCHEMA, STRINGS, metadata_type, write_document_indexes, refresh_source_metadata
    url='https://docs.house.gov/meetings/opaque'
    occurrence={'source_document_type':['BR'], 'source_document_type_basis':['publisher'],
                'source_link_url':[url], 'source_receipt_key':['original.jsonl.gz'], 'source_receipt_line':['123']}
    row=dict(filename='opaque',source_url=url,source_occurrences=[occurrence],**occurrence)
    schema=pa.schema([*SOURCE_SCHEMA, *[(k,metadata_type(k)) for k in row if k not in SOURCE_SCHEMA.names]])
    (tmp_path/'indexes').mkdir()
    path=tmp_path/'indexes/document-filenames.parquet'
    write_document_indexes(path,[row],schema)
    refresh_source_metadata(tmp_path,DocumentSources())
    after,=pq.read_table(path).to_pylist()
    assert after['document_kind']==['legislative-text']
    assert after['source_document_type']==['BR']
    assert after['source_receipt_line']==['123']


@pytest.mark.parametrize('same_page,expected', [(True,['member-statement']),
    (False,['member-statement','witness-statement'])])
def test_explicit_card_corrects_old_inference_only_for_the_same_page_and_link(same_page,expected):
    page='https://www.armed-services.senate.gov/hearings/example'
    url='https://www.armed-services.senate.gov/download/inhofe_03-26-20'
    row={'source_occurrences':[
        {'source_document_type':['member statement'],'source_document_type_basis':['publisher_member_card'],
         'source_original_page_url':[page],'source_link_url':[url]},
        {'source_document_type':['witness statement'],'source_document_type_basis':['inventory_inference'],
         'source_original_page_url':[page if same_page else page+'-other'],'source_link_url':[url]}]}
    before=deepcopy(row['source_occurrences'])
    fill_document_kind(row)
    assert row['document_kind']==expected
    assert row['source_occurrences']==before
