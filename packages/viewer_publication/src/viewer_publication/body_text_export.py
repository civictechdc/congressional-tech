"""The per-release `body_text` export and its pointer (data model §6.6).

One docspec-rs SQL job reads `body_text` at an exact snapshot, keeps one row per `body_sha` the
release's `detail.saved_body` shows at each parser's declared version, and writes
``saved_body, text, page_offsets, text_sha256`` ordered by ``saved_body`` with the `ranged`
profile and small row groups (``model/jobs/body-text-export.json``). Only this SQL truncates
text, to a JSON-escaped byte bound: SpicyEngine's row limit counts the text as JSON. A truncated
row's ``text_sha256`` is of the text it carries, so a reader's per-row check still holds; its
``page_offsets`` stay the lake's, and offsets past the text's end mark the pages cut.

The export is written create-only to ``derived/body_text/<sha256>.parquet`` and pinned by its
own pointer, ``derived/body_text/current.json``, never by the release manifest (§8.1, §8.3).
Once the pointer has moved, every other export under the prefix is deleted (plan §2, Lifetimes:
only the export the current pointer names is kept).

Joins keep text off build sides (§6.6, AGENTS.md): the saved-body set and the narrow chosen
keys build, the text rows probe. Cost: one pass over the selected text, materialized once to
scratch and sorted by the writer with spill; the counts read narrow steps.
"""
from hashlib import md5, sha256
import json
from pathlib import Path
import re

from congress_api.lake import readings
from congress_api.lake.tables import table_input
from congress_api.retention.provenance import durable_json, run_job

ROOT = Path(__file__).resolve().parents[4]
DEFINITION = ROOT / 'model/jobs/body-text-export.json'
CONTENT_TYPE = 'application/vnd.apache.parquet'
COLUMNS = ['saved_body', 'text', 'page_offsets', 'text_sha256']


def load_definition(path=DEFINITION):
    value = json.loads(Path(path).read_text())
    settings = value.get('settings', {})
    if (value.get('version') != 1 or settings.get('profile') != 'ranged' or settings.get('columns') != COLUMNS
            or settings.get('order_by') != ['saved_body'] or not 128 <= settings.get('row_group_rows', 0) <= 256
            or type(value.get('max_text_json_bytes')) is not int or value['max_text_json_bytes'] < 64
            or not set(value.get('parsers', ())) or not value.get('prefix', '').endswith('/')):
        raise ValueError('Invalid body-text export definition')
    return value


def _quote(value):
    return "'" + value.replace("'", "''") + "'"


def _at_versions(versions, alias=''):
    """The declared (parser, version) partitions as a literal predicate the scan can prune on."""
    return '(' + ' OR '.join(f'({alias}parser={_quote(p)} AND {alias}parser_version={_quote(v)})'
                             for p, v in sorted(versions.items())) + ')'


# Regex classes (Rust syntax, in SQL literals that keep backslashes as written).
QUOTED = r'["\\]'
SHORT_ESCAPES = r'[\x08\x09\x0a\x0c\x0d]'
LONG_ESCAPES = r'[\x00-\x07\x0b\x0e-\x1f]'


def json_bytes_sql(x):
    """Bytes of ``x`` as a JSON string: two quotes, UTF-8 kept, `"` and `\\` escaped, the five
    short control escapes one extra byte each and every other C0 control ``\\u00XX`` (5 extra)."""
    def count(pattern):
        return f"(character_length({x})-character_length(regexp_replace({x},'{pattern}','','g')))"
    return f'(octet_length({x})+2+{count(QUOTED)}+{count(SHORT_ESCAPES)}+5*{count(LONG_ESCAPES)})'


def export_steps(versions, *, max_json_bytes):
    """Saved bodies, then narrow chosen keys, then the text rows with any cut applied."""
    bound = int(max_json_bytes)
    # Worst case six bytes per character (a \\u00XX escape), so this prefix always fits.
    floor_chars = (bound - 2) // 6
    proportional = f'cast(floor(character_length(text)*{bound - 2}/json_bytes) AS BIGINT)'
    cut = f'substr(text,1,{proportional})'
    return [
        dict(name='saved', materialize=True,
             sql='SELECT DISTINCT saved_body FROM detail WHERE saved_body IS NOT NULL'),
        dict(name='text_keys', materialize=True, sql=f'''SELECT b.body_sha,b.parser FROM saved s RIGHT SEMI JOIN
            (SELECT body_sha,parser FROM body_text WHERE {_at_versions(versions)}) b ON s.saved_body=b.body_sha'''),
        # A body has one sniffed format, so one parser; min() keeps the export single-row anyway.
        dict(name='chosen', materialize=True, sql='''SELECT body_sha,min(parser) AS parser,count(*) AS parsers
            FROM text_keys GROUP BY body_sha'''),
        dict(name='measured', sql=f'''SELECT t.body_sha,t.parser,t.text,t.page_offsets,t.ocr_pages,t.text_sha256,
            {json_bytes_sql('t.text')} AS json_bytes FROM chosen c RIGHT SEMI JOIN
            (SELECT * FROM body_text WHERE {_at_versions(versions)}) t ON c.body_sha=t.body_sha AND c.parser=t.parser'''),
        dict(name='exported', materialize=True, sql=f'''SELECT body_sha AS saved_body,parser,page_offsets,
            cardinality(ocr_pages) AS ocr_page_count,json_bytes>{bound} AS truncated,json_bytes,
            CASE WHEN json_bytes<={bound} THEN text
                 WHEN {json_bytes_sql(cut)}<={bound} THEN {cut}
                 ELSE substr(text,1,{floor_chars}) END AS text,
            CASE WHEN json_bytes<={bound} THEN text_sha256
                 WHEN {json_bytes_sql(cut)}<={bound} THEN arrow_cast(sha256({cut}),'FixedSizeBinary(32)')
                 ELSE arrow_cast(sha256(substr(text,1,{floor_chars})),'FixedSizeBinary(32)') END AS text_sha256
            FROM measured'''),
    ]


def coverage_queries(versions, *, with_readings, with_unreadable):
    queries = [
        dict(name='saved', sql='SELECT count(*) AS n FROM saved'),
        dict(name='rows', sql='''SELECT parser,count(*) AS rows,coalesce(sum(ocr_page_count),0) AS ocr_pages,
            count(*) FILTER (WHERE ocr_page_count>0) AS ocr_bodies,count(*) FILTER (WHERE truncated) AS truncated,
            max(json_bytes) AS max_json_bytes FROM exported GROUP BY parser ORDER BY parser'''),
        dict(name='parser_conflicts', sql='SELECT count(*) AS n FROM chosen WHERE parsers>1'),
    ]
    if with_readings:
        queries.append(dict(name='readings', sql=f'''SELECT r.parser,r.status,count(*) AS n FROM saved s RIGHT SEMI JOIN
            (SELECT body_sha,parser,status FROM readings WHERE {_at_versions(versions)}) r ON s.saved_body=r.body_sha
            GROUP BY r.parser,r.status ORDER BY r.parser,r.status'''))
    if with_unreadable:
        queries.append(dict(name='unreadable', sql=f'''SELECT u.parser,count(*) AS n FROM saved s RIGHT SEMI JOIN
            (SELECT decode(body_sha256,'hex') AS body_sha,parser FROM unreadable a
             WHERE {_at_versions(versions, 'a.')} AND NOT EXISTS (SELECT 1 FROM unreadable b WHERE b.supersedes=a.id)) u
            ON s.saved_body=u.body_sha GROUP BY u.parser ORDER BY u.parser'''))
    return queries


def file_facts(path):
    """SHA-256, MD5 and size of one file in a single read, as archive_multipart takes them."""
    whole, checksum, size = sha256(), md5(), 0
    with Path(path).open('rb') as source:
        while block := source.read(8 << 20):
            whole.update(block)
            checksum.update(block)
            size += len(block)
    return {'sha256': whole.hexdigest(), 'md5': checksum.hexdigest(), 'size': size}


def footer_sha256(path):
    """SHA-256 of the Parquet footer: its metadata, 4-byte length and closing magic."""
    with Path(path).open('rb') as source:
        source.seek(-8, 2)
        tail = source.read(8)
        if tail[4:] != b'PAR1':
            raise ValueError('Export is not a Parquet file')
        size = int.from_bytes(tail[:4], 'little') + 8
        source.seek(-size, 2)
        return sha256(source.read(size)).hexdigest()


def export(*, engine, work, body_text, detail, readings_table=None, unreadable_files=(), versions=None,
           definition=None, release_id=None):
    """Run the export job into ``work`` and write the pointer it would publish beside it.

    ``body_text`` and ``readings_table`` are exact native pins (or Parquet stages in tests);
    ``detail`` is the release's local `detail.parquet`. Returns the pointer.
    """
    from congress_api.retention.provenance import field
    definition = load_definition() if definition is None else definition
    versions = versions or {p: readings.current_version(p) for p in definition['parsers']}
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    inputs = [table_input('body_text', body_text), dict(name='detail', kind='parquet', path=str(Path(detail).resolve()))]
    if readings_table is not None:
        inputs.append(table_input('readings', readings_table))
    if unreadable_files:
        schema = dict(id='Utf8', body_sha256='Utf8', parser='Utf8', parser_version='Utf8', supersedes='Utf8')
        inputs.append(dict(name='unreadable', kind='json_lines', files=list(unreadable_files),
                           schema=dict(fields=[field(k, v) for k, v in schema.items()], metadata={})))
    settings = dict(definition['settings'], order_by=[dict(field=k) for k in definition['settings']['order_by']],
                    dictionary_columns=[], delta_columns=[], key_column=None)
    output = work / 'export.parquet'
    counts = run_job(work / 'job', engine, inputs=inputs,
        steps=export_steps(versions, max_json_bytes=definition['max_text_json_bytes']),
        outputs=[dict(name='export.parquet', path=str(output), sql='SELECT * FROM exported', settings=settings)],
        queries=coverage_queries(versions, with_readings=readings_table is not None,
                                 with_unreadable=bool(unreadable_files)))
    if counts['parser_conflicts'][0]['n']:
        raise ValueError('A saved body has body text under more than one parser')
    facts = file_facts(output)
    digest, size = facts['sha256'], facts['size']
    by_parser = {row['parser']: row for row in counts['rows']}
    pointer = dict(version=1, key=definition['prefix'] + digest + '.parquet', sha256=digest, bytes=size,
        rows=sum(row['rows'] for row in by_parser.values()), footer_sha256=footer_sha256(output),
        row_group_rows=definition['settings']['row_group_rows'], max_text_json_bytes=definition['max_text_json_bytes'],
        body_text=body_text if isinstance(body_text, dict) else None, release_id=release_id,
        parser_versions=dict(sorted(versions.items())),
        coverage=dict(saved_bodies=counts['saved'][0]['n'],
            bodies_with_text={p: r['rows'] for p, r in by_parser.items()},
            ocr_pages=sum(r['ocr_pages'] for r in by_parser.values()),
            ocr_bodies=sum(r['ocr_bodies'] for r in by_parser.values()),
            truncated=sum(r['truncated'] for r in by_parser.values()),
            max_json_bytes=max((r['max_json_bytes'] for r in by_parser.values()), default=None),
            warc_unwrapped=by_parser.get('warc', {}).get('rows', 0),
            readings={f"{r['parser']}:{r['status']}": r['n'] for r in counts.get('readings', [])} or None,
            unreadable={r['parser']: r['n'] for r in counts.get('unreadable', [])} if unreadable_files else None))
    durable_json(work / 'current.json', pointer)
    return pointer


def publish(client, *, bucket, export_path, pointer, expected_pointer_etag, journal, pointer_key=None):
    """Upload the export create-only by bounded multipart, then move the pointer conditionally.

    The Parquet goes to its content-named key through ``archive_multipart.transfer`` (8 MiB
    parts, ``If-None-Match: *`` on completion); a key that already exists must already hold
    these bytes. The pointer is a compare-and-swap: ``If-Match`` its current ETag, or
    ``If-None-Match: *`` when none exists. ``journal`` receives each upload stage.
    """
    from viewer_publication import archive_multipart
    from viewer_publication.archive_publish import IMMUTABLE
    from viewer_publication.client import publish_manifest_pointer
    definition = load_definition()
    export_path = Path(export_path)
    facts = file_facts(export_path)
    if facts['sha256'] != pointer['sha256'] or facts['size'] != pointer['bytes'] \
            or pointer['key'] != definition['prefix'] + facts['sha256'] + '.parquet':
        raise ValueError('Export bytes differ from the pointer that names them')
    plan = archive_multipart.plan_file(export_path, facts)
    outcome = archive_multipart.transfer(client, bucket=bucket, key=pointer['key'], source=export_path,
        facts=facts, plan=plan, content_type=CONTENT_TYPE, cache_control=IMMUTABLE, record=journal)
    if outcome == 'already_exists':
        head = client.head_object(Bucket=bucket, Key=pointer['key'])
        if head.get('ContentLength') != facts['size'] or head.get('ETag', '').strip('"') not in {plan['etag'], facts['md5']}:
            raise ValueError('An existing export key holds other bytes')
    pointer_key = pointer_key or definition['pointer']
    published = publish_manifest_pointer(client, bucket=bucket, pointer=pointer,
        key=pointer_key, expected_etag=expected_pointer_etag)
    retired = retire_unnamed(client, bucket=bucket, prefix=definition['prefix'], pointer_key=pointer_key)
    return dict(export=outcome, pointer=published, retired=retired)


def retire_unnamed(client, *, bucket, prefix, pointer_key):
    """Delete each export under ``prefix`` that the current pointer does not name; return their keys.

    The pointer is read afresh, so a pointer another publisher moved since is the one kept. Only
    content-named exports (``<prefix><sha256>.parquet``) are candidates, never the pointer or any
    other key, and one written after the pointer last changed is kept: it may be another
    publisher's upload whose pointer move is still to come. Deletion only; no object is replaced.
    Cost: one pointer read, one listing page per 1,000 keys and one DELETE per retired export.
    """
    response = client.get_object(Bucket=bucket, Key=pointer_key)
    with response['Body'] as body:
        named = json.loads(body.read(1 << 20))['key']
    moved = response['LastModified']
    pattern = re.compile(re.escape(prefix) + '[0-9a-f]{64}[.]parquet')
    if pattern.fullmatch(named) is None:
        raise ValueError('The body-text pointer names no content-named export')
    retired, token = [], None
    while True:
        request = dict(Bucket=bucket, Prefix=prefix, **({} if token is None else dict(ContinuationToken=token)))
        page = client.list_objects_v2(**request)
        for item in page.get('Contents', []):
            if pattern.fullmatch(item['Key']) and item['Key'] != named and item['LastModified'] <= moved:
                retired.append(item['Key'])
        if not page.get('IsTruncated'):
            break
        following = page.get('NextContinuationToken')
        if not isinstance(following, str) or not following or following == token:
            raise ValueError('Body-text export listing did not advance')
        token = following
    for key in retired:  # after the listing, so no page is read while keys are being removed
        client.delete_object(Bucket=bucket, Key=key)
    return retired


SPEC_REQUIRED = {'body_text', 'detail', 'work'}
SPEC_OPTIONAL = {'readings', 'unreadable_files', 'release_id'}


def _pointer_etag(client, *, bucket, key):
    """The pointer's current ETag for the compare-and-swap, or None when there is none yet."""
    try:
        return client.head_object(Bucket=bucket, Key=key)['ETag']
    except Exception as error:
        if (getattr(error, 'response', None) or {}).get('Error', {}).get('Code') in {'404', 'NoSuchKey', 'NotFound'}:
            return None
        raise


def main(argv=None, *, client=None):
    """Plan, build or publish one release's body_text export, as `congress_api.cli.body_text` runs the producer.

    The spec names ``body_text`` (an exact native pin or a Parquet path), the release's local
    ``detail`` Parquet and ``work``; ``readings`` (pin or path), ``unreadable_files`` and
    ``release_id`` add coverage. ``--execute`` writes ``export.parquet`` and ``current.json`` under
    ``work`` on a local-only engine; ``--publish`` then uploads them to the definition's bucket with
    R2 credentials from the environment, journaling each multipart stage beside them.
    """
    import argparse
    import os
    from docspec_client.client import NativeDatasets
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--engine-config', default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--plan', action='store_true', help='Validate the spec and name the work directory')
    actions.add_argument('--execute', action='store_true', help='Build the export and its pointer under work')
    parser.add_argument('--publish', action='store_true', help='With --execute: upload the export, move the pointer')
    args = parser.parse_args(argv)
    if args.publish and not args.execute:
        parser.error('--publish requires --execute')
    spec = json.loads(args.spec.read_text())
    if not isinstance(spec, dict) or not SPEC_REQUIRED <= spec.keys() or spec.keys() - SPEC_REQUIRED - SPEC_OPTIONAL:
        parser.error('Body-text export spec requires body_text, detail and work')
    definition = load_definition()
    work = Path(spec['work']).resolve()
    if args.plan:
        print(json.dumps(dict(status='planned', executed=False, work=str(work), key_prefix=definition['prefix'],
                              pointer=definition['pointer']), sort_keys=True))
        return 0
    if not args.engine_config:
        parser.error('An explicit pinned engine configuration is required')
    with NativeDatasets.from_config(args.engine_config) as engine:
        if engine.remote is not None:
            parser.error('The body-text export runs on a local-only engine configuration')
        pointer = export(engine=engine, work=work, body_text=spec['body_text'], detail=spec['detail'],
                         readings_table=spec.get('readings'), unreadable_files=spec.get('unreadable_files', ()),
                         definition=definition, release_id=spec.get('release_id'))
    result = dict(status='exported', executed=True, work=str(work), pointer=pointer)
    if args.publish:
        from congress_shared.storage import connect_r2
        bucket = definition['bucket']
        client = client or connect_r2(bucket=bucket, connect_timeout=15, read_timeout=180,
                                      retries={'total_max_attempts': 1})
        result.update(status='published', published=publish(client, bucket=bucket, export_path=work / 'export.parquet',
            pointer=pointer, expected_pointer_etag=_pointer_etag(client, bucket=bucket, key=definition['pointer']),
            journal=lambda stage: durable_json(work / 'upload-journal.json', stage)))
    print(json.dumps(result, default=str, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
