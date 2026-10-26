"""Re-derive the PDF-integrity reuse numbers of plan section 2 from the pinned snapshot (read-only)."""
import duckdb, sys
root = sys.argv[1]
con = duckdb.connect()
con.execute(f"""create view c as select *, regexp_extract(receipt_key, '/([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})/', 1) as rdate
               from '{root}/captures.parquet'""")
con.execute(f"create view r as select * from '{root}/readings/*.parquet'")
con.execute(f"create view d as select body_key, response_format, body_format from '{root}/documents.parquet'")
def q(label, s):
    print(label, con.execute(s).fetchall())
# body sizes: one row per body
con.execute("""create temp table bodies as select sha256, max(bytes) bytes, max(stored_bytes) stored_bytes,
               bool_or(media_type ilike '%pdf%') mt_pdf from c where sha256 is not null group by sha256""")
con.execute("""create temp table cat_pdf as select distinct regexp_extract(body_key, '([0-9a-f]{64})', 1) sha256 from d
               where list_contains(response_format, 'pdf') or list_contains(body_format, 'pdf')""")
con.execute("""create temp table rd as select regexp_extract(body_key, '([0-9a-f]{64})', 1) sha256, status,
               list_contains(body_format, 'pdf') is_pdf, body_format from r""")
q("readings rows/bodies", "select count(*), count(distinct sha256) from rd")
con.execute("""create temp table cand as select b.* from bodies b
               where b.mt_pdf or b.sha256 in (select sha256 from cat_pdf) or b.sha256 in (select sha256 from rd where is_pdf)""")
q("candidates (media type OR catalog sniff OR reading format pdf)", "select count(*), sum(bytes)/1e9, sum(stored_bytes)/1e9 from cand")
q("candidates (media type OR catalog sniff)", "select count(*) from bodies b where b.mt_pdf or b.sha256 in (select sha256 from cat_pdf)")
con.execute("""create temp table capchk as select sha256,
                 bool_or(resolution='saved') any_saved, bool_or(resolution='invalid_document') any_invalid,
                 bool_or(rdate > '2026-10-01' and resolution in ('saved','invalid_document')) after_1001,
                 bool_or(rdate = '2026-10-01' and resolution in ('saved','invalid_document')) on_1001
               from c where rdate >= '2026-10-01' and resolution in ('saved','invalid_document') group by sha256""")
con.execute("create temp table legacy as select distinct sha256 from rd where status='completed' and is_pdf")
con.execute("create temp table legacy_fail as select distinct sha256 from rd where status='failed' and is_pdf")
q("capture-checked candidates", "select count(*) from cand where sha256 in (select sha256 from capchk)")
q("legacy-opened candidates", "select count(*) from cand where sha256 in (select sha256 from legacy)")
q("covered (either)", "select count(*) from cand where sha256 in (select sha256 from capchk) or sha256 in (select sha256 from legacy)")
q("unchecked: n, GB original, GB stored", """select count(*), sum(bytes)/1e9, sum(stored_bytes)/1e9 from cand
     where sha256 not in (select sha256 from capchk) and sha256 not in (select sha256 from legacy)""")
q("rests on 2026-10-01 lines alone (no later line, no legacy)", """select count(*) from cand k join capchk x using (sha256)
     where x.on_1001 and not x.after_1001 and k.sha256 not in (select sha256 from legacy)""")
q("capture says invalid_document (any line >= 10-01)", "select count(*) from cand where sha256 in (select sha256 from capchk where any_invalid)")
q("capture invalid on 10-01 only", "select count(*) from cand k join capchk x using(sha256) where x.any_invalid and x.on_1001 and not x.after_1001")
q("both bases: agree(saved & legacy ok) / capture-invalid but legacy-ok", """select
      count(*) filter (where x.any_saved and not x.any_invalid),
      count(*) filter (where x.any_invalid), count(*) from capchk x join legacy l using (sha256)""")
q("saved AND invalid both on lines (conflict within capture)", "select count(*) from capchk where any_saved and any_invalid")
q("legacy failed opens among candidates", "select count(*) from cand where sha256 in (select sha256 from legacy_fail)")
q("unchecked size distribution (MB): p50,p90,max; n>=64MiB exact", """select quantile_cont(bytes,0.5)/1e6, quantile_cont(bytes,0.9)/1e6, max(bytes)/1e6,
     count(*) filter (where bytes = 67108864) from cand where sha256 not in (select sha256 from capchk) and sha256 not in (select sha256 from legacy)""")
q("unchecked by reading status", """select coalesce(rd.status,'(no reading)'), count(distinct k.sha256) from cand k left join rd using (sha256)
     where k.sha256 not in (select sha256 from capchk) and k.sha256 not in (select sha256 from legacy) group by 1 order by 2 desc""")
q("unchecked by latest rdate bucket", """select case when max(c.rdate)='' then 'undated' else max(c.rdate) end d, count(distinct k.sha256) from cand k join c using (sha256)
     where k.sha256 not in (select sha256 from capchk) and k.sha256 not in (select sha256 from legacy) group by k.sha256 order by 1""")
