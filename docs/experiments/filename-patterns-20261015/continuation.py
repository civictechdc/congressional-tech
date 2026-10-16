"""Freeze native-format checks, association diagnostics and a blind PDF pilot.

This experiment never changes capture state or production classifications.
Run prepare before fetching or reviewing any selected body.
"""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import pyarrow.parquet as pq

from rule_review import DEFAULT_INPUT, digest
from congress_api.parsers.document_links import http_url
from congress_api.parsers.document_types import document_label_kind

SEED = 'kind-continuation-20261015-v1'


def rank(value):
    return hashlib.sha256((SEED + value).encode()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def compact(row):
    return {k: row.get(k) for k in ('document_id', 'filename', 'source_url', 'source_urls', 'body_keys')}


def native_family(row):
    name = row['filename']
    if re.fullmatch(r'PLAW-\d{3}publ[1-9]\d*\.pdf', name, re.I):
        return 'public-law'
    if re.fullmatch(r'(?:h|s|hc|sc|hj|sj)[1-9]\d*(?:fs|nr|ew)?[_-][a-z]+[_-]xml\.pdf', name, re.I):
        return 'short-measure'
    if re.fullmatch(r'\d{3}-[1-9]\d*\.pdf', name, re.I):
        return 'numbered-pdf'


def filename_family(name):
    stem = Path(name).stem
    if re.fullmatch(r'[\d_. -]+', stem):
        return 'numbers-and-dates'
    if re.search(r'[a-f\d]{24,}', stem, re.I):
        return 'opaque-prefix'
    if re.search(r'(?:memo|testimony|statement|amend|vote|report|letter|notice|transcript)', stem, re.I):
        return 'genre-word'
    return 'other-name'


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    frozen = DEFAULT_INPUT / 'documents.parquet'
    baseline = DEFAULT_INPUT / 'integration-v3/results.jsonl.gz'
    unresolved = {r['document_id'] for line in gzip.open(baseline, 'rt')
                  if (r := json.loads(line))['status'] == 'unresolved'}
    native, variants, pdfs = defaultdict(list), [], []
    fields = ['document_id', 'filename', 'source_url', 'source_urls', 'body_keys', 'format', 'source_occurrences']
    for batch in pq.ParquetFile(frozen).iter_batches(columns=fields):
        for row in batch.to_pylist():
            if row['document_id'] not in unresolved:
                continue
            if family := native_family(row):
                native[family].append(compact(row))
            if Path(row['filename']).suffix.lower() == '.pdf' or 'pdf' in (row.get('format') or []):
                pdfs.append(compact(row))
            for number, occurrence in enumerate(row.get('source_occurrences') or []):
                if (occurrence.get('source_occurrence_scope') != ['anchor']
                        or 'user_accepted_url_variant' not in (occurrence.get('source_association_basis') or [])):
                    continue
                kinds = sorted({kind for label in occurrence.get('source_link_label') or []
                                if (kind := document_label_kind(label))})
                if kinds:
                    variants.append(dict(compact(row), occurrence_index=number, proposed_kinds=kinds,
                                         occurrence={k: v for k, v in occurrence.items() if v}))

    # A grouped table can suggest a match, but only receipt-level URL/body pairs
    # can establish it. Keep grouped matches diagnostic, never trusted automatically.
    targets = {http_url(u) for r in variants for u in r['occurrence'].get('source_link_url') or []}
    targets.discard(None)
    matches = defaultdict(list)
    for batch in pq.ParquetFile(frozen).iter_batches(columns=['document_id', 'source_urls', 'body_keys']):
        for row in batch.to_pylist():
            for url in set(row.get('source_urls') or []):
                if (normalized := http_url(url)) in targets:
                    matches[normalized].append(row)
    for row in variants:
        row['grouped_url_matches'] = [m for u in row['occurrence'].get('source_link_url') or []
                                      for m in matches.get(http_url(u), [])]
        row['status'] = 'needs_receipt_check' if row['grouped_url_matches'] else 'original_url_not_in_frozen_sources'

    save(output / 'association-candidates.json', variants)
    save(output / 'native-candidates.json', dict(native))
    selected = {}
    for family, rows in native.items():
        # Three per publisher and observed filename variant, selected before availability.
        pools = defaultdict(list)
        for row in rows:
            host = (urlsplit(row['source_url']).hostname or '').removeprefix('www.')
            modifier = 'modified' if re.search(r'\d(?:fs|nr|ew)[_-]', row['filename'], re.I) else 'plain'
            pools[(host, modifier)].append(row)
        for (host, modifier), pool in sorted(pools.items()):
            for row in sorted(pool, key=lambda r: rank(r['document_id']))[:3]:
                selected.setdefault(row['document_id'], dict(row, selection=[]))['selection'].append(f'{family}/{host}/{modifier}')
    content = output / 'native-content'
    content.mkdir()
    save(content / 'sample.json', dict(seed=SEED, method='Three hash-ranked records per native family, publisher and modifier stratum, before availability checks. Not a precision estimate.', records=list(selected.values())))

    # No prefilled guesses in the human review sheet. Balance publishers and
    # filename families; allow one record per retained body across both splits.
    reviewed_bodies = set()
    for sample in DEFAULT_INPUT.glob('*content*/sample.json'):
        for row in json.loads(sample.read_text()).get('records', []):
            reviewed_bodies.update(row.get('body_keys') or [])
    reviewed_bodies.update(k for row in selected.values() for k in row.get('body_keys') or [])
    pools = defaultdict(list)
    for row in pdfs:
        if native_family(row) or reviewed_bodies.intersection(row.get('body_keys') or []):
            continue
        host = (urlsplit(row['source_url']).hostname or '').removeprefix('www.')
        stratum = (host, filename_family(row['filename']), 'retained' if row.get('body_keys') else 'missing-body')
        pools[stratum].append(row)
    for rows in pools.values():
        rows.sort(key=lambda r: rank(r['document_id']), reverse=True)
    pilot, seen = [], set(reviewed_bodies)
    while len(pilot) < 400 and pools:
        for stratum in sorted(list(pools)):
            row = pools[stratum].pop()
            if not pools[stratum]:
                del pools[stratum]
            keys = set(row.get('body_keys') or [])
            if keys & seen:
                continue
            seen.update(keys)
            pilot.append(dict(row, stratum=list(stratum), text_availability='not_checked'))
            if len(pilot) == 400:
                break
    # Selection never consults kind labels or availability. Randomize the split
    # after stratified selection, with no duplicate retained body across splits.
    for n, row in enumerate(sorted(pilot, key=lambda r: rank('split/' + r['document_id']))):
        row['split'] = 'development' if n % 2 == 0 else 'held-out'
    save(output / 'pilot.json', dict(seed=SEED, method='Round-robin publisher/filename/body-presence strata, hash-ranked within strata, 400 records. Excludes native candidates and prior reviewed bodies. One selected record per retained body. Not a population-weighted sample.', records=pilot))
    with (output / 'pilot-review.csv').open('w', newline='') as stream:
        fields = ['document_id', 'filename', 'source_url', 'split', 'text_availability', 'reviewed_kind', 'evidence_page', 'evidence_quote', 'reviewer', 'notes']
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(pilot)
    stats = dict(input_sha256=digest(frozen), baseline_sha256=digest(baseline),
                 unresolved=len(unresolved), native_candidates={k: len(v) for k, v in native.items()},
                 native_sample=len(selected), association_records=len({r['document_id'] for r in variants}),
                 association_occurrences=len(variants), association_status=dict(Counter(r['status'] for r in variants)),
                 pilot_records=len(pilot), pilot_splits=dict(Counter(r['split'] for r in pilot)),
                 pilot_strata=len({tuple(r['stratum']) for r in pilot}),
                 scope='Frozen experiment population; refresh against the completed public rebuild before production application.')
    save(output / 'preparation.json', stats)
    print(json.dumps(stats, indent=2))


def prepare_boundaries(output):
    """Expand numeric publisher checks across Congress/path strata before promotion."""
    native = json.loads((output / 'native-candidates.json').read_text())
    previous = {r['document_id'] for r in json.loads((output / 'native-content/sample.json').read_text())['records']}
    pools = defaultdict(list)
    for row in native['numbered-pdf']:
        if row['document_id'] in previous or urlsplit(row['source_url']).hostname != 'financialservices.house.gov':
            continue
        key = row['filename'].split('-')[0] + '/' + str('/media/' in row['source_url'])
        pools[key].append(row)
    for row in native['short-measure']:
        if '_sus_' in row['filename'].lower():
            pools['short-sus'].append(row)
    selected = []
    for key, rows in sorted(pools.items()):
        ordered = sorted(rows, key=lambda r: hashlib.sha256(('native-boundary-20261015' + r['document_id']).encode()).hexdigest())
        selected.extend(dict(row, selection=[key]) for row in ordered[:2])
    path = output / 'native-boundary-content'
    path.mkdir(exist_ok=False)
    save(path / 'sample.json', dict(method='Two fresh hash-ranked examples per Financial Services serial-Congress/path stratum, plus two SUS controls, selected before availability.', records=selected))


def audit_capture_index(output, source):
    """Retain exact URL/body evidence and the age of a supplied local snapshot."""
    candidates = json.loads((output / 'association-candidates.json').read_text())
    targets = {http_url(u) for r in candidates for u in r['occurrence'].get('source_link_url') or []}
    matches, latest, earliest = [], '', None
    fields = ['context_url', 'body_key', 'http_status', 'receipt_key', 'receipt_line', 'retrieved_at']
    for batch in pq.ParquetFile(source).iter_batches(columns=fields):
        for row in batch.to_pylist():
            when = str(row.get('retrieved_at') or '')
            if when:
                latest = max(latest, when)
                earliest = min(earliest, when) if earliest else when
            if http_url(row['context_url']) in targets:
                matches.append({k: str(v) if k == 'retrieved_at' and v else v for k, v in row.items()})
    save(output / 'local-capture-audit.json', dict(source=str(source), sha256=digest(source),
        rows=pq.ParquetFile(source).metadata.num_rows, earliest_retrieved_at=earliest,
        latest_retrieved_at=latest, matches=matches,
        limitation='This local capture snapshot may predate the candidate associations; missing matches do not prove absence from current retained storage.'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--boundaries', action='store_true')
    parser.add_argument('--capture-index', type=Path)
    args = parser.parse_args()
    if args.capture_index:
        audit_capture_index(args.output, args.capture_index)
    elif args.boundaries:
        prepare_boundaries(args.output)
    else:
        prepare(args.output)
