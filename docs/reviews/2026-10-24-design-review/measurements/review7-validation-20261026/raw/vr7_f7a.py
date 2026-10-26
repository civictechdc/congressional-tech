"""Finding 7a: share of older successful pages that declare no length (DM 6.1 says 62%)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
c.execute("""create temp table p as
select l.*, coalesce(try_cast(split_part(r_http_status,':',2) as int), try_cast(json_extract_string(rec_scalars::json,'$.status_code') as int), try_cast(split_part(r_status,':',2) as int)) st,
  lower(coalesce(h_content_type, (select max(media_type) from r where r.rk=l.rk and r.ln=l.ln and r.kind='cap'))) ct,
  rk like '%/download-%' dl
from l where hdr_kind is not null or hdr_items_kind is not null or hdr_headers_kind is not null""")
def show(label, where):
    q(c, f"""select count(*) n, count(*) filter (h_content_length is null) no_cl, round(100.0*count(*) filter (h_content_length is null)/count(*),1) pct_no_cl,
       count(*) filter (h_content_length is null and coalesce(lower(h_transfer_encoding),'') not like '%chunked%') no_cl_no_chunked,
       round(100.0*count(*) filter (h_content_length is null and coalesce(lower(h_transfer_encoding),'') not like '%chunked%')/count(*),1) pct,
       count(*) filter (h_content_length is not null and h_content_encoding is not null) cl_with_ce,
       round(100.0*count(*) filter (h_content_length is null or h_content_encoding is not null)/count(*),1) pct_no_usable_length
       from p where {where}""", label)
show("2xx HTML lines that record headers (all)", "st between 200 and 299 and ct like '%html%'")
show("... download receipts only", "st between 200 and 299 and ct like '%html%' and dl")
show("... assemble receipts only", "st between 200 and 299 and ct like '%html%' and not dl")
show("2xx any type, recording headers", "st between 200 and 299")
show("2xx HTML+XML", "st between 200 and 299 and (ct like '%html%' or ct like '%xml%')")
show("2xx HTML download, direct transport", "st between 200 and 299 and ct like '%html%' and dl and r_transport='direct'")
show("2xx HTML download, zyte", "st between 200 and 299 and ct like '%html%' and dl and r_transport='zyte'")
q(c,"""with x as (select coalesce(r_requested_url,r_url) u, bool_and(h_content_length is null) none_ from p where st between 200 and 299 and ct like '%html%' group by 1) select count(*), round(100.0*count(*) filter (none_)/count(*),1) from x""","per distinct URL: share whose every 2xx HTML line declares no length")
q(c,"""with x as (select r.sha256, bool_and(h_content_length is null) none_ from p join r using (rk,ln) where st between 200 and 299 and ct like '%html%' and r.kind='cap' group by 1) select count(*), round(100.0*count(*) filter (none_)/count(*),1) from x""","per distinct body")
q(c,"""select count(*), round(100.0*count(*) filter (h_content_length is null)/count(*),1) from p where st between 200 and 299 and ct like '%html%' and (n_caps>0 or n_frefs>0)""","lines with a body")
q(c,"""select count(*), round(100.0*count(*) filter (h_content_length is null)/count(*),1) from p where st between 200 and 299 and (ct like '%html%' or ct like 'text/%')""","html or text/*")
q(c,"""select count(*), round(100.0*count(*) filter (h_content_length is null)/count(*),1) from p where st between 200 and 299 and ct not like '%pdf%' and ct is not null""","2xx non-PDF typed")
q(c,"""select count(*), round(100.0*count(*) filter (h_content_length is null)/count(*),1) from p where st between 200 and 299 and ct like '%html%' and r_mode='fetch'""","mode=fetch")
