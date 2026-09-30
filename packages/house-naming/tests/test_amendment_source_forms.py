"""Source amendment IDs retain their full spelling and explicit local parts."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in (*result['observations'], *result['suppressed']):
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result


def fields(result, name, rule=None):
    return [f for m in result['observations'] if rule is None or m['rule'] == rule
            for f in m['fields'] if f['name'] == name]


@pytest.mark.parametrize('name,identifier', [
    ('alsobrooks-s163-amendment-1pdf', '1'),
    ('blunt-rochester-s-163_amendment-3pdf', '3'),
    ('kaine-s-3747-amendment-7pdf', '7'),
    ('02-10-21_rep._velazquez_amendment_1v2.pdf', '1v2'),
    ('09-21-22_meuser_amendment_1v2_tally_sheet.pdf', '1v2'),
    ('Amendment-1a2.pdf', '1a2'),
    ('Amdt_02V003.pdf', '02V003'),
    ('Amnt-1bpdf.pdf', '1b'),
    ('Amendment-01pdf-2', '01'),
    ('Amendment-1v2pdf&download=1', '1v2'),
])
def test_whole_identifiers_and_existing_suffix_policy(engine, name, identifier):
    result = checked(engine, name)
    field, = fields(result, 'amendment_token', 'source-amendment-reference')
    assert field['raw'] == identifier
    assert field['code'] is None and field['context'] is None
    assert not fields(result, 'version_token')


@pytest.mark.parametrize('name,number,marker,revision', [
    ('02-10-21_rep._velazquez_amendment_1v1.pdf', '1', 'v', '1'),
    ('02-10-21_rep._velazquez_amendment_1v2.pdf', '1', 'v', '2'),
    ('Amendment_02V003.pdf', '02', 'V', '003'),
])
def test_local_version_parts_do_not_replace_parent_or_infer_official_numbers(engine, name, number, marker, revision):
    result = checked(engine, name)
    assert [f['raw'] for f in fields(result, 'amendment_token', 'source-amendment-reference')] == [number+marker+revision]
    assert [f['raw'] for f in fields(result, 'local_number_token', 'amendment-local-version')] == [number]
    assert [f['raw'] for f in fields(result, 'revision_marker', 'amendment-local-version')] == [marker]
    assert [f['raw'] for f in fields(result, 'revision_number', 'amendment-local-version')] == [revision]
    assert all(f['code'] is None and f['context'] is None
               for m in result['observations'] if m['rule'] == 'amendment-local-version' for f in m['fields'])


@pytest.mark.parametrize('name', [
    'Amendment-1a2.pdf', 'Amendment-1a.pdf', 'Amendment-1pdf',
])
def test_non_v_forms_are_not_revisions(engine, name):
    result = checked(engine, name)
    assert not fields(result, 'revision_marker', 'amendment-local-version')


@pytest.mark.parametrize('name', [
    'S.1542_Managers_Substitute_Amendment_1cc209c9-0e12-4e78-b44d-52ba94638abb.pdf',
    'S.2578_Managers_Substitute_Amendment_2916c443-069b-4be6-afc0-6ccada2d87a1.pdf',
    'hr-31-managers-amendment-052219',
    'hr-133-substitute-amendment-121119',
    'Amendment-20250318pdf',
    'HHRG-119-IF00-Wstate-Amendment-1v2-20250318.pdf',
    'BILLS-119-HR42-B000668-Amdt-1v2.pdf',
    'PreAmendment-1v2.pdf', 'Amendment-1v2x.pdf', 'Amendment-1pdfx.pdf',
])
def test_dates_ids_and_unsupported_boundaries_remain_protected(engine, name):
    assert not fields(checked(engine, name), 'amendment_token', 'source-amendment-reference')


def test_existing_references_do_not_get_duplicate_observations(engine):
    result = checked(engine, 'Amendment-12a.pdf')
    assert [f['raw'] for f in fields(result, 'amendment_token')] == ['12a']
    assert not fields(result, 'amendment_token', 'source-amendment-reference')


def test_original_assumptions_and_bill_reference_are_retained(engine):
    result = checked(engine, 'alsobrooks-s163-amendment-1pdf')
    assert fields(result, 'amendment_token', 'source-amendment-reference')[0]['raw'] == '1'
    assert [f['raw'] for f in fields(result, 'measure_number')] == ['163']
    assert [f['raw'] for f in fields(result, 'generic_identifier')] == ['1']
    assert [f['raw'] for f in fields(result, 'ignored_suffix')] == ['pdf']
