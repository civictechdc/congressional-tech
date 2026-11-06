"""Read-only campaign progress from the existing target ledger and import operations.

An acknowledged import is not a published attachment or a new semantic document.
Final state belongs to a separate descriptor; execution bindings never change.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.parquet as pq

from congress_shared.campaign import load_campaign
from congress_shared.custody import bounded_control_read, canonical_json_bytes, write_atomic_bytes
from congress_api.retention.provenance import file_pin, parquet_output, run_job
from corpus_recovery.acceptance import VERSION
from corpus_recovery.campaign import plan


def _read(path):
    path = Path(path).resolve()
    with path.open('rb') as stream:
        raw = bounded_control_read(stream)
    return json.loads(raw), dict(path=str(path), sha256=sha256(raw).hexdigest(), size=len(raw))


def _operation(path, campaign):
    root = Path(path)
    binding, binding_pin = _read(root / 'binding.json')
    fields = {'descriptor_sha256', 'request_sha256', 'policy'}
    if (set(binding) not in (fields, fields | {'identity_note_policy'})
            or binding['descriptor_sha256'] != campaign.descriptor_sha256
            or binding['policy'] != VERSION
            or ('identity_note_policy' in binding and
                (not isinstance(binding['identity_note_policy'], str) or not binding['identity_note_policy'].strip()))
            or not isinstance(binding['request_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', binding['request_sha256'])):
        raise ValueError('Import operation does not bind the original descriptor and request')
    operation_id = sha256(canonical_json_bytes(binding)).hexdigest()
    row = dict(operation_id=operation_id, status='incomplete', target_url=None,
               candidate_url=None, body_sha256=None, qualification_sha256=None,
               receipt_key=None, provenance_key=None)
    pins = [binding_pin]
    result_path = root / 'result.json'
    if not result_path.exists():
        return row, pins
    result, result_pin = _read(result_path)
    pins.append(result_pin)
    if result.get('status') not in {'accepted', 'rejected', 'review_required'}:
        raise ValueError('Unknown import result status')
    row['status'] = result['status']
    evidence_path = root / 'identity-evidence.json'
    if evidence_path.exists():
        evidence, evidence_pin = _read(evidence_path)
        pins.append(evidence_pin)
        if (evidence_pin['sha256'] != result.get('evidence_sha256')
                or evidence.get('version') != VERSION
                or evidence.get('requirement') != campaign.requirement):
            raise ValueError('Import identity evidence differs from its result or requirement')
        row.update(target_url=evidence['target']['url'], candidate_url=evidence['candidate']['url'],
                   body_sha256=evidence['body_sha256'], qualification_sha256=evidence['qualification_sha256'])
    if row['status'] == 'accepted':
        decision = result.get('decision', {})
        if (not evidence_path.exists() or decision.get('id') != operation_id
                or decision.get('acceptance_status') != 'accepted'
                or decision.get('acceptance_policy') != VERSION
                or decision.get('target_requirement') != campaign.requirement
                or any(decision.get(k) != row[v] for k, v in (
                    ('original_url', 'target_url'), ('recovered_url', 'candidate_url'),
                    ('body_sha256', 'body_sha256'), ('qualification_sha256', 'qualification_sha256')))
                or decision.get('evidence_sha256') != result.get('evidence_sha256')
                or not all(isinstance(result.get(k), str) and result[k] for k in ('receipt_key', 'provenance_key'))):
            raise ValueError('Accepted import lacks its acknowledged original operation bindings')
        row.update(receipt_key=result['receipt_key'], provenance_key=result['provenance_key'])
    return row, pins


def report_campaign(descriptor, *, output, engine, operation_dirs=(), final_descriptor=None,
                    release_comparison=None):
    """Join initial/final target ledgers to imports without acquisition or raw writes.

    ``final_descriptor`` may change only state/profile/requirements pins. It must
    be a different file. The release comparison must name both releases and pin
    the original descriptor via its maintained ``--record-digest`` option.
    """
    campaign = load_campaign(descriptor)
    root = Path(output)
    initial_root = Path(descriptor).parent / 'plan'
    initial = plan(descriptor, output=initial_root, engine=engine)
    initial_counts, counts_pin = _read(initial_root / 'counts.json')
    inputs = [dict(name='initial_ledger', kind='parquet', path=str(initial_root / 'url-dispositions.parquet'))]
    final, final_counts = None, None
    if final_descriptor is not None:
        if Path(final_descriptor).resolve() == Path(descriptor).resolve():
            raise ValueError('Final state requires a separate read-only descriptor')
        updated = load_campaign(final_descriptor)
        state_tables = {'state', 'state_profile', 'state_requirements'}
        original_tables = {k: v.sha256 for k, v in campaign.tables.items() if k not in state_tables}
        final_tables = {k: v.sha256 for k, v in updated.tables.items() if k not in state_tables}
        if (updated.campaign_id != campaign.campaign_id or updated.requirement != campaign.requirement
                or updated.target_table != campaign.target_table or updated.candidate_table != campaign.candidate_table
                or original_tables != final_tables or not state_tables.issubset(updated.tables)):
            raise ValueError('Final plan must preserve original membership, candidates and requirement')
        final = plan(final_descriptor, output=root / 'final-plan', engine=engine)
        final_counts, _ = _read(root / 'final-plan/counts.json')
        inputs.append(dict(name='final_ledger', kind='parquet',
                           path=str(root / 'final-plan/url-dispositions.parquet')))
    comparison = None
    if release_comparison is not None:
        value, pin = _read(release_comparison)
        if (not final or not value.get('base_release') or not value.get('candidate_release')
                or not any(p.get('sha256') == campaign.descriptor_sha256 for p in value.get('inputs', []))):
            raise ValueError('Release comparison must name both releases and pin the execution descriptor after final planning')
        comparison = dict(pin=pin, base_release=value['base_release'], candidate_release=value['candidate_release'],
                          comparison_ok=value['ok'])
    rows, operation_pins, seen = [], [], {}
    for directory in operation_dirs:
        row, pins = _operation(directory, campaign)
        if row['operation_id'] in seen:
            if seen[row['operation_id']] != row:
                raise ValueError('Conflicting results for the same import operation')
            continue
        seen[row['operation_id']] = row
        rows.append(row)
        operation_pins.extend(pins)
    root.mkdir(parents=True, exist_ok=True)
    operations = root / 'import-operations.parquet'
    schema = pa.schema([(k, pa.string()) for k in (
        'operation_id', 'status', 'target_url', 'candidate_url', 'body_sha256',
        'qualification_sha256', 'receipt_key', 'provenance_key')])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), operations)
    inputs.append(dict(name='import_operations', kind='parquet', path=str(operations)))
    steps = [] if final else [dict(name='final_ledger', sql='SELECT * FROM initial_ledger WHERE false')]
    joined = '''SELECT i.target_url,i.disposition AS initial_disposition,
        f.disposition AS final_disposition,o.operation_id,o.status AS import_status,
        o.candidate_url,o.body_sha256,o.qualification_sha256,o.receipt_key,o.provenance_key
        FROM initial_ledger i LEFT JOIN final_ledger f ON i.target_url=f.target_url
        LEFT JOIN import_operations o ON i.target_url=o.target_url'''
    outputs = [parquet_output(root, 'target-progress', joined, ['target_url', 'operation_id'])]
    reports = run_job(root / 'native-progress', engine, inputs=inputs, steps=steps, outputs=outputs, queries=[
        dict(name='operations', sql='SELECT status,count(*) AS operations FROM import_operations GROUP BY status ORDER BY status'),
        dict(name='imports', sql="""SELECT count(*) AS acknowledged_import_operations,
            count(DISTINCT target_url) AS accepted_targets,count(DISTINCT body_sha256) AS distinct_qualified_imported_bodies,
            count(DISTINCT receipt_key) AS acknowledged_receipt_keys,
            count(DISTINCT provenance_key) AS acknowledged_provenance_keys
            FROM import_operations WHERE status='accepted'"""),
        dict(name='relationships', sql="""SELECT count(*) AS accepted_target_body_relationships FROM
            (SELECT target_url,body_sha256 FROM import_operations WHERE status='accepted' GROUP BY target_url,body_sha256)"""),
        dict(name='invariants', sql='''SELECT
            (SELECT count(*) FROM import_operations WHERE target_url IS NULL) AS unmapped_operations,
            (SELECT count(*) FROM import_operations o LEFT JOIN initial_ledger i ON o.target_url=i.target_url
                WHERE o.target_url IS NOT NULL AND i.target_url IS NULL) AS outside_operations''')])
    if reports['invariants'][0]['outside_operations']:
        raise ValueError('Import result names a target outside the original campaign')
    campaign.require_custody()
    if final:
        updated.require_custody()
    report = dict(version=1, read_only=True, execution_descriptor_sha256=campaign.descriptor_sha256,
                  initial_plan=initial, initial_counts=initial_counts, initial_counts_pin=counts_pin,
                  final_plan=final, final_counts=final_counts, operation_inputs=operation_pins,
                  import_counts=reports, target_progress=dict(path=str(root / 'target-progress.parquet'),
                      **file_pin(root / 'target-progress.parquet')),
                  unmapped_operations=[r for r in rows if r['target_url'] is None],
                  release_comparison=comparison,
                  publication_counts=dict(attached_occurrences=None, distinct_document_rows=None,
                                          newly_verified_semantic_documents=None),
                  limits=['Import acknowledgements do not establish selected capture/provenance membership or publication.',
                          'Only supplied operation directories are assessed; a target with no supplied operation has unknown import progress.',
                          'Release comparison is release-wide; verify cohort target/body attachments through the reader and MCP.',
                          'Semantic equivalence and publication gains remain unknown without separate evidence.'])
    write_atomic_bytes(root / 'progress.json', canonical_json_bytes(report) + b'\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--operation', action='append', default=[])
    parser.add_argument('--final-campaign')
    parser.add_argument('--release-comparison')
    args = parser.parse_args(argv)
    from docspec_client.client import NativeDatasets
    result = report_campaign(args.campaign, output=args.output,
                             engine=NativeDatasets.from_config(args.runtime), operation_dirs=args.operation,
                             final_descriptor=args.final_campaign, release_comparison=args.release_comparison)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
