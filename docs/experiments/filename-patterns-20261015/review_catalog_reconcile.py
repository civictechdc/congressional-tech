"""Reconcile complete reviews against another bound catalog without transferring them."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from catalog_alias_review import COLUMNS, eligible_body
from catalog_content_review import load_reviews, read_ledger
from catalog_disposition_compare import compare_case
from catalog_filename_replay import implementation_manifest, implementation_identity
from catalog_review_evidence import verified
from congress_api.retention.catalog_publication import local_catalog_paths
from congress_api.retention.document_index import RESPONSE_FIELDS
from pilot_reconcile import file_digest


def selected_rows(path, ids, source_ids, identity):
    """Project small fields and retain old members even if their group ID changed."""
    file = pq.ParquetFile(path)
    required = {'document_id', 'source_id', 'filename', 'source_url', 'body_key',
                'document_kind', 'record_role', 'media_type', 'http_status',
                'capture_outcome', 'body_format', *RESPONSE_FIELDS}
    if identity == 'document_id': required.add('body_keys')
    if not required <= set(file.schema_arrow.names):
        raise ValueError('Catalog lacks reconciliation columns')
    wanted = pa.array(sorted(ids), type=pa.string())
    old_sources = pa.array(sorted(source_ids), type=pa.string())
    rows = {}
    for batch in file.iter_batches(columns=sorted(COLUMNS & set(file.schema_arrow.names)), batch_size=2048):
        mask = pc.is_in(batch['document_id'], value_set=wanted)
        if identity == 'source_id':
            mask = pc.or_(mask, pc.is_in(batch['source_id'], value_set=old_sources))
        for row in batch.filter(mask).to_pylist():
            key = row[identity]
            if not key or key in rows:
                raise ValueError('Missing or duplicate selected identity')
            rows[key] = row
    return rows


def reconcile_case(proposal, original, document, members, old_sources, review):
    """Report differences; even identical projected evidence grants no transfer."""
    # Validate the proposal against its original evidence, never against a
    # fabricated fresh ledger or a substituted body at the same source URL.
    compare_case(proposal, original,
                 dict(document_id=original['document_id'], document_kind=original['after_kind']),
                 original['members'], review)
    key = original['document_id']
    before = {r['source_id']: r for r in original['members']}
    after = {r['source_id']: r for r in members}
    if (len(after) != len(members) or any(r['document_id'] != key for r in members)
            or document is not None and document['document_id'] != key):
        raise ValueError('Inconsistent current group identity')
    reasons = []
    if document is None: reasons.append('missing_document')
    added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
    if added or removed: reasons.append('source_membership_changed')
    changes = {}
    for sid in sorted(before.keys() & after.keys()):
        fields = {f: dict(before=before[sid].get(f), after=after[sid].get(f))
                  for f in ['filename', 'source_url', 'body_key']
                  if before[sid].get(f) != after[sid].get(f)}
        if fields: changes[sid] = fields
    if changes: reasons.append('member_identity_changed')
    old_keys = sorted({k for r in before.values() if (k := eligible_body(r))})
    new_keys = sorted({k for r in members if (k := eligible_body(r))})
    if old_keys != new_keys: reasons.append('eligible_bodies_changed')
    if document is not None and set(document.get('body_keys') or []) != {r['body_key'] for r in members if r.get('body_key')}:
        reasons.append('group_body_union_mismatch')
    if document is not None and document.get('record_role') != ['document']:
        reasons.append('role_not_document')
    reviewed_body = review['observation']['body_key'] if review else None
    exact_body = review is not None and new_keys == [reviewed_body]
    body_status = ('reviewed_body_still_only_eligible' if exact_body else
                   'reviewed_body_no_longer_only_eligible' if review else
                   'new_eligible_body_without_review' if new_keys else 'no_eligible_body_or_review')
    forms = sorted(proposal['proposed_primary_forms'] + proposal['proposed_component_forms'])
    selected = sorted(document.get('document_kind') or []) if document is not None else None
    comparison = ('same_labels' if selected == forms else 'different_labels') if exact_body and document else 'not_comparable'
    # Keep literal claims visible, including native kinds and capture failures.
    return dict(document_id=key, filename=original['filename'], document_present=document is not None,
        reasons=reasons, source_count_before=len(before), source_count_after=len(after),
        added_source_ids=added, removed_source_ids=removed, member_identity_changes=changes,
        removed_member_current_groups={sid: old_sources[sid]['document_id'] if sid in old_sources else None for sid in removed},
        original_eligible_body_keys=old_keys, current_eligible_body_keys=new_keys,
        reviewed_body_key=reviewed_body, body_status=body_status,
        matching_body_and_source_identity=exact_body and not reasons,
        original_selected_kinds=original['after_kind'], current_selected_kinds=selected,
        reviewed_forms=forms, label_comparison=comparison,
        current_document=document, current_members=sorted(members, key=lambda r: r['source_id']),
        review_receipt=review['receipt'] if review else None,
        review_receipt_sha256=review['receipt_sha256'] if review else None,
        transfer_approved=False, classification_mutations=False,
        independent_reference=False, release_approved=False)


def run(comparison_checkpoint, raw_checkpoint, catalog_root, output):
    output = Path(output)
    if output.exists(): raise FileExistsError(output)
    implementation = implementation_manifest()
    bindings = {str(p): file_digest(p) for p in [comparison_checkpoint, raw_checkpoint]}
    cp = json.loads(Path(comparison_checkpoint).read_text())
    summary = json.loads(verified(cp['summary_path'], cp['summary_sha256'], bindings).read_text())
    for path, digest in summary['bindings'].items(): verified(path, digest, bindings)
    raw = json.loads(Path(raw_checkpoint).read_text())
    if raw.get('exact_pair_verified') is not True or raw.get('reference_integrity_verified') is not True:
        raise ValueError('Require a verified raw pair checkpoint')
    for path, digest in raw['evidence'].items(): verified(path, digest, bindings)
    source_path, document_path = local_catalog_paths(catalog_root)
    for path in [Path(catalog_root) / 'indexes/catalog.json', source_path, document_path]:
        verified(path, raw['evidence'][str(path)], bindings)
    manifest = json.loads((Path(catalog_root) / 'indexes/catalog.json').read_text())
    if manifest['catalog_id'] != raw['catalog_id'] or manifest['generation'] != raw['generation']:
        raise ValueError('Raw checkpoint selects another catalog')
    # The prior comparison pins its proposal input and all saved review bytes.
    proposal_paths = [p for p in summary['bindings'] if Path(p).name == 'content_disposition_proposals_v1.json']
    if len(proposal_paths) != 1: raise ValueError('Require exactly one bound proposal input')
    spec = json.loads(Path(proposal_paths[0]).read_text())
    if any(spec.get(f) is not False for f in ['classification_mutations', 'independent_reference', 'release_approved']):
        raise ValueError('Require unapproved assistant proposals')
    originals = read_ledger(verified(spec['original_ledger'], spec['original_ledger_sha256'], bindings))
    reviews = load_reviews(spec['receipt'], spec['receipt_sha256'], bindings)
    ids = {p['document_id'] for p in spec['records']}
    if len(ids) != len(spec['records']) or ids != {k for k, r in originals.items() if r['review_basis'] == 'needs_review'}:
        raise ValueError('Require every original review case exactly once')
    old_ids = {r['source_id'] for key in ids for r in originals[key]['members']}
    sources = selected_rows(source_path, ids, old_ids, 'source_id')
    documents = selected_rows(document_path, ids, set(), 'document_id')
    members = defaultdict(list)
    for row in sources.values(): members[row['document_id']].append(row)
    results = [reconcile_case(p, originals[p['document_id']], documents.get(p['document_id']),
        members[p['document_id']], sources, reviews.get(p['document_id'])) for p in spec['records']]
    for path, digest in bindings.items(): verified(path, digest, {})
    if implementation_identity(implementation_manifest()) != implementation_identity(implementation):
        raise ValueError('Implementation changed during reconciliation')
    output.mkdir(parents=True)
    (output / 'implementation.json').write_text(json.dumps(implementation, indent=2) + '\n')
    with (output / 'reconciliation.jsonl').open('x') as stream:
        for row in results: stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    columns = ['document_id', 'filename', 'source_count_before', 'source_count_after', 'reasons',
               'body_status', 'matching_body_and_source_identity', 'original_selected_kinds',
               'current_selected_kinds', 'reviewed_forms', 'label_comparison']
    with (output / 'reconciliation.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader()
        for row in results:
            writer.writerow({k: '|'.join(row[k]) if isinstance(row[k], list) else row[k] for k in columns})
    result = dict(catalog_id=raw['catalog_id'], records=len(results),
        current_documents=len(documents), selected_current_sources=len(sources),
        matching_body_and_source_identity=sum(r['matching_body_and_source_identity'] for r in results),
        body_status=dict(Counter(r['body_status'] for r in results)),
        reasons=dict(Counter(reason for r in results for reason in r['reasons'])),
        label_comparison=dict(Counter(r['label_comparison'] for r in results)),
        bindings=bindings, outputs={name:file_digest(output/name) for name in
            ['reconciliation.jsonl', 'reconciliation.csv', 'implementation.json']},
        transfer_approved=False, classification_mutations=False, independent_reference=False, release_approved=False,
        scope='Projected metadata reconciliation against the saved public pair. Matching bodies and source identities do not establish complete-row identity, independent correctness or review transfer approval.')
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['comparison-checkpoint', 'raw-checkpoint', 'catalog-root', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k not in ['bindings', 'outputs']}, indent=2))
