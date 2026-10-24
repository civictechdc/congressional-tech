import duckdb, time
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect()
con.execute("SET memory_limit='6GB'; SET threads=4;")
cap = f"read_parquet('{base}/captures.parquet')"

def q(sql, title=None, limit=None):
    t = time.time()
    rows = con.execute(sql).fetchall()
    cols = [d[0] for d in con.description]
    print(f"--- {title or sql[:80]}   ({time.time()-t:.2f}s)")
    print("  " + " | ".join(cols))
    for r in rows[: (limit or 60)]:
        print("  " + " | ".join(str(x) for x in r))
    return rows

q(f"""select count(*) attempts, count(distinct receipt_key) receipts, count(distinct sha256) bodies,
      count(distinct stored_sha256) stored_bodies, count(distinct context_url) urls, count(distinct body_key) body_keys,
      count(distinct source_file) source_files, min(capture_date) first_day, max(capture_date) last_day
      from {cap}""", "overall")

q(f"select family, count(*) n, count(distinct sha256) bodies, count(distinct context_url) urls, count(distinct receipt_key) receipts from {cap} group by 1 order by 2 desc", "by family")

q(f"""select media_type, count(*) attempts, count(distinct sha256) bodies,
      sum(bytes) sum_bytes_all_attempts, sum(stored_bytes) sum_stored_all_attempts
      from {cap} group by 1 order by 2 desc""", "by media type", 25)

# distinct body bytes (one row per sha)
q(f"""with b as (select sha256, any_value(media_type) mt, max(bytes) bytes, max(stored_bytes) stored_b from {cap} where sha256 is not null group by 1)
      select mt, count(*) bodies, sum(bytes) orig_bytes, sum(stored_b) stored_bytes, round(avg(bytes)) avg_orig, median(bytes) med_orig from b group by 1 order by 2 desc""", "distinct bodies by media type", 25)

q(f"select resolution, http_status, count(*) n from {cap} group by 1,2 order by 3 desc", "resolution/status", 20)
q(f"select reference_kind, count(*) n from {cap} group by 1 order by 2 desc", "reference_kind", 10)
q(f"select fidelity, count(*) n from {cap} group by 1 order by 2 desc", "fidelity", 10)

# daily change: attempts per capture_date for last 45 days; new bodies (first seen) per day
q(f"""with first_seen as (select sha256, min(capture_date) d from {cap} where sha256 is not null group by 1),
      per_day as (select capture_date d, count(*) attempts, count(distinct receipt_key) receipts, count(distinct sha256) bodies_touched from {cap} group by 1),
      nb as (select d, count(*) new_bodies from first_seen group by 1)
      select per_day.d, attempts, receipts, bodies_touched, coalesce(new_bodies,0) new_bodies
      from per_day left join nb using(d) order by d desc limit 45""", "last 45 days")

q(f"""with per_day as (select capture_date d, count(*) attempts from {cap} group by 1)
      select count(*) n_days, median(attempts) med_attempts, avg(attempts) avg_attempts, quantile_cont(attempts,0.9) p90, max(attempts) mx from per_day""", "attempts per day distribution")

q(f"""with first_seen as (select sha256, min(capture_date) d from {cap} where sha256 is not null group by 1),
      nb as (select d, count(*) new_bodies from first_seen group by 1)
      select count(*) n_days, median(new_bodies) med, avg(new_bodies) avg, quantile_cont(new_bodies,0.9) p90, max(new_bodies) mx from nb""", "new bodies per day distribution")

# receipts: lines per receipt
q(f"""with r as (select receipt_key, count(*) lines, max(receipt_line) max_line from {cap} group by 1)
      select count(*) receipts, median(lines) med_lines, avg(lines) avg_lines, max(lines) max_lines, min(lines) min_lines from r""", "lines per receipt")
q(f"select receipt_key, count(*) n from {cap} group by 1 order by 2 desc limit 5", "largest receipts")
q(f"select receipt_key, count(*) n from {cap} group by 1 order by random() limit 8", "random receipts")
q(f"select receipt_key from {cap} where family like '%house%' or family like '%senate%' group by 1 order by random() limit 4", "random receipts (house/senate)")

# bodies per url
q(f"""with u as (select context_url, count(*) attempts, count(distinct sha256) bodies from {cap} group by 1)
      select count(*) urls, avg(attempts) avg_attempts, median(attempts) med_attempts, max(attempts) max_attempts, avg(bodies) avg_bodies, sum(case when bodies>1 then 1 else 0 end) urls_with_multiple_bodies from u""", "attempts per url")

# body shared across urls
q(f"""with s as (select sha256, count(distinct context_url) urls from {cap} where sha256 is not null group by 1)
      select count(*) bodies, sum(case when urls>1 then 1 else 0 end) shared_bodies, max(urls) max_urls, avg(urls) avg_urls from s""", "urls per body")

# sample rows
q(f"select * from {cap} where sha256 is not null order by random() limit 3", "sample rows", 3)
q(f"select body_key, sha256, stored_sha256, media_type, fidelity, bytes, stored_bytes from {cap} where sha256 is not null and sha256<>stored_sha256 order by random() limit 3", "sample stored!=orig", 3)
q(f"select count(*) n, sum(case when sha256=stored_sha256 then 1 else 0 end) same, sum(case when sha256<>stored_sha256 then 1 else 0 end) diff from {cap} where sha256 is not null", "stored vs orig sha equality")
