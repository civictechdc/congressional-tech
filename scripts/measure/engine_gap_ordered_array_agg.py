"""Engine gap: a regexp CASE in named_struct in an ordered array_agg took 20 GiB RSS on 3,000 synthetic rows at a 1 GiB pool.

    guard.py --rss-gb 3 -- python engine_gap_ordered_array_agg.py ROWS blow|noorder|preprojected SCRATCH

Measured: blow 3000 stopped at 20.4 GiB; blow 300, noorder 3000 and preprojected 3000 finish in about 0.1 s.
"""
import json,sys,shutil,time
from pathlib import Path
H=Path(sys.argv[3]).resolve()  # Directory holding a runtime.json with a low memory limit
import pyarrow as pa,pyarrow.parquet as pq
from docspec_client.client import NativeDatasets
rows=int(sys.argv[1]);variant=sys.argv[2]
work=H/'repro-work';shutil.rmtree(work,ignore_errors=True);work.mkdir()
st=pa.struct([('system_code',pa.string()),('name',pa.string()),('chamber',pa.string()),('role',pa.string())])
data=[[dict(system_code=f'{"hs" if i%3 else "HS"}{"cn" if i%2 else "ag"}{i%100:02d}',name='Committee on Things '*3,chamber='house',role='host')] for i in range(rows)]
tb=pa.table(dict(event_id=pa.array(range(rows),pa.int64()),raw=pa.array(data,pa.list_(st))))
pq.write_table(tb,work/'t.parquet')
CASE="CASE WHEN lower(c['system_code'])='hszt00' THEN 'htzt00' WHEN regexp_like(lower(c['system_code']),'^hs(?:cn|ef|fd|gw|hk|ie|ig|ij|mh|qj|rk|vc|zi|zs)[0-9]{2}$') THEN 'hl'||substr(lower(c['system_code']),3) ELSE lower(c['system_code']) END"
R="SELECT event_id,unnest(raw) AS c,unnest(range(0,cast(array_length(raw) AS BIGINT))) AS idx FROM t"
Q=dict(blow=f"WITH r AS ({R}) SELECT event_id,array_agg(named_struct('system_code',{CASE},'role',c['role']) ORDER BY idx) AS a FROM r WHERE c['system_code'] IS NOT NULL GROUP BY event_id",
 noorder=f"WITH r AS ({R}) SELECT event_id,array_agg(named_struct('system_code',{CASE},'role',c['role'])) AS a FROM r WHERE c['system_code'] IS NOT NULL GROUP BY event_id",
 preprojected=f"WITH r AS ({R}),p AS (SELECT event_id,idx,c['role'] AS role,{CASE} AS s FROM r WHERE c['system_code'] IS NOT NULL) SELECT event_id,array_agg(named_struct('system_code',s,'role',role) ORDER BY idx) AS a FROM p GROUP BY event_id")
job=dict(scratch=str(work/'n'),inputs=[dict(name='t',kind='parquet',path=str(work/'t.parquet'))],steps=[dict(name='p',sql=Q[variant],materialize=True)],outputs=[],queries=[dict(name='n',sql='SELECT count(*) AS n FROM p')])
(work/'j.json').write_text(json.dumps(job));t=time.time()
with NativeDatasets.from_config(H/'runtime.json') as e:
    r=e.run_job(work/'j.json')
print(variant,rows,round(time.time()-t,2),r['queries'][0]['data'])
shutil.rmtree(work)
