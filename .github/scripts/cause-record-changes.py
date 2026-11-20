"""Classify a Git tree diff, or validate the changed release records in the checked-out head."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

CAUSES = 'model/jobs/release-causes/'
PUBLISH = 'model/jobs/publish.json'


def git(*args):
    return subprocess.check_output(['git', *args])


def changes(base, head):
    fields = git('diff', '--raw', '-z', '--no-renames', base, head, '--').split(b'\0')
    return {path.decode(): header.decode().split() for header, path in zip(fields[:-1:2], fields[1::2])}


def strict_json(data, *, exact_numbers=False):
    def unique(pairs):
        obj = dict(pairs)
        if len(obj) != len(pairs):
            raise ValueError('duplicate JSON key')
        return obj

    def invalid(value):
        raise ValueError(f'invalid JSON number {value}')

    # Number tokens compare exactly, including precision and type. JSON arrays
    # decode to lists, so a tuple cannot be confused with any other JSON value.
    def number(token):
        return ('number', token)

    options = dict(parse_int=number, parse_float=number) if exact_numbers else {}
    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid, **options)


def cause_record_only(base, head):
    """Read committed blobs, including both sides of the top-level release_causes pin."""
    try:
        diff = changes(base, head)
        touched = False
        for path, (old_mode, mode, _, _, status) in diff.items():
            if path.startswith(('.tickets/', 'docs/')) and not path.startswith('docs/experiments/'):
                continue
            if mode != '100644' or old_mode not in (':000000', ':100644') or status not in ('A', 'M'):
                return False
            if path == PUBLISH:
                before, after = (strict_json(git('show', f'{rev}:{path}'), exact_numbers=True) for rev in (base, head))
                if not isinstance(before, dict) or not isinstance(after, dict) or 'release_causes' not in after:
                    return False
                before.pop('release_causes', None)
                after.pop('release_causes')
                if before != after:
                    return False
            elif path.startswith(CAUSES) and path.endswith('.json'):
                strict_json(git('show', f'{head}:{path}'))
            else:
                return False
            touched = True
        return touched
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f'Full validation required: {exc}', file=sys.stderr)
        return False


def verify_changed(base, head):
    """Check changed JSON, each changed record and the records that pin changed evidence."""
    from congress_api.retention.provenance import file_pin
    from viewer_publication.release_gate import load_causes

    diff = changes(base, head)
    if PUBLISH in diff:
        strict_json(Path(PUBLISH).read_bytes())
    touched = {path for path in diff if path.startswith(CAUSES)}
    for path in sorted(touched):
        if path.endswith('.json') and Path(path).is_file():
            strict_json(Path(path).read_bytes())
    for record in sorted(Path(CAUSES).rglob('*.json')):
        if record.is_relative_to(Path(CAUSES) / 'evidence'):
            continue
        entries = strict_json(record.read_bytes())['groups']
        if str(record) in touched or any(os.path.normpath(pin['path']) in touched
                                         for entry in entries for pin in entry.get('evidence', [])):
            load_causes(dict(path=str(record), **file_pin(record)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base')
    parser.add_argument('head')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        verify_changed(args.base, args.head)
    else:
        print(str(cause_record_only(args.base, args.head)).lower())


if __name__ == '__main__':
    main()
