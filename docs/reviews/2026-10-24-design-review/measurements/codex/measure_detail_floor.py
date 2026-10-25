from pathlib import Path
import json
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

root=Path('/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs')
con=duckdb.connect()
con.execute("SET threads=4")
con.execute("SET memory_limit='2GB'")
con.execute("SET temp_directory='./detail_tmp'")
rows=con.execute(f"""SELECT document_id, body_key FROM read_parquet('{root/'documents.parquet'}')
 WHERE body_key IS NOT NULL AND length(body_key)>0
 ORDER BY filename NULLS LAST,document_id LIMIT 650000""").fetchall()
keys=[row[1] for row in rows]
hashes=[key.rsplit('/',1)[-1].split('.',1)[0] for key in keys]
table=pa.table({
 'link_key':pa.array([bytes.fromhex(v[:16]) for v in hashes],type=pa.binary(8)),
 'saved_key':pa.array(keys),
 'fields':pa.array([[{'field':'document_id','value':row[0]}] for row in rows],
                  type=pa.list_(pa.struct([('field',pa.string()),('value',pa.string())])))})
pq.write_table(table,'detail_three_keys.parquet',row_group_size=65536,
 compression='zstd',compression_level=3,data_page_version='2.0',
 data_page_size=16384,write_batch_size=1024,write_page_index=True,
 use_dictionary=['fields.list.element.field'])
p=pq.ParquetFile('detail_three_keys.parquet')
sizes={}
for i in range(p.metadata.num_row_groups):
 rg=p.metadata.row_group(i)
 for j in range(rg.num_columns):
  col=rg.column(j)
  sizes[col.path_in_schema]=sizes.get(col.path_in_schema,0)+col.total_compressed_size
result={'kind':'proxy, not the target release: sorted existing catalog rows with a body key; first 650000',
 'rows':len(rows),'bytes':Path('detail_three_keys.parquet').stat().st_size,
 'column_compressed_bytes':sizes,
 'contains':'only link_key, saved_key and the folded document_id; no other detail facts',
 'schema':str(table.schema), 'pyarrow_version':pa.__version__}
Path('detail_floor_measurements.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
