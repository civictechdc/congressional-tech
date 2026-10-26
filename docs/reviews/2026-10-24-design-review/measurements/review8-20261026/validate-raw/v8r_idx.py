import pyarrow.parquet as pq, sys
I='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/'
for n in ['captures','documents','document-filenames','download-state']:
    f=pq.ParquetFile(I+n+'.parquet'); print(n, f.metadata.num_rows); print('  ',[ (x.name, str(x.type)) for x in f.schema_arrow][:40])
