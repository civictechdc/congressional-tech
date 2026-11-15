"""Observe one retained response without selecting, repairing or fetching it."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from congress_api.parsers.response_roles import MAX_BYTES, MAX_PDF_BYTES, assess_response


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--format', choices=('html', 'xml', 'pdf', 'warc', 'other'), required=True)
    args = parser.parse_args(argv)
    # Refuse before allocation; byte observations do not parse or rasterize PDF pages.
    bound = MAX_PDF_BYTES if args.format == 'pdf' else MAX_BYTES
    if args.source.stat().st_size > bound:
        parser.error(f'Source exceeds the {bound}-byte assessment bound; use its dedicated reader')
    with args.source.open('rb') as stream:
        body = stream.read(bound + 1)
    if len(body) > bound:
        parser.error('Source grew beyond the assessment bound while reading')
    result = assess_response(body, format=args.format, max_bytes=bound)
    print(json.dumps(dict(source=str(args.source.resolve()), **asdict(result)), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
