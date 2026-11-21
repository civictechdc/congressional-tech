"""Classify a Git tree diff or validate the checked-out cause records and their evidence."""
import argparse
import json
import os
import re
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
            if mode != '100644' or old_mode not in (':000000', ':100644') or status not in ('A', 'M'):
                return False
            if re.fullmatch(r'\.tickets/[^/]+\.md', path):
                continue
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
    """Validate every record and repository pin. With no base, require all original evidence."""
    from congress_shared.custody import verify_local_file
    from viewer_publication.release_gate import validate_cause_record

    changed_paths = set(changes(base, head)) if base else None
    evidence = set()
    root = Path.cwd()
    for path in sorted(Path(CAUSES).rglob('*.json')):
        record = strict_json(path.read_bytes())
        if path.is_relative_to(Path(CAUSES) / 'evidence'):
            continue
        pins = validate_cause_record(record)
        repository_pins = {pin: str(p.relative_to(root)) for pin in pins
                           if (p := Path(os.path.abspath(pin[0]))).is_relative_to(root)}
        affected = changed_paths is None or str(path) in changed_paths or not changed_paths.isdisjoint(repository_pins.values())
        # Every repository pin is reproducible in CI. A changed record, changed evidence,
        # or an unknown base also requires all the record's original offline artifacts.
        evidence.update(pins if affected else repository_pins)
    if Path(PUBLISH).exists():
        strict_json(Path(PUBLISH).read_bytes())
    errors = []
    for name, digest, size in sorted(evidence):
        try:
            verify_local_file(name, digest, size)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    if errors:
        raise ValueError('Cause evidence failed verification:\n' + '\n'.join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', nargs='?')
    parser.add_argument('head', default='HEAD', nargs='?')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        verify_changed(args.base, args.head)
    elif not args.base:
        parser.error('classification requires a base')
    else:
        print(str(cause_record_only(args.base, args.head)).lower())


if __name__ == '__main__':
    main()
