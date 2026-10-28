"""Shared native release layout; application models supply complete document rows."""
from hashlib import md5, sha256
import json
from pathlib import Path


ROOT = Path(__file__).parents[4]


EMPTY_STRINGS = "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')"


def legacy_meeting_keys(url):
    """Retain the old catalog URL selector for conversion and parity checks."""
    key = 'coalesce(' + ','.join(f"array_element(regexp_match({url},'{pattern}'),1)" for pattern in [
        '/meetings/[^/]+/[^/]+/[0-9]{8}/([0-9]+)/', '(?i)[?&]eventid=([0-9]+)',
        '/(?:house|senate|joint)-event/([0-9]+)']) + ')'
    numeric = f'try_cast({key} AS BIGINT)'
    return f'CASE WHEN {numeric} IS NULL THEN {EMPTY_STRINGS} ELSE make_array(cast({numeric} AS VARCHAR)) END'


TS = "arrow_cast(NULL,'Timestamp(Microsecond, Some(\"UTC\"))')"


def _empty_struct(**fields):
    args = ','.join(f"'{name}',{value}" for name, value in fields.items())
    return f'array_slice(make_array(named_struct({args})),1,0)'


EMPTY_ALTERNATES = _empty_struct(format='cast(NULL AS VARCHAR)', body="arrow_cast(NULL,'FixedSizeBinary(32)')",
                                suffix='cast(NULL AS VARCHAR)', size='cast(NULL AS BIGINT)')


EMPTY_FACTS = _empty_struct(field='cast(NULL AS VARCHAR)', value='cast(NULL AS VARCHAR)')


LIST_COLUMNS = ['filename', 'title', 'document_kind', 'document_family', 'committee_keys', 'chambers',
    'congress', 'format', 'document_date', 'first_captured', 'date_kind', 'saved_kind', 'hidden',
    'meeting_keys', 'measure_keys', 'bioguide_ids', 'witness_keys', 'version_keys']


DETAIL_COLUMNS = ['link_key', 'saved_body', 'saved_suffix', 'saved_media_type', 'saved_bytes',
    'document_date_source', 'in_archive_since', 'removed_on', 'review_note', 'review_decided_at',
    'src_start', 'src_len', 'rec_start', 'rec_len', 'alternates', 'package_id', 'facts']


def _step(name, sql, *, materialize=False, release_after=()):
    step = dict(name=name, sql=sql, materialize=materialize)
    if release_after:
        step['release_after'] = list(release_after)
    return step


def _binary(expression, size):
    return f"arrow_cast(decode({expression},'hex'),'FixedSizeBinary({size})')"


def _hash_key(expression, prefix=''):
    return _binary(f"substr(encode(sha256('{prefix}' || {expression}),'hex'),1,16)", 8)


def _lookup_steps(source):
    # DM8.2's fixed lookup spelling; the query remains byte-for-byte intact.
    # Source addresses here are absolute HTTP(S), rather than relative links.
    return [
        _step('lookup_parts', f"""SELECT DISTINCT list_row,url,
            lower(array_element(regexp_match(url,'^([a-zA-Z][a-zA-Z0-9+.-]*)://'),1)) AS scheme,
            regexp_replace(url,'^[a-zA-Z][a-zA-Z0-9+.-]*://','') AS tail FROM {source} WHERE url IS NOT NULL"""),
        _step('lookup_hosts', """SELECT *,array_element(regexp_match(tail,'^([^/?#]*)'),1) AS authority FROM lookup_parts"""),
        _step('lookup_paths', """SELECT *,regexp_replace(substr(tail,length(authority)+1),'#.*$','') AS remainder,
            regexp_replace(lower(authority),'^www[.]','') AS host FROM lookup_hosts"""),
        _step('lookup_values', """SELECT list_row,concat(
            CASE WHEN scheme='http' THEN regexp_replace(host,':80$','')
                 WHEN scheme='https' THEN regexp_replace(host,':443$','') ELSE host END,
            regexp_replace(array_element(regexp_match(remainder,'^([^?]*)'),1),'/$',''),
            coalesce(array_element(regexp_match(remainder,'([?].*)$'),1),'')) AS lookup_url FROM lookup_paths"""),
        _step('lookup_keys_full', f"SELECT {_hash_key('lookup_url', 'lookup:')} AS lookup_key,list_row,lookup_url FROM lookup_values", materialize=True),
        _step('url_keys', 'SELECT DISTINCT lookup_key,list_row FROM lookup_keys_full'),
    ]


def _settings(profile, order, *, columns=None, dictionary=(), delta=()):
    return dict(profile=profile, row_group_rows=65536, order_by=[dict(field=name) for name in order],
        columns=columns or [], dictionary_columns=list(dictionary), delta_columns=list(delta),
        key_column=order[0] if profile == 'lookup' else None, created_by='docspec archive release v1', footer_limit=512 << 10)


def _core(steps, output,*,lookup_extra=None):
    order = ['filename', 'document_date', 'first_captured', 'doc_key']
    steps += [_step('ordered', "SELECT *,cast(row_number() OVER(ORDER BY filename,document_date NULLS LAST,first_captured NULLS LAST,doc_key)-1 AS INT) AS list_row FROM normalized", materialize=True, release_after=["normalized"]),
        _step('source_rows', """SELECT o.list_row,s.*,cast(row_number() OVER(PARTITION BY o.list_row ORDER BY s.is_saved DESC,s.first_seen NULLS LAST,s.url,s.member_path NULLS LAST)-1 AS INT) AS ordinal,
            cast(row_number() OVER(ORDER BY o.list_row,s.is_saved DESC,s.first_seen NULLS LAST,s.url,s.member_path NULLS LAST)-1 AS INT) AS source_index
            FROM source_input s JOIN ordered o ON s.doc_key=o.doc_key""", materialize=True, release_after=["source_input"]),
        _step('source_ranges', 'SELECT doc_key,min(source_index) AS src_start,cast(count(*) AS INT) AS src_len FROM source_rows GROUP BY doc_key'),
        _step('recovery_rows', """SELECT o.list_row,r.*,cast(row_number() OVER(PARTITION BY o.list_row ORDER BY r.recovery_key)-1 AS INT) AS ordinal,
            cast(row_number() OVER(ORDER BY o.list_row,r.recovery_key)-1 AS INT) AS recovery_index
            FROM recovery_input r JOIN ordered o ON r.doc_key=o.doc_key""", materialize=True, release_after=["recovery_input"]),
        _step('recovery_ranges', 'SELECT doc_key,min(recovery_index) AS rec_start,cast(count(*) AS INT) AS rec_len FROM recovery_rows GROUP BY doc_key'),
        _step('details', f"""SELECT o.*,CASE WHEN saved_kind='recovery' THEN {_hash_key('o.source_url', 'url:')}
            ELSE {_binary('substr(body_hex,1,16)', 8)} END AS link_key,
            {_binary('body_hex', 32)} AS saved_body,CASE WHEN body_hex IS NOT NULL THEN suffix END AS saved_suffix,CASE WHEN body_hex IS NOT NULL THEN media_type END AS saved_media_type,bytes AS saved_bytes,
            coalesce(s.src_start,cast(0 AS INT)) AS src_start,coalesce(s.src_len,cast(0 AS INT)) AS src_len,
            coalesce(r.rec_start,cast(0 AS INT)) AS rec_start,coalesce(r.rec_len,cast(0 AS INT)) AS rec_len
            FROM ordered o LEFT JOIN source_ranges s ON o.doc_key=s.doc_key LEFT JOIN recovery_ranges r ON o.doc_key=r.doc_key""", materialize=True),
        _step('body_links', "SELECT list_row,unnest(link_bodies) AS body_hex FROM ordered"),
        _step('all_links', f"""SELECT {_binary('substr(body_hex,1,16)', 8)} AS link_key,list_row,'body:' || body_hex AS origin FROM body_links
            UNION ALL SELECT {_hash_key('original_url', 'url:')},list_row,'url:' || original_url FROM recovery_rows"""),
        _step('links', 'SELECT link_key,min(list_row) AS list_row FROM all_links GROUP BY link_key'),
        _step('lookup_sources', "SELECT DISTINCT list_row,url FROM source_rows UNION SELECT DISTINCT list_row,original_url AS url FROM recovery_rows"+((' UNION '+lookup_extra) if lookup_extra else '')),
    ]
    steps += _lookup_steps('lookup_sources')
    specs = [
        ('list', 'ordered', _settings('whole', order, columns=LIST_COLUMNS,
            dictionary=[*(f'{name}.list.item' for name in ['document_kind', 'document_family', 'committee_keys', 'chambers', 'meeting_keys', 'measure_keys', 'bioguide_ids', 'witness_keys', 'version_keys']), 'format', 'date_kind', 'saved_kind'], delta=['filename', 'title'])),
        ('detail', 'details', _settings('ranged', order, columns=DETAIL_COLUMNS, dictionary=['saved_suffix', 'saved_media_type', 'document_date_source', 'alternates.list.item.format', 'alternates.list.item.suffix', 'facts.list.item.field'])),
        ('links', 'links', _settings('lookup', ['link_key'])),
        ('urls', 'url_keys', _settings('lookup', ['lookup_key', 'list_row'])),
        ('sources', 'source_rows', _settings('ranged', ['list_row', 'ordinal'], columns=['list_row', 'ordinal', 'url', 'member_path', 'is_saved', 'first_seen', 'listed_on', 'link_text', 'doc_type', 'posted'])),
        ('recoveries', 'recovery_rows', _settings('ranged', ['list_row', 'ordinal'], columns=['list_row', 'ordinal', 'kind', 'body', 'suffix', 'bytes', 'imported_at', 'recovered_url', 'identity_note'], dictionary=['kind', 'suffix'])),
    ]
    outputs = [dict(name=name + '.parquet', path=str(output / (name + '.parquet')), sql='SELECT * FROM ' + table, settings=settings) for name, table, settings in specs]
    return outputs


def _content(path, value):
    data = (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
    path.write_bytes(data)
    return dict(name=path.name, sha256=sha256(data).hexdigest(), md5=md5(data).hexdigest(), size=len(data), rows=0, producer='archive', coverage={})


def release_identity(schema_version,files):
    """Hash the one content-only ordered file list declared by DM8.3."""
    identity=[schema_version,[[item['name'],item['sha256'],item['size'],item['rows']] for item in files]]
    return sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _release_schema():
    # The interface registry is shared with the reader; policy metadata stays
    # content-only while all row transformations and Parquet writing stay native.
    return json.loads((ROOT / 'model/registries/release-schema.json').read_text())


NORMAL_DEFAULTS = dict(body_expected='true', title='cast(NULL AS VARCHAR)', document_kind=EMPTY_STRINGS,
    document_family=EMPTY_STRINGS, committee_keys=EMPTY_STRINGS, chambers=EMPTY_STRINGS,
    congress='cast(NULL AS SMALLINT)', format="'other'", document_date='cast(NULL AS DATE)',
    first_captured='cast(NULL AS DATE)', date_kind="'unknown'", saved_kind="'original'", hidden='false',
    meeting_keys=EMPTY_STRINGS, measure_keys=EMPTY_STRINGS, bioguide_ids=EMPTY_STRINGS,
    witness_keys=EMPTY_STRINGS, version_keys=EMPTY_STRINGS, suffix="'.gz'", media_type="'application/octet-stream'",
    bytes='cast(0 AS BIGINT)', document_date_source='cast(NULL AS VARCHAR)', in_archive_since='cast(NULL AS DATE)',
    removed_on='cast(NULL AS DATE)', review_note='cast(NULL AS VARCHAR)', review_decided_at='cast(NULL AS DATE)',
    alternates=EMPTY_ALTERNATES, package_id='cast(NULL AS VARCHAR)', facts=EMPTY_FACTS, link_bodies=EMPTY_STRINGS)


def _normal(table, **values):
    values = dict(NORMAL_DEFAULTS, **values)
    for name in ['document_kind', 'document_family', 'committee_keys', 'chambers', 'meeting_keys',
                 'measure_keys', 'bioguide_ids', 'witness_keys', 'version_keys', 'link_bodies']:
        values[name] = f"arrow_cast(array_sort(array_distinct(coalesce({values[name]},{EMPTY_STRINGS}))),'List(Utf8)')"
    return 'SELECT ' + ','.join(f'{expression} AS "{name}"' for name, expression in values.items()) + ' FROM ' + table



def _execute(inputs, steps, *, output, scratch, engine, origin, auxiliary=None, capture_scope=None, extra_outputs=(), diagnostics=(), metadata_queries=(), content_files=None,lookup_extra=None):
    output.mkdir(parents=True, exist_ok=False)
    outputs = _core(steps, output,lookup_extra=lookup_extra)
    # Entity files and the capture fixture have their full declared schema,
    # including when this documents-only input provides no rows for them.
    for name, sql, keys, dictionary in (_auxiliary() if auxiliary is None else auxiliary):
        steps.append(_step(name + '_export', sql, materialize=True))
        outputs.append(dict(name=name + '.parquet', path=str(output / (name + '.parquet')), sql='SELECT * FROM ' + name + '_export',
            settings=_settings('whole', keys, dictionary=dictionary)))
    outputs.extend(extra_outputs)
    facets = [f"SELECT '{name}' AS facet,cast({name} AS VARCHAR) AS value,count(*) AS count FROM ordered WHERE NOT hidden GROUP BY {name}" for name in ['format', 'congress', 'saved_kind']]
    facets += [f"SELECT '{name}' AS facet,value,count(*) AS count FROM (SELECT unnest({name}) AS value FROM ordered WHERE NOT hidden) GROUP BY value" for name in ['document_kind', 'document_family', 'committee_keys', 'chambers', 'meeting_keys']]
    facets = ' UNION ALL '.join(facets)
    queries = [dict(name='facets', sql='SELECT * FROM (' + facets + ') WHERE value IS NOT NULL ORDER BY facet,value'),
        dict(name='invariants', sql="""SELECT (SELECT count(*) FROM (SELECT doc_key FROM ordered GROUP BY doc_key HAVING count(*)>1)) AS duplicate_documents,
            (SELECT count(*) FROM ordered WHERE body_expected AND (body_hex IS NULL OR length(body_hex)<>64)) AS missing_saved_bodies,
            (SELECT count(*) FROM ordered WHERE body_hex IS NOT NULL AND (bytes IS NULL OR bytes<0)) AS missing_saved_sizes,
            (SELECT count(*) FROM (SELECT link_key FROM all_links GROUP BY link_key HAVING count(DISTINCT origin)>1)) AS link_collisions,
            (SELECT count(*) FROM (SELECT lookup_key FROM lookup_keys_full GROUP BY lookup_key HAVING count(DISTINCT lookup_url)>1)) AS lookup_collisions""")]
    queries.extend(diagnostics)
    queries.extend(metadata_queries)
    coverage_parts = []
    for name, relation in [('list', None), ('detail', None), ('links', 'links'), ('urls', 'url_keys'), ('sources', 'source_rows'), ('recoveries', 'recovery_rows')]:
        source = 'ordered o' if relation is None else f'ordered o JOIN (SELECT DISTINCT list_row FROM {relation}) r ON o.list_row=r.list_row'
        coverage_parts.append(f"SELECT '{name}.parquet' AS file,min(o.congress) AS congress_start,max(o.congress) AS congress_end,min(o.document_date) AS date_start,max(o.document_date) AS date_end FROM {source}")
    coverage_parts.append("SELECT 'meetings.parquet' AS file,cast(NULL AS SMALLINT) AS congress_start,cast(NULL AS SMALLINT) AS congress_end,min(meeting_date) AS date_start,max(meeting_date) AS date_end FROM meetings_export")
    queries.append(dict(name='coverage', sql=' UNION ALL '.join(coverage_parts)))
    spec = dict(scratch=str(scratch / 'native'), inputs=inputs, steps=steps, outputs=outputs, queries=queries)
    spec_path = scratch / 'job.json'
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, separators=(',', ':')))
    from docspec_client.models import DocSpecFailure
    try:
        result = engine.run_job(spec_path)
    except DocSpecFailure as error:
        if error.completed is not None:
            (scratch / 'result.json').write_text(error.stdout)
        raise
    (scratch / 'result.json').write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    reports = {query['name']: query['data'] for query in result['queries']}
    if any(reports['invariants'][0].values()) or any(any(row.values()) for query in diagnostics for row in reports[query['name']]):
        raise ValueError('Release key invariant failed; native results retained in scratch')
    coverage = {row['file']: {key: value for key, value in row.items() if key != 'file'} for row in reports['coverage']}
    files = [dict(entry, row_range=None, shard=None, producer='archive',
        coverage=dict(coverage.get(entry['name'], dict(congress_start=None, congress_end=None, date_start=None, date_end=None)), gaps=origin['gaps'])) for entry in result['outputs'] if entry['name'] not in {item['name'] for item in extra_outputs}]
    for entry in files:
        entry.pop('footer_bytes', None)
    files.append(_content(output / 'schema.json', _release_schema()))
    files.append(_content(output / 'capture_scope.json', dict(version=1, entries=[]) if capture_scope is None else capture_scope))
    for name,value in (content_files or {}).items():
        files.append(_content(output/name,value))
    release_id = release_identity(1,files)
    manifest = dict(schema_version=1, files=files, facet_counts=reports['facets'], release_id=release_id, origin=origin)
    _content(output / 'manifest.json', manifest)
    return manifest


def _auxiliary():
    sittings = _empty_struct(start=TS, end=TS, place='cast(NULL AS VARCHAR)')
    committees = _empty_struct(system_code='cast(NULL AS VARCHAR)', role='cast(NULL AS VARCHAR)')
    transcripts = _empty_struct(package_id='cast(NULL AS VARCHAR)', list_row='cast(NULL AS INT)')
    videos = _empty_struct(name='cast(NULL AS VARCHAR)', url='cast(NULL AS VARCHAR)', video_key='cast(NULL AS VARCHAR)')
    names = _empty_struct(name='cast(NULL AS VARCHAR)', start='cast(NULL AS DATE)', end='cast(NULL AS DATE)')
    return [
        ('meetings', f"""WITH keys AS (SELECT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered),
            meta AS (SELECT * FROM meeting_input UNION ALL SELECT event_id,cast(NULL AS VARCHAR) AS chamber,
                cast(NULL AS VARCHAR) AS title,cast(NULL AS DATE) AS meeting_date FROM keys WHERE event_id IS NOT NULL)
            SELECT event_id,max(chamber) AS chamber,max(title) AS title,max(meeting_date) AS meeting_date,
                cast(NULL AS VARCHAR) AS meeting_type,cast(NULL AS SMALLINT) AS session,cast(NULL AS VARCHAR) AS status,
                {sittings} AS sittings,{committees} AS committees,{EMPTY_STRINGS} AS subject_keys,
                {transcripts} AS transcripts,{videos} AS videos FROM meta GROUP BY event_id""", ['event_id'],
            ['chamber', 'meeting_type', 'status', 'committees.list.item.system_code', 'committees.list.item.role', 'subject_keys.list.item']),
        ('committees', f"""SELECT system_code,name,chamber,cast(NULL AS VARCHAR) AS committee_type,
            cast(NULL AS VARCHAR) AS parent_system_code,{names} AS names,cast(NULL AS VARCHAR) AS website,
            cast(NULL AS BOOLEAN) AS is_current FROM committee_input""", ['system_code'], ['chamber', 'committee_type', 'parent_system_code']),
        ('url_state', f"""SELECT cast(NULL AS VARCHAR) AS requested_url,cast(0 AS INT) AS attempts,
            {TS} AS last_attempt,cast(NULL AS SMALLINT) AS last_status,cast(NULL AS VARCHAR) AS last_outcome,
            {TS} AS last_good_at,{TS} AS next_attempt_at WHERE false""", ['requested_url'], ['last_outcome']),
    ]

