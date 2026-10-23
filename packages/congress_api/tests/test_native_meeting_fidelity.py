"""Retained Congress.gov records keep family-specific references and source types."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from congress_api.adapters import meetings
from test_explorer_material_adapters import context, catalog


FIXTURE = Path(__file__).parent / 'fixtures/congress_meetings/native-relations-documents.json'
ROWS = json.loads(FIXTURE.read_text())


def imported(row):
    result = list(meetings.records([row], context('congress.gov')))
    catalog(result)
    assert next(r for r in result if r.kind == 'source_record').payload == row
    return result


def test_real_nomination_parts_and_treaties_survive_without_bill_type():
    for row in ROWS[:2]:
        result = imported(row)
        subjects = [r for r in result if r.kind == 'meeting_subject']
        expected = sum(len(items) for items in row['relatedItems'].values())
        assert len(subjects) == expected
        assert len({r.item.id for r in subjects}) == expected
        items = {r.id: r for r in result if r.kind == 'legislative_item'}
        for subject in subjects:
            selector = subject.provenance.citations[0].selector.split('/')
            family, index = selector[-2], int(selector[-1])
            native = row['relatedItems'][family][index]
            item = items[subject.item.id]
            assert item.congress == native['congress']
            expected_kind = {'nominations': 'nomination', 'treaties': 'treaty', 'bills': 'bill'}[family]
            if family == 'bills' and native['type'].endswith('RES'):
                expected_kind = 'resolution'
            assert item.item_type == expected_kind
            if family == 'nominations':
                assert item.identifiers[0].value == f"PN/{native['number']}/{native['part']}"
            assert item.provenance.citations[0].selector == subject.provenance.citations[0].selector


def test_nomination_whole_and_parts_remain_distinct_even_with_same_api_url():
    row = deepcopy(ROWS[0])
    base = row['relatedItems']['nominations'][0]
    row['relatedItems'] = {'nominations': [{**base, 'part': part} for part in ('00', '01', '02')]}
    result = imported(row)
    items = [r for r in result if r.kind == 'legislative_item']
    assert len({r.id for r in items}) == 3
    assert {r.designation for r in items} == {f"PN{base['number']}", f"PN{base['number']}-01", f"PN{base['number']}-02"}


@pytest.mark.parametrize('typ,kind', [('HR', 'bill'), ('S', 'bill'), ('HRES', 'resolution'), ('SRES', 'resolution'),
                                     ('HJRES', 'resolution'), ('SJRES', 'resolution'), ('HCONRES', 'resolution'), ('SCONRES', 'resolution')])
def test_bill_family_preserves_old_identity_and_distinguishes_resolutions(typ, kind):
    row = {**ROWS[0], 'relatedItems': {'bills': [{'congress': 119, 'number': 12, 'type': typ}]}}
    item = next(r for r in imported(row) if r.kind == 'legislative_item')
    assert item.id == context().ids('legislative_item', f'congress.gov|119|{typ}|12')
    assert item.item_type == kind


def test_real_continuations_keep_their_own_dates_and_do_not_claim_held():
    row = ROWS[2]
    occurrences = [r for r in imported(row) if r.kind == 'occurrence']
    assert len(occurrences) == 3
    assert occurrences[0].id == context().ids('occurrence', meetings.meeting_key(row) + '|sitting')
    for i, occurrence in enumerate(occurrences[1:]):
        assert occurrence.scheduled_start.original == row['continuations'][i]['continuationDate']
        assert occurrence.provenance.citations[0].selector == f'/continuations/{i}'
        assert occurrence.status == occurrence.access == 'unknown'
        assert occurrence.location is None


def test_invalid_continuation_stays_evidence_and_is_flagged():
    row = {**ROWS[2], 'continuations': [{'continuationDate': 'bad'}, {}]}
    result = imported(row)
    assert len([r for r in result if r.kind == 'occurrence']) == 1
    assert len([r for r in result if r.kind == 'data_issue']) == 2


def test_real_document_types_survive_without_changing_material_identity():
    expected = {
        'Hearing: Questions for the Record': 'questions_for_record', 'Committee Report': 'report', 'Conference Report': 'report',
        'Hearing: Member Roster': 'hearing_record', 'Hearing: Cover Page': 'hearing_record', 'Hearing: Table of Contents': 'hearing_record',
        'Support Document': 'supporting', 'Committee Recorded Vote': 'vote',
    }
    seen = set()
    for row in ROWS[3:]:
        result = imported(row)
        for doc, material in zip(row['meetingDocuments'], (r for r in result if r.kind == 'material')):
            native = doc['documentType']; seen.add(native)
            assert material.details.category == expected[native]
            assert material.id == context().ids('material', meetings.meeting_key(row) + '|meetingDocuments|' + doc['url'])
            link = next(r for r in result if r.kind == 'material_link' and r.material.id == material.id)
            if native == 'Hearing: Questions for the Record':
                assert link.role == 'questions_for_record'
            if native == 'Committee Recorded Vote':
                assert link.role == 'vote_record'
    assert seen == set(expected)
    assert meetings.category({'documentType': 'Hearing: Questions for the Record', 'name': 'Witness statement about a bill'}) == 'questions_for_record'
    assert meetings.category({'documentType': 'Support Document', 'name': 'Hearing transcript'}) == 'transcript'
