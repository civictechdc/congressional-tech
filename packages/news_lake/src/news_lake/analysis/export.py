"""C5 owner: restricted-export enforcement for release-scoped reads.

`export_release` takes the dict returned by
`news_lake.storage.releases.read_release` and returns a deep copy safe for a
public/unprivileged consumer:

- restricted captures lose their payload reference/hash/media type and
  rights basis; restricted versions lose text, text hash, and rights basis;
  both are downgraded to `access='metadata_only'`;
- any capture past `retain_until` is treated as expired even when its access
  is redistributable, because expiry policy reaches raw payloads and derived
  text (C5). The expired capture keeps `retain_until` as evidence, and every
  version referencing it loses its text too;
- redistributable records keep their bodies (including rights_basis);
- an authorized export bypasses all filtering and returns everything, still
  as a deep copy.

The release record itself is never altered: ids pinned by the release keep
naming the same versions and runs. The input is never mutated.
"""
import copy
from datetime import datetime, timezone

from news_lake.context import parse_instant
from news_lake.contract.records import validate_shape
from news_lake.contract.semantics import _check_credentials

CAPTURE_PAYLOAD_FIELDS = ('payload_uri', 'payload_hash', 'media_type', 'rights_basis')
CAPTURE_BODY_FIELDS = ('payload_uri', 'payload_hash', 'media_type')
VERSION_BODY_FIELDS = ('text', 'text_hash', 'rights_basis')


def _expired(record, now):
    retain_until = record.get('retain_until')
    return retain_until is not None and parse_instant(retain_until) < now


def _strip(record, fields):
    for field in fields:
        record.pop(field, None)


def export_release(release_read, *, authorized=False, now=None):
    """Return a C5-filtered deep copy of a release read.

    `now` may be an aware datetime or an instant string; it defaults to the
    current UTC time. Expiry is strict: a payload is expired only when
    `retain_until < now`.

    Precondition: `release_read` is a validated release snapshot (as returned
    by `read_release`), and every exported record is re-checked for shape and
    credential redaction (C2/C5) before return.
    """
    exported = copy.deepcopy(release_read)
    validate_shape(exported['release'])
    _check_credentials(exported['release'])
    if authorized:
        for records in exported['tables'].values():
            for record in records:
                validate_shape(record)
                _check_credentials(record)
        return exported

    if now is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(now, str):
        moment = parse_instant(now)
    else:
        moment = now
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    expired_captures = {
        record['id']
        for records in exported['tables'].values()
        for record in records
        if record.get('kind') == 'capture' and _expired(record, moment)
    }

    for records in exported['tables'].values():
        for record in records:
            kind = record.get('kind')
            if kind == 'capture':
                if record.get('access') == 'restricted' or record['id'] in expired_captures:
                    _strip(record, CAPTURE_PAYLOAD_FIELDS)
                    record['access'] = 'metadata_only'
                elif record.get('access') == 'metadata_only':
                    _strip(record, CAPTURE_BODY_FIELDS)
            elif kind == 'version':
                capture_id = record.get('capture_id')
                expired = capture_id in expired_captures
                if record.get('access') == 'restricted' or expired:
                    _strip(record, VERSION_BODY_FIELDS)
                    record['access'] = 'metadata_only'
                elif record.get('access') == 'metadata_only':
                    _strip(record, ('text', 'text_hash'))
            validate_shape(record)
            _check_credentials(record)
    return exported
