"""Finding 7a (cont.): include 2xx HTML entries whose line records no headers at all, and snapshot-based variants."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
q(c,"""with x as (select r.rk, r.ln, max(coalesce(try_cast(split_part(r.http_status,':',2) as int), try_cast(r.status_code as int))) st, bool_or(lower(r.media_type) like '%html%') html from r group by 1,2)
select count(*) n, count(*) filter (l.hdr_kind is null and l.hdr_items_kind is null and l.hdr_headers_kind is null) no_headers_recorded, count(*) filter (l.h_content_length is null) no_cl, round(100.0*count(*) filter (l.h_content_length is null)/count(*),1) from x join l using (rk,ln) where st between 200 and 299 and html""","2xx HTML by entry status/media type, all lines")
q(c,"""with x as (select distinct receipt_key, receipt_line from c where http_status between 200 and 299 and lower(media_type) like '%html%') select count(*), count(*) filter (l.h_content_length is null), round(100.0*count(*) filter (l.h_content_length is null)/count(*),1) from x join l on l.rk=substr(x.receipt_key,10) and l.ln=x.receipt_line""","snapshot 2xx HTML lines: no content-length on the line")
q(c,"""with x as (select r.rk, r.ln, max(coalesce(try_cast(split_part(r.http_status,':',2) as int), try_cast(r.status_code as int))) st, bool_or(lower(r.media_type) like '%html%') html from r group by 1,2),
y as (select l.*, (l.hdr_kind is null and l.hdr_items_kind is null and l.hdr_headers_kind is null) nohdr from x join l using (rk,ln) where st between 200 and 299 and html)
select count(*) filter (not nohdr) with_headers, count(*) filter (not nohdr and h_content_length is null) none_, round(100.0*count(*) filter (not nohdr and h_content_length is null)/count(*) filter (not nohdr),1) pct,
 count(*) filter (h_content_length is not null) declaring, count(*) filter (h_content_length is not null and h_content_encoding is not null) declaring_with_ce,
 count(*) filter (not nohdr and lower(coalesce(h_content_type,'')) not like '%html%') hdr_ct_not_html,
 count(*) filter (h_content_length is not null and lower(coalesce(h_content_type,'')) not like '%html%') declaring_hdr_ct_not_html
 from y""","62% set split: header-recording lines only; declaring lines with Content-Encoding; header content-type not html")
