"""Literal source-context gaps; no source category is copied into filename facts."""
import pytest
from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('name,url,subject,date', [
    ('53501-hbctestimony1.30.2018.pdf',
     'https://www.congress.gov/115/meeting/house/106799/witnesses/53501-hbctestimony1.30.2018.pdf',
     None, '2018-01-30'),
    ('testimonyrevised_cheng_03302023pdf',
     'https://www.agriculture.senate.gov/download/testimonyrevised_cheng_03302023pdf',
     'cheng', '2023-03-30'),
    ('testimonybeaudette',
     'https://www.armed-services.senate.gov/download/testimonybeaudette',
     'beaudette', None),
])
def test_joined_testimony_wording_has_literal_category_without_witness_identity(engine,name,url,subject,date):
    result=engine.extract(name,source_url=url)
    row=result['metadata']
    assert 'testimony' in row['document_kind']
    assert row.get('subject_token') == ([subject] if subject else None)
    assert not row.get('witness_id')
    assert not row.get('sponsor_bioguide_id')
    if date: assert date in row['date_token_candidates']
    if 'revised' in name: assert row['qualifier_wording'] == ['revised']
    if 'hbc' in name:
        assert row['context_token'] == ['hbc']
        assert not row.get('committee_code')
        assert row['generic_identifier'] == ['53501']
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for observation in result['observations']:
        for field in observation['fields']:
            assert name[field['start']:field['end']] == field['raw']


@pytest.mark.parametrize('name,identifier,subject',[
    ('addendum_b_undesser_07192023pdf','b','undesser'),
    ('Addendum_C_Garcia_2026-10-01.pdf','C','Garcia'),
    ('Addendum-Z-Lee-2026-10-01.pdf','Z','Lee'),
])
def test_alphabetic_addendum_keeps_identifier_separate_from_subject(engine,name,identifier,subject):
    result=engine.extract(name)
    row=result['metadata']
    assert row['addendum_identifier'] == [identifier]
    assert row['subject_token'] == [subject]
    assert any(x.lower() == 'addendum' for x in row['qualifier_wording'])
    assert row.get('date_token_candidates')
    assert not row.get('part_number')
    assert not row.get('publication_number')
    for observation in result['observations']:
        for field in observation['fields']:
            assert name[field['start']:field['end']] == field['raw']


@pytest.mark.parametrize('name,url',[
    ('testimonybeaudette',None),
    ('testimonyrevised_cheng_03302023pdf',None),
    ('testimonybeaudette','https://example.org/download/testimonybeaudette'),
    ('Statement-on-testimonybeaudette.pdf',None),
    ('BILLS-119-HR123-TestimonyRevisedAct-ih.pdf',None),
    ('BILLS-119-HR123-AddendumBAct-ih.pdf',None),
    ('Addendum_bill_analysis_2026-10-01.pdf',None),
    ('Addendum_ABC_Garcia_2026-10-01.pdf',None),
])
def test_joined_boundaries_need_the_reviewed_layout_or_source(engine,name,url):
    row=engine.extract(name,source_url=url)['metadata']
    assert 'testimony' not in row.get('document_kind',[])
    assert not row.get('addendum_identifier')


@pytest.mark.parametrize('name', ['tt_ritchie_web.pdf','TT_Aloul.pdf','tt_ponder.pdf','tt_whitehurst.pdf'])
def test_tt_remains_literal_without_a_verified_local_code_meaning(engine,name):
    row=engine.extract(name)['metadata']
    assert [x.lower() for x in row['local_code_token']] == ['tt']
    assert not row.get('document_kind')


@pytest.mark.parametrize('name,kind,subject',[
    ('eapheaa-letter','letter','eapheaa'),
    ('Garcia_letter.pdf','letter','Garcia'),
    ('09-09-21_meuser_2v1_tally_sheet.pdf','tally-sheet','meuser_2v1'),
])
def test_explicit_letter_and_tally_sheet_wording(engine,name,kind,subject):
    result=engine.extract(name)
    row=result['metadata']
    assert kind in row['document_kind']
    assert row['subject_token'] == [subject]
    assert 'amendment' not in row['document_kind']
    if kind == 'tally-sheet':
        assert row['date_token'] == ['09-09-21']
        assert not row.get('date_token_candidates')
    for observation in result['observations']:
        for field in observation['fields']:
            assert name[field['start']:field['end']] == field['raw']


@pytest.mark.parametrize('url',[
    'https://transportation.house.gov/uploadedfiles/tdamend_002_xml1.pdf',
    'https://www.congress.gov/115/meeting/house/106690/documents/tdamend_002_xml1.pdf',
])
def test_corroborated_local_amendment_code_retains_only_filename_components(engine,url):
    result=engine.extract('tdamend_002_xml1.pdf',source_url=url)
    row=result['metadata']
    assert row['document_kind'] == ['amendment']
    assert row['local_code_token'] == ['tdamend']
    assert row['local_identifier'] == ['002']
    assert row['filename_format_token'] == ['xml']
    assert row['local_number_token'] == ['1']
    # The retained PDF names a bill and author, but neither appears in the basename.
    assert not row.get('measure_references')
    assert not row.get('subject_token')
    assert not row.get('sponsor_bioguide_id')


@pytest.mark.parametrize('name,url',[
    ('tdamend_002_xml1.pdf',None),
    ('tdamend_002_xml1.pdf','https://example.org/tdamend_002_xml1.pdf'),
    ('newsletter.pdf',None),
    ('letterman.pdf',None),
    ('Statement-on-eapheaa-letter.pdf',None),
    ('Statement-about-tally-sheet.pdf',None),
    ('09-09-21_statement_about_tally_sheet.pdf',None),
    ('BILLS-119-HR123-TallySheetAct-ih.pdf',None),
    ('BILLS-119-HR123-Garcia-letter-ih.pdf',None),
])
def test_literal_labels_do_not_override_references_or_unqualified_codes(engine,name,url):
    row=engine.extract(name,source_url=url)['metadata']
    assert not {'letter','tally-sheet','amendment'} & set(row.get('document_kind',[]))
