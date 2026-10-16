"""Replay maintained filename metadata on a complete, read-only catalog pair.

Writes only to a new experiment directory. No source/body acquisition, body
reinspection, catalog selection or publication occurs.
"""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
import logging
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import time

import pyarrow.parquet as pq

from rule_review import ROOT
from pilot_reconcile import file_digest, publication_gate
from congress_api.retention import document_index as index
from congress_api.retention.catalog_publication import local_catalog_paths
from congress_api.retention.catalog_staging import WorkingCatalog

RESERVE = 10 * 1024**3
PROTECTED = (set(index.SOURCE_SCHEMA.names) | index.SOURCE_CONTEXT_FIELDS | index.AVAILABILITY_FIELDS
             | index.BODY_FIELDS | {'capture_outcome', 'source_record_type', 'source_record_identifier'}) - {'record_role'}


def normalized(value):
    # Arrow can add null struct fields when combining schemas. Ignore only that
    # padding, preserving source strings, list order and all non-null evidence.
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def protected_hash(row, document):
    fields = PROTECTED
    if document:
        fields = (fields - {'body_key', 'filename', 'source_url'}) | {'body_keys', 'filenames', 'source_urls'}
    return sha256(encode(normalized({k: row.get(k) for k in sorted(fields)})).encode()).hexdigest()


def compare_table(before, after, output, *, document=False):
    """Join both complete tables on stable IDs using bounded SQLite storage."""
    identity = 'document_id' if document else 'source_id'
    output = Path(output)
    with TemporaryDirectory(prefix='compare-', dir=output.parent) as temporary:
        db = sqlite3.connect(Path(temporary) / 'comparison.sqlite')
        try:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-16384;')
            counts = {}
            for label, path in [('before_rows', before), ('after_rows', after)]:
                index.progress.report('compare_' + identity + '_' + label)
                db.execute(f'CREATE TABLE {label}(id TEXT PRIMARY KEY NOT NULL, document_id TEXT, kind TEXT, kind_source TEXT, role TEXT, evidence TEXT, representative TEXT, filename TEXT, source_url TEXT)')
                file = pq.ParquetFile(path)
                needed = PROTECTED | {'document_id', 'source_id', 'document_kind', 'document_kind_source', 'record_role', 'body_keys', 'filenames', 'source_urls'}
                selected = sorted(needed & set(file.schema_arrow.names))
                rows = 0
                for batch in file.iter_batches(columns=selected, batch_size=1024):
                    values = []
                    for row in batch.to_pylist():
                        if not row.get(identity):
                            raise ValueError('Missing comparison identity')
                        values.append((row[identity], row['document_id'], encode(row.get('document_kind') or []),
                            encode(row.get('document_kind_source') or []), encode(row.get('record_role') or []),
                            protected_hash(row, document), row.get('source_id'), row.get('filename'), row.get('source_url')))
                    db.executemany(f'INSERT INTO {label} VALUES (?,?,?,?,?,?,?,?,?)', values)
                    rows += len(values)
                counts[label] = rows
            missing = db.execute('SELECT count(*) FROM before_rows b LEFT JOIN after_rows a USING(id) WHERE a.id IS NULL').fetchone()[0]
            added = db.execute('SELECT count(*) FROM after_rows a LEFT JOIN before_rows b USING(id) WHERE b.id IS NULL').fetchone()[0]
            changes = Counter()
            columns = ['id', 'document_id', 'filename', 'source_url', 'change', 'before_kind', 'after_kind',
                       'before_kind_source', 'after_kind_source', 'before_role', 'after_role', 'protected_evidence_changed',
                       'document_id_changed', 'representative_changed']
            with output.open('x', newline='') as stream:
                writer = csv.writer(stream); writer.writerow(columns)
                query = '''SELECT b.id,a.document_id,a.filename,a.source_url,b.kind,a.kind,b.kind_source,a.kind_source,
                           b.role,a.role,b.evidence!=a.evidence,b.document_id!=a.document_id,b.representative!=a.representative
                           FROM before_rows b JOIN after_rows a USING(id)
                           WHERE b.kind!=a.kind OR b.kind_source!=a.kind_source OR b.role!=a.role
                           OR b.evidence!=a.evidence OR b.document_id!=a.document_id OR b.representative!=a.representative
                           ORDER BY b.id'''
                for row in db.execute(query):
                    old, new = row[4], row[5]
                    change = ('new_assignment' if old == '[]' else 'removed_assignment' if new == '[]' else 'changed_prior_kind') if old != new else 'other_metadata'
                    changes[change] += 1
                    for label, changed in [('role_changed', row[8] != row[9]), ('protected_evidence_changed', row[10]),
                                           ('document_id_changed', row[11]), ('representative_changed', row[12]),
                                           ('kind_source_changed', row[6] != row[7])]:
                        changes[label] += bool(changed)
                    writer.writerow([*row[:4], change, *row[4:]])
                for side, other, change in [('before_rows', 'after_rows', 'missing_id'), ('after_rows', 'before_rows', 'added_id')]:
                    for row in db.execute(f'SELECT s.id,s.document_id,s.filename,s.source_url FROM {side} s LEFT JOIN {other} o USING(id) WHERE o.id IS NULL ORDER BY s.id'):
                        writer.writerow([*row, change, *[''] * 9])
            counts.update(missing_ids=missing, added_ids=added, changes=dict(changes), changes_sha256=file_digest(output))
            counts['identities_roles_evidence_preserved'] = not (missing or added or any(changes[k] for k in
                ['role_changed', 'protected_evidence_changed', 'document_id_changed']))
            counts['prior_kind_changes'] = changes['changed_prior_kind'] + changes['removed_assignment']
            return counts
        except sqlite3.IntegrityError as error:
            raise ValueError('Duplicate comparison identity') from error
        finally:
            db.close()


def refused_body(key):
    raise RuntimeError('Filename-only replay attempted to read a retained body: ' + str(key))


def run(catalog_root, output, *, publication_dir=None, rehearsal=False, workers=3):
    catalog_root, output = Path(catalog_root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    index.progress.report('validate_replay_input')
    source_path, document_path = local_catalog_paths(catalog_root)
    index.validate_document_indexes(source_path, document_path)
    source, documents = pq.ParquetFile(source_path), pq.ParquetFile(document_path)
    meta = {k.decode(): v.decode() for k, v in (source.schema_arrow.metadata or {}).items()}
    gate = publication_gate(publication_dir, catalog_root, meta)
    if not rehearsal and not gate['verified']:
        raise ValueError('Verified 3.1.0 publication is required; historical input needs explicit --rehearsal')
    if index.__version__ != '3.2.1':
        raise ValueError('This comparison is scoped to filename version 3.2.1')
    required = RESERVE + 8 * (source_path.stat().st_size + document_path.stat().st_size)
    allocation_parent = output.parent
    while not allocation_parent.exists():
        allocation_parent = allocation_parent.parent
    if shutil.disk_usage(allocation_parent).free < required:
        raise ValueError('Insufficient free disk for isolated catalog replay and reserve')
    output.mkdir(parents=True)
    inputs = {label: dict(path=str(path), sha256=file_digest(path), rows=pq.ParquetFile(path).metadata.num_rows)
              for label, path in [('filenames', source_path), ('documents', document_path)]}
    source_hash = file_digest(index.__file__)
    fingerprint = index.parser_fingerprint()
    manifest = dict(input_catalog_id=meta['catalog_id'], input_naming_version=meta.get('house_naming_version'),
        target_naming_version=index.__version__, inputs=inputs, publication=gate, rehearsal=rehearsal,
        filename_fingerprint=fingerprint, index_source_sha256=source_hash, evaluator_sha256=file_digest(__file__),
        acquisition=False, body_reinspection=False, publication_performed=False)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    isolated = output / 'catalog'
    (isolated / 'indexes').mkdir(parents=True)
    rows, metadata = index.filename_refresh_inputs(source)

    def guarded_rows():
        for number, row in enumerate(rows):
            if number % 4096 == 0 and shutil.disk_usage(output).free < RESERVE:
                raise RuntimeError('Disk reserve reached; partial isolated output retained')
            yield row

    started = time.monotonic()
    with TemporaryDirectory(prefix='replay-working-', dir=output) as temporary:
        working = WorkingCatalog(Path(temporary) / 'working.sqlite')
        try:
            built = index.write_filename_metadata(isolated, guarded_rows(), workers=workers,
                previous=source, previous_documents=documents, reuse_results=False, inspect_bodies=False,
                read_body=refused_body, working=working, output_root=isolated, metadata=metadata)
        finally:
            working.close()
    after_source, after_documents = local_catalog_paths(isolated)
    index.validate_document_indexes(after_source, after_documents)
    comparisons = {label: compare_table(before, after, output / (label + '-changes.csv'), document=label == 'documents')
                   for label, before, after in [('filenames', source_path, after_source), ('documents', document_path, after_documents)]}
    # Re-read the selection and bytes: no moving baseline may be qualified.
    current = local_catalog_paths(catalog_root)
    if current != (source_path, document_path) or any(file_digest(Path(item['path'])) != item['sha256'] for item in inputs.values()):
        raise ValueError('Input catalog changed during replay')
    if index.parser_fingerprint() != fingerprint or file_digest(index.__file__) != source_hash:
        raise ValueError('Filename implementation changed during replay')
    if publication_gate(publication_dir, catalog_root, meta) != gate:
        raise ValueError('Publication evidence changed during replay')
    result = dict(manifest, comparisons=comparisons, build=built,
                  output_files={label: dict(path=str(path), sha256=file_digest(path), rows=pq.ParquetFile(path).metadata.num_rows)
                                for label, path in [('filenames', after_source), ('documents', after_documents)]},
                  input_bytes_unchanged=True, completed=True, elapsed_seconds=round(time.monotonic() - started, 2),
                  invariants_preserved=all(c['identities_roles_evidence_preserved'] for c in comparisons.values()),
                  changed_prior_kinds_need_review=sum(c['prior_kind_changes'] for c in comparisons.values()),
                  release_qualified=False,
                  limitation='Complete retained-pair filename replay only. Any identity/role/evidence change or prior-kind change needs review. Historical rehearsals do not qualify the new publication; no automatic release.')
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--publication-dir', type=Path)
    parser.add_argument('--rehearsal', action='store_true')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=3)
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s %(progress)s', defaults={'progress': None}))
    index.progress.LOGGER.addHandler(handler)
    index.progress.LOGGER.setLevel(logging.INFO)
    run(args.catalog_root, args.output, publication_dir=args.publication_dir, rehearsal=args.rehearsal, workers=args.workers)
