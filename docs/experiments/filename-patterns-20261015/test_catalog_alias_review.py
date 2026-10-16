from copy import deepcopy

import pytest

from catalog_alias_review import audit_group


def fixture(prior='meeting-support', added='committee-memorandum', bodies=('body-a', 'body-a')):
    members = [dict(source_id='s1', document_id='d', filename='HHRG-SD.pdf', source_url='https://a',
                    body_key=bodies[0], filename_document_kind=[prior]),
               dict(source_id='s2', document_id='d', filename='hearing_memo.pdf', source_url='https://b',
                    body_key=bodies[1], filename_document_kind=[added])]
    for row in members:
        row.update(media_type=['application/pdf'], http_status=['200'], body_format=['pdf'])
    document = dict(document_id='d', filename='hearing_memo.pdf', document_kind=[prior, added],
                    filename_document_kind=[prior, added], filenames=[r['filename'] for r in members],
                    source_urls=[r['source_url'] for r in members], body_keys=sorted(set(bodies)))
    return dict(document_kind=[prior]), document, members


def test_shared_body_links_broad_and_specific_aliases_without_approving_contents():
    before, document, members = fixture()
    original = deepcopy((before, document, members))
    row = audit_group(before, document, members)
    assert row['metadata_review'] == 'broad_specific_aliases'
    assert row['alias_links'][0]['shared_retained_body_keys'] == ['body-a']
    assert row['alias_links'][0]['prior_source_ids'] == ['s1']
    assert row['alias_links'][0]['added_source_ids'] == ['s2']
    assert row['content_review'] == 'not_performed' and row['release_approved'] is False
    assert (before, document, members) == original


def test_reused_endpoint_with_different_bodies_cannot_prove_alias_compatibility():
    before, document, members = fixture(bodies=('body-a', 'body-b'))
    members[1]['source_url'] = members[0]['source_url']
    document['source_urls'] = [members[0]['source_url']]
    row = audit_group(before, document, members)
    assert row['metadata_review'] == 'needs_review'
    assert row['flags'] == ['multiple_retained_bodies']
    assert row['alias_links'][0]['shared_retained_body_keys'] == []


def test_same_family_aliases_keep_their_original_kinds():
    row = audit_group(*fixture(prior='committee-amendment', added='amendment'))
    assert row['metadata_review'] == 'same_family_aliases'
    assert row['after_kind'] == ['amendment', 'committee-amendment']
    assert row['release_approved'] is False


@pytest.mark.parametrize('field', ['filename_document_kind', 'body_keys', 'filenames', 'source_urls'])
def test_missing_group_evidence_refuses_compatible_disposition(field):
    before, document, members = fixture()
    document[field] = []
    row = audit_group(before, document, members)
    assert row['integrity_issues']
    assert row['metadata_review'] == 'needs_review'


def test_removed_prior_kind_and_unassigned_baseline_need_review():
    before, document, members = fixture()
    document['document_kind'] = ['committee-memorandum']
    assert audit_group(before, document, members)['metadata_review'] == 'needs_review'
    before['document_kind'] = []
    assert audit_group(before, document, members)['metadata_review'] == 'needs_review'


def test_nonmatching_member_is_an_integrity_failure():
    before, document, members = fixture()
    members[0]['document_id'] = 'another-group'
    row = audit_group(before, document, members)
    assert 'missing_or_foreign_group_member' in row['integrity_issues']
    assert row['metadata_review'] == 'needs_review'


def test_complete_pair_audit_preserves_input_and_leaves_content_unreviewed(tmp_path, monkeypatch):
    import json
    from catalog_alias_review import run
    from catalog_filename_replay import run as replay
    from test_catalog_filename_replay import baseline
    from congress_api.retention import document_index as index
    before = baseline(tmp_path)
    monkeypatch.setattr(index, 'read_retained_body', lambda *a: pytest.fail('Body read during alias audit'))
    replay(before, tmp_path / 'replay', rehearsal=True, workers=1)
    result = run(before, tmp_path / 'replay/catalog', tmp_path / 'review')
    assert result['source_rows'] == 6 and result['verified_alias_unions'] == 5
    assert result['unchanged_kind_groups'] == 4 and result['changed_kind_groups'] == 1
    assert result['metadata_review'] == {'needs_review': 1}
    assert result['input_bytes_unchanged'] and result['body_reads'] is False
    row = json.loads((tmp_path / 'review/ledger.jsonl').read_text())
    assert len(row['members']) == 2 and row['after_kind'] == ['public-law']
    assert row['content_review'] == 'not_performed' and not row['release_approved']
    with pytest.raises(FileExistsError):
        run(before, tmp_path / 'replay/catalog', tmp_path / 'review')


@pytest.mark.parametrize('evidence', [dict(http_status=['404']), dict(response_usable=['false']), dict(body_key='bodies/sha256/e3/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.gz')])
def test_failed_or_empty_capture_cannot_support_alias_compatibility(evidence):
    before, document, members = fixture()
    for row in members:
        row.update(evidence)
    document['body_keys'] = sorted({row['body_key'] for row in members})
    row = audit_group(before, document, members)
    assert row['metadata_review'] == 'needs_review'
    assert row['alias_links'][0]['shared_retained_body_keys'] == []
