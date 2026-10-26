import duckdb
O='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/page-versions/'
c=duckdb.connect()
c.sql(f"""create table rc as select *,
  case when attempt>=0 then att_status else coalesce(cap_status, rec_status) end st,
  case when attempt>=0 then att_complete else complete end cmp,
  case when mode like 'fileref%' then context_url else coalesce(requested_url, context_url) end req_key,
  regexp_replace(rfile, '-[0-9]+\\.jsonl\\.gz$', '') run
  from '{O}receipt_caps.parquet' where pointer not like '%archive_members%' and sha256 is not null
  and pointer not like '%provider_response%'""")
GOOD="st between 200 and 299 and coalesce(cmp,true) and coalesce(outcome,'x') not in ('request_failed','http_error','retry_later','empty','invalid_document','unverified','size_limit')"
for kind, mt in [('html',"media_type like 'text/html%'"),('bin',"(media_type like 'application/pdf%' or media_type like 'application/zip%' or media_type like '%word%' or media_type like '%octet%')")]:
    c.sql(f"create table g_{kind} as select * from rc where {mt} and {GOOD}")
    for key in ['req_key','context_url']:
        c.sql(f"create or replace table p_{kind}_{key} as select {key} k, count(distinct sha256) nb from g_{kind} where {key} is not null group by 1 having nb>=2")
        print(kind, key, c.sql(f"select count(*) from p_{kind}_{key}").fetchall())
    c.sql(f"copy g_{kind} to '{O}good_{kind}.parquet'")
    c.sql(f"copy p_{kind}_req_key to '{O}recpop_{kind}_req.parquet'")
    c.sql(f"copy p_{kind}_context_url to '{O}recpop_{kind}_ctx.parquet'")
c.sql(f"create table snap as select context_url k from '{O}urls_html.parquet'")
print('html req vs snap: both', c.sql("select count(*) from p_html_req_key join snap using(k)").fetchall(),
  'rec-only', c.sql("select count(*) from p_html_req_key anti join snap using(k)").fetchall(),
  'snap-only', c.sql("select count(*) from snap anti join p_html_req_key using(k)").fetchall())
print(c.sql("select k from snap anti join p_html_req_key using(k) limit 5").fetchall())
print(c.sql("select k from p_html_req_key anti join snap using(k) limit 5").fetchall())
# origin decomposition per URL (req key)
c.sql("""create table origin as select k, nb,
   count(distinct run) nruns, count(distinct rfile||line) nlines,
   bool_or(attempt>=0) has_attempt, bool_or(mode='retained_import') has_import, bool_or(mode like 'fileref%') has_fileref,
   count(distinct sha256) filter (where attempt<0) nb_final,
   count(distinct sha256) filter (where attempt<0 and mode='fetch') nb_final_fetch,
   min(coalesce(retrieved_at, rec_retrieved_at)) t0, max(coalesce(retrieved_at, rec_retrieved_at)) t1
   from p_html_req_key p join g_html g on g.req_key=p.k group by all""")
c.sql(f"copy origin to '{O}origin_html.parquet'")
print(c.sql("""select case when nlines=1 then 'one fetch line (attempt vs final)'
      when nb_final_fetch>=2 then 'two+ separate live fetches with different final bodies'
      when has_import or has_fileref then 'involves import/archive or file-ref body'
      else 'other' end why, count(*) from origin group by 1 order by 2 desc""").fetchall())
print(c.sql("select has_attempt, has_import, has_fileref, nb_final_fetch, count(*) from origin group by all order by 5 desc").fetchall())
