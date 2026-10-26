"""Finding 6: PDF copier candidate rule vs the old catalog's sniff."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q, A
c=con()
c.execute(f"create view rd as select * from read_parquet('{A}readings/*.parquet', union_by_name=true)")
q(c,"select bf, count(*) from (select unnest(body_format) bf from rd) group by 1 order by 2 desc limit 15","readings body_format values")
q(c,"select bf, count(*) from (select unnest(body_format) bf from f) group by 1 order by 2 desc limit 15","filenames body_format values")
c.execute("create temp table mt as select sha256, bool_or(media_type ilike '%pdf%') mpdf, max(bytes) b from c where sha256 is not null group by 1")
c.execute("""create temp table loc as select sha256, bool_or(regexp_matches(lower(coalesce(original_path_tail,'')), '\\.pdf$') or regexp_matches(lower(coalesce(context_url,'')), '\\.pdf($|[?#])')) lpdf from r where sha256 is not null group by 1""")
c.execute("create temp table rmt as select sha256, bool_or(media_type ilike '%pdf%') rmpdf from r where sha256 is not null group by 1")
c.execute("""create temp table sf as select regexp_extract(body_key,'([0-9a-f]{64})',1) sha256, bool_or(list_contains(body_format,'pdf')) spdf, bool_or(len(body_format)>0) sniffed from f where body_key is not null group by 1""")
c.execute("""create temp table sr as select regexp_extract(body_key,'([0-9a-f]{64})',1) sha256, bool_or(list_contains(body_format,'pdf')) spdf, bool_or(len(body_format)>0) sniffed from rd where body_key is not null group by 1""")
q(c,"select count(*) filter (mpdf), count(*) from mt","snapshot: distinct bodies with a pdf media_type on any row; all bodies")
q(c,"select count(*) filter (rmpdf) from rmt","receipts: distinct bodies with a pdf media_type on any entry")
for name in ('sf','sr'):
    q(c,f"""select count(*) filter (s.spdf) sniff_pdf, count(*) filter (s.sniffed) sniffed,
      count(*) filter (mt.mpdf and not coalesce(s.spdf,false)) mt_not_sniff_pdf,
      count(*) filter (mt.mpdf and s.sniffed and not s.spdf) mt_sniffed_other,
      count(*) filter (mt.mpdf and s.sha256 is null) mt_no_sniff_row,
      count(*) filter (s.spdf and not mt.mpdf) sniff_pdf_not_mt,
      count(*) filter (s.spdf and not mt.mpdf and loc.lpdf) of_which_locator_pdf,
      count(*) filter (s.spdf and not (mt.mpdf or loc.lpdf)) missed_by_mt_or_loc
      from mt left join {name} s using (sha256) left join loc using (sha256)""", f"{name}: media-type rule vs sniff")
q(c,"""select count(*) filter (mpdf or lpdf) mt_or_loc, count(*) filter (lpdf and not mpdf) loc_only from mt left join loc using (sha256)""","media type OR locator says PDF: bodies; locator-only additions")
