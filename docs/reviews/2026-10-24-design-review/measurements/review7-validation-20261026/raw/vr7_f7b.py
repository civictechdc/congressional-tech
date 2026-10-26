"""Finding 7b: bodies over 100 MB (A 11.5 says 579, up to 1.19 GB)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q, A
c=con()
c.execute("create temp table b as select sha256, max(bytes) ob, max(stored_bytes) sb, coalesce(bool_or(media_type ilike '%pdf%'),false) mpdf from c where sha256 is not null group by 1")
c.execute(f"""create temp table sf as select regexp_extract(body_key,'([0-9a-f]{{64}})',1) sha256, bool_or(list_contains(body_format,'pdf')) spdf from read_parquet('{A}filenames.parquet') where body_key is not null group by 1""")
q(c,"""select count(*) filter (ob > 104857600) ob_gt_100MiB, count(*) filter (ob > 100000000) ob_gt_100MB, count(*) filter (sb > 104857600) sb_gt_100MiB, count(*) filter (sb > 100000000) sb_gt_100MB, max(ob), max(sb) from b""","all bodies: original vs stored, MiB vs MB")
q(c,"""select count(*) filter (ob > 104857600) ob_MiB, count(*) filter (ob > 100000000) ob_MB, count(*) filter (sb > 104857600) sb_MiB, count(*) filter (sb > 100000000) sb_MB, max(ob) from b left join sf using (sha256) where not (mpdf or coalesce(spdf,false))""","non-PDF bodies (no PDF media type, not sniffed PDF): the .gz ones the site unpacks")
q(c,"""select count(*) filter (ob > 104857600) ob_MiB, count(*) filter (ob > 100000000) ob_MB, count(*) filter (sb > 104857600) sb_MiB, count(*) filter (sb > 100000000) sb_MB from b left join sf using (sha256) where (mpdf or coalesce(spdf,false))""","PDF bodies (open their .pdf copy)")
q(c,"""select count(*) from b where ob between 100000000 and 104857600""","bodies between 100 MB and 100 MiB original")
