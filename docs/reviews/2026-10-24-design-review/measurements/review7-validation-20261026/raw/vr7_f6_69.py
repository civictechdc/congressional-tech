"""Finding 6: what the 69 sniff-PDF bodies without a PDF media type are."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
shas=[r[0] for r in json.load(open('pdf_bytes.json'))['missed69']['rows']]
c.execute("create temp table s69 as select unnest(?::varchar[]) sha256",[shas])
q(c,"select coalesce(media_type,'<null>'), reference_kind, fidelity, family, count(*), count(distinct sha256) from c join s69 using (sha256) group by all order by 5 desc","snapshot rows of the 69: media_type, reference_kind, fidelity, family")
q(c,"select regexp_replace(regexp_replace(rk,'/\\d{4}-\\d\\d-\\d\\d/','/D/'),'/(download|corpus-recovery)-.*$','/\\1') shape, kind, coalesce(media_type,'<null>'), count(*), count(distinct sha256) from r join s69 using (sha256) group by all order by 4 desc","receipt entries of the 69")
q(c,"select regexp_extract(context_url,'^https?://([^/]+)',1), count(distinct sha256) from r join s69 using (sha256) group by 1 order by 2 desc limit 8","hosts")
q(c,"select count(distinct sha256) from r join s69 using (sha256) where regexp_matches(lower(coalesce(original_path_tail,'')), '\\.pdf$')","with .pdf original_path tail")
q(c,"select count(distinct sha256) from r join s69 using (sha256) where regexp_matches(lower(coalesce(context_url,'')), '\\.pdf($|[?#])')","with .pdf context_url")
q(c,"select regexp_replace(regexp_replace(rk,'\\d{8}T\\d{6}Z-[0-9a-f]+','TS-H'),'\\d+','N') p, l.r_mode, l.has_recovery_evidence, r.fidelity, count(*) from r join s69 using (sha256) join l using (rk,ln) where kind='cap' group by all order by 5 desc","download receipts holding the 69: name pattern, mode, recovery evidence, fidelity")
