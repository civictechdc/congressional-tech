"""Authored relationship explanations and metadata-only legacy corrections.

An accepted mapping or campaign request may supply an explanation supported by
its reviewed evidence. Reconciliation and acceptance reasons cannot supply one.
"""
from hashlib import sha256
import re

from congress_api.retention.provenance import validate_provenance
from congress_shared.custody import canonical_json_bytes


POLICY = 'authored-or-null-v1'
_GENERATED = re.compile(
    r'Reconciled from pinned accepted mappings [0-9a-f]{64}; receipt categories preserved'
)


def authored_note(note):
    """Preserve explicit text; leave unknown and exact generated notes null."""
    if note is not None and not isinstance(note, str):
        raise ValueError('Recovery identity_note must be an authored explanation or null')
    if note is None or not note.strip() or _GENERATED.fullmatch(note):
        return None
    return note


def correct_generated_note(record, *, decided_at, decided_by):
    """Prepare a new null-note decision; append it through the provenance CLI.

    The caller selects a current immutable decision. Only its exact provenance
    sentinel is eligible; authored notes and other evidence pins are untouched.
    This function reads no bodies and does not write or apply the correction.
    """
    validate_provenance('recoveries', record)
    pin = record['evidence_sha256']
    if pin is None or record['identity_note'] != (
        'Reconciled from pinned accepted mappings ' + pin + '; receipt categories preserved'
    ):
        raise ValueError('Correction requires the exact generated note for this evidence pin')
    correction = dict(record, identity_note=None, supersedes=record['id'],
                      decided_at=decided_at, decided_by=decided_by)
    del correction['id']
    correction['id'] = sha256(POLICY.encode() + b':' + canonical_json_bytes(correction)).hexdigest()
    validate_provenance('recoveries', correction)
    return correction
