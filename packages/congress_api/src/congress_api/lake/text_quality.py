"""Measure review signals; source fidelity and action policy have other owners.

Native/final differences preserve order, multiplicity and original character
spans. They nominate review, including legitimate cleanup, never a defect verdict.
"""
from collections import Counter, defaultdict, deque
from hashlib import sha256
from itertools import islice

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
    if r.get('largest_unmatched_ocr_passage_tokens', 0) >= 20:
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


def _match_edited_chunks(deleted, inserted, deleted_masks, inserted_masks):
    """Mark aligned words in whole blocks that differ only by isolated substitutions."""
    shared = {word for chunk in deleted for word in chunk}.intersection(
        word for chunk in inserted for word in chunk)

    def pattern(chunk):
        # A field absent from the other side cannot have moved elsewhere.
        key = tuple(word if word in shared else None for word in chunk)
        edits = [i for i, word in enumerate(key) if word is None]
        if (edits and len(key) - len(edits) >= _MIN_INTERIOR_MOVE
                and all(b - a > _MIN_MOVE_ANCHOR for a, b in zip(edits, edits[1:]))):
            return key

    # Earlier reservations must agree at every position before the remaining
    # fields can be paired in order. Count each matching block only once.
    counts = Counter((pattern(chunk), bytes(mask)) for chunk, mask in zip(inserted, inserted_masks))
    for chunk, mask in zip(deleted, deleted_masks):
        key = pattern(chunk)
        pair = key, bytes(mask)
        if key is not None and counts[pair]:
            counts[pair] -= 1
            mask[:] = bytes(word is not None for word in key)


def _largest_unmatched_ocr_passage(changes):
    """Reserve complete moves, then longest spans, and measure the remaining gaps."""
    def chunks(field):
        counts = Counter()
        for change in changes:
            tokens = tuple(token for token, _, _ in _comparison_tokens(change[field])
                           if any(c.isalnum() for c in token))
            if tokens:
                counts[tokens] += 1
        return counts

    before, after = chunks('intermediate_slice'), chunks('output_slice')
    deleted = list((before - after).elements())
    inserted = list((after - before).elements())
    longest = max(map(len, deleted), default=0)
    if not inserted or longest < _MIN_MOVE_ANCHOR:
        return longest

    deleted_masks = [bytearray(len(chunk)) for chunk in deleted]
    inserted_masks = [bytearray(len(chunk)) for chunk in inserted]
    # Only a whole chunk can qualify below 12 tokens, so shorter anchors are
    # necessary only when such a chunk is present.
    width = min(_MIN_INTERIOR_MOVE, *(len(c) for c in deleted + inserted if len(c) >= _MIN_MOVE_ANCHOR))
    buckets = [[] for _ in range(longest + 1)]
    for length, d, a, i, b in _moved_spans(deleted, inserted, width):
        if length >= _MIN_INTERIOR_MOVE or length in (len(deleted[d]), len(inserted[i])):
            buckets[length].append((d, a, i, b))

    for length in range(longest, width - 1, -1):
        for d, a, i, b in buckets[length]:
            # Every reserved interval is at least this long. Any overlap must
            # cover an endpoint; put its unused remainder back at its true length.
            left, right = 0, length
            source, output = deleted_masks[d], inserted_masks[i]
            while left < right and (source[a + left] or output[b + left]):
                left += 1
            while right > left and (source[a + right - 1] or output[b + right - 1]):
                right -= 1
            remaining = right - left
            if remaining == length:
                source[a:a + length] = output[b:b + length] = b'\x01' * length
            elif remaining >= _MIN_INTERIOR_MOVE:
                buckets[remaining].append((d, a + left, i, b + left))

    # A moved table may have only short exact runs between changed row identifiers.
    _match_edited_chunks(deleted, inserted, deleted_masks, inserted_masks)
    return max(len(run) for mask in deleted_masks for run in mask.split(b'\x01'))


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
                recognition['largest_unmatched_ocr_passage_tokens'] = _largest_unmatched_ocr_passage(comparison['changes'])
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
