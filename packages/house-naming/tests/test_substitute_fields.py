"""Substitute targets and literal local components, with misleading-word controls."""
import pytest

from house_naming import Engine
from house_naming.corpus import residual_fields


@pytest.fixture(scope='module')
def engine():
    return Engine()


def fields(result, name, rule=None):
    return [f for m in result['observations'] if rule is None or m['rule'] == rule
            for f in m['fields'] if f['name'] == name]


def checked(engine, filename):
    result = engine.extract(filename)
    assert all(result[k] == value for k, value in engine.parse(filename).items())
    assert ''.join(p['raw'] for p in result['pieces']) == filename
    for m in result['observations']:
        for f in m['fields']:
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
            assert filename[f['start']:f['end']] == f['raw']
    return result


@pytest.mark.parametrize('subject,expected', [
    ('ANStoCommitteePrint', {'amendment_marker':'ANS','target_marker':'to','label':'CommitteePrint'}),
    ('anstoCommitteePrint119-A', {'amendment_marker':'ans','target_marker':'to','label':'CommitteePrint','print_identifier':'119-A'}),
    ('ANStoHR6498', {'amendment_marker':'ANS','target_marker':'to','measure_token':'HR','measure_number':'6498'}),
    ('ANStoHRes922', {'amendment_marker':'ANS','target_marker':'to','measure_token':'HRes','measure_number':'922'}),
    ('ANStoHConRes110', {'measure_token':'HConRes','measure_number':'110'}),
    ('ANSforHR295', {'target_marker':'for','measure_token':'HR','measure_number':'295'}),
    ('ANS1toHR2804', {'local_number_token':'1','measure_number':'2804'}),
    ('AmendmentintheNatureofaSubstitutetoHR2741', {'amendment_marker':'AmendmentintheNatureofaSubstitute','measure_number':'2741'}),
    ('AnAmendmentintheNatureofaSubstitutetoHR2741', {'amendment_marker':'AnAmendmentintheNatureofaSubstitute','measure_number':'2741'}),
    ('AmendmentintheNatureofaSubstitutetoHR2187theTruckParkingSafetyImprovementAct', {'measure_number':'2187','descriptor':'theTruckParkingSafetyImprovementAct'}),
    ('ANStoContemptReport', {'target_subject':'ContemptReport'}),
    ('AmendmentinthenatureofasubstitutetoSubtitle__BudgetReconciliationLegislativeRecommenda', {'target_subject':'Subtitle__BudgetReconciliationLegislativeRecommenda'}),
])
def test_explicit_targets_retain_the_whole_subject_and_literal_parts(engine, subject, expected):
    name = f'BILLS-119-{subject}-B000668-Amdt-18.pdf'
    result = checked(engine, name)
    match = next(m for m in result['observations'] if m['rule']=='substitute-target')
    actual = {f['name']:f['raw'] for f in match['fields']}
    assert all(actual.get(k) == v for k,v in expected.items())
    assert fields(result, 'subject_token')[0]['raw'] == subject
    assert [f['raw'] for f in fields(result, 'congress')] == ['119']
    if 'measure_number' not in expected:
        assert not fields(result, 'measure_number', 'substitute-target')
    marker = fields(result, 'amendment_marker', 'substitute-target')[0]
    assert marker['code'] is None  # No new official vocabulary definition.


@pytest.mark.parametrize('token,number', [
    ('ANS_01','01'), ('ains-02','02'), ('ANS02','02'), ('033_ANS','033'),
    ('01ANS','01'), ('1toANS','1'), ('069toANS','069'), ('1SubstituteANS','1'),
    ('6RevisedtoANS','6'), ('ANS_077Revised','077'), ('075ANS-U1','075'),
])
def test_local_numeric_component_does_not_replace_or_renumber_the_identifier(engine, token, number):
    result = checked(engine, f'BILLS-119-HR123-W000821-Amdt-{token}.pdf')
    assert fields(result, 'amendment_token', 'sponsored-amendment')[0]['raw'] == token
    parts = fields(result, 'local_number_token')
    assert parts and {f['raw'] for f in parts} == {number}
    assert all('not an established bill or amendment' in f['note'] for f in parts)
    assert {f['raw'] for f in fields(result, 'measure_number')} == {'123'}
    assert not any(f['raw'] == number for f in fields(result, 'amendment_identifier'))


@pytest.mark.parametrize('subject,number', [('ANS1596','1596'), ('3774ANS','3774'), ('AINS_01','01')])
def test_number_in_an_untyped_subject_stays_untyped(engine, subject, number):
    result = checked(engine, f'BILLS-117-{subject}-B001295-Amdt-12.pdf')
    assert fields(result, 'local_number_token')[0]['raw'] == number
    assert not fields(result, 'measure_number')


@pytest.mark.parametrize('token,marker', [
    ('ANS','ANS'), ('AnAmendmentintheNatureofaSubstitute','AnAmendmentintheNatureofaSubstitute'),
    ('SC-AINS_01','AINS'), ('TELE-SUD-CVGE-CMT-AINS_01','AINS'),
])
def test_bounded_words_inside_local_identifiers_remain_literal(engine, token, marker):
    result = checked(engine, f'BILLS-119-HR123-W000821-Amdt-{token}.pdf')
    assert fields(result, 'amendment_marker', 'substitute-marker')[0]['raw'] == marker
    assert fields(result, 'amendment_token', 'sponsored-amendment')[0]['raw'] == token


@pytest.mark.parametrize('subject', [
    'TransHUD', 'WASSERMANSCHULTZ', 'Transportation', 'Evans', 'HANS', 'TRANS',
    'ANStone', 'GrijalvaANS', 'AANS2521', 'SANS1957', 'SAANS6671',
    'ANStoHR575921stCentAct', 'ANStoHR123Services', 'ANSto123',
])
def test_substrings_and_unsupported_target_boundaries_do_not_get_new_interpretations(engine, subject):
    result = checked(engine, f'BILLS-119-{subject}-B000668-Amdt-18.pdf')
    assert not any(m['rule'] in {'substitute-target','substitute-marker',
        'local-substitute-number','local-number-substitute'} for m in result['observations'])


def test_existing_compound_identifier_is_not_truncated_to_a_number(engine):
    token = '5555-FC-AINS_01XMLfiledbyRepMiller-MeekstoHR5555'
    result = checked(engine, f'BILLS-118-HR5555-M001215-Amdt-{token}.pdf')
    assert fields(result, 'amendment_token', 'sponsored-amendment')[0]['raw'] == token
    assert {f['raw'] for f in fields(result, 'local_number_token')} == {'01'}
    assert not fields(result, 'amendment_identifier')


@pytest.mark.parametrize('name', ['ANStoCommitteePrint.pdf','033_ANS.pdf','Evans.pdf'])
def test_rules_do_not_escape_assigned_legislative_fields(engine, name):
    result = checked(engine, name)
    assert not any(m['rule'] in {'substitute-target','substitute-marker',
        'local-substitute-number','local-number-substitute'} for m in result['observations'])


def test_broad_target_description_does_not_conceal_remaining_text(engine):
    target = 'Subtitle__BudgetReconciliationLegislativeRecommenda'
    filename = f'BILLS-115-AmendmentintheNatureofaSubstituteto{target}-B000755-Amdt-10.pdf'
    result = checked(engine, filename)
    rows = residual_fields(result, field_names={'subject_token'})
    assert target in [s['raw'] for row in rows for s in row['residual_spans']]
