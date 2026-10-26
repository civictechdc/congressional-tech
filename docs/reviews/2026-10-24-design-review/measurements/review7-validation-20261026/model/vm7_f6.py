"""F6: veterans.house.gov page versions. Which archives saved them, and at what URL (wrapped or not)."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
def q(l,s):
    rows=con.execute(s).fetchall(); print(f'\n## {l}')
    for r in rows[:30]: print('  ',r)
V="(ctx ILIKE '%veterans.house.gov%')"
q("veterans.house.gov HTML-format rows: family, receipt shape, pointer, wrapped?, good, real", f"""SELECT fam, regexp_extract(rk,'/([a-z]+)-[^/]*$',1) shape, regexp_replace(ptr,'[0-9]+','N','g') p,
   ctx LIKE '%web.archive.org%' wrapped, good, id IN (SELECT id FROM real) is_real, count(*), count(DISTINCT sha), count(DISTINCT ctx) FROM c WHERE {V} AND fmt='html' GROUP BY ALL ORDER BY 7 DESC""")
q("transport per family for veterans html lines (raw transport not in snapshot; receipt key prefix shown)", f"""SELECT fam, regexp_extract(rk,'^receipts/([^/]+/[^/]+)',1), count(*) FROM c WHERE {V} AND fmt='html' GROUP BY ALL ORDER BY 3 DESC LIMIT 10""")
for nm, cond in [('real (proxy)', "id IN (SELECT id FROM real)"), ('good, any role, html', "coalesce(good,false)"), ('any status, html, with body', "sha IS NOT NULL")]:
    q(f"veterans exact URLs with >=2 distinct HTML bodies [{nm}]: count, by family combination", f"""WITH e AS (SELECT ctx, count(DISTINCT sha) nb, list_sort(list_distinct(list(fam))) fams FROM c WHERE {V} AND fmt='html' AND {cond} GROUP BY 1 HAVING count(DISTINCT sha)>=2)
       SELECT fams::VARCHAR, count(*), sum(nb) FROM e GROUP BY 1 ORDER BY 2 DESC""")
    q(f"same, on ukey [{nm}]", f"""WITH e AS (SELECT ukey, count(DISTINCT sha) nb, list_sort(list_distinct(list(fam))) fams FROM c WHERE (ukey LIKE 'veterans.house.gov%') AND fmt='html' AND {cond} GROUP BY 1 HAVING count(DISTINCT sha)>=2)
       SELECT fams::VARCHAR, count(*), sum(nb) FROM e GROUP BY 1 ORDER BY 2 DESC""")
q("all hosts: exact URLs with >=2 distinct good HTML bodies (no role filter), top hosts", """WITH e AS (SELECT ctx, count(DISTINCT sha) nb FROM c WHERE fmt='html' AND coalesce(good,false) AND mem IS NULL GROUP BY 1 HAVING count(DISTINCT sha)>=2)
   SELECT regexp_extract(ctx,'^https?://([^/]+)',1) h, count(*) FROM e GROUP BY 1 ORDER BY 2 DESC LIMIT 8""")
q("veterans 2-body endpoints: example rows", f"""WITH e AS (SELECT ctx FROM c WHERE {V} AND fmt='html' AND coalesce(good,false) GROUP BY 1 HAVING count(DISTINCT sha)>=2 LIMIT 2)
   SELECT ctx[1:80], fam, rk[1:75], ptr, sha[1:12], bytes, retrieved_at, res FROM c JOIN e USING (ctx) WHERE fmt='html' ORDER BY ctx""")
# --- part 2: reproduce the reconciliation's 959 (its predicate: exact URL, >=2 distinct text/html bodies, row status 2xx,
# resolution in saved/html/digest_verified, not archive members) and say where each body came from
G="st_row between 200 and 299 and sha is not null and bytes>0 and coalesce(ptr,'') not like '%archive_members%' and res in ('saved','html','digest_verified') and mt like 'text/html%'"
con.execute(f"CREATE TEMP TABLE e959 AS SELECT ctx FROM c WHERE {G} AND ctx LIKE '%veterans.house.gov%' GROUP BY 1 HAVING count(DISTINCT sha)>=2")
q("reconciliation predicate: all hosts / veterans endpoints", f"WITH e AS (SELECT ctx FROM c WHERE {G} GROUP BY 1 HAVING count(DISTINCT sha)>=2) SELECT count(*), count(*) FILTER (WHERE ctx LIKE '%veterans.house.gov%') FROM e")
q("959 veterans endpoints: body origins (recovery = raw mode retained_import; eot = line also holds an eot.raw_warc entry)", f"""
  WITH b AS (SELECT c.ctx, c.sha, c.recovery, (c.rk, c.rl) IN (SELECT rk, rl FROM c WHERE fmt='warc') eot, c.rk LIKE '%corpus-recovery%' corpus
             FROM c JOIN e959 USING (ctx) WHERE {G})
  SELECT recovery, eot, corpus, count(*), count(DISTINCT ctx) FROM b GROUP BY ALL""")
q("959: endpoints with exactly one EOT copy and one recovery copy", f"""
  WITH b AS (SELECT c.ctx, bool_or(c.recovery) r, bool_or((c.rk, c.rl) IN (SELECT rk, rl FROM c WHERE fmt='warc')) e, count(DISTINCT sha) n FROM c JOIN e959 USING (ctx) WHERE {G} GROUP BY 1)
  SELECT r, e, n, count(*) FROM b GROUP BY ALL""")
q("959: under DM 7.3 (recoveries are not real files), endpoints with >=2 real bodies counting the WARC as a document; without the WARC; endpoints left with one real body", """
  SELECT count(*) FILTER (WHERE n>=2), count(*) FILTER (WHERE n_nowarc>=2), count(*) FILTER (WHERE n_nowarc=1) FROM (SELECT ctx, count(DISTINCT sha) n, count(DISTINCT sha) FILTER (WHERE fmt<>'warc') n_nowarc FROM real JOIN e959 USING (ctx) GROUP BY 1)""")
# --- part 3: the real page-version population under DM (exact endpoints with >=2 distinct real HTML bodies, WARC excluded)
q("page-version endpoints: count; bodies from one fetch line vs several lines; by host", """
  WITH e AS (SELECT ctx, count(DISTINCT sha) nb, count(DISTINCT (rk, rl)) nl, bool_or(is_prior) pr FROM real WHERE fmt='html' AND mem IS NULL GROUP BY 1 HAVING count(DISTINCT sha)>=2)
  SELECT nl=1 one_line, pr has_prior_attempt, count(*), sum(nb) FROM e GROUP BY ALL ORDER BY 3 DESC""")
q("page-version endpoints by host", """WITH e AS (SELECT ctx FROM real WHERE fmt='html' AND mem IS NULL GROUP BY 1 HAVING count(DISTINCT sha)>=2)
  SELECT regexp_extract(ctx,'^https?://([^/]+)',1), count(*) FROM e GROUP BY 1 ORDER BY 2 DESC LIMIT 6""")
