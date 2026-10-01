"""Resolve specified document URLs, reusing the raw archive before bounded GETs.

No full documents are downloaded. Prefixes and results go in a separate probe
receipt, not the capture index. Use --live to explicitly bypass saved responses.
"""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.acquisition.documents import resolve_document
from congress_api.models.content import RawContent
from congress_api.models.documents import DocumentProbeResponse
from congress_api.transport.document_probe import DEFAULT_LIMIT, get_prefix

ROOT = Path(__file__).resolve().parents[4]


def archive_reader(root, *, live=False):
    table = None if live else pq.read_table(root / 'indexes/document-filenames.parquet',
        columns=['source_url', 'body_key', 'media_type', 'http_status'])

    def read(url, *, max_bytes):
        if table is not None:
            rows = table.filter(pc.fill_null(pc.equal(table['source_url'], url), False)).to_pylist()
            # Prefer a successful exact-URL capture; failed captures remain
            # evidence, not proof that a candidate download no longer exists.
            for row in rows:
                if not row['body_key'] or not any(s.startswith('2') for s in row['http_status'] or []):
                    continue
                path = (root / row['body_key']).resolve()
                path.relative_to(root.resolve())
                if not path.is_file():
                    continue
                with gzip.open(path, 'rb') as source:
                    prefix = source.read(max_bytes + 1)
                media = next(iter(row['media_type'] or []), '')
                return DocumentProbeResponse(url=url,
                    status_code=int(next(s for s in row['http_status'] if s.startswith('2'))),
                    headers={'content-type': media}, header_items=[('content-type', media)],
                    content=RawContent.from_bytes(prefix[:max_bytes], media),
                    complete=len(prefix) <= max_bytes, from_cache=True, body_key=row['body_key'])
        return get_prefix(url, max_bytes=max_bytes)
    return read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('urls', nargs='+')
    parser.add_argument('--archive', type=Path, default=ROOT / '.cache/congressional-tech-raw')
    parser.add_argument('--max-bytes', type=int, default=DEFAULT_LIMIT)
    parser.add_argument('--max-steps', type=int, default=5)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    output = args.output or ROOT / '.cache/document-probes' / (now.strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    get = archive_reader(args.archive, live=args.live)
    results = []
    for url in args.urls:
        result = resolve_document(url, get=get, max_bytes=args.max_bytes, max_steps=args.max_steps)
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k not in ('responses', 'links')}))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'checked_at': now.isoformat(), 'max_bytes_per_response': args.max_bytes,
        'max_steps_per_url': args.max_steps, 'full_document_downloads': False, 'results': results},
        default=lambda value: value.model_dump(mode='json'), ensure_ascii=False, indent=2) + '\n')
    print(f'Probe receipt: {output}')


if __name__ == '__main__':
    main()
