"""Report which receipt JSON paths a fixture holds and which the capture mapper reads.

Gaps are reported, not failed. This shows whether a path is read, not whether it is
interpreted correctly. The mapper's path list is local to the byte-hashed
receipt_metadata.source_plan, so this spies on its projection call.
"""
import argparse
import json
from pathlib import Path
import sys

from congress_api.lake import receipt_metadata


def mapper_paths():
    seen = []
    original = receipt_metadata.projection

    def spy(raw, paths, slot='__slots'):
        seen.extend(tuple(path) for path in paths)
        return original(raw, paths, slot)

    receipt_metadata.projection = spy
    try:
        receipt_metadata.source_plan(files=[])
    finally:
        receipt_metadata.projection = original
    return {normalized(path) for path in seen}


def normalized(path):
    return tuple('*' if isinstance(part, int) else part for part in path)


def walk(value, prefix=()):
    """Yield every container and leaf path, with list indices normalized."""
    if prefix:
        yield prefix
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, prefix + (key,))
    elif isinstance(value, list):
        for item in value:
            yield from walk(item, prefix + ('*',))


def pointers(value):
    """Yield pointer/pointer_json values anywhere in a line, normalized."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'pointer' and isinstance(item, list):
                yield normalized(item)
            elif key == 'pointer_json' and isinstance(item, str):
                yield normalized(json.loads(item))
            else:
                yield from pointers(item)
    elif isinstance(value, list):
        for item in value:
            yield from pointers(item)


def report(rows):
    fixture = {path for row in rows for path in walk(row)}
    read = mapper_paths()
    text = lambda paths: sorted('/'.join(path) for path in paths)
    return dict(read_by_mapper=text(read & fixture), fixture_paths_not_read=text(fixture - read),
                mapper_paths_not_exercised=text(read - fixture),
                pointers=text({pointer for row in rows for pointer in pointers(row)}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path, help='JSON lines holding {"key","line","row"}')
    args = parser.parse_args(argv)
    rows = [json.loads(text)['row'] for text in args.fixture.read_text().splitlines()]
    json.dump(report(rows), sys.stdout, indent=1)
    print()


if __name__ == '__main__':
    main()
