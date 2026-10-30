"""Shared native release layout; application models supply complete document rows."""
from hashlib import md5, sha256

from viewer_publication.archive_model_lifetimes import retire_relations
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


def _settings(profile, order, *, columns=None, dictionary=(), delta=(), footer_limit=512 << 10):
    return dict(profile=profile, row_group_rows=65536, order_by=[dict(field=name) for name in order],
        columns=columns or [], dictionary_columns=list(dictionary), delta_columns=list(delta),
        key_column=order[0] if profile == 'lookup' else None, created_by='docspec archive release v1', footer_limit=footer_limit)


def _core(steps, output,*,lookup_extra=None):
    order = ['filename', 'document_date', 'first_captured', 'doc_key']
    detail_inputs = ','.join('o.'+name for name in dict.fromkeys([*order,*LIST_COLUMNS,'list_row',
        'document_date_source','in_archive_since','removed_on','review_note','review_decided_at',
        'alternates','package_id','facts']))
    steps += [_step('ordered', "SELECT *,cast(row_number() OVER(ORDER BY filename,document_date NULLS LAST,first_captured NULLS LAST,doc_key)-1 AS INT) AS list_row FROM normalized", materialize=True),
        _step('source_rows', """SELECT o.list_row,s.*,cast(row_number() OVER(PARTITION BY o.list_row ORDER BY s.is_saved DESC,s.first_seen NULLS LAST,s.url,s.member_path NULLS LAST)-1 AS INT) AS ordinal,
            cast(row_number() OVER(ORDER BY o.list_row,s.is_saved DESC,s.first_seen NULLS LAST,s.url,s.member_path NULLS LAST)-1 AS INT) AS source_index
            FROM (SELECT doc_key,list_row FROM ordered) o JOIN source_input s ON s.doc_key=o.doc_key""", materialize=True),
        _step('source_ranges', 'SELECT doc_key,min(source_index) AS src_start,cast(count(*) AS INT) AS src_len FROM source_rows GROUP BY doc_key'),
        _step('recovery_rows', """SELECT o.list_row,r.*,cast(row_number() OVER(PARTITION BY o.list_row ORDER BY r.recovery_key)-1 AS INT) AS ordinal,
            cast(row_number() OVER(ORDER BY o.list_row,r.recovery_key)-1 AS INT) AS recovery_index
            FROM (SELECT doc_key,list_row FROM ordered) o JOIN recovery_input r ON r.doc_key=o.doc_key""", materialize=True),
        _step('recovery_ranges', 'SELECT doc_key,min(recovery_index) AS rec_start,cast(count(*) AS INT) AS rec_len FROM recovery_rows GROUP BY doc_key'),
        _step('details', f"""SELECT {detail_inputs},CASE WHEN saved_kind='recovery' THEN {_hash_key('o.source_url', 'url:')}
            ELSE {_binary('substr(body_hex,1,16)', 8)} END AS link_key,
            {_binary('body_hex', 32)} AS saved_body,CASE WHEN body_hex IS NOT NULL THEN suffix END AS saved_suffix,CASE WHEN body_hex IS NOT NULL THEN media_type END AS saved_media_type,bytes AS saved_bytes,
            coalesce(s.src_start,cast(0 AS INT)) AS src_start,coalesce(s.src_len,cast(0 AS INT)) AS src_len,
            coalesce(r.rec_start,cast(0 AS INT)) AS rec_start,coalesce(r.rec_len,cast(0 AS INT)) AS rec_len
            FROM recovery_ranges r RIGHT JOIN (source_ranges s RIGHT JOIN ordered o ON o.doc_key=s.doc_key) ON o.doc_key=r.doc_key""", materialize=True),
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


def _release_schema(available=None):
    from viewer_publication.archive_schema import build_schema
    return build_schema(available)


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



SPICY_PRODUCER_FAMILIES = {
    'committees.parquet': ('committee-rosters',),
    'members.parquet': ('members',),
    'rosters.parquet': ('committee-rosters',),
    'bills.parquet': ('bill-family', 'roll-call-votes'),
    'nominations.parquet': ('nominations', 'roll-call-votes'),
}


def _execute(inputs, steps, *, output, scratch, engine, origin, auxiliary=None, capture_scope=None, extra_outputs=(), diagnostics=(), metadata_queries=(), content_files=None, lookup_extra=None, entity_digests=None):
    output.mkdir(parents=True, exist_ok=False)
    outputs = _core(steps, output,lookup_extra=lookup_extra)
    # Entity files and the capture fixture have their full declared schema,
    # including when this documents-only input provides no rows for them.
    # A step dict among them is a named step that a later export reads.
    aux_items = list(_auxiliary() if auxiliary is None else auxiliary)
    aux_names = {item[0] for item in aux_items if not isinstance(item, dict)}
    for item in aux_items:
        if isinstance(item, dict):
            steps.append(item)
            continue
        name, sql, keys, dictionary = item
        steps.append(_step(name + '_export', sql, materialize=True))
        outputs.append(dict(name=name + '.parquet', path=str(output / (name + '.parquet')), sql='SELECT * FROM ' + name + '_export',
            settings=_settings('whole', keys, dictionary=dictionary)))
    schema = _release_schema([item['name'] for item in outputs])
    from viewer_publication.archive_schema import publication_checks
    diagnostics = [*diagnostics, *publication_checks(schema, aux_names)]
    outputs.extend(extra_outputs)
    facets = [f"SELECT '{name}' AS facet,cast({name} AS VARCHAR) AS value,count(*) AS count FROM ordered WHERE NOT hidden GROUP BY {name}" for name in ['format', 'congress', 'saved_kind']]
    facets += [f"SELECT '{name}' AS facet,value,count(*) AS count FROM (SELECT unnest({name}) AS value FROM ordered WHERE NOT hidden) GROUP BY value" for name in ['document_kind', 'document_family', 'committee_keys', 'chambers', 'meeting_keys']]
    facets = ' UNION ALL '.join(facets)
    queries = [dict(name='facets', sql='SELECT * FROM (' + facets + ') WHERE value IS NOT NULL ORDER BY facet,value'),
        dict(name='invariants', sql="""SELECT (SELECT count(*) FROM (SELECT doc_key FROM ordered GROUP BY doc_key HAVING count(*)>1)) AS duplicate_documents,
            (SELECT count(*) FROM ordered WHERE body_expected AND (body_hex IS NULL OR length(body_hex)<>64)) AS missing_saved_bodies,
            (SELECT count(*) FROM ordered WHERE body_hex IS NOT NULL AND (bytes IS NULL OR bytes<0)) AS missing_saved_sizes,
            (SELECT count(*) FROM (SELECT link_key FROM all_links GROUP BY link_key HAVING min(origin)<>max(origin))) AS link_collisions,
            (SELECT count(*) FROM (SELECT lookup_key FROM lookup_keys_full GROUP BY lookup_key HAVING min(lookup_url)<>max(lookup_url))) AS lookup_collisions""")]
    queries.extend(diagnostics)
    queries.extend(metadata_queries)
    step_names = {s['name'] for s in steps}
    coverage_parts = []
    for name, relation in [('list', None), ('detail', None), ('links', 'links'), ('urls', 'url_keys'), ('sources', 'source_rows'), ('recoveries', 'recovery_rows')]:
        source = 'ordered o' if relation is None else f'ordered o JOIN (SELECT DISTINCT list_row FROM {relation}) r ON o.list_row=r.list_row'
        coverage_parts.append(f"SELECT '{name}.parquet' AS file,min(o.congress) AS congress_start,max(o.congress) AS congress_end,min(o.document_date) AS date_start,max(o.document_date) AS date_end FROM {source}")
    if 'meetings_resolved' in step_names:
        coverage_parts.append("""SELECT 'meetings.parquet' AS file,
            min(coalesce(cast(r.congress AS SMALLINT),o.congress_min)) AS congress_start,
            max(coalesce(cast(r.congress AS SMALLINT),o.congress_max)) AS congress_end,
            min(m.meeting_date) AS date_start,
            max(m.meeting_date) AS date_end
            FROM meetings_export m
            LEFT JOIN meetings_resolved r ON m.event_id=r.event_id
            LEFT JOIN (
                SELECT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id,min(congress) AS congress_min,max(congress) AS congress_max
                FROM ordered WHERE meeting_keys IS NOT NULL GROUP BY 1
            ) o ON m.event_id=o.event_id""")
    else:
        coverage_parts.append("SELECT 'meetings.parquet' AS file,cast(NULL AS SMALLINT) AS congress_start,cast(NULL AS SMALLINT) AS congress_end,min(meeting_date) AS date_start,max(meeting_date) AS date_end FROM meetings_export")
    if 'witnesses' in aux_names and 'meetings_resolved' in step_names:
        coverage_parts.append("""SELECT 'witnesses.parquet' AS file,
            min(coalesce(cast(m.congress AS SMALLINT),o.congress)) AS congress_start,
            max(coalesce(cast(m.congress AS SMALLINT),o.congress)) AS congress_end,
            min(coalesce(m.meeting_date,o.document_date)) AS date_start,
            max(coalesce(m.meeting_date,o.document_date)) AS date_end
            FROM witnesses_export w
            LEFT JOIN meetings_resolved m ON w.event_id=m.event_id
            LEFT JOIN (
                SELECT unnest(witness_keys) AS witness_key,min(congress) AS congress,min(document_date) AS document_date
                FROM ordered WHERE witness_keys IS NOT NULL GROUP BY 1
            ) o ON w.witness_key=o.witness_key""")
    if 'committees' in aux_names:
        coverage_parts.append("SELECT 'committees.parquet' AS file,cast(NULL AS SMALLINT) AS congress_start,cast(NULL AS SMALLINT) AS congress_end,min(n['start']) AS date_start,max(n['end']) AS date_end FROM (SELECT unnest(names) AS n FROM committees_export WHERE names IS NOT NULL)")
    if 'members' in aux_names:
        coverage_parts.append("SELECT 'members.parquet' AS file,cast(NULL AS SMALLINT) AS congress_start,cast(NULL AS SMALLINT) AS congress_end,min(t['start']) AS date_start,max(t['end']) AS date_end FROM (SELECT unnest(terms) AS t FROM members_export WHERE terms IS NOT NULL)")
    if 'rosters' in aux_names:
        coverage_parts.append("SELECT 'rosters.parquet' AS file,min(congress) AS congress_start,max(congress) AS congress_end,cast(NULL AS DATE) AS date_start,cast(NULL AS DATE) AS date_end FROM rosters_export")
    if 'bills' in aux_names:
        coverage_parts.append("SELECT 'bills.parquet' AS file,min(try_cast(split_part(bill_id,'-',1) AS SMALLINT)) AS congress_start,max(try_cast(split_part(bill_id,'-',1) AS SMALLINT)) AS congress_end,min(introduced) AS date_start,max(introduced) AS date_end FROM bills_export")
    if 'nominations' in aux_names:
        coverage_parts.append("SELECT 'nominations.parquet' AS file,min(try_cast(split_part(nomination_id,'-',1) AS SMALLINT)) AS congress_start,max(try_cast(split_part(nomination_id,'-',1) AS SMALLINT)) AS congress_end,min(received) AS date_start,max(received) AS date_end FROM nominations_export")
    if 'search' in aux_names:
        congresses = 'FROM (SELECT try_cast(unnest(congress) AS SMALLINT) AS c FROM search_export)'
        coverage_parts.append(f"SELECT 'search.parquet' AS file,(SELECT min(c) {congresses}) AS congress_start,(SELECT max(c) {congresses}) AS congress_end,min(date) AS date_start,max(date) AS date_end FROM search_export")
    queries.append(dict(name='coverage', sql=' UNION ALL '.join(coverage_parts)))
    spec = retire_relations(dict(scratch=str(scratch / 'native'), inputs=inputs, steps=steps, outputs=outputs, queries=queries))
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
    schema_files = {item['name']: item for item in schema['files']}
    coverage = {row['file']: {key: value for key, value in row.items() if key != 'file'} for row in reports['coverage']}
    files = []
    for entry in result['outputs']:
        if entry['name'] in {item['name'] for item in extra_outputs}:
            continue
        meta = schema_files.get(entry['name'], {})
        file_gaps = list(meta.get('gaps') or origin['gaps'])
        producer = 'spicy-regs' if (entity_digests is not None and entry['name'] in SPICY_PRODUCER_FAMILIES) else 'archive'
        extra_meta = {}
        if producer == 'spicy-regs':
            extra_meta['generations'] = {
                family: entity_digests[family]
                for family in SPICY_PRODUCER_FAMILIES[entry['name']]
                if family in entity_digests
            }
        files.append(dict(entry, row_range=None, shard=None, producer=producer, **extra_meta,
            coverage=dict(coverage.get(entry['name'], dict(congress_start=None, congress_end=None, date_start=None, date_end=None)), gaps=file_gaps)))
    for entry in files:
        entry.pop('footer_bytes', None)
    from viewer_publication.archive_schema import validate_parquet_fields
    validate_parquet_fields(schema, [output / f['name'] for f in files])
    files.append(_content(output / 'schema.json', schema))
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

