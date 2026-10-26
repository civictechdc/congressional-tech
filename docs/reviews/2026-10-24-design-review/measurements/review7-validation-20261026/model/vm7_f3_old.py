"""F3 part 1: reproduce 'about 16,000 groups split across about 32,500 documents' on the old catalog (filenames.parquet source files):
(dir, stem) with >=2 formats whose source files sit in >=2 old documents. Then attribute the docs.house.gov .xml side."""
import duckdb
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
con=duckdb.connect(); con.execute("SET threads=6")
def q(l,s):
    rows=con.execute(s).fetchall(); print(f'\n## {l}')
    for r in rows[:20]: print('  ',r)
con.execute(f"""CREATE TABLE f AS SELECT body_key, filename, source_url, document_id, lower(coalesce(format[1],'')) fmt0,
   regexp_replace(regexp_replace(source_url,'[?#].*$',''),'/[^/]*$','') dir,
   CASE WHEN filename LIKE '%.%' THEN regexp_replace(filename,'\\.[^.]*$','') ELSE filename END stem,
   lower(regexp_extract(filename,'\\.([A-Za-z0-9]+)$',1)) ext, http_status
   FROM read_parquet('{B}filenames.parquet') WHERE source_url IS NOT NULL AND source_url<>'' AND document_id IS NOT NULL""")
con.execute("""CREATE TABLE g AS SELECT dir, stem, count(DISTINCT fmt0) nf, count(DISTINCT document_id) nd, list_sort(list_distinct(list(fmt0))) fs FROM f
   WHERE fmt0 IN ('pdf','html','xml','docx','doc','txt','text') AND lower(stem) NOT IN ('index','download','default','document','file','')
   GROUP BY 1,2 HAVING count(DISTINCT fmt0)>=2 AND count(DISTINCT document_id)>=2""")
q("old catalog: (dir, stem) groups with >=2 formats split over >=2 documents: groups, documents", "SELECT count(*), sum(nd) FROM g")
q("by host", "SELECT regexp_extract(dir,'^https?://([^/]+)',1) h, count(*), sum(nd) FROM g GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
q("by format set", "SELECT fs::VARCHAR, count(*), sum(nd) FROM g GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
q("docs.house.gov groups: the xml side's body (distinct bodies; how many groups share the single most common xml body)", """
  WITH x AS (SELECT f.body_key FROM f JOIN g USING (dir, stem) WHERE g.dir LIKE '%docs.house.gov%' AND f.fmt0='xml')
  SELECT count(*), count(DISTINCT body_key), (SELECT count(*) FROM x WHERE body_key=(SELECT mode(body_key) FROM x)) top_body_rows, (SELECT mode(body_key) FROM x) FROM x""")
q("docs.house.gov groups: xml side's old http_status values", """SELECT f.http_status::VARCHAR, count(*) FROM f JOIN g USING (dir, stem) WHERE g.dir LIKE '%docs.house.gov%' AND f.fmt0='xml' GROUP BY 1 ORDER BY 2 DESC LIMIT 5""")
q("docs.house.gov [html, pdf] groups: the html side's filename extension, old status, and how many share one body", """
  WITH x AS (SELECT f.* FROM f JOIN g USING (dir, stem) WHERE g.dir LIKE '%docs.house.gov%' AND g.fs=['html','pdf'] AND f.fmt0='html')
  SELECT ext, http_status::VARCHAR, count(*), count(DISTINCT body_key), max(n) FROM (SELECT *, count(*) OVER (PARTITION BY body_key) n FROM x) GROUP BY ALL ORDER BY 3 DESC LIMIT 6""")
q("same, the top shared html body: rows and its capture status in the snapshot", f"""
  WITH x AS (SELECT f.body_key FROM f JOIN g USING (dir, stem) WHERE g.dir LIKE '%docs.house.gov%' AND g.fs=['html','pdf'] AND f.fmt0='html'),
       t AS (SELECT mode(body_key) k FROM x)
  SELECT (SELECT count(*) FROM x, t WHERE x.body_key=t.k), (SELECT list(DISTINCT http_status) FROM read_parquet('{B}captures.parquet') c, t WHERE c.body_key=t.k), (SELECT count(*) FROM read_parquet('{B}captures.parquet') c, t WHERE c.body_key=t.k)""")
