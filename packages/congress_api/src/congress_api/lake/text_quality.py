"""Measure review signals; source fidelity and action policy have other owners.

Native/final differences preserve order, multiplicity and original character
spans. They nominate review, including legitimate cleanup, never a defect verdict.
"""
from difflib import SequenceMatcher
from hashlib import sha256
import re
import unicodedata

from congress_api.parsers.response_roles import assess_response

POLICY_VERSION = 'ct-text-quality-measures-v1'
FEATURE_VERSION = 'pdf-page-features-20261113-1'
MAX_TEXT_BYTES = 256 << 10
MAX_COMPARE_CHARS = 64 << 10
MAX_COMPARE_TOKENS = 2048
MAX_TOKEN_PRODUCT = 1_000_000
_QUOTE_SHAPES = str.maketrans({'“': '"', '”': '"', '‘': "'", '’': "'"})
_KEY = ('body_sha256', 'parser', 'parser_version', 'text_sha256')


def _tokens(text):
    spans = []
    start = 0
    def word(c):
        return c.isalnum() or c == '_' or unicodedata.category(c).startswith('M')
    while start < len(text):
        if text[start].isspace():
            start += 1
            continue
        end = start+1
        if word(text[start]):
            while end < len(text) and word(text[end]):
                end += 1
        spans.append((unicodedata.normalize('NFC', text[start:end]).translate(_QUOTE_SHAPES).casefold(), start, end))
        start = end
    return spans


def compare_intermediate(before, after):
    """Bounded ordered alignment; ranges index original Unicode characters."""
    if before is None:
        return {'status': 'missing_intermediate', 'changes': []}
    if not before.strip():
        return {'status': 'empty_intermediate_no_cleanup_inference', 'changes': []}
    if max(len(before), len(after)) > MAX_COMPARE_CHARS:
        return {'status': 'unassessed_character_budget', 'changes': []}
    left, right = _tokens(before), _tokens(after)
    if max(len(left), len(right)) > MAX_COMPARE_TOKENS or len(left) * len(right) > MAX_TOKEN_PRODUCT:
        return {'status': 'unassessed_token_budget', 'changes': [],
                'intermediate_tokens': len(left), 'output_tokens': len(right)}
    removed_content = removed_symbols = inserted = matched = 0
    changes = []
    for operation, a, b, c, d in SequenceMatcher(
            None, [t[0] for t in left], [t[0] for t in right], autojunk=False).get_opcodes():
        if operation == 'equal':
            matched += b-a
            continue
        start = left[a][1] if a < len(left) else len(before)
        end = left[b-1][2] if b > a else start
        out_start = right[c][1] if c < len(right) else len(after)
        out_end = right[d-1][2] if d > c else out_start
        content = sum(any(ch.isalnum() for ch in t[0]) for t in left[a:b])
        removed_content += content
        removed_symbols += b-a-content
        inserted += d-c
        changes.append({'operation': operation, 'intermediate_char_range': [start, end],
                        'output_char_range': [out_start, out_end],
                        'intermediate_slice': before[start:end], 'output_slice': after[out_start:out_end],
                        'removed_content_tokens': content, 'removed_symbol_tokens': b-a-content})
    return {'status': 'measured', 'intermediate_tokens': len(left), 'output_tokens': len(right),
            'ordered_retained_token_fraction': matched/len(left) if left else None,
            'removed_content_tokens': removed_content, 'removed_symbol_tokens': removed_symbols,
            'inserted_tokens': inserted, 'intermediate_nonspace_chars': sum(not c.isspace() for c in before),
            'output_nonspace_chars': sum(not c.isspace() for c in after), 'changes': changes}


def text_corruption_measures(text):
    """Script-aware mechanical anomalies; plausible wrong words/values can pass."""
    words = list(re.finditer(r'\w+', text))
    latin = [m for m in words if m.group().isalpha() and all(
        unicodedata.name(c, '').startswith('LATIN ') for c in m.group())]
    singles = sum(len(m.group()) == 1 for m in latin)
    longest = run = 0
    previous_end = None
    for match in words:
        word = match.group()
        single = len(word) == 1 and word.isalpha() and unicodedata.name(word, '').startswith('LATIN ')
        run = (run+1 if previous_end is not None and text[previous_end:match.start()].isspace() else 1) if single else 0
        longest = max(longest, run)
        previous_end = match.end()
    return {'status': 'measured', 'unicode_characters': len(text),
            'replacement_characters': text.count('\ufffd'),
            'nonwhitespace_control_characters': sum(unicodedata.category(c) == 'Cc' and not c.isspace() for c in text),
            'private_use_characters': sum(unicodedata.category(c) == 'Co' for c in text),
            'latin_word_tokens': len(latin), 'latin_single_letter_tokens': singles,
            'latin_single_letter_fraction': singles/len(latin) if latin else None,
            'longest_latin_single_letter_run': longest,
            'source_fidelity': 'unknown_text_only'}


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
    if slots > 1 and c.get('nonspace_characters') == 0:
        reasons.append('empty_multi_slot_output')
    if run >= 3 and (run/max(slots, 1) >= 0.1 or run >= 20):
        reasons.append('substantial_interior_blank_run')
    bad_chars = sum(r.get(n, 0) for n in ('replacement_characters', 'nonwhitespace_control_characters', 'private_use_characters'))
    if bad_chars >= 3 or r.get('longest_latin_single_letter_run', 0) >= 12:
        reasons.append('severe_mechanical_garbling')
    elif bad_chars or r.get('longest_latin_single_letter_run', 0) >= 8:
        later.append('possible_mechanical_garbling')
    if (slots >= 3 and (c.get('sparse_repeated_line_char_fraction') or 0) >= 0.8
            and c.get('sparse_under_1000_slots', 0)/slots >= 0.8
            and c.get('nonspace_characters', 0)/slots < 200):
        reasons.append('sparse_output_dominated_by_repeated_furniture')
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
    if intermediate is not None and not related_intermediate:
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
    signals = []
    if coverage.get('under_200_slots', 0):
        signals.append('low_quantity')
    if coverage.get('longest_interior_empty_run', 0):
        signals.append('interior_blank_run')
    if coverage.get('nonocr_empty_slots', 0) and coverage.get('ocr_slot_count', 0):
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
            'fts_triage': fts_triage(axes),
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
