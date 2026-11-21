"""Measure review signals; source fidelity and action policy have other owners.

Native/final differences preserve order, multiplicity and original character
spans. They nominate review, including legitimate cleanup, never a defect verdict.
"""
from collections import defaultdict, deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from itertools import chain, pairwise

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


def _anchor_pairs(ref, out, width):
    """Center bounded probes on the corresponding occurrence of a repeated phrase."""
    positions = defaultdict(list)
    for b in range(len(out) - width + 1):
        positions[out[b:b + width]].append(b)
    occurrences = defaultdict(int)
    for a in range(len(ref) - width + 1):
        phrase = ref[a:a + width]
        starts = positions.get(phrase, ())
        if len(starts) > _MAX_ANCHOR_PROBES:
            first = max(0, occurrences[phrase] - _MAX_ANCHOR_PROBES // 2)
            first = min(first, len(starts) - _MAX_ANCHOR_PROBES)
            starts = starts[first:first + _MAX_ANCHOR_PROBES]
            occurrences[phrase] += 1
        for b in starts:
            yield a, b


def _exact_spans(ref, out):
    # A rare twelve-word phrase can locate an exact span even when its
    # four-word anchors are crowded. Extend once per run on each diagonal.
    ends = {}
    for a, b in _anchor_pairs(ref, out, _MIN_INTERIOR_MOVE):
        delta = b - a
        end = a + _MIN_INTERIOR_MOVE
        if end <= ends.get(delta, 0):
            continue
        while a and b and ref[a - 1] == out[b - 1]:
            a -= 1
            b -= 1
        while end < len(ref) and end + delta < len(out) and ref[end] == out[end + delta]:
            end += 1
        ends[delta] = end
        yield end - a, [(a, b, end - a)]


_MAX_EDIT_GAP = 4


@dataclass(slots=True)
class _Anchor:
    a: int
    b: int
    matched: int = _MIN_MOVE_ANCHOR
    following: '_Anchor | None' = None
    head: bool = True


def _edited_chains(ref, out):
    """Score each four-word anchor once, from the end of the page backwards."""
    width = _MIN_MOVE_ANCHOR
    rows = [{} for _ in range(len(ref) + width + _MAX_EDIT_GAP + 1)]
    for a, b in _anchor_pairs(ref, out, width):
        rows[a][b] = _Anchor(a, b)

    for a in reversed(range(len(ref))):
        for b, anchor in rows[a].items():
            # Overlapping anchors on one diagonal add one exact word. A jump
            # to a disjoint anchor can also preserve aligned words in the gap.
            extension = rows[a + 1].get(b + 1)
            if extension:
                anchor.matched = 1 + extension.matched
                anchor.following = extension
            for p in range(a + width, a + width + _MAX_EDIT_GAP + 1):
                if not rows[p]:
                    continue
                for q in range(b + width, b + width + _MAX_EDIT_GAP + 1):
                    following = rows[p].get(q)
                    if following is None:
                        continue
                    score = width + following.matched
                    for i, j in zip(range(a + width, p), range(b + width, q)):
                        score += ref[i] == out[j]
                    if score > anchor.matched:
                        anchor.matched = score
                        anchor.following = following
            if anchor.following:
                anchor.following.head = False

    # A suffix shares all its matches with its longer chain. If a reservation
    # cuts the chain, the free pieces re-enter the ranking at their own size.
    for row in rows:
        for anchor in row.values():
            if anchor.head and anchor.matched >= _MIN_INTERIOR_MOVE:
                yield anchor.matched, _chain_blocks(anchor, ref, out)


def _chain_blocks(anchor, ref, out):
    blocks = []
    while anchor:
        a, b = anchor.a, anchor.b
        following = anchor.following
        while following and following.a == anchor.a + 1:
            anchor = following
            following = anchor.following
        end = anchor.a + _MIN_MOVE_ANCHOR
        blocks.append((a, b, end - a))
        if following:
            for i, j in zip(range(end, following.a), range(anchor.b + _MIN_MOVE_ANCHOR, following.b)):
                if ref[i] == out[j]:
                    blocks.append((i, j, 1))
        anchor = following
    return blocks


def _unused_pieces(blocks, ref_mask, out_mask):
    """Split at occupied words on either side, including words in edit gaps."""
    piece = []
    end_a, end_b = blocks[0][:2]
    for a, b, size in blocks:
        if piece and (ref_mask.find(1, end_a, a) >= 0 or out_mask.find(1, end_b, b) >= 0):
            yield piece
            piece = []
        end_a, end_b = a + size, b + size
        if ref_mask.find(1, a, end_a) < 0 and out_mask.find(1, b, end_b) < 0:
            piece.append((a, b, size))
            continue
        start = 0
        for i in range(size):
            if ref_mask[a + i] or out_mask[b + i]:
                if i > start:
                    piece.append((a + start, b + start, i - start))
                if piece:
                    yield piece
                    piece = []
                start = i + 1
        if start < size:
            piece.append((a + start, b + start, size - start))
    if piece:
        yield piece


def _reserve_spans(ref, out, ref_mask, out_mask):
    """Reserve the most matched words first and rank clipped pieces again."""
    buckets = [[] for _ in range(min(len(ref), len(out)) + 1)]
    for matched, blocks in chain(_exact_spans(ref, out), _edited_chains(ref, out)):
        buckets[matched].append(blocks)
    reserved = []
    for size in range(len(buckets) - 1, _MIN_INTERIOR_MOVE - 1, -1):
        for blocks in buckets[size]:
            for piece in _unused_pieces(blocks, ref_mask, out_mask):
                remaining = sum(n for _, _, n in piece)
                if remaining == size:
                    for a, b, n in piece:
                        ref_mask[a:a + n] = out_mask[b:b + n] = b'\x01' * n
                    reserved.extend(piece)
                elif remaining >= _MIN_INTERIOR_MOVE:
                    buckets[remaining].append(piece)
    return reserved


def _page_words(text):
    words, lines = [], []
    for line in text.split('\n'):
        start = len(words)
        words.extend(token for token, _, _ in _comparison_tokens(line) if any(c.isalnum() for c in token))
        if len(words) > start:
            lines.append((tuple(words[start:]), start))
    return tuple(words), lines


def _line_parts(row, starts, widths):
    """Find a complete division of a joined OCR row into lines on the other page."""
    if row in starts:
        return [row] if len(row) >= _MIN_MOVE_ANCHOR else []
    # Several printed lines can have the same opening. Keep each reachable
    # boundary so a longer prefix cannot hide the only complete division.
    previous = {0: 0}
    for i, word in enumerate(row):
        if i in previous:
            for width in widths.get(word, ()):
                end = i + width
                if end <= len(row) and end not in previous and row[i:end] in starts:
                    previous[end] = i
    if len(row) not in previous:
        return []
    parts = []
    end = len(row)
    while end:
        i = previous[end]
        parts.append(row[i:end])
        end = i
    return reversed(parts)


def _reserve_lines(lines, rows, line_mask, row_mask):
    starts = defaultdict(deque)
    widths = defaultdict(set)
    for line, a in lines:
        widths[line[0]].add(len(line))
        available = starts[line]
        if line_mask.find(1, a, a + len(line)) < 0:
            available.append(a)
    for row, b in rows:
        for line in _line_parts(row, starts, widths):
            size = len(line)
            if starts[line] and row_mask.find(1, b, b + size) < 0:
                a = starts[line].popleft()
                line_mask[a:a + size] = row_mask[b:b + size] = b'\x01' * size
                yield a, b, size
            b += size


_MAX_SLOT_TOKENS = 128


def _slot_matches(ref, out):
    def small_edit(opcode):
        _, a, end_a, b, end_b = opcode
        return end_a - a <= 3 and end_b - b <= 3

    ops = SequenceMatcher(None, ref, out, autojunk=False).get_opcodes()
    for i, (tag, a, end_a, b, _) in enumerate(ops):
        if tag != 'equal':
            continue
        length = end_a - a
        at_edge = i == 0 or i == len(ops) - 1
        if (length >= _MIN_INTERIOR_MOVE or (at_edge and length >= 2)
                or (not at_edge and small_edit(ops[i - 1]) and small_edit(ops[i + 1]))):
            yield a, b, length


def _reserve_inorder_slots(ref, out, ref_mask, out_mask, reserved):
    """Align short free gaps between blocks that are neighbors on both pages."""
    def align(a, end_a, b, end_b, *, crossed_edge=False):
        ref_size, out_size = end_a - a, end_b - b
        if not (2 <= ref_size <= _MAX_SLOT_TOKENS and 2 <= out_size <= _MAX_SLOT_TOKENS):
            return
        if out_mask.find(1, b, end_b) >= 0:
            return
        runs = list(_slot_matches(ref[a:end_a], out[b:end_b]))
        # Without anchors on either page, keep the minimum evidence for an
        # interior match. Isolated common words supply no such evidence.
        if crossed_edge or (not reserved and sum(n for _, _, n in runs if n >= 2) < _MIN_INTERIOR_MOVE):
            # Headings/footers must touch the same page boundary and account
            # for the entire shorter side before they can establish a match.
            runs = [(p, q, n) for p, q, n in runs
                    if p == q == 0 or (p + n == ref_size and q + n == out_size)]
            if sum(n for _, _, n in runs) != min(ref_size, out_size):
                return
            if not any((a + p == b + q == 0) or (a + p + n == len(ref) and b + q + n == len(out))
                       for p, q, n in runs):
                return
        for p, q, n in runs:
            ref_mask[a + p:a + p + n] = out_mask[b + q:b + q + n] = b'\x01' * n

    if not reserved:
        align(0, len(ref), 0, len(out))
        return
    reserved.sort()
    first_a, first_b, _ = reserved[0]
    first_out = out_mask.find(1)
    last_a, last_b, length = reserved[-1]
    last_out = out_mask.rfind(1) + 1
    # Page boundaries pair with the first/last block only when that block is
    # also first/last in the output. A move leaves only the two outer edges.
    align(0, first_a, 0, first_out, crossed_edge=first_b != first_out)
    for (a, b, n), (next_a, next_b, _) in pairwise(reserved):
        align(a + n, next_a, b + n, next_b)
    align(last_a + length, len(ref), last_out, len(out), crossed_edge=last_b + length != last_out)


def _largest_unmatched_ocr_passage(intermediate, text):
    """Measure the longest unaccounted stretch of the independent OCR page."""
    ref, ref_lines = _page_words(intermediate)
    out, out_lines = _page_words(text)
    if not ref or ref == out:
        return 0
    if not out:
        return len(ref)
    ref_mask, out_mask = bytearray(len(ref)), bytearray(len(out))
    reserved = _reserve_spans(ref, out, ref_mask, out_mask)
    reserved.extend(_reserve_lines(ref_lines, out_lines, ref_mask, out_mask))
    reserved.extend((a, b, n) for b, a, n in _reserve_lines(out_lines, ref_lines, out_mask, ref_mask))
    if not reserved and len(ref) < _MIN_MISSING_PASSAGE:
        for a, b, n in SequenceMatcher(None, ref, out, autojunk=False).get_matching_blocks():
            ref_mask[a:a + n] = out_mask[b:b + n] = b'\x01' * n
    else:
        _reserve_inorder_slots(ref, out, ref_mask, out_mask, reserved)
    limit = min(len(ref), len(out))
    for edge in (range(limit), range(-1, -limit - 1, -1)):
        for i in edge:
            if ref_mask[i] or out_mask[i] or ref[i] != out[i]:
                break
            ref_mask[i] = out_mask[i] = 1
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
