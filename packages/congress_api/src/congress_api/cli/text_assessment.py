"""Write bounded offline repair proposals from retained assessment facts JSONL."""
import argparse
import json
from pathlib import Path
import sys

from congress_api.lake.text_assessment import MAX_RECORD_BYTES, assess_text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('facts', type=Path)
    parser.add_argument('--limit', type=int, default=1000)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 10_000:
        parser.error('--limit must be between 1 and 10000 records')
    count, seen = 0, set()
    with args.facts.open('rb') as stream:
        for _ in range(args.limit):
            line = stream.readline(MAX_RECORD_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_RECORD_BYTES:
                parser.error(f'record {count + 1} exceeds the byte bound; earlier output is partial')
            try:
                result = assess_text(json.loads(line))
            except (ValueError, TypeError, KeyError) as error:
                parser.error(f'record {count + 1}: {error}; earlier output is partial')
            key = (result['facts']['body_sha256'], result['facts']['parser'],
                   result['facts']['parser_version'], result['facts']['page_number'])
            if key in seen:
                parser.error(f'record {count + 1} duplicates an assessed reading/page; earlier output is partial')
            seen.add(key)
            print(json.dumps(result, sort_keys=True, separators=(',', ':')))
            count += 1
        remaining = bool(stream.read(1))
    print(json.dumps(dict(records=count, remaining='not_read' if remaining else 'none',
                          scope='proposal_only_no_dispatch')), file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
