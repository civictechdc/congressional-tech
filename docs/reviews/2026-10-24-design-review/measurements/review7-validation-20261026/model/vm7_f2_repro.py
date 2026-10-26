"""F2: reproduce the reviewer's [html, pdf] endpoints with his predicate (prof7_grouping2.py: media-type format, status inherited
from the line max, reference_kind <> 'retained-file', no mode filter), then explain each with this folder's flags."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
def q(l,s):
    rows=con.execute(s).fetchall(); print(f'\n## {l}')
    for r in rows[:30]: print('  ',r)
con.execute("""CREATE TEMP TABLE pf AS SELECT c.*,
  CASE WHEN mt ILIKE '%html%' THEN 'html' WHEN mt ILIKE '%pdf%' THEN 'pdf' WHEN mt ILIKE '%zip%' THEN 'zip' WHEN mt ILIKE '%xml%' THEN 'xml'
       WHEN mt ILIKE '%json%' THEN 'json' WHEN mt ILIKE '%vtt%' THEN 'vtt' WHEN mt ILIKE '%mpegurl%' THEN 'm3u8'
       WHEN mt='' OR mt ILIKE '%octet-stream%' THEN CASE WHEN loc LIKE '%.pdf' THEN 'pdf' WHEN loc LIKE '%.zip' THEN 'zip' WHEN regexp_matches(loc,'\\.html?$') THEN 'html' WHEN loc LIKE '%.xml' THEN 'xml' ELSE 'other' END
       ELSE 'other' END pfmt,
  regexp_replace(regexp_replace(regexp_replace(regexp_replace(ctx, '^https?://web\\.archive\\.org/web/[0-9]+[a-z_]*/', ''), '^https?://(www\\.)?', ''), '/$', ''), '#.*$', '') pukey,
  lower(coalesce(mem, regexp_replace(ctx, '[?#].*$', ''))) ploc
  FROM c""")
con.execute("CREATE TEMP TABLE ls AS SELECT rk, rl, max(st_row) st FROM c WHERE mem IS NULL GROUP BY 1,2")
con.execute("""CREATE TEMP TABLE preal AS SELECT pf.*, coalesce(pf.st_row, ls.st) pst FROM pf LEFT JOIN ls USING (rk, rl)
  WHERE sha IS NOT NULL AND bytes>0 AND rkind <> 'retained-file' AND coalesce(pf.st_row, ls.st) BETWEEN 200 AND 299
    AND sha NOT IN (SELECT sha FROM placeholders) AND pfmt NOT IN ('vtt','m3u8','json')
    AND NOT (pfmt='html' AND (regexp_matches(ploc,'\\.(pdf|zip|doc|docx|xml)$') OR ctx LIKE '%/download/%' OR ctx LIKE '%download=1%' OR ctx LIKE '%file_id=%'))""")
con.execute("CREATE TEMP TABLE pep AS SELECT pukey, mem, count(DISTINCT sha) nb, list_sort(list_distinct(list(pfmt))) fs FROM preal GROUP BY 1,2 HAVING count(DISTINCT sha)>=2")
q("reviewer predicate: endpoints by format set (top)", "SELECT fs::VARCHAR, count(*) FROM pep GROUP BY 1 ORDER BY 2 DESC LIMIT 10")
con.execute("CREATE TEMP TABLE hp AS SELECT * FROM pep WHERE fs IN (['html','pdf'], ['html','pdf','zip'])")
q("[html,pdf] and [html,pdf,zip] endpoints: rows by format and recovery flag and fidelity and family", """
  SELECT p.pfmt, p.recovery, p.fid, p.fam, p.res, count(*), count(DISTINCT p.sha), count(DISTINCT p.pukey) FROM preal p JOIN hp ON p.pukey=hp.pukey AND p.mem IS NOT DISTINCT FROM hp.mem GROUP BY ALL ORDER BY 6 DESC""")
q("endpoints where every PDF row is a recovery import", """WITH x AS (SELECT hp.pukey, bool_and(p.recovery) FILTER (WHERE p.pfmt='pdf') pdf_all_rec, bool_or(p.recovery) FILTER (WHERE p.pfmt='html') html_any_rec
   FROM preal p JOIN hp ON p.pukey=hp.pukey AND p.mem IS NOT DISTINCT FROM hp.mem GROUP BY 1) SELECT pdf_all_rec, html_any_rec, count(*) FROM x GROUP BY ALL""")
q("example", """SELECT p.ctx[1:100], p.pfmt, p.recovery, p.fid, p.rk[1:70], p.sha[1:10] FROM preal p JOIN (SELECT * FROM hp LIMIT 3) hp ON p.pukey=hp.pukey ORDER BY 1""")
