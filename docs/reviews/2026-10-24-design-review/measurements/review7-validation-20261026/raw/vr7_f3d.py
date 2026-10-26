"""Finding 3d: P D1 recount. Snapshot rows in dated receipts with no time, and the fetch times their lines carry."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
# per line: which time sources exist
c.execute("""create temp table lt as
select rk, ln, seg, r_mode, r_transport,
  json_extract_string(times::json,'$.retrieved_at') is not null t_ret,
  json_extract_string(times::json,'$.captured_at') is not null t_cap,
  (json_extract_string(times::json,'$.started_at') is not null or json_extract_string(times::json,'$.checked_at') is not null or json_extract_string(times::json,'$.completed_at') is not null) t_bracket,
  (json_extract_string(times::json,'$.observed_at') is not null or json_extract_string(times::json,'$."receipt.observed_at"') is not null or json_extract_string(times::json,'$.recorded_at') is not null or json_extract_string(times::json,'$.request_started_at') is not null) t_obs,
  times is not null t_any,
  coalesce(r_transport,'') like 'eot-%' eot
from l""")
c.execute("""create temp table rt as select rk, ln, bool_or(retrieved_at is not null) ref_ret, bool_or(captured_at is not null) ref_cap, bool_or(observed_at is not null or checked_at is not null) ref_obs, bool_or(capture_date is not null) ref_cdate from r group by 1,2""")
c.execute("create temp table lx as select lt.*, coalesce(ref_ret,false) ref_ret, coalesce(ref_cap,false) ref_cap, coalesce(ref_obs,false) ref_obs, coalesce(ref_cdate,false) ref_cdate from lt left join rt using (rk,ln)")
c.execute("""create temp table cn as select c.*, substr(c.receipt_key,10) rk, c.receipt_line ln from c where regexp_matches(c.receipt_key, '/\\d{4}-\\d\\d-\\d\\d/') and c.retrieved_at is null""")
q(c,"select count(*), count(distinct (rk,ln)) from cn","snapshot rows in date-prefixed receipts with null retrieved_at: rows, lines")
q(c,"select count(*) from c where capture_date<>'undated' and retrieved_at is null","snapshot rows with capture_date <> 'undated' and null retrieved_at")
q(c,"""select count(*) rows_,
 count(*) filter (t_ret) line_rec_retrieved_at,
 count(*) filter (t_ret or ref_ret) plus_ref_retrieved_at,
 count(*) filter (t_ret or ref_ret or (t_cap and not eot) or ref_cap) plus_captured_at,
 count(*) filter (t_ret or ref_ret or t_cap or ref_cap or t_bracket) plus_started_checked,
 count(*) filter (t_ret or ref_ret or t_cap or ref_cap or t_bracket or t_obs or ref_obs) plus_observed_recorded,
 count(*) filter (t_any or ref_ret or ref_cap or ref_obs) any_at_key
 from cn join lx using (rk,ln)""","snapshot null-time rows in dated receipts: rows whose line carries each time class (cumulative)")
q(c,"""select regexp_replace(regexp_replace(rk,'/\\d{4}-\\d\\d-\\d\\d/','/D/'),'/(download|corpus-recovery)-.*$','/\\1') shape, reference_kind, count(*) n,
 count(*) filter (t_ret or ref_ret) ret, count(*) filter (t_cap or ref_cap) cap, count(*) filter (t_bracket) br, count(*) filter (t_obs or ref_obs) obs, count(*) filter (not (t_any or ref_ret or ref_cap or ref_obs)) none_
 from cn join lx using (rk,ln) group by 1,2 order by 3 desc limit 25""","by shape")
q(c,"""select count(distinct (rk,ln)) filter (t_ret), count(distinct (rk,ln)) filter (t_ret or ref_ret), count(*) filter (t_ret and reference_kind='metadata'), count(*) filter (ref_ret), count(*) filter (t_ret and not ref_ret), count(*) filter(ref_cdate), count(*) filter (t_ret and r_mode is null) from cn join lx using (rk,ln)""","variants hunting 47,359: distinct lines t_ret; lines t_ret|ref_ret; metadata rows with t_ret; ref_ret rows; t_ret not ref_ret; ref capture_date; t_ret & no mode")
q(c,"""select reference_kind, count(*) filter (t_ret) from cn join lx using (rk,ln) group by 1""","rows with record.retrieved_at by reference_kind")
q(c,"""select regexp_replace(regexp_replace(cn.rk,'/\\d{4}-\\d\\d-\\d\\d/','/D/'),'/(download|corpus-recovery)-.*$','/\\1') shape, count(*), count(try_cast(json_extract_string(l.times::json,'$.retrieved_at') as timestamptz)), count(*) filter (length(json_extract_string(l.times::json,'$.retrieved_at'))=10), count(distinct json_extract_string(l.times::json,'$.retrieved_at')) from cn join l on l.rk=cn.rk and l.ln=cn.ln where l.times like '%"retrieved_at"%' group by 1""","rows with record.retrieved_at: parseable, date-only, distinct values")
q(c,"""select l.r_mode, l.r_outcome, l.r_transport, split_part(l.r_http_status,':',2), count(*) from cn join lx using (rk,ln) join l using (rk,ln) where not (lx.t_any or ref_ret or ref_cap or ref_obs) group by all order by 5 desc""","the rows with no time-like field at all")
