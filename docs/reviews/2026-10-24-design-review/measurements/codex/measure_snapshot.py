from pathlib import Path
import json
import time
import duckdb
import pyarrow.parquet as pq

ROOT = Path('/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs')
con = duckdb.connect('review.duckdb')
con.execute("SET threads = 4")
con.execute("SET memory_limit = '3GB'")
con.execute("SET temp_directory = './duckdb_tmp'")
for short, name in [('c', 'captures'), ('f', 'filenames'), ('d', 'documents')]:
    con.execute(f"CREATE OR REPLACE VIEW {short} AS SELECT * FROM read_parquet('{ROOT / (name + '.parquet')}')")
con.execute(f"CREATE OR REPLACE VIEW r AS SELECT * FROM read_parquet('{ROOT / 'readings' / '*.parquet'}', union_by_name=true)")
results = {}

def q(label, sql):
    start = time.perf_counter()
    cur = con.execute(sql.replace(' rows', ' row_count'))
    rows = [dict(zip([v[0] for v in cur.description], row)) for row in cur.fetchall()]
    results[label] = {'seconds': round(time.perf_counter() - start, 3), 'rows': rows}
    print(label, json.dumps(results[label], default=str), flush=True)
    Path('snapshot_measurements.json').write_text(json.dumps(results, indent=2, default=str))

q('capture_counts', '''SELECT count(*) rows, count(distinct receipt_key) receipt_files,
   count(distinct (receipt_key, receipt_line)) receipt_lines,
   count(distinct nullif(sha256,'')) bodies, count(distinct context_url) urls,
   count(*) FILTER(WHERE sha256 IS NULL OR sha256='') bodiless_rows,
   count(*) FILTER(WHERE retrieved_at IS NULL) undated_rows FROM c''')
q('receipt_shapes', '''SELECT count(*) receipts, sum(n) capture_rows, sum(lines) receipt_lines FROM
   (SELECT receipt_key,count(*) n,count(distinct receipt_line) lines FROM c
    WHERE regexp_matches(receipt_key,'/(undated|mixed-dates)/') GROUP BY 1)''')
q('resolution', "SELECT resolution, count(*) rows FROM c GROUP BY 1 ORDER BY 2 DESC")
q('reference_kind', "SELECT reference_kind, count(*) rows FROM c GROUP BY 1 ORDER BY 2 DESC")
q('body_sizes', '''WITH b AS (SELECT sha256,max(stored_bytes) nstored,max(bytes) original,
   count(distinct stored_bytes) ns FROM c WHERE nullif(sha256,'') IS NOT NULL GROUP BY 1)
   SELECT count(*) bodies,sum(nstored) stored_bytes,sum(original) original_bytes,
   max(nstored) largest_stored,max(original) largest_original,
   count(*) FILTER(WHERE original>5000000000) above_5gb_original,
   count(*) FILTER(WHERE ns>1) conflicting_stored_sizes FROM b''')
q('body_sizes_by_media', '''WITH b AS (SELECT sha256,max(stored_bytes) nstored,max(bytes) original,
   min(media_type) media FROM c WHERE nullif(sha256,'') IS NOT NULL GROUP BY 1)
   SELECT media,count(*) bodies,sum(nstored) stored_bytes,sum(original) original_bytes
   FROM b GROUP BY 1 ORDER BY stored_bytes DESC LIMIT 20''')
q('catalog_counts', '''SELECT (SELECT count(*) FROM f) source_files,
   (SELECT count(*) FROM d) documents,
   (SELECT count(distinct (filename,source_url)) FROM f) filename_url_pairs,
   (SELECT sum(len(source_occurrences)) FROM d) occurrences,
   (SELECT max(len(source_occurrences)) FROM d) max_occurrences,
   (SELECT count(*) FROM d WHERE len(body_keys)>1) multiple_body_documents''')
q('catalog_id_uniqueness', '''SELECT count(*) rows,count(distinct source_id) ids,
    count(distinct (body_key,filename,source_url)) triples FROM f''')
q('reading_status', "SELECT status, count(*) rows FROM r GROUP BY 1 ORDER BY 2 DESC")
q('reading_formats', "SELECT body_format, record_role, count(*) rows FROM r GROUP BY 1,2 ORDER BY 3 DESC LIMIT 25")
q('member_samples', '''SELECT context_url,original_path,sha256,media_type,resolution,reference_kind
    FROM c WHERE original_path IS NOT NULL LIMIT 8''')
q('capture_day_counts', '''SELECT capture_date,count(*) rows,count(distinct(receipt_key,receipt_line)) attempts,
    count(distinct sha256) bodies FROM c GROUP BY 1 ORDER BY 1''')
q('hot_bodies', '''SELECT sha256,count(distinct context_url) urls,count(*) capture_rows,
    min(media_type) media,min(bytes) original_bytes FROM c WHERE sha256 IS NOT NULL
    GROUP BY 1 HAVING count(distinct context_url)>100 ORDER BY 2 DESC''')
q('filename_example', '''SELECT filename, source_url, source_paths, body_key,source_id,document_id,
    response_format,response_body_complete,response_result FROM f WHERE len(source_paths)>1 LIMIT 5''')

meta = json.loads(Path('snapshot_metadata.json').read_text())
print('file_metadata', json.dumps({k:{a:b for a,b in v.items() if 'schema' not in a} for k,v in meta.items()}))
for name in ('filenames', 'documents'):
    schema=pq.read_schema(ROOT / (name + '.parquet'))
    print(name+'_simple_columns', [f'{x.name}: {x.type}' for x in schema if not x.name.startswith('source_') and not 'list<' in str(x.type)])
con.close()
