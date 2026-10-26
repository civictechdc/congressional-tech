import duckdb
con=duckdb.connect()
q="""
with u as (select distinct context_url url from '/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/captures.parquet' where context_url is not null
 union select distinct url from '/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/download-state.parquet'),
t as (select url, regexp_extract(url, '(HHRG|HMKP|HMTG)[-_]?[^/?#]*', 0) tok from u where regexp_matches(url,'HHRG|HMKP|HMTG'))
select case when regexp_matches(tok,'^(HHRG|HMKP|HMTG)-\\d{2,3}-[A-Za-z]{2}\\d{2}-') then 'prefix-congress-committee-...'
            when regexp_matches(tok,'^(HHRG|HMKP|HMTG)-?\\d{5,6}($|[^0-9-])') then 'prefix+eventid-like'
            else 'other' end k, count(*), any_value(tok) from t group by 1
"""
print(con.sql(q).fetchall())
print(con.sql("select count(distinct regexp_extract(url,'docs\\.house\\.gov/meetings/[^/]+/[^/]+/\\d+/([^/]+)/',1)) n, count(distinct regexp_extract(url,'docs\\.house\\.gov/meetings/[^/]+/[^/]+/\\d+/([^/]+)/',1)) filter (where not regexp_matches(regexp_extract(url,'docs\\.house\\.gov/meetings/[^/]+/[^/]+/\\d+/([^/]+)/',1),'^\\d+$')) nondigit from (select distinct context_url url from '/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/captures.parquet') where regexp_matches(url,'docs\\.house\\.gov/meetings/[^/]+/[^/]+/\\d+/[^/]+/')").fetchall())
