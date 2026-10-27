"""F0 migration: declarative native jobs produce every release relation."""
from hashlib import md5, sha256
import gzip
import json
from pathlib import Path


ROOT = Path(__file__).parents[4]
EMPTY_STRINGS = "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')"
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


def _step(name, sql, *, materialize=False, release_after=()):
    step = dict(name=name, sql=sql, materialize=materialize)
    if release_after:
        step['release_after'] = list(release_after)
    return step


def _field(name, kind):
    return dict(name=name, data_type=kind, nullable=True, dict_id=0, dict_is_ordered=False, metadata={})


def _list(kind):
    return {'List': _field('item', kind)}


def _struct(**fields):
    return {'Struct': [_field(name, kind) for name, kind in fields.items()]}


def _json_input(scratch, table_name, rows, **fields):
    path = scratch / f'{table_name}.jsonl.gz'
    with gzip.open(path, 'wt', encoding='utf-8', newline='\n') as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    return dict(name=table_name, kind='json_lines', files=[dict(key=table_name, path=str(path))],
        schema=dict(fields=[_field(key, kind) for key, kind in fields.items()], metadata={}))


def _body(byte):
    return f"repeat(lpad(to_hex(cast({byte} AS BIGINT)),2,'0'),32)"


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


def _core(steps, output):
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
            FROM ordered o LEFT JOIN source_ranges s ON o.doc_key=s.doc_key LEFT JOIN recovery_ranges r ON o.doc_key=r.doc_key"""),
        _step('body_links', "SELECT list_row,unnest(link_bodies) AS body_hex FROM ordered"),
        _step('all_links', f"""SELECT {_binary('substr(body_hex,1,16)', 8)} AS link_key,list_row,'body:' || body_hex AS origin FROM body_links
            UNION ALL SELECT {_hash_key('original_url', 'url:')},list_row,'url:' || original_url FROM recovery_rows"""),
        _step('links', 'SELECT link_key,min(list_row) AS list_row FROM all_links GROUP BY link_key'),
        _step('lookup_sources', 'SELECT DISTINCT list_row,url FROM source_rows UNION SELECT DISTINCT list_row,original_url AS url FROM recovery_rows'),
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


def _execute(inputs, steps, *, output, scratch, engine, origin):
    output.mkdir(parents=True, exist_ok=False)
    outputs = _core(steps, output)
    # Entity files and the capture fixture have their full declared schema,
    # including when this documents-only input provides no rows for them.
    for name, sql, keys, dictionary in _auxiliary():
        steps.append(_step(name + '_export', sql, materialize=True))
        outputs.append(dict(name=name + '.parquet', path=str(output / (name + '.parquet')), sql='SELECT * FROM ' + name + '_export',
            settings=_settings('whole', keys, dictionary=dictionary)))
    facets = [f"SELECT '{name}' AS facet,cast({name} AS VARCHAR) AS value,count(*) AS count FROM ordered WHERE NOT hidden GROUP BY {name}" for name in ['format', 'congress', 'saved_kind']]
    facets += [f"SELECT '{name}' AS facet,value,count(*) AS count FROM (SELECT unnest({name}) AS value FROM ordered WHERE NOT hidden) GROUP BY value" for name in ['document_kind', 'document_family', 'committee_keys', 'chambers', 'meeting_keys']]
    facets = ' UNION ALL '.join(facets)
    queries = [dict(name='facets', sql='SELECT * FROM (' + facets + ') WHERE value IS NOT NULL ORDER BY facet,value'),
        dict(name='invariants', sql="""SELECT (SELECT count(*) FROM (SELECT doc_key FROM ordered GROUP BY doc_key HAVING count(*)>1)) AS duplicate_documents,
            (SELECT count(*) FROM ordered WHERE body_expected AND (body_hex IS NULL OR length(body_hex)<>64)) AS missing_saved_bodies,
            (SELECT count(*) FROM ordered WHERE body_hex IS NOT NULL AND (bytes IS NULL OR bytes<0)) AS missing_saved_sizes,
            (SELECT count(*) FROM (SELECT link_key FROM all_links GROUP BY link_key HAVING count(DISTINCT origin)>1)) AS link_collisions,
            (SELECT count(*) FROM (SELECT lookup_key FROM lookup_keys_full GROUP BY lookup_key HAVING count(DISTINCT lookup_url)>1)) AS lookup_collisions""")]
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
    if any(reports['invariants'][0].values()):
        raise ValueError('Release key invariant failed; native results retained in scratch')
    coverage = {row['file']: {key: value for key, value in row.items() if key != 'file'} for row in reports['coverage']}
    files = [dict(entry, row_range=None, shard=None, producer='archive',
        coverage=dict(coverage.get(entry['name'], dict(congress_start=None, congress_end=None, date_start=None, date_end=None)), gaps=origin['gaps'])) for entry in result['outputs']]
    for entry in files:
        entry.pop('footer_bytes', None)
    files.append(_content(output / 'schema.json', _release_schema()))
    files.append(_content(output / 'capture_scope.json', dict(version=1, entries=[])))
    identity = [1, [[item['name'], item['sha256'], item['size'], item['rows']] for item in files]]
    release_id = sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
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


def _release_schema():
    # The interface registry is shared with the reader; policy metadata stays
    # content-only while all row transformations and Parquet writing stay native.
    return json.loads((ROOT / 'model/registries/release-schema.json').read_text())


def build_fixture_release(fixture, *, output, scratch, engine):
    """Build the hand-authored F0 acceptance release with the real native writer."""
    fixture, output, scratch = Path(fixture), Path(output), Path(scratch)
    scratch.mkdir(parents=True, exist_ok=False)
    data = json.loads(fixture.read_text())
    # These are authored input records, not a migration of retained source data.
    # The only added value is the application's stable endpoint ID formula.
    documents = [dict(row, version_key=sha256(json.dumps([row['source_url'].removeprefix('https://'), None],
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:16]) for row in data['documents']]
    inputs = [_json_input(scratch, 'hand', documents, name='Utf8', filename='Utf8', title='Utf8', body_byte='Int64',
        format='Utf8', document_date='Utf8', first_captured='Utf8', hidden='Boolean', review_note='Utf8',
        review_decided_at='Utf8', source_url='Utf8', meeting_keys=_list('Utf8'), version_names=_list('Utf8'),
        version_key='Utf8', extra_link_body_bytes=_list('Int64'),
        alternates=_list(_struct(format='Utf8', body_byte='Int64', suffix='Utf8', size='Int64')),
        recovery=_struct(kind='Utf8', recovered_url='Utf8', identity_note='Utf8', imported_at='Utf8')),
        _json_input(scratch, 'hand_meetings', data['meetings'], event_id='Int64', chamber='Utf8', title='Utf8', meeting_date='Utf8')]
    steps = [_step('hand_bodies', f"SELECT *,{_body('body_byte')} AS body_hex FROM hand"),
        _step('hand_alternates', 'SELECT name,unnest(alternates) AS alt FROM hand'),
        _step('alternate_groups', f"""SELECT name,array_agg(named_struct('format',alt['format'],
            'body',{_binary(_body("alt['body_byte']"), 32)},'suffix',alt['suffix'],'size',alt['size']) ORDER BY alt['format']) AS alternatives,
            array_agg({_body("alt['body_byte']")} ORDER BY alt['format']) AS bodies FROM hand_alternates GROUP BY name"""),
        _step('hand_extra_bodies', 'SELECT name,unnest(extra_link_body_bytes) AS extra FROM hand'),
        _step('extra_groups', f'SELECT name,array_agg({_body("extra")} ORDER BY extra) AS bodies FROM hand_extra_bodies GROUP BY name'),
        _step('normalized', _normal('hand_bodies h LEFT JOIN alternate_groups a ON h.name=a.name LEFT JOIN extra_groups e ON h.name=e.name',
            doc_key='h.name', filename='h.filename', title='h.title', format='h.format', body_hex='h.body_hex', source_url='h.source_url',
            document_date='try_cast(h.document_date AS DATE)', first_captured='try_cast(h.first_captured AS DATE)',
            date_kind="CASE WHEN h.first_captured IS NOT NULL THEN 'captured' WHEN h.recovery IS NOT NULL THEN 'import_day' ELSE 'unknown' END",
            saved_kind="CASE WHEN h.recovery IS NOT NULL THEN 'recovery' ELSE 'original' END", hidden='h.hidden',
            meeting_keys=f'coalesce(h.meeting_keys,{EMPTY_STRINGS})',
            version_keys=f"CASE WHEN cardinality(h.version_names)>0 THEN make_array(h.version_key) ELSE {EMPTY_STRINGS} END",
            bytes='cast(100 AS BIGINT)', media_type="'application/pdf'", document_date_source="CASE WHEN h.document_date IS NOT NULL THEN 'content' ELSE NULL END",
            in_archive_since="try_cast(h.recovery['imported_at'] AS DATE)", review_note='h.review_note', review_decided_at='try_cast(h.review_decided_at AS DATE)',
            alternates=f'coalesce(a.alternatives,{EMPTY_ALTERNATES})',
            link_bodies=f"CASE WHEN h.recovery IS NOT NULL THEN {EMPTY_STRINGS} ELSE array_concat(make_array(h.body_hex),coalesce(a.bodies,{EMPTY_STRINGS}),coalesce(e.bodies,{EMPTY_STRINGS})) END"), materialize=True),
        _step('source_input', """SELECT name AS doc_key,name AS source_key,source_url AS url,cast(NULL AS VARCHAR) AS member_path,
            recovery IS NULL AS is_saved,try_cast(first_captured AS DATE) AS first_seen,cast(NULL AS VARCHAR) AS listed_on,
            title AS link_text,cast(NULL AS VARCHAR) AS doc_type,cast(NULL AS DATE) AS posted FROM hand"""),
        _step('recovery_input', f"""SELECT name AS doc_key,name AS recovery_key,source_url AS original_url,recovery['kind'] AS kind,
            {_binary(_body('body_byte'), 32)} AS body,'.gz' AS suffix,cast(100 AS BIGINT) AS bytes,
            try_cast(recovery['imported_at'] AS DATE) AS imported_at,recovery['recovered_url'] AS recovered_url,
            recovery['identity_note'] AS identity_note FROM hand WHERE recovery IS NOT NULL"""),
        _step('meeting_input', 'SELECT event_id,chamber,title,try_cast(meeting_date AS DATE) AS meeting_date FROM hand_meetings'),
        _step('committee_input', 'SELECT cast(NULL AS VARCHAR) AS system_code,cast(NULL AS VARCHAR) AS name,cast(NULL AS VARCHAR) AS chamber WHERE false'),
    ]
    return _execute(inputs, steps, output=output, scratch=scratch, engine=engine,
        origin=dict(kind='hand_fixture', source_sha256=sha256(fixture.read_bytes()).hexdigest(),
                    gaps=['Synthetic reader fixture; capture scheduling is disabled']))


def _match(expression, pattern):
    return f"array_element(regexp_match({expression},'{pattern}'),1)"


def _meeting_keys(url):
    key = 'coalesce(' + ','.join(_match(url, pattern) for pattern in [
        '/meetings/[^/]+/[^/]+/[0-9]{8}/([0-9]+)/', '(?i)[?&]eventid=([0-9]+)',
        '/(?:house|senate|joint)-event/([0-9]+)']) + ')'
    numeric = f'try_cast({key} AS BIGINT)'
    return f'CASE WHEN {numeric} IS NULL THEN {EMPTY_STRINGS} ELSE make_array(cast({numeric} AS VARCHAR)) END'


def committee_input(path):
    """Read the retained committee inventory through the native JSON reader."""
    path = Path(path)
    if path.suffix == '.parquet':
        return dict(name='committee_source', kind='parquet', path=str(path.resolve())), []
    schema = dict(fields=[_field('congress', 'Int64'), _field('committee', _struct(
        systemCode='Utf8', name='Utf8', chamber='Utf8', subcommittees=_list(_struct(systemCode='Utf8', name='Utf8'))))], metadata={})
    source = dict(name='committee_inventory', kind='json_lines',
        files=[dict(key='committee_inventory', path=str(path.resolve()))], schema=schema)
    steps = [_step('committee_candidates', """SELECT congress,committee['systemCode'] AS system_code,
        committee['name'] AS name,lower(committee['chamber']) AS chamber FROM committee_inventory
        UNION ALL SELECT congress,sub['systemCode'],sub['name'],lower(chamber) FROM
        (SELECT congress,committee['chamber'] AS chamber,unnest(committee['subcommittees']) AS sub FROM committee_inventory)"""),
        _step('committee_source', """SELECT system_code,name,chamber FROM (SELECT *,row_number() OVER
        (PARTITION BY system_code ORDER BY congress DESC NULLS LAST,name,chamber) AS rank FROM committee_candidates)
        WHERE rank=1 AND system_code IS NOT NULL""", materialize=True)]
    return source, steps


def convert_catalog(documents, filenames, captures, committees, *, catalog_id, output, scratch, engine):
    """Convert the pinned catalog pair, using engine joins, grouping and exports."""
    output, scratch = Path(output), Path(scratch)
    scratch.mkdir(parents=True, exist_ok=False)
    inputs = [dict(name=name, kind='parquet', path=str(Path(path).resolve())) for name, path in [
        ('legacy_documents', documents), ('legacy_filenames', filenames), ('legacy_captures', captures)]]
    committee, committee_steps = committee_input(committees)
    inputs.append(committee)
    raw_date = 'array_element(d.date_token,1)'
    date = f"CASE WHEN cardinality(d.date_token)=1 THEN try_cast(CASE WHEN regexp_like({raw_date},'^[0-9]{{8}}$') THEN concat(substr({raw_date},1,4),'-',substr({raw_date},5,2),'-',substr({raw_date},7,2)) ELSE {raw_date} END AS DATE) ELSE NULL END"
    body_hex = _match('d.body_key', '([0-9a-f]{64})')
    steps = committee_steps + [_step('body_metadata', """SELECT body_key,max(bytes) AS bytes,max(media_type) AS media_type
        FROM legacy_captures WHERE body_key IS NOT NULL GROUP BY body_key""", materialize=True, release_after=['legacy_captures']),
        _step('document_bodies', 'SELECT document_id,unnest(body_keys) AS body_key FROM legacy_documents'),
        _step('body_groups', f"SELECT document_id,array_agg({_match('body_key', '([0-9a-f]{64})')} ORDER BY body_key) AS bodies FROM document_bodies GROUP BY document_id", materialize=True),
        _step('document_codes', 'SELECT document_id,unnest(committee_code) AS code FROM legacy_documents'),
        _step('committee_aliases', """SELECT system_code,chamber,upper(system_code) AS code FROM committee_source
            UNION SELECT system_code,chamber,upper(substr(system_code,3)) AS code FROM committee_source
            UNION SELECT system_code,chamber,upper(substr(system_code,3,2)) AS code FROM committee_source
            WHERE lower(chamber)='house' AND right(system_code,2)='00'"""),
        _step('committee_groups', """SELECT d.document_id,array_agg(DISTINCT c.system_code ORDER BY c.system_code) AS committee_keys,
            array_agg(DISTINCT lower(c.chamber) ORDER BY lower(c.chamber)) AS chambers FROM document_codes d JOIN committee_aliases c
            ON upper(d.code)=c.code GROUP BY d.document_id""", materialize=True),
        _step('normalized', _normal('legacy_documents d LEFT JOIN body_metadata b ON d.body_key=b.body_key LEFT JOIN committee_groups c ON d.document_id=c.document_id LEFT JOIN body_groups g ON d.document_id=g.document_id',
            body_expected='d.body_key IS NOT NULL', doc_key='d.document_id', filename='d.filename', title='array_element(d.source_link_label,1)',
            source_url='d.source_url', body_hex=body_hex, format="lower(coalesce(array_element(d.format,1),'other'))",
            document_kind='d.document_kind', document_family='d.document_family', committee_keys='c.committee_keys', chambers='c.chambers',
            congress='CASE WHEN cardinality(d.congress)=1 THEN try_cast(array_element(d.congress,1) AS SMALLINT) ELSE NULL END',
            document_date=date, document_date_source=f"CASE WHEN {date} IS NULL THEN NULL ELSE 'filename' END",
            suffix="CASE WHEN regexp_like(d.body_key,'[.]pdf$') THEN '.pdf' WHEN regexp_like(d.body_key,'[.]gz$') THEN '.gz' ELSE '' END",
            media_type="coalesce(b.media_type,CASE WHEN array_element(d.format,1)='pdf' THEN 'application/pdf' ELSE 'application/octet-stream' END)",
            bytes='b.bytes', meeting_keys=_meeting_keys('d.source_url'), link_bodies='g.bodies'), materialize=True, release_after=['body_metadata', 'body_groups', 'document_bodies', 'committee_groups', 'document_codes', 'committee_aliases']),
        _step('source_candidates', """SELECT f.document_id AS doc_key,f.source_id AS source_key,f.source_url AS url,
            cast(NULL AS VARCHAR) AS member_path,coalesce(f.body_key=d.body_key,false) AS is_saved,
            cast(NULL AS DATE) AS first_seen,
            array_element(f.source_page_url,1) AS listed_on,array_element(f.source_link_label,1) AS link_text,
            cast(NULL AS VARCHAR) AS doc_type,cast(NULL AS DATE) AS posted
            FROM legacy_filenames f JOIN (SELECT document_id,body_key FROM legacy_documents) d ON f.document_id=d.document_id
            WHERE f.source_url IS NOT NULL"""),
        _step('source_input', """SELECT doc_key,min(source_key) AS source_key,url,member_path,
            bool_or(is_saved) AS is_saved,min(first_seen) AS first_seen,min(listed_on) AS listed_on,
            min(link_text) AS link_text,min(doc_type) AS doc_type,min(posted) AS posted
            FROM source_candidates GROUP BY doc_key,url,member_path""", materialize=True, release_after=['source_candidates', 'legacy_documents', 'legacy_filenames']),
        _step('recovery_input', """SELECT cast(NULL AS VARCHAR) AS doc_key,cast(NULL AS VARCHAR) AS recovery_key,
            cast(NULL AS VARCHAR) AS original_url,cast(NULL AS VARCHAR) AS kind,arrow_cast(NULL,'FixedSizeBinary(32)') AS body,
            cast(NULL AS VARCHAR) AS suffix,cast(NULL AS BIGINT) AS bytes,cast(NULL AS DATE) AS imported_at,
            cast(NULL AS VARCHAR) AS recovered_url,cast(NULL AS VARCHAR) AS identity_note WHERE false"""),
        _step('meeting_input', 'SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS chamber,cast(NULL AS VARCHAR) AS title,cast(NULL AS DATE) AS meeting_date WHERE false'),
        _step('committee_input', 'SELECT system_code,name,lower(chamber) AS chamber FROM committee_source'),
    ]
    return _execute(inputs, steps, output=output, scratch=scratch, engine=engine,
        origin=dict(kind='converted_catalog', catalog_id=catalog_id, gaps=[
            'Converted catalog fixture; old grouping and classifications are retained',
            'Fetch and import dates are not reconstructed from legacy timestamps',
            'Format alternates, meeting titles, recovery kinds and member paths are unavailable',
            'Metadata-only legacy rows have no saved body, bytes or body link',
            'Capture scheduling is disabled']))


def main():
    import argparse
    from docspec_client.client import NativeDatasets

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--scratch', required=True, type=Path)
    modes = parser.add_subparsers(dest='mode', required=True)
    hand = modes.add_parser('fixture')
    hand.add_argument('--input', type=Path, default=ROOT / 'model/fixtures/hand-release.json')
    catalog = modes.add_parser('catalog')
    for name in ['documents', 'filenames', 'captures', 'committees']:
        catalog.add_argument('--' + name, type=Path, required=True)
    catalog.add_argument('--catalog-id', required=True)
    args = parser.parse_args()
    common = dict(output=args.output, scratch=args.scratch, engine=NativeDatasets.from_config(args.runtime))
    if args.mode == 'fixture':
        result = build_fixture_release(args.input, **common)
    else:
        result = convert_catalog(args.documents, args.filenames, args.captures, args.committees,
                                 catalog_id=args.catalog_id, **common)
    print(json.dumps(dict(release_id=result['release_id'], files=result['files'])))


if __name__ == '__main__':
    main()
