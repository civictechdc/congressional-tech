"""F1: WARC rows in the snapshot captures table: where they come from, their status, and whether their line also stores the payload."""
import duckdb, os, time
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
M='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/'
con=duckdb.connect(); con.execute("SET threads=6")
def q(l,s):
    t=time.time(); rows=con.execute(s).fetchall(); print(f'\n## {l}  ({time.time()-t:.1f}s)')
    for r in rows[:40]: print('  ',r)
    return rows
con.execute(f"CREATE VIEW c AS SELECT * FROM read_parquet('{B}captures.parquet')")
q("captures columns sample row (WARC)", "SELECT * FROM c WHERE media_type ILIKE '%arc+gzip%' LIMIT 2")
q("WARC rows: media_type, family, reference_kind, pointer_json, http_status, resolution, fidelity", """SELECT media_type, family, reference_kind, pointer_json, http_status, resolution, fidelity, count(*), count(DISTINCT sha256), round(sum(bytes)/1e9,3) FROM c WHERE media_type ILIKE '%arc+gzip%' OR pointer_json ILIKE '%warc%' OR pointer_json ILIKE '%raw_arc%' GROUP BY ALL ORDER BY 8 DESC""")
q("WARC rows: receipt key prefixes", "SELECT regexp_extract(receipt_key,'^(receipts/[^/]+/[^/]+/[^/]+)',1) p, count(*), count(DISTINCT receipt_key) FROM c WHERE media_type ILIKE '%arc+gzip%' GROUP BY 1 ORDER BY 2 DESC LIMIT 20")
rows=q("distinct WARC receipt keys", "SELECT DISTINCT receipt_key FROM c WHERE media_type ILIKE '%arc+gzip%'")
have=sum(os.path.exists(M+r[0]) for r in rows); print('   WARC receipt keys present in mirror:', have, 'of', len(rows))
q("WARC line siblings: rows in the same (receipt_key, receipt_line) by pointer and media class and status",
  """WITH w AS (SELECT DISTINCT receipt_key, receipt_line FROM c WHERE media_type ILIKE '%arc+gzip%')
     SELECT c.pointer_json, CASE WHEN media_type ILIKE '%arc+gzip%' THEN 'warc' WHEN media_type ILIKE '%pdf%' THEN 'pdf' WHEN media_type ILIKE '%html%' THEN 'html' ELSE coalesce(media_type,'NULL') END mt,
            CASE WHEN http_status BETWEEN 200 AND 299 THEN '2xx' WHEN http_status IS NULL THEN 'null' ELSE 'other' END st, count(*), count(DISTINCT sha256)
     FROM c JOIN w USING (receipt_key, receipt_line) GROUP BY ALL ORDER BY 4 DESC LIMIT 20""")
q("WARC lines: number of sibling body rows (non-WARC) per line",
  """WITH w AS (SELECT receipt_key, receipt_line, count(*) FILTER (WHERE media_type ILIKE '%arc+gzip%') nw, count(*) FILTER (WHERE NOT media_type ILIKE '%arc+gzip%' OR media_type IS NULL) nother, count(*) FILTER (WHERE sha256 IS NOT NULL AND NOT coalesce(media_type,'') ILIKE '%arc+gzip%') nbody FROM c GROUP BY 1,2 HAVING count(*) FILTER (WHERE media_type ILIKE '%arc+gzip%')>0)
     SELECT nw, nother, nbody, count(*) FROM w GROUP BY ALL ORDER BY 4 DESC""")
