"""Finding 1: file_references vs captures[]; bodiless lines; overlap; old-index coverage."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
q(c,"select count(*), sum(n_caps), sum(n_frefs), count(*) filter (n_frefs>0), count(*) filter (n_caps=0), count(*) filter (n_caps=0 and n_frefs=0), count(*) filter (n_caps>0 and n_frefs>0), count(*) filter(n_caps=0 and n_frefs>0) from l",
  "lines, cap entries, fref entries, lines w/ frefs, lines w/ empty captures, lines with neither, lines with both, frefs-only lines")
q(c,"select kind, count(*), count(sha256), count(distinct sha256) from r group by 1","refs by kind: entries, with sha, distinct sha")
q(c,"select kind, bytes_type, count(*) from r group by 1,2 order by 1,3 desc","bytes JSON type by kind")
q(c,"select kind, has_original_path, original_path_abs, count(*) from r group by 1,2,3 order by 1","original_path presence/absolute")
q(c,"select kind, reference_kind, count(*) from r group by 1,2 order by 1,3 desc","reference_kind on entries")
q(c,"select kind, count(*) filter (body_key is not null), count(*) filter (sha256 is null) from r group by 1","body_key present / sha null")
# overlap on the same line
q(c,"""with fr as (select rk,ln,sha256 from r where kind='fref' and sha256 is not null),
 ca as (select distinct rk,ln,sha256 from r where kind='cap' and sha256 is not null),
 bl as (select distinct rk, ln from r where kind='cap' intersect select distinct rk, ln from r where kind='fref')
 select (select count(*) from bl) lines_both,
   (select count(*) from fr join bl using(rk,ln)) fref_on_both_lines,
   (select count(*) from fr semi join ca using(rk,ln,sha256)) fref_same_sha_as_cap_same_line,
   (select count(*) from fr) fref_total,
   (select count(*) from fr where sha256 in (select sha256 from ca)) fref_sha_seen_in_any_cap,
   (select count(distinct sha256) from fr) fref_distinct,
   (select count(distinct sha256) from fr where sha256 not in (select sha256 from ca)) fref_distinct_never_in_cap""","overlap")
q(c,"select seg, count(*) filter (n_frefs>0), sum(n_frefs) from l group by 1","frefs by segment")
q(c,"select regexp_replace(regexp_replace(rk,'\\d{4}-\\d\\d-\\d\\d','DATE'),'-\\d{8}','') g, count(*) filter (n_frefs>0) lines, sum(n_frefs) refs from l group by 1 having sum(n_frefs)>0 order by 3 desc limit 40","frefs by receipt shape")
# old index coverage
q(c,"select reference_kind, count(*) from c group by 1 order by 2 desc","old index reference_kind")
q(c,"""select count(*) from r x where kind='fref' and not exists (select 1 from c where c.receipt_key='receipts/'||x.rk and c.sha256=x.sha256)""","fref entries with no old-index row of same receipt+sha")
q(c,"""select count(*) from r x where kind='cap' and sha256 is not null and not exists (select 1 from c where c.receipt_key='receipts/'||x.rk and c.sha256=x.sha256)""","cap entries with no old-index row of same receipt+sha")
q(c,"""select count(*) from (select rk, ln from r where kind='fref' group by 1,2 having count(sha256)=0) x join l using (rk,ln) where l.n_caps=0""","lines whose only references are null-sha file_references")
q(c,"select count(*) from c where reference_kind='file' and sha256 is null","snapshot file rows with null sha")
