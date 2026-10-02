"""Real committee layouts retain document meaning at the linked occurrence."""
from pathlib import Path

import pytest

from congress_api.parsers.senate import parsed
from congress_api.parsers.senate_page import documents
from congress_api.retention.document_index import DocumentSources, fill_document_kind

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory'
PAGE = 'https://www.aging.senate.gov/hearings/example'


def read(name, host):
    return parsed((FIXTURES / name).read_text(), f'https://www.{host}/hearings/example')


def indexed(page, host, link):
    sources = DocumentSources()
    sources.add_senate({host: {'pages': {f'https://www.{host}/hearings/example': page}}})
    row = sources.for_url(link)
    fill_document_kind(row)
    return row


def test_epw_visual_bold_sections_and_linked_question_responses():
    page = read('senate-epw-bold-sections.html', 'epw.senate.gov')
    dupon = next(d for d in page['documents'] if d[1] == 'Dupon')
    assert dupon[0] == 'witness statement'
    row = indexed(page, 'epw.senate.gov', dupon[2])
    assert row['document_kind'] == ['witness-statement']
    assert row['source_link_heading'] == ['Written Testimony Submitted for the Record']
    assert row['source_link_label'] == ['Dupon']  # Preserve the publisher's truncated anchor.
    zero = next(d for d in page['documents'] if d[1] == 'Zero Zon')
    assert zero[0] == 'witness statement'  # The later response heading must not apply backwards.
    responses = next(d for d in page['documents'] if 'Stakeholder Responses' in d[1])
    assert responses[0] == 'questions for the record'


def test_aging_member_statement_section_is_not_a_witness_card():
    page = read('senate-aging-member-sections.html', 'aging.senate.gov')
    link = 'https://www.aging.senate.gov/download/rpc_01_29_2020'
    assert next(d for d in page['documents'] if d[2] == link)[0] == 'member statement'
    row = indexed(page, 'aging.senate.gov', link)
    assert row['document_kind'] == ['member-statement']
    assert row['source_link_heading'] == ['Member Statements']
    assert not row.get('source_witness_name')


def test_aging_witness_card_supplies_type_and_person_for_an_opaque_filename():
    page = read('senate-aging-witness-sections.html', 'aging.senate.gov')
    link = 'https://www.aging.senate.gov/download/sca_-blunt_6_17_21_update'
    assert next(d for d in page['documents'] if d[2] == link)[0] == 'witness statement'
    row = indexed(page, 'aging.senate.gov', link)
    assert row['document_kind'] == ['witness-statement']
    assert row['source_witness_name'] == ['Stephanie Blunt']
    assert row['source_document_type_basis'] == ['publisher_witness_card']


def test_commerce_amendment_list_keeps_bill_context_and_summary_distinct():
    page = read('senate-commerce-amendment-list.html', 'commerce.senate.gov')
    baldwin = next(d for d in page['documents'] if d[1] == 'Baldwin_1 (as modified')
    assert baldwin[0] == 'committee amendment'
    row = indexed(page, 'commerce.senate.gov', baldwin[2])
    assert row['document_kind'] == ['committee-amendment']
    assert row['source_link_heading'] == ['S. 1939, the FAA Reauthorization Act of 2023, as amended by:']
    summary = next(d for d in page['documents'] if d[1] == 'Amendment Summaries')
    assert summary[0] == 'summary'
    assert indexed(page, 'commerce.senate.gov', summary[2])['document_kind'] == ['summary']


def test_help_manager_and_member_amendment_headings():
    page = read('senate-help-amendment-sections.html', 'help.senate.gov')
    assert {d[0] for d in page['documents']} == {'committee amendment'}


@pytest.mark.parametrize('fixture,host,suffix,kind', [
    ('senate-commerce-nested-amendment-list.html', 'commerce.senate.gov', '16D7FE42-7BF0-4580-B7AD-63B5669E2833', 'committee amendment'),
    ('senate-veterans-legislation.html', 'veterans.senate.gov', 's2864-sinema/tillis/blackburn', 'legislative text'),
])
def test_real_nested_lists_and_bold_bill_links(fixture, host, suffix, kind):
    page = read(fixture, host)
    assert next(d for d in page['documents'] if d[2].endswith(suffix))[0] == kind


@pytest.mark.parametrize('heading,kind', [
    ('Legislation', 'legislative-text'), ('Member Statements', 'member-statement'),
    ('Written Testimony Submitted for the Record', 'witness-statement'),
    ('Stakeholder Responses to Senators Questions', 'questions-for-record'),
])
def test_exact_source_section_types_survive_the_index(heading, kind):
    page = parsed(f'<section><h2>{heading}</h2><a href="/download/opaque">File</a></section>', PAGE)
    assert indexed(page, 'aging.senate.gov', page['documents'][0][2])['document_kind'] == [kind]


@pytest.mark.parametrize('raw', [
    '<p>Discussion of <strong>Written Testimony Submitted for the Record</strong> and policy.</p><p><a href="/download/opaque">File</a></p>',
    '<p><strong>Testimony</strong><a href="/download/first">File</a></p><p><a href="/download/opaque">File</a></p>',
    '<p><strong>Written Testimony Submitted for the Record</strong></p><p><strong>Related Files</strong></p><a href="/download/opaque">File</a>',
    '<section><p><strong>Member Statements</strong></p></section><section><a href="/download/opaque">File</a></section>',
    '<p>S. 1939, as amended by:</p><ul><li><a href="/download/first">Baldwin_1</a></li></ul><p><a href="/download/opaque">File</a></p>',
    '<p>S. 1939, as amended by:</p><p>Unrelated information</p><ul><li><a href="/download/opaque">File</a></li></ul>',
    '<section><h2>Legislation discussed in the hearing</h2><a href="/download/opaque">File</a></section>',
])
def test_context_does_not_leak_across_sections_or_from_topic_prose(raw):
    assert next(d for d in parsed(raw, PAGE)['documents'] if d[2].endswith('/opaque'))[0] == 'other'


def test_linked_bold_bill_titles_do_not_replace_the_legislation_section():
    raw = '<section><h2>Legislation</h2><p><strong><a href="/download/opaque">S.2864 (Sinema/Tillis/Blackburn)</a></strong></p></section>'
    page = parsed(raw, PAGE)
    assert page['documents'][0][0] == 'legislative text'
    assert page['document_metadata'][page['documents'][0][2]]['occurrences'][0]['headings'] == ['Legislation']


@pytest.mark.parametrize('intro', [
    'S. 576, the Railway Safety Act of 2023, as amended by:',
    'S. 4357, the Maritime Administration Reauthorization Act, as modified by:',
    'S. 4769, the Validation and Evaluation for the Trustworthy Artificial Intelligence Act, as amended by: PASSED BY VOICE VOTE',
])
def test_commerce_nested_list_introductions(intro):
    raw = f'<ul><li><b>{intro}</b></li><ul><li><a href="/download/opaque">Blackburn_2 (as modified)</a></li></ul><li><a href="/download/next">Other item</a></li></ul>'
    page = parsed(raw, PAGE)
    assert [d[0] for d in page['documents']] == ['committee amendment', 'other']


def test_same_url_under_different_sections_retains_separate_claims():
    page = parsed('<section><h2>Legislation</h2><a href="/download/shared">File</a></section>'
                  '<section><h2>Related Files</h2><a href="/download/shared">File</a></section>', PAGE)
    row = indexed(page, 'aging.senate.gov', page['documents'][0][2])
    assert {(tuple(o['source_link_heading']), tuple(o['source_document_type'])) for o in row['source_occurrences']} == {
        (('Legislation',), ('legislative text',)), (('Related Files',), ('other',))}


def test_witness_card_does_not_replace_a_biography_or_questions_with_testimony():
    raw = (FIXTURES / 'senate-aging-witness-sections.html').read_text()
    original = 'https://www.aging.senate.gov/download/sca_-blunt_6_17_21_update'
    for name, expected in [('biography.pdf', 'witness biography'), ('questions-for-the-record.pdf', 'questions for the record')]:
        page = parsed(raw.replace(original, f'https://www.aging.senate.gov/download/{name}'), PAGE)
        assert next(d for d in page['documents'] if d[2].endswith(name))[0] == expected


def test_an_arbitrary_witness_attachment_is_not_automatically_testimony():
    raw = (FIXTURES / 'senate-aging-witness-sections.html').read_text().replace('Button--hearingLink', 'attachment')
    page = parsed(raw, PAGE)
    assert next(d for d in page['documents'] if 'sca_-blunt_6_17_21_update' in d[2])[0] == 'other'


def test_direct_document_reader_and_typed_page_agree_on_witness_files():
    raw = (FIXTURES / 'senate-aging-witness-sections.html').read_text()
    assert documents(raw, PAGE) == parsed(raw, PAGE)['documents']


@pytest.mark.parametrize('kind,title,expected', [
    ('legislative text', 'S. 123', 'bill_text'),
    ('summary', 'Amendment Summaries', 'supporting'),
    ('committee amendment', 'Changes to witness statements', 'amendment'),
])
def test_normalization_respects_source_type_before_title_words(kind, title, expected):
    from test_explorer_senate_adapter import adapt, of_kind, page
    saved = page(documents=[[kind, title, 'https://www.help.senate.gov/download/opaque']])
    records = adapt(saved)
    material, = of_kind(records, 'material')
    assert material.details.category == expected
    source, = of_kind(records, 'source_record')
    assert source.payload == saved
