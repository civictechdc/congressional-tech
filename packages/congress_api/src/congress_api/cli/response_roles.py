"""Observe one retained response without selecting, repairing or fetching it."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from congress_api.parsers.response_roles import MAX_BYTES, assess_response


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--format', choices=('html', 'xml', 'pdf', 'warc', 'other'), required=True)
    args = parser.parse_args(argv)
    # Refuse before allocation. Large feeds and PDF containers have their own readers.
    if args.source.stat().st_size > MAX_BYTES:
        parser.error(f'Source exceeds the {MAX_BYTES}-byte assessment bound; use its dedicated reader')
    with args.source.open('rb') as stream:
        body = stream.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        parser.error('Source grew beyond the assessment bound while reading')
    result = assess_response(body, format=args.format)
    print(json.dumps(dict(source=str(args.source.resolve()), **asdict(result)), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
