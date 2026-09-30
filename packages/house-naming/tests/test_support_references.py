"""Printed support/opposition structures do not establish identities or stances."""
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


def values(result, name, rule=None):
    return [f['raw'] for m in result['observations'] if rule is None or m['rule'] == rule
            for f in m['fields'] if f['name'] == name]


def references(result):
    return [m for m in result['observations'] if m['rule'] == 'support-reference']


@pytest.mark.parametrize('name,left,wording,right', [
    ('-law-enforcement-officer-mitchell-support-for-pennell', 'law-enforcement-officer-mitchell', 'support-for', 'pennell'),
    ('1.10.23 - Deandre Weathersby Support for Kirsch_77e718a0-5fcb-42f2-afbd-d3a419ceecbe.pdf', 'Deandre Weathersby', 'Support for', 'Kirsch'),
    ('11323_-roberto-espinoza-support-for-kirschpdf', 'roberto-espinoza', 'support-for', 'kirsch'),
    ('conservative-political-action-coalition-letter-of-support-for-patel', 'conservative-political-action-coalition', 'letter-of-support-for', 'patel'),
    ('former_state_attorneys_general_letter_of_support_for_bondi1.pdf', 'former_state_attorneys_general', 'letter_of_support_for', 'bondi1'),
    ('labor-unions-joint-statement-of-support-for-berner', 'labor-unions', 'joint-statement-of-support-for', 'berner'),
    ('majac-and-supporting-orgs-follow-up-support-for-mangi', 'majac-and-supporting-orgs-follow-up', 'support-for', 'mangi'),
    ('Letter of Support for Smith.pdf', None, 'Letter of Support for', 'Smith'),
    ('Smith Letter in Support of H.R. 42.pdf', 'Smith', 'Letter in Support of', 'H.R. 42'),
    ('Group Letters of Support for Jones.pdf', 'Group', 'Letters of Support for', 'Jones'),
    ('Group opposition to HR42.pdf', 'Group', 'opposition to', 'HR42'),
    ('Group letter opposing HR42.pdf', 'Group', 'letter opposing', 'HR42'),
    ('Group in support of HR42.pdf', 'Group', 'in support of', 'HR42'),
    ('1.23.23 - Opposing Counsel Support for Farbiarz_d053343c-9c1b-4dc7-aa69-97ada3127096.pdf', 'Opposing Counsel', 'Support for', 'Farbiarz'),
    ('former_opposing_federal_prosecutors_support_for_hwang.pdf', 'former_opposing_federal_prosecutors', 'support_for', 'hwang'),
    ('03 28 23 -- U.S. Support of Democracy And Human Rights.pdf', 'U.S.', 'Support of', 'Democracy And Human Rights'),
    ('Company Inc. support for Smith Jr..pdf', 'Company Inc.', 'support for', 'Smith Jr.'),
    ('Group support for .NET Foundation.pdf', 'Group', 'support for', '.NET Foundation'),
])
def test_source_sides_and_complete_wording(engine, name, left, wording, right):
    result = checked(engine, name)
    match, = references(result)
    found = {f['name']: f['raw'] for f in match['fields']}
    assert found == {'relation_wording': wording, 'target_subject': right,
                     **({'subject_token': left} if left else {})}
    for f in match['fields']:
        assert f['code'] is None and f['context'] is None
        assert 'not established' in f['note']


def test_real_opaque_prefix_and_date_do_not_enter_bill_target_or_subject(engine):
    name = '41A30D95566198DB05F8C2C6F889CD1D61C5D1C3B348F7B6328903EE525EDD14.03.24.2020-dynatemp-support-for-s.-2754.pdf'
    result = checked(engine, name)
    assert values(result, 'subject_token', 'support-reference') == ['dynatemp']
    assert values(result, 'target_subject', 'support-reference') == ['s.-2754']
    assert values(result, 'measure_number') == ['2754']
    assert values(result, 'date_token') == ['03.24.2020']
    assert values(result, 'opaque_identifier') == [name[:64]]


def test_real_hearing_title_is_not_assigned_a_letter_or_person_role(engine):
    result = checked(engine, 'strengthening-support-for-grandfamilies-during-the-covid-19-pandemic-and-beyond')
    assert values(result, 'subject_token', 'support-reference') == ['strengthening']
    assert values(result, 'target_subject', 'support-reference') == ['grandfamilies-during-the-covid-19-pandemic-and-beyond']
    assert not values(result, 'document_token')
    assert not values(result, 'person_id')
    assert not values(result, 'author')


@pytest.mark.parametrize('name,left,right', [
    ('12345_Group_support_for_Smith_7.pdf', 'Group', 'Smith'),
    ('Group_support_for_Smith_20250318.pdf', 'Group', 'Smith'),
    ('20250318_Group_support_for_Smith_20250319.pdf', 'Group', 'Smith'),
    ('Group_support_for_Smith_d91faa5b-4bb2-466d-8675-13becf679c7b.pdf', 'Group', 'Smith'),
    ('Group support for S. 20250318.pdf', 'Group', 'S. 20250318'),
    ('Group 20250318 Committee support for Smith.pdf', 'Group 20250318 Committee', 'Smith'),
    ('Group support for Smith 20250318 Committee.pdf', 'Group', 'Smith 20250318 Committee'),
])
def test_only_assigned_boundary_metadata_is_trimmed(engine, name, left, right):
    result = checked(engine, name)
    assert values(result, 'subject_token', 'support-reference') == [left]
    assert values(result, 'target_subject', 'support-reference') == [right]


@pytest.mark.parametrize('name', [
    'Support for.pdf', 'Group support for.pdf', 'support-for_7.pdf',
])
def test_absent_target_is_not_invented(engine, name):
    result = checked(engine, name)
    assert references(result)
    assert not values(result, 'target_subject', 'support-reference')


@pytest.mark.parametrize('name', [
    'unsupported-format.pdf', 'support-format.pdf', 'support_forensic_tests.pdf',
    'opposition-together.pdf', 'Letter of Support.pdf',
    'Opposing Counsel.pdf',
    'HHRG-119-IF00-Wstate-Support-for-Smith-20250318.pdf',
])
def test_word_boundaries_and_assigned_witness_slots_are_protected(engine, name):
    assert not references(checked(engine, name))


def test_constructed_multiple_phrases_keep_local_source_context(engine):
    result = checked(engine, 'Group support for Smith opposition to Jones.pdf')
    assert values(result, 'relation_wording', 'support-reference') == ['support for', 'opposition to']
    assert values(result, 'subject_token', 'support-reference') == ['Group', 'Smith']
    assert values(result, 'target_subject', 'support-reference') == ['Smith', 'Jones']


def test_known_labels_and_parent_name_text_remain_available(engine):
    name = 'Group Letter of Support for Smith.pdf'
    result = checked(engine, name)
    assert 'Letter of Support' in values(result, 'label')
    assert 'Group Letter of Support for Smith' in values(result, 'name_token')
    assert values(result, 'subject_token', 'support-reference') == ['Group']


def test_constructed_target_digits_are_not_split_without_an_existing_role(engine):
    result = checked(engine, 'Group support for Person1032922.pdf')
    assert values(result, 'target_subject', 'support-reference') == ['Person1032922']
    assert not values(result, 'local_number_token')
