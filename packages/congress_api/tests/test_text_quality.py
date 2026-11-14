from hashlib import sha256

import pytest

from congress_api.lake.text_assessment import assess_text
from congress_api.lake.text_quality import (
    FEATURE_VERSION, assessment_facts, compare_intermediate, measure_quality, text_corruption_measures,
)


def identity(text, **updates):
    digest = sha256(text.encode()).hexdigest()
    return dict(body_sha256='a'*64, parser='pdf_text', parser_version='retained-v1',
                text_sha256=digest, output_sha256=digest, source_format='pdf', scope='reading',
                page_number=None, source_page_count=None, **updates)


def test_omitted_clause_has_actual_ordered_slice():
    before = 'First clause.\nPreserve grants of $12.50, not $15.20.\nLast clause.'
    after = 'First clause.\nLast clause.'
    result = compare_intermediate(before, after)
    assert result['removed_content_tokens'] > 0
    assert any('$12.50, not $15.20' in c['intermediate_slice'] for c in result['changes'])
    for change in result['changes']:
        start, end = change['intermediate_char_range']
        assert before[start:end] == change['intermediate_slice']


def test_order_multiplicity_numbers_and_signs_are_not_sets():
    result = compare_intermediate('A 12 - 4; A 12 - 4;', 'A 12 + 4;')
    assert result['removed_content_tokens'] >= 3
    assert result['removed_symbol_tokens'] > 0
    assert any('-' in c['intermediate_slice'] or '+' in c['output_slice'] for c in result['changes'])


def test_whitespace_unicode_and_quote_shapes_preserve_tokens():
    result = compare_intermediate('你好 κόσμος ᎣᏏᏲ\n“2019”', '你好  κόσμος\nᎣᏏᏲ "2019"')
    assert result['removed_content_tokens'] == result['removed_symbol_tokens'] == 0
    assert result['ordered_retained_token_fraction'] == 1
    assert text_corruption_measures('Ꭳ Ꮟ Ᏺ 日 本 語')['longest_latin_single_letter_run'] == 0
    equivalent = compare_intermediate('café ₹12', 'cafe\u0301 ₹12')
    assert equivalent['changes'] == []


@pytest.mark.parametrize('native,status', [(None, 'missing_intermediate'), ('\f', 'empty_intermediate_no_cleanup_inference')])
def test_ocr_only_native_cannot_imply_cleanup(native, status):
    text = 'Plausible name 5 | 28/24 and other fluent but unverified text.'
    ident = identity(text, intermediate_body_sha256='a'*64, intermediate_scope='reading', intermediate_page_number=None)
    measured = measure_quality(ident, text=text, intermediate=native)
    assert measured['axes']['cleanup']['status'] == status
    assert 'possible_cleanup_loss' not in measured['signals']
    assert measured['source_fidelity'] == 'unknown'


def test_repeated_text_budget_refuses_before_alignment():
    result = compare_intermediate('a '*1200, 'a '*1200)
    assert result['status'] == 'unassessed_token_budget'
    assert result['changes'] == []


def test_corruption_counts_are_script_aware_and_do_not_certify():
    text = 'a b c d e f g h \ufffd\x00\ue001'
    measured = measure_quality(identity(text), text=text)
    axis = measured['axes']['recognition']
    assert axis['replacement_characters'] == axis['nonwhitespace_control_characters'] == axis['private_use_characters'] == 1
    assert axis['longest_latin_single_letter_run'] == 8
    assert 'possible_encoding_corruption' in measured['signals']
    assert axis['source_fidelity'] == 'unknown_text_only'


def test_short_blank_and_repeated_pages_are_only_measurement_findings():
    text = 'A short real amendment.'
    ident = identity(text)
    feature = {**{k: ident[k] for k in ('body_sha256', 'parser', 'parser_version', 'text_sha256')},
               'feature_version': FEATURE_VERSION, 'pages': 3, 'page_nonspace_chars': [20, 0, 20],
               'ocr_page_numbers': [1], 'sparse_repeated_line_char_fraction': 0.8, 'nonspace_chars': 40}
    measured = measure_quality(ident, text=text, feature=feature)
    assert measured['axes']['coverage']['longest_interior_empty_run'] == 1
    facts = assessment_facts(measured, dict(stage='measurement', path='/retained/measurements.jsonl', sha256='b'*64, locator='line 1'))
    proposal = assess_text(facts)
    assert facts['page_count'] is None
    assert all(f['basis'] == 'measurement' and f['reviewer'] is None for f in facts['findings'])
    assert proposal['action'] == 'manual_review' and proposal['qualified'] is False
    assert proposal['dispatch_allowed'] is False
    bad = {**feature, 'parser_version': 'other'}
    with pytest.raises(ValueError, match='exact reading'):
        measure_quality(ident, text=text, feature=bad)


def test_role_reuses_raw_structure_and_preserves_quoted_prose():
    raw = b'<html><title>Access Denied</title><h1>Access Denied</h1><p>You don\'t have permission to access X https://errors.edgesuite.net/abc</p></html>'
    text = 'Access Denied'
    ident = identity(text)
    ident.update(body_sha256=sha256(raw).hexdigest(), parser='html_text', source_format='html')
    measured = measure_quality(ident, text=text, raw_markup=raw)
    assert measured['axes']['role']['reason'] == 'edge_access_denied'
    assert measured['signals'] == ['role_phrase_match']
    article = b'<html><title>Hearing on network access</title><h1>Evidence</h1><p>The phrase Access Denied appeared in the report.</p></html>'
    ident['body_sha256'] = sha256(article).hexdigest()
    assert measure_quality(ident, text=text, raw_markup=article)['axes']['role']['role'] == 'unassessed'


def test_output_hash_and_page_scope_refuse_invented_identity():
    with pytest.raises(ValueError, match='output text hash'):
        measure_quality(identity('one'), text='two')
    ident = identity('one')
    ident.update(scope='page', page_number=1)
    with pytest.raises(ValueError, match='independently known'):
        measure_quality(ident, text='one')


def test_page_measurement_does_not_inherit_another_pages_blank_or_repetition():
    text = 'A substantial selected page.'
    ident = identity(text)
    ident.update(scope='page', page_number=1, source_page_count=3)
    feature = {**{k: ident[k] for k in ('body_sha256', 'parser', 'parser_version', 'text_sha256')},
               'feature_version': FEATURE_VERSION, 'pages': 3, 'page_nonspace_chars': [500, 0, 600],
               'ocr_page_numbers': [3], 'sparse_repeated_line_char_fraction': 0.9, 'nonspace_chars': 1100}
    measured = measure_quality(ident, text=text, feature=feature)
    assert measured['signals'] == []
    assert measured['axes']['coverage']['nonspace_characters'] == 500
    assert measured['axes']['coverage']['sparse_repeated_line_char_fraction'] is None
    ident['source_page_count'] = 4
    assert measure_quality(ident, text=text, feature=feature)['axes']['coverage']['status'] == 'unassessed_page_slot_mapping_count_differs'


def test_unstated_availability_and_unbound_intermediate_remain_unknown():
    text = 'final'
    measured = measure_quality(identity(text), text=text, intermediate='native final')
    assert measured['axes']['cleanup']['status'] == 'unassessed_intermediate_scope'
    facts = assessment_facts(measured, dict(stage='measurement', path='/measure.json', sha256='b'*64, locator='line 1'))
    assert facts['source_state'] == 'unknown' and facts['precleanup_available'] is None
    assert facts['selected'] is None
    assert assess_text(facts)['facts']['selected'] is None
    assert measured['intermediate_identity']['sha256'] == sha256(b'native final').hexdigest()


def test_cli_measure_bounds_hash_and_actual_proposal(tmp_path):
    import json
    from congress_api.cli.text_quality import measure_cases
    text = 'A small useful record.'
    output = tmp_path/'text.txt'
    output.write_text(text)
    case = {**identity(text), 'case_id': 'short', 'output_path': str(output)}
    source = tmp_path/'cases.jsonl'
    source.write_text(json.dumps(case)+'\n')
    result = measure_cases(source, tmp_path/'result')
    assert result['cases'] == 1
    measured = json.loads((tmp_path/'result/measurements.jsonl').read_text())
    assert measured['fts_triage']['band'] == 'no_obvious_failure_detected'
    proposal = json.loads((tmp_path/'result/proposals.jsonl').read_text())['proposal']
    assert proposal['facts']['selected'] is None and proposal['qualified'] is False
    source.write_text((json.dumps(case)+'\n')*2)
    with pytest.raises(ValueError, match='case limit exceeded'):
        measure_cases(source, tmp_path/'limited', limit=1)
    case['output_sha256'] = '0'*64
    source.write_text(json.dumps(case)+'\n')
    with pytest.raises(ValueError, match='artifact hash differs'):
        measure_cases(source, tmp_path/'bad-hash')


def test_cli_rank_clean_first_part_then_anomaly(tmp_path):
    import json
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.cli.text_quality import rank_features
    parts = []
    for name, counts in [('clean', [500, 600, 700]), ('gap', [500, 0, 0, 0, 600])]:
        row = {**{k: v for k, v in identity(name).items() if k in {'body_sha256', 'parser', 'parser_version', 'text_sha256'}},
               'feature_version': FEATURE_VERSION, 'pages': len(counts), 'page_nonspace_chars': counts,
               'ocr_page_numbers': [], 'sparse_repeated_line_char_fraction': 0.0, 'nonspace_chars': sum(counts)}
        row['body_sha256'] = sha256(name.encode()).hexdigest()
        path = tmp_path/(name+'.parquet')
        pq.write_table(pa.Table.from_pylist([row]), path)
        parts.append(dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest()))
    generation = tmp_path/'generation.json'
    generation.write_text(json.dumps(dict(baseline_parts=parts, delta_parts=[], combined_rows=2, combined_pdf_slots=8)))
    summary = rank_features(generation, tmp_path/'rank')
    assert summary['fts_band_counts'] == {'no_obvious_failure_detected': 1, 'review_first': 1}
    ranked = pq.read_table(tmp_path/'rank/coverage-ranked.parquet').to_pylist()
    assert ranked[0]['fts_reasons'] == 'substantial_interior_blank_run'
    assert ranked[1]['signals'] == ''
