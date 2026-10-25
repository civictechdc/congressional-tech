from pathlib import Path
import json
import pyarrow.parquet as pq

ROOT = Path('/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs')
result = {}
for name in ('captures', 'filenames', 'documents'):
    path = ROOT / (name + '.parquet')
    p = pq.ParquetFile(path)
    result[name] = {'rows': p.metadata.num_rows, 'bytes': path.stat().st_size,
                    'row_groups': p.metadata.num_row_groups, 'schema': str(p.schema_arrow)}
files = sorted((ROOT / 'readings').glob('*.parquet'))
result['readings'] = {'files': len(files), 'rows': sum(pq.read_metadata(p).num_rows for p in files),
                      'bytes': sum(p.stat().st_size for p in files),
                      'sample_schema': str(pq.ParquetFile(files[0]).schema_arrow)}
Path('snapshot_metadata.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
