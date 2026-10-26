"""Does legacy_pdf_checks add coverage beyond the capture check, under several readings of DM 6.1? (read-only)"""
import duckdb, sys
root = sys.argv[1]
con = duckdb.connect()
con.execute(f"""create view c as select *, regexp_extract(receipt_key, '/([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})/', 1) as rdate
               from '{root}/captures.parquet'""")
con.execute(f"create view r as select regexp_extract(body_key, '([0-9a-f]{{64}})', 1) sha256, status, list_contains(body_format,'pdf') is_pdf from '{root}/readings/*.parquet'")
con.execute("create temp table k as select sha256, max(bytes) bytes from c where media_type ilike '%pdf%' group by 1")
con.execute("create temp table legacy as select distinct sha256 from r where status='completed' and is_pdf")
variants = {
 "any row >= 10-01, saved|invalid": "rdate >= '2026-10-01' and resolution in ('saved','invalid_document')",
 "rows > 10-01 only": "rdate > '2026-10-01' and resolution in ('saved','invalid_document')",
 "capture kind, exact-bytes, >= 10-01": "rdate >= '2026-10-01' and resolution in ('saved','invalid_document') and reference_kind='capture' and fidelity='exact-bytes'",
 "capture kind, exact-bytes, > 10-01": "rdate > '2026-10-01' and resolution in ('saved','invalid_document') and reference_kind='capture' and fidelity='exact-bytes'",
}
for name, cond in variants.items():
    con.execute(f"create or replace temp table cap as select distinct sha256 from c where {cond}")
    r = con.execute("""select count(*), count(*) filter (where sha256 in (select sha256 from cap)),
        count(*) filter (where sha256 in (select sha256 from legacy)),
        count(*) filter (where sha256 in (select sha256 from cap) and sha256 in (select sha256 from legacy)),
        count(*) filter (where sha256 in (select sha256 from legacy) and sha256 not in (select sha256 from cap)),
        count(*) filter (where sha256 not in (select sha256 from cap) and sha256 not in (select sha256 from legacy)),
        round(sum(bytes) filter (where sha256 not in (select sha256 from cap) and sha256 not in (select sha256 from legacy))/1e9,1)
        from k""").fetchone()
    print(f"{name:40s} cand={r[0]} cap={r[1]} legacy={r[2]} both={r[3]} legacy_only={r[4]} unchecked={r[5]} ({r[6]} GB)")
