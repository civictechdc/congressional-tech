"""Explicit accepted body-text keys; never infer acceptance from version recency.

A manifest pins baseline versions and exceptions qualified by a retained report. The
same predicate selects text, reading outcomes and active unreadable decisions. It does
not change historical rows or authorize execution with a historical parser version.
"""
from hashlib import sha256
import json
from pathlib import Path
import re

from congress_api.retention.provenance import json_input


def at_versions(versions, prefix=''):
    def quote(value):
        return "'" + value.replace("'", "''") + "'"
    return '(' + ' OR '.join(f'({prefix}parser={quote(p)} AND {prefix}parser_version={quote(v)})'
                             for p, v in sorted(versions.items())) + ')'


def load(path, versions):
    """Read a frozen manifest and verify its qualification report before using any key."""
    if path is None:
        return dict(versions=dict(versions), overrides=[], identity=None)
    path = Path(path).resolve()
    raw = path.read_bytes()
    value = json.loads(raw)
    if set(value) != {'version', 'baseline_versions', 'qualification', 'overrides'} or value['version'] != 1:
        raise ValueError('Invalid body-text selection manifest')
    baseline = value['baseline_versions']
    if not isinstance(baseline, dict) or set(baseline) != set(versions):
        raise ValueError('Selection baseline must name exactly the supported parsers')
    def digest(value):
        return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None
    if not all(digest(v) for v in baseline.values()):
        raise ValueError('Selection baseline versions must be SHA-256 identities')
    proof = value['qualification']
    if not isinstance(proof, dict) or set(proof) != {'path', 'sha256'} or not digest(proof['sha256']):
        raise ValueError('Selection requires a pinned qualification report')
    if sha256((path.parent / proof['path']).read_bytes()).hexdigest() != proof['sha256']:
        raise ValueError('Selection qualification digest mismatch')
    seen = set()
    for row in value['overrides']:
        if set(row) != {'body_sha256', 'parser', 'parser_version', 'status', 'text_sha256'}:
            raise ValueError('Invalid selected reading key')
        key = (row['body_sha256'], row['parser'])
        if (not digest(key[0]) or key[1] not in baseline or not digest(row['parser_version'])
                or row['status'] not in {'completed', 'error', 'size_limit', 'unreadable'}):
            raise ValueError('Invalid selected reading identity or status')
        if (row['status'] == 'completed' and not digest(row['text_sha256'])) or (
                row['status'] != 'completed' and row['text_sha256'] is not None):
            raise ValueError('Only completed selections must pin a text digest')
        if key in seen:
            raise ValueError('Duplicate body/parser selection')
        seen.add(key)
    return dict(versions=baseline, overrides=value['overrides'],
                identity=dict(sha256=sha256(raw).hexdigest(), qualification=proof,
                              overrides=len(seen)))


def selection_input(work, selection):
    return json_input(work, 'body_text_choices', selection['overrides'],
                      body_sha256='Utf8', parser='Utf8', parser_version='Utf8', status='Utf8', text_sha256='Utf8')


def exception_versions(selection):
    return '(' + ' OR '.join(at_versions({p: v}) for p, v in sorted({
        (r['parser'], r['parser_version']) for r in selection['overrides']})) + ')'


def selected_sql(table, selection, *, body='r.body_sha', columns=None):
    """Partition pruning for baseline rows; exception keys build the narrow join."""
    versions = selection['versions']
    projection = 'r.*' if columns is None else ','.join('r.' + c for c in columns)
    baseline = f'SELECT {projection} FROM {table} r WHERE {at_versions(versions, "r.")}'
    if not selection['overrides']:
        return baseline
    match = f"decode(s.body_sha256,'hex')={body} AND s.parser=r.parser"
    return f'''SELECT {projection} FROM body_text_choices s RIGHT ANTI JOIN ({baseline}) r ON {match}
        UNION ALL SELECT {projection} FROM body_text_choices s JOIN
            (SELECT * FROM {table} WHERE {exception_versions(selection)}) r
        ON {match} AND s.parser_version=r.parser_version'''


def validation_queries(selection, *, text_table=None):
    """Check only the explicit exceptions, against actual rows and active refusals."""
    if not selection['overrides']:
        return []
    queries = [dict(name='invalid_selected_outcomes', sql='''SELECT count(*) AS n FROM (
        SELECT s.body_sha256,s.parser FROM body_text_choices s LEFT JOIN (
            SELECT body_sha,parser,parser_version,status FROM selected_body_readings
            UNION ALL SELECT decode(body_sha256,'hex') AS body_sha,parser,parser_version,'unreadable' AS status
                FROM selected_body_unreadable) r
        ON decode(s.body_sha256,'hex')=r.body_sha AND s.parser=r.parser
            AND s.parser_version=r.parser_version
        GROUP BY s.body_sha256,s.parser,s.status
        HAVING count(r.parser)<>1 OR min(r.status)<>s.status)''')]
    if text_table:
        queries.append(dict(name='invalid_selected_text', sql=f'''SELECT count(*) AS n FROM (
            SELECT s.body_sha256,s.parser FROM body_text_choices s LEFT JOIN
                (SELECT * FROM {text_table} WHERE {exception_versions(selection)}) t
            ON decode(s.body_sha256,'hex')=t.body_sha AND s.parser=t.parser AND s.parser_version=t.parser_version
            GROUP BY s.body_sha256,s.parser,s.status,s.text_sha256
            HAVING (s.status='completed' AND (count(t.parser)<>1 OR min(encode(t.text_sha256,'hex'))<>s.text_sha256
                OR min(encode(sha256(t.text),'hex'))<>s.text_sha256))
                OR (s.status<>'completed' AND count(t.parser)<>0))'''))
    return queries


def validate_counts(counts):
    for name in ('invalid_selected_outcomes', 'invalid_selected_text'):
        if counts.get(name, [{'n': 0}])[0]['n']:
            raise ValueError(f'Body-text selection does not match retained rows: {name}')
