"""Shared native release layout; application models supply complete document rows."""
from hashlib import md5, sha256
from io import BytesIO
from congress_shared.custody import write_atomic_bytes

from viewer_publication.archive_model_lifetimes import retire_relations
from viewer_publication.archive_catalog import CORE_RELATIONS, release_output_sql
import json
from pathlib import Path
import re


ROOT = Path(__file__).parents[4]
CATALOG_ARTIFACT = re.compile(r'catalog\.(?:ddk|report|lock)\.json|discovery\.dcat\.json'
                              r'|queries/[a-f0-9]{64}\.sql|lineage/[0-9]{4}\.openlineage\.json')


class NativeReleaseNotReady(RuntimeError):
    """A native observation that cannot yet produce a selected release."""

    def __init__(self, phase, response):
        self.response = response
        super().__init__(f'Native release {phase} is not complete: '
                         f'{response.get("error") or response.get("result", {}).get("status")}')


def archive_asset_name(name):
    """Keep flat archive names and the standard catalog companion paths safe."""
    return (isinstance(name, str) and bool(name) and '\\' not in name
            and name not in {'.', '..', 'manifest.json'}
            and not any(character in name for character in '%?#')
            and not any(ord(character) < 32 for character in name)
            and ('/' not in name or CATALOG_ARTIFACT.fullmatch(name) is not None))


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


NULL_MEETING_DOCUMENT_REFERENCES = 'CASE WHEN false THEN ' + _empty_struct(
    collection='cast(NULL AS VARCHAR)', ordinal='cast(NULL AS INT)', url='cast(NULL AS VARCHAR)',
    role='cast(NULL AS VARCHAR)', format='cast(NULL AS VARCHAR)', description='cast(NULL AS VARCHAR)',
    name='cast(NULL AS VARCHAR)') + ' END'


EMPTY_ALTERNATES = _empty_struct(format='cast(NULL AS VARCHAR)', body="arrow_cast(NULL,'FixedSizeBinary(32)')",
                                suffix='cast(NULL AS VARCHAR)', size='cast(NULL AS BIGINT)')


EMPTY_FACTS = _empty_struct(field='cast(NULL AS VARCHAR)', value='cast(NULL AS VARCHAR)')


EMPTY_PAGE_METADATA = _empty_struct(field='cast(NULL AS VARCHAR)', value='cast(NULL AS VARCHAR)', format='cast(NULL AS VARCHAR)',
    path='cast(NULL AS VARCHAR)', date='cast(NULL AS DATE)', precision='cast(NULL AS VARCHAR)', resolved='cast(NULL AS VARCHAR)',
    selected='cast(NULL AS BOOLEAN)', context_url='cast(NULL AS VARCHAR)')


# A document with no html reading has no main content: a NULL struct of the declared shape.
NO_MAIN_CONTENT = ("CASE WHEN false THEN named_struct('outcome',cast(NULL AS VARCHAR),'selector',cast(NULL AS VARCHAR),"
    "'text_sha256',cast(NULL AS VARCHAR),'text_bytes',cast(NULL AS INT),'snippet',cast(NULL AS VARCHAR),"
    "'reader_version',cast(NULL AS VARCHAR),'reading_status',cast(NULL AS VARCHAR),'reason',cast(NULL AS VARCHAR),"
    "'facts_limited',cast(NULL AS BOOLEAN),'text_available',cast(NULL AS BOOLEAN),'decision_id',cast(NULL AS VARCHAR),"
    "'evidence_limited',cast(NULL AS BOOLEAN)) END")


PAGE_DEFAULTS = dict(description='cast(NULL AS VARCHAR)', published_on='cast(NULL AS DATE)', modified_on='cast(NULL AS DATE)',
    publisher_labels="arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')",
    page_metadata=EMPTY_PAGE_METADATA, main_content=NO_MAIN_CONTENT, selected_text='cast(NULL AS VARCHAR)')


LIST_COLUMNS = ['filename', 'title', 'document_kind', 'document_family', 'committee_keys', 'chambers',
    'congress', 'format', 'document_date', 'first_captured', 'date_kind', 'saved_kind', 'hidden',
    'meeting_keys', 'measure_keys', 'bioguide_ids', 'witness_keys', 'version_keys']


# Declared page metadata (ct-93zs D5): detail only, selected by model SQL and page-signals.json.
PAGE_COLUMNS = ['description', 'published_on', 'modified_on', 'publisher_labels', 'page_metadata', 'main_content', 'selected_text']


DETAIL_COLUMNS = ['link_key', 'saved_body', 'saved_suffix', 'saved_media_type', 'saved_bytes',
    'document_date_source', 'document_date_status', 'in_archive_since', 'removed_on', 'review_note', 'review_decided_at',
    'src_start', 'src_len', 'rec_start', 'rec_len', 'alternates', 'package_id', 'facts', *PAGE_COLUMNS]


# A filename date is suspect when it is more than 30 days after the archive's first capture
# (committees post hearing documents ahead of the hearing date), or its year falls outside the
# tagged Congress's two years with one year of margin (Congress n begins in 1789+2(n-1)).
# Content and meeting dates are always accepted. The literal date stays in document_date.
DOCUMENT_DATE_STATUS = """CASE WHEN document_date IS NULL THEN NULL
    WHEN document_date_source='filename' AND (document_date>first_captured+INTERVAL '30 days' OR (congress IS NOT NULL AND (
        date_part('year',document_date)<1789+2*(cast(congress AS INT)-1)-1
        OR date_part('year',document_date)>1789+2*(cast(congress AS INT)-1)+3)))
    THEN 'suspect' ELSE 'accepted' END"""


# The keyed document table: detail-only columns, then the list projection. A new
# document field needs one entry in a constant above; detail carries it from there.
DOCUMENT_COLUMNS = [*DETAIL_COLUMNS, *LIST_COLUMNS]


LIST_DICTIONARY = [*(f'{name}.list.item' for name in ['document_kind', 'document_family', 'committee_keys', 'chambers', 'meeting_keys', 'measure_keys', 'bioguide_ids', 'witness_keys', 'version_keys']), 'format', 'date_kind', 'saved_kind']


DETAIL_DICTIONARY = ['saved_suffix', 'saved_media_type', 'document_date_source', 'document_date_status', 'alternates.list.item.format', 'alternates.list.item.suffix', 'facts.list.item.field',
    'publisher_labels.list.item', 'page_metadata.list.item.field', 'page_metadata.list.item.format', 'page_metadata.list.item.precision', 'main_content.outcome']


MEETING_DICTIONARY = ['chamber', 'meeting_type', 'status', 'congress_gov_meeting_type', 'access', 'access_basis', 'rescheduled_basis', 'committees.list.item.system_code', 'committees.list.item.role', 'subject_keys.list.item', 'transcripts.list.item.source', 'transcripts.list.item.language', 'transcripts.list.item.production']


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
        'document_date_source','document_date_status','in_archive_since','removed_on','review_note','review_decided_at',
        'alternates','package_id','facts',*PAGE_COLUMNS]))
    steps += [_step('ordered', f"SELECT *,{DOCUMENT_DATE_STATUS} AS document_date_status,cast(row_number() OVER(ORDER BY filename,document_date NULLS LAST,first_captured NULLS LAST,doc_key)-1 AS INT) AS list_row FROM normalized", materialize=True),
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
        ('list', _settings('whole', order, columns=LIST_COLUMNS,
            dictionary=LIST_DICTIONARY, delta=['filename', 'title'])),
        ('detail', _settings('ranged', order, columns=DOCUMENT_COLUMNS, dictionary=[*DETAIL_DICTIONARY, *LIST_DICTIONARY], delta=['filename', 'title'])),
        ('links', _settings('lookup', ['link_key'])),
        ('urls', _settings('lookup', ['lookup_key', 'list_row'])),
        ('sources', _settings('ranged', ['list_row', 'ordinal'], columns=['list_row', 'ordinal', 'url', 'member_path', 'is_saved', 'first_seen', 'listed_on', 'link_text', 'doc_type', 'posted'])),
        ('recoveries', _settings('ranged', ['list_row', 'ordinal'], columns=['list_row', 'ordinal', 'kind', 'body', 'suffix', 'bytes', 'imported_at', 'recovered_url', 'identity_note'], dictionary=['kind', 'suffix'])),
    ]
    outputs = [dict(name=name + '.parquet', path=str(output / (name + '.parquet')), sql=release_output_sql(name), settings=settings) for name, settings in specs]
    return outputs


def _content(path, value):
    data = _content_data(value)
    write_atomic_bytes(path,data,fsync_dir=True)
    return _content_record(path.name, data)


def _content_data(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _content_record(name, data):
    return dict(name=name, sha256=sha256(data).hexdigest(), md5=md5(data).hexdigest(), size=len(data), rows=0, producer='archive', coverage={})


def _retain_controls(output, controls):
    """Preflight the complete byte set, then keep or exclusively add each file."""
    from congress_api.retention.derived_files import copy_checked

    if output.is_symlink() or not output.is_dir():
        raise ValueError('Unsafe retained release directory')
    for name, data in controls.items():
        if name != 'manifest.json' and not archive_asset_name(name):
            raise ValueError('Invalid release control path')
        if not isinstance(data, bytes):
            raise ValueError('Release control content must be bytes')
        path = output/name
        parents = [Path(*Path(name).parts[:index]) for index in range(1, len(Path(name).parts))]
        if path.is_symlink() or any((output/parent).is_symlink() for parent in parents):
            raise ValueError('Unsafe retained release control path')
        if any(parent.as_posix() in controls or ((output/parent).exists() and not (output/parent).is_dir())
               for parent in parents):
            raise ValueError('Release control parent is not a directory: '+name)
        if path.exists() and (not path.is_file() or path.stat().st_size != len(data) or path.read_bytes() != data):
            raise ValueError('Retained release control differs: '+name)
    for name, data in controls.items():
        path = output/name
        if not path.exists():
            copy_checked(BytesIO(data), path, size=len(data),
                         expected=dict(sha256=sha256(data).hexdigest(), bytes=len(data)),
                         key=name, exclusive=True)


def _catalog_artifacts(result):
    """Snapshot an admitted public DDK output set; never recheck definitions here.

    A durable caller must retain this exact byte set beside origin, capture_scope,
    content_files and entity_digests as inputs to finalization. A resumed caller
    supplies those retained values, rather than assembling current definitions.
    """
    if result is None or result.report['decision'] != 'passed' or not result.artifacts:
        raise ValueError('DDK catalog checking must pass before release finalization')
    if result.catalog is None or result.catalog['audience'] != 'public':
        raise ValueError('Archive finalization requires an admitted public DDK catalog')
    artifacts = dict(result.artifacts)
    if not {'catalog.ddk.json', 'catalog.report.json', 'catalog.lock.json'} <= artifacts.keys():
        raise ValueError('DDK output set lacks required catalog artifacts')
    for name, data in artifacts.items():
        relative = Path(name)
        if (not CATALOG_ARTIFACT.fullmatch(name) or relative.is_absolute()
                or '..' in relative.parts or name != relative.as_posix()
                or not isinstance(data, bytes)):
            raise ValueError('Invalid DDK output artifact delivery')
    return artifacts


def release_identity(schema_version,files):
    """Hash the one content-only ordered file list declared by DM8.3."""
    identity=[schema_version,[[item['name'],item['sha256'],item['size'],item['rows']] for item in files]]
    return sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


NORMAL_DEFAULTS = dict(body_expected='true', title='cast(NULL AS VARCHAR)', document_kind=EMPTY_STRINGS,
    document_family=EMPTY_STRINGS, committee_keys=EMPTY_STRINGS, chambers=EMPTY_STRINGS,
    congress='cast(NULL AS SMALLINT)', format="'other'", document_date='cast(NULL AS DATE)',
    first_captured='cast(NULL AS DATE)', date_kind="'unknown'", saved_kind="'original'", hidden='false',
    meeting_keys=EMPTY_STRINGS, measure_keys=EMPTY_STRINGS, bioguide_ids=EMPTY_STRINGS,
    witness_keys=EMPTY_STRINGS, version_keys=EMPTY_STRINGS, suffix="'.gz'", media_type="'application/octet-stream'",
    bytes='cast(0 AS BIGINT)', document_date_source='cast(NULL AS VARCHAR)', in_archive_since='cast(NULL AS DATE)',
    removed_on='cast(NULL AS DATE)', review_note='cast(NULL AS VARCHAR)', review_decided_at='cast(NULL AS DATE)',
    alternates=EMPTY_ALTERNATES, package_id='cast(NULL AS VARCHAR)', facts=EMPTY_FACTS, link_bodies=EMPTY_STRINGS, **PAGE_DEFAULTS)


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
    'bills.parquet': ('bill-family', 'roll-call-votes', 'amendments'),
    'nominations.parquet': ('nominations', 'roll-call-votes'),
}


def native_release_job(inputs, steps, *, catalog_result, output, scratch, origin, auxiliary, capture_scope=None,
                       extra_outputs=(), diagnostics=(), metadata_queries=(),
                       content_files=None, lookup_extra=None, entity_digests=None):
    """Construct the shared native JobSpec without opening inputs or executing it.

    Return the native job and blocking diagnostic definitions. DDK owns dataset
    declarations; DocSpec owns physical schemas, execution and acceptance.
    Caller relations remain reusable.
    ``capture_scope`` is accepted at the shared model boundary; its JSON control
    file belongs to finalization and adds no separate native job operation.
    """
    output, scratch = Path(output), Path(scratch)
    steps = list(steps)
    outputs = _core(steps, output,lookup_extra=lookup_extra)
    aux_items = list(auxiliary)
    aux_names = {name for name, _, _, _ in aux_items}
    for name, sql, keys, dictionary in aux_items:
        steps.append(_step(name + '_export', sql, materialize=True))
        outputs.append(dict(name=name + '.parquet', path=str(output / (name + '.parquet')), sql=release_output_sql(name),
            settings=_settings('whole', keys, dictionary=dictionary)))
    from viewer_publication.archive_catalog import publication_checks
    checks, _bindings = publication_checks(catalog_result, aux_names, published=[item['name'] for item in outputs])
    diagnostics = [*diagnostics, *checks]
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
        coverage_parts.append(f"""SELECT '{name}.parquet' AS file,
            min(CASE WHEN o.document_date_status IS DISTINCT FROM 'suspect' THEN o.congress END) AS congress_start,
            max(CASE WHEN o.document_date_status IS DISTINCT FROM 'suspect' THEN o.congress END) AS congress_end,
            min(CASE WHEN o.document_date_status='accepted' THEN o.document_date END) AS date_start,
            max(CASE WHEN o.document_date_status='accepted' THEN o.document_date END) AS date_end FROM {source}""")
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
            min(coalesce(cast(m.congress AS SMALLINT),o.congress_min,p.congress_min,try_cast((regexp_match(w.package_id,'(?i)^CHRG-([0-9]+)'))[1] AS SMALLINT))) AS congress_start,
            max(coalesce(cast(m.congress AS SMALLINT),o.congress_max,p.congress_max,try_cast((regexp_match(w.package_id,'(?i)^CHRG-([0-9]+)'))[1] AS SMALLINT))) AS congress_end,
            min(coalesce(m.meeting_date,o.date_min,p.date_min)) AS date_start,
            max(coalesce(m.meeting_date,o.date_max,p.date_max)) AS date_end
            FROM witnesses_export w
            LEFT JOIN meetings_resolved m ON w.event_id=m.event_id
            LEFT JOIN (
                SELECT unnest(witness_keys) AS witness_key,min(congress) AS congress_min,max(congress) AS congress_max,
                    min(CASE WHEN document_date_status='accepted' THEN document_date END) AS date_min,max(CASE WHEN document_date_status='accepted' THEN document_date END) AS date_max
                FROM ordered WHERE witness_keys IS NOT NULL GROUP BY 1
            ) o ON w.witness_key=o.witness_key
            LEFT JOIN (
                SELECT package_id,min(congress) AS congress_min,max(congress) AS congress_max,
                    min(CASE WHEN document_date_status='accepted' THEN document_date END) AS date_min,max(CASE WHEN document_date_status='accepted' THEN document_date END) AS date_max
                FROM ordered WHERE package_id IS NOT NULL GROUP BY 1
            ) p ON w.package_id=p.package_id""")
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
    queries.append(dict(name='coverage', sql=' UNION ALL '.join(coverage_parts)))
    queries.append(dict(name='document_dates', sql="""SELECT
        sum(CASE WHEN document_date_status='accepted' THEN 1 ELSE 0 END) AS accepted,
        sum(CASE WHEN document_date_status='suspect' THEN 1 ELSE 0 END) AS suspect,
        sum(CASE WHEN document_date IS NULL THEN 1 ELSE 0 END) AS undated FROM ordered"""))
    spec = retire_relations(dict(scratch=str(scratch / 'native'), inputs=inputs, steps=steps, outputs=outputs, queries=queries))
    return spec, diagnostics


def _request_artifact(directory, name, value):
    """Write one immutable, small input with its ordinary artifact identity."""
    data = _content_data(value)
    _retain_controls(directory, {name: data})
    return dict(path=str(directory/name), sha256=sha256(data).hexdigest())


def _controls_directory(path, native_roots=()):
    """Resolve ownership boundaries before any control write or selection."""
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('Release controls cannot use a symlink path')
    path = path.resolve()
    for root in native_roots:
        root = Path(root).resolve()
        if path.is_relative_to(root) or root.is_relative_to(path):
            raise ValueError('Release controls must be separate from retained native artifacts')
    return path


def native_input_declarations(inputs, *, directory, observed_schemas=None, file_pins=None):
    """Bind local bytes and declared physical schemas without converting native inputs.

    Existing file pins are reused by exact path; native admission checks those
    bytes. Native schemas retain the accepted proof's original Arrow IPC bytes.
    """
    from base64 import b64encode
    from hashlib import file_digest
    from os import fstat
    import pyarrow.parquet as pq

    observed_schemas = observed_schemas or {}
    pins = dict(file_pins or {})
    files, schemas = [], []
    for index, item in enumerate(inputs):
        name, kind = item['name'], item['kind']
        if kind == 'native_table':
            schemas.append(dict(name=name, schema_ipc_base64=observed_schemas[name]))
            continue
        if kind == 'parquet':
            encoded = observed_schemas.get(name)
            if encoded is None:
                encoded = b64encode(pq.read_schema(item['path']).serialize().to_pybytes()).decode()
            schemas.append(dict(name=name, schema_ipc_base64=encoded))
            members = [dict(key=None, path=item['path'])]
        elif kind == 'json_lines':
            if name in observed_schemas:
                schemas.append(dict(name=name, schema_ipc_base64=observed_schemas[name]))
            else:
                pin = _request_artifact(directory, f'input-schema-{index}.json', item['schema'])
                schemas.append(dict(name=name, schema_artifact=dict(pin, format='arrow_serde_json')))
            members = item['files']
        else:
            raise ValueError('Unsupported release input kind: ' + kind)
        bound = []
        for member in members:
            path = Path(member['path']).resolve(strict=True)
            key = str(path)
            if key not in pins:
                with path.open('rb') as stream:
                    pins[key] = dict(size=fstat(stream.fileno()).st_size,
                                     sha256=file_digest(stream, 'sha256').hexdigest())
            bound.append(dict(key=member['key'], **{field: pins[key][field] for field in ('sha256', 'size')}))
        files.append(dict(name=name, members=bound))
    return files, schemas


def _read_preparation_artifact(pin):
    """Read bounded retained control bytes without changing their serialization."""
    from ddk.adapters.docspec import DEFAULT_CAPTURE_BYTES

    if (not isinstance(pin, dict) or set(pin) != {'path', 'sha256', 'size'}
            or type(pin['size']) is not int or not 0 < pin['size'] <= DEFAULT_CAPTURE_BYTES):
        raise ValueError('Retained preparation requires exact bounded artifact pins')
    with Path(pin['path']).open('rb') as stream:
        raw = stream.read(pin['size'] + 1)
    if len(raw) != pin['size'] or sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('Retained preparation differs from its original artifact identity')
    return raw


def _retained_preparation(retained, job, native_schemas, runtime):
    """Match prior inference to this exact job, native input schemas and runtime."""
    from base64 import b64decode
    import pyarrow as pa

    if not isinstance(retained, dict) or set(retained) != {'job', 'result', 'policy', 'runtime'}:
        raise ValueError('Retained preparation requires its job, inference, policy and runtime')
    if (not all(runtime.get(key) for key in ('distributionSha256', 'commit'))
            or retained['runtime'] != {key: runtime[key] for key in ('distributionSha256', 'commit')}):
        raise ValueError('Retained schema inference belongs to a different native runtime')
    job_bytes = _read_preparation_artifact(retained['job'])
    if json.loads(job_bytes) != job:
        raise ValueError('Retained preparation names a different job or original input paths')
    inferred = json.loads(_read_preparation_artifact(retained['result']))
    if (inferred.get('input_admission') != 'not_run' or inferred.get('execution') != 'not_run'
            or inferred.get('job', {}).get('sha256') != retained['job']['sha256']
            or inferred.get('job_size') != len(job_bytes)):
        raise ValueError('Retained schema inference differs from the original unexecuted job')
    if [item['name'] for item in inferred.get('inputs', ())] != [item['name'] for item in job['inputs']]:
        raise ValueError('Retained schema inference changes complete ordered input membership')
    schemas = {}
    for item in inferred['inputs']:
        encoded = inferred['schemas'][item['schema_sha256']]
        raw = b64decode(encoded, validate=True)
        if sha256(raw).hexdigest() != item['schema_sha256']:
            raise ValueError('Retained input schema differs from its original digest')
        name = item['name']
        if name in native_schemas:
            observed = pa.ipc.read_schema(pa.BufferReader(raw))
            proved = pa.ipc.read_schema(pa.BufferReader(b64decode(native_schemas[name], validate=True)))
            if not observed.equals(proved, check_metadata=True):
                raise ValueError('Retained native schema differs from the accepted producer proof: ' + name)
        schemas[name] = encoded
    return job_bytes, inferred, schemas


def prepare_native_release(job, diagnostics, *, adapter, project, catalog_result,
                           request_dir, workspace, dataset, operation, policy_id,
                           file_pins, producer_proof, producer_definition, expected_epoch, expected_selection,
                           controls_dir, private_outputs, origin, capture_scope,
                           content_files, entity_digests, retained_preparation=None):
    """Capture a native request and publication inputs, without executing data.

    The caller supplies exact file custody and the verified native producer proof.
    DocSpec infers the complete job; its report schemas bind the blocking policy.
    The returned artifact is the restart input. There is no application phase
    state, phase key, selection pointer or retry loop.
    """
    from ddk.catalog_managed_jobs import managed_job_definition
    from ddk.catalog_native_rules import native_rule_artifact
    from viewer_publication.archive_catalog import captured_catalog_options, native_catalog_mapping
    from viewer_publication.archive_model_profile import native_report_policy
    from viewer_publication.archive_model_proof import producer_proof_bindings, require_producer_proof

    if origin.get('kind') == 'model' or any(item['kind'] == 'native_table' for item in job['inputs']):
        require_producer_proof(producer_proof)
    bindings, native_schemas = (producer_proof_bindings(producer_proof, producer_definition, job['inputs'],
        dataset=dataset, operation=operation) if producer_proof is not None else ({}, {}))
    directory = Path(request_dir).resolve(strict=True)
    project = Path(project).resolve(strict=True)
    workspace = Path(workspace).resolve(strict=True)
    controls_dir = _controls_directory(controls_dir, (workspace,))
    if not project.is_relative_to(directory):
        raise ValueError('Captured release definitions must live beside their request')
    options = captured_catalog_options(project)
    mapping = native_catalog_mapping(catalog_result, job, private_outputs=private_outputs)
    if retained_preparation is None:
        job_pin = _request_artifact(directory, 'job.json', job)
        job_bytes = Path(job_pin['path']).read_bytes()
        inferred = None
        observed_schemas = native_schemas
    else:
        job_bytes, inferred, observed_schemas = _retained_preparation(
            retained_preparation, job, native_schemas, adapter.tool)
        job_pin = {key: retained_preparation['job'][key] for key in ('path', 'sha256')}
        expected_paths = {str(Path(member['path']).resolve()) for item in job['inputs']
            if item['kind'] != 'native_table'
            for member in ([item] if item['kind'] == 'parquet' else item['files'])}
        if not expected_paths <= file_pins.keys():
            raise ValueError('Retained preparation requires every original local file pin')
    if (producer_definition is not None
            and sha256(job_bytes).hexdigest() != producer_definition['model']['job_sha256']):
        raise ValueError('Model JobSpec differs from the exact adopted producer definition')
    file_inputs, input_schemas = native_input_declarations(job['inputs'], directory=directory,
        observed_schemas=observed_schemas, file_pins=file_pins)
    if inferred is None:
        response = adapter.prepare_job(dict(job=job_pin, inputs=input_schemas))
        if response['status'] != 'succeeded':
            raise NativeReleaseNotReady('schema preparation', response)
        inferred = response['result']
    rules = native_rule_artifact(catalog_result, job_bytes,
        native_rule_profile=options['native_rule_profile'], **mapping)
    rules_pin = _request_artifact(directory, 'native-rules.json', rules)
    definition = managed_job_definition(catalog_result, native_rules=rules_pin,
        native_rule_profile=options['native_rule_profile'], **mapping)
    if producer_definition is not None and definition != producer_definition['definition']:
        raise ValueError('Model dataset definition differs from the adopted producer definition')
    policy = native_report_policy(job_bytes, diagnostics, inferred, policy_id=policy_id)
    if retained_preparation is None:
        policy_pin = _request_artifact(directory, 'policy.json', policy)
    else:
        if json.loads(_read_preparation_artifact(retained_preparation['policy'])) != policy:
            raise ValueError('Retained policy differs from the original required reports or inferred schemas')
        policy_pin = {key: retained_preparation['policy'][key] for key in ('path', 'sha256')}
    if (producer_definition is not None
            and (policy_id != producer_definition['model']['policy_id']
                 or policy_pin['sha256'] != producer_definition['model']['policy_sha256'])):
        raise ValueError('Model policy differs from the exact adopted producer definition')
    request = dict(action='prepare', dataset=dataset, operation=operation, definition=definition,
        job=job_pin, file_inputs=file_inputs, policy_id=policy_id, policy=policy_pin,
        **bindings,
        expected_epoch=expected_epoch, expected_selection=expected_selection)
    return _request_artifact(directory, 'release-request.json', dict(
        native=request, workspace=str(workspace),
        project=str(project), mapping=mapping, native_rules=rules_pin,
        controls_dir=str(controls_dir), origin=origin,
        capture_scope=capture_scope, content_files=content_files, entity_digests=entity_digests))


def execute_native_release(prepared, *, adapter, snapshot_source=None):
    """Execute or resume the exact request through the maintained native owner.

    Keep the first accepted receipt as the catalog's immutable metadata input.
    Later native observations never replace that observation's timestamp or
    identity. Selection follows successful DDK schema and rule qualification.
    The optional private source configuration is native-owned execution input;
    it stays outside the saved request, receipt and catalog.
    """
    from ddk.catalog import assemble_catalog
    from ddk.catalog_managed_jobs import managed_job_metadata
    from ddk.docspec_job_evidence import verify_completed_job
    from viewer_publication.archive_catalog import captured_catalog_options

    path = Path(prepared['path']).resolve(strict=True)
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != prepared['sha256']:
        raise ValueError('Prepared release input differs from its original artifact identity')
    saved = json.loads(raw)
    request, workspace = saved['native'], saved['workspace']
    if saved.get('origin', {}).get('kind') == 'model':
        from viewer_publication.archive_model_proof import require_model_proof_request
        require_model_proof_request(request)
    _controls_directory(saved['controls_dir'], (workspace,))
    project = Path(saved['project'])
    options = captured_catalog_options(project)
    options['permitted_roots'].append(path.parent)
    # Requalification keeps the original rules beside the original request.
    # Admit that one pinned file, without granting access to its whole directory.
    options['permitted_roots'].append(Path(saved['native_rules']['path']))
    response = adapter.managed_job(workspace, request, snapshot_source=snapshot_source)
    if response['status'] != 'succeeded' or response['result']['status'] != 'completed':
        raise NativeReleaseNotReady('preparation', response)
    verify_completed_job(response['result'])
    native = response['result']
    action = dict(dataset=native['dataset'], operation=native['operation'],
        request_digest=native['request_digest'], candidate=native['candidate'], policy_id=request['policy_id'])
    accepted = adapter.managed_job(workspace, dict(action='accept', **action), prior=response)
    if accepted['status'] != 'succeeded':
        raise NativeReleaseNotReady('acceptance', accepted)
    evidence = verify_completed_job(accepted['result'], require_accepted=True)
    metadata_path = path.parent/'catalog-metadata.json'
    if not metadata_path.exists():
        # Copy only this bounded metadata record, preserving every original byte.
        # Native payloads and their completion records remain with DocSpec.
        receipt_path = path.parent/'native-accepted.json'
        if not receipt_path.exists():
            receipt_bytes = Path(accepted['evidence']['path']).read_bytes()
            if sha256(receipt_bytes).hexdigest() != accepted['evidence']['sha256']:
                raise ValueError('Accepted receipt changed before it could be retained')
            _retain_controls(path.parent, {receipt_path.name: receipt_bytes})
        receipt = dict(path=str(receipt_path), sha256=sha256(receipt_path.read_bytes()).hexdigest())
        metadata = managed_job_metadata(receipt=receipt, native_rules=saved['native_rules'], **saved['mapping'])
        _request_artifact(path.parent, metadata_path.name, metadata)
    catalog = assemble_catalog(project, metadata=metadata_path, metadata_adapter='local',
        disclosure_policy=project.parent/'public-disclosure.json', exports=('dcat',), **options)
    # Finalization also joins exact membership and acceptance to this same result.
    from viewer_publication.archive_catalog import accepted_output_definitions
    accepted_output_definitions(evidence, catalog)
    _catalog_artifacts(catalog)
    release = finalize_native_release(evidence, catalog, **{key: saved[key] for key in (
        'controls_dir', 'origin', 'capture_scope', 'content_files', 'entity_digests')})
    selected = adapter.managed_job(workspace, dict(action='select',
        accepted_qualification=evidence.accepted['identity'], **action), prior=accepted)
    if selected['status'] != 'succeeded' or selected['result']['selection'] != 'selected':
        raise NativeReleaseNotReady('selection', selected)
    evidence = verify_completed_job(selected['result'], require_accepted=True)
    accepted_output_definitions(evidence, catalog)
    return release


def finalize_native_release(evidence, catalog_result, *, controls_dir, origin, capture_scope,
                            content_files, entity_digests):
    """Finalize one accepted native candidate without reading or copying data.

    DDK has already bound the captured definitions and native schema/counter
    evidence. The native JobResult supplies reports and export identities;
    its exact retained paths stay with the native owner. Only application
    controls are written here. Return the manifest and its complete file map.
    """
    from viewer_publication.archive_catalog import accepted_output_definitions, coverage_limits

    definitions = accepted_output_definitions(evidence, catalog_result)
    catalog_artifacts = _catalog_artifacts(catalog_result)
    result = evidence.manifest['result']
    reports = {query['name']: query['data'] for query in result['queries']}
    native_paths = {entry['name']: Path(entry['path']) for entry in evidence.manifest['outputs']}
    controls_dir = _controls_directory(controls_dir, (path.parent for path in native_paths.values()))
    coverage = {row['file']: {key: value for key, value in row.items() if key != 'file'} for row in reports['coverage']}
    document_dates = {key: int(value or 0) for key, value in reports['document_dates'][0].items()}
    for name in ('list.parquet', 'detail.parquet'):
        if name in coverage:
            coverage[name]['document_dates'] = document_dates
    files = []
    for entry in result['outputs']:
        if entry['name'] not in definitions:
            continue
        file_gaps = coverage_limits(definitions[entry['name']]) or list(origin['gaps'])
        producer = 'spicy-regs' if (entity_digests is not None and entry['name'] in SPICY_PRODUCER_FAMILIES) else 'archive'
        extra_meta = {}
        if producer == 'spicy-regs':
            extra_meta['generations'] = {
                family: entity_digests[family]
                for family in SPICY_PRODUCER_FAMILIES[entry['name']]
                if family in entity_digests
            }
        exported = {key: value for key, value in entry.items() if key != 'footer_bytes'}
        files.append(dict(exported, row_range=None, shard=None, producer=producer, **extra_meta,
            coverage=dict(coverage.get(entry['name'], dict(congress_start=None, congress_end=None, date_start=None, date_end=None)), gaps=file_gaps)))
    controls = {'capture_scope.json': _content_data(dict(version=1, entries=[]) if capture_scope is None else capture_scope)}
    for name, value in (content_files or {}).items():
        if name in {'manifest.json', 'schema.json'} or name in controls:
            raise ValueError('Release control collides with a prepared control or uses retired schema metadata')
        controls[name] = _content_data(value)
    occupied = {item['name'] for item in files}
    if (occupied & (controls.keys() | catalog_artifacts.keys())
            or controls.keys() & catalog_artifacts.keys()):
        raise ValueError('DDK artifact collides with a release file')
    controls.update(sorted(catalog_artifacts.items()))
    files.extend(_content_record(name, data) for name, data in controls.items())
    manifest = dict(schema_version=1, files=files, facet_counts=reports['facets'],
                    release_id=release_identity(1, files), origin=origin)
    controls['manifest.json'] = _content_data(manifest)
    controls_dir.mkdir(parents=True, exist_ok=True)
    _retain_controls(controls_dir, controls)
    return manifest, {**{name: native_paths[name] for name in definitions},
                      **{name: controls_dir/name for name in controls}}
