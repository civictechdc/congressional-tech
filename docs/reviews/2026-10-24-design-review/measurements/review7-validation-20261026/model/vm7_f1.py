"""F1: WARC envelopes. Counts on vm7.duckdb. WARC = media type application/(w)arc+gzip (all at pointer eot.raw_(w)arc.body).
Raw check (vm7_warc_raw_all.out): every WARC entry and its payload carry http_status 200, line complete=true, mode=fetch, so
all WARC rows and their payload rows are treated as good fetches here (31 snapshot rows lost the status)."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
def q(l,s):
    rows=con.execute(s).fetchall(); print(f'\n## {l}')
    for r in rows[:30]: print('  ',r)
con.execute("""CREATE TEMP TABLE wl AS SELECT DISTINCT rk, rl FROM c WHERE fmt='warc'""")
# real rows with the WARC override: WARC rows and their line siblings are good
con.execute("""CREATE TEMP TABLE r2 AS
  SELECT * FROM real UNION ALL
  SELECT * FROM c WHERE (rk, rl) IN (SELECT rk, rl FROM wl) AND NOT coalesce(good,false) AND bytes>0
     AND role='document' AND NOT (fmt='html' AND file_shaped) AND sha NOT IN (SELECT sha FROM placeholders)""")
q("WARC bodies: n, GB, distinct context_url, fidelity", "SELECT count(*), count(DISTINCT sha), round(sum(bytes)/1e9,3), count(DISTINCT ctx), list(DISTINCT fid), list(DISTINCT fam) FROM c WHERE fmt='warc'")
q("WARC URL suffix", "SELECT CASE WHEN ext IN ('.pdf','.htm','.html','.xml','.wvx') THEN ext WHEN ext LIKE '.%' THEN 'other ext' ELSE 'none' END, count(*) FROM c WHERE fmt='warc' GROUP BY 1 ORDER BY 2 DESC")
q("payload rows in WARC lines: fmt, role, file_shaped, real?", """SELECT p.fmt, p.role, p.file_shaped, p.sha IN (SELECT sha FROM r2) is_real_somewhere,
   count(*), count(DISTINCT p.sha) FROM c p JOIN wl USING (rk, rl) WHERE p.fmt<>'warc' GROUP BY ALL ORDER BY 5 DESC""")
q("WARC lines whose payload is not stored as its own body", "SELECT count(*) FROM wl WHERE (rk,rl) NOT IN (SELECT rk, rl FROM c WHERE fmt<>'warc' AND sha IS NOT NULL)")
for name, key in [('exact endpoint (ctx, mem)', "ctx || '|' || coalesce(mem,'')"), ('ukey endpoint', "ukey || '|' || coalesce(mem,'')")]:
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ep AS SELECT {key} k, count(DISTINCT sha) nb, count(DISTINCT sha) FILTER (WHERE fmt<>'warc') nb_nonwarc,
        bool_or(fmt='warc') has_warc, list_sort(list_distinct(list(fmt) FILTER (WHERE fmt<>'warc'))) oth FROM r2 GROUP BY 1""")
    q(f"{name}: endpoints holding a real WARC, by other real formats there (WARC counted as a document)",
      "SELECT oth::VARCHAR, nb_nonwarc, count(*) FROM ep WHERE has_warc GROUP BY ALL ORDER BY 3 DESC")
    q(f"{name}: summary: WARC endpoints; ambiguous only because of the WARC (exactly one other real body); WARC alone (would list a WARC document); ambiguous anyway (>=2 non-WARC bodies)",
      "SELECT count(*), count(*) FILTER (WHERE nb_nonwarc=1), count(*) FILTER (WHERE nb_nonwarc=0), count(*) FILTER (WHERE nb_nonwarc>=2) FROM ep WHERE has_warc")
    q(f"{name}: the WARC-caused ambiguous endpoints by the other body's format", "SELECT oth::VARCHAR, count(*) FROM ep WHERE has_warc AND nb_nonwarc=1 GROUP BY 1 ORDER BY 2 DESC")
q("WARC-caused ambiguous HTML endpoints by host (exact)", """WITH e AS (SELECT ctx, count(DISTINCT sha) FILTER (WHERE fmt<>'warc') n, bool_or(fmt='warc') w, bool_and(fmt IN ('warc','html')) h FROM r2 WHERE mem IS NULL GROUP BY 1)
   SELECT regexp_extract(ctx,'^https?://([^/]+)',1) host, count(*) FROM e WHERE w AND n=1 AND h GROUP BY 1 ORDER BY 2 DESC LIMIT 10""")
q("WARC-line PDF payloads: damaged proxy (resolution invalid_document)", "SELECT p.res, p.role, count(*) FROM c p JOIN wl USING (rk,rl) WHERE p.fmt='pdf' GROUP BY ALL")
q("fingerprint work the WARCs would add (DM as written: WARC sniffs 'other', both bodies are candidates): payload PDFs n, GB; WARC n, GB", """
  SELECT count(DISTINCT p.sha) FILTER (WHERE p.fmt='pdf'), round(sum(p.bytes) FILTER (WHERE p.fmt='pdf')/1e9,2),
         count(DISTINCT p.sha) FILTER (WHERE p.fmt='warc'), round(sum(p.bytes) FILTER (WHERE p.fmt='warc')/1e9,2)
  FROM (SELECT DISTINCT sha, fmt, bytes FROM c WHERE (rk, rl) IN (SELECT rk, rl FROM wl)) p""")
