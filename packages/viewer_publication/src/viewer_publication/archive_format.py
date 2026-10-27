"""Shared native release layout; application models supply complete document rows."""
from hashlib import md5, sha256
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


def _release_schema():
    # The interface registry is shared with the reader; policy metadata stays
    # content-only while all row transformations and Parquet writing stay native.
    return json.loads((ROOT / 'model/registries/release-schema.json').read_text())
