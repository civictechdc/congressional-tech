"""Report which receipt JSON paths a fixture holds and which the capture mapper reads.

Gaps are reported, not failed. This shows whether a path is read, not whether it is
interpreted correctly. The mapper exposes both of its path lists (ct-mrgt): the line
projection in receipt_metadata.source_paths and the list-item projection in
captures.item_paths, read relative to each item of a list record.
"""
import argparse
import json
from pathlib import Path
import sys

from congress_api.lake import captures, receipt_metadata


def mapper_paths():
    return ({normalized(path) for path in receipt_metadata.source_paths()}
            | {normalized(('record', '*') + tuple(path)) for path in captures.item_paths()})


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
    declared = mapper_paths()
    # A declared container is read whole, so its descendants are read too. A path
    # that merely contains read fields is neither: it is left out of both sets.
    read = {path for path in fixture if any(path[:n] in declared for n in range(1, len(path) + 1))}
    holders = {path[:n] for path in read for n in range(1, len(path))}
    text = lambda paths: sorted('/'.join(path) for path in paths)
    return dict(read_by_mapper=text(read), fixture_paths_not_read=text(fixture - read - holders),
                mapper_paths_not_exercised=text(declared - fixture),
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
