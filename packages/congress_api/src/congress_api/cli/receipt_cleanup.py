"""Scan or rewrite an explicit receipt inventory; default is a read-only scan.

The owner must approve the report's two patterns and drain all older writers
before --apply. Local fixtures and private backups use directory roots that
contain receipts/. The R2 adapter is only for the owner's one-time live run.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
from uuid import uuid4

from congress_api.retention.receipt_cleanup import digest, rewrite_receipt
from congress_api.retention.receipt_cleanup_stores import DirectoryFiles, R2ReceiptFiles
from congress_api.retention.receipt_privacy import LOCAL_PATH, clean_older_line


def local_keys(root):
    return sorted(p.relative_to(root).as_posix() for p in (root / 'receipts').rglob('*.jsonl.gz'))


def scan(root, keys):
    """Count matches by JSON path without recording any sensitive header value."""
    fields, examples = Counter(), {}
    receipts, lines, sizes, affected = 0, 0, 0, 0
    for key in keys:
        file_fields = Counter()
        path = root / key
        with gzip.open(path, 'rb') as source:
            for number, encoded in enumerate(source, 1):
                try:
                    _, cuts = clean_older_line(json.loads(encoded))
                except (ValueError, TypeError):
                    raise ValueError(f'{key} line {number}: uncleanable receipt') from None
                file_fields.update(cuts)
                lines += 1
        for (kind, field_path, example), count in file_fields.items():
            fields[kind, field_path] += count
            samples = examples.setdefault((kind, field_path), set())
            samples.add(example)
            if len(samples) > 3:
                samples.remove(max(samples))
        receipts += 1
        sizes += path.stat().st_size
        affected += bool(file_fields)
    totals = Counter()
    for (kind, _), count in fields.items():
        totals[kind] += count
    return dict(patterns=dict(header='case-insensitive authorization or name ending in cookie, as a key or header item',
                              local_path=LOCAL_PATH.pattern),
                receipts=receipts, compressed_bytes=sizes, lines=lines, affected_receipts=affected,
                counts=dict(totals),
                fields=[dict(kind=k, path=p, examples=sorted(examples[k, p]), count=n)
                        for (k, p), n in sorted(fields.items())])

def receipt_inventory(client, bucket):
    """List every receipt once, retaining metadata for the owner's frozen input."""
    entries = []
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix='receipts/'):
        for row in page.get('Contents', []):
            if not row['Key'].endswith('.jsonl.gz'):
                raise ValueError('Unexpected receipt object; review the listing before cleanup')
            entries.append(dict(key=row['Key'], size=row['Size'], etag=row['ETag'].strip('"')))
    entries.sort(key=lambda entry: entry['key'])
    if len(entries) != len({entry['key'] for entry in entries}):
        raise ValueError('Duplicate receipt key in listing')
    return entries


def scan_live(store, root, keys):
    """Verify downloads into a local mirror, then apply the same complete scan."""
    local = DirectoryFiles(root)
    for key in keys:
        path = local.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = store.get_file(key, path)
        if (metadata is None or metadata['etag'] != digest(path)
                or metadata['size'] != path.stat().st_size):
            raise ValueError('Live receipt mirror failed identity verification')
    return scan(root, keys)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--root', type=Path, help='Local directory containing receipts/')
    source.add_argument('--bucket', help='Owner-only live R2 receipt store')
    parser.add_argument('--inventory', type=Path, help='JSON array of receipt keys, pinned after writers drain')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--backup-root', type=Path)
    parser.add_argument('--scratch', type=Path)
    parser.add_argument('--records', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--scan-live', action='store_true')
    parser.add_argument('--mirror-root', type=Path)
    parser.add_argument('--list-inventory', action='store_true', help='Owner: read-only live listing to --inventory and --report')
    args = parser.parse_args(argv)
    if args.list_inventory:
        if not args.bucket or not args.inventory or args.apply:
            parser.error('--list-inventory requires --bucket and --inventory, without --apply')
        from congress_shared.storage import connect_r2
        entries = receipt_inventory(connect_r2(bucket=args.bucket), args.bucket)
        args.inventory.write_text(json.dumps([row['key'] for row in entries], indent=2) + '\n')
        args.report.write_text(json.dumps(entries, indent=2) + '\n')
        print(json.dumps(dict(receipts=len(entries), read_only=True)))
        return 0
    if args.scan_live:
        if not args.bucket or not args.inventory or not args.mirror_root or args.apply:
            parser.error('--scan-live requires --bucket, --inventory and --mirror-root, without --apply')
        from congress_shared.storage import connect_r2
        keys = json.loads(args.inventory.read_text())
        report = scan_live(R2ReceiptFiles(connect_r2(bucket=args.bucket), args.bucket), args.mirror_root, keys)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k: v for k, v in report.items() if k not in {'fields', 'patterns'}}))
        return 1 if report['counts'] else 0
    if args.bucket and (not args.apply or not args.inventory):
        parser.error('Live rewrite needs --apply and an explicit --inventory; scan local copies first')
    keys = json.loads(args.inventory.read_text()) if args.inventory else local_keys(args.root)
    if len(keys) != len(set(keys)) or any(not isinstance(k, str) or not k.startswith('receipts/')
                                        or '..' in Path(k).parts for k in keys):
        parser.error('Inventory must contain unique receipt keys')
    if not args.apply:
        report = scan(args.root, keys)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k: v for k, v in report.items() if k not in {'patterns', 'fields'}}))
        return 0
    if not all((args.backup_root, args.scratch, args.records)):
        parser.error('--apply requires --backup-root, --scratch and --records')
    args.scratch.mkdir(parents=True, exist_ok=True)
    backup = DirectoryFiles(args.backup_root)
    client = None
    if args.bucket:
        from congress_shared.storage import connect_r2
        client = connect_r2(bucket=args.bucket)
        store = R2ReceiptFiles(client, args.bucket)
    else:
        store = DirectoryFiles(args.root)
    previous = {}
    if args.records.exists():
        for line in args.records.read_text().splitlines():
            row = json.loads(line)
            previous[row['key']] = row
    def record(row):
        # This is only the owner's private durable local verification log.
        # R2 receives the same complete set below, as a create-only batch.
        with args.records.open('a') as out:
            out.write(json.dumps(row, separators=(',', ':')) + '\n')
            out.flush()
            import os
            os.fsync(out.fileno())
        previous[row['key']] = row
    for key in keys:
        rewrite_receipt(store, backup, key, scratch=args.scratch,
                        verified=previous.get(key), record=record)
    report = dict(receipts=len(keys), verified=len(previous), changed=sum(x['changed'] for x in previous.values()))
    if client:
        from congress_api.retention.r2 import R2Store
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        key = f'provenance/verification/{stamp}-{uuid4().hex}.jsonl'
        payload = ''.join(json.dumps(previous[k], separators=(',', ':')) + '\n' for k in sorted(previous)).encode()
        R2Store(client, args.bucket).put(key, payload, immutable=True)
        report['provenance_key'] = key
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
