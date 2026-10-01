"""Source-backed name boundaries and corpus analysis regression controls."""
from copy import deepcopy
import json
import re
import subprocess
import sys

import pytest

from house_naming import Engine, NamingError
from house_naming.corpus import filename_tokens, shared_token_pattern, residual_fields


@pytest.fixture(scope='module')
def engine():
    return Engine()


def member_fields(result):
    return {f['name']: f for m in result['observations'] if m['rule'] == 'member-title' for f in m['fields']}


@pytest.mark.parametrize('filename,surname,title', [
    ('BILLS-119HR9269RepClyburnRenewingtheAfricanAmericanCivilRightsNetworkActih.pdf', 'Clyburn', 'RenewingtheAfricanAmericanCivilRightsNetworkAct'),
    ('BILLS-119HR5470RepLaHoodRoute66NationalHistoricTrailDesignationActih.pdf', 'LaHood', 'Route66NationalHistoricTrailDesignationAct'),
    ('BILLS-119S675RepHoevenTheodoreRooseveltPresidentialLibraryActats.pdf', 'Hoeven', 'TheodoreRooseveltPresidentialLibraryAct'),
    ('BILLS-118HR6062RepRadewagenih.pdf', 'Radewagen', None),
    ('BILLS-118HR4090-RepMoylanih.pdf', 'Moylan', None),
])
def test_member_title_uses_explicit_congress_reference(engine, filename, surname, title):
    congress = filename[6:9]
    result = engine.extract(filename, member_surnames={congress: [surname]})
    fields = member_fields(result)
    assert fields['member_marker']['raw'] == 'Rep'
    assert fields['member_surname_token']['raw'] == surname
    assert fields.get('title_token', {}).get('raw') == title
    assert 'no person identity or sponsorship' in fields['member_surname_token']['note']
    for match in result['observations']:
        for f in match['fields']:
            assert filename[f['start']:f['end']] == f['raw']
            assert match['start'] <= f['start'] <= f['end'] <= match['end']
    assert not member_fields(engine.extract(filename))
    assert not member_fields(engine.extract(filename, member_surnames={'100': [surname]}))


@pytest.mark.parametrize('reference,printed', [
    ('Van Drew', 'VanDrew'), ('Miller-Meeks', 'MillerMeeks'), ("O'Brien", 'OBrien'),
    ('Blunt Rochester', 'BluntRochester'), ('Newperson', 'Newperson'),
])
def test_new_and_multipart_surnames_need_no_code_changes(engine, reference, printed):
    name = f'BILLS-119HR42Rep{printed}SomeTitleih.pdf'
    result = engine.extract(name, member_surnames={'119': [reference]})
    fields = member_fields(result)
    assert fields['member_surname_token']['raw'] == printed
    assert fields['title_token']['raw'] == 'SomeTitle'


def test_reference_boundaries_do_not_guess_names(engine):
    reference = {'119': ['Miller', 'Miller-Meeks', 'Smith']}
    before = deepcopy(reference)
    longest = engine.extract('BILLS-119HR42RepMillerMeeksSomeTitleih.pdf', member_surnames=reference)
    assert member_fields(longest)['member_surname_token']['raw'] == 'MillerMeeks'
    assert not member_fields(engine.extract('BILLS-119HR42RepSmithsonianSomeTitleih.pdf', member_surnames=reference))
    assert not member_fields(engine.extract('RepSmithSomeTitle.pdf', member_surnames=reference))
    assert reference == before


@pytest.mark.parametrize('reference', [['Clyburn'], {'119': 'Clyburn'}, {'119': [None]}, {'119': ['']}])
def test_invalid_member_reference(engine, reference):
    with pytest.raises(NamingError, match='surname'):
        engine.extract('BILLS-119HR2RepClyburnSomeTitleih.pdf', member_surnames=reference)


def test_cli_can_read_explicit_reference_from_stdin():
    result = subprocess.run([sys.executable, '-m', 'house_naming', 'extract',
        'BILLS-119HR2RepClyburnSomeTitleih.pdf', '--member-surnames', '-'],
        input='{"119":["Clyburn"]}', capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert member_fields(json.loads(result.stdout))['member_surname_token']['raw'] == 'Clyburn'


def test_tokens_preserve_whole_words_case_parts_and_unicode(engine):
    source = engine.extract('RepClyburnRenewingtheAfricanAmericanCivilRightsNetworkAct-Élodie-123.docx.pdf&download=1')
    tokens = filename_tokens(source)
    words = [t['raw'] for t in tokens if t['kind'] == 'wordpart']
    assert words == ['Rep', 'Clyburn', 'Renewingthe', 'African', 'American', 'Civil', 'Rights', 'Network', 'Act', 'Élodie']
    assert [t['raw'] for t in tokens if t['kind'] == 'number'] == ['123']
    assert all(source['input'][t['start']:t['end']] == t['raw'] for t in tokens)
    assert 'Renewingthe' in words and 'Renewing' not in words


@pytest.mark.parametrize('variants,kind,text,expected', [
    (('Rep',), 'wordpart', 'RepClyburn Representative Rep', ['Rep', 'Rep']),
    (('Act',), 'wordpart', 'SomeAct Act Actuary', ['Act', 'Act']),
    (('Statement', 'statement'), 'word', 'Statement statement Statements', ['Statement', 'statement']),
    (('12',), 'number', '12 123 012 A12', ['12', '12']),
    (('Élodie',), 'word', 'Élodie xÉlodie', ['Élodie']),
])
def test_shared_patterns_respect_exact_token_boundaries(variants, kind, text, expected):
    pattern = re.compile(shared_token_pattern(variants, kind))
    assert [m['token'] for m in pattern.finditer(text)] == expected


@pytest.mark.parametrize('variants,kind', [((), 'word'), (('x-y',), 'word'), (('1',), 'word'), (('x',), 'number'), (('x',), 'other'), ('x', 'word')])
def test_invalid_shared_pattern_inputs(variants, kind):
    with pytest.raises(NamingError):
        shared_token_pattern(variants, kind)


def test_residuals_subtract_specific_middle_spans_without_hiding_prose(engine):
    result = engine.extract('BILLS-119HR42Left-HR3-Rightih.pdf')
    before = deepcopy(result)
    rows = residual_fields(result)
    descriptor = next(r for r in rows if r['field']['name'] == 'descriptor')
    assert [s['raw'] for s in descriptor['residual_spans']] == ['Left', 'Right']
    assert result == before
    for row in rows:
        text = result['input']
        start, end = row['field']['start'], row['field']['end']
        all_positions = {i for i in range(start, end) if text[i].isalnum()}
        covered = {i for x in row['covered_by'] for i in range(max(start,x['field']['start']),min(end,x['field']['end'])) if text[i].isalnum()}
        unexplained = {i for s in row['residual_spans'] for i in range(s['start'],s['end']) if text[i].isalnum()}
        assert all_positions == covered | unexplained
        assert not covered & unexplained


def test_assumed_name_does_not_make_all_text_explained(engine):
    result = engine.extract('UnfamiliarText-2024-02-29.pdf')
    rows = residual_fields(result, include_unstructured=True)
    assert [s['raw'] for r in rows for s in r['residual_spans']] == ['UnfamiliarText']
    # A candidate bill version at a word ending is still residual text.
    rows = residual_fields(engine.extract('BILLS-119ANSServices.pdf'))
    assert any(s['raw'] == 'Services' for r in rows for s in r['residual_spans'])


def test_simple_amendment_identifiers_stay_explained_when_auditing_complex_ones(engine):
    result = engine.extract('Cassidy S. 1664 Amendment #1.pdf')
    # The subject now has an explicit slot, but its identity remains unexplained.
    rows = residual_fields(result, field_names={'amendment_token', 'subject_token'}, include_unstructured=True)
    assert [s['raw'] for r in rows for s in r['residual_spans']] == ['Cassidy']
