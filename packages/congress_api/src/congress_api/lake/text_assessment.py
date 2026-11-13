"""Recommend review/repair from retained facts; never read, select or dispatch.

The caller owns measurements and direct source review. Artifact references bind
their assertions to an exact input/output; this module does not verify artifact
contents or turn a declared review into independent source qualification.
"""
from hashlib import sha256
import json
import math
import re

POLICY_VERSION = 'ct-text-assessment-proposal-v1'
MAX_RECORD_BYTES = 1 << 20
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_REVIEWED = {
    'cleanup_loss', 'native_omission', 'native_text_corruption', 'recognition_corruption',
    'wrong_source', 'source_error', 'source_wait', 'source_feed', 'source_container',
    'source_metadata', 'source_unresolved', 'valid_empty', 'source_match',
    'native_reread_supported', 'source_requires_recognition',
}
_RUNTIME = {'parser_refused', 'geometry_refused', 'offsets_invalid', 'source_unavailable'}
_SIGNALS = {
    'low_quantity', 'repeated_sparse_text', 'interior_blank_run', 'mixed_native_ocr_gap',
    'possible_missing_content', 'possible_cleanup_loss', 'possible_encoding_corruption',
    'role_phrase_match', 'markup_policy_changed',
}
_LOSS = {'cleanup_loss', 'native_omission', 'native_text_corruption', 'recognition_corruption', 'wrong_source'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _hash(value, label, *, nullable=False):
    _require((nullable and value is None) or isinstance(value, str) and _HASH.fullmatch(value),
             f'{label} must be an exact lowercase SHA-256')


def _label(value, name):
    _require(isinstance(value, str) and 0 < len(value) <= 512, f'{name} must be a nonempty bounded string')


def _validate(record):
    _require(isinstance(record, dict), 'assessment facts must be an object')
    fields = {
        'body_sha256', 'parser', 'parser_version', 'text_sha256', 'output_sha256',
        'source_format', 'source_state', 'reading_status', 'page_number', 'page_count',
        'selected', 'precleanup_available', 'measurements', 'missing_measurements', 'findings',
    }
    _require(record.keys() == fields, f'assessment fields differ: {sorted(record.keys() ^ fields)}')
    _hash(record['body_sha256'], 'body_sha256')
    _hash(record['text_sha256'], 'text_sha256', nullable=True)
    _hash(record['output_sha256'], 'output_sha256', nullable=True)
    for key in ('parser', 'parser_version'):
        _label(record[key], key)
    _require(record['source_format'] in {'pdf', 'html', 'xml', 'warc', 'other'}, 'unknown source_format')
    _require(record['source_state'] in {'retained', 'missing', 'damaged', 'unknown'}, 'unknown source_state')
    _require(record['reading_status'] in {'completed', 'error', 'unreadable', 'pending', 'missing'},
             'unknown reading_status')
    _require(type(record['selected']) is bool, 'selected must be boolean')
    _require(record['precleanup_available'] is None or type(record['precleanup_available']) is bool,
             'precleanup_available must be boolean or unknown')
    for key in ('page_number', 'page_count'):
        value = record[key]
        minimum = 1 if key == 'page_number' else 0
        _require(value is None or type(value) is int and value >= minimum,
                 f'{key} must be an integer of at least {minimum} or unknown')
    page, count = record['page_number'], record['page_count']
    _require(page is None or record['source_format'] == 'pdf' and count is not None and page <= count,
             'a reviewed page requires a PDF and a known containing page count')
    _require(record['reading_status'] != 'completed' or record['output_sha256'] is not None,
             'a completed result requires output identity')
    _require(record['text_sha256'] is None or record['output_sha256'] is not None,
             'text identity requires output identity')
    metrics = record['measurements']
    _require(isinstance(metrics, dict) and len(metrics) <= 64, 'measurements must be a bounded object')
    for key, value in metrics.items():
        _label(key, 'measurement name')
        _require(value is None or type(value) in (bool, int, float) or isinstance(value, str) and len(value) <= 512,
                 'measurements must be bounded scalar values')
        _require(type(value) is not float or math.isfinite(value), 'measurements must be finite')
    missing = record['missing_measurements']
    _require(isinstance(missing, list) and len(missing) <= 64, 'missing_measurements must be a bounded list')
    for name in missing:
        _label(name, 'missing measurement')
        _require(name not in metrics or metrics[name] is None, 'a measurement cannot be both known and missing')
    findings = record['findings']
    _require(isinstance(findings, list) and len(findings) <= 32, 'findings must be a bounded list')
    codes = set()
    for finding in findings:
        _require(isinstance(finding, dict) and finding.keys() == {'code', 'basis', 'reviewer', 'evidence'},
                 'each finding needs code, basis, reviewer and evidence')
        code, basis = finding['code'], finding['basis']
        _require(isinstance(code, str) and code in _REVIEWED | _RUNTIME | _SIGNALS, 'unknown finding code')
        _require(code not in codes, 'duplicate finding code')
        codes.add(code)
        expected = 'source_review' if code in _REVIEWED else 'runtime' if code in _RUNTIME else 'measurement'
        _require(basis == expected, f'{code} requires {expected} evidence')
        evidence = finding['evidence']
        _require(isinstance(evidence, list) and 0 < len(evidence) <= 16, 'each finding needs bounded evidence')
        for artifact in evidence:
            _require(isinstance(artifact, dict) and artifact.keys() == {'stage', 'path', 'sha256', 'locator'},
                     'artifact reference fields differ')
            _require(artifact['stage'] in {'raw', 'intermediate', 'output', 'measurement', 'runtime'},
                     'unknown evidence stage')
            _hash(artifact['sha256'], 'evidence sha256')
            _label(artifact['path'], 'evidence path')
            _label(artifact['locator'], 'evidence locator')
        if basis == 'source_review':
            _label(finding['reviewer'], 'source reviewer')
            _require(record['output_sha256'] is not None, 'source review requires output identity')
            _require(any(a['stage'] == 'raw' and a['sha256'] == record['body_sha256'] for a in evidence),
                     'source review does not bind the raw body')
            _require(any(a['stage'] == 'output' and a['sha256'] == record['output_sha256'] for a in evidence),
                     'source review does not bind the assessed output')
            _require(any(a['stage'] == 'intermediate' for a in evidence), 'source review needs intermediary evidence')
        else:
            _require(finding['reviewer'] is None, 'measurement/runtime observations do not declare a source reviewer')
    return codes


def assess_text(record):
    """Return a deterministic proposal from explicit, identity-bound facts.

    Priority is ordinal: 3 reviewed loss/wrong role, 2 runtime/source obstacle,
    1 measurement signal, 0 no trigger. It is neither a calibrated probability
    nor a quality score. Unknown/no-trigger records remain unqualified.
    """
    codes = _validate(record)
    encoded = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    _require(len(encoded) <= MAX_RECORD_BYTES, 'assessment facts exceed the record bound')
    # Isolate the returned evidence from later caller mutations.
    facts = json.loads(encoded)
    reviewed = codes & _REVIEWED
    priority = 3 if reviewed & (_LOSS | {'source_error', 'wrong_source'}) else 2 if (
        codes & _RUNTIME or facts['reading_status'] != 'completed' or facts['source_state'] != 'retained'
    ) else 1 if codes & _SIGNALS else 0
    reasons, prerequisites = sorted(codes), []
    action = 'manual_review'
    if reviewed & {'valid_empty', 'source_match'} and reviewed & (_LOSS | {'source_error', 'source_wait', 'source_unresolved'}):
        reasons.append('conflicting_source_findings')
    elif {'native_reread_supported', 'source_requires_recognition'} <= reviewed:
        reasons.append('conflicting_extraction_stage_findings')
    elif 'cleanup_loss' in reviewed and reviewed & {'native_omission', 'native_text_corruption', 'recognition_corruption'}:
        reasons.append('multiple_loss_stages_require_an_ordered_repair')
    elif 'source_unresolved' in reviewed:
        action = 'refetch_deferred'
        prerequisites.append('user_resumes_publisher_refetch')
    elif reviewed & {'source_error', 'source_wait', 'wrong_source'}:
        reasons.append('reconcile_retained_capture_and_selection_history')
    elif reviewed & {'source_feed', 'source_container', 'source_metadata'}:
        reasons.append('use_qualified_structured_reader_not_prose_or_ocr')
    elif facts['source_state'] != 'retained':
        reasons.append('source_state_requires_reconciliation')
    elif 'offsets_invalid' in codes:
        reasons.append('repair_page_identity_before_page_recommendations')
    elif 'cleanup_loss' in reviewed:
        if facts['precleanup_available'] is True:
            action = 'renormalize'
            prerequisites.append('qualify_retained_intermediate_identity_and_coverage')
        elif facts['source_format'] == 'pdf' and 'native_reread_supported' in reviewed:
            action = 'native_reread'
        elif facts['source_format'] in {'html', 'xml'}:
            action = 'reparse'
        else:
            reasons.append('locate_precleanup_text_or_establish_native_reread_capability')
    elif reviewed & {'native_omission', 'native_text_corruption', 'recognition_corruption'}:
        if facts['source_format'] == 'pdf' and 'native_reread_supported' in reviewed:
            action = 'native_reread'
        elif facts['source_format'] == 'pdf' and facts['page_number'] is not None and 'source_requires_recognition' in reviewed:
            action = 'selective_ocr'
            prerequisites.extend(['user_resumes_ocr', 'qualify_exact_page_policy_backend_and_cost'])
        else:
            reasons.append('identify_exact_affected_pages_and_justified_extraction_stage')
    elif codes & {'parser_refused', 'markup_policy_changed', 'possible_encoding_corruption'} and facts['source_format'] in {'html', 'xml'}:
        action = 'reparse'
    elif codes & _RUNTIME or facts['reading_status'] != 'completed':
        reasons.append('resolve_runtime_or_missing_result_before_quality_acceptance')
    elif reviewed & {'valid_empty', 'source_match'}:
        action = 'keep'
        reasons.append('preserve_only_the_explicitly_reviewed_scope')
    elif codes & _SIGNALS:
        reasons.append('signal_requires_direct_source_review')
    else:
        action = 'keep'
        reasons.append('no_trigger_preserve_existing_reading_but_quality_unassessed')
    if action in {'reparse', 'renormalize', 'native_reread'}:
        prerequisites.extend(['qualified_candidate_reading_policy', 'independent_source_to_output_review'])
    if action not in {'keep', 'manual_review', 'refetch_deferred'}:
        prerequisites.append('select_candidate_separately_after_qualification')
    missing = set(facts['missing_measurements'])
    if not reviewed:
        missing.add('direct_source_review')
    if facts['source_state'] == 'unknown':
        missing.add('source_state')
    if facts['output_sha256'] is None:
        missing.add('output_identity')
    if facts['page_count'] is None and facts['source_format'] == 'pdf':
        missing.add('source_page_count')
    return {
        'assessment_id': sha256(POLICY_VERSION.encode() + b'\0' + encoded).hexdigest(),
        'policy_version': POLICY_VERSION,
        'facts': facts,
        'action': action,
        'reasons': reasons,
        'priority_score': priority,
        'priority_scale': 'ordinal_0_to_3_higher_first_not_probability',
        'confidence_basis': 'direct_source_review' if reviewed else 'runtime_evidence' if codes & _RUNTIME else
                            'measurement_signal' if codes & _SIGNALS else 'unassessed',
        'calibration_status': 'not_calibrated',
        'missing_evidence': sorted(missing),
        'prerequisites': prerequisites,
        'qualified': False,
        'dispatch_allowed': False,
        'ocr_paused': True,
        'publisher_refetch': 'deferred',
    }
