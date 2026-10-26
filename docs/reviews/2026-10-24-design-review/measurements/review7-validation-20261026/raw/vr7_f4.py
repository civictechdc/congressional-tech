"""Finding 4: where the old index's status (and time) come from on undated/assemble-* receipts."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
q(c,"select receipt_key, count(*), count(http_status), count(retrieved_at) from c where receipt_key like '%/undated/assemble-%' group by 1 having count(http_status)>0 order by 3 desc limit 12","snapshot rows with status/time in undated assemble receipts")
q(c,"select count(*), count(http_status) from c where receipt_key like '%/undated/assemble-%'","total")
# for the top receipts, where is the status on the line?
c.execute("create temp table cr as select substr(receipt_key,10) rk, receipt_line ln, pointer_json, sha256, http_status, retrieved_at, reference_kind from c where receipt_key like '%/undated/assemble-%' and http_status is not null")
q(c,"""select cr.rk, count(*) n,
 count(*) filter (l.r_http_status is not null) rec_http_status,
 count(*) filter (json_extract(l.rec_scalars::json,'$.status_code') is not null) rec_status_code,
 count(*) filter (l.r_status is not null) rec_status,
 count(*) filter (l.times is not null) any_rec_time
 from cr join l on l.rk=cr.rk and l.ln=cr.ln group by 1 order by 2 desc limit 8""","line-level fields for status-bearing snapshot rows")
q(c,"""select cr.rk, count(*) n, count(*) filter (x.http_status is not null) ref_http_status, count(*) filter (x.status_code is not null) ref_status_code, count(*) filter (x.status is not null) ref_status,
  count(*) filter (cast(cr.http_status as varchar) = split_part(coalesce(x.http_status,''),':',2) or cast(cr.http_status as varchar)=x.status_code) equal_to_ref
 from cr join (select distinct on (rk,ln,sha256) * from r) x on x.rk=cr.rk and x.ln=cr.ln and x.sha256=cr.sha256 group by 1 order by 2 desc limit 8""","entry-level fields for those rows")
q(c,"""select count(*) lines, count(*) filter (r_http_status is not null) rec_http_status, count(*) filter (json_extract(rec_scalars::json,'$.status_code') is not null) rec_status_code, count(*) filter (times like '%"retrieved_at"%') rec_retrieved_at, count(*) filter (n_caps+n_frefs>0) with_bodies from l where rk like '%/undated/assemble-%'""","all undated/assemble-* lines: record-level status/time")
q(c,"""with x as (select l.rk, l.ln, l.n_caps, json_extract_string(times::json,'$.started_at')::timestamptz s, json_extract_string(times::json,'$.finished_at')::timestamptz f from l where rk='senate/captions/undated/assemble-20260930.jsonl.gz')
select count(*) lines, sum(n_caps) caps, sum(n_caps) filter (s is not null) caps_on_lines_with_started, sum(n_caps) filter (f is not null) caps_with_finished, round(median(epoch(f)-epoch(s))) med_span_s, round(quantile_cont(epoch(f)-epoch(s),0.95)) p95_span_s, min(s)::date, max(f)::date from x""","senate/captions/undated: started_at/finished_at bracket per session line")
q(c,"""with t as (select distinct r.sha256 from r join l using (rk,ln) where l.times like '%"retrieved_at"%' or l.times like '%"captured_at"%' or r.retrieved_at is not null or r.captured_at is not null),
 u as (select sha256 from r where rk='senate/captions/undated/assemble-20260930.jsonl.gz')
 select count(*), count(*) filter (sha256 in (select sha256 from t)), count(distinct sha256), count(distinct sha256) filter (sha256 in (select sha256 from t)) from u""","senate/captions/undated entries whose body has a fetch time on some other line: entries, distinct bodies")
