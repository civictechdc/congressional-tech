"""F5: ZIP endpoints with two distinct real ZIP bodies; which need a streaming walk. Reproduces the reviewer's 685 with his
predicate (port in vm7_f2_repro.py style) and explains each body with this folder's flags (recovery, sniff format, status)."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
def q(l,s):
    rows=con.execute(s).fetchall(); print(f'\n## {l}')
    for r in rows[:30]: print('  ',r)
con.execute("CREATE TEMP TABLE ls AS SELECT rk, rl, max(st_row) st FROM c WHERE mem IS NULL GROUP BY 1,2")
con.execute("""CREATE TEMP TABLE pz AS SELECT c.*, regexp_replace(regexp_replace(regexp_replace(regexp_replace(ctx, '^https?://web\\.archive\\.org/web/[0-9]+[a-z_]*/', ''), '^https?://(www\\.)?', ''), '/$', ''), '#.*$', '') pukey
  FROM c LEFT JOIN ls USING (rk, rl) WHERE mt ILIKE '%zip%' AND sha IS NOT NULL AND bytes>0 AND rkind<>'retained-file' AND coalesce(st_row, ls.st) BETWEEN 200 AND 299
  AND sha NOT IN (SELECT sha FROM placeholders) AND mem IS NULL""")
con.execute("CREATE TEMP TABLE pze AS SELECT pukey FROM pz GROUP BY 1 HAVING count(DISTINCT sha)>=2")
q("reviewer-style ZIP endpoints (media type ILIKE zip, which also matches gzip)", "SELECT count(*) FROM pze")
q("their rows: media type, recovery, this folder's format, good, family, receipt shape", """SELECT mt, recovery, fmt, good, fam, regexp_extract(rk,'/([a-z]+)-[^/]*$',1), count(*), count(DISTINCT sha), count(DISTINCT pukey)
   FROM pz WHERE pukey IN (SELECT pukey FROM pze) GROUP BY ALL ORDER BY 7 DESC""")
q("per endpoint: number of recovery ZIP bodies vs fetched ZIP bodies", """WITH e AS (SELECT pukey, count(DISTINCT sha) FILTER (WHERE recovery) nr, count(DISTINCT sha) FILTER (WHERE NOT recovery) nf FROM pz WHERE pukey IN (SELECT pukey FROM pze) GROUP BY 1)
   SELECT nr, nf, count(*) FROM e GROUP BY ALL ORDER BY 3 DESC""")
# this folder's real ZIPs (sniff/old reading first; recoveries excluded)
con.execute("CREATE TEMP TABLE ze AS SELECT ctx, count(DISTINCT sha) nb FROM real WHERE fmt='zip' AND mem IS NULL GROUP BY 1 HAVING count(DISTINCT sha)>=2")
con.execute("""CREATE TEMP TABLE zb AS SELECT DISTINCT r.ctx, r.sha, r.bytes,
   EXISTS (SELECT 1 FROM c m WHERE m.rk=r.rk AND m.rl=r.rl AND m.mem IS NOT NULL) expanded_here FROM real r JOIN ze USING (ctx) WHERE r.fmt='zip' AND r.mem IS NULL""")
con.execute("CREATE TEMP TABLE zbx AS SELECT ctx, sha, any_value(bytes) bytes, bool_or(expanded_here) expanded FROM zb GROUP BY 1,2")
q("DM proxy: endpoints with >=2 distinct real ZIP bodies; bodies", "SELECT count(*), sum(nb) FROM ze")
q("DM proxy: endpoints with an unexpanded ZIP (walk needed); unexpanded bodies; GB", """SELECT count(DISTINCT ctx) FILTER (WHERE NOT expanded), count(*) FILTER (WHERE NOT expanded), round(sum(bytes) FILTER (WHERE NOT expanded)/1e9,2) FROM zbx""")
q("DM proxy: member-set fingerprints at fully expanded endpoints (equal -> same_text; differ -> ambiguous)", """
  WITH fp AS (SELECT r.ctx, r.sha, sha256(string_agg(m.sha, chr(10) ORDER BY m.sha)) fp FROM (SELECT DISTINCT ctx, sha, rk, rl FROM real WHERE fmt='zip' AND mem IS NULL AND ctx IN (SELECT ctx FROM ze)) r
              JOIN c m ON m.rk=r.rk AND m.rl=r.rl AND m.mem IS NOT NULL GROUP BY 1,2),
       e AS (SELECT ctx, count(DISTINCT fp) nfp, count(*) n FROM fp GROUP BY 1)
  SELECT nfp=1 equal, count(*) FROM e GROUP BY 1""")
q("DM proxy ZIP endpoints by host", "SELECT regexp_extract(ctx,'^https?://([^/]+)',1), count(*) FROM ze GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
q("fingerprint-candidate ZIPs overall (DM proxy): bodies, of which unexpanded", "SELECT count(*), count(*) FILTER (WHERE NOT expanded) FROM zbx")
# --- why each of the reviewer's 685 endpoints falls away under DM 7.3
q("685 endpoints: per ZIP row, why it is not a real file here", """
  SELECT CASE WHEN id IN (SELECT id FROM real) THEN 'real' WHEN recovery THEN 'recovery import (mode retained_import)'
              WHEN is_prior AND NOT att_complete THEN 'cut-off prior attempt (raw complete=false)'
              WHEN res IN ('request_failed','size_limit','resource_limit','timeout','http_error') THEN 'line outcome '||res
              ELSE 'other: '||coalesce(res,'') END why, count(*), count(DISTINCT sha), count(DISTINCT pukey), round(sum(bytes)/1e9,2)
  FROM pz WHERE pukey IN (SELECT pukey FROM pze) GROUP BY 1 ORDER BY 2 DESC""")
q("685 endpoints: count of real ZIP bodies left per endpoint", """WITH e AS (SELECT pukey, count(DISTINCT sha) FILTER (WHERE id IN (SELECT id FROM real)) n FROM pz WHERE pukey IN (SELECT pukey FROM pze) GROUP BY 1)
  SELECT n, count(*) FROM e GROUP BY 1 ORDER BY 1""")
