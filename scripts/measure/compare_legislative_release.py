#!/usr/bin/env python3
"""Compare every released legislative detail row to its exact pinned upstream row.

The native producer is not imported. SHA-256 row digests preserve multiplicity;
positive differences are missing source rows and negative differences are added
release rows. DuckDB spills bounded aggregation state to the supplied work path.
Run under archive_watchdog, and retain the JSON report beside the release evidence.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import duckdb
import pyarrow.parquet as pq


def quoted(name):
    return '"'+name.replace('"','""')+'"'


def literal(value):
    return "'"+str(value).replace("'","''")+"'"


def compare(manifest, release, work):
    manifest,release,work=Path(manifest),Path(release),Path(work)
    pin=json.loads(manifest.read_text());work.mkdir(parents=True,exist_ok=True)
    db=duckdb.connect(config=dict(memory_limit='256MB',threads=2,temp_directory=str(work),max_temp_directory_size='4GB'))
    report=dict(manifest=str(manifest),manifest_sha256=sha256(manifest.read_bytes()).hexdigest(),release=str(release),relations={})
    try:
        for name,family in [('bill_actions','bill-family'),('roll_call_votes','roll-call-votes'),('member_votes','roll-call-votes')]:
            selected=pin['tables']['spicy_'+name];source=manifest.parent/selected['path'];target=release/(name+'.parquet')
            columns=pq.read_schema(source).names
            source_fields=','.join(quoted(key)+':='+quoted(key) for key in columns)
            expected=source_fields+',source_generation:='+literal(pin['generations'][family])+',source_reference:='+literal(selected['path'])
            actual=source_fields+',source_generation:=source_generation,source_reference:=source_reference'
            sql=f"""WITH row_changes AS (
                SELECT unhex(sha256(to_json(struct_pack({expected})))) AS fingerprint,1 AS change FROM read_parquet({literal(source)})
                UNION ALL
                SELECT unhex(sha256(to_json(struct_pack({actual})))) AS fingerprint,-1 AS change FROM read_parquet({literal(target)})
              ), difference AS (SELECT fingerprint,sum(change) AS change FROM row_changes GROUP BY fingerprint HAVING sum(change)<>0)
              SELECT coalesce(sum(CASE WHEN change>0 THEN change ELSE 0 END),0)::BIGINT AS missing,
                coalesce(sum(CASE WHEN change<0 THEN -change ELSE 0 END),0)::BIGINT AS added FROM difference"""
            missing,added=db.execute(sql).fetchone()
            source_rows=pq.read_metadata(source).num_rows;released_rows=pq.read_metadata(target).num_rows
            report['relations'][name]=dict(source=selected['path'],generation=pin['generations'][family],source_rows=source_rows,
                released_rows=released_rows,missing_rows=missing,added_rows=added,match=missing==added==0 and source_rows==released_rows)
    finally:db.close()
    report['match']=all(r['match'] for r in report['relations'].values())
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path,required=True)
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();result=compare(args.source_manifest,args.release,args.work)
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return 0 if result['match'] else 1


if __name__=='__main__':raise SystemExit(main())
