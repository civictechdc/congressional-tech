"""Preserve the complete category mappings captured before the ct-87uq refactor."""
import json
from collections import Counter
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from typing import get_args

import pytest

from committee_meeting.materials import DocumentDetails
from congress_api.adapters import documents, house, meetings, senate
from congress_api.parsers import document_types, house_documents
from congress_api.retention.document_index import fill_document_kind
from house_naming import document_families
from house_naming.categories import _FAMILY_MEMBERS

# Captured from unmodified b191fc8 before extracting adapters/documents.py.
BASELINE = json.loads((Path(__file__).parent / 'fixtures/document_category_mapping_baseline.json').read_text())
CONFLICTING_TITLE = 'Truth in Testimony transcript witness list statement biography disclosure amendment vote bill'


def test_complete_mapping_sets_match_pre_refactor_baseline():
    assert document_types.DOCUMENT_TYPE_MEANINGS == BASELINE['publisher_meanings']
    assert house_documents.COLLECTOR_KINDS == BASELINE['collector_kinds']
    assert house_documents.XML_KINDS == BASELINE['collector_xml_kinds']
    assert documents.DOCUMENT_CATEGORIES == BASELINE['explorer_categories']
    assert house.DOCUMENT_CATEGORIES == BASELINE['house_xml_categories']
    assert {family: list(kinds) for family, kinds in _FAMILY_MEMBERS.items()} == BASELINE['filename_family_members']
    assert list(get_args(DocumentDetails.model_fields['category'].annotation)) == BASELINE['model_categories']


def test_source_meanings_have_explicit_output_coverage():
    meanings = set(document_types.DOCUMENT_TYPE_MEANINGS.values())
    # These omissions preserve existing consumer behavior; they are not aliases.
    assert meanings - documents.DOCUMENT_CATEGORIES.keys() == {'questionnaire'}
    assert meanings - house_documents.COLLECTOR_KINDS.keys() == {'questionnaire', 'summary'}
    assert documents.DOCUMENT_CATEGORIES.keys() <= meanings
    assert house_documents.COLLECTOR_KINDS.keys() <= meanings
    allowed = set(get_args(DocumentDetails.model_fields['category'].annotation))
    assert set(documents.DOCUMENT_CATEGORIES.values()) <= allowed
    assert set(house.DOCUMENT_CATEGORIES.values()) <= allowed
    assert 'SD' not in house.DOCUMENT_CATEGORIES
    assert house_documents.XML_KINDS['SD'] == 'support document'


def test_consumers_share_adapter_policy_and_preserve_existing_imports():
    assert meetings.category is house.category is senate.category is documents.category
    assert meetings.DOCUMENT_CATEGORIES is documents.DOCUMENT_CATEGORIES
    assert house.DOCUMENT_CATEGORIES is documents.HOUSE_DOCUMENT_CATEGORIES


@pytest.mark.parametrize('alias', BASELINE['publisher_meanings'])
def test_every_literal_alias_and_title_conflict_keeps_existing_output(alias):
    meaning = BASELINE['publisher_meanings'][alias]
    assert document_types.document_type(alias) == meaning
    assert document_types.document_type('  ' + alias.upper().replace(' ', '   ') + '  ') == meaning
    expected, conflicting = BASELINE['alias_category_outputs'][alias]
    for field in ('documentType', 'kind'):
        row = {field: alias}
        assert documents.category(row) == expected
        row['name'] = CONFLICTING_TITLE
        original = deepcopy(row)
        assert documents.category(row) == conflicting
        assert row == original


# Original ordered title fallbacks, including two needles with the same output.
TITLE_NEEDLES = [
    ('truth in testimony', 'disclosure'), ('transcript', 'transcript'),
    ('witness list', 'witness_list'), ('statement', 'statement'),
    ('testimony', 'statement'), ('biograph', 'biography'),
    ('disclosure', 'disclosure'), ('amendment', 'amendment'),
    ('vote', 'vote'), ('bill', 'bill_text'),
]


@pytest.mark.parametrize('first,second', list(combinations(TITLE_NEEDLES, 2)))
def test_title_fallback_priority_is_independent_of_word_order(first, second):
    for title in (f'{first[0]} {second[0]}', f'{second[0]} {first[0]}'):
        assert documents.category({'name': title}) == first[1]


@pytest.mark.parametrize('row,expected', [
    ({}, 'unknown'), ({'documentType': None}, 'unknown'),
    ({'documentType': 'new-publisher-kind'}, 'unknown'),
    ({'documentType': 'WS'}, 'unknown'),  # Codes are handled by the House adapter.
    ({'documentType': 'Questionnaire'}, 'unknown'),
    ({'documentType': 'Support Document'}, 'supporting'),
    ({'documentType': 'SD', 'name': 'Transcript'}, 'transcript'),
    ({'documentType': 'Summary', 'name': 'Transcript'}, 'supporting'),
    ({'documentType': '', 'kind': 'Committee Report', 'name': 'Transcript'}, 'report'),
    ({'documentType': 'unknown', 'kind': 'Committee Report', 'name': 'Transcript'}, 'transcript'),
    ({'documentType': 'Hearing:  Table of Contents', 'name': 'Transcript'}, 'transcript'),
    ({'documentType': 'Hearing: Table of Contents', 'name': 'Transcript'}, 'hearing_record'),
])
def test_unknowns_codes_and_exact_label_priority(row, expected):
    assert documents.category(row) == expected


def test_filename_membership_is_unique_and_every_mapping_reaches_public_output():
    members = [kind for kinds in BASELINE['filename_family_members'].values() for kind in kinds]
    assert all(count == 1 for count in Counter(members).values())
    for family, kinds in BASELINE['filename_family_members'].items():
        for kind in kinds:
            assert document_families([kind]) == [family]
        assert document_families(kinds + list(reversed(kinds)) + [family]) == [family]
    assert document_families(members) == sorted(BASELINE['filename_family_members'])


def test_filename_family_unknowns_order_and_dedup_remain_unchanged():
    kinds = ['committee-vote', 'statement', 'witness-statement', 'new-publisher-kind',
             'table-of-contents', 'committee-vote', 'bill-comparison']
    expected = ['bill-comparison', 'new-publisher-kind', 'statement', 'table-of-contents', 'vote-record']
    assert document_families(kinds) == expected
    assert document_families(iter(reversed(kinds))) == expected
    assert document_families(None) == document_families([]) == []
    assert kinds[0] == kinds[-2] == 'committee-vote'


@pytest.mark.parametrize('alias', BASELINE['publisher_meanings'])
def test_retained_index_preserves_every_publisher_kind_and_source_value(alias):
    row = {'source_document_type': [alias]}
    fill_document_kind(row)
    meaning = BASELINE['publisher_meanings'][alias]
    assert row['document_kind'] == [meaning]
    assert row['document_kind_source'] == ['source_document_type']
    assert row['source_document_type'] == [alias]
    assert row['document_family'] == document_families([meaning])
