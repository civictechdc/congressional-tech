import pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc, os
base='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/'
t=pq.read_table(base+'download-state.parquet')
t=t.sort_by([('url','ascending')])
def ts(c):
    a=t[c]
    return pc.cast(pc.strptime(pc.utf8_slice_codeunits(a,0,19),format='%Y-%m-%dT%H:%M:%S',unit='us'),pa.timestamp('us',tz='UTC'))
o=pa.table({'requested_url':t['url'],'attempts':pc.cast(t['attempts'],pa.int32()),
 'last_attempt':ts('checked_at'),'last_status':pc.cast(t['http_status'],pa.int16()),
 'last_outcome':pc.dictionary_encode(t['outcome']),'last_good_at':ts('retrieved_at'),'next_attempt_at':ts('next_attempt_at')})
pq.write_table(o,'out/url_state.parquet',compression='zstd',compression_level=3,use_dictionary=['last_outcome'],row_group_size=65536,data_page_version='2.0')
print(o.num_rows, os.path.getsize('out/url_state.parquet'))
md=pq.ParquetFile('out/url_state.parquet').metadata
cols=[0]*md.num_columns
for i in range(md.num_row_groups):
    for j in range(md.num_columns): cols[j]+=md.row_group(i).column(j).total_compressed_size
print(list(zip(o.column_names,cols)))
