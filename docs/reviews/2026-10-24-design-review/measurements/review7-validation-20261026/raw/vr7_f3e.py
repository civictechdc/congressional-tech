"""Finding 3e: requested URLs with no fetch time on any line (DM 7.7's 19,316 / 1,158,426)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
q(c,"select count(distinct context_url), count(distinct context_url) filter (reference_kind<>'retained-file') from c","snapshot distinct context_url (all; excluding retained-file)")
q(c,"""select count(*), count(*) filter (not has_t) from (select context_url, bool_or(retrieved_at is not null) has_t from c where context_url is not null group by 1)""","snapshot context_urls; with no retrieved_at on any row")
q(c,"""select count(*), count(*) filter (not has_t) from (select context_url, bool_or(retrieved_at is not null) has_t from c where context_url is not null and reference_kind<>'retained-file' group by 1)""","... excluding retained-file rows")
c.execute("""create temp table lu as select rk, ln, coalesce(r_requested_url, r_url, r_x_url, r_final_url, r_request_url) u, r_mode, has_recovery_evidence,
  json_extract_string(times::json,'$.retrieved_at') is not null or (json_extract_string(times::json,'$.captured_at') is not null and coalesce(r_transport,'') not like 'eot-%') t_strict,
  (json_extract_string(times::json,'$.started_at') is not null or json_extract_string(times::json,'$.checked_at') is not null or json_extract_string(times::json,'$.completed_at') is not null) t_br,
  (json_extract_string(times::json,'$.observed_at') is not null or json_extract_string(times::json,'$."receipt.observed_at"') is not null or json_extract_string(times::json,'$.recorded_at') is not null or json_extract_string(times::json,'$.request_started_at') is not null or json_extract_string(times::json,'$._retrieved_at') is not null) t_obs,
  rk like '%/download-%' dl
  from l""")
c.execute("create temp table ru as select rk, ln, bool_or(retrieved_at is not null or captured_at is not null) rt from r group by 1,2")
q(c,"""with x as (select u, bool_or(t_strict or coalesce(rt,false)) s, bool_or(t_strict or coalesce(rt,false) or t_br) b, bool_or(t_strict or coalesce(rt,false) or t_br or t_obs) o, bool_or(dl) any_dl from lu left join ru using (rk,ln) where u is not null and coalesce(r_mode,'') not in ('retained_import') and not has_recovery_evidence group by 1)
select count(*) urls, count(*) filter (not s) no_strict, count(*) filter (not b) no_bracket, count(*) filter (not o) no_obs, count(*) filter (any_dl) urls_in_download, count(*) filter (any_dl and not s) dl_no_strict from x""","receipt requested URLs (non-recovery lines): total; with no time on any line by class")
q(c,"""with x as (select u, bool_or(t_strict or coalesce(rt,false)) s from lu left join ru using (rk,ln) where u is not null and coalesce(r_mode,'') not in ('retained_import') and not has_recovery_evidence group by 1),
y as (select u, min(rk) rk from lu where u is not null group by 1)
select regexp_replace(regexp_replace(rk,'/\\d{4}-\\d\\d-\\d\\d/','/D/'),'/(download|corpus-recovery)-.*$','/\\1') shape, count(*) from x join y using (u) where not s group by 1 order by 2 desc limit 10""","URLs with no strict time, by first receipt shape")
q(c,"""with x as (select context_url, bool_or(retrieved_at is not null) t, bool_or(capture_date<>'undated') cd, bool_or(reference_kind='retained-file') rf, bool_or(reference_kind in ('capture','embedded','file')) body, bool_or(reference_kind='metadata') md from c where context_url is not null group by 1)
select count(*) filter (not t and not cd), count(*) filter (not t and not cd and not rf), count(*) filter (not t and body), count(*) filter (not t and not md), count(*) filter (not t and md and not body) from x""","hunting 19,316: no time & no capture_date; ...& no retained; no time & has body row; no time & no metadata row; no time & only metadata")
