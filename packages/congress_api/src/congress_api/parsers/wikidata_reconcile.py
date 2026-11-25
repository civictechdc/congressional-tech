"""Parse retained Wikidata W3C Reconciliation Service JSON responses (ct-39u8).

Pure per (body, version): takes no URL and makes no network calls. Extracts
candidate QIDs, labels, descriptions, scores, and API match flags per query key
into typed reading fields so model SQL can apply acceptance and review rules.
"""
import json
import math
import re

_QID_RE = re.compile(r'^Q[0-9]+$')


def _reject_constant(_value):
    raise ValueError('Non-finite JSON number')


def _error(reason: str) -> dict:
    return dict(
        status='error',
        error_type='unsupported_wikidata_reconcile',
        format='json',
        fields=[dict(field='reason', value=reason[:500])],
    )


def reading_row(body: bytes) -> dict:
    """One completed Wikidata reconciliation reading, or an explicit refusal."""
    try:
        text = body.decode('utf-8')
        payload = json.loads(text, parse_constant=_reject_constant)
    except (UnicodeError, ValueError) as error:
        return _error(f'{type(error).__name__}: {error}')
    if not isinstance(payload, dict) or not payload:
        return _error('Reconciliation response must be a non-empty JSON object')
    fields = []
    for query_key in sorted(payload):
        if not isinstance(query_key, str) or not query_key:
            return _error('Query key must be a non-empty string')
        entry = payload[query_key]
        if not isinstance(entry, dict) or not isinstance(entry.get('result'), list):
            return _error(f'Query {query_key!r} missing result list')
        candidates = []
        for cand in entry['result']:
            if not isinstance(cand, dict):
                return _error(f'Query {query_key!r} candidate must be an object')
            qid = cand.get('id')
            score = cand.get('score')
            if not isinstance(qid, str) or _QID_RE.fullmatch(qid) is None:
                return _error(f'Query {query_key!r} candidate has invalid QID {qid!r}')
            if type(score) not in (int, float) or not math.isfinite(float(score)):
                return _error(f'Query {query_key!r} candidate {qid} has invalid score')
            name = cand.get('name')
            desc = cand.get('description')
            candidates.append(dict(
                id=qid,
                name=name.strip() if isinstance(name, str) and name.strip() else None,
                description=desc.strip() if isinstance(desc, str) and desc.strip() else None,
                score=float(score),
                match=bool(cand.get('match', False)),
            ))
        fields.append(dict(
            field=f'query:{query_key}',
            value=json.dumps(candidates, ensure_ascii=False, separators=(',', ':')),
        ))
    return dict(
        status='completed',
        error_type=None,
        format='json',
        xml_root=None,
        title=None,
        text_bytes=0,
        text_head=None,
        content_date=None,
        base_href=None,
        intact=True,
        link_count=0,
        link_text_bytes=0,
        links=[],
        fields=fields,
    )
