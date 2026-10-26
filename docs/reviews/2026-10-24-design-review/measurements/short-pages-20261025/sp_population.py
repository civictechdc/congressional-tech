# Build the population: distinct HTML bodies with a 2xx, complete capture.
import duckdb, sys
D='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
OUT='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/short-pages/'
c=duckdb.connect()
c.sql(f"create view cap as select * from '{D}captures.parquet'")
c.sql(f"create view rd as select * from '{D}readings/*.parquet'")
c.sql("""create table good as
select c.sha256, c.body_key, c.family, c.context_url, c.original_path, c.bytes, c.media_type, c.fidelity, c.resolution, c.http_status,
       list_contains(r.record_role,'error-response') as parser_error
from cap c join rd r using(body_key)
where list_contains(r.body_format,'html') and c.http_status between 200 and 299
  and c.fidelity in ('exact-bytes','retained-file')
  and c.resolution in ('saved','digest_verified','html','path_verified')
  and c.sha256 is not null and c.bytes > 0""")
print('capture rows', c.sql('select count(*), count(distinct sha256), count(distinct context_url) from good').fetchall())
c.sql("""create table pop as
select sha256, any_value(body_key) AS body_key, min(context_url) AS context_url, arg_min(original_path, context_url) AS member_path, arg_min(family, context_url) AS family,
       max(bytes) AS bytes, bool_or(parser_error) AS parser_error, count(distinct context_url) AS n_urls,
       lower(regexp_extract(min(context_url), '^https?://([^/:]+)', 1)) AS host
from good group by sha256""")
print('bodies', c.sql('select count(*), sum(parser_error::int), sum((n_urls>100)::int) from pop').fetchall())
print(c.sql("select family, count(*) from pop group by 1 order by 2 desc").fetchall())
print(c.sql("select host, count(*) n from pop group by 1 order by 2 desc limit 50").fetchall())
print('hosts', c.sql("select count(distinct host) from pop").fetchall())
print(c.sql("select case when bytes<5000 then 'a<5k' when bytes<15000 then 'b<15k' when bytes<40000 then 'c<40k' when bytes<100000 then 'd<100k' else 'e>=100k' end b, count(*) from pop group by 1 order by 1").fetchall())
c.sql(f"copy pop to '{OUT}pop.parquet'")
