"""Report filename subjects are not necessarily official report numbers."""
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
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
    return result


def fields(result, key):
    return [f for m in result['observations'] for f in m['fields'] if f['name'] == key]


@pytest.mark.parametrize('name,subject', [
    ('HRPT-114-1.pdf', '1'),  # USSS committee report; local legis-num 1.
    ('HRPT-114-122.pdf', '122'),  # Source describes Record Vote No. 122.
    ('HRPT-114-114-2Part1.pdf', '114-2'),  # PDF actually says Report 114-12.
    ('HRPT-116-1053.pdf', '1053'),  # Source names H. Res. 1053.
    ('HRPT-116-116-1.pdf', '116-1'),  # Source names committee rules.
    ('HRPT-117-1.pdf', '1'),  # PDF report number is a placeholder.
    ('HRPT-117-117-2.pdf', '117-2'),  # Source names Committee Print 117-2.
    ('HRPT-117-1171153.pdf', '1171153'),  # Joined digits are not split.
    ('HRPT-117-117385.pdf', '117385'),
    ('HRPT-117-35622.pdf', '35622'),  # Source names H. Rept. 117-356.
    ('HRPT-119-4550.pdf', '4550'),  # PDF is Report 119-233, accompanying HR4550.
    ('HRPT-119-7567-p1.pdf', '7567'),
    ('SRPT-119-00123.xml', '00123'),
    (' HRPT-119-001-0002.pdf.pdf ', '001-0002'),
    ('HRPT-119-119_0002.pdf?download=1', '119_0002'),
])
def test_literal_subject_does_not_invent_an_identity(engine, name, subject):
    result = checked(engine, name)
    field, = fields(result, 'report_subject_token')
    assert field['raw'] == subject
    assert field['code'] is None and field['label'] is None and not field['candidates']
    assert 'No official number, embedded Congress or document identity' in field['note']
    assert not any(fields(result, k) for k in ['publication_number', 'measure_number', 'citation_number', 'referenced_congress'])
    assert len(fields(result, 'congress')) == 1


@pytest.mark.parametrize('ending,marker,number,rule', [
    ('114-2Part1', 'Part', '1', 'part-token'),
    ('114-6Part1', 'Part', '1', 'part-token'),
    ('114-9Part1', 'Part', '1', 'part-token'),
    ('7567-p1', 'p', '1', 'report-part'),
    ('12345-Part111111', 'Part', '111111', 'part-token'),
    ('12345_p111111', 'p', '111111', 'report-part'),
    ('12345PART001', 'PART', '001', 'part-token'),
])
def test_explicit_parts_reuse_the_existing_readers(engine, ending, marker, number, rule):
    result = checked(engine, f'HRPT-119-{ending}.pdf')
    m, = [m for m in result['observations'] if m['rule'] == rule]
    assert [(f['name'], f['raw']) for f in m['fields']] == [('part_marker', marker), ('part_number', number)]
    assert len(fields(result, 'part_number')) == 1
    assert not fields(result, 'date_token') and not fields(result, 'short_date_token')
    assert not fields(result, 'bioguide_token')


@pytest.mark.parametrize('subject', ['12345', '111111', '20250318', '119-12345', '119-111111'])
def test_structured_subject_numbers_are_not_generic_dates(engine, subject):
    result = checked(engine, f'HRPT-119-{subject}.pdf')
    assert fields(result, 'report_subject_token')[0]['raw'] == subject
    assert not fields(result, 'date_token') and not fields(result, 'short_date_token')


@pytest.mark.parametrize('name', [
    'HRPT-119-HR123.pdf', 'HRPT-119-Report123.pdf', 'HRPT-119-123Notes.pdf',
    'HRPT-119-123Part.pdf', 'HRPT-119-123Parts1.pdf', 'HRPT-119-123Part1Notes.pdf',
    'HRPT-119-123-Notes-p1.pdf', 'HRPT-119-123-Paper1.pdf',
    'HRPT-119-123p1.pdf',  # A bare joined p lacks the documented delimiter.
    'CRPT-119hrpt12345.pdf', 'BILLS-119HR12345ih.pdf', '12345.pdf',
    '2025-03-18.pdf', 'HHRG-119-IF00-Wstate-HRPT-119-123-20250318.pdf',
])
def test_other_slots_and_unsupported_suffixes_are_not_numeric_report_subjects(engine, name):
    assert not fields(checked(engine, name), 'report_subject_token')


def test_ordinary_date_and_member_identifiers_keep_their_existing_meaning(engine):
    assert fields(checked(engine, '2025-03-18.pdf'), 'date_token')
    assert fields(checked(engine, 'P111111.pdf'), 'bioguide_token')
