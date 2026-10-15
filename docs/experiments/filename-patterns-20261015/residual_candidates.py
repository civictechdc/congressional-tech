"""Select held-out body checks for bounded residual filename/source conventions."""
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import pyarrow.parquet as pq
from congress_api.retention import document_index as index
from rule_review import DEFAULT_INPUT

FILENAME_RULES = [
    ('transportation-ssm', ['transportation.house.gov', 'democrats-transportation.house.gov', 'archives113-transportation.house.gov'],
     r'(?!.*addendum).*?(?P<document_wording>(?<![a-z])ssm(?![a-z])).*', 'committee-memorandum'),
    ('financial-meeting-memo', ['financialservices.house.gov', 'democrats-financialservices.house.gov'],
     r'\d[\d._-]{5,10}[_.-]+(?P<document_wording>(?:(?:fc|tf|housing|meeting|markup)[_.-]+)+memo)', 'committee-memorandum'),
    ('resources-joined-testimony', ['naturalresources.house.gov'],
     r'(?P<document_wording>(?:\d[\d_.-]*testimony[a-z]+|[a-z]+testimony[\d_.-]+))', 'testimony'),
    ('joint-committee-mstate', ['energycommerce.house.gov', 'archives-energycommerce.house.gov'],
     r'HHRG-\d{3}-IF\d{2}-IF\d{2}-(?P<document_wording>MState)-[A-Z]\d{6}-\d{8}(?:-\d+)?', 'member-statement'),
]


def added_label(label):
    value = ' '.join(label.split()).casefold().strip(' :»')
    if value in {'updated: subcommittee hearing notice', 'official hearing notice'}:
        return 'meeting-notice'
    if value in {'a preliminary transcript of this hearing is now available.',
                 'a transcript of this hearing is now available.'}:
        return 'transcript'
    # Designation grammar, not arbitrary sentences mentioning amendments.
    if re.fullmatch(r'amendment\s*#?\s*\d+[a-z]?(?:\s+to\s+(?:h\.?r\.?|s\.?)\s*\d+)?\s+(?:offered\s+)?by\s+(?:mr\.?|ms\.?|mrs\.?|rep\.?)\s+[^.!?]+', value):
        return 'amendment'
    return None


def main():
    output = DEFAULT_INPUT / 'residual-content-v1'
    output.mkdir(exist_ok=False)
    unresolved = {r['document_id'] for line in gzip.open(DEFAULT_INPUT / 'integration-v2/results.jsonl.gz', 'rt')
                  if (r := json.loads(line))['status'] == 'unresolved'}
    groups = {}
    previous = index.document_label_kind
    index.document_label_kind = lambda value: previous(value) or added_label(value)
    for batch in pq.ParquetFile(DEFAULT_INPUT / 'documents.parquet').iter_batches():
        for row in batch.to_pylist():
            if row['document_id'] not in unresolved:
                continue
            host = (urlsplit(row.get('source_url') or '').hostname or '').removeprefix('www.')
            stem = Path(row['filename']).stem
            for name, hosts, pattern, kind in FILENAME_RULES:
                if host in hosts and Path(row['filename']).suffix.casefold() == '.pdf' and re.fullmatch(pattern, stem, re.I):
                    groups.setdefault(name, []).append(dict(row, proposed_kinds=[kind]))
            kind = index.publisher_anchor_kind(row)
            if kind:
                groups.setdefault('label-' + kind, []).append(dict(row, proposed_kinds=[kind]))
    records = {}
    for name, rows in groups.items():
        ordered = sorted(rows, key=lambda r: hashlib.sha256(('residual-heldout-20261015' + r['document_id']).encode()).hexdigest())
        for row in ordered[:3]:
            records.setdefault(row['document_id'], dict(row, selection=[]))['selection'].append(name)
    (output / 'sample.json').write_text(json.dumps({'method':'Hash-ranked three per residual rule, before availability checks.',
        'candidate_counts':{k:len(v) for k,v in groups.items()}, 'records':list(records.values())}, indent=2)+'\n')
    print({k:len(v) for k,v in groups.items()})
    for n, row in enumerate(records.values(), 1):
        print(n, row['filename'], row['selection'])


if __name__ == '__main__':
    main()
