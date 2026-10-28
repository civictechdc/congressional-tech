"""Receipt-key evidence for replay; storage effects use an injected create-only store.

The list digest hashes canonical uncompressed JSON, independent of gzip versions.
Lists and input records live inside their release prefix, so retaining a release
retains all identities that produced it without reference counting.
"""
from base64 import b64encode
import gzip
from hashlib import md5, sha256
import json
import re

PREFIX = 'viewer-publications/releases/'


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Expected a lowercase SHA-256 digest')
    return value


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def receipt_list(keys):
    """Serialize a sorted set of object keys. O(R log R), once per input pin."""
    keys = list(keys)
    for key in keys:
        if (not isinstance(key, str) or not key.startswith('receipts/') or
            any(part in {'', '.', '..'} for part in key.split('/')) or
            any(char in key for char in '\\?#') or any(ord(char) < 32 for char in key)):
            raise ValueError('Invalid receipt object key')
    raw = _canonical(sorted(set(keys)))
    return sha256(raw).hexdigest(), gzip.compress(raw, mtime=0)


def read_receipt_list(digest, payload):
    _digest(digest)
    try:
        raw = gzip.decompress(payload)
        keys = json.loads(raw)
        if not isinstance(keys, list): raise ValueError('Receipt list must be an array')
        actual, _ = receipt_list(keys)
        if actual != digest or sha256(raw).hexdigest() != digest:
            raise ValueError('Receipt-list identity or canonical bytes differ')
        return keys
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Unreadable receipt list') from error


def write_input_receipts(store, release_id, input_digest, record, keys):
    """Create the list before the record; no pointer mutation or delete occurs here.

    store.create must implement create-only PUT with Content-MD5, and accept a
    pre-existing identical object. A changed input record must refuse.
    """
    prefix = PREFIX + _digest(release_id) + '/inputs/'
    _digest(input_digest)
    if record.get('input_digest') != input_digest:
        raise ValueError('Input record identity differs from its key')
    digest, payload = receipt_list(keys)
    record = dict(record, receipt_keys_sha256=digest)
    for key, body, media in [(prefix + 'receipts/' + digest + '.json.gz', payload, 'application/gzip'),
                             (prefix + input_digest + '.json', _canonical(record), 'application/json')]:
        store.create(key, body, content_type=media,
            content_md5=b64encode(md5(body).digest()).decode(),
            cache_control='public,max-age=31536000,immutable')
    return record


def kept_input_records(store, release_ids):
    """Verify every input of kept releases before retention can remove a prefix.

    Missing evidence refuses maintenance, rather than treating a release as
    rebuildable. Returns (entries, protected object keys); entries retain every
    parsed input record and its validated receipt keys for downstream guards.
    """
    protected = set()
    entries = []
    receipt_lists = {}
    for release in sorted({_digest(value) for value in release_ids}):
        prefix = PREFIX + release + '/inputs/'
        records = sorted({key for key in store.keys(prefix)
                   if re.fullmatch(re.escape(prefix) + '[a-f0-9]{64}[.]json', key)})
        if not records: raise ValueError('Kept release has no input record')
        for key in records:
            try:
                record = json.loads(store.get(key))
                if record['input_digest'] != key[len(prefix):-5]:
                    raise ValueError('Input record identity differs')
                digest = _digest(record['receipt_keys_sha256'])
                receipt_key = prefix + 'receipts/' + digest + '.json.gz'
                # Different kept prefixes must each contain valid evidence.
                if receipt_key not in receipt_lists:
                    receipt_lists[receipt_key] = read_receipt_list(digest, store.get(receipt_key))
            except (KeyError, OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError('Kept release receipt evidence is missing or unreadable') from error
            protected.update([key, receipt_key])
            entries.append(dict(release_id=release, key=key, record=record,
                receipt_keys=receipt_lists[receipt_key]))
    return entries, protected


def kept_receipt_keys(store, release_ids):
    """Return protected input/list keys through the maintained validation pass."""
    return kept_input_records(store, release_ids)[1]
