"""Raw companion markers retain their context without overriding document types."""
import pytest

from house_naming import Engine
from house_naming.filenames import parse_filename


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    assert parse_filename(name).model_dump(mode='json')['matches'] == result['observations']
    for m in result['observations']:
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result


@pytest.mark.parametrize('name,raw', [
    ('S 3679 SXS.pdf', 'SXS'),
    ('S. 1157 MA.pdf', 'MA'),
    ('S.2305 MA.pdf', 'MA'),
    ('s-1067-ma', 'ma'),
    ('s_1114_ma.pdf', 'ma'),
    ('S 1414 MA_c506dbe8-5ffe-4171-8557-486a6241a6b7.pdf', 'MA'),
    ('S. 4189, SxS_241606b5-708b-49c4-9880-1b20982c374b.pdf', 'SxS'),
    ('S. 2355 SxS (2)_cdc056e4-8308-4f12-a644-5662156d6b8d.pdf', 'SxS'),
    ('s-2355-sxs-2pdf', 'sxs'),
    ('s-3679-sxspdf', 'sxs'),
    ('s-1157-mapdf', 'ma'),
    ('S.__ Autism CARES SXS.pdf', 'SXS'),
    ('S.__Older Americans Act SxS.pdf', 'SxS'),
    ('S__Medical Graduate Investment Act of 2024 SxS.pdf', 'SxS'),
    ('Childhood Diabetes Reduction Act SxS_e31b4831-eff3-4edc-b54d-115bca2de4a1.pdf', 'SxS'),
    ('Making America\'s Food Safer Act SxS_7eeacfc0-f58d-401b-9468-37a5e63450a6.pdf', 'SxS'),
])
def test_retained_companion_file_names(engine, name, raw):
    result = checked(engine, name)
    match, = [m for m in result['observations'] if m['rule'] == 'bill-companion-abbreviation']
    field, = match['fields']
    assert (field['name'], field['raw']) == ('document_abbreviation', raw)
    assert (field['start'], field['end']) == (name.index(raw), name.index(raw) + len(raw))
    assert field['code'] is None and field['label'] is None and not field['candidates']
    assert 'source context is required' in field['note']
    assert not any(f['name'] == 'version_token' for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'Grace Bannasch - Shutesbury, MA.pdf',
    'gsa-committee-resolution---va-hampden-county-ma.pdf',
    'MAʻO Testimony for Committee on Indian Affairs- Testimony ag   clean energy.pdf',
    'former_federal_bar_association_ma_presidents_support_for_murphy.pdf',
    'BILLS-118pih-MA-OWNERSHIP-U1.pdf',
    'BILLS-115-5240-L000566-Amdt-MA_01.pdf',
    'BILLS-118-HR995-P000608-Amdt-HR995_MA_01.pdf',
    'BILLS-119-HR1-A000001-Amdt-SXS.pdf',
    'S 1 title MA.pdf',
    'HR 1 MA.pdf',
    'MS 1 MA.pdf',
    'S1MA.pdf',
    'S 1 MARY.pdf',
    'SXS Industries.pdf',
    'S 1 SXS_final.pdf',
    's-2355-sxs-2pdfmore.pdf',
    'caféSXS.pdf',
    '%20SXS.pdf',
    'test%73XS.pdf',
])
def test_other_ma_uses_and_assigned_slots_stay_unchanged(engine, name):
    assert not any(m['rule'] == 'bill-companion-abbreviation'
                   for m in checked(engine, name)['observations'])


def test_bill_identity_and_uuid_are_independent_of_marker(engine):
    name = ' S. 1414 MA_c506dbe8-5ffe-4171-8557-486a6241a6b7.pdf?download=1 '
    result = checked(engine, name)
    fields = [f for m in result['observations'] for f in m['fields']]
    for key, value in [('measure_number', '1414'), ('document_abbreviation', 'MA'),
                       ('opaque_uuid', 'c506dbe8-5ffe-4171-8557-486a6241a6b7'),
                       ('query_text', '?download=1')]:
        assert any(f['name'] == key and f['raw'] == value for f in fields)


def test_query_abbreviations_are_not_filename_markers(engine):
    result = checked(engine, 'S 1.pdf?name=SXS&other=MA')
    assert not any(m['rule'] == 'bill-companion-abbreviation' for m in result['observations'])
