"""Finding 2b: lines in record-as-list receipts; distinct raw record keys; per-shape field locations."""
import sys, os, gzip, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
q(c,"select count(distinct rk), sum(n) from (select rk, count(*) n from l group by 1) where rk in (select rk from l where rec_type='list')","receipts holding a record-as-list line, and their lines")
q(c,"select count(distinct rk), sum(n) from (select rk, count(*) n from l group by 1) where rk in (select rk from l where rec_type='list' or r_http_status='str:')","... or http_status ''")
SH="regexp_replace(regexp_replace(regexp_replace(rk,'\\d{4}-\\d\\d-\\d\\d','D'),'-\\d{8}T\\d{6}Z-[0-9a-z]+(-[0-9a-z]+)*-\\d+',''),'-\\d{8}','')"
c.execute(f"create view ls as select *, case when rk like '%/download-%' or rk like '%corpus-recovery%' then regexp_replace({SH},'^([^/]+(/[^/]+)?)/D/(download|corpus-recovery).*$','\\1/D/\\3') else {SH} end shape from l")
q(c,"select shape, count(*) n, round(avg((r_requested_url is not null)::int),2) req, round(avg((r_url is not null)::int),2) url, round(avg((r_final_url is not null)::int),2) final, round(avg((r_x_url is not null)::int),2) _url, round(avg((times is not null)::int),2) t, round(avg((r_http_status is not null)::int),2) hs, round(avg((r_status is not null)::int),2) st, round(avg((r_outcome is not null)::int),2) oc, round(avg((r_result is not null)::int),2) res, round(avg((hdr_kind is not null)::int),2) hdr, round(avg((n_caps>0)::int),2) caps, round(avg((n_frefs>0)::int),2) frefs, round(avg(has_recovery_evidence::int),2) rec from ls group by 1 order by 2 desc", "per shape: share of lines with each field (record.*)")
q(c,"select shape, string_agg(distinct k, ' ') from (select shape, unnest(json_keys(times::json)) k from ls where times is not null) group by 1 order by 1","per shape: time keys present on record")
c.execute(f"create view rs as select r.*, ls.shape from r join ls using (rk, ln)")
q(c,"select shape, kind, count(*), round(avg((retrieved_at is not null)::int),2) t, round(avg((http_status is not null and http_status<>'null:')::int),2) hs, round(avg((capture_date is not null)::int),2) cd, round(avg((media_type is not null)::int),2) mt from rs group by 1,2 order by 3 desc","per shape: refs with retrieved_at / http_status / capture_date / media_type")
# distinct raw record keys
keys=collections.Counter()
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
for dp,_,fs in os.walk(R):
    for f in fs:
        with gzip.open(os.path.join(dp,f),'rb') as fh:
            for raw in fh:
                d=json.loads(raw); rec=d.get('record')
                if isinstance(rec,dict): keys.update(rec.keys())
print('## distinct raw record keys', len(keys), 'all-digit keys', sum(1 for k in keys if k.isdigit()))
