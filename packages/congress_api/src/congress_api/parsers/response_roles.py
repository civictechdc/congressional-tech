"""CT compatibility names for the shared SpicyDocs response observations.

HTML/XML retain their qualified CT policy after exact retained-output replay.
The added PDF byte observations have a distinct policy; neither selects text,
changes an inventory item, or certifies a complete source.
"""
from dataclasses import replace

from spicy_docs.reading.response_roles import (
    MAX_BYTES as MAX_BYTES,
    MAX_PDF_BYTES as MAX_PDF_BYTES,
    MAX_EVIDENCE_FIELDS as MAX_EVIDENCE_FIELDS,
    MAX_EVIDENCE_TEXT_CHARS as MAX_EVIDENCE_TEXT_CHARS,
    ResponseRole as ResponseRole,
    assess_response as _assess_response,
)

POLICY_VERSION = 'ct-response-roles-v2'
PDF_POLICY_VERSION = 'ct-pdf-byte-observations-v1'


def assess_response(body: bytes, *, format: str, max_bytes=MAX_BYTES):
    observed = _assess_response(body, format=format, max_bytes=max_bytes)
    return replace(observed, policy_version=PDF_POLICY_VERSION if format == 'pdf' else POLICY_VERSION)
