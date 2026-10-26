"""Finding 3f: rows with no time (snapshot vs receipts), and DM 7.5's ~30% of documents without a capture date."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
q(c,"select count(*), count(*) filter (retrieved_at is null) from c","snapshot rows; rows with null retrieved_at")
c.execute("""create temp table lt as select rk, ln,
  json_extract_string(times::json,'$.retrieved_at') is not null or (json_extract_string(times::json,'$.captured_at') is not null and coalesce(r_transport,'') not like 'eot-%') t_strict,
  (json_extract_string(times::json,'$.started_at') is not null or json_extract_string(times::json,'$.checked_at') is not null or json_extract_string(times::json,'$.completed_at') is not null or json_extract_string(times::json,'$.observed_at') is not null or json_extract_string(times::json,'$."receipt.observed_at"') is not null or json_extract_string(times::json,'$.recorded_at') is not null or json_extract_string(times::json,'$.request_started_at') is not null or json_extract_string(times::json,'$._retrieved_at') is not null) t_loose
  from l""")
c.execute("create temp table rr as select r.rk, r.ln, r.sha256, (r.retrieved_at is not null or r.captured_at is not null) ref_t, lt.t_strict, lt.t_loose from r join lt using (rk,ln)")
q(c,"""select count(*) refs, count(*) filter (not (ref_t or t_strict)) no_strict, count(*) filter (not (ref_t or t_strict or t_loose)) no_loose from rr""","body references (captures[] + file_references[]): with no fetch time on the entry or its line")
q(c,"""select count(*) bodiless, count(*) filter (not t_strict), count(*) filter (not (t_strict or t_loose)) from l join lt using (rk,ln) where n_caps=0 and n_frefs=0""","bodiless lines: with no fetch time")
c.execute("""create temp table bt as select sha256, bool_or(ref_t or t_strict) s, bool_or(ref_t or t_strict or t_loose) lo from rr where sha256 is not null group by 1""")
c.execute("""create temp table bs as select sha256, bool_or(retrieved_at is not null) s from c where sha256 is not null group by 1""")
c.execute("""create temp table dd as select regexp_extract(body_key,'([0-9a-f]{64})',1) sha, lower(regexp_extract(filename,'\\.([A-Za-z0-9]+)$',1)) in ('vtt','m3u8') vtt from d""")
q(c,"select count(*), count(sha), count(*) filter (vtt) from dd","documents rows, with body sha, vtt")
q(c,"""select (vtt) is_vtt, count(*) docs, count(*) filter (not coalesce(bs.s,false)) no_snapshot_time, count(*) filter (not coalesce(bt.s,false)) no_receipt_strict, count(*) filter (not coalesce(bt.lo,false)) no_receipt_loose
 from dd left join bs on bs.sha256=dd.sha left join bt on bt.sha256=dd.sha where dd.sha <> '' group by 1""","documents rows by vtt: body has no time on any row (snapshot) / on any referencing line (receipts)")
