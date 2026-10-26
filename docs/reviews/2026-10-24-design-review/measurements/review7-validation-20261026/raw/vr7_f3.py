"""Finding 3: which line time fields are fetch times; agreement with Date header, retrieved_at, write date."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
c.execute("""create temp table lt as
select rk, ln, seg, n_caps, n_frefs, r_requested_url, r_url, r_final_url, rec_scalars, times,
  try_strptime(h_date, '%a, %d %b %Y %H:%M:%S GMT') hdate,
  try_cast(regexp_extract(rk, '(\\d{4}-\\d\\d-\\d\\d)/', 1) as date) pdate,
  regexp_extract(rk, '/(download|assemble|corpus-recovery)', 1) writer,
  regexp_replace(regexp_replace(rk,'/\\d{4}-\\d\\d-\\d\\d/','/D/'),'/(download|corpus-recovery)-.*$','/\\1') shape,
  t.k, try_cast(t.v as timestamptz) tv
from l, lateral (select unnest(json_keys(times::json)) k) kk,
  lateral (select kk.k k, json_extract_string(times::json, '$."'||kk.k||'"') v) t
where times is not null""")
q(c,"select k, count(*) n, count(tv) parsed, count(hdate) with_date_hdr, count(*) filter (abs(epoch(tv)-epoch(hdate::timestamptz))<=5) within5s_of_Date, count(*) filter (abs(epoch(tv)-epoch(hdate::timestamptz))<=300) within5min, round(median(abs(epoch(tv)-epoch(hdate::timestamptz)))) med_abs_s, count(pdate) dated, count(*) filter (tv::date = pdate) same_day_as_prefix from lt group by 1 having count(*)>100 order by 2 desc",
  "per record time key: lines, Date-header agreement (|t-Date|), prefix-date agreement")
q(c,"""with a as (select rk, ln, max(tv) filter (k='retrieved_at') ra, max(tv) filter (k='captured_at') ca, max(tv) filter (k='observed_at') oa, max(tv) filter (k='checked_at') cha, max(tv) filter (k='started_at') sa from lt group by 1,2)
select count(*) filter (ra is not null and ca is not null) ra_ca, count(*) filter (ra is not null and ca is not null and abs(epoch(ra)-epoch(ca))<=5) ra_ca_5s,
 count(*) filter (ra is not null and oa is not null) ra_oa, count(*) filter (ra is not null and oa is not null and abs(epoch(ra)-epoch(oa))<=5) ra_oa_5s,
 count(*) filter (ra is not null and cha is not null) ra_cha, count(*) filter (ra is not null and cha is not null and abs(epoch(ra)-epoch(cha))<=60) ra_cha_60s,
 count(*) filter (ra is not null and sa is not null) ra_sa, count(*) filter (ra is not null and sa is not null and abs(epoch(ra)-epoch(sa))<=60) ra_sa_60s from a""","pairwise agreement with retrieved_at on the same line")
q(c,"select shape, k, count(*), count(hdate), count(*) filter (abs(epoch(tv)-epoch(hdate::timestamptz))<=5), count(pdate), count(*) filter (tv::date=pdate) from lt where k in ('captured_at','observed_at','checked_at','started_at','recorded_at','finished_at') group by 1,2 having count(*)>200 order by 3 desc","non-retrieved_at time keys by shape: n, with Date, within 5 s of Date, dated, same day as prefix")
q(c,"select shape, count(*), count(*) filter (rec_scalars like '%captured_at%'), count(*) filter (rec_scalars like '%captured_at%' and times like '%captured_at%') from lt where k='captured_at' group by 1 order by 2 desc","captured_at by shape")
