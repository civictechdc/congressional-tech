"""F7: find the predicates behind (a) ARCHITECTURE 16 'the most real files at one address being 50' and (b) DM 7.10 '1,695,040 occurrences;
its largest listed document has 27', by computing candidate predicates on the old catalog and on this folder's real-file proxy."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True); con.execute("SET threads=6")
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
DOC=f"read_parquet('{B}documents.parquet')"; FN=f"read_parquet('{B}filenames.parquet')"
def q(l,s):
    rows=con.execute(s).fetchall(); print(f'\n## {l}')
    for r in rows[:12]: print('  ',r)
q("(b) old catalog documents: candidate occurrence counts (sum, max)", f"""SELECT
  sum(len(source_urls)), max(len(source_urls)),
  sum(len(source_paths)), max(len(source_paths)),
  sum(len(filenames)), max(len(filenames)),
  sum(len(body_keys)), max(len(body_keys)),
  sum(len(source_occurrences)), max(len(source_occurrences)) FROM {DOC}""")
q("(b) filenames rows per document_id: total, max", f"SELECT count(*), max(n) FROM (SELECT document_id, count(*) n FROM {FN} GROUP BY 1)")
q("(b) filenames rows x source_paths (one row per (source file, path)): total, max per document", f"""SELECT sum(n), max(n) FROM (SELECT document_id, sum(greatest(coalesce(len(source_paths),0),1)) n FROM {FN} GROUP BY 1)""")
q("(b) distinct (source_id, path) per document: total, max", f"""WITH x AS (SELECT document_id, source_id, unnest(CASE WHEN len(source_paths)>0 THEN source_paths ELSE [NULL] END) p FROM {FN})
   SELECT sum(n), max(n) FROM (SELECT document_id, count(DISTINCT (source_id, p)) n FROM x GROUP BY 1)""")
q("(b) the documents with most occurrence structs and most distinct capture URLs", f"""SELECT len(source_occurrences) n_struct, len(list_distinct(flatten(list_transform(source_occurrences, o -> o.source_capture_url)))) n_capurl,
   len(source_urls), len(filenames), len(body_keys), filename[1:50], format::VARCHAR FROM {DOC} ORDER BY 1 DESC LIMIT 5""")
q("(b) max distinct capture URLs over documents", f"""SELECT max(len(list_distinct(flatten(list_transform(source_occurrences, o -> o.source_capture_url))))) FROM {DOC}""")
# (a)
q("(a) top-level URLs: max distinct real bodies at one source URL (proxy)", "SELECT max(n) FROM (SELECT ctx, count(DISTINCT sha) n FROM real WHERE mem IS NULL GROUP BY 1)")
q("(a) top-level URLs: max distinct real source files (body, URL-derived name) at one source URL; also old catalog source files per source_url", f"""SELECT
   (SELECT max(n) FROM (SELECT ctx, count(DISTINCT sha) n FROM real WHERE mem IS NULL GROUP BY 1)),
   (SELECT max(n) FROM (SELECT source_url, count(*) n FROM {FN} WHERE source_url<>'' GROUP BY 1))""")
q("(a) container addresses: max distinct real member files (sha, member path) in one archive URL, plus the container itself", """
   SELECT ctx, count(DISTINCT (sha, mem)) n_member_files, count(DISTINCT sha) n_member_bodies FROM real WHERE mem IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 5""")
q("(a) container addresses: distinct real member files by member basename (DM 7.4 grain: body + name)", """
   SELECT ctx, count(DISTINCT (sha, regexp_extract(mem,'([^/]*)$',1))) n FROM real WHERE mem IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 5""")
q("(a) the member endpoint with many bodies (one member path, many bodies)", "SELECT ctx, mem, count(DISTINCT sha) FROM real WHERE mem IS NOT NULL GROUP BY 1,2 HAVING count(DISTINCT sha)>=2 ORDER BY 3 DESC LIMIT 3")
U='https://www.govinfo.gov/content/pkg/CHRG-117hhrg44535.zip'
q("(a) CHRG-117hhrg44535.zip: source files at the address by kind (all rows with a body, any role), and real ones", f"""
   SELECT mem IS NULL is_container, fmt, role, count(DISTINCT (sha, coalesce(mem,''))) all_files, count(DISTINCT (sha, coalesce(mem,''))) FILTER (WHERE id IN (SELECT id FROM real)) real_files
   FROM c WHERE ctx='{U}' AND sha IS NOT NULL GROUP BY ALL ORDER BY 1,2""")
q("(a) max over addresses of: distinct (body, member path) source files with a body at that context URL (any role, good or not)", """
   SELECT ctx, count(DISTINCT (sha, coalesce(mem,''))) n FROM c WHERE sha IS NOT NULL AND ctx IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 4""")
q("(a) same, good fetches only, any role", """SELECT ctx, count(DISTINCT (sha, coalesce(mem,''))) n FROM c WHERE coalesce(good,false) AND ctx IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 4""")
q("(a) same, real files plus the container's source records (all members + container, good)", f"""SELECT ctx, count(DISTINCT (sha, coalesce(mem,''))) n FROM c WHERE coalesce(good,false) AND ctx IS NOT NULL AND (id IN (SELECT id FROM real) OR role='source_record') GROUP BY 1 ORDER BY 2 DESC LIMIT 3""")
q("(b) old catalog: top documents by distinct (source_id, path), with filename and format", f"""WITH x AS (SELECT document_id, source_id, unnest(CASE WHEN len(source_paths)>0 THEN source_paths ELSE [NULL] END) p FROM {FN}),
   n AS (SELECT document_id, count(DISTINCT (source_id, p)) n FROM x GROUP BY 1)
   SELECT n.n, d.filename[1:45], d.format::VARCHAR, len(d.body_keys) FROM n JOIN {DOC} d USING (document_id) ORDER BY 1 DESC LIMIT 12""")
q("(b) old catalog: top documents by distinct (source_id, path) excluding documents whose bodies include a >100-URL placeholder or a non-2xx-only body", f"""
   WITH x AS (SELECT document_id, source_id, body_key, unnest(CASE WHEN len(source_paths)>0 THEN source_paths ELSE [NULL] END) p FROM {FN}),
        bad AS (SELECT DISTINCT 'bodies/sha256/'||substr(sha,1,2)||'/'||sha||'.gz' bk FROM placeholders),
        n AS (SELECT document_id, count(DISTINCT (source_id, p)) n, bool_or(body_key IN (SELECT bk FROM bad)) ph FROM x GROUP BY 1)
   SELECT n.n, d.filename[1:45], d.format::VARCHAR FROM n JOIN {DOC} d USING (document_id) WHERE NOT ph ORDER BY 1 DESC LIMIT 6""")
