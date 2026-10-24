"""Verify revision-5 numeric claims against the Oct 19 snapshot."""
import duckdb, time
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect(); con.execute("SET memory_limit='8GB'; SET threads=4; SET preserve_insertion_order=false;")
cap = f"read_parquet('{base}/captures.parquet')"
docs = f"read_parquet('{base}/documents.parquet')"
def q(title, sql):
    t=time.time(); r = con.execute(sql).fetchall(); print(f"--- {title} ({time.time()-t:.1f}s)"); [print("   ", row) for row in r[:40]]; return r

q("1. cut-off bodies: bytes or stored_bytes == 64 MiB", f"""
select count(distinct sha256) bodies, count(*) attempts, count(distinct context_url) urls,
       list(distinct resolution) resolutions, list(distinct http_status) statuses
from {cap} where bytes = 67108864 or stored_bytes = 67108864""")
q("1b. URLs whose every body is cut off", f"""
with u as (select context_url, count(distinct sha256) bodies, sum(case when bytes=67108864 or stored_bytes=67108864 then 1 else 0 end) cut, count(*) n
           from {cap} where sha256 is not null group by 1)
select count(*) urls_all_cut from u where cut = n""")

q("2. Oct 15 recovery receipts", f"""
select count(*) rows_, count(distinct receipt_key) files, list(distinct reference_kind) ref_kinds, list(distinct fidelity) fidelities,
       list(distinct resolution) resolutions, list(distinct capture_date) dates, min(receipt_key) smallest_key_example
from {cap} where receipt_key like 'receipts/documents/2026-10-15/download-filename-recovery-all-%'""")
q("2b. smallest Oct 15 recovery receipt file (for a public fetch)", f"""
select receipt_key, count(*) n from {cap} where receipt_key like 'receipts/documents/2026-10-15/download-filename-recovery-all-%' group by 1 order by 2 asc limit 2""")

q("3. successful HTML bodies: page-like vs file-like link shape; page-like under 16 KB", f"""
with h as (
  select sha256, any_value(context_url) url, max(bytes) bytes
  from {cap} where sha256 is not null and http_status between 200 and 299 and media_type ilike 'text/html%' group by 1),
c as (select *, (regexp_matches(url, '\\.(pdf|zip|docx?|xml)([?#]|$)', 'i') or url ilike '%/download/%' or url ilike '%download=1%' or url ilike '%file_id=%') file_like from h)
select sum(case when not file_like then 1 else 0 end) page_like, sum(case when file_like then 1 else 0 end) file_like,
       sum(case when not file_like and bytes < 16384 then 1 else 0 end) page_like_under_16k,
       sum(case when not file_like and bytes < 2048 then 1 else 0 end) page_like_under_2k from c""")

q("4. documents with >1 body, and what the extra bodies are", f"""
with d as (select document_id, body_keys from {docs} where len(body_keys) > 1),
     b as (select body_key, any_value(http_status) st, any_value(resolution) res, any_value(media_type) mt, max(bytes) bytes, any_value(fidelity) fid
           from {cap} where body_key is not null group by 1),
     j as (select d.document_id, b.* from d, unnest(d.body_keys) as t(k) left join b on b.body_key = t.k)
select (select count(*) from d) docs_multi_body,
       count(distinct case when st is not null and st not between 200 and 299 then document_id end) docs_with_non2xx_body,
       count(distinct case when st = 503 or res = 'retry_later' then document_id end) docs_with_503_retry_later,
       count(distinct case when mt is null and st between 200 and 299 then document_id end) docs_with_untyped_2xx_body,
       count(distinct case when bytes = 67108864 then document_id end) docs_with_cutoff_body,
       count(distinct case when fid = 'retained-file' then document_id end) docs_with_retained_import_body,
       count(distinct case when st is null then document_id end) docs_with_body_missing_from_captures
from j""")

q("5. saved-file date classes (document's primary body_key)", f"""
with b as (select body_key, max(retrieved_at) ra, list(distinct capture_date) dates from {cap} where body_key is not null group by 1)
select count(*) docs,
       sum(case when b.ra is not null then 1 else 0 end) real_fetch_date,
       sum(case when b.ra is null and list_contains(b.dates, '2026-09-29') then 1 else 0 end) import_day_only,
       sum(case when b.ra is null and not list_contains(b.dates, '2026-09-29') then 1 else 0 end) no_date,
       sum(case when b.body_key is null then 1 else 0 end) body_not_in_captures
from {docs} d left join b on b.body_key = d.body_key""")

q("6. fingerprint candidates: URLs with >=2 distinct complete real non-HTML files", f"""
with r as (select context_url url, sha256 from {cap}
           where sha256 is not null and http_status between 200 and 299 and resolution in ('saved','digest_verified','path_verified')
             and bytes <> 67108864 and bytes > 0
             and (media_type ilike 'application/pdf%' or media_type ilike 'application/zip%' or media_type ilike '%xml%')
           group by 1,2),
     u as (select url, count(*) n from r group by 1)
select count(*) urls_with_2plus, sum(n) bodies_at_them, max(n) max_bodies from u where n >= 2""")
q("6b. same, HTML page-like >= 2 KB included", f"""
with r as (select context_url url, sha256 from {cap}
           where sha256 is not null and http_status between 200 and 299 and resolution in ('saved','digest_verified','path_verified')
             and bytes <> 67108864 and bytes > 0
             and (media_type ilike 'application/pdf%' or media_type ilike 'application/zip%' or media_type ilike '%xml%'
                  or (media_type ilike 'text/html%' and bytes >= 2048 and not (regexp_matches(context_url, '\\.(pdf|zip|docx?|xml)([?#]|$)', 'i') or context_url ilike '%/download/%' or context_url ilike '%download=1%' or context_url ilike '%file_id=%')))
           group by 1,2),
     u as (select url, count(*) n from r group by 1)
select count(*) urls_with_2plus, sum(n) bodies_at_them, max(n) max_bodies from u where n >= 2""")
q("6c. of the non-HTML candidates, how many URLs have 2+ PDFs of different sizes (proxy for 'different content')", f"""
with r as (select context_url url, sha256, max(bytes) bytes from {cap}
           where sha256 is not null and http_status between 200 and 299 and resolution in ('saved','digest_verified','path_verified')
             and bytes <> 67108864 and bytes > 0 and media_type ilike 'application/pdf%' group by 1,2),
     u as (select url, count(*) n, count(distinct bytes) sizes from r group by 1)
select count(*) urls_2plus_pdf, sum(case when sizes>1 then 1 else 0 end) urls_with_differing_sizes from u where n >= 2""")

q("7. real files in documents' body sets (links rows) and documents with no real file", f"""
with b as (select body_key, any_value(http_status) st, any_value(resolution) res, any_value(media_type) mt, max(bytes) bytes, any_value(fidelity) fid, count(distinct context_url) urls
           from {cap} where body_key is not null group by 1),
     j as (select d.document_id, t.k body_key, b.st, b.res, b.mt, b.bytes, b.fid, b.urls from {docs} d, unnest(d.body_keys) as t(k) left join b on b.body_key = t.k),
     real as (select * from j where st between 200 and 299 and res in ('saved','digest_verified','path_verified') and bytes <> 67108864 and bytes > 0
              and fid <> 'retained-file' and urls <= 100
              and (mt ilike 'application/pdf%' or mt ilike 'application/zip%' or mt ilike '%xml%' or mt ilike 'text/html%'))
select (select count(distinct body_key) from real) real_bodies, (select count(*) from real) real_body_refs,
       (select count(*) from {docs}) docs, (select count(distinct document_id) from real) docs_with_real_file""")
q("8. body sets: refs and distinct bodies", f"select sum(len(body_keys)) refs, count(*) docs, sum(case when len(body_keys)=0 then 1 else 0 end) no_body from {docs}")
