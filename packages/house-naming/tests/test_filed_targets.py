"""Literal filing wording and bounded targets inside compound local filenames."""
import subprocess
import sys

import pytest

from house_naming import Engine
from house_naming.corpus import residual_fields


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, token, *, subject='HR9'):
    name = f'BILLS-118-{subject}-C001097-Amdt-{token}.pdf'
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for match in result['observations']:
        for field in match['fields']:
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
            assert name[field['start']:field['end']] == field['raw']
    assert any(f['name'] == 'amendment_token' and f['raw'] == token
               for m in result['observations'] for f in m['fields'])
    return result


def fields(result, name):
    return [f for m in result['observations'] for f in m['fields'] if f['name'] == name]


def filing(result):
    return [{f['name']: f for f in m['fields']} for m in result['observations']
            if m['rule'] == 'compound-filing-target']


@pytest.mark.parametrize('token,local,filer,printed_name,target', [
    ('H1352-FC-AMD_01XMLfiledbyRepCrdenastoHR1352', 'H1352-FC-AMD_01', 'RepCrdenas', 'Crdenas', 'HR1352'),
    ('H2880-FC-AINS_01XMLfiledbyRepCartertoHR2880', 'H2880-FC-AINS_01', 'RepCarter', 'Carter', 'HR2880'),
    ('H4814_ANS_01XMLfiledbyRepSototoHR4814', 'H4814_ANS_01', 'RepSoto', 'Soto', 'HR4814'),
    ('5555-FC-AINS_01XMLfiledbyRepMiller-MeekstoHR5555', '5555-FC-AINS_01', 'RepMiller-Meeks', 'Miller-Meeks', 'HR5555'),
    ('ANS_02XMLfiledbyRepBluntRochestertoHR6571', 'ANS_02', 'RepBluntRochester', 'BluntRochester', 'HR6571'),
    ('TRAHAN_041XMLfiledbyRepsTrahanandObernoltetoHR6544', 'TRAHAN_041', 'RepsTrahanandObernolte', 'TrahanandObernolte', 'HR6544'),
    ('FC_MN_02XMLfiledbytheMinoritytoHR4167', 'FC_MN_02', 'theMinority', None, 'HR4167'),
    ('H6125_ANS_01_xmlfiledbytheMajoritytoHR6125', 'H6125_ANS_01', 'theMajority', None, 'HR6125'),
    ('H6192FCA_01XMLtoHR6192', 'H6192FCA_01', None, None, 'HR6192'),
])
def test_real_filing_variants_preserve_every_component(engine, token, local, filer, printed_name, target):
    result = checked(engine, token)
    match, = filing(result)
    assert match['local_identifier']['raw'] == local
    assert match['filename_format_token']['raw'].lower() == 'xml'
    assert match.get('filer_token', {}).get('raw') == filer
    assert match.get('name_token', {}).get('raw') == printed_name
    assert match['target_subject']['raw'] == target
    assert match['target_marker']['raw'] == 'to'
    assert not fields(result, 'amendment_identifier')
    if filer:
        assert match['filing_marker']['raw'] == 'filedby'
        assert 'no author identity' in match['filer_token']['note']
    if printed_name:
        assert match['member_marker']['raw'] == ('Reps' if filer.startswith('Reps') else 'Rep')
    assert {f['raw'] for f in fields(result, 'measure_number')} == {'9', target[2:]}


def test_format_suffix_is_not_a_revision_or_an_extension(engine):
    result = checked(engine, 'BILIFL_046_XML002filedbyRepBilirakistoHR2365')
    match, = filing(result)
    assert match['local_identifier']['raw'] == 'BILIFL_046'
    assert match['filename_format_token']['raw'] == 'XML'
    assert 'neither an extension nor a verified content format' in match['filename_format_token']['note']
    assert match['numeric_suffix_token']['raw'] == '002'
    assert [f['raw'] for f in fields(result, 'extension')] == ['pdf']
    assert not fields(result, 'revision_number')


def test_spelled_out_substitute_is_not_part_of_the_name(engine):
    token = 'ANS_HR9612_02XMLfiledbyRepFryanamendmentinthenatureofasubstitutetoHR9612'
    match, = filing(checked(engine, token))
    assert match['name_token']['raw'] == 'Fry'
    assert match['amendment_marker']['raw'] == 'anamendmentinthenatureofasubstitute'
    assert match['amendment_marker']['code'] is None


@pytest.mark.parametrize('token', [
    'DINGMI_096filedbyRepDingelltoHR____AmericanPrivacyRightsActdiscussiondraft',
    'BLOCKCHAIN_03XMLtoHR___DeployingAmericanBlockchainsAct',
])
def test_placeholder_target_does_not_get_primary_bill_number(engine, token):
    result = checked(engine, token)
    assert len(filing(result)) == 1
    assert [f['raw'] for f in fields(result, 'measure_number')] == ['9']
    assert fields(result, 'number_placeholder')
    assert any(f['raw'].startswith(('AmericanPrivacy', 'DeployingAmerican')) for f in fields(result, 'descriptor'))
    if token.startswith('DINGMI'):
        assert not fields(result, 'filename_format_token')


@pytest.mark.parametrize('measure', ['HR', 'S', 'HRes', 'SRes', 'HJRes', 'SJRes', 'HConRes', 'SConRes'])
def test_target_type_and_number_are_explicit_and_separate(engine, measure):
    result = checked(engine, f'LOCAL_01XMLto{measure}42', subject='HR___')
    match, = filing(result)
    target = match['target_subject']
    typed = [f for f in fields(result, 'measure_token') if f['start'] == target['start']]
    assert len(typed) == 1 and typed[0]['code'] == measure.lower()
    assert [f['raw'] for f in fields(result, 'measure_number')] == ['42']
    # Missing primary number stays missing in validated record metadata too.
    assert all(m['record'].get('measureNumber') != 42 for m in result['matches'])


def test_repeated_subject_and_amendment_occurrences_remain_distinct(engine):
    token = 'H1352-FC-AMD_02XMLfiledbyRepCrdenastoHR1352'
    result = checked(engine, token, subject=token)
    matches = filing(result)
    assert len(matches) == 2
    assert len({m['name_token']['start'] for m in matches}) == 2


@pytest.mark.parametrize('token', [
    'LOCAL_01XMLtoHR575921stCentAct', 'LOCAL_01XMLtoHR123Services',
    'LOCAL_01XMLto123', 'LOCAL_01XMLtoH123', 'LOCAL_01XMLtoHR',
    'LOCAL_01XMLfiledbyRepSoto', 'LOCAL_01XMLfiledbytoHR42',
    'LOCAL_01XMLfiledbyRepSototo', 'LOCAL_01toHR42',
    'LOCAL_01XMLResources', 'MyXMLtoHR42', 'XMLtoHR42',
])
def test_incomplete_or_unsupported_shapes_do_not_gain_a_filing(engine, token):
    assert not filing(checked(engine, token))


@pytest.mark.parametrize('filer', ['REPSOTO', 'repsoto', 'REPSTRAHANANDOBERNOLTE'])
def test_ambiguous_member_marker_case_preserves_whole_filer(engine, filer):
    match, = filing(checked(engine, f'LOCAL_01XMLfiledby{filer}toHR42'))
    assert match['filer_token']['raw'] == filer
    assert 'name_token' not in match and 'member_marker' not in match


def test_other_filenames_do_not_gain_legislative_filing_roles(engine):
    result = engine.extract('LOCAL_01XMLfiledbyRepSototoHR42.pdf')
    assert not filing(result)


def test_new_broad_fields_do_not_hide_unexplained_text(engine):
    result = checked(engine, '5555-FC-AINS_01XMLfiledbyRepMiller-MeekstoHR5555')
    rows = residual_fields(result, field_names={'amendment_token'})
    residual = [s['raw'] for r in rows for s in r['residual_spans']]
    assert '5555-FC' in residual and 'Miller-Meeks' in residual


def test_local_number_refinement_keeps_its_non_official_role(engine):
    result = checked(engine, 'ANS_02XMLfiledbyRepBluntRochestertoHR6571')
    component, = fields(result, 'local_number_token')
    assert component['raw'] == '02' and 'not an established' in component['note']
    assert not fields(result, 'amendment_identifier')


def test_failed_long_filing_shape_is_bounded():
    subprocess.run([sys.executable, '-c',
        'from house_naming import Engine; Engine().extract("BILLS-118-HR9-C001097-Amdt-" + "1" * 12000 + "XMLtoHR.pdf")'],
        check=True, timeout=8, capture_output=True)
