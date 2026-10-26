"""Finding 7c: recovery bodies also saved by a real fetch (DM 7.8 says 3,558 of 11,044)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
q(c,"select r_mode, has_recovery_evidence, publisher_requested, count(*) from l where r_mode in ('retained_import','import','replay') or has_recovery_evidence group by all order by 4 desc","recovery-ish lines: mode, recovery_evidence, publisher_requested")
c.execute("""create temp table e as select r.*, l.r_mode, l.has_recovery_evidence rec_ev, l.r_transport,
  coalesce(try_cast(split_part(r.http_status,':',2) as int), try_cast(r.status_code as int), try_cast(split_part(l.r_http_status,':',2) as int)) st
  from r join l using (rk,ln) where r.sha256 is not null""")
c.execute("create temp table recb as select distinct sha256 from e where r_mode='retained_import' or rec_ev")
c.execute("create temp table recb_m as select distinct sha256 from e where r_mode='retained_import'")
q(c,"select (select count(*) from recb), (select count(*) from recb_m)","recovery bodies: mode=retained_import OR recovery_evidence; mode=retained_import only")
def real(where, label):
    q(c,f"""with rf as (select distinct sha256 from e where not (coalesce(r_mode,'')='retained_import' or rec_ev) and {where})
      select (select count(*) from recb), (select count(*) from recb join rf using (sha256)), (select count(*) from recb_m join rf using (sha256))""", label)
real("st between 200 and 299", "also in a non-recovery entry with 2xx status")
real("st between 200 and 299 and coalesce(fidelity,'') = 'exact-bytes'", "... and fidelity exact-bytes")
real("st between 200 and 299 and coalesce(fidelity,'') = 'exact-bytes' and coalesce(r_mode,'') <> 'replay'", "... and not a replay line")
real("st between 200 and 299 and coalesce(fidelity,'') not in ('retained-file')", "... 2xx and fidelity not retained-file")
real("coalesce(fidelity,'') not in ('retained-file') and coalesce(reference_kind,'') <> 'retained-file'", "... any status, not retained-file")
q(c,"""with rf as (select distinct sha256 from c where reference_kind <> 'retained-file' and fidelity <> 'retained-file' and http_status between 200 and 299 and receipt_key not like '%recovery%' and receipt_key not like '%import%'),
 rb as (select distinct sha256 from c where receipt_key like '%recovery%' or receipt_key like '%import%')
 select (select count(*) from rb), (select count(*) from rb join rf using (sha256))""","snapshot, key-pattern variant (hunting 3,558 / 11,044)")
q(c,"""select regexp_extract(rk,'(\\d{4}-\\d\\d-\\d\\d)',1) d, regexp_replace(regexp_replace(split_part(rk,'/',-1),'\\d{8}T\\d{6}Z-[0-9a-f]+','TS-H'),'[0-9a-f]{32}|\\d+','N','g') p, count(distinct sha256) from e where r_mode='retained_import' group by all order by 1,2""","recovery bodies by receipt date/pattern")
real("st between 200 and 299 and coalesce(fidelity,'') = 'exact-bytes' and rk not like '%corpus-recovery%'", "exact-bytes 2xx, excluding corpus-recovery receipts from the real side")
q(c,"""with rb as (select distinct sha256 from e where r_mode='retained_import' and rk not like '%corpus-recovery%'),
 rf as (select distinct sha256 from e where not (coalesce(r_mode,'')='retained_import' or rec_ev) and st between 200 and 299 and coalesce(fidelity,'')='exact-bytes')
 select (select count(*) from rb), (select count(*) from rb join rf using (sha256))""","recovery bodies excluding the 2026-10-16 corpus-recovery runs")
