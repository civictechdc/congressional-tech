"""Reconcile every frozen pilot ID without replacing samples or reading PDFs."""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import pyarrow.parquet as pq

import pilot_review as review
from congress_api.retention.catalog_publication import local_catalog_paths
from congress_api.retention.document_index import validate_document_indexes


def file_digest(path):
    value = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def body_hashes(keys):
    return sorted({Path(key).stem for key in keys or []})


def reconcile_record(original, current, receipt, identity):
    before = body_hashes(original.get('body_keys'))
    after = body_hashes(current.get('body_keys')) if current else []
    changes = []
    if current is None:
        changes.append('missing_document_id')
    else:
        if current.get('record_role') != ['document']:
            changes.append('role_changed_or_ambiguous')
        if current.get('document_kind'):
            changes.append('newly_classified')
        if before != after:
            changes.append('body_set_changed')
    if not before:
        changes.append('no_frozen_body_digest')
    matched = sorted({b['sha256'] for b in (receipt or {}).get('bodies', [])})
    return dict(review_id=identity, document_id=original['document_id'], split=original['split'],
                changes=changes, frozen_body_hashes=before, current_body_hashes=after,
                matched_pilot_body_hashes=matched,
                current_kinds=current.get('document_kind') or [] if current else [],
                current_roles=current.get('record_role') or [] if current else [],
                extraction_status=(receipt or {}).get('status', 'not_attempted'),
                catalog_eligible=not changes,
                reference_available=not changes and len(before) == 1 and before == matched)


def publication_gate(directory, root, metadata):
    """Bind a verified public readback to this exact selected local pair."""
    if directory is None or root is None:
        return dict(verified=False, reason='publication_receipt_and_selected_pair_required')
    directory, root = Path(directory), Path(root)
    names = ['publication-receipt.json', 'public-readback.json', 'after-public-manifest.json', 'after-viewer-manifest.json']
    if any(not (directory / name).is_file() for name in names) or not (root / 'indexes/catalog.json').is_file():
        return dict(verified=False, reason='publication_readback_incomplete')
    receipt, readback, pointer, viewer = [json.loads((directory / name).read_text()) for name in names]
    selected = json.loads((root / 'indexes/catalog.json').read_text())
    catalog_id = metadata['catalog_id']
    valid = (
        receipt.get('status') == 'published_and_verified'
        and readback.get('public_readback') == 'verified'
        and bool(re.fullmatch(r'[0-9a-f]{40}', receipt.get('published_commit', '')))
        and receipt.get('published_commit') == readback.get('commit')
        and readback.get('rebuild_run') == 'https://github.com/civictechdc/congressional-tech/actions/runs/' + str(receipt.get('rebuild_run'))
        and catalog_id != receipt.get('previous_catalog_id')
        and all(value == catalog_id for value in [receipt.get('catalog_id'), readback.get('catalog_id'), pointer.get('catalog_id'), viewer.get('info', {}).get('catalog_id')])
        and pointer.get('source_manifest') == viewer.get('source_manifest') == selected
        and metadata.get('house_naming_version') == readback.get('house_naming_version') == viewer.get('info', {}).get('house_naming_version') == '3.1.0'
    )
    return dict(verified=valid, reason='verified_selected_pair' if valid else 'publication_evidence_mismatch',
                receipt_hashes={name: file_digest(directory / name) for name in names})


def run(sample_path, documents, output, *, catalog_root=None, publication_dir=None, receipts=None):
    sample = json.loads(Path(sample_path).read_text())['records']
    ids = [row['document_id'] for row in sample]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate frozen document IDs')
    splits = Counter(row['split'] for row in sample)
    if not set(splits) <= {'development', 'held-out'}:
        raise ValueError('Unknown frozen split')
    paired = catalog_root is not None
    if paired:
        source, documents = local_catalog_paths(catalog_root)
        validate_document_indexes(source, documents)
    documents = Path(documents)
    file = pq.ParquetFile(documents)
    fields = ['document_id', 'filename', 'source_url', 'source_urls', 'document_kind', 'record_role', 'format', 'body_keys']
    if not set(fields) <= set(file.schema_arrow.names):
        raise ValueError('Catalog lacks required reconciliation fields')
    metadata = {k.decode(): v.decode() for k, v in (file.schema_arrow.metadata or {}).items()}
    if not metadata.get('catalog_id'):
        raise ValueError('Catalog has no identity')
    targets, found, seen = set(ids), {}, set()
    census, totals = Counter(), Counter()
    for batch in file.iter_batches(columns=fields, batch_size=4096):
        for row in batch.to_pylist():
            identity = row['document_id']
            if not identity or identity in seen:
                raise ValueError('Missing or duplicate catalog document ID')
            seen.add(identity)
            totals['records'] += 1
            totals['unnamed_records'] += not bool((row['filename'] or '').strip())
            if not row['document_kind']:
                totals['unclassified_records'] += 1
                urls = row.get('source_urls') or [row.get('source_url')]
                publishers = set()
                for url in urls:
                    try:
                        host = urlsplit(url or '').hostname
                    except ValueError:
                        host = None
                    if host:
                        publishers.add(host.removeprefix('www.'))
                publisher = next(iter(publishers)) if len(publishers) == 1 else 'multiple-publishers' if publishers else 'unknown'
                census[(publisher, '|'.join(sorted(row['format'] or [])), '|'.join(sorted(row['record_role'] or [])),
                        'retained_digest' if row['body_keys'] else 'no_retained_digest')] += 1
            if identity in targets:
                found[identity] = row
    receipts = receipts if receipts is not None else review.records()
    positions, rows = Counter(), []
    for original in sample:
        split = original['split']; positions[split] += 1
        identity = ('D' if split == 'development' else 'H') + f'{positions[split]:03}'
        rows.append(reconcile_record(original, found.get(original['document_id']), receipts.get(original['document_id']), identity))
    gate = publication_gate(publication_dir, catalog_root, metadata)
    summary = dict(sample_sha256=file_digest(sample_path), catalog_id=metadata['catalog_id'],
        catalog_root=str(Path(catalog_root).resolve()) if catalog_root else None,
        publication_directory=str(Path(publication_dir).resolve()) if publication_dir else None,
        documents_path=str(documents.resolve()),
        house_naming_version=metadata.get('house_naming_version'), documents_sha256=file_digest(documents),
        paired_catalog_validated=paired, publication=gate, held_out_review_unlocked=paired and gate['verified'],
        records=len(rows), splits=dict(splits), census_totals=dict(totals),
        changes=dict(Counter(change for row in rows for change in row['changes'])),
        catalog_eligible=sum(row['catalog_eligible'] for row in rows), reference_available=sum(row['reference_available'] for row in rows),
        limit='Retained digests describe catalog evidence, not object availability. Rehearsals never unlock held-out review.')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    ledger = dict(sample_sha256=summary['sample_sha256'], catalog_id=summary['catalog_id'], records=rows)
    (output / 'eligibility.json').write_text(json.dumps(ledger, indent=2) + '\n')
    summary['eligibility_sha256'] = file_digest(output / 'eligibility.json')
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    with (output / 'eligibility.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ['review_id'])
        writer.writeheader()
        writer.writerows({k: json.dumps(v) if isinstance(v, list) else v for k, v in row.items()} for row in rows)
    with (output / 'unclassified-census.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['publisher', 'format', 'role', 'body_evidence', 'records'])
        writer.writerows([*key, count] for key, count in sorted(census.items(), key=lambda item: (-item[1], item[0])))
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--catalog-root', type=Path)
    source.add_argument('--documents', type=Path, help='Standalone table: rehearsal only')
    parser.add_argument('--sample', type=Path, default=review.SAMPLE)
    parser.add_argument('--publication-dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.sample, args.documents, args.output, catalog_root=args.catalog_root, publication_dir=args.publication_dir)
