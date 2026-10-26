"""F3 part 2: same-stem rendition groups (DM 7.5 rule b) on this folder's real files (vm7 proxy) and effective filenames.
Effective filename proxy (DM 7.4 steps 2,5,6; no download header or filename parameter in the snapshot): member basename, else the final
URL's last path segment, percent-decoded once. Variant: the old catalog's filename for the (body, source URL).
Directory: host+path up to the last '/', or container URL + member path up to its last '/'. Formats: pdf, html, xml, doc, docx, text.
Generic stems: index, download, default, document, file. edition_bodies: bodies at endpoints holding >=2 distinct real bodies (upper bound:
fingerprints unknown), WARC excluded (F1 fix) and included (as the DM reads today). Publisher groups are not computable (no links), so (b) is
counted over all real files: an upper bound on (b)."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
def q(l,s):
    rows=con.execute(s).fetchall(); print(f'\n## {l}')
    for r in rows[:20]: print('  ',r)
con.execute("""CREATE TEMP TABLE sf AS SELECT DISTINCT sha, fmt, ctx, mem,
   url_decode(CASE WHEN mem IS NOT NULL THEN regexp_extract(mem,'([^/]*)$',1) ELSE regexp_extract(regexp_replace(ctx,'[?#].*$',''),'([^/]*)$',1) END) fname,
   CASE WHEN mem IS NOT NULL THEN ctx || '!' || regexp_replace(mem,'[^/]*$','') ELSE regexp_replace(regexp_replace(regexp_replace(ctx,'[?#].*$',''),'^[a-z]+://',''),'[^/]*$','') END dir
   FROM real WHERE fmt IN ('pdf','html','xml','doc','docx','text')""")
con.execute(f"""CREATE TEMP TABLE oldname AS SELECT regexp_extract(body_key,'([0-9a-f]{{64}})',1) sha, source_url, any_value(filename) filename
   FROM read_parquet('{B}filenames.parquet') WHERE filename IS NOT NULL GROUP BY 1,2""")
for amb_name, amb in [('edition_bodies=0 (fingerprints all equal)', "SELECT NULL::VARCHAR sha WHERE false"),
                      ('edition_bodies upper bound, WARC excluded', "SELECT DISTINCT r.sha FROM real r JOIN (SELECT ctx, mem FROM real WHERE fmt<>'warc' GROUP BY 1,2 HAVING count(DISTINCT sha)>=2) e ON r.ctx=e.ctx AND r.mem IS NOT DISTINCT FROM e.mem WHERE r.fmt<>'warc'"),
                      ('edition_bodies upper bound, WARC included (DM as written)', "SELECT DISTINCT r.sha FROM real r JOIN (SELECT ctx, mem FROM real GROUP BY 1,2 HAVING count(DISTINCT sha)>=2) e ON r.ctx=e.ctx AND r.mem IS NOT DISTINCT FROM e.mem")]:
    con.execute(f"CREATE OR REPLACE TEMP TABLE amb AS {amb}")
    for nm_name, nm in [('URL/member name', 'fname'), ('old catalog filename', "coalesce(CASE WHEN sf.mem IS NULL THEN o.filename END, fname)")]:
        con.execute(f"""CREATE OR REPLACE TEMP TABLE st AS SELECT sf.sha, sf.fmt, sf.dir, CASE WHEN {nm} LIKE '%.%' THEN regexp_replace({nm},'\\.[^.]*$','') ELSE {nm} END stem,
            a.sha IS NOT NULL is_amb
            FROM sf LEFT JOIN oldname o ON o.sha=sf.sha AND o.source_url=sf.ctx LEFT JOIN (SELECT DISTINCT sha FROM amb) a ON a.sha=sf.sha""")
        con.execute("""CREATE OR REPLACE TEMP TABLE gg AS SELECT dir, stem, count(DISTINCT fmt) nf_all, list_sort(list_distinct(list(fmt))) fs,
              count(DISTINCT sha) FILTER (WHERE NOT is_amb) nb_rem, count(DISTINCT fmt) FILTER (WHERE NOT is_amb) nf_rem
            FROM st WHERE lower(stem) NOT IN ('index','download','default','document','file','') GROUP BY 1,2 HAVING count(DISTINCT fmt)>=2""")
        q(f"[{amb_name}; {nm_name}] (dir, stem) groups with >=2 formats; drawing edges (one body per format, >=2 left); bodies joined; refused (2 bodies of one format); lost to edition_bodies",
          "SELECT count(*), count(*) FILTER (WHERE nb_rem=nf_rem AND nf_rem>=2), sum(nb_rem) FILTER (WHERE nb_rem=nf_rem AND nf_rem>=2), count(*) FILTER (WHERE nb_rem>nf_rem), count(*) FILTER (WHERE nf_rem<2) FROM gg")
q("[last variant] edge groups by host and format set", "SELECT regexp_extract(dir,'^([^/!]+)',1) h, fs::VARCHAR, count(*) FROM gg WHERE nb_rem=nf_rem AND nf_rem>=2 GROUP BY ALL ORDER BY 3 DESC LIMIT 12")
