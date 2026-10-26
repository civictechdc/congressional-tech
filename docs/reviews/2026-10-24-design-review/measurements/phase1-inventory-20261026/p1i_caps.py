import duckdb, sys
p = sys.argv[1]
con = duckdb.connect()
con.execute("SET threads=4; SET memory_limit='6GB'")
q = lambda s: con.execute(s).fetchall()
t = f"read_parquet('{p}')"
print("rows", q(f"select count(*), count(sha256), count(distinct sha256), count(stored_sha256), count(distinct body_key) from {t}"))
print("stored!=sha", q(f"select count(*) from {t} where stored_sha256 is not null and sha256 is not null and stored_sha256<>sha256"))
print("body_key suffix", q(f"select regexp_extract(body_key,'(\\.[a-z]+)$',1) s, count(distinct body_key) from {t} where body_key is not null group by 1 order by 2 desc limit 10"))
print("body_key sample", q(f"select body_key, sha256, stored_sha256 from {t} where body_key is not null limit 3"))
print("ref kinds", q(f"select reference_kind, count(*) from {t} group by 1 order by 2 desc"))
print("fidelity", q(f"select fidelity, count(*) from {t} group by 1 order by 2 desc limit 10"))
print("capture_date range", q(f"select min(capture_date), max(capture_date), count(distinct receipt_key) from {t}"))
print("media pdf bodies", q(f"select count(distinct sha256) from {t} where media_type ilike '%pdf%'"))
