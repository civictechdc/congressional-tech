"""Independent controls for the exhaustive shared-token boundary audit."""
from copy import deepcopy
import re

import pytest

from audit_filename_token_boundaries import TokenIndex, independent_tokens


def rule(kind, *variants):
    boundaries = {
        'word': (r'(?<![^\W\d_])', r'(?![^\W\d_])'),
        'number': (r'(?<![0-9])', r'(?![0-9])'),
        'wordpart': (
            r'(?:(?<![^\W\d_])|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z]))',
            r'(?:(?![^\W\d_])|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z]))',
        ),
    }
    prefix, suffix = boundaries[kind]
    body = '|'.join(re.escape(v) for v in sorted(set(variants), key=lambda v: (-len(v), v)))
    token = variants[0].casefold()
    return {'id': f'{kind}:{token}', 'kind': kind, 'token': token,
            'variants': list(variants), 'flags': [],
            'pattern': prefix + '(?P<token>' + body + ')' + suffix}


ROWS = [
    rule('word', 'Act', 'ACT', 'act'), rule('wordpart', 'Act', 'ACT', 'act'),
    rule('word', 'QFR'), rule('wordpart', 'QFR'),
    rule('word', 'SS', 'ß'), rule('wordpart', 'SS', 'ß'),
    rule('word', 'café'), rule('wordpart', 'café'),
    rule('word', 'a', 'A'), rule('wordpart', 'a', 'A'),
    rule('number', '1'), rule('number', '11'), rule('number', '111'),
    rule('number', '2024'), rule('word', 'download'), rule('word', 'pdf'),
]


@pytest.fixture(scope='module')
def index():
    return TokenIndex(ROWS)


@pytest.mark.parametrize('stem', [
    '', '---', 'Act', 'ACT', 'act', 'aCt', 'Actuary', 'SomeAct',
    'SomeActuary', 'ActActAct', 'ACTTitle', 'XACT', 'QFRResponse',
    'QFRResponsesQFR', 'QFResponses', 'XQFR', 'A_ACT_Act_act',
    '1_11_111_1111_0111_1110', 'a1Act11QFR111', '20242024-2024-02024',
    'café—café-caféteria', 'xcafé', 'caféAct', 'Acté', 'éAct',
    'ß-SS-SSS-xß', 'ßAct', '١1٢11³Act', 'Act\u0301Act',
    'pdf.download=1', 'Act\nAct\tACT', '🔎Act_\x00QFR',
])
def test_index_matches_direct_scanning_and_independent_lexer(index, stem):
    actual, candidates, literals = index.indexed(stem)
    assert actual == index.direct(stem) == index.expected(stem)
    assert len(actual) <= candidates <= literals


def test_character_lexer_has_explicit_expected_spans():
    assert list(independent_tokens('QFRAct_12-é³')) == [
        ('word', 0, 6, 'QFRAct'),
        ('wordpart', 0, 3, 'QFR'), ('wordpart', 3, 6, 'Act'),
        ('number', 7, 9, '12'),
        ('word', 10, 12, 'é³'), ('wordpart', 10, 12, 'é³'),
    ]


def test_frozen_stem_excludes_extension_and_query(index):
    filename = 'Act-2024.pdf?download=1'
    stem = filename[:8]
    actual, _, _ = index.indexed(stem)
    assert actual == index.expected(stem)
    assert {match[0] for match in actual} == {'word:act', 'wordpart:act', 'number:2024'}
    assert index.indexed(filename)[0] != actual


@pytest.mark.parametrize('change', [
    {'flags': ['IGNORECASE']},
    {'id': 'word:wrong'},
    {'variants': []},
    {'variants': ['Act', 'other']},
    {'pattern': '(?P<token>Act)'},
    {'pattern': r'(?<![^\W\d_])(?P<token>Act.*)(?![^\W\d_])'},
])
def test_index_rejects_rules_that_do_not_prove_literal_pruning(change):
    row = deepcopy(ROWS[0])
    row.update(change)
    with pytest.raises(AssertionError):
        TokenIndex([row])


def test_index_rejects_duplicate_rule_ids():
    with pytest.raises(AssertionError):
        TokenIndex([ROWS[0], ROWS[0]])


def test_independent_oracle_detects_weakened_word_boundary():
    index = TokenIndex([rule('word', 'Act')])
    index.patterns['word:act'] = re.compile('(?P<token>Act)')
    stem = 'SomeActuary'
    actual, _, _ = index.indexed(stem)
    assert actual == index.direct(stem) == {('word:act', 4, 7, 'Act')}
    assert index.expected(stem) == set()


def test_independent_oracle_detects_invalid_camel_part_variant():
    index = TokenIndex([rule('wordpart', 'FooBar')])
    actual, _, _ = index.indexed('FooBar')
    assert actual == index.direct('FooBar') == {('wordpart:foobar', 0, 6, 'FooBar')}
    assert index.expected('FooBar') == set()
