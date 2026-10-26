import duckdb
base="/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/"
con=duckdb.connect()
c=f"read_parquet('{base}captures.parquet')"
d=f"read_parquet('{base}documents.parquet')"
q=lambda s: con.execute(s).fetchall()
print("leading-zero CHRG:", q(f"select distinct regexp_extract(context_url,'(CHRG-[0-9]+[hsj]hrg0[0-9]+)',1) from {c} where regexp_matches(context_url,'CHRG-[0-9]+[hsj]hrg0[0-9]')"))
for col in ["record_role","source_chamber","source_meeting_id","source_meeting_key","source_document_group","source_record_type","measure_references","source_document_type","document_kind"]:
    rows=q(f"select v, count(*) n from (select unnest({col}) v from {d}) group by 1 order by 2 desc limit 7")
    print(f"--- {col}:", rows)
print("--- source_meeting_id with letter prefix:", q(f"select count(distinct v) from (select unnest(source_meeting_id) v from {d}) where regexp_matches(v,'^[A-Z]')"))
print("--- source_meeting_id all-digit:", q(f"select count(distinct v) from (select unnest(source_meeting_id) v from {d}) where regexp_matches(v,'^[0-9]+$')"))
