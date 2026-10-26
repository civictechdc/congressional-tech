"""Split the PDF candidates by signal and basis (read-only)."""
import duckdb, sys
root = sys.argv[1]
con = duckdb.connect()
con.execute(f"""create view c as select *, regexp_extract(receipt_key, '/([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})/', 1) as rdate
               from '{root}/captures.parquet'""")
con.execute(f"create view r as select * from '{root}/readings/*.parquet'")
con.execute(f"create view d as select body_key, response_format, body_format from '{root}/documents.parquet'")
def q(label, s):
    print(label, con.execute(s).fetchall())
q("catalog response_format values", "select f, count(*) from (select unnest(response_format) f from d) group by 1 order by 2 desc limit 12")
q("catalog body_format values", "select f, count(*) from (select unnest(body_format) f from d) group by 1 order by 2 desc limit 12")
q("reading body_format values", "select f, count(*) from (select unnest(body_format) f from r) group by 1 order by 2 desc limit 12")
q("media types with pdf", "select media_type, count(distinct sha256) from c where media_type ilike '%pdf%' group by 1 order by 2 desc limit 8")
con.execute("""create temp table bodies as select sha256, max(bytes) bytes, max(stored_bytes) stored_bytes,
               bool_or(media_type ilike '%pdf%') mt_pdf from c where sha256 is not null group by sha256""")
con.execute("""create temp table cat as select regexp_extract(body_key, '([0-9a-f]{64})', 1) sha256,
                 bool_or(list_contains(response_format, 'pdf')) rf_pdf, bool_or(list_contains(body_format, 'pdf')) bf_pdf,
                 bool_or(len(response_format) > 0) rf_any from d group by 1""")
con.execute("""create temp table rd as select regexp_extract(body_key, '([0-9a-f]{64})', 1) sha256, status,
               list_contains(body_format, 'pdf') is_pdf, body_format from r""")
con.execute("""create temp table capchk as select distinct sha256 from c
               where rdate >= '2026-10-01' and resolution in ('saved','invalid_document')""")
con.execute("create temp table legacy as select distinct sha256 from rd where status='completed' and is_pdf")
con.execute("""create temp table k as select b.*, coalesce(cat.rf_pdf,false) rf_pdf, coalesce(cat.bf_pdf,false) bf_pdf,
                 coalesce(cat.rf_any,false) rf_any, rd.status rstatus, coalesce(rd.is_pdf,false) r_pdf,
                 b.sha256 in (select sha256 from capchk) capc, b.sha256 in (select sha256 from legacy) leg
               from bodies b left join cat using (sha256) left join rd using (sha256)
               where b.mt_pdf or coalesce(cat.rf_pdf,false) or coalesce(cat.bf_pdf,false) or coalesce(rd.is_pdf,false)""")
q("candidates", "select count(*), count(distinct sha256) from k")
q("by signal: (mt, rf, bf, r_pdf) -> n, covered, unchecked, unchecked GB", """select mt_pdf, rf_pdf, bf_pdf, r_pdf, count(*),
     count(*) filter (where capc or leg), count(*) filter (where not capc and not leg),
     round(sum(bytes) filter (where not capc and not leg)/1e9,2) from k group by all order by 5 desc""")
q("sniffed-pdf (rf or bf or r_pdf) -> n, covered, unchecked, GB", """select count(*), count(*) filter (where capc or leg),
     count(*) filter (where not capc and not leg), round(sum(bytes) filter (where not capc and not leg)/1e9,2)
     from k where rf_pdf or bf_pdf or r_pdf""")
q("media-type only, no catalog format at all, no reading", """select count(*), count(*) filter (where capc or leg) from k
     where mt_pdf and not rf_pdf and not bf_pdf and not r_pdf and not rf_any and rstatus is null""")
q("unchecked & sniffed pdf: sizes p50/p90/max MB, n=64MiB", """select quantile_cont(bytes,0.5)/1e6, quantile_cont(bytes,0.9)/1e6, max(bytes)/1e6,
     count(*) filter (where bytes=67108864), count(*) filter (where bytes>100e6) from k where (rf_pdf or bf_pdf or r_pdf) and not capc and not leg""")
print("---- capture-kind-only variant and size-limit readings")
con.execute("""create temp table capchk2 as select distinct sha256 from c
               where rdate >= '2026-10-01' and resolution in ('saved','invalid_document') and reference_kind='capture'""")
q("mt_pdf candidates: n, covered(capture-kind)+legacy, unchecked, GB", """select count(*),
     count(*) filter (where sha256 in (select sha256 from capchk2) or leg),
     count(*) filter (where not (sha256 in (select sha256 from capchk2) or leg)),
     round(sum(bytes) filter (where not (sha256 in (select sha256 from capchk2) or leg))/1e9,2) from k where mt_pdf""")
q("reading status for mt_pdf candidates", "select rstatus, count(*), round(sum(bytes)/1e9,1) from k where mt_pdf group by 1 order by 2 desc")
q("size_limit readings among candidates: n, GB, capture-checked", """select count(*), round(sum(bytes)/1e9,1), count(*) filter (where capc) from k where rstatus='size_limit'""")
q("candidates > 30 MB: n, GB, unchecked n, unchecked GB", """select count(*), round(sum(bytes)/1e9,1), count(*) filter (where not capc and not leg),
     round(sum(bytes) filter (where not capc and not leg)/1e9,1) from k where bytes > 30e6""")
q("legacy-only basis (no capture check): n", "select count(*) from k where leg and not capc")
q("capture basis by date: on 10-01 only / later", """select count(*) filter (where sha256 in (select sha256 from c where rdate='2026-10-01' and resolution in ('saved','invalid_document'))
     and sha256 not in (select sha256 from c where rdate>'2026-10-01' and resolution in ('saved','invalid_document'))) from k where capc""")
