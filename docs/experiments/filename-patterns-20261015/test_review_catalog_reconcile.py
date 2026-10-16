"""Fresh catalogs may change identity or eligibility without changing old reviews."""
from copy import deepcopy
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from catalog_alias_review import COLUMNS
from catalog_review_evidence import row_digest
from pilot_reconcile import file_digest
from review_catalog_reconcile import reconcile_case, selected_rows, run
from test_catalog_disposition_compare import case
from test_catalog_content_review import fixture as review_fixture


def current_case():
    proposal, original, document, members, review = case()
    original['members'][0]['body_format'] = ['pdf']
    proposal['source_row_sha256'] = review['source_row_sha256'] = row_digest(original)
    members = deepcopy(original['members'])
    document.update(record_role=['document'], body_keys=['body'])
    return proposal, original, document, members, {r['source_id']: r for r in members}, review


def test_matching_body_identity_does_not_approve_transfer_or_mutate_inputs():
    args = current_case(); before = deepcopy(args)
    result = reconcile_case(*args)
    assert result['matching_body_and_source_identity']
    assert result['body_status'] == 'reviewed_body_still_only_eligible'
    assert result['label_comparison'] == 'different_labels'
    assert result['transfer_approved'] is result['classification_mutations'] is False
    assert args == before


@pytest.mark.parametrize('change,reason', [
    ('body', 'member_identity_changed'), ('filename', 'member_identity_changed'),
    ('url', 'member_identity_changed'), ('new_member', 'source_membership_changed'),
    ('ineligible', 'eligible_bodies_changed'), ('role', 'role_not_document'),
    ('union', 'group_body_union_mismatch')])
def test_changed_current_evidence_blocks_matching_identity(change, reason):
    p, o, d, members, sources, review = current_case()
    if change == 'body': members[0]['body_key'] = 'replacement'
    elif change == 'filename': members[0]['filename'] = 'changed.pdf'
    elif change == 'url': members[0]['source_url'] = 'https://elsewhere.gov/file.pdf'
    elif change == 'new_member': members.append(dict(members[0], source_id='new'))
    elif change == 'ineligible': members[0]['response_usable'] = ['false']
    elif change == 'role': d['record_role'] = ['reference']
    elif change == 'union': d['body_keys'] = ['other']
    result = reconcile_case(p, o, d, members, sources, review)
    assert reason in result['reasons']
    assert not result['matching_body_and_source_identity']
    assert not result['transfer_approved']


def test_missing_group_reports_old_member_destination_without_rebinding():
    p, o, _, _, sources, review = current_case()
    sources['source']['document_id'] = 'new-group'
    result = reconcile_case(p, o, None, [], sources, review)
    assert result['removed_member_current_groups'] == {'source': 'new-group'}
    assert 'missing_document' in result['reasons']
    assert result['current_selected_kinds'] is None
    assert result['label_comparison'] == 'not_comparable'


@pytest.mark.parametrize('now_eligible', [False, True])
def test_unavailable_case_stays_unreviewed_even_if_a_body_appears(now_eligible):
    p, o, d, members, sources, _ = current_case()
    p.update(status='unresolved_no_body', evidence=None, proposed_primary_forms=[])
    o['members'][0]['body_format'] = ['html']
    p['source_row_sha256'] = row_digest(o)
    if not now_eligible: members[0]['body_format'] = ['html']
    result = reconcile_case(p, o, d, members, sources, None)
    assert result['body_status'] == ('new_eligible_body_without_review' if now_eligible else 'no_eligible_body_or_review')
    assert result['label_comparison'] == 'not_comparable'
    assert not result['matching_body_and_source_identity']


def schema():
    scalar = {'document_id', 'source_id', 'filename', 'source_url', 'body_key'}
    return pa.schema([(c, pa.string() if c in scalar else pa.list_(pa.string())) for c in sorted(COLUMNS)],
                     metadata={b'catalog_id': b'fresh'})


def test_projection_finds_moved_members_and_new_members_but_excludes_controls(tmp_path):
    p = tmp_path / 'rows.parquet'
    rows = [dict(document_id='target', source_id='new'), dict(document_id='moved', source_id='old'),
            dict(document_id='unrelated', source_id='control')]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema()), p)
    found = selected_rows(p, {'target'}, {'old'}, 'source_id')
    assert set(found) == {'old', 'new'}
    pq.write_table(pa.Table.from_pylist(rows + [rows[0]], schema=schema()), p)
    with pytest.raises(ValueError, match='duplicate'): selected_rows(p, {'target'}, {'old'}, 'source_id')


@pytest.mark.parametrize('change', [None, 'catalog_bytes', 'receipt_bytes', 'checkpoint_catalog', 'missing_case'])
def test_bound_reconciliation_integration(tmp_path, change):
    original, receipt, receipt_path, _, ledger = review_fixture(tmp_path)
    observed = receipt['records'][0]
    proposal = dict(document_id='d', source_row_sha256=row_digest(original),
        proposed_primary_forms=observed['observed_document_forms'], proposed_component_forms=[],
        status='assistant_proposal', handling='composite', independent_reference=False, release_approved=False,
        evidence=dict(receipt=str(receipt_path), receipt_sha256=file_digest(receipt_path),
                      **{k:observed[k] for k in ['body_key', 'sha256', 'pages']}))
    spec = dict(records=[] if change == 'missing_case' else [proposal],
        original_ledger=str(ledger), original_ledger_sha256=file_digest(ledger),
        receipt=str(receipt_path), receipt_sha256=file_digest(receipt_path),
        classification_mutations=False, independent_reference=False, release_approved=False)
    proposals = tmp_path / 'content_disposition_proposals_v1.json'; proposals.write_text(json.dumps(spec))
    comparison = tmp_path / 'comparison.json'
    comparison.write_text(json.dumps(dict(bindings={str(p):file_digest(p) for p in [proposals, ledger, receipt_path]})))
    cp = tmp_path / 'comparison-checkpoint.json'
    cp.write_text(json.dumps(dict(summary_path=str(comparison), summary_sha256=file_digest(comparison))))
    root = tmp_path / 'catalog'; generation = 'a' * 32
    directory = root / 'catalog-generations' / generation; directory.mkdir(parents=True)
    row = dict(original['members'][0], document_kind=['biography'], record_role=['document'],
               body_keys=original['retained_body_keys'])
    files, evidence = {}, {}
    for label, name in [('filenames','document-filenames.parquet'), ('documents','documents.parquet')]:
        path = directory / name; pq.write_table(pa.Table.from_pylist([row], schema=schema()), path)
        files[label] = dict(key=str(path.relative_to(root)), rows=1, bytes=path.stat().st_size, sha256=file_digest(path))
        evidence[str(path)] = file_digest(path)
    (root/'indexes').mkdir(); manifest = root/'indexes/catalog.json'
    manifest.write_text(json.dumps(dict(version=1, catalog_id='fresh', generation=generation, files=files)))
    evidence[str(manifest)] = file_digest(manifest)
    raw = tmp_path/'raw.json'; raw.write_text(json.dumps(dict(catalog_id='wrong' if change == 'checkpoint_catalog' else 'fresh',
        generation=generation, exact_pair_verified=True, reference_integrity_verified=True, evidence=evidence)))
    if change == 'catalog_bytes':
        with (directory/'documents.parquet').open('ab') as stream: stream.write(b'changed')
    if change == 'receipt_bytes': receipt_path.write_text('{}')
    output = tmp_path / 'result'
    if change:
        with pytest.raises(ValueError): run(cp, raw, root, output)
        assert not output.exists()
    else:
        result = run(cp, raw, root, output)
        assert result['records'] == result['matching_body_and_source_identity'] == 1
        assert result['label_comparison'] == {'different_labels': 1}
        assert not result['transfer_approved']
        for name, digest in result['outputs'].items(): assert file_digest(output/name) == digest
        with pytest.raises(FileExistsError): run(cp, raw, root, output)
