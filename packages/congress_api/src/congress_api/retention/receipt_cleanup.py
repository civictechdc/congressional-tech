"""One-time receipt rewrite, outside the create-only body store (PLAN B0)."""
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import shutil

from congress_api.retention.receipt_privacy import URL, clean_older_line


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'md5').hexdigest()


def evidence(line):
    """Independently collect URL strings, link values and resolved pointer targets."""
    urls, links = [], []
    def visit(value):
        if isinstance(value, str):
            urls.extend(m[0] for m in URL.finditer(value))
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            for key, child in value.items():
                urls.extend(m[0] for m in URL.finditer(key))
                if key == 'links':
                    links.append(child)
                visit(child)
    visit(line)
    targets = []
    for capture in line.get('captures', []) if isinstance(line, dict) else []:
        value = line.get('record', line)
        try:
            for part in capture.get('pointer', []):
                value = value[part]
        except (KeyError, IndexError, TypeError):
            # A historical dangling pointer must remain dangling, with the same path.
            targets.append(('unresolved', capture.get('pointer')))
        else:
            targets.append(('resolved', value))
    return urls, links, targets


def verify_line(original, cleaned):
    if evidence(original) != evidence(cleaned):
        raise ValueError('Cleanup changed a URL, links value or pointer target')
    expected, _ = clean_older_line(original)
    if cleaned != expected:
        raise ValueError('Cleanup changed an unapproved field')


def transform(source, destination):
    """Stream a receipt line at a time; preserve the bytes of every uncut line."""
    counts, changed, lines = Counter(), False, 0
    with gzip.open(source, 'rb') as before, Path(destination).open('wb') as raw:
        with gzip.GzipFile(fileobj=raw, filename='', mode='wb', mtime=0) as after:
            for number, encoded in enumerate(before, 1):
                try:
                    original = json.loads(encoded)
                    cleaned, cuts = clean_older_line(original)
                    verify_line(original, cleaned)
                except (ValueError, TypeError) as error:
                    raise ValueError(f'Receipt line {number}: {type(error).__name__}') from None
                counts.update(cuts)
                lines += 1
                if original == cleaned:
                    after.write(encoded)
                else:
                    changed = True
                    after.write(json.dumps(cleaned, ensure_ascii=False, separators=(',', ':')).encode()
                                + (b'\n' if encoded.endswith(b'\n') else b''))
    return changed, lines, counts


def verify_files(original, actual):
    """Read back all lines, including byte equality for every unchanged line."""
    from itertools import zip_longest
    with gzip.open(original, 'rb') as before, gzip.open(actual, 'rb') as after:
        for number, pair in enumerate(zip_longest(before, after), 1):
            left, right = pair
            if left is None or right is None:
                raise ValueError(f'Receipt line count changed at {number}')
            old, new = json.loads(left), json.loads(right)
            verify_line(old, new)
            if old == new and left != right:
                raise ValueError(f'Uncut line bytes changed at {number}')


def rewrite_receipt(store, backup, key, *, scratch, verified=None, record=None):
    """Back up, conditionally replace, read back and record one receipt; O(receipt bytes)."""
    if not key.startswith('receipts/') or not key.endswith('.jsonl.gz'):
        raise ValueError('Cleanup accepts receipt keys only')
    if verified is not None:
        if verified.get('key') != key or verified.get('verified') is not True:
            raise ValueError('Invalid prior verification')
        return verified
    with tempfile.TemporaryDirectory(prefix='cx_receipt_cleanup_', dir=scratch) as work:
        work = Path(work)
        live, original, cleaned, readback = (work / name for name in
                                            ('live.gz', 'original.gz', 'cleaned.gz', 'readback.gz'))
        current = store.get_file(key, live)
        if current is None:
            raise ValueError('Receipt is missing')
        if digest(live) != current['etag'] or live.stat().st_size != current['size']:
            raise ValueError('Original receipt transfer failed size or MD5 verification')
        saved = backup.get_file(key, original)
        if saved is None:
            shutil.copyfile(live, original)
        else:
            if digest(original) != saved['etag'] or original.stat().st_size != saved['size']:
                raise ValueError('Private backup failed size or MD5 verification')
        changed, lines, cuts = transform(original, cleaned)
        if any(kind == 'protected_path' for kind, _, _ in cuts):
            raise ValueError('Local path key is protected by a pointer; owner decision required')
        original_etag = digest(original)
        expected = digest(cleaned) if changed else original_etag
        if current['etag'] not in {original_etag, expected}:
            raise ValueError('Live receipt changed independently of the backup')
        # A no-match receipt is recorded without a rewrite or a new backup copy.
        if changed:
            if saved is None:
                backup.put_file(key, original, create_only=True)
                saved = backup.get_file(key, readback)
                if (saved is None or saved['etag'] != original_etag
                        or digest(readback) != original_etag
                        or saved['size'] != original.stat().st_size):
                    raise ValueError('Private backup readback failed before rewrite')
            if current['etag'] != expected:
                store.put_file(key, cleaned, if_match=current['etag'])
            result = store.get_file(key, readback)
            if result is None or result['etag'] != expected or digest(readback) != expected:
                raise ValueError('Cleaned receipt readback failed')
            verify_files(original, readback)
        else:
            result = current
            verify_files(original, live)
        totals = Counter()
        for (kind, _, _), count in cuts.items():
            totals[kind] += count
        result = dict(key=key, size=result['size'], etag=result['etag'],
                      original_size=original.stat().st_size, original_etag=original_etag,
                      backup_object=key if changed or saved else None,
                      fields_cut=[dict(kind=k, path=p, example=e, count=n)
                                  for (k, p, e), n in sorted(cuts.items())],
                      cookies_removed=totals['header'], paths_removed=totals['path'],
                      credential_parameters_removed=0, changed=changed, lines=lines,
                      verified=True, sha256_verified=False, job='receipt-cleanup',
                      checked_at=datetime.now(timezone.utc).isoformat())
        if record is not None:
            record(result)
        return result
