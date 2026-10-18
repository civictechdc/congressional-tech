"""Bounded, read-only admission of a sealed recovery import.

JSON objects are capped at 64 MiB; event histories at 64 MiB/100,000 events,
with at most 1 MiB per event. Large retained tables stay on streaming hash APIs.
These are admission limits, not claims about acquisition or domain coverage.
"""
import hashlib
import json
from pathlib import Path
import re

JSON_BYTES = 64 * 1024**2
EVENT_BYTES = 1024**2
EVENT_TOTAL_BYTES = 64 * 1024**2
EVENT_COUNT = 100_000


def invalid(path, field, message):
    return ValueError(f'{path}: invalid {field}: {message}')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def parse(data, path, field='$'):
    try:
        return json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise invalid(path, field, 'invalid JSON') from error


def read(path, shape):
    with path.open('rb') as stream:
        data = stream.read(JSON_BYTES + 1)
    if len(data) > JSON_BYTES:
        raise invalid(path, '$', f'exceeds {JSON_BYTES} byte budget')
    value = parse(data, path)
    if not isinstance(value, shape):
        raise invalid(path, '$', f'expected {shape.__name__}')
    return value


def field(value, key, shape, path):
    item = value.get(key)
    if type(item) is not shape:
        raise invalid(path, key, f'expected {shape.__name__}')
    return item


def hashes(value, path):
    files = field(value, 'files', dict, path)
    for name, pin in files.items():
        if (not isinstance(name, str) or Path(name).name != name or name in ('.', '..')
                or not isinstance(pin, str) or not re.fullmatch('[a-f0-9]{64}', pin)):
            raise invalid(path, 'files', 'expected plain filenames and SHA-256 digests')
    return files


def events(path):
    total = 0
    with path.open('rb') as stream:
        for count in range(EVENT_COUNT + 1):
            line = stream.readline(EVENT_BYTES + 1)
            if not line:
                return
            total += len(line)
            if count == EVENT_COUNT or len(line) > EVENT_BYTES or total > EVENT_TOTAL_BYTES:
                raise invalid(path, f'event[{count}]', 'event count or byte budget exceeded')
            value = parse(line, path, f'event[{count}]')
            if not isinstance(value, dict):
                raise invalid(path, f'event[{count}]', 'expected object')
            field(value, 'event', str, path)
            yield value


def verify_import(batch, imported, *, readiness=None):
    batch, imported = Path(batch), Path(imported)
    manifest_path = batch / 'manifest.json'
    manifest = read(manifest_path, dict)
    manifest_pin = digest(manifest_path)
    manifest_files = hashes(manifest, manifest_path)
    readiness = readiness.resolve() if readiness is not None else batch / 'import-readiness.json'
    ready = read(readiness, dict)
    ready_files = hashes(ready, readiness)
    if ready.get('remote_body_readback_sha256'):
        readback = readiness.with_name('remote-body-readback.json')
        if digest(readback) != ready['remote_body_readback_sha256']:
            raise invalid(readback, 'sha256', 'Body reconciliation evidence changed')
        if field(read(readback, dict), 'batch_manifest_sha256', str, readback) != manifest_pin:
            raise invalid(readback, 'batch_manifest_sha256', 'Body reconciliation belongs to another batch')
    for name, expected in ready_files.items():
        if name in manifest_files and manifest_files[name] != expected:
            raise invalid(readiness, 'files.' + name, 'conflicting batch evidence hashes')
    for name, expected in (manifest_files | ready_files).items():
        if digest(batch / name) != expected:
            raise invalid(batch / name, 'sha256', 'Batch evidence changed')
    preparation_path = batch / 'source-record-preparation.json'
    preparation = read(preparation_path, dict)
    if (field(preparation, 'unresolved', list, preparation_path)
            or field(preparation, 'batch_manifest_sha256', str, preparation_path) != manifest_pin):
        raise invalid(preparation_path, 'batch_manifest_sha256/unresolved', 'Source records do not cover the sealed batch')
    result_path = imported / 'payloads/import-complete.json'
    result = read(result_path, dict)
    if (field(result, 'complete', bool, result_path) is not True
            or field(result, 'added_capture_rows', int, result_path) < 0
            or field(result, 'distinct_bodies', int, result_path) < 0):
        raise invalid(result_path, 'complete/counts', 'incomplete import')
    capture_rows, bodykeys = 0, set()
    for name in ('prepared-source-records.json', 'zip-receipts.json'):
        path = batch / name
        for index, item in enumerate(read(path, list)):
            if not isinstance(item, dict):
                raise invalid(path, f'row[{index}]', 'expected object')
            for cap in field(item, 'captures', list, path):
                if not isinstance(cap, dict):
                    raise invalid(path, f'row[{index}].captures', 'expected objects')
                bodykeys.add(field(cap, 'body_key', str, path))
                capture_rows += 1
    for key, count in (('capture_rows', capture_rows), ('distinct_capture_bodykeys', len(bodykeys))):
        if key in ready and (type(ready[key]) is not int or ready[key] != count):
            raise invalid(readiness, key, 'Readiness counts differ from sealed source records')
    if result['added_capture_rows'] != capture_rows or result['distinct_bodies'] != len(bodykeys):
        raise invalid(result_path, 'counts', 'Import completion does not cover the sealed batch')
    event_path = imported / 'events.jsonl'
    pins, completed = None, False
    for event in events(event_path):
        if event['event'] == 'pins':
            if pins is not None:
                raise invalid(event_path, 'pins', 'duplicate pins event')
            pins = field(event, 'value', dict, event_path)
        elif event['event'] == 'import_complete':
            if completed or field(event, 'value', dict, event_path) != result:
                raise invalid(event_path, 'import_complete', 'duplicate or conflicting completion')
            completed = True
    if pins is None or not completed:
        raise invalid(event_path, 'pins/import_complete', 'missing required event')
    for path in (manifest_path, batch / 'prepared-source-records.json', readiness):
        if pins.get(str(path)) != digest(path):
            raise invalid(event_path, 'pins.' + str(path), 'Import belongs to a different batch')
    return result
