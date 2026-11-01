"""The ledger balances and refuses reasons nobody declared."""
import duckdb
import pytest

from measure.explorer_native_comparison import REASONS, account, issue_disposition


def rows(*keys):
    return ' UNION ALL '.join(f"SELECT {key if key is None else repr(key)} AS key,'c' AS context".replace('None', 'cast(NULL AS VARCHAR)') for key in keys)


@pytest.fixture
def db():
    with duckdb.connect() as connection:
        yield connection


def test_multiset_pairs_repeats_and_accounts_for_both_sides(db):
    result = account(db, 'f', rows('a', 'a', 'b'), rows('a', 'c'), old_reason="'old_state_only'", new_reason="'native_found_more'", multiset=True)
    assert (result['old_rows'], result['new_rows'], result['matched'], result['matched_new']) == (3, 2, 1, 1)
    assert result['old_only_by_reason'] == {'old_state_only': 2} and result['new_only_by_reason'] == {'native_found_more': 1}


def test_presence_matches_every_copy(db):
    result = account(db, 'f', rows('a', 'a'), rows('a'))
    assert result['matched'] == 2 and result['matched_new'] == 1 and not result['old_only_by_reason']


def test_a_null_key_never_matches_and_is_counted(db):
    result = account(db, 'f', rows(None, 'a'), rows('a'), old_reason="CASE WHEN x.key IS NULL THEN 'no_public_url' ELSE 'unexplained' END")
    assert result['old_only_by_reason'] == {'no_public_url': 1}


def test_unexplained_is_reported_not_hidden(db):
    result = account(db, 'f', rows('a'), rows('b'))
    assert result['old_only_by_reason'] == {'unexplained': 1} and result['samples']['old_only']['unexplained'] == [['a', 'c']]


def test_undeclared_reason_is_refused(db):
    with pytest.raises(ValueError, match='undeclared'):
        account(db, 'f', rows('a'), rows('b'), old_reason="'because'")


def test_every_retained_issue_title_has_a_declared_disposition():
    titles = ['The original video publication time is not established by this cache.', 'This recording has no verified meeting association.',
        'The retained decision aggregates its recording evidence.', 'Sources disagree about label', 'Legacy House state omits alternate file URLs and source ownership']
    assert all(issue_disposition(title) in REASONS and issue_disposition(title) != 'unexplained' for title in titles)
    assert issue_disposition('A title nobody has seen') == 'unexplained'
