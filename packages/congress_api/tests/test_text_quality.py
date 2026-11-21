from hashlib import sha256
from pathlib import Path

import pytest

from congress_api.lake.text_assessment import assess_text
from congress_api.lake.text_quality import (
    FEATURE_VERSION, _largest_unmatched_ocr_passage, assessment_facts, compare_intermediate, measure_quality,
    text_corruption_measures,
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


def _reference_corruption_counts(text):
    """Deliberately direct Unicode/token oracle for the optimized counters."""
    import re
    import unicodedata
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
    return dict(unicode_characters=len(text), alphanumeric_characters=sum(c.isalnum() for c in text),
                replacement_characters=text.count('\ufffd'),
                nonwhitespace_control_characters=sum(unicodedata.category(c) == 'Cc' and not c.isspace() for c in text),
                private_use_characters=sum(unicodedata.category(c) == 'Co' for c in text),
                latin_word_tokens=len(latin), latin_single_letter_tokens=singles,
                latin_single_letter_fraction=singles/len(latin) if latin else None,
                longest_latin_single_letter_run=longest)


@pytest.mark.parametrize('text', [
    'A_ B2 3C abcΔ Δabc A\u0301 é ſ Ａ ᵃ Ⅳ 𝔄 中文',
    'A\tB\nC\rD\fE\vF\u0085G\u00a0H\u2028I\u2029J\u3000K,L M-N O',
    ''.join(chr(n) for n in range(256)) + '\ue000\uf8ff\uf900\U000f0000\U000ffffd\U00100000\U0010fffd\U0010fffe',
    ('A substantial hearing statement with 2026 figures and café.\n' * 5000) + 'a b c d e f g h i j k l',
])
def test_fast_corruption_counters_preserve_unicode_boundaries_and_long_text(text):
    actual = text_corruption_measures(text)
    expected = _reference_corruption_counts(text)
    assert {k: actual[k] for k in expected} == expected


def test_fast_corruption_character_classes_cover_the_runtime_unicode_database():
    # This includes every control, private-use range and unassigned/non-Latin
    # character rather than relying on a few English examples.
    text = ''.join(map(chr, range(0x110000)))
    actual = text_corruption_measures(text)
    expected = _reference_corruption_counts(text)
    assert {k: actual[k] for k in expected} == expected


@pytest.mark.parametrize('text', ['', ' \n\t', '--- ... !!!'])
def test_output_without_search_tokens_needs_review(text):
    measured = measure_quality(identity(text), text=text)
    assert measured['fts_triage']['band'] == 'review_first'
    assert measured['fts_triage']['reasons'] == ['empty_or_no_searchable_tokens']


def test_sparse_multi_page_and_corruption_density_are_coarse_signals():
    from congress_api.lake.text_quality import coverage_measures, fts_triage
    axes = dict(recognition={}, cleanup={}, role={})
    for counts, ocr, reason in [([20]*5, [], 'mostly_near_empty_multi_slot_output'),
                               ([50, 50, 50, 2000, 2000], [4, 5], 'mixed_sparse_native_ocr_slots')]:
        axes['coverage'] = coverage_measures(dict(feature_version=FEATURE_VERSION, pages=5,
            page_nonspace_chars=counts, ocr_page_numbers=ocr, sparse_repeated_line_char_fraction=0.0))
        assert fts_triage(axes)['band'] == 'review_later'
        assert reason in fts_triage(axes)['reasons']
    text = 'A useful body of text. '*1000+'\ufffd'*3
    assert measure_quality(identity(text), text=text)['fts_triage']['reasons'] == ['possible_mechanical_garbling']


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


@pytest.mark.parametrize('kind', ['meeting', 'file'])
def test_house_response_cli_keeps_extraction_status_separate_from_review(kind, tmp_path):
    import json
    from congress_api.cli.text_quality import measure_cases
    raw = Path(__file__).parent / 'fixtures/response_roles' / f'house-{kind}-not-found.html'
    text = 'Error Encountered. The requested '+kind+' was not found.'
    output = tmp_path/'text.txt'
    output.write_text(text)
    ident = identity(text)
    ident.update(body_sha256=sha256(raw.read_bytes()).hexdigest(), parser='html_text', source_format='html')
    case = {**ident, 'case_id': kind, 'output_path': str(output), 'raw_markup_path': str(raw),
            'raw_markup_sha256': ident['body_sha256']}
    cases = tmp_path/'cases.jsonl'
    cases.write_text(json.dumps(case)+'\n')
    measure_cases(cases, tmp_path/'result')
    measured = json.loads((tmp_path/'result/measurements.jsonl').read_text())
    assert measured['policy_version'] == 'ct-text-quality-measures-v3'
    assert measured['axes']['role']['reason'] == f'house_{kind}_not_found'
    assert measured['axes']['role']['policy_version'] == 'ct-response-roles-v2'
    assert measured['fts_triage']['band'] == 'review_first'
    assert measured['fts_triage']['reasons'] == ['obvious_response_body']
    proposal = json.loads((tmp_path/'result/proposals.jsonl').read_text())['proposal']
    assert proposal['facts']['reading_status'] == 'completed'
    assert proposal['facts']['selected'] is None
    assert proposal['qualified'] is False and proposal['dispatch_allowed'] is False


@pytest.mark.parametrize(('before', 'after'), [
    (b'<div id="body">', b'<div id="different" id="body">'),
    (b'<h1>', b'<h1 style="display:none" style="display:block">'),
    (b'[Meeting Not Found]', b'[<q>Meeting Not Found</q>]'),
])
def test_unqualified_house_evidence_does_not_promote_fts_review(before, after):
    raw = (Path(__file__).parent/'fixtures/response_roles/house-meeting-not-found.html').read_bytes()
    raw = raw.replace(before, after)
    text = 'A retained example with searchable text.'
    ident = identity(text)
    ident.update(body_sha256=sha256(raw).hexdigest(), parser='html_text', source_format='html')
    measured = measure_quality(ident, text=text, raw_markup=raw)
    assert measured['axes']['role']['role'] == 'unassessed'
    assert measured['fts_triage']['band'] == 'no_obvious_failure_detected'
    assert 'role_phrase_match' not in measured['signals']


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


@pytest.mark.parametrize('updates', [
    {'intermediate_body_sha256': 'b'*64}, {'intermediate_page_number': 2},
    {'scope': 'reading', 'intermediate_scope': 'reading'}, {'source_format': 'html'},
])
def test_independent_ocr_requires_the_same_pdf_page(updates):
    ident = identity('final')
    ident.update(scope='page', page_number=1, source_page_count=2, intermediate_kind='independent_ocr',
                 intermediate_scope='page', intermediate_page_number=1, intermediate_body_sha256=ident['body_sha256'])
    ident.update(updates)
    with pytest.raises(ValueError, match='same PDF body and page'):
        measure_quality(ident, text='final', intermediate='reference')


@pytest.mark.parametrize(('moved_copies', 'expected_missing'), [(2, 0), (1, 20), (0, 20)])
def test_independent_ocr_counts_each_moved_copy_once_across_deleted_spans(moved_copies, expected_missing):
    passage = ' '.join(['Café!'] * 20)
    first = ' '.join(f'first{i}' for i in range(50))
    second = ' '.join(f'second{i}' for i in range(50))
    reference = ' '.join([passage, first, passage, second])
    # Both deletions compete for the same inserted occurrences, normalized as in the alignment.
    output = ' '.join([first, second, *(['CAFE\u0301!'] * (20 * moved_copies))])
    ident = identity(output)
    ident.update(scope='page', page_number=1, source_page_count=1, intermediate_kind='independent_ocr',
                 intermediate_scope='page', intermediate_page_number=1, intermediate_body_sha256=ident['body_sha256'])
    review = measure_quality(ident, text=output, intermediate=reference)
    recognition = review['axes']['recognition']
    assert recognition['independent_ocr_comparison']['removed_content_tokens'] == 40
    assert recognition['largest_unmatched_ocr_passage_tokens'] == expected_missing
    assert review['signals'] == (['possible_missing_content'] if expected_missing else [])


@pytest.mark.parametrize(('length', 'missing'), [(4, 24), (11, 31), (12, 10)])
def test_partial_ocr_move_requires_twelve_tokens(length, missing):
    phrase = ' '.join(f'word{i}' for i in range(length))
    omitted = ' '.join(['lost'] * 10)
    deleted = f'{omitted} {phrase} {omitted}'
    assert _largest_unmatched_ocr_passage(deleted, f'new {phrase} text') == missing
    assert _largest_unmatched_ocr_passage(deleted, phrase) == missing


@pytest.mark.parametrize(('reference', 'output', 'missing'), [
    ('---', 'new', 0), ('first last', 'FIRST! LAST', 0),
    ('first last', '---', 2), ('first lost words last', 'first last', 2),
])
def test_short_ocr_pages_measure_alphanumeric_gaps(reference, output, missing):
    assert _largest_unmatched_ocr_passage(reference, output) == missing


@pytest.mark.parametrize('extra_words', [True, False])
def test_longer_ocr_move_wins_over_an_eligible_twelve_token_overlap(extra_words):
    words = [f'word{i}' for i in range(18)]
    overlap = ' '.join(words[:12])
    sentence = ' '.join(words)
    lost = f'opening {overlap} conclusion'
    # The omitted opening could take twelve words that belong to the moved sentence.
    retained = ' '.join(f'retained{i}' for i in range(24))
    ref = f'{lost} {retained} {sentence}'
    out = f'{sentence} {retained}'
    if extra_words:
        ref = f'{lost} {retained} old {sentence}'
        out = f'{sentence} new {retained}'
    assert _largest_unmatched_ocr_passage(ref, out) == 14


def test_edited_rows_require_matching_context():
    def fields(label, prefix):
        return ' '.join(f'{label} {prefix if i > 2 else "same"}{i}' for i in range(20))

    # Three unchanged rows give the span matcher a long exact reservation.
    label = 'current year approved amount'
    assert _largest_unmatched_ocr_passage(fields(label, 'old'), fields(label, 'new')) == 1
    # Isolated common words alone do not establish a corresponding block.
    assert _largest_unmatched_ocr_passage(fields('the', 'old'), fields('the', 'new')) == 40


@pytest.mark.parametrize(('ref_gap', 'out_gap', 'missing'), [
    ('old1 old2 same old4', 'new1 new2 same new4', 2),
    ('', 'e', 1),  # Insertion repeats the first word of the next anchor.
    ('', 'new1 new2 new3 new4', 1),
    ('old1 old2 old3 old4', '', 4),
    ('old1 old2 old3 old4 old5', 'new', 18),
    ('old', 'new1 new2 new3 new4 new5', 14),
])
def test_four_word_anchors_need_twelve_matches_with_gaps_of_at_most_four(ref_gap, out_gap, missing):
    # The table and the retained paragraph exchange places on the page.
    tail = ' '.join(f'tail{i}' for i in range(20))
    ref = f'a b c d {ref_gap} e f g h old i j k l {tail}'
    out = f'{tail} a b c d {out_gap} e f g h new i j k l'
    assert _largest_unmatched_ocr_passage(ref, out) == missing


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
