"""Bounded latest reconciliation observations; never recovery or write authority."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from congress_shared.custody import canonical_json_bytes, write_atomic_bytes

MAX_PROGRESS_BYTES = 16384
MAX_READ_UPDATES = 32
NEXT_CHECK = {
    'starting': 'Read only uncertain requests and compare their size, SHA256 and original condition.',
    'reading': 'Finish the current body, check ContentLength, then compare SHA256 and the recorded version.',
    'reconciled': 'Check the next uncertain request; matching bytes resolve its outcome without another PUT.',
    'uncommitted': 'Check the next object; any later write must explicitly retain its original condition.',
    'conflict': 'Preserve this attempt and compare the current object with its recorded intent before any explicit continuation.',
    'failed': 'Preserve this attempt and inspect the failed read or checkpoint before explicit reconciliation.',
    'complete': 'Run the protected-input guard; recorded progress grants no write or public verification authority.',
}


def binding_digest(binding):
    return hashlib.sha256(canonical_json_bytes(binding, ensure_ascii=True)).hexdigest()


def validate_progress(value):
    fields = {'version', 'state', 'next_check', 'observation_only', 'resume_authorized', 'current_readback_proof',
              'public_readback', 'scan_id', 'binding_sha256', 'updated_at', 'key', 'object_index',
              'total_objects', 'checked_objects', 'bytes_read', 'declared_bytes'}
    if (not isinstance(value, dict) or set(value) != fields or type(value.get('version')) is not int or value['version'] != 1
            or value.get('state') not in NEXT_CHECK or value.get('next_check') != NEXT_CHECK[value['state']]
            or value.get('observation_only') is not True or value.get('resume_authorized') is not False
            or value.get('current_readback_proof') is not False or value.get('public_readback') != 'not_checked'):
        raise ValueError('Invalid reconciliation observation')
    if (not isinstance(value.get('scan_id'), str) or len(value['scan_id']) != 32
            or any(c not in '0123456789abcdef' for c in value['scan_id'])
            or not isinstance(value.get('updated_at'), str) or len(value['updated_at']) > 64
            or (value.get('key') is not None and (not isinstance(value['key'], str) or len(value['key']) > 2048))):
        raise ValueError('Invalid reconciliation observation identity')
    if (not isinstance(value.get('binding_sha256'), str) or len(value['binding_sha256']) != 64
            or any(c not in '0123456789abcdef' for c in value['binding_sha256'])):
        raise ValueError('Invalid reconciliation observation binding')
    for name in ('object_index', 'total_objects', 'checked_objects', 'bytes_read', 'declared_bytes'):
        if name == 'declared_bytes' and value.get(name) is None:
            continue
        if type(value.get(name)) is not int or value[name] < 0:
            raise ValueError('Invalid reconciliation observation counter')
    if value['object_index'] > value['total_objects'] or value['checked_objects'] > value['total_objects']:
        raise ValueError('Invalid reconciliation observation object count')
    return value


def read_progress(path, *, binding):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_PROGRESS_BYTES + 1)
    if len(raw) > MAX_PROGRESS_BYTES:
        raise ValueError('Reconciliation observation exceeds byte limit')
    value = validate_progress(json.loads(raw))
    if value['binding_sha256'] != binding_digest(binding):
        raise ValueError('Reconciliation observation belongs to different inputs')
    return value


class ReconciliationProgress:
    """Atomic latest-file replacement with no durability sync or retained history."""
    def __init__(self, root, binding):
        self.path = Path(root) / 'reconciliation-progress.json'
        self.scan_id = uuid.uuid4().hex
        self.binding_sha256 = binding_digest(binding)

    def __call__(self, value):
        value = dict(value, version=1, scan_id=self.scan_id, binding_sha256=self.binding_sha256,
                     updated_at=datetime.now(timezone.utc).isoformat(), observation_only=True,
                     resume_authorized=False, current_readback_proof=False, public_readback='not_checked')
        raw = canonical_json_bytes(validate_progress(value), ensure_ascii=True, trailing_newline=True)
        if len(raw) > MAX_PROGRESS_BYTES:
            raise ValueError('Reconciliation observation exceeds byte limit')
        write_atomic_bytes(
            self.path,
            raw,
            temp_path=self.path.with_suffix('.tmp'),
            fsync=False,
        )
