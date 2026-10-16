"""Audit complete alias evidence without reading bodies or approving classifications."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

from house_naming import document_families
from congress_api.retention.catalog_publication import local_catalog_paths
from congress_api.retention.document_index import validate_document_indexes, document_body, RESPONSE_FIELDS
from pilot_reconcile import file_digest
from catalog_filename_replay import implementation_manifest, implementation_identity

BROAD_SUPPORT = {'meeting-support', 'witness-support', 'support-document'}
COLUMNS = {'document_id', 'source_id', 'filename', 'source_url', 'body_key',
           'filenames', 'source_urls', 'body_keys', 'document_kind', 'filename_document_kind',
           'document_kind_source', 'record_role', 'source_document_type',
           'source_document_type_basis', 'content_document_kind', 'media_type', 'http_status',
           'capture_outcome', 'body_format', *RESPONSE_FIELDS}


def values(row, key):
    return set(row.get(key) or [])


def eligible_body(row):
    # Reuse the catalog's body-join policy; error/empty captures are not alias proof.
    return document_body(row.get('body_key'), row.get('media_type'), row.get('http_status'),
                         row.get('capture_outcome'), row.get('body_format'), row)


def audit_group(before, document, members):
    """Describe compatibility and exact alias/body links, never content correctness."""
    old, new = values(before, 'document_kind'), values(document, 'document_kind')
    claims = set().union(*(values(row, 'filename_document_kind') for row in members))
    integrity = []
    if claims != values(document, 'filename_document_kind'):
        integrity.append('filename_claim_union_mismatch')
    if not members or any(row['document_id'] != document['document_id'] for row in members):
        integrity.append('missing_or_foreign_group_member')
    for scalar, plural in [('filename', 'filenames'), ('source_url', 'source_urls'), ('body_key', 'body_keys')]:
        if {row[scalar] for row in members if row.get(scalar)} != values(document, plural):
            integrity.append(plural + '_union_mismatch')

    support = defaultdict(list)
    for row in members:
        for kind in values(row, 'filename_document_kind'):
            support[kind].append(row)
    links = []
    for broad in sorted(old & new):
        for specific in sorted(new - old):
            if broad in BROAD_SUPPORT or document_families([broad]) == document_families([specific]):
                left, right = support[broad], support[specific]
                shared = ({key for r in left if (key := eligible_body(r))}
                          & {key for r in right if (key := eligible_body(r))})
                links.append(dict(prior_kind=broad, added_kind=specific,
                                  prior_source_ids=sorted(r['source_id'] for r in left),
                                  added_source_ids=sorted(r['source_id'] for r in right),
                                  shared_retained_body_keys=sorted(shared)))
    # Shared body locators support alias compatibility; they do not verify bytes.
    supported_additions = {link['added_kind'] for link in links if link['shared_retained_body_keys']}
    disposition = 'needs_review'
    if not integrity and old and old < new and new - old <= supported_additions:
        disposition = ('same_family_aliases' if document_families(old) == document_families(new)
                       else 'broad_specific_aliases')
    flags = []
    if len(values(document, 'body_keys')) > 1:
        flags.append('multiple_retained_bodies')
    if any(re.search(r'(?:^|[\s_.-])text(?:$|[\s_.-])', r.get('filename') or '', re.I) for r in members):
        flags.append('explicit_TEXT_wording')
    return dict(document_id=document['document_id'], filename=document.get('filename'),
                before_kind=sorted(old), after_kind=sorted(new), metadata_review=disposition,
                content_review='not_performed', release_approved=False,
                integrity_issues=integrity, flags=flags, alias_links=links,
                retained_body_keys=sorted(values(document, 'body_keys')),
                members=sorted(members, key=lambda row: row['source_id']))


def read_rows(path, key):
    file = pq.ParquetFile(path)
    rows = {}
    for batch in file.iter_batches(columns=sorted(COLUMNS & set(file.schema_arrow.names)),
                                   batch_size=1024, use_threads=False):
        for row in batch.to_pylist():
            if not row.get(key) or row[key] in rows:
                raise ValueError('Missing or duplicate ' + key)
            rows[row[key]] = row
    return rows


def run(before_root, after_root, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    implementation = implementation_manifest()
    paths, tables, fingerprints = {}, {}, {}
    for label, root in [('before', before_root), ('after', after_root)]:
        source, document = local_catalog_paths(root)
        validate_document_indexes(source, document)
        paths[label] = (source, document)
        for name, path, key in [('sources', source, 'source_id'), ('documents', document, 'document_id')]:
            fingerprints[label + '_' + name] = dict(path=str(path), sha256=file_digest(path))
            tables[label + '_' + name] = read_rows(path, key)
    for name in ['sources', 'documents']:
        if tables['before_' + name].keys() != tables['after_' + name].keys():
            raise ValueError('Before/after ' + name + ' identities differ')
    for key, row in tables['after_sources'].items():
        if row['document_id'] != tables['before_sources'][key]['document_id']:
            raise ValueError('Source membership changed')
    if 'filename_document_kind' not in pq.read_schema(paths['after'][0]).names:
        raise ValueError('Current sources lack original filename claims')
    groups = defaultdict(list)
    for row in tables['after_sources'].values():
        groups[row['document_id']].append(row)
    if set(groups) != set(tables['after_documents']):
        raise ValueError('Source groups and document IDs differ')
    records = []
    unchanged = 0
    for key, document in sorted(tables['after_documents'].items()):
        before = tables['before_documents'][key]
        result = audit_group(before, document, groups[key])
        if result['integrity_issues']:
            raise ValueError('Alias evidence mismatch for ' + key + ': ' + ', '.join(result['integrity_issues']))
        if result['before_kind'] == result['after_kind']:
            unchanged += 1
        else:
            records.append(result)
    # Bind both complete selected pairs; refuse a moving input before writing.
    for label, root in [('before', before_root), ('after', after_root)]:
        if local_catalog_paths(root) != paths[label]:
            raise ValueError('Catalog selection changed during audit')
    if any(file_digest(item['path']) != item['sha256'] for item in fingerprints.values()):
        raise ValueError('Input bytes changed during audit')
    if implementation_identity(implementation_manifest()) != implementation_identity(implementation):
        raise ValueError('Implementation changed during audit')
    output.mkdir(parents=True)
    (output / 'implementation.json').write_text(json.dumps(implementation, indent=2) + '\n')
    with (output / 'ledger.jsonl').open('x') as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    buckets = defaultdict(list)
    for record in records:
        buckets[record['metadata_review'], tuple(record['before_kind']), tuple(record['after_kind'])].append(record)
    with (output / 'groupings.csv').open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['metadata_review', 'count', 'before', 'after', 'multiple_body_groups', 'sample_1', 'sample_2', 'sample_3'])
        for (status, old, new), rows in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0])):
            examples = [row['filename'] or '(unnamed)' for row in rows[:3]]
            writer.writerow([status, len(rows), '|'.join(old), '|'.join(new),
                             sum('multiple_retained_bodies' in row['flags'] for row in rows),
                             *examples, *[''] * (3 - len(examples))])
    summary = dict(inputs=fingerprints, evaluator_sha256=file_digest(__file__),
                   implementation_sha256=file_digest(output / 'implementation.json'),
                   source_rows=len(tables['after_sources']), document_groups=len(groups),
                   unchanged_kind_groups=unchanged, changed_kind_groups=len(records),
                   metadata_review=dict(Counter(row['metadata_review'] for row in records)),
                   flags=dict(Counter(flag for row in records for flag in row['flags'])),
                   verified_alias_unions=len(groups), input_bytes_unchanged=True,
                   body_reads=False, classification_mutations=False, release_approved=False,
                   limitation='Metadata compatibility from all alias rows and shared retained body keys only; no content correctness or release approval.',
                   outputs={name: file_digest(output / name) for name in ['ledger.jsonl', 'groupings.csv']})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-root', type=Path, required=True)
    parser.add_argument('--after-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.before_root, args.after_root, args.output), indent=2))
