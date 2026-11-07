"""Small independent decoder cases, not native archive qualification fixtures."""
from decimal import Decimal
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
schema = pa.schema([
    ('id', pa.int64()), ('floating', pa.float64()), ('day', pa.date32()),
    ('micros', pa.timestamp('us', tz='UTC')), ('nanos', pa.timestamp('ns')),
    ('binary', pa.binary()), ('fixed', pa.binary(4)), ('labels', pa.list_(pa.string())),
    ('date_struct', pa.struct([('type', pa.string()), ('days', pa.int32())])),
    ('nested', pa.struct([('clock', pa.struct([
        ('type', pa.string()), ('unit', pa.string()), ('value', pa.int64())]))])),
    ('row', pa.int32()), ('fileRow', pa.int32()),
])
arrays = [
    pa.array([9007199254740993, -9007199254740993, 0], type=pa.int64()),
    pa.array([-0.0, float('nan'), float('inf')], type=pa.float64()),
    pa.array([-1, 0, 1], type=pa.date32()),
    pa.array([1700000000000001, -1, 0], type=pa.timestamp('us', tz='UTC')),
    pa.array([1700000000000000001, -1, 0], type=pa.timestamp('ns')),
    pa.array([b'\x00\x80\xff', b'', None], type=pa.binary()),
    pa.array([b'\x00\x01\x02\x03', b'\xff\x00\x00\x80', None], type=pa.binary(4)),
    pa.array([['one', None], [], None], type=pa.list_(pa.string())),
    pa.array([{'type': 'date', 'days': 3}, None, {'type': 'other', 'days': None}], type=schema.field('date_struct').type),
    pa.array([{'clock': {'type': 'timestamp', 'unit': 'us', 'value': 7}}, {'clock': None}, None], type=schema.field('nested').type),
    pa.array([99, 98, 97], type=pa.int32()), pa.array([88, 87, 86], type=pa.int32()),
]
pq.write_table(pa.Table.from_arrays(arrays, schema=schema), ROOT/'raw_rows.parquet',
               compression='snappy', row_group_size=2, use_dictionary=False, write_page_index=True)
pq.write_table(pa.table({'amount': pa.array([Decimal('9007199254740993.123456789012345678')],
                   type=pa.decimal128(38, 18))}), ROOT/'raw_decimal.parquet', compression='snappy')
pq.write_table(pa.table({'id': range(4096), 'text': ['repeated']*4096}), ROOT/'raw_group.parquet',
               compression='snappy', use_dictionary=False, row_group_size=4096)
nested_type = pa.int64()
for _ in range(6):
    nested_type = pa.list_(nested_type)
values = []
for i in range(512):
    value = i
    for _ in range(5):
        value = [value]
    values.append(value)
pq.write_table(pa.table({'nested': pa.array([values], type=nested_type)}),
               ROOT/'raw_nested.parquet', compression='snappy', use_dictionary=False)
pq.write_table(pa.table({'outer': pa.array([{'a.b': 'literal', 'a': {'b': 'nested'}}],
    type=pa.struct([('a.b', pa.string()), ('a', pa.struct([('b', pa.string())]))]))}),
    ROOT/'raw_dotted.parquet', compression='snappy')
metadata = {}
for name in ('raw_rows.parquet', 'raw_decimal.parquet', 'raw_group.parquet', 'raw_nested.parquet', 'raw_dotted.parquet'):
    file = pq.ParquetFile(ROOT/name)
    metadata[name] = {'rows': file.metadata.num_rows, 'groups': []}
    for index in range(file.metadata.num_row_groups):
        group = file.metadata.row_group(index)
        metadata[name]['groups'].append({'rows': group.num_rows, 'columns': [
            {'dataOffset': group.column(i).data_page_offset,
             'compressedBytes': group.column(i).total_compressed_size,
             'uncompressedBytes': group.column(i).total_uncompressed_size,
             'values': group.column(i).num_values}
            for i in range(group.num_columns)]})
(ROOT/'raw_rows_cases.json').write_text(json.dumps(metadata, indent=2)+'\n')
print(json.dumps({name: {'bytes': (ROOT/name).stat().st_size, 'rows': item['rows']}
                  for name, item in metadata.items()}))
