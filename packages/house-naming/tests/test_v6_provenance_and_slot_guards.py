"""Tests for PR-U3a DocMeta V5/V6 backports:
1. Filename upload-slot kind vs. body-verified document kind (`-Bio-` TTF slot ambiguity, `-SD-`, `-Wstate-`).
2. Concatenated `BILLS-` Congress/bill-number sanity guard & `1..130` Congress bounds.
3. Constitutional Noon-Jan-3 Congress boundary helper (`date_to_congress_constitutional`).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

import house_naming
from house_naming import (
    AMBIGUOUS_SLOT_KINDS,
    AMBIGUOUS_SLOT_TOKENS,
    MAX_CONGRESS,
    MIN_CONGRESS,
    Engine,
    date_to_congress_constitutional,
    filename_slot_info,
    is_slot_kind_ambiguous,
    is_valid_congress,
    parse_bills_slug,
    resolve_verified_document_kind,
    split_bills_congress_and_number,
)
from house_naming.filenames import parse_filename
from house_naming.metadata import (
    resolve_verified_document_kind as metadata_resolve_verified_document_kind,
)
from house_naming.values import (
    date_to_congress_constitutional as values_date_to_congress_constitutional,
)


@pytest.fixture(scope='module')
def engine() -> Engine:
    return Engine()


def assert_lossless_spans(result: dict, filename: str) -> None:
    assert ''.join(piece['raw'] for piece in result['pieces']) == filename
    for match in (*result['observations'], *result['suppressed']):
        assert 0 <= match['start'] <= match['end'] <= len(filename)
        for field in match['fields']:
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
            assert filename[field['start']:field['end']] == field['raw']


# ---------------------------------------------------------------------------
# 1. Filename upload-slot ambiguity & body-verified document kind resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'filename,expected_doc_kind,expected_slot_kind,expected_ambiguous',
    [
        # Ambiguous House Clerk upload slots (-Bio- has 59.6% TTF contradiction rate; -SD- / -Wstate- require body check)
        ('HHRG-118-JU00-Bio-SmithJ-20230510.pdf', ['witness-biography'], 'witness-biography', True),
        ('HMTG-117-IF16-Bio-DoeJ-20210615.pdf', ['witness-biography'], 'witness-biography', True),
        ('HMKP-115-AG14-Bio-BlackL-20170309.pdf', ['witness-biography'], 'witness-biography', True),
        ('HHRG-118-JU00-Wstate-SmithJ-20230510.pdf', ['witness-statement'], 'witness-statement', True),
        ('HHRG-118-JU00-Wstate-SmithJ-20230510-SD001.pdf', ['witness-support'], 'witness-support', True),
        ('HHRG-118-JU00-20230510-SD001.pdf', ['meeting-support'], 'meeting-support', True),
        ('HHRG-114-HA00-20160517-CPg.pdf', ['committee-document'], 'committee-document', True),
        ('HHRG-115-SM27-20180614-TOC.pdf', ['committee-document'], 'committee-document', True),
        # Non-ambiguous Clerk / GPO structured slots
        ('HHRG-118-JU00-TTF-SmithJ-20230510.pdf', ['testimony-disclosure'], 'testimony-disclosure', False),
        ('HHRG-118-JU00-MState-N000002-20230510.pdf', ['member-statement'], 'member-statement', False),
        ('HHRG-118-JU00-Transcript-20230510.pdf', ['committee-transcript'], 'committee-transcript', False),
        ('HHRG-118-JU00-WList-20230510.pdf', ['witness-list'], 'witness-list', False),
        ('HMKP-119-II00-20251120-QFR001.pdf', ['questions-for-record'], 'questions-for-record', False),
        ('HHRG-114-IF02-20160224-MbrRoster.pdf', ['member-roster'], 'member-roster', False),
        ('CRPT-114-JU00-Vote001-20160525.pdf', ['committee-vote'], 'committee-vote', False),
        ('HMTG-112-AG-Weekof20111205.pdf', ['weekly-meeting-notice'], 'weekly-meeting-notice', False),
        ('BILLS-118hr1418ih.pdf', ['bill-numbered'], 'bill-numbered', False),
        ('CHRG-118shrg049104057.pdf', ['published-hearing'], 'published-hearing', False),
    ],
)
def test_filename_slot_kind_and_ambiguity_preserve_backward_compat(
    engine: Engine,
    filename: str,
    expected_doc_kind: list[str],
    expected_slot_kind: str,
    expected_ambiguous: bool,
) -> None:
    extracted = engine.extract(filename)
    assert_lossless_spans(extracted, filename)
    parsed = parse_filename(filename)

    # Existing public fields remain 100% intact for backward compatibility
    assert extracted['metadata']['document_kind'] == expected_doc_kind
    assert parsed.metadata['document_kind'] == expected_doc_kind

    # Explicit slot fields on both Engine.extract(), ParsedFilename, and metadata dict
    assert extracted['filename_slot_kind'] == expected_slot_kind
    assert extracted['is_slot_ambiguous'] is expected_ambiguous
    assert parsed.filename_slot_kind == expected_slot_kind
    assert parsed.is_slot_ambiguous is expected_ambiguous
    assert extracted['metadata']['filename_slot_kind'] == [expected_slot_kind]
    assert extracted['metadata']['is_slot_ambiguous'] == ['true' if expected_ambiguous else 'false']


def test_malformed_and_sha_prefixed_clerk_slots_retain_slot_ambiguity(engine: Engine) -> None:
    sha = '0123456789abcdef' * 4
    prefixed = f'{sha}.HHRG-118-JU00-Bio-SmithJ-20230510.pdf'
    res_prefixed = parse_filename(prefixed)
    assert res_prefixed.filename_slot_kind == 'witness-biography'
    assert res_prefixed.is_slot_ambiguous is True

    # Malformed 7-digit date in Clerk -Bio- filename still flags ambiguous Bio upload slot
    malformed_bio = parse_filename('HHRG-118-JU00-Bio-SmithJ-2023051.pdf')
    assert malformed_bio.filename_slot_kind == 'witness-biography'
    assert malformed_bio.is_slot_ambiguous is True

    # Standalone -SD001 upload suffix without Clerk prefix still marks ambiguous support slot
    standalone_sd = parse_filename('WitnessPacket-SD002.pdf')
    assert standalone_sd.filename_slot_kind == 'support-document'
    assert standalone_sd.is_slot_ambiguous is True

    # Unstructured free-text filenames have no structured upload slot
    free_text = parse_filename('Lee-testimony.pdf')
    assert free_text.metadata['document_kind'] == ['testimony']
    assert free_text.filename_slot_kind is None
    assert free_text.is_slot_ambiguous is False
    assert 'filename_slot_kind' not in free_text.metadata


def test_resolve_verified_document_kind_guards_bio_ttf_and_sd_contradictions() -> None:
    assert metadata_resolve_verified_document_kind is resolve_verified_document_kind
    assert {'bio', 'sd', 'wstate'} <= AMBIGUOUS_SLOT_TOKENS
    assert {'witness-biography', 'witness-statement', 'witness-support', 'meeting-support'} <= AMBIGUOUS_SLOT_KINDS

    for tok in ('Bio', 'bio', 'witness-biography', 'SD', 'meeting-support', 'witness-support', 'Wstate', 'witness-statement'):
        assert is_slot_kind_ambiguous(tok) is True
        # Without body verification, ambiguous slots NEVER resolve to ground-truth document kind
        assert resolve_verified_document_kind(tok, None) is None
        assert resolve_verified_document_kind(tok, '') is None
        assert resolve_verified_document_kind(tok, '   ') is None

    # TTF disclosure form uploaded into a -Bio- or -Wstate- slot resolves to the body-verified TTF kind
    assert resolve_verified_document_kind('witness-biography', 'testimony-disclosure') == 'testimony-disclosure'
    assert resolve_verified_document_kind('Bio', 'truth_in_testimony_disclosure') == 'truth_in_testimony_disclosure'
    assert resolve_verified_document_kind('witness-statement', 'testimony-disclosure') == 'testimony-disclosure'
    assert resolve_verified_document_kind('meeting-support', 'letter') == 'letter'
    assert resolve_verified_document_kind('SD', 'investigative_exhibit') == 'investigative_exhibit'
    # Genuine biography confirmed by body verification resolves to witness-biography
    assert resolve_verified_document_kind('witness-biography', 'witness-biography') == 'witness-biography'

    # Non-ambiguous slots preserve their normalized kind when body_kind is absent, while allowing body override
    assert is_slot_kind_ambiguous('TTF') is False
    assert is_slot_kind_ambiguous('testimony-disclosure') is False
    assert resolve_verified_document_kind('TTF', None) == 'testimony-disclosure'
    assert resolve_verified_document_kind('Transcript', None) == 'committee-transcript'
    assert resolve_verified_document_kind('WList', None) == 'witness-list'
    assert resolve_verified_document_kind('bill-numbered', None) == 'bill-numbered'
    assert resolve_verified_document_kind('testimony-disclosure', 'witness-statement') == 'witness-statement'
    assert resolve_verified_document_kind(None, None) is None


# ---------------------------------------------------------------------------
# 2. Concatenated BILLS- Congress/bill-number sanity guard & Congress bounds
# ---------------------------------------------------------------------------


def test_valid_congress_bounds_helper() -> None:
    assert MIN_CONGRESS == 1 and MAX_CONGRESS == 130
    for valid in (1, 93, 100, 115, 118, 119, 130, '1', '93', '115', '130'):
        assert is_valid_congress(valid) is True
    for invalid in (0, -1, 131, 150, 932, 999, 1117, 114119, 1152823, True, False, None, '', '0115', '000', 'abc'):
        assert is_valid_congress(invalid) is False


@pytest.mark.parametrize(
    'filename,expected_cong,expected_mtype,expected_mnum,expected_stage,expected_concat',
    [
        ('BILLS-1152823ih.pdf', 115, None, 2823, 'ih', True),
        ('BILLS-1152823ih-U1.pdf', 115, None, 2823, 'ih', True),
        ('BILLS1152823ih.pdf', 115, None, 2823, 'ih', True),
        ('BILLS112hr2576ih.pdf', 112, 'hr', 2576, 'ih', True),
        ('BILLS117HR2377RH.xml', 117, 'hr', 2377, 'rh', True),
        ('BILLS-1141192ih-NationalDiabetesClinicalCareCommissionAct-U1_0.pdf', 114, None, 1192, 'ih', True),
        ('BILLS-115-HR2823ih.pdf', 115, 'hr', 2823, 'ih', False),
        ('BILLS-115hr2823ih.pdf', 115, 'hr', 2823, 'ih', False),
        ('BILLS-115-2823ih.pdf', 115, None, 2823, 'ih', False),
        ('BILLS-93hr2823ih.pdf', 93, 'hr', 2823, 'ih', False),
        ('BILLS-93-HR2823ih.pdf', 93, 'hr', 2823, 'ih', False),
    ],
)
def test_bills_concatenated_split_recovery(
    engine: Engine,
    filename: str,
    expected_cong: int,
    expected_mtype: str | None,
    expected_mnum: int,
    expected_stage: str,
    expected_concat: bool,
) -> None:
    assert parse_bills_slug is split_bills_congress_and_number
    split = split_bills_congress_and_number(filename)
    assert split == {
        'congress': expected_cong,
        'measure_type': expected_mtype,
        'measure_number': expected_mnum,
        'number_token': str(expected_mnum),
        'stage': expected_stage,
        'was_concatenated': expected_concat,
    }

    extracted = engine.extract(filename)
    assert_lossless_spans(extracted, filename)
    parsed = parse_filename(filename)
    assert parsed.metadata['congress'] == [str(expected_cong)]
    assert parsed.metadata['measure_number'] == [str(expected_mnum)]
    if expected_mtype is not None:
        assert f'{expected_mtype}{expected_mnum}' in parsed.metadata['measure_references']


@pytest.mark.parametrize(
    'malformed',
    [
        # Jammed multi-Congress / 4+ digit Congress before explicit measure code
        'BILLS-1152823hr2823ih.pdf',
        'BILLS-114119hr1ih.pdf',
        'BILLS-1117s2126-SUS.pdf',
        'BILLS-114119-HR1-A000055-Amdt-1.pdf',
        # Overlong 6+ digit untyped number after 3-digit Congress
        'BILLS-115123456ih.pdf',
        # Implausible Congress > 130 or < 1
        'BILLS-131hr1ih.pdf',
        'BILLS-150hr1ih.pdf',
        'BILLS-1502823ih.pdf',
        'BILLS-9992823ih.pdf',
        'BILLS-999hr1ih.pdf',
        'BILLS-000hr1ih.pdf',
        # Ambiguous 2-digit Congress concatenated directly with untyped bill digits (932 > 130)
        'BILLS-932823ih.pdf',
    ],
)
def test_bills_malformed_and_out_of_bounds_congress_rejected(engine: Engine, malformed: str) -> None:
    assert split_bills_congress_and_number(malformed) is None
    extracted = engine.extract(malformed)
    assert_lossless_spans(extracted, malformed)
    parsed = parse_filename(malformed)

    # Never emits implausible (> 130) or mis-grouped Congress in metadata
    assert 'congress' not in parsed.metadata

    # Multi-digit concatenated Congress candidates in Engine.parse are explicitly rejected
    if any(tok in malformed for tok in ('1152823hr', '114119', '1117s', '115123456')):
        assert not extracted['valid']
        assert 'invalid-congress-boundary' in extracted['issues']


# ---------------------------------------------------------------------------
# 3. Constitutional Noon-Jan-3 Congress boundary helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'ymd,expected_congress',
    [
        # Explicit Done Criteria boundary dates
        ('2021-01-01', 116),
        ('2021-01-02', 116),
        ('2021-01-03', 117),
        ('2022-01-02', 117),
        ('2023-01-03', 118),
        # Additional odd/even early-January boundaries across modern Congresses
        ('2015-01-01', 113),
        ('2015-01-02', 113),
        ('2015-01-03', 114),
        ('2017-01-02', 114),
        ('2017-01-03', 115),
        ('2019-01-02', 115),
        ('2019-01-03', 116),
        ('2023-01-01', 117),
        ('2023-01-02', 117),
        ('2024-01-01', 118),
        ('2024-01-02', 118),
        ('2025-01-01', 118),
        ('2025-01-02', 118),
        ('2025-01-03', 119),
        ('2026-01-02', 119),
        ('2027-01-02', 119),
        ('2027-01-03', 120),
        # Compact Clerk YYYYMMDD strings, slash dates, date objects, and (Y, M, D) tuples
        ('20210101', 116),
        ('20210102', 116),
        ('20210103', 117),
        ('20220102', 117),
        ('20230103', 118),
        ('2021/01/02', 116),
        (date(2021, 1, 1), 116),
        (date(2021, 1, 2), 116),
        (date(2021, 1, 3), 117),
        (date(2022, 1, 2), 117),
        (date(2023, 1, 3), 118),
        ((2021, 1, 2), 116),
        ((2021, 1, 3), 117),
        # Pre-20th Amendment March 4 historical boundaries & 1935 transition
        ('1789-03-04', 1),
        ('1933-03-03', 72),
        ('1933-03-04', 73),
        ('1935-01-01', 73),
        ('1935-01-02', 73),
        ('1935-01-03', 74),
    ],
)
def test_date_to_congress_constitutional_dates(ymd, expected_congress: int) -> None:
    assert house_naming.date_to_congress_constitutional is values_date_to_congress_constitutional
    assert date_to_congress_constitutional(ymd) == expected_congress


def test_date_to_congress_constitutional_noon_jan3_timestamps() -> None:
    # Naive wall-clock datetimes on Jan 3 of an odd year: < 12:00 -> outgoing, >= 12:00 -> incoming
    assert date_to_congress_constitutional(datetime(2021, 1, 3, 0, 0, 0)) == 116
    assert date_to_congress_constitutional(datetime(2021, 1, 3, 11, 59, 59)) == 116
    assert date_to_congress_constitutional(datetime(2021, 1, 3, 12, 0, 0)) == 117
    assert date_to_congress_constitutional(datetime(2023, 1, 3, 11, 30, 0)) == 117
    assert date_to_congress_constitutional(datetime(2023, 1, 3, 12, 0, 0)) == 118

    # Timezone-aware UTC timestamps converted to Washington, D.C. (EST = UTC-5 in January)
    assert date_to_congress_constitutional(datetime(2021, 1, 3, 16, 59, 59, tzinfo=timezone.utc)) == 116
    assert date_to_congress_constitutional(datetime(2021, 1, 3, 17, 0, 0, tzinfo=timezone.utc)) == 117
    assert date_to_congress_constitutional('2021-01-03T16:59:59Z') == 116
    assert date_to_congress_constitutional('2021-01-03T17:00:00Z') == 117
    assert date_to_congress_constitutional('2021-01-03T11:59:00-05:00') == 116
    assert date_to_congress_constitutional('2021-01-03T12:00:00-05:00') == 117

    # Even-numbered year Jan 3 morning stays in the same Congress
    assert date_to_congress_constitutional(datetime(2022, 1, 3, 9, 0, 0)) == 117


@pytest.mark.parametrize(
    'invalid_input',
    [
        None,
        '',
        '   ',
        'not-a-date',
        '2021-02-29',
        '2021-13-01',
        '20210229',
        '1789-03-03',
        '1776-07-04',
        '2299-01-05',
        True,
        False,
        20210102,
        (2021, 2, 29),
        (True, 1, 2),
    ],
)
def test_date_to_congress_constitutional_invalid_or_out_of_bounds(invalid_input) -> None:
    assert date_to_congress_constitutional(invalid_input) is None
