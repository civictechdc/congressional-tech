"""Classify a Git tree diff or validate the checked-out cause records and their evidence."""
import argparse
from hashlib import sha256
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


def tree_paths(revision):
    return set(os.fsdecode(git('ls-tree', '-rz', '--name-only', revision)).split('\0')[:-1])


def record_paths(tracked):
    return {path for path in tracked if re.fullmatch(CAUSES + r'[^/]+\.json', path)}


def evidence_pins(data, path, tracked):
    from viewer_publication.release_gate import validate_cause_record
    try:
        return validate_cause_record(strict_json(data), tracked=tracked)
    except ValueError as exc:
        raise ValueError(f'{path}: {exc}') from exc


def check_bytes(path, data, digest, size):
    if len(data) != size or sha256(data).hexdigest() != digest:
        raise ValueError(f'Cause pin differs from recorded size or SHA-256: {path}')


def verify_records(tracked, records, read, changed):
    from viewer_publication.release_gate import repository_evidence

    active = None
    binding = None
    check_sources = set(changed or ())
    if PUBLISH in tracked:
        spec = strict_json(read(PUBLISH))
        if not isinstance(spec, dict):
            raise ValueError(f'{PUBLISH} must be a JSON object')
        if 'release_causes' in spec:
            binding = spec['release_causes']
            active = os.path.relpath(Path(PUBLISH).parent / binding['path'])
            if active not in tracked:
                raise ValueError(f'Missing tracked release_causes record: {active}')
            records = records | {active}
            if changed is None or PUBLISH in changed:
                check_sources.add(active)

    evidence = set()
    for path in sorted(records):
        data = read(path)
        if path == active:
            check_bytes(path, data, binding['sha256'], binding['size'])
        pins = evidence_pins(data, path, tracked)
        evidence.update(repository_evidence(pins, tracked, check_sources=path in check_sources,
                                            require_relative=changed is not None and path in changed))
    for path, digest, size in sorted(evidence):
        check_bytes(path, read(path), digest, size)


def verify_changed(base, head):
    from viewer_publication.release_gate import IMMUTABLE_EVIDENCE, repository_evidence_path

    diff = changes(base, head) if base else {}
    # Read the old records before accepting new pins. Removing a record or
    # updating its hash in the same diff cannot authorize rewriting evidence.
    rewritten = {p for p, fields in diff.items() if p.startswith(IMMUTABLE_EVIDENCE) and fields[-1] != 'A'}
    if rewritten:
        previous = tree_paths(base)
        for path in sorted(record_paths(previous)):
            for name, _, _ in evidence_pins(git('show', f'{base}:{path}'), path, previous):
                if repository_evidence_path(name) in rewritten:
                    raise ValueError(f'{path} pins changed historical evidence: {name}')

    tracked = tree_paths(head)
    records = record_paths(tracked)
    verify_records(tracked, records, lambda path: git('show', f'{head}:{path}'), diff if base else None)

    # A local full-directory check also covers edits and new records awaiting commit.
    if not base:
        local_records = {str(path) for path in Path(CAUSES).glob('*.json')}
        if local_records != records or git('diff', '--name-only', head, '--'):
            index = set(os.fsdecode(git('ls-files', '-z')).split('\0')[:-1])
            verify_records(index, record_paths(index) | local_records, lambda path: Path(path).read_bytes(), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', nargs='?')
    parser.add_argument('head', default='HEAD', nargs='?')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        try:
            verify_changed(args.base, args.head)
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            parser.exit(1, f'Cause verification failed: {exc}\n')
    elif not args.base:
        parser.error('classification requires a base')
    else:
        print(str(cause_record_only(args.base, args.head)).lower())


if __name__ == '__main__':
    main()
