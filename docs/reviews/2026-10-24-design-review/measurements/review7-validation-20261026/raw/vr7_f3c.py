"""Finding 3c: where retrieved_at disagrees with the Date header."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
q(c,"""with x as (select r_mode m, r_transport tr, split_part(rk,'/',1) fam, rk like '%/download-%' dl,
  epoch(json_extract_string(times::json,'$.retrieved_at')::timestamptz) - epoch(try_strptime(h_date, '%a, %d %b %Y %H:%M:%S GMT')::timestamptz) dt
  from l where times like '%"retrieved_at"%' and try_strptime(h_date, '%a, %d %b %Y %H:%M:%S GMT') is not null)
select m, tr, fam, dl, count(*) n, count(*) filter (abs(dt)>5) off5, count(*) filter (dt < -86400) older_than_Date_by_1d, round(median(dt)) from x group by all having count(*) filter (abs(dt)>5) > 0 order by off5 desc limit 12""","retrieved_at - Date header (s), lines >5 s off")
