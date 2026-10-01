"""Source-observed degree clauses, plus constructed boundary controls."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for match in (*result['observations'], *result['suppressed']):
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
    return result


def fields(result, key, rule=None):
    return [f for m in result['observations'] if rule is None or m['rule'] == rule
            for f in m['fields'] if f['name'] == key]


def values(result, key, rule=None):
    return [f['raw'] for f in fields(result, key, rule)]


@pytest.mark.parametrize('name,wording,code,number', [
    ('H.R. 31_Paul_1st_Degree_2_REVISED.pdf', '1st_Degree', '1', '2'),
    ('S. 482_Cardin_1st_Degree_7_REVISED1.pdf', '1st_Degree', '1', '7'),
    ('S.1462_Welch_1st_Degree_01.pdf', '1st_Degree', '1', '01'),
    ('s1462_welch_1st_degree_02pdf-1', '1st_degree', '1', '02'),
    ('s-3199-rounds-first-degree-1032922', 'first-degree', '1', '1032922'),
    ('North Macedonia Resolution_Paul_1st_Degree_1.pdf', '1st_Degree', '1', '1'),
    ('S1_Third_Degree_3.pdf', 'Third_Degree', '3', '3'),  # Constructed.
])
def test_literal_degree_and_whole_local_number(engine, name, wording, code, number):
    result = checked(engine, name)
    field, = fields(result, 'degree_token')
    assert (field['raw'], field['code'], field['context']) == (wording, code, None)
    assert 'Literal degree wording' in field['note']
    assert values(result, 'local_number_token', 'degree-local-number') == [number]
    assert not fields(result, 'amendment_degree')
    local, = fields(result, 'local_number_token', 'degree-local-number')
    assert 'not an established bill or amendment sequence' in local['note']
    assert not any(f['start'] < local['end'] and f['end'] > local['start']
                   for f in fields(result, 'generic_identifier'))


@pytest.mark.parametrize('name,target,numbers', [
    ('H.R.260_Shaheen_2nd_Degree_1_to_Shaheen_1st_Degree_3.pdf', 'Shaheen', ['1', '3']),
    ('S.1462_Boozman_2nd_Degree_to_Schiff_1st_Degree_1.pdf', 'Schiff', ['1']),
    ('s2043_schatz_2nd_degree_4_-to_menendez_1st_degree_2', 'menendez', ['4', '2']),
    ('sjres10-hagerty-2nd-degree-1-to-hagerty-1st-degree1-080421', 'hagerty', ['1', '1']),
    ('S1_Smith_2nd_degree_01_to_Van_Hollen-Smith_1st_degree_02.pdf', 'Van_Hollen-Smith', ['01', '02']),
])
def test_explicit_target_keeps_two_distinct_degree_clauses(engine, name, target, numbers):
    result = checked(engine, name)
    assert [f['code'] for f in fields(result, 'degree_token')] == ['2', '1']
    assert values(result, 'local_number_token', 'degree-local-number') == numbers
    assert values(result, 'target_subject', 'degree-target') == [target]
    assert 'no person identity' in fields(result, 'target_subject', 'degree-target')[0]['note']


@pytest.mark.parametrize('name,marker,placeholder,code', [
    ('S.__Bennet_1st_Degree_11.pdf', 'S.', '__', 's'),
    ('S.___Bennet_1st_Degree_01_d91faa5b-4bb2-466d-8675-13becf679c7b.pdf', 'S.', '___', 's'),
    ('S___, Strategic Competition Act of 2021_Cardin_1st_Degree_2.pdf', 'S', '___', 's'),
    ('H.R.___Smith_1st_Degree_01.pdf', 'H.R.', '___', 'hr'),
    ('H_Con_Res___Smith.pdf', 'H_Con_Res', '___', 'hconres'),
    ('S_Res___Draft.pdf', 'S_Res', '___', 'sres'),
])
def test_placeholder_reuses_measure_vocabulary_without_inventing_number(engine, name, marker, placeholder, code):
    result = checked(engine, name)
    assert values(result, 'measure_token', 'measure-placeholder') == [marker]
    assert fields(result, 'measure_token', 'measure-placeholder')[0]['code'] == code
    assert values(result, 'number_placeholder', 'measure-placeholder') == [placeholder]
    assert not fields(result, 'measure_number')
    assert not fields(result, 'congress')


def test_actual_uuid_and_modified_spelling_remain_intact(engine):
    name = 'S.___Grassley_1st_Degree_01_Modfied_92ae810d-649a-4a3b-8edc-64ee0c0aee3a.pdf'
    result = checked(engine, name)
    assert values(result, 'opaque_uuid') == ['92ae810d-649a-4a3b-8edc-64ee0c0aee3a']
    assert values(result, 'local_number_token', 'degree-local-number') == ['01']
    assert 'Modfied' in result['input']


@pytest.mark.parametrize('number', ['02', '03'])
def test_actual_hanging_pdf_copy_suffix_survives_local_number_refinement(engine, number):
    result = checked(engine, f's1462_welch_1st_degree_{number}pdf-1')
    assert values(result, 'ignored_suffix') == ['pdf']
    assert values(result, 'generic_identifier') == ['1']
    assert 's1462_welch_1st_degree' in values(result, 'name_token')
    assert values(result, 'local_number_token', 'degree-local-number') == [number]


def test_actual_amendment_and_agenda_numbers_keep_their_roles(engine):
    result = checked(engine, 'Amdt #1 - Cortez Masto 1st Degree Amdt to S.1760 - Agenda Item 20 (FLO23798).pdf')
    assert values(result, 'degree_token') == ['1st Degree']
    assert values(result, 'amendment_token') == ['1']
    assert values(result, 'item_token') == ['20']
    assert values(result, 'measure_number') == ['1760']
    assert not fields(result, 'local_number_token', 'degree-local-number')


@pytest.mark.parametrize('suffix', ['121119', '20250318', '20250318123145', 'd91faa5b-4bb2-466d-8675-13becf679c7b'])
def test_constructed_date_and_uuid_suffixes_take_precedence(engine, suffix):
    result = checked(engine, f'S1_Smith_1st_degree_{suffix}.pdf')
    assert values(result, 'degree_token') == ['1st_degree']
    assert not fields(result, 'local_number_token', 'degree-local-number')
    assert any(fields(result, k) for k in ('date_token', 'short_date_token', 'opaque_uuid'))


def test_compact_digits_after_amendment_keep_reference_and_alternative_date(engine):
    result = checked(engine, 's-704-murphy-1st-degree-amendment-121119-15')
    assert values(result, 'degree_token') == ['1st-degree']
    assert values(result, 'short_date_token') == ['121119']
    assert result['metadata'].get('date_token_candidates', []) == []
    assert values(result, 'amendment_token') == ['121119']
    # The filename does not prove an event date or official amendment number.
    assert any(s['raw'] == '121119' and s['rule'] == 'short-date-compact'
               for s in result['suppressed'])
    assert not fields(result, 'local_number_token', 'degree-local-number')


@pytest.mark.parametrize('name', ['11st_degree_2.pdf', '21st_degree_1.pdf', 'Xfirst_degree_2.pdf',
    '1st_degrees_2.pdf', 'firstdegree_2.pdf', 'degree_2.pdf', '2nd_degree20abc.pdf',
    'HHRG-119-IF00-Wstate-1st-degree-20250318.pdf'])
def test_constructed_boundaries_and_protected_slots(engine, name):
    result = checked(engine, name)
    assert not fields(result, 'local_number_token', 'degree-local-number')
    if name != '2nd_degree20abc.pdf':
        assert not fields(result, 'degree_token')


@pytest.mark.parametrize('name', ['S_Smith_1st_degree_1.pdf', 'AS___Draft.pdf', 'S__Res_120.pdf',
    'S_Res_120.pdf', 'HHRG-119-IF00-Wstate-S___-20250318.pdf'])
def test_constructed_separators_words_and_existing_references_are_not_placeholders(engine, name):
    assert not fields(checked(engine, name), 'number_placeholder', 'measure-placeholder')


@pytest.mark.parametrize('name', ['first-degree-murder.pdf', 'second_degree_burns.pdf',
    'First-degree to improve safety.pdf'])
def test_constructed_general_degree_wording_does_not_assert_amendment_role(engine, name):
    result = checked(engine, name)
    assert fields(result, 'degree_token')
    assert not fields(result, 'amendment_degree')
    assert not fields(result, 'target_subject', 'degree-target')


@pytest.mark.parametrize('name', ['to_Smith_1st_degree_1.pdf', '2nd_degree_discussion_to_Smith_1st_degree_1.pdf',
    '2nd_degree_1_to_Smith.pdf', '2nd_degree_1_to__1st_degree_2.pdf'])
def test_constructed_incomplete_target_context_is_not_a_target(engine, name):
    assert not fields(checked(engine, name), 'target_subject', 'degree-target')
