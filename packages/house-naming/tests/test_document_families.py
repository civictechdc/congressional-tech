"""Broad navigation categories preserve specific kinds and literal relations."""
import pytest

from house_naming import Engine


@pytest.mark.parametrize('name,kind,family', [
    ('Lee Letter of Support for Smith.pdf', 'letter-of-support', 'letter'),
    ('Lee Opening Statement.pdf', 'opening-statement', 'statement'),
    ('HHRG-119-IF00-Wstate-Lee-20250318.pdf', 'witness-statement', 'statement'),
    ('S. 123 As Reported.pdf', 'legislative-text', 'legislation'),
    ('Witness List.pdf', 'witness-list', 'list'),
])
def test_family_is_additive_to_specific_kind(name, kind, family):
    result = Engine().extract(name)
    assert result['metadata']['document_kind'] == [kind]
    assert result['metadata'].get('document_family') == [family]
    assert ''.join(piece['raw'] for piece in result['pieces']) == name


def test_support_relationship_does_not_establish_letter_family():
    row = Engine().extract('5.15.23 - Assistant District Attorney Aramayo Support for de Alba.pdf')['metadata']
    assert not row.get('document_kind')
    assert not row.get('document_family')
    assert row['relation_wording'] == ['Support for']
    assert row['target_subject'] == ['de Alba']


def test_only_primary_kind_supplies_family():
    row = Engine().extract('BILLS-119-Bill_Summary-C001053-Amdt-1.pdf')['metadata']
    assert row['target_document_kind'] == ['summary']
    assert row.get('document_family') == ['amendment']


def test_shared_mapping_handles_multiple_kinds_and_unknowns():
    from house_naming import document_families
    assert document_families(['letter', 'letter-of-support', 'statement']) == ['letter', 'statement']
    assert document_families(['new-publisher-kind']) == ['new-publisher-kind']
    assert document_families(None) == []
    assert document_families([]) == []
