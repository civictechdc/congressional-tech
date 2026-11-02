"""Engine gap: a computed THEN branch in CASE inside named_struct in an ordered array_agg exceeds the pool.

    guard.py --rss-gb 3 -- python engine_gap_ordered_array_agg.py ROWS VARIANT

Measured at 1 GiB pool and a 3 GiB guard: one_concat, no_regex and case3 at 3,000 rows were stopped at 14.6-17.3 GiB.
plain, concat_only, regex_only, two_literal at 3,000 rows and two_literal at 300 finish in about 0.1 s.
A regexp is not the trigger, which corrects the first report. Needs runtime.json beside it.
"""
import json,sys,shutil,time
from pathlib import Path
H=Path(__file__).resolve().parent
import pyarrow as pa,pyarrow.parquet as pq
from docspec_client.client import NativeDatasets
rows=int(sys.argv[1]);v=sys.argv[2]
work=H/f'gap-{v}';shutil.rmtree(work,ignore_errors=True);work.mkdir()
st=pa.struct([('system_code',pa.string()),('role',pa.string())])
data=[[dict(system_code=f'hs{"cn" if i%2 else "ag"}{i%100:02d}',role='host')] for i in range(rows)]
pq.write_table(pa.table(dict(event_id=pa.array(range(rows),pa.int64()),raw=pa.array(data,pa.list_(st)),flag=pa.array([False]*rows))),work/'t.parquet')
R="SELECT event_id,flag,unnest(raw) AS c,unnest(range(0,cast(array_length(raw) AS BIGINT))) AS idx FROM t"
S="lower(c['system_code'])"
RX=f"regexp_like({S},'^hs(?:cn|ef)[0-9]{{2}}$')"
E={'case3':f"CASE WHEN {S}='hszt00' THEN 'x' WHEN {RX} THEN 'hl'||substr({S},3) ELSE {S} END",
 'regex_only':f"CASE WHEN {RX} THEN 'y' ELSE {S} END",
 'no_regex':f"CASE WHEN {S}='hszt00' THEN 'x' WHEN {S}='hsag00' THEN 'hl'||substr({S},3) ELSE {S} END",
 'concat_only':f"'hl'||substr({S},3)",
 'plain':S,
 'flag_false':f"CASE WHEN flag AND {RX} THEN 'y' ELSE {S} END",
 'two_literal':f"CASE WHEN {S}='hszt00' THEN 'x' WHEN {S}='hsag00' THEN 'z' ELSE {S} END",
 'one_concat':f"CASE WHEN {S}='hsag00' THEN 'hl'||substr({S},3) ELSE {S} END",
 'two_no_else':f"CASE WHEN {S}='hszt00' THEN 'x' WHEN {S}='hsag00' THEN 'z' END",
 'bool_field':None}
if v=='bool_field':
    agg=f"named_struct('s',{S},'b',{RX},'r',c['role'])"
else:
    agg=f"named_struct('s',{E[v]},'r',c['role'])"
q=f"WITH r AS ({R}) SELECT event_id,array_agg({agg} ORDER BY idx) AS a FROM r GROUP BY event_id"
job=dict(scratch=str(work/'n'),inputs=[dict(name='t',kind='parquet',path=str(work/'t.parquet'))],steps=[dict(name='p',sql=q,materialize=True)],outputs=[],queries=[dict(name='n',sql='SELECT count(*) AS n FROM p')])
(work/'j.json').write_text(json.dumps(job));t=time.time()
with NativeDatasets.from_config(H/'runtime.json') as e:
    r=e.run_job(work/'j.json')
print(v,rows,round(time.time()-t,2),r['queries'][0]['data'],flush=True)
shutil.rmtree(work)
