"""Real discovery cases and controls for preserving useful filename readings."""
import pytest
from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for match in result['observations']:
        for f in match['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert match['start'] <= f['start'] <= f['end'] <= match['end']
    return result


@pytest.mark.parametrize('name', [
    'HHRG-113-JU00-Transcript-20130719.pdf',
    'BILLS-118-SC-AP-FY2025-Interior-FY25InteriorSubcommitteeMark.pdf',
    'BILLS-119-CommitteePrintSubtitleB-P000034-Amdt-050.pdf',
    'HHRG-112-ED-WState-IveyB-20110922-SD001.pdf',
    'Lee-testimony.pdf',
])
@pytest.mark.parametrize('suffix', ['&download=1', '?download=1', '?download=1&format=pdf'])
def test_transport_suffix_keeps_all_useful_metadata_but_not_strict_validity(engine, name, suffix):
    baseline = checked(engine, name)
    result = checked(engine, name + suffix)
    assert result['metadata'] == baseline['metadata']
    assert not result['valid']
    assert any(f['name'] == 'query_text' and f['raw'] == suffix
               for m in result['observations'] for f in m['fields'])


def test_literal_ampersand_is_not_a_transport_boundary(engine):
    row = checked(engine, 'Rock & Roll Testimony.pdf')['metadata']
    assert row['subject_token'] == ['Rock & Roll']
    assert row['document_kind'] == ['testimony']


@pytest.mark.parametrize('prefix', [
    '2DF2F478A5A7A5CD77127C2E58EB6EB2300F508F3E14B23DBADE8F7EFE98E57B.',
    'aa11bb22-1234-abcd-5678-000000000000_',
])
def test_opaque_prefix_does_not_hide_descriptive_payload(engine, prefix):
    payload = 'spw-12032025-hearing-on-nominations-of-beaman-and-weaver'
    result = checked(engine, prefix + payload + '.pdf')
    row = result['metadata']
    assert row['name_token'] == [payload]
    assert row['opaque_identifier'] == [prefix[:-1]]
    assert row['date_token'] == ['12032025']
    assert 'payload' not in row
    assert not {'person_id', 'witness_id', 'author'} & row.keys()


@pytest.mark.parametrize('name,subject', [
    ('Amdt #9 - Joint Staff Sub Amdt to S. 3266 - Agenda Item 14 (FLO22394).pdf',
     '#9 - Joint Staff Sub Amdt to S. 3266 - Agenda Item 14 (FLO22394)'),
    ('Smith (ACME) Testimony.pdf', 'Smith (ACME)'),
    ('Smith [ACME] Testimony.pdf', 'Smith [ACME]'),
    ('Smith (ACME [US]) Testimony.pdf', 'Smith (ACME [US])'),
])
def test_subject_refinement_preserves_balanced_parenthetical_text(engine, name, subject):
    assert checked(engine, name)['metadata']['subject_token'] == [subject]


@pytest.mark.parametrize('label', ['Additional Materials', 'Supporting Materials'])
def test_materials_for_a_document_are_not_that_document(engine, label):
    name = label + ' for Norton Testimony 5-19-22.pdf'
    row = checked(engine, name)['metadata']
    assert row['document_kind'] == ['supporting-material']
    assert row['target_document_kind'] == ['testimony']
    assert row['target_subject'] == ['Norton Testimony 5-19-22']
    assert row['date_token'] == ['5-19-22']
    assert not {'person_id', 'author', 'witness_id'} & row.keys()


@pytest.mark.parametrize('name', [
    'Norton Testimony 5-19-22.pdf',
    'Testimony on Supporting Materials for Schools.pdf',
    'HHRG-119-IF00-Wstate-Additional Materials for Norton Testimony-20250318.pdf',
])
def test_support_phrase_inside_a_title_or_identifier_does_not_reclassify(engine, name):
    row = checked(engine, name)['metadata']
    assert 'supporting-material' not in row.get('document_kind', [])
    assert 'target_document_kind' not in row


def test_topic_report_word_is_not_trimmed_as_a_transcript_label(engine):
    name = 'the-path-forward-key-findings-in-the-syria-study-group-report-transcript-092419'
    row = checked(engine, name)['metadata']
    assert row['subject_token'] == ['the-path-forward-key-findings-in-the-syria-study-group-report']
    assert row['document_kind'] == ['transcript']
    assert row['label'] == ['transcript', 'report']


@pytest.mark.parametrize('possessive', ["'s", '’s', '-s', '_s'])
def test_dangling_role_possessive_is_not_a_subject(engine, possessive):
    name = 'chairman' + possessive + '-opening-statement-final.pdf'
    result = checked(engine, name)
    assert 'subject_token' not in result['metadata']
    assert result['metadata']['subject_role_wording_code'] == ['chair']
    assert result['metadata']['document_kind'] == ['opening-statement']
    assert any(f['name'] == 'subject_token' and f['raw'] == 'chairman' + possessive
               for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name,subject', [
    ('Senator S Testimony.pdf', 'S'),
    ('Chairman-S Testimony.pdf', 'S'),
    ('ranking-member-lee-opening-statement.pdf', 'lee'),
    ('012225rankingmembermerkleyopeningstatement.pdf', 'merkley'),
])
def test_initials_and_real_role_remainders_survive(engine, name, subject):
    assert checked(engine, name)['metadata']['subject_token'] == [subject]
