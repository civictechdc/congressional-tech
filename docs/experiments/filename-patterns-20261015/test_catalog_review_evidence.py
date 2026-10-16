from copy import deepcopy

import pytest

from catalog_review_evidence import (apply_filename_reviews, load_filename_reviews,
                                    match_group, row_digest, verified)


def evidence():
    document = dict(document_id='d', source_id='s1', document_kind=['committee-vote'],
                    document_kind_source=['filename'], record_role=['document'],
                    filenames=['vote.pdf'], source_urls=['https://example.gov/vote.pdf'], body_keys=['body-a'])
    members = [dict(source_id='s1', document_id='d', filename='vote.pdf',
                    source_url='https://example.gov/vote.pdf', body_key='body-a',
                    document_kind=['committee-vote'], document_kind_source=['filename'], record_role=['document'])]
    return document, members


def test_exact_group_match_does_not_mutate_evidence():
    current, members = evidence()
    original = deepcopy((current, members))
    assert match_group(current, members, *deepcopy((current, members))) == []
    assert (current, members) == original


@pytest.mark.parametrize('field,value', [('document_id','other'), ('source_id','other'),
    ('document_kind',['report']), ('document_kind_source',['content']), ('body_keys',['body-b']),
    ('filenames',['renamed.pdf']), ('source_urls',['https://other.gov/vote.pdf']),
    ('record_role',['error-response']), ('content_document_kind',['amendment'])])
def test_matching_id_does_not_hide_changed_group_evidence(field, value):
    current, members = evidence()
    prior = deepcopy(current);prior[field] = value
    assert field+'_changed' in match_group(current, members, prior, members)


@pytest.mark.parametrize('field,value', [('source_id','s2'), ('filename','renamed.pdf'),
    ('source_url','https://other.gov/vote.pdf'), ('body_key','body-b'),
    ('document_kind',['amendment']), ('record_role',['error-response']),
    ('content_document_kind',['report']), ('source_document_type',['witness statement'])])
def test_matching_group_does_not_hide_changed_alias_evidence(field, value):
    current, members = evidence()
    prior = deepcopy(members);prior[0][field] = value
    assert match_group(current, members, current, prior)


def test_tampered_receipt_is_rejected_before_binding(tmp_path):
    path = tmp_path/'receipt.json';path.write_text('{}')
    bindings = {}
    with pytest.raises(ValueError, match='digest mismatch'):
        verified(path, '0'*64, bindings)
    assert bindings == {}


def filename_receipt(tmp_path, interpretation='reviewed_explicit_disclosure_wording'):
    import json
    from pilot_reconcile import file_digest
    row = dict(document_id='d', review_basis='needs_review', after_kind=['testimony-disclosure'],
               members=[dict(source_id='s', body_key='body-a', filename='Truth in Testimony.pdf')],
               content_review='not_performed', release_approved=False)
    original = tmp_path/'original.jsonl'; original.write_text(json.dumps(row)+'\n')
    decision = dict(document_id='d', source_row_sha256=row_digest(row), filename_interpretation=interpretation,
                    content_review='not_performed', release_approved=False)
    checkpoint = dict(input_ledger=str(original), input_ledger_sha256=file_digest(original), decisions=[decision])
    path = tmp_path/'filename-checkpoint.json'; path.write_text(json.dumps(checkpoint))
    note = tmp_path/'note.txt'; note.write_text('Filename interpretation only.')
    spec = dict(name='filename-fixture', checkpoint=str(path), checkpoint_sha256=file_digest(path),
                review=str(note), review_sha256=file_digest(note))
    return row, checkpoint, spec


def test_exact_filename_review_sets_only_interpretation_basis(tmp_path):
    row, _, spec = filename_receipt(tmp_path)
    original = deepcopy(row)
    reviews = load_filename_reviews([spec], {})
    apply_filename_reviews(row, reviews)
    assert row['review_basis'] == 'filename_interpretation_review'
    assert row['members'] == original['members'] and row['after_kind'] == original['after_kind']
    assert row['content_review'] == 'not_performed' and row['release_approved'] is False
    assert row['filename_reviews'][0]['scope'] == 'filename_interpretation_only'
    assert not row['nonmatching_filename_reviews']


def test_unresolved_filename_review_does_not_clear_pending_status(tmp_path):
    row, _, spec = filename_receipt(tmp_path, 'unresolved_award_list')
    apply_filename_reviews(row, load_filename_reviews([spec], {}))
    assert row['review_basis'] == 'needs_review'
    assert row['filename_reviews'][0]['interpretation'] == 'unresolved_award_list'


@pytest.mark.parametrize('field,value', [('body_key','body-b'), ('filename','renamed.pdf'), ('source_id','s2')])
def test_changed_alias_cannot_inherit_filename_review(tmp_path, field, value):
    row, _, spec = filename_receipt(tmp_path)
    row['members'][0][field] = value
    apply_filename_reviews(row, load_filename_reviews([spec], {}))
    assert row['review_basis'] == 'needs_review' and not row['filename_reviews']
    assert row['nonmatching_filename_reviews'] == [{'name':'filename-fixture','reason':'complete_row_changed'}]


@pytest.mark.parametrize('mutation,error', [
    ('row_hash','does not bind'), ('unknown_id','does not bind'), ('duplicate','Duplicate filename review decision'),
    ('unknown_decision','Unknown filename'), ('content','cannot approve'), ('release','cannot approve'),
])
def test_hash_valid_checkpoint_still_requires_valid_decisions(tmp_path, mutation, error):
    import json
    from pathlib import Path
    from pilot_reconcile import file_digest
    _, checkpoint, spec = filename_receipt(tmp_path)
    decision = checkpoint['decisions'][0]
    if mutation == 'row_hash': decision['source_row_sha256'] = '0'*64
    elif mutation == 'unknown_id': decision['document_id'] = 'missing'
    elif mutation == 'duplicate': checkpoint['decisions'].append(deepcopy(decision))
    elif mutation == 'unknown_decision': decision['filename_interpretation'] = 'approved'
    elif mutation == 'content': decision['content_review'] = 'verified'
    elif mutation == 'release': decision['release_approved'] = True
    path = Path(spec['checkpoint']); path.write_text(json.dumps(checkpoint))
    spec['checkpoint_sha256'] = file_digest(path)
    with pytest.raises(ValueError, match=error):
        load_filename_reviews([spec], {})


def test_duplicate_filename_review_is_rejected(tmp_path):
    _, _, spec = filename_receipt(tmp_path)
    with pytest.raises(ValueError, match='Duplicate filename review name'):
        load_filename_reviews([spec, spec], {})


def test_complete_linkage_keeps_content_pending_and_requires_checkpoint_binding(tmp_path):
    import json
    from catalog_review_evidence import run
    from catalog_alias_review import run as audit
    from catalog_filename_replay import run as replay
    from pilot_reconcile import file_digest
    from test_catalog_filename_replay import baseline
    before = baseline(tmp_path)
    replay_root = tmp_path/'replay'
    replay(before, replay_root, rehearsal=True, workers=1)
    audit_root = tmp_path/'audit'
    audit(before, replay_root/'catalog', audit_root)
    audit_cp = tmp_path/'audit-checkpoint.json'
    audit_cp.write_text(json.dumps({'summary_sha256':file_digest(audit_root/'summary.json')}))
    receipt_cp = tmp_path/'receipt-checkpoint.json'
    receipt_cp.write_text(json.dumps({'replay_summary_path':str(replay_root/'summary.json'),
                                      'replay_summary_sha256':file_digest(replay_root/'summary.json')}))
    note = tmp_path/'review.txt';note.write_text('Interpretation review fixture, not content truth.')
    spec = dict(name='fixture', checkpoint=str(receipt_cp), checkpoint_sha256=file_digest(receipt_cp),
                review=str(note), review_sha256=file_digest(note), summary=str(replay_root/'summary.json'),
                summary_sha256=file_digest(replay_root/'summary.json'))
    registry = dict(alias_checkpoint=str(audit_cp), alias_checkpoint_sha256=file_digest(audit_cp),
                    alias_summary=str(audit_root/'summary.json'), receipts=[spec])
    registry_path = tmp_path/'registry.json';registry_path.write_text(json.dumps(registry))
    result = run(registry_path,tmp_path/'linked')
    assert result['review_basis'] == {'prior_interpretation_review':1}
    assert result['matched_prior_reviews'] == {'fixture':1}
    row = json.loads((tmp_path/'linked/ledger.jsonl').read_text())
    assert row['prior_reviews'][0]['scope'] == 'historical_interpretation_only'
    assert row['content_review'] == 'not_performed' and row['release_approved'] is False
    # A hash-valid checkpoint that does not actually name this replay is insufficient.
    receipt_cp.write_text('{}');spec['checkpoint_sha256'] = file_digest(receipt_cp)
    registry_path.write_text(json.dumps(registry))
    with pytest.raises(ValueError,match='Checkpoint does not bind'):
        run(registry_path,tmp_path/'refused')
    assert not (tmp_path/'refused').exists()
