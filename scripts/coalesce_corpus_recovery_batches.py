"""Seal completed local batches into one import/publication unit, without network I/O.

Only each batch's newly recovered URL/body pairs change the provided mapping
baseline. Historical rows copied into older accepted.json files are ignored.
Original batches and their receipts remain unchanged and digest-bound.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from reconcile_corpus_recovery_bodies import digest, sealed_inputs


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def publication_due(manifests, *, now=None, max_wait_seconds=900, minimum_urls=100):
    if not manifests:
        return False
    if max_wait_seconds <= 0 or minimum_urls <= 0:
        raise ValueError('Cadence limits must be positive')
    now = now or datetime.now(timezone.utc)
    oldest = min(datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')) for row in manifests)
    if oldest.tzinfo is None or now.tzinfo is None:
        raise ValueError('Use timezone-aware batch timestamps')
    return (sum(row['recovered_urls'] for row in manifests) >= minimum_urls
            or (now-oldest).total_seconds() >= max_wait_seconds)


def coalesce(batches, *, baseline, destination):
    batches = [Path(batch).resolve() for batch in batches]
    if not batches or len(set(batches)) != len(batches):
        raise ValueError('Supply distinct nonempty completed batches')
    baseline = Path(baseline).resolve()
    baseline_value = json.loads(baseline.read_text())
    accepted = {row['original_url']: row for row in baseline_value['recoveries']}
    if len(accepted) != len(baseline_value['recoveries']):
        raise ValueError('Duplicate baseline mapping')
    recovered, bodies, additions, records, zips, inputs = {}, {}, {}, {}, {}, {}
    for batch in batches:
        files, inventory, counts = sealed_inputs(batch)
        inputs[str(batch)] = dict(files=files, counts=counts)
        candidates = json.loads((batch/'accepted.json').read_text())['recoveries']
        pairs = {}
        for candidate in candidates:
            pair = candidate['original_url'], candidate['body_key']
            if pair in pairs and pairs[pair] != candidate:
                raise ValueError('Conflicting accepted mapping metadata')
            pairs[pair] = candidate
        for row in json.loads((batch/'recoveries.json').read_text()):
            url, key = row['original_url'], row['body_key']
            if not row.get('validated') or (url, key) not in pairs:
                raise ValueError('Batch recovery lacks a validated accepted mapping')
            if url in recovered and recovered[url]['body_key'] != key:
                raise ValueError('Conflicting recovered bodies for one URL')
            recovered.setdefault(url, row)
            additions.setdefault(url, pairs[url, key])
        for key, value in inventory.items():
            if key in bodies and any(bodies[key][field] != value[field] for field in ('sha256', 'bytes')):
                raise ValueError('Conflicting body identity')
            bodies.setdefault(key, value)
        for name, target in [('prepared-source-records.json', records), ('zip-receipts.json', zips)]:
            for row in json.loads((batch/name).read_text()):
                target.setdefault(canonical(row), row)
    accepted.update(additions)
    accepted_value = dict(baseline_value, recoveries=list(accepted.values()))
    values = {'recoveries.json': list(recovered.values()), 'bodies.json': bodies,
              'accepted.json': accepted_value, 'zip-receipts.json': list(zips.values()),
              'coalescing.json': dict(baseline=str(baseline), baseline_sha256=digest(baseline),
                  inputs=inputs, receipt_records=sum(v['counts']['receipt_records'] for v in inputs.values()),
                  distinct_receipt_records=len(records)+len(zips),
                  mapping_rule='only_new_recovered_url_body_pairs_overlay_baseline')}
    destination = Path(destination).resolve(); destination.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        (destination/name).write_text(json.dumps(value, indent=2)+'\n')
    for name, value in values.items():write(name,value)
    manifest = dict(created_at=datetime.now(timezone.utc).isoformat(),
        status='validated_local_batch_not_imported_or_published', recovered_urls=len(recovered),
        zip_parents=len(zips), distinct_bodies=len(bodies), input_batches=len(batches),
        files={name:digest(destination/name) for name in values},
        publication_requires=['fresh_cloud_clear','local_recovery_lock','fresh_input_versions_and_rebase',
                              'conditional_publication','remote_readback'])
    write('manifest.json',manifest)
    write('prepared-source-records.json',list(records.values()))
    write('source-record-preparation.json',dict(unresolved=[],
        batch_manifest_sha256=digest(destination/'manifest.json'),
        source_batches=inputs, prepared_records=len(records)))
    # Reuse the same readiness coverage check, without loading any body payload.
    sealed_inputs(destination)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,action='append',required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(coalesce(args.batch,baseline=args.baseline,destination=args.destination),indent=2))
