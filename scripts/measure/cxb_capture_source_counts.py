"""Independent, read-only D1 acceptance counts; never a production ingest path.

The owner explicitly authorized DuckDB for this source-count oracle. Only small
per-receipt metrics leave SQL. JSON payload rows are neither stored nor exported.
Byte weights exclude JSONL terminators; list weights include primary references,
record candidates and secondary references before the production fanout filters.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
from time import perf_counter

import duckdb

from congress_api.lake.receipt_metadata import source_pins,recheck_source_pins


def literal(value):
    return "'"+str(value).replace("'","''")+"'"


def count_sql(counter,files):
    sources=[f'''SELECT cast(__receipt_key AS VARCHAR) AS key,
        cast(__receipt_line AS BIGINT) AS source_line,__raw_line AS raw,0 AS source_id
        FROM read_parquet({literal(counter)})''']
    for number,item in enumerate(files,1):
        sources.append(f'''SELECT {literal(item['key'])} AS key,row_number() OVER () AS source_line,
            __raw_line AS raw,{number} AS source_id FROM read_csv({literal(item['path'])},
            columns={{'__raw_line':'VARCHAR'}},header=false,delim='\x1e',quote='',escape='',
            compression='gzip',parallel=false,max_line_size=268435456,buffer_size=268435456)''')
    # This is independently expressed source arithmetic, not copied mapper SQL.
    # Distinct pointer ordinals establish coverage, not reference multiplicity.
    return '''WITH source AS NOT MATERIALIZED (
        '''+' UNION ALL '.join(sources)+'''
    ), parsed AS NOT MATERIALIZED (
        SELECT key,source_line,source_id,octet_length(encode(raw)) AS line_bytes,
            CASE WHEN json_valid(raw) AND json_type(raw)='OBJECT'
                THEN json_extract(raw,['$.record','$.captures','$.file_references'])
                ELSE error('Malformed source JSON object') END AS fields FROM source
    ), shaped AS NOT MATERIALIZED (
        SELECT key,source_line,source_id,line_bytes,
            CASE WHEN json_type(fields[1])='ARRAY' THEN json_array_length(fields[1]) ELSE 0 END AS records,
            CASE WHEN fields[2] IS NULL OR json_type(fields[2])='NULL' THEN 0
                 WHEN json_type(fields[2])='ARRAY' THEN json_array_length(fields[2])
                 ELSE error('Malformed captures list') END AS caps,
            CASE WHEN fields[3] IS NULL OR json_type(fields[3])='NULL' THEN 0
                 WHEN json_type(fields[3])='ARRAY' THEN json_array_length(fields[3])
                 ELSE error('Malformed file references list') END AS refs,
            fields[2] AS capture_list,fields[3] AS reference_list FROM parsed
    ), weighted AS NOT MATERIALIZED (
        SELECT key,source_line,source_id,line_bytes,records,caps,refs,
            CASE WHEN caps>0 THEN caps WHEN refs>0 THEN refs ELSE greatest(records,1) END AS primary_items,
            CASE WHEN caps>0 THEN capture_list WHEN refs>0 THEN reference_list ELSE '[]'::JSON END AS primary_list
        FROM shaped
    ), line_metrics AS NOT MATERIALIZED (
        SELECT key,source_line,source_id,line_bytes,
            primary_items+CASE WHEN caps+refs>0 THEN records ELSE 0 END
                +CASE WHEN caps>0 THEN refs ELSE 0 END AS items,
            primary_items+CASE WHEN records>0 AND caps+refs>0 THEN records-len(list_distinct(
                list_filter(list_transform(json_extract(primary_list,'$[*]'),
                    p->coalesce(try_cast(json_extract_string(p,'$.pointer[0]') AS BIGINT),
                        try_cast(json_extract_string(p,'$.pointer[1]') AS BIGINT),0)),
                    i->i>=0 AND i<records))) ELSE 0 END AS expected_captures
        FROM weighted
    ) SELECT key,count(*) AS source_rows,sum(line_bytes)::BIGINT AS uncompressed_bytes,
        sum(items)::BIGINT AS list_items,sum(expected_captures)::BIGINT AS expected_captures,
        max(line_bytes)::BIGINT AS max_line_bytes,max(items)::BIGINT AS max_line_items,
        min(source_line) AS first_line,max(source_line) AS last_line,
        count(DISTINCT source_line) AS distinct_lines,count(DISTINCT source_id) AS source_origins,
        min(source_id) AS source_id
        FROM line_metrics GROUP BY key ORDER BY key'''


def count_sources(*,counter,files,receipt_keys,work,source_qualifications,memory_bytes=2<<30,threads=1):
    """Return complete per-receipt counts, refusing missing or malformed sources."""
    if (type(memory_bytes) is not int or memory_bytes<=0 or type(threads) is not int or not 1<=threads<=4):
        raise ValueError('Independent counts require positive memory and at most four threads')
    keys=list(receipt_keys)
    if (not keys or any(not isinstance(k,str) or not k.startswith('receipts/') for k in keys)
            or len(keys)!=len(set(keys))):
        raise ValueError('Receipt inventory requires unique original keys')
    counter=Path(counter).absolute()
    files=[dict(key=f.get('key',f.get('receipt_key')),path=str(Path(f['path']).absolute())) for f in files]
    file_keys=[f['key'] for f in files]
    if len(file_keys)!=len(set(file_keys)) or set(file_keys)-set(keys):
        raise ValueError('Direct receipt inputs must have unique selected keys')
    paths={str(counter),*(f['path'] for f in files)}
    if set(map(str,source_qualifications))!=paths:
        raise ValueError('Source qualifications must bind exactly the original inputs')
    pins=source_pins(counter=counter,qualifications={str(counter):source_qualifications[str(counter)]})
    if files:
        pins+=source_pins(files=files,qualifications={f['path']:source_qualifications[f['path']] for f in files})
    if 'rows' not in pins[0]['qualification']:
        raise ValueError('Independent counts need the qualified counter creation row count')
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    sql=count_sql(counter,files);(work/'counts.sql').write_text(sql+'\n')
    config=dict(threads=str(threads),memory_limit=str(memory_bytes)+'B',
        temp_directory=str(work/'spill'),max_temp_directory_size='512MiB',
        autoinstall_known_extensions='false',autoload_known_extensions='false')
    started=perf_counter()
    try:
        with duckdb.connect(config=config) as connection:
            cursor=connection.execute(sql)
            columns=[c[0] for c in cursor.description]
            rows=[dict(zip(columns,r)) for r in cursor.fetchall()]
    except duckdb.Error:
        raise ValueError('Malformed or invalid source, or independent count resource refusal; see saved SQL') from None
    recheck_source_pins(pins)
    if {r['key'] for r in rows}!=set(keys):
        raise ValueError('Counted receipt keys differ from the complete original receipt inventory')
    source_rows=defaultdict(int)
    for row in rows:
        if (row['source_origins']!=1 or row['first_line']!=1 or row['last_line']!=row['source_rows']
                or row['distinct_lines']!=row['source_rows']):
            raise ValueError('Invalid receipt source lines or duplicate original receipt keys')
        source_rows[row['source_id']]+=row['source_rows']
    rows_by_path={str(counter):source_rows[0],**{f['path']:source_rows[i] for i,f in enumerate(files,1)}}
    if any(rows_by_path[p['path']]!=p['qualification']['rows'] for p in pins if 'rows' in p['qualification']):
        raise ValueError('Source rows differ from qualified original creation counts')
    public=('key','source_rows','uncompressed_bytes','list_items','expected_captures','max_line_bytes','max_line_items')
    result=[{k:r[k] for k in public} for r in rows]
    recheck_source_pins(pins)
    (work/'metrics.json').write_text(json.dumps(dict(seconds=perf_counter()-started,
        duckdb_version=duckdb.__version__,config=config,sources=pins,receipts=len(result),
        expected_captures=sum(r['expected_captures'] for r in result)),indent=2)+'\n')
    (work/'counts.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('counter','files','receipt-inventory','source-qualifications','work'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--memory-bytes',type=int,default=2<<30)
    parser.add_argument('--threads',type=int,default=1)
    args=parser.parse_args(argv)
    inventory=json.loads(args.receipt_inventory.read_text())
    rows=count_sources(counter=args.counter,files=json.loads(args.files.read_text()),
        receipt_keys=[r if isinstance(r,str) else r['key'] for r in inventory],work=args.work,
        source_qualifications=json.loads(args.source_qualifications.read_text()),
        memory_bytes=args.memory_bytes,threads=args.threads)
    print(json.dumps(dict(receipts=len(rows),expected_captures=sum(r['expected_captures'] for r in rows))))
    return 0


if __name__=='__main__':raise SystemExit(main())
