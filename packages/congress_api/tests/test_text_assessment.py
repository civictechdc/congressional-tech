"""Proposal routing preserves identity, uncertainty and the paused work boundary."""
from copy import deepcopy
import json

import pytest

from congress_api.lake.text_assessment import MAX_RECORD_BYTES, assess_text


def facts(*codes, page=1, precleanup=True):
    row = dict(
        body_sha256='a' * 64, parser='pdf_text', parser_version='reviewed-pdf-policy',
        text_sha256='b' * 64, output_sha256='b' * 64, source_format='pdf',
        source_state='retained', reading_status='completed', page_number=page, page_count=4,
        selected=True, precleanup_available=precleanup,
        measurements={'nonspace_characters': 20}, missing_measurements=['source_geometry'], findings=[],
    )
    for code in codes:
        basis = 'measurement' if code in {'low_quantity', 'markup_policy_changed'} else 'runtime' if code in {
            'offsets_invalid', 'parser_refused'} else 'source_review'
        evidence = [dict(stage=stage, path=f'/not-opened/{stage}', sha256=digest, locator='PDF page 1')
                    for stage, digest in [('raw', 'a' * 64), ('intermediate', 'c' * 64), ('output', 'b' * 64)]]
        row['findings'].append(dict(code=code, basis=basis, reviewer='independent-reader' if basis == 'source_review'
                                    else None, evidence=evidence))
    return row


def test_cleanup_uses_retained_intermediate_and_never_ocr():
    for retained, action in [(True, 'renormalize'), (False, 'manual_review'), (None, 'manual_review')]:
        result = assess_text(facts('cleanup_loss', precleanup=retained))
        assert result['action'] == action
        assert result['priority_score'] == 3
        assert result['qualified'] is result['dispatch_allowed'] is False
        assert result['ocr_paused'] is True
        assert result['publisher_refetch'] == 'deferred'
    native = assess_text(facts('cleanup_loss', 'native_reread_supported', precleanup=False))
    assert native['action'] == 'native_reread'


def test_a_short_reviewed_page_survives_a_low_quantity_score():
    for review in ('source_match', 'valid_empty'):
        result = assess_text(facts(review, 'low_quantity'))
        assert result['action'] == 'keep'
        assert result['confidence_basis'] == 'direct_source_review'
        assert result['calibration_status'] == 'not_calibrated'
        assert result['facts']['page_number'] == 1
    unreviewed = assess_text(facts('low_quantity'))
    assert unreviewed['action'] == 'manual_review'
    assert 'direct_source_review' in unreviewed['missing_evidence']
    no_trigger = assess_text(facts())
    assert no_trigger['action'] == 'keep' and no_trigger['confidence_basis'] == 'unassessed'
    assert no_trigger['qualified'] is False


def test_even_reviewed_ocr_repairs_require_an_exact_page_and_stay_paused():
    for code in ('native_omission', 'native_text_corruption', 'recognition_corruption'):
        assert assess_text(facts(code))['action'] == 'manual_review'
        result = assess_text(facts(code, 'source_requires_recognition'))
        assert result['action'] == 'selective_ocr'
        assert 'user_resumes_ocr' in result['prerequisites']
        assert result['dispatch_allowed'] is False
        assert assess_text(facts(code, 'source_requires_recognition', page=None))['action'] == 'manual_review'
    native = assess_text(facts('native_omission', 'native_reread_supported'))
    assert native['action'] == 'native_reread'
    conflict = assess_text(facts('native_omission', 'native_reread_supported', 'source_requires_recognition'))
    assert conflict['action'] == 'manual_review'
    bad_basis = facts('native_omission')
    bad_basis['findings'][0]['basis'] = 'measurement'
    with pytest.raises(ValueError, match='requires source_review'):
        assess_text(bad_basis)


def test_response_and_container_roles_do_not_trigger_recognition():
    for code in ('source_error', 'source_wait', 'source_feed', 'source_container', 'source_metadata', 'wrong_source'):
        result = assess_text(facts(code, page=None))
        assert result['action'] == 'manual_review'
        assert result['dispatch_allowed'] is False
    unresolved = assess_text(facts('source_error', 'source_unresolved', page=None))
    assert unresolved['action'] == 'refetch_deferred'
    assert unresolved['prerequisites'] == ['user_resumes_publisher_refetch']


def test_runtime_missing_and_conflicting_evidence_cannot_become_success():
    assert assess_text(facts('valid_empty', 'cleanup_loss'))['action'] == 'manual_review'
    assert assess_text(facts('cleanup_loss', 'native_omission'))['action'] == 'manual_review'
    assert assess_text(facts('cleanup_loss', 'offsets_invalid'))['action'] == 'manual_review'
    unknown = facts()
    unknown.update(source_state='unknown', reading_status='missing', output_sha256=None,
                   text_sha256=None, page_number=None, page_count=None)
    result = assess_text(unknown)
    assert result['action'] == 'manual_review'
    assert {'source_state', 'source_page_count', 'output_identity', 'direct_source_review'} <= set(result['missing_evidence'])
    markup = facts('parser_refused', page=None)
    markup.update(source_format='html', parser='html_text', page_count=None)
    assert assess_text(markup)['action'] == 'reparse'
    zero_pages = facts('parser_refused', page=None)
    zero_pages.update(reading_status='error', page_count=0)
    result = assess_text(zero_pages)
    assert result['action'] == 'manual_review'
    assert result['facts']['page_count'] == 0
    assert 'source_page_count' not in result['missing_evidence']


@pytest.mark.parametrize('damage, message', [
    ('raw', 'bind the raw body'), ('output', 'bind the assessed output'),
    ('intermediate', 'intermediary evidence'), ('reviewer', 'source reviewer'),
    ('page', 'page_number'), ('page_range', 'known containing page count'),
    ('unknown_code', 'unknown finding'), ('missing_output', 'requires output identity'),
])
def test_wrong_identity_or_incomplete_review_refuses(damage, message):
    row = facts('cleanup_loss')
    evidence = row['findings'][0]['evidence']
    if damage in {'raw', 'output'}:
        next(a for a in evidence if a['stage'] == damage)['sha256'] = 'd' * 64
    elif damage == 'intermediate':
        row['findings'][0]['evidence'] = [a for a in evidence if a['stage'] != 'intermediate']
    elif damage == 'reviewer':
        row['findings'][0]['reviewer'] = None
    elif damage == 'page':
        row['page_number'] = True
    elif damage == 'page_range':
        row['page_number'] = 5
    elif damage == 'unknown_code':
        row['findings'][0]['code'] = 'looks_good'
    else:
        row['output_sha256'] = None
    with pytest.raises(ValueError, match=message):
        assess_text(row)


def test_proposal_identity_is_replayable_and_evidence_is_not_mutated():
    row = facts('cleanup_loss')
    original = deepcopy(row)
    result = assess_text(row)
    assert result == assess_text(json.loads(json.dumps(row)))
    row['measurements']['nonspace_characters'] = 99
    assert result['facts'] == original
    assert assess_text(row)['assessment_id'] != result['assessment_id']
    row['measurements']['infinite'] = float('inf')
    with pytest.raises(ValueError):
        assess_text(row)


def test_cli_bounds_work_and_reports_unread_records(tmp_path, capsys):
    from congress_api.cli.text_assessment import main
    source = tmp_path / 'facts.jsonl'
    source.write_text(json.dumps(facts('cleanup_loss')) + '\n' + json.dumps(facts('source_match', page=2)) + '\n')
    assert main([str(source), '--limit', '1']) == 0
    out = capsys.readouterr()
    row = json.loads(out.out)
    assert row['action'] == 'renormalize'
    assert json.loads(out.err) == dict(records=1, remaining='not_read', scope='proposal_only_no_dispatch')
    assert main([str(source)]) == 0
    out = capsys.readouterr()
    assert [json.loads(line)['action'] for line in out.out.splitlines()] == ['renormalize', 'keep']
    assert json.loads(out.err)['remaining'] == 'none'


def test_cli_refuses_oversized_records_and_conflicting_reading_outputs(tmp_path, capsys):
    from congress_api.cli.text_assessment import main
    source = tmp_path / 'bad.jsonl'
    source.write_bytes(b'x' * (MAX_RECORD_BYTES + 1))
    with pytest.raises(SystemExit) as error:
        main([str(source)])
    assert error.value.code == 2
    assert not capsys.readouterr().out
    for output in ('b' * 64, 'd' * 64):
        changed = facts()
        changed.update(output_sha256=output, text_sha256=output)
        source.write_text(json.dumps(facts()) + '\n' + json.dumps(changed) + '\n')
        with pytest.raises(SystemExit) as error:
            main([str(source)])
        out = capsys.readouterr()
        assert error.value.code == 2
        assert len(out.out.splitlines()) == 1
        assert 'duplicates' in out.err and 'partial' in out.err
