"""Reviewed receipt eligibility through the actual roster SQL, including competing contexts."""
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from congress_api.lake.appearance_records import build_appearance_record_row, current_version
from test_meeting_semantics import ROOT, record, resolve, witness


ORIGINAL = Path(__file__).parent / 'fixtures/house-100876-original.xml.gz'
MANUAL = ROOT / 'packages/congress_api/tests/fixtures/meeting_inventory/house-repeated-documents.xml'
ORIGINAL_SHA = 'ba982aafcdb8d02568e8b44f46bfdabd6e99226a2e61fd4c909612404821e55a'
MANUAL_SHA = '69547a916ec086bb82bb6d504c5400381051f9c8d508634b37904fbc3eb7064e'
RECEIPT = 'receipts/house/witness-xml/undated/assemble-20260930.jsonl.gz'


def body_bytes(path):
    body = path.read_bytes()
    return gzip.decompress(body) if path.suffix == '.gz' else body


def parsed(path):
    body = body_bytes(path)
    row = build_appearance_record_row(hashlib.sha256(body).hexdigest(), 'house_xml', body,
                                      parser_version=current_version('house_xml'))
    row['record_sha_hex'] = row.pop('record_sha')
    return row


def capture(sha, **values):
    return dict(sha_hex=sha, family='house/witness-xml', mode='fetch', outcome='stored',
                **values)


def retained_original():
    # Completion receipt line 59: verified original file, with unknown acquisition time and HTTP facts.
    return capture(ORIGINAL_SHA, receipt_key='receipts/house/witness-xml/undated/assemble-20260930-completion.jsonl.gz',
                   receipt_line=59, capture_index=0, run_id='external-sources/hearing-text/docs_house_xml/wlist/100876.xml',
                   original_path='external-sources/hearing-text/docs_house_xml/wlist/100876.xml')


def manual_captures(sha=MANUAL_SHA, **values):
    return [capture(sha, receipt_key=RECEIPT, receipt_line=line, capture_index=0,
                    run_id=f'source-models/manual-house-pdf/house-repeated-documents.{suffix}.json', **values)
            for line, suffix in ((1, 'normalized'), (2, 'model'))]


def run_rosters(directory, records=None, captures=None, **options):
    return resolve(directory, records or [parsed(ORIGINAL), parsed(MANUAL)], [], {},
                   meetings=((100876, '2013-05-21', 'Cybersecurity supply chain'),),
                   capture_rows=captures or [retained_original(), *manual_captures()], details=True, **options)


def assert_original_occurrences(rows):
    """Compare each occurrence and its URL associations to an independent direct XML reading."""
    raw = ET.fromstring(body_bytes(ORIGINAL))
    expected = Counter()
    for entry in raw.findall('./panel/witness'):
        expected[tuple(entry.findtext(tag) for tag in ('firstname', 'middlename', 'lastname', 'suffix', 'position', 'organization'))
                 + (frozenset(file.attrib['doc-url'] for file in entry.findall('./witness-documents/witness-document/files/file')),)] += 1
    actual = Counter(tuple(row[key] for key in ('given', 'middle', 'family', 'suffix', 'position', 'organization'))
                     + (frozenset(row['document_urls']),) for row in rows)
    assert actual == expected
    assert len(rows) == 7
    assert len({row['source_locator'] for row in rows}) == 7
    assert all(len(row['document_urls']) == len(set(row['document_urls'])) for row in rows)
    assert all(row['record_sha_hex'] == ORIGINAL_SHA and row['testified'] is None for row in rows)


@pytest.fixture(scope='module')
def repaired(tmp_path_factory):
    assert hashlib.sha256(body_bytes(ORIGINAL)).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(MANUAL.read_bytes()).hexdigest() == MANUAL_SHA
    return run_rosters(tmp_path_factory.mktemp('reviewed-house-roster'))


def test_exact_manual_receipts_cannot_displace_the_retained_original(repaired):
    assert_original_occurrences(repaired['resolved'])
    observed = {row['record_sha_hex']: row for row in repaired['observations']}
    assert observed[ORIGINAL_SHA]['observation_eligible'] is True
    assert observed[ORIGINAL_SHA]['retrieved_at'] is None
    assert observed[MANUAL_SHA]['observation_eligible'] is False
    assert 'manual review/fixture derivative' in observed[MANUAL_SHA]['observation_exclusion_reason']
    excluded = [row for row in repaired['capture_contexts'] if row['exclusion_reason']]
    assert [(row['receipt_key'], row['receipt_line'], row['capture_index'], row['run_id']) for row in excluded] == [
        (RECEIPT, line, 0, f'source-models/manual-house-pdf/house-repeated-documents.{suffix}.json')
        for line, suffix in ((1, 'normalized'), (2, 'model'))]


def test_without_the_reviewed_decision_the_real_counterexample_hides_six_occurrences(tmp_path):
    baseline = run_rosters(tmp_path, observation_exclusions=[])
    assert len(baseline['resolved']) == 1
    assert baseline['resolved'][0]['record_sha_hex'] == MANUAL_SHA


def test_manual_receipt_authority_cannot_be_created_by_a_favorable_digest_or_late_date(tmp_path):
    manual = parsed(MANUAL)
    manual['record_sha_hex'] = '00' * 32
    rows = run_rosters(tmp_path, records=[parsed(ORIGINAL), manual],
                       captures=[retained_original(), *manual_captures('00' * 32, complete=True, http_status=200,
                           retrieved_at='2099-01-01T00:00:00Z', url='https://docs.house.gov/meetings/IF/IF16/20130521/100876/manual.xml')])
    assert_original_occurrences(rows['resolved'])


@pytest.mark.parametrize('context', ['http', 'retained-file'])
def test_identical_bytes_with_an_independent_source_context_remain_eligible(tmp_path, context):
    independent = capture(MANUAL_SHA, receipt_key='receipts/house/witness-xml/independent.jsonl.gz',
                          receipt_line=1, capture_index=0, run_id='independent-publisher-observation')
    if context == 'http':
        independent.update(complete=True, http_status=200, retrieved_at='2026-11-06T12:00:00Z',
                           url='https://docs.house.gov/meetings/IF/IF16/20130521/100876/WList.xml')
    else:
        independent['original_path'] = 'separately-qualified/wlist/100876.xml'
    result = run_rosters(tmp_path, captures=[retained_original(), *manual_captures(), independent])
    assert len(result['resolved']) == 1
    assert result['resolved'][0]['record_sha_hex'] == MANUAL_SHA
    assert next(row for row in result['observations'] if row['record_sha_hex'] == MANUAL_SHA)['observation_eligible'] is True
    assert len([row for row in result['capture_contexts'] if row['exclusion_reason']]) == 2


@pytest.mark.parametrize('state', ['present', 'empty'])
def test_authentic_newer_roster_replaces_the_original_without_union(tmp_path, state):
    newer = record('newer-' + state, 'house_xml', [witness('Later Witness')] if state == 'present' else [], event_id=100876)
    newer_capture = capture(newer['record_sha_hex'], complete=True, http_status=200,
                            url='https://docs.house.gov/meetings/IF/IF16/20130521/100876/WList.xml',
                            retrieved_at='2026-11-06T12:00:00Z', receipt_key='receipts/house/later.jsonl.gz',
                            receipt_line=1, capture_index=0, run_id='publisher-fetch')
    result = run_rosters(tmp_path, records=[parsed(ORIGINAL), parsed(MANUAL), newer],
                         captures=[retained_original(), *manual_captures(), newer_capture])
    assert [row['name'] for row in result['resolved']] == (['Later Witness'] if state == 'present' else [])


@pytest.mark.parametrize('corruption', ['omitted_occurrence', 'wrong_role', 'wrong_link', 'invented_testimony'])
def test_raw_occurrence_comparison_detects_planted_wrong_outputs(repaired, corruption):
    rows = deepcopy(repaired['resolved'])
    if corruption == 'omitted_occurrence':
        rows.pop()
    elif corruption == 'wrong_role':
        rows[1]['position'] = rows[0]['position']
    elif corruption == 'wrong_link':
        rows[1]['document_urls'][0] = rows[0]['document_urls'][0]
    else:
        rows[1]['testified'] = True
    with pytest.raises(AssertionError):
        assert_original_occurrences(rows)
