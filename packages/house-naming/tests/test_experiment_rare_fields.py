"""Regressions from the exhaustive 298-name rare-column review."""
import pytest
from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, filename):
    result = engine.extract(filename)
    assert ''.join(piece['raw'] for piece in result['pieces']) == filename
    for observation in result['observations']:
        for field in observation['fields']:
            assert filename[field['start']:field['end']] == field['raw']
    return result['metadata']


@pytest.mark.parametrize('filename', [
    'Clements Responses to Supplemental QFRs 9-16-20 SENR Cmte Noms Hrg.pdf',
    'Clements Responses to Supplemental QFRs.pdf',
    'Clements Answers to Supplemental Questions for the Record.pdf',
    'Clements Responses to Written QFRs.pdf',
])
def test_response_qualifiers_do_not_become_questioners(engine, filename):
    data = checked(engine, filename)
    assert data['document_kind'] == ['questions-for-record-response']
    assert data['subject_token'] == ['Clements']
    assert 'questioner_token' not in data


@pytest.mark.parametrize('filename', [
    'Clements Responses to Senator Smith QFRs.pdf',
    'Clements Responses to Smith QFRs.pdf',
])
def test_actual_questioner_wording_survives(engine, filename):
    data = checked(engine, filename)
    assert data['document_kind'] == ['questions-for-record-response']
    assert data['questioner_token'] == [filename.split(' to ', 1)[1].split(' QFRs')[0]]


@pytest.mark.parametrize('filename', [
    'Supplemental QFRs for Clements.pdf',
    'Clements Supplemental Statement.pdf',
    'BILLS-119-ResponsesToSupplementalQFRs-B001234-Amdt-1.pdf',
])
def test_response_wording_controls(engine, filename):
    assert 'questions-for-record-response' not in checked(engine, filename).get('document_kind', [])


@pytest.mark.parametrize('filename,subject', [
    ('III.-A.-Testimony-Moore_0.pdf', 'Moore'),
    ('III.-A.-Witness-Testimonies-AY.pdf', 'AY'),
    ('III.-A.-Witness-Testimonies-Hill.pdf', 'Hill'),
    ('III.-A.-Witness-Testimonies-OS-2.pdf', 'OS'),
    ('III.-B.-Testimony-Melia.pdf', 'Melia'),
    ('III.-B.-Witness-Testimonies-Pasa.pdf', 'Pasa'),
    ('III.-B.-Witness-Testimonies-TT-2.pdf', 'TT'),
    ('III.-C.-Testimony-Blagovcanin_0.pdf', 'Blagovcanin'),
    ('III.-C.-Witness-Testimonies-FV.pdf', 'FV'),
    ('III.-C.-Witness-Testimonies-MH-2.pdf', 'MH'),
    ('III.-D.-Testimony-Perry.pdf', 'Perry'),
    ('III.-D.-Witness-Testimonies-BW.pdf', 'BW'),
    ('III.-a.-Heather-Conley-Writen-Testimony-11.03.21_Final.pdf', 'Heather-Conley'),
    ('III.-a.-Omelicheva-Testimony.pdf', 'Omelicheva'),
    ('III.-b.-Csaky-testimony-11-1.pdf', 'Csaky'),
    ('III.-b.-DENBER-Testimony-CounterExtremism-June-12-2019-FINAL.pdf', 'DENBER-Testimony-CounterExtremism'),
    ('III.-c.-Rohac-Testimony-Helsinki-Commission-Full.pdf', 'Rohac-Testimony-Helsinki-Commission-Full'),
])
def test_outline_stays_separate_from_subject(engine, filename, subject):
    data = checked(engine, filename)
    assert data['outline_identifier'] == [filename[:filename.index('.-', 5)+1]]
    assert data['subject_token'] == [subject]
    assert 'name_token' not in data
    assert data['document_kind'] == ['testimony']


@pytest.mark.parametrize('filename', [
    'Haynes Testimony Addendum 2 3-29-22.pdf',
    'haynes-testimony-addendum-2-3-29-22',
    'haynes-testimony-addendum-2-3-29-22&download=1',
])
def test_addendum_components_stay_separate_from_subject(engine, filename):
    data = checked(engine, filename)
    assert data['subject_token'] == [filename[:6]]
    assert data['addendum_marker'][0].lower() == 'addendum'
    assert data['local_number_token'] == ['2']
    assert data['date_token'] == ['3-29-22']


@pytest.mark.parametrize('extension', ['pdf', 'xml'])
def test_compound_opaque_id_has_no_numeric_or_name_fallback(engine, extension):
    data = checked(engine, '64e8b6_a5137a1179b04b3e9ba8d48ca57519fd.' + extension)
    assert data['opaque_identifier'] == ['64e8b6']
    assert data['opaque_hex'] == ['a5137a1179b04b3e9ba8d48ca57519fd']
    assert not set(data) & {'generic_identifier', 'subject_token', 'name_token'}


@pytest.mark.parametrize('filename', [
    'facade_a5137a1179b04b3e9ba8d48ca57519fd.pdf',
    '64-Smith-Testimony.pdf',
    'III.-A.-Agency-Report-on-Testimony-Requirements.pdf',
    'Smith-Testimony-on-Addendum-Policy.pdf',
])
def test_structural_cleanup_preserves_unassigned_text(engine, filename):
    data = checked(engine, filename)
    assert data.get('name_token') or data.get('subject_token')
    if filename.startswith('facade_'):
        assert 'opaque_identifier' not in data


@pytest.mark.parametrize('filename', [
    'Treaty Doc. 117-1.pdf',
    'treaty-document-119-3.pdf',
    'Testimony concerning Treaty Doc. 119-3.pdf',
])
def test_treaty_citation_preserves_reference_code_and_standalone_kind(engine, filename):
    data = checked(engine, filename)
    assert data['citation_marker_code'] == ['tdoc']
    assert data['citation_marker_label'] == ['Treaty document citation']
    assert 'congress' not in data
    assert ('treaty-document' in data.get('document_kind', [])) == (not filename.startswith('Testimony'))


@pytest.mark.parametrize('filename', ['Treaty Documentation 119-3.pdf', 'Treaty Doc Policy.pdf'])
def test_treaty_non_citations_remain_literal(engine, filename):
    assert 'citation_marker_code' not in checked(engine, filename)


def test_literal_display_and_version_fields_are_not_blanket_aliases(engine):
    data = checked(engine, 'Smith Testimony 8-8-19 SENR Cmte MT field Hrg.pdf')
    assert data['field_marker'] == ['field']
    assert data['field_marker_label'] == ['Field']
    data = checked(engine, 'BILLS-119ANSInteriorih2.pdf')
    assert data['version_number_token'] == ['2']
    assert 'stage_occurrence' not in data


def test_target_role_wording_does_not_resolve_a_person(engine):
    data = checked(engine, 'BILLS-1165214ih-ANStotheRepresentativePayeeFraudPreventionActof2019.pdf')
    assert data['target_role_wording'] == ['Representative']
    assert data['target_subject'] == ['RepresentativePayeeFraudPreventionActof2019']
    assert 'member_bioguide_id' not in data


@pytest.mark.parametrize('filename', [
    'BILLS-119-HR1234-TranscriptAct.pdf',
    'BILLS-119TranscriptProtectionActih.pdf',
])
def test_transcript_word_inside_bill_title_is_not_primary_document_kind(engine, filename):
    data = checked(engine, filename)
    assert 'transcript' not in data.get('document_kind', [])
    assert any('Transcript' in value for field in ['description', 'descriptor', 'suffix'] for value in data.get(field, []))


@pytest.mark.parametrize('filename', ['Transcript.pdf', 'Smith Hearing Transcript.pdf', 'Transcript concerning HR1234.pdf'])
def test_primary_transcript_category_survives(engine, filename):
    assert 'transcript' in checked(engine, filename).get('document_kind', [])


@pytest.mark.parametrize('filename,subject', [
    ('09.30.2020 Witness Testimony, Administrator Bridenstine.pdf', 'Administrator Bridenstine'),
    ('Witness Testimony, Doe, Jane.pdf', 'Doe, Jane'),
    ('Smith, Witness Testimony.pdf', 'Smith'),
])
def test_label_separator_commas_do_not_enter_subjects(engine, filename, subject):
    assert checked(engine, filename)['subject_token'] == [subject]


@pytest.mark.parametrize('prefix', [', ', ': ', '; ', '... ', '— ', '– ', '• ', '| ', '!? '])
def test_leading_subject_punctuation_is_trimmed_without_changing_filename(engine, prefix):
    filename = f'Witness Testimony {prefix}Doe, Jane O’Neill-Smith.pdf'
    result = engine.extract(filename)
    assert result['metadata']['subject_token'] == ['Doe, Jane O’Neill-Smith']
    assert ''.join(piece['raw'] for piece in result['pieces']) == filename
    for observation in result['observations']:
        for field in observation['fields']:
            assert filename[field['start']:field['end']] == field['raw']


def test_leading_punctuation_after_subject_role_is_trimmed(engine):
    assert checked(engine, 'Opening Statement Senator: Lee.pdf')['subject_token'] == ['Lee']


def test_subject_cleanup_preserves_balanced_parentheses(engine):
    assert checked(engine, 'Opening Statement Senator (Lee).pdf')['subject_token'] == ['(Lee)']
