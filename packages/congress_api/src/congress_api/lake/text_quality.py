"""Measure review signals; source fidelity and action policy have other owners.

Native/final differences preserve order, multiplicity and original character
spans. They nominate review, including legitimate cleanup, never a defect verdict.
"""
from collections import defaultdict, deque
from difflib import SequenceMatcher
from hashlib import sha256
from itertools import islice, product
import re

from spicy_docs.extraction.quality import (
    MAX_COMPARE_CHARS as MAX_COMPARE_CHARS,
    MAX_COMPARE_TOKENS as MAX_COMPARE_TOKENS,
    MAX_TOKEN_PRODUCT as MAX_TOKEN_PRODUCT,
    _tokens as _comparison_tokens,
    compare_intermediate as compare_intermediate,
    text_corruption_measures as text_corruption_measures,
)

from congress_api.parsers.response_roles import assess_response

POLICY_VERSION = 'ct-text-quality-measures-v3'
FEATURE_VERSION = 'pdf-page-features-20261113-1'
MAX_TEXT_BYTES = 256 << 10
_MIN_MISSING_PASSAGE = 20
_KEY = ('body_sha256', 'parser', 'parser_version', 'text_sha256')


def coverage_measures(feature, slot=None):
    if feature is None:
        return {'status': 'missing_page_features'}
    if feature['feature_version'] != FEATURE_VERSION:
        raise ValueError('unsupported retained page-feature version')
    counts, ocr = feature['page_nonspace_chars'], set(feature['ocr_page_numbers'])
    if len(counts) != feature['pages'] or any(type(n) is not int or n < 0 for n in counts):
        raise ValueError('page feature counts disagree')
    if len(ocr) != len(feature['ocr_page_numbers']) or any(type(n) is not int or not 1 <= n <= len(counts) for n in ocr):
        raise ValueError('invalid OCR slot identities')
    if slot is not None:
        if not 1 <= slot <= len(counts):
            raise ValueError('selected page has no retained offset slot')
        counts, ocr = [counts[slot-1]], {1} if slot in ocr else set()
    longest = run = interior = 0
    for count in counts[1:-1]:
        interior += count == 0
        run = run+1 if count == 0 else 0
        longest = max(longest, run)
    return {'status': 'measured_offset_slots_not_physical_pages', 'recorded_offset_slots': len(counts),
            'empty_slots': sum(n == 0 for n in counts), 'interior_empty_slots': interior,
            'longest_interior_empty_run': longest,
            'nonocr_empty_slots': sum(n == 0 and i+1 not in ocr for i, n in enumerate(counts)),
            'under_200_slots': sum(n < 200 for n in counts),
            'nonocr_under_200_slots': sum(n < 200 and i+1 not in ocr for i, n in enumerate(counts)),
            'sparse_under_1000_slots': sum(n < 1000 for n in counts),
            'under_200_slot_fraction': sum(n < 200 for n in counts)/len(counts) if counts else None,
            'ocr_slot_count': len(ocr),
            'sparse_repeated_line_char_fraction': feature['sparse_repeated_line_char_fraction'] if slot is None else None,
            'repetition_scope': 'whole_reading' if slot is None else 'unavailable_for_selected_page',
            'selected_offset_slot': slot,
            'nonspace_characters': sum(counts), 'physical_source_coverage': 'unknown'}


def axis_ranks(axes):
    """Independent lexicographic review order; no combined quality score."""
    coverage, recognition, cleanup, role = (axes[n] for n in ('coverage', 'recognition', 'cleanup', 'role'))
    return {
        'coverage': [coverage.get('longest_interior_empty_run', 0), coverage.get('nonocr_empty_slots', 0),
                     coverage.get('sparse_repeated_line_char_fraction') or 0, coverage.get('under_200_slot_fraction') or 0],
        'recognition': [sum(recognition.get(n, 0) for n in ('replacement_characters', 'nonwhitespace_control_characters', 'private_use_characters')),
                        recognition.get('longest_latin_single_letter_run', 0), recognition.get('latin_single_letter_fraction') or 0],
        'cleanup': [cleanup.get('removed_content_tokens', 0), cleanup.get('removed_symbol_tokens', 0)],
        'role': [int(role.get('role') in {'error_response', 'wait_response', 'empty_response', 'feed'})],
    }


def fts_triage(axes):
    """Cheap search-usefulness bands; thresholds nominate review, not rejection."""
    c, r, cleanup, role = (axes[n] for n in ('coverage', 'recognition', 'cleanup', 'role'))
    slots = c.get('recorded_offset_slots', 0)
    run = c.get('longest_interior_empty_run', 0)
    reasons, later = [], []
    if role.get('role') in {'error_response', 'wait_response', 'empty_response'}:
        reasons.append('obvious_response_body')
    if (r.get('status') == 'measured' and r.get('alphanumeric_characters') == 0
            or slots and c.get('nonspace_characters') == 0):
        reasons.append('empty_or_no_searchable_tokens')
    if run >= 3 and (run/max(slots, 1) >= 0.1 or run >= 20):
        reasons.append('substantial_interior_blank_run')
    bad_chars = sum(r.get(n, 0) for n in ('replacement_characters', 'nonwhitespace_control_characters', 'private_use_characters'))
    if (bad_chars >= 3 and bad_chars/max(r.get('unicode_characters', 0), 1) >= 0.01
            or r.get('longest_latin_single_letter_run', 0) >= 12):
        reasons.append('severe_mechanical_garbling')
    elif bad_chars or r.get('longest_latin_single_letter_run', 0) >= 8:
        later.append('possible_mechanical_garbling')
    if r.get('largest_unmatched_ocr_passage_tokens', 0) >= _MIN_MISSING_PASSAGE:
        later.append('possible_missing_content')
    if (slots >= 3 and (c.get('sparse_repeated_line_char_fraction') or 0) >= 0.8
            and c.get('sparse_under_1000_slots', 0)/slots >= 0.8
            and c.get('nonspace_characters', 0)/slots < 200):
        reasons.append('sparse_output_dominated_by_repeated_furniture')
    if slots >= 3 and c.get('under_200_slot_fraction', 0) >= 0.8:
        later.append('mostly_near_empty_multi_slot_output')
    if (c.get('ocr_slot_count', 0) and c.get('nonocr_under_200_slots', 0) >= 3
            and c['nonocr_under_200_slots']/max(slots, 1) >= 0.2):
        later.append('mixed_sparse_native_ocr_slots')
    if cleanup.get('removed_content_tokens', 0) >= 20 and (cleanup.get('ordered_retained_token_fraction') or 0) < 0.8:
        later.append('substantial_intermediate_difference')
    if not reasons and (c.get('empty_slots', 0) or role.get('role') == 'feed'):
        later.append('blank_slots_or_structured_source_may_be_legitimate')
    if reasons:
        return {'band': 'review_first', 'reasons': reasons+later, 'meaning': 'possible_searchability_failure_not_certified_defect'}
    if later:
        return {'band': 'review_later', 'reasons': later, 'meaning': 'limited_or_ambiguous_signal'}
    if not slots and r.get('status') != 'measured':
        return {'band': 'unassessed', 'reasons': ['no_output_measurements'], 'meaning': 'unknown'}
    return {'band': 'no_obvious_failure_detected', 'reasons': [],
            'meaning': 'likely_searchable_under_measured_checks_not_source_certified'}


_MIN_MOVE_ANCHOR = 4
_MIN_INTERIOR_MOVE = 12
_MAX_ANCHOR_PROBES = 16


def _moved_spans(deleted, inserted, width):
    """Yield contiguous runs found by the bounded anchor search."""
    index = defaultdict(deque)
    page_order = []
    for i, chunk in enumerate(inserted):
        for pos in range(len(chunk) - width + 1):
            positions = index[chunk[pos:pos + width]]
            positions.append((i, pos))
            page_order.append(positions)
        page_order.extend([None] * min(width - 1, len(chunk)))

    inserted_offsets = iter(page_order)
    for d, chunk in enumerate(deleted):
        # (inserted chunk, offset difference) identifies a contiguous alignment.
        active = {}
        for offset in range(len(chunk)):
            end = offset + width
            following = {}
            extension_probes = 0
            positions = index.get(chunk[offset:end])
            if positions:
                probes = len(positions)
                if probes > _MAX_ANCHOR_PROBES:
                    probes = max(1, _MAX_ANCHOR_PROBES - len(active))
                    extension_probes = _MAX_ANCHOR_PROBES - probes
                for i, pos in islice(positions, probes):
                    alignment = (i, pos - offset)
                    following[alignment] = active.pop(alignment, offset)
            for probe, ((i, delta), start) in enumerate(active.items()):
                if (probe < extension_probes and end + delta <= len(inserted[i])
                        and chunk[end - 1] == inserted[i][end + delta - 1]):
                    following[i, delta] = start
                else:
                    yield end - 1 - start, d, start, i, start + delta
            active = following
            # Advance crowded anchors in page order so later copies can pair
            # with later positions, even when the first 16 are already taken.
            passed = next(inserted_offsets, None)
            if passed and len(passed) > _MAX_ANCHOR_PROBES:
                passed.rotate(-1)


def _reserve_exact_spans(ref, out, ref_mask, out_mask):
    buckets = [[] for _ in range(min(len(ref), len(out)) + 1)]
    for length, _, a, _, b in _moved_spans([ref], [out], width=_MIN_INTERIOR_MOVE):
        buckets[length].append((a, b))

    for length in range(len(buckets) - 1, _MIN_INTERIOR_MOVE - 1, -1):
        for a, b in buckets[length]:
            # A reservation at least this long can cover only a prefix, suffix,
            # or the entire candidate. Reconsider the remainder at its own length.
            left, right = 0, length
            while left < right and (ref_mask[a + left] or out_mask[b + left]):
                left += 1
            while right > left and (ref_mask[a + right - 1] or out_mask[b + right - 1]):
                right -= 1
            remaining = right - left
            if remaining == length:
                ref_mask[a:a + length] = out_mask[b:b + length] = b'\x01' * length
            elif remaining >= _MIN_INTERIOR_MOVE:
                buckets[remaining].append((a + left, b + left))


# Prefer nearby continuations when several four-word anchors fit the edit gap.
_MAX_EDIT_GAP = 4
_EDIT_GAPS = sorted(product(range(_MAX_EDIT_GAP + 1), repeat=2), key=lambda gaps: (max(gaps), sum(gaps)))


def _anchor_chain(ref, out, a, b, ref_end, out_end, out_mask):
    """Follow exact runs forward while both sides have at most four intervening words."""
    width = _MIN_MOVE_ANCHOR
    blocks = []
    start_a, start_b = a, b
    a, b = a + width, b + width
    while True:
        used = out_mask.find(1, b, min(out_end, b + _MAX_EDIT_GAP + width))
        if used >= 0:
            out_end = used
        for gap_ref, gap_out in _EDIT_GAPS:
            p, q = a + gap_ref, b + gap_out
            if (p + width <= ref_end and q + width <= out_end
                    and ref[p:p + width] == out[q:q + width]):
                # Extend only up to the next anchor. An inserted copy of its
                # first word could otherwise consume part of that four-word run.
                while a < p and b < q and ref[a] == out[b]:
                    a += 1
                    b += 1
                blocks.append((start_a, start_b, a - start_a))
                start_a, start_b = p, q
                a, b = p + width, q + width
                break
        else:
            if a == ref_end or b == out_end or ref[a] != out[b]:
                blocks.append((start_a, start_b, a - start_a))
                return blocks
            a += 1
            b += 1


def _reserve_edited_spans(ref, out, ref_mask, out_mask):
    """Reserve each chain once, including equal words at corresponding offsets in its gaps."""
    width = _MIN_MOVE_ANCHOR
    positions = defaultdict(deque)
    for run in re.finditer(b'\x00+', out_mask):
        for b in range(run.start(), run.end() - _MIN_INTERIOR_MOVE + 1):
            positions[out[b:b + width]].append((b, run.end()))

    for run in re.finditer(b'\x00+', ref_mask):
        a = run.start()
        while a + _MIN_INTERIOR_MOVE <= run.end():
            starts = positions.get(ref[a:a + width], ())
            for b, end in islice(starts, _MAX_ANCHOR_PROBES):
                if out_mask.find(1, b, b + width) >= 0:
                    continue
                blocks = _anchor_chain(ref, out, a, b, run.end(), end, out_mask)
                if sum(length for _, _, length in blocks) < _MIN_INTERIOR_MOVE:
                    continue
                for p, q, length in blocks:
                    for i, j in zip(range(a, p), range(b, q)):
                        if ref[i] == out[j]:
                            ref_mask[i] = out_mask[j] = 1
                    a, b = p + length, q + length
                    ref_mask[p:a] = out_mask[q:b] = b'\x01' * length
                break
            else:
                a += 1
            if len(starts) > _MAX_ANCHOR_PROBES:
                starts.rotate(-1)


def _reserve_page_edges(ref, out, ref_mask, out_mask):
    """Credit short headings and footers when one omission or insertion explains an edge."""
    def edges(mask):
        first = mask.find(1)
        if first < 0:
            return [(0, len(mask))]
        return [(0, first), (mask.rfind(1) + 1, len(mask))]

    for (a, end_a), (b, end_b) in zip(edges(ref_mask), edges(out_mask)):
        shorter = min(end_a - a, end_b - b)
        prefix = 0
        while prefix < shorter and ref[a + prefix] == out[b + prefix]:
            prefix += 1
        suffix = shorter - prefix
        if ref[end_a - suffix:end_a] == out[end_b - suffix:end_b]:
            ref_mask[a:a + prefix] = out_mask[b:b + prefix] = b'\x01' * prefix
            ref_mask[end_a - suffix:end_a] = out_mask[end_b - suffix:end_b] = b'\x01' * suffix


def _largest_unmatched_ocr_passage(intermediate, text):
    """Measure the longest unaccounted stretch of the independent OCR page."""
    def words(s):
        return tuple(token for token, _, _ in _comparison_tokens(s)
                     if any(c.isalnum() for c in token))

    ref, out = words(intermediate), words(text)
    if not ref or ref == out:
        return 0
    if not out:
        return len(ref)
    if len(ref) < _MIN_MISSING_PASSAGE:
        changes = SequenceMatcher(None, ref, out, autojunk=False).get_opcodes()
        return max((b - a for tag, a, b, _, _ in changes if tag != 'equal'), default=0)

    ref_mask, out_mask = bytearray(len(ref)), bytearray(len(out))
    _reserve_exact_spans(ref, out, ref_mask, out_mask)
    _reserve_edited_spans(ref, out, ref_mask, out_mask)
    _reserve_page_edges(ref, out, ref_mask, out_mask)
    return max(map(len, ref_mask.split(b'\x01')))


def measure_quality(identity, *, text=None, intermediate=None, feature=None, raw_markup=None):
    """Measure an exact output scope. Labels and source-review judgments are not inputs."""
    if text is not None:
        raw = text.encode()
        if len(raw) > MAX_TEXT_BYTES:
            raise ValueError('output exceeds bounded text measurement size')
        if sha256(raw).hexdigest() != identity['output_sha256']:
            raise ValueError('output text hash differs from scoped identity')
    if feature is not None and any(feature[k] != identity[k] for k in _KEY):
        raise ValueError('page features differ from exact reading key or text hash')
    if identity['scope'] == 'reading' and identity['output_sha256'] != identity['text_sha256']:
        raise ValueError('whole-reading output hash differs from reading text hash')
    if identity['scope'] == 'page' and (not identity.get('page_number') or not identity.get('source_page_count')
                                      or identity['page_number'] > identity['source_page_count']):
        raise ValueError('page scope requires independently known physical page/count')
    if feature is not None and identity['scope'] == 'page' and feature['pages'] != identity['source_page_count']:
        coverage = {'status': 'unassessed_page_slot_mapping_count_differs', 'physical_source_coverage': 'unknown'}
    else:
        coverage = coverage_measures(feature, identity.get('page_number') if identity['scope'] == 'page' else None)
    recognition = text_corruption_measures(text) if text is not None else {'status': 'unmeasured_output_text', 'source_fidelity': 'unknown'}
    related_intermediate = (identity.get('intermediate_body_sha256') == identity['body_sha256']
                            and identity.get('intermediate_scope') == identity['scope']
                            and identity.get('intermediate_page_number') == identity.get('page_number'))
    if identity.get('intermediate_kind') == 'independent_ocr':
        if not related_intermediate or identity['scope'] != 'page' or identity['source_format'] != 'pdf':
            raise ValueError('independent OCR requires a reference from the same PDF body and page')
        if text is not None:
            comparison = compare_intermediate(intermediate, text)
            recognition['independent_ocr_comparison'] = comparison
            if comparison['status'] == 'measured':
                recognition['largest_unmatched_ocr_passage_tokens'] = _largest_unmatched_ocr_passage(intermediate, text)
        cleanup = {'status': 'missing_intermediate', 'changes': []}
    elif intermediate is not None and not related_intermediate:
        cleanup = {'status': 'unassessed_intermediate_scope', 'changes': []}
    else:
        cleanup = compare_intermediate(intermediate, text) if text is not None else {'status': 'unmeasured_output_text', 'changes': []}
    intermediate_identity = None if intermediate is None else {
        'sha256': sha256(intermediate.encode()).hexdigest(), 'utf8_bytes': len(intermediate.encode()),
        'kind': identity.get('intermediate_kind'), 'declared_body_sha256': identity.get('intermediate_body_sha256'),
        'declared_scope': identity.get('intermediate_scope'), 'declared_page_number': identity.get('intermediate_page_number'),
        'historical_precleanup_claim': identity.get('intermediate_kind') == 'precleanup',
    }
    role = {'status': 'unmeasured_source_structure', 'role': 'unassessed'}
    if raw_markup is not None:
        if sha256(raw_markup).hexdigest() != identity['body_sha256']:
            raise ValueError('raw markup differs from body identity')
        observed = assess_response(raw_markup, format=identity['source_format'])
        role = {'status': 'measured_source_structure', 'role': observed.role, 'reason': observed.reason,
                'policy_version': observed.policy_version, 'evidence': list(observed.evidence)}
    axes = dict(coverage=coverage, recognition=recognition, cleanup=cleanup, role=role)
    triage = fts_triage(axes)
    signals = ['possible_missing_content'] if 'possible_missing_content' in triage['reasons'] else []
    if coverage.get('under_200_slots', 0):
        signals.append('low_quantity')
    if coverage.get('longest_interior_empty_run', 0):
        signals.append('interior_blank_run')
    if coverage.get('nonocr_under_200_slots', 0) and coverage.get('ocr_slot_count', 0):
        signals.append('mixed_native_ocr_gap')
    if (coverage.get('sparse_repeated_line_char_fraction') or 0) > 0:
        signals.append('repeated_sparse_text')
    if cleanup.get('removed_content_tokens', 0) or cleanup.get('removed_symbol_tokens', 0):
        signals.append('possible_cleanup_loss')
    if any(recognition.get(n, 0) for n in ('replacement_characters', 'nonwhitespace_control_characters', 'private_use_characters')) or recognition.get('longest_latin_single_letter_run', 0) >= 8:
        signals.append('possible_encoding_corruption')
    if role['role'] != 'unassessed':
        signals.append('role_phrase_match')  # Existing adapter code; evidence remains structural, not phrase-only.
    return {'policy_version': POLICY_VERSION, 'identity': identity, 'axes': axes, 'intermediate_identity': intermediate_identity,
            'fts_triage': triage,
            'signals': sorted(signals), 'axis_review_ranks': axis_ranks(axes),
            'calibration': 'development_only_unqualified', 'source_fidelity': 'unknown',
            'no_trigger_means': 'no_measured_trigger_not_source_agreement'}


def assessment_facts(measured, evidence):
    """Translate measurements to existing measurement-only adapter inputs."""
    identity, axes = measured['identity'], measured['axes']
    metrics = {f'{axis}_{name}': value for axis, values in axes.items() for name, value in values.items()
               if not isinstance(value, (dict, list))}
    metrics['selection_state'] = 'not_established'
    return dict(body_sha256=identity['body_sha256'], parser=identity['parser'], parser_version=identity['parser_version'],
                text_sha256=identity['text_sha256'], output_sha256=identity['output_sha256'],
                source_format=identity['source_format'], source_state=identity.get('source_state', 'unknown'), reading_status='completed',
                page_number=identity.get('page_number'), page_count=identity.get('source_page_count'),
                selected=identity.get('selected'), precleanup_available=(True if measured['intermediate_identity'] is not None
                    and identity.get('intermediate_kind') == 'precleanup' else identity.get('precleanup_available')),
                measurements=metrics, missing_measurements=['source_fidelity', 'held_out_calibration'],
                findings=[dict(code=code, basis='measurement', reviewer=None, evidence=[evidence]) for code in measured['signals']])
