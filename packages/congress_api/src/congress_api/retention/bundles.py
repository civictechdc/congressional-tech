"""Separate embedded source bodies from saved JSON without changing their metadata.

This is an offline migration helper, not another acquisition or normalization
path. A receipt contains the original JSON value with captured strings replaced
by null, plus their locations and body references. Restoring those strings must
reproduce the original JSON value. Original JSON formatting is not preserved.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable

from congress_api.models.content import RawContent


def _copy_json(value):
    # JSON has no shared object references: each occurrence needs its own slot.
    if isinstance(value, dict):
        return {key: _copy_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_copy_json(child) for child in value]
    return value


def separate(value: object, put: Callable[[bytes], str]) -> tuple[object, list[dict]]:
    """Extract exact RawContent bytes and explicitly identified older text captures.

    ``put`` returns the storage key. Unknown fields remain in the receipt. Older
    text has no claim to preserve the publisher's original byte encoding.
    """
    record = _copy_json(value)
    captures: list[dict] = []

    def capture(node, key, path, *, encoding, fidelity, media_type, context):
        original = node[key]
        data = original.encode('utf-8') if encoding == 'utf-8' else base64.b64decode(original, validate=True)
        entry = {
            'pointer': [*path, key], 'body_key': put(data),
            'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'string_encoding': encoding, 'fidelity': fidelity,
            'media_type': media_type, **context,
        }
        # A few providers wrap base64 across lines. Do not claim to reconstruct
        # a different spelling; unsupported base64 spellings fail explicitly.
        if encoding == 'base64' and base64.b64encode(data).decode('ascii') != original:
            raise ValueError(f'Noncanonical base64 at {path + [key]}')
        node[key] = None
        captures.append(entry)

    def walk(node, path, inherited):
        if isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, [*path, index], inherited)
            return
        if not isinstance(node, dict):
            return
        context = dict(inherited)
        for source_key, target in (
            ('url', 'context_url'), ('_url', 'context_url'),
            ('retrieved_at', 'retrieved_at'), ('captured_at', 'captured_at'),
            ('status_code', 'status_code'), ('http_status', 'http_status'),
            ('statusCode', 'http_status'),
        ):
            if source_key in node and isinstance(node[source_key], (str, int, type(None))):
                context[target] = node[source_key]
        if 'body_encoding' in node and 'body' in node:
            raw = RawContent.model_validate(node)
            capture(node, 'body', path, encoding=raw.body_encoding,
                    fidelity='exact-bytes', media_type=raw.media_type, context=context)
        if isinstance(node.get('httpResponseBody'), str) and any(
            field in node for field in ('httpResponseHeaders', 'httpResponseStatusCode', 'statusCode')
        ):
            capture(node, 'httpResponseBody', path, encoding='base64',
                    fidelity='exact-bytes', media_type=None, context=context)
        for key in ('raw_html', 'raw_xml', 'browserHtml'):
            if isinstance(node.get(key), str):
                capture(node, key, path, encoding='utf-8', fidelity='saved-text',
                        media_type='application/xml' if key == 'raw_xml' else 'text/html', context=context)
        # HouseEvidence.html stores a complete decoded page, unlike arbitrary
        # "html" fields in publisher JSON which might contain only a fragment.
        if (isinstance(node.get('html'), str)
                and ('document_groups' in node or 'witness_observations' in node)):
            capture(node, 'html', path, encoding='utf-8', fidelity='saved-text',
                    media_type='text/html', context=context)
        # MediaTextSource stores the decoded response alongside optional exact
        # bytes. Preserve both, even when they differ due to replacement decoding.
        if (isinstance(node.get('text'), str) and isinstance(node.get('url'), str)
                and ('raw_body' in node or 'status_code' in node
                     or any(part in ('master', 'master_checks', 'playlist', 'segments',
                                     'prior_responses', 'source_responses') for part in path))):
            capture(node, 'text', path, encoding='utf-8', fidelity='saved-text',
                    media_type=None, context=context)
        for key, child in node.items():
            child_context = context
            if key.startswith(('http://', 'https://')):
                child_context = {**context, 'context_url': key}
            walk(child, [*path, key], child_context)

    walk(record, [], {})
    return record, captures


def restore(record: object, captures: list[dict], get: Callable[[str], bytes]) -> object:
    """Reconstruct a saved JSON value and reject missing, corrupt or duplicate bodies."""
    value = _copy_json(record)
    for capture in captures:
        data = get(capture['body_key'])
        if len(data) != capture['bytes'] or hashlib.sha256(data).hexdigest() != capture['sha256']:
            raise ValueError(f"Body integrity failure: {capture['body_key']}")
        parent = value
        for part in capture['pointer'][:-1]:
            parent = parent[part]
        key = capture['pointer'][-1]
        if parent[key] is not None:
            raise ValueError(f"Body location already occupied: {capture['pointer']}")
        parent[key] = (data.decode('utf-8') if capture['string_encoding'] == 'utf-8'
                       else base64.b64encode(data).decode('ascii'))
    return value
