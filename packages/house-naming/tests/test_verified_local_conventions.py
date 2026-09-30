"""Reviewed source conventions, role distinctions and adverse controls.

Fixture hashes identify the research bodies; these offline tests exercise the
filename reader, not current URL availability or PDF contents.
"""
import json
from pathlib import Path

import pytest

from house_naming import Engine
from house_naming.catalog import check_catalog
from house_naming.cli import main
from house_naming.errors import NamingError
from house_naming.filenames import parse_filename


CASES = json.loads((Path(__file__).parent / 'fixtures/verified_local_conventions.json').read_text())['cases']
SUBSTITUTE = 'Amendment in the nature of a substitute'
TARGET = 'Substitute amendment target'


@pytest.fixture(scope='module')
def engine():
    return Engine()


def fields(result, name=None):
    return [f for m in result['observations'] for f in m['fields']
            if name is None or f['name'] == name]


def checked(engine, name, url=None):
    result = engine.extract(name, source_url=url)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in result['observations']:
        for f in m['fields']:
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
            assert name[f['start']:f['end']] == f['raw']
    if url is not None:
        assert result['source_url'] == url
    return result


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['filename'])
def test_reviewed_names_and_every_source_occurrence(engine, case):
    for name in case['variants']:
        for body in case['occurrences']:
            for url in body['urls']:
                result = checked(engine, name, url)
                readings = {f['label'] for f in fields(result)}
                if case['expected_label'] is not None:
                    assert case['expected_label'] in readings
                else:
                    assert 'Manager amendment' not in readings
                if case['expected_label'] == TARGET:
                    assert SUBSTITUTE not in readings


@pytest.mark.parametrize('url', [
    None, 'https://unrelated.house.gov/TT_Doar_3.15.18.pdf',
    'https://edworkforce.house.gov.example.com/TT_Doar_3.15.18.pdf',
    'https://www.congress.gov/999/meeting/house/123/witnesses/TT_Doar_3.15.18.pdf',
])
def test_tt_requires_qualified_source(engine, url):
    result = checked(engine, 'TT_Doar_3.15.18.pdf', url)
    assert not any(f['label'] == 'Truth in Testimony disclosure' for f in fields(result))
    assert any(f['raw'] == 'TT' for f in fields(result, 'local_code_token'))


def test_tt_subject_and_date_remain_literal(engine):
    result = checked(engine, 'TT_Doar_3.15.18.pdf', 'https://edworkforce.house.gov/UploadedFiles/TT_Doar_3.15.18.pdf')
    assert any(f['raw'] == 'Doar_3.15.18' for f in fields(result, 'subject_token'))
    assert [f['raw'] for f in fields(result, 'date_token')] == ['3.15.18']
    assert all(not f['candidates'] for f in fields(result, 'date_token'))  # No invented century.
    marker, = fields(result, 'document_token')
    assert marker['raw'] == 'TT' and marker['code'] is None
    assert not fields(result, 'committee_code')  # Publisher is not issuer.


def test_sfr_expansion_remains_inferred_and_requires_publisher(engine):
    name = 'sfr-gregory-heeb.fbi.pdf'
    url = 'https://www.jec.senate.gov/public/_cache/files/2f5ca5c1-44c9-4e23-944e-8008293856f7/' + name
    marker, = fields(checked(engine, name, url), 'document_token')
    assert marker['raw'] == 'sfr' and marker['code'] is None
    assert marker['label'] == 'Written witness statement'
    assert 'inferred expansion' in marker['note']
    assert 'Not answers to questions for the record' in marker['note']
    for other in (None, 'https://www.judiciary.senate.gov/' + name):
        assert not fields(checked(engine, name, other), 'document_token')


@pytest.mark.parametrize('token', ['MState', 'WState'])
def test_publisher_alias_does_not_override_official_document_slot(engine, token):
    name = f'HHRG-119-ED00-{token}-TT_SFR_MGR_ANS-20250318.pdf'
    result = checked(engine, name, 'https://edworkforce.house.gov/' + name)
    assert [f['raw'] for f in fields(result, 'document_token')] == [token]
    assert not any(m['scope'] == 'source-stem' for m in result['observations'])
    assert not any(f['label'] in {SUBSTITUTE, TARGET, 'Manager amendment', 'Truth in Testimony disclosure'}
                   for f in fields(result))


@pytest.mark.parametrize('name,number', [
    ('BILLS-117-AANS6671-T000472-Amdt-50.pdf', '6671'),
    ('BILLS-117-2724-B001295-Amdt-AANS2724-U1.pdf', '2724'),
    ('BILLS-119-HR2556-B001285-Amdt-2toANS.pdf', '2'),
    ('BILLS-119-HR2556-H001068-Amdt-5toANS.pdf', '5'),
])
def test_amendment_target_retains_local_number_and_unknown_measure(engine, name, number):
    result = checked(engine, name)
    marker, = fields(result, 'target_amendment_marker')
    assert marker['raw'] == 'ANS' and marker['label'] == TARGET
    assert number in {f['raw'] for f in fields(result, 'local_number_token')}
    assert not any(f['label'] == SUBSTITUTE for f in fields(result))
    if 'HR2556' not in name:
        assert not fields(result, 'measure_token') and not fields(result, 'measure_number')
    if '-U1' in name:
        assert [f['raw'] for f in fields(result, 'revision_number')] == ['1']


@pytest.mark.parametrize('token', ['AANS111111', '111111toANS', 'MGR_111111'])
def test_local_reference_digits_do_not_turn_into_dates(engine, token):
    result = checked(engine, f'BILLS-117-{token}-B001295-Amdt-50.pdf')
    assert [f['raw'] for f in fields(result, 'local_number_token')] == ['111111']
    assert not fields(result, 'date_token') and not fields(result, 'short_date_token')


def test_version_and_substitute_form_coexist(engine):
    result = checked(engine, 'BILLS-116ANS2326ih.pdf')
    assert fields(result, 'version_token')[0]['label'] == 'Introduced in House'
    assert fields(result, 'amendment_marker')[0]['label'] == SUBSTITUTE


def test_qualifier_and_measure_reference_supply_descriptive_context(engine):
    result = checked(engine, 'S. 1421 Baldwin_ANS as modified.pdf')
    assert any(f['label'] == SUBSTITUTE for f in fields(result))
    assert [f['raw'] for f in fields(result, 'qualifier_wording')] == ['as modified']


def test_explicit_descriptive_target_wins_over_standalone_ans(engine):
    result = checked(engine, 'S. 1421 Baldwin Amendment to ANS as modified.pdf')
    assert [f['label'] for f in fields(result, 'target_amendment_marker')] == [TARGET]
    assert not any(f['label'] == SUBSTITUTE for f in fields(result))


@pytest.mark.parametrize('name', ['ANS.pdf', 'AANS6671.pdf', 'MGR_01.pdf',
    'BILLS-119-Evans-A000001-Amdt-1.pdf', 'HHRG-119-ED00-WState-ANS-20250318.pdf',
    'BILLS-118-HR4045-M001159-Amdt-FC_MGR_02XMLfiledbytheMajoritytoHR4045.pdf',
    'cole-letter-of-support_-mgr-eliecer-camacho-jimenez'])
def test_unsupported_context_does_not_acquire_local_expansions(engine, name):
    result = checked(engine, name)
    assert not any(f['label'] in {SUBSTITUTE, TARGET, 'Manager amendment'} for f in fields(result))


def test_same_basename_is_not_an_identity_or_bill_lookup(engine):
    case = next(c for c in CASES if c['filename'] == 'mgr_01.pdf')
    assert len({o['sha256'] for o in case['occurrences']}) == 2
    for occurrence in case['occurrences']:
        for url in occurrence['urls']:
            result = checked(engine, 'MGR_01.pdf', url)
            assert not fields(result, 'measure_number') and not fields(result, 'congress')
            assert fields(result, 'amendment_marker')[0]['label'] == 'Manager amendment'
            assert 'do not identify an edition or bill' in fields(result, 'amendment_marker')[0]['note']


def test_missing_target_is_not_backfilled_from_reviewed_pdf(engine):
    case = next(c for c in CASES if c['filename'] == 'updated_ans_for_website.pdf')
    result = checked(engine, case['filename'], case['occurrences'][0]['urls'][0])
    assert fields(result, 'amendment_marker')[0]['label'] == SUBSTITUTE
    assert not fields(result, 'measure_number') and not fields(result, 'print_identifier')
    assert not fields(result, 'target_subject')


def test_typed_api_and_cli_preserve_source_context(engine, capsys):
    name = 'TT_Doar_3.15.18.pdf'
    url = 'https://edworkforce.house.gov/UploadedFiles/' + name
    expected = checked(engine, name, url)
    parsed = parse_filename(name, source_url=url).model_dump(mode='json')
    assert parsed['source_url'] == url and parsed['matches'] == expected['observations']
    assert main(['extract', name, '--source-url', url]) == 0
    assert json.loads(capsys.readouterr().out) == expected


@pytest.mark.parametrize('url', [42, '', '/relative/path', 'file:///tmp/TT_x.pdf',
    'https://edworkforce.house.gov@evil.example/TT_x.pdf',  # credentials, not this publisher
    'https://@edworkforce.house.gov/TT_x.pdf', 'https://[invalid/TT_x.pdf',
    'https://edworkforce.house.gov/\nTT_x.pdf', 'https://edworkforce.house.gov:123/TT_x.pdf',
    'https://edworkforce.house.gov/' + 'a' * 16384])
def test_invalid_source_context_fails_explicitly(engine, url):
    with pytest.raises(NamingError) as error:
        engine.extract('TT_x.pdf', source_url=url)
    assert error.value.code == 'invalid-source-url'


def test_catalog_rejects_unbound_meanings_and_unguarded_source_rules(engine):
    guide = engine.guide
    rule = next(r for r in guide['extraction_rules'] if r['id'] == 'publisher-tt-disclosure')
    rule['field_readings']['missing_capture'] = {'label':'Wrong', 'note':'No such capture'}
    with pytest.raises(NamingError, match='absent capture'):
        check_catalog(guide)
    del rule['field_readings']['missing_capture']
    del rule['source_hosts']
    del rule['source_urls']
    with pytest.raises(NamingError, match='source qualifiers'):
        check_catalog(guide)
