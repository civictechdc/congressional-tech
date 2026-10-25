"""Spot-check load-bearing numbers in design rev 7 / data model rev 5 against the Oct 19 snapshot."""
import duckdb, time
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect(); con.execute("SET memory_limit='8GB'; SET threads=4; SET preserve_insertion_order=false;")
cap = f"read_parquet('{base}/captures.parquet')"; docs = f"read_parquet('{base}/documents.parquet')"; fn = f"read_parquet('{base}/filenames.parquet')"
def q(t, s):
    t0=time.time(); r = con.execute(s).fetchall(); print(f"--- {t} ({time.time()-t0:.1f}s)"); [print("   ", row) for row in r[:12]]

# 1. URLs differing only by scheme / www. / host case / trailing slash (DM §3.0: 64,860, 5.6%)
con.execute(f"""create table urls as select distinct context_url u from {cap} where context_url is not null""")
con.execute("""create table norm as select u,
   lower(regexp_extract(u, '^([a-zA-Z]+)://', 1)) scheme,
   regexp_replace(lower(regexp_extract(u, '^[a-zA-Z]+://([^/?#]+)', 1)), '^www\\.', '') host,
   regexp_replace(regexp_replace(regexp_extract(u, '^[a-zA-Z]+://[^/?#]+([^?#]*)', 1), '/$', ''), '^$', '/') path,
   regexp_extract(u, '\\?([^#]*)', 1) query
 from urls""")
q("1. URL groups differing only by scheme/www/host-case/trailing slash", """
with g as (select host, path, query, count(*) n from norm group by 1,2,3 having count(*) > 1)
select (select count(*) from urls) urls, sum(n) urls_in_groups, count(*) groups_, round(100.0*sum(n)/(select count(*) from urls),1) pct from g""")
q("1b. of those, groups differing only by scheme or www. (same path incl. slash): do they serve identical latest bytes?", f"""
with latest as (select context_url u, arg_max(sha256, coalesce(retrieved_at,'')) sha from {cap} where sha256 is not null group by 1),
     k as (select n.u, n.host, regexp_extract(n.u, '^[a-zA-Z]+://[^/?#]+([^?#]*)', 1) rawpath, n.query, l.sha from norm n left join latest l using(u)),
     g as (select host, rawpath, query, count(*) n, count(distinct sha) shas, count(sha) with_sha from k group by 1,2,3 having count(*) > 1)
select count(*) groups_, sum(case when with_sha>=2 and shas=1 then 1 else 0 end) identical_bytes, sum(case when with_sha>=2 and shas>1 then 1 else 0 end) differing, sum(case when with_sha<2 then 1 else 0 end) not_comparable from g""")

# 2. query strings (DM §3.0: 13,930 URLs, 1.2%; download groups 916)
q("2. URLs with a query string", "select count(*) n, round(100.0*count(*)/(select count(*) from urls),2) pct from urls where u like '%?%'")
q("2b. download= groups: URL with ?download=... whose base URL also exists; do bodies differ?", f"""
with d as (select u, regexp_replace(u, '[?&]download=[^&#]*', '') base_ from urls where regexp_matches(u, '[?&]download=')),
     latest as (select context_url u, list(distinct sha256) shas from {cap} where sha256 is not null group by 1)
select count(*) groups_, sum(case when l1.shas is not null and l2.shas is not null and list_has_any(l1.shas, l2.shas) then 1 else 0 end) share_a_body,
       sum(case when l1.shas is not null and l2.shas is not null and not list_has_any(l1.shas, l2.shas) then 1 else 0 end) disjoint
from d join urls b on b.u = regexp_replace(d.base_, '\\?$', '') left join latest l1 on l1.u = d.u left join latest l2 on l2.u = b.u""")

# 3. rendition groups: same directory + same stem, >= 2 document extensions (DM §3.3: 16,156 groups, 32,547 documents)
q("3. same-directory same-stem groups with >= 2 document extensions", f"""
with s as (select document_id, source_url, filename,
                  regexp_replace(source_url, '/[^/]*$', '') dir,
                  lower(regexp_extract(filename, '^(.*)\\.([A-Za-z0-9]+)$', 1)) stem,
                  lower(regexp_extract(filename, '^(.*)\\.([A-Za-z0-9]+)$', 2)) ext
           from {fn} where filename is not null and source_url is not null),
     g as (select dir, stem, count(distinct ext) exts, count(distinct document_id) docs_, list(distinct ext) extl from s
           where ext in ('pdf','xml','htm','html','doc','docx','txt') and stem not in ('index','document','download','file','default','') and length(stem) > 0
           group by 1,2 having count(distinct ext) >= 2)
select count(*) groups_, sum(docs_) documents_in_groups, sum(case when docs_>1 then 1 else 0 end) groups_split_across_docs, sum(case when docs_>1 then docs_ else 0 end) docs_in_split_groups from g""")

# 4. meeting and govinfo coverage (DM §3.3: 45,761 docs / 6,551 house events; 142,997 / 11,634 congress.gov; 141,694 / 36,943 govinfo; overlap 4,715 of 6,550)
con.execute(f"create table du as select document_id, unnest(source_urls) su from {docs}")
q("4. docs.house.gov meeting URLs", """select count(distinct document_id) docs_, count(distinct regexp_extract(su, 'docs\\.house\\.gov/meetings/[A-Za-z]{2}/[A-Za-z0-9]+/\\d{8}/(\\d+)', 1)) events from du where regexp_matches(su, 'docs\\.house\\.gov/meetings/[A-Za-z]{2}/[A-Za-z0-9]+/\\d{8}/\\d+')""")
q("4b. congress.gov meeting URLs", """select count(distinct document_id) docs_, count(distinct regexp_extract(su, 'congress\\.gov/\\d+/meeting/(house|senate|joint)/(\\d+)', 2)) meetings from du where regexp_matches(su, 'congress\\.gov/\\d+/meeting/(house|senate|joint)/\\d+')""")
q("4c. overlap of House event IDs with Congress.gov house meeting IDs", """
with h as (select distinct regexp_extract(su, 'docs\\.house\\.gov/meetings/[A-Za-z]{2}/[A-Za-z0-9]+/\\d{8}/(\\d+)', 1) id from du where regexp_matches(su, 'docs\\.house\\.gov/meetings/[A-Za-z]{2}/[A-Za-z0-9]+/\\d{8}/\\d+')),
     c as (select distinct regexp_extract(su, 'congress\\.gov/\\d+/meeting/house/(\\d+)', 1) id from du where regexp_matches(su, 'congress\\.gov/\\d+/meeting/house/\\d+'))
select (select count(*) from h) house_ids, (select count(*) from c) cg_house_ids, (select count(*) from h join c using(id)) overlap""")
q("4d. govinfo packages", """select count(distinct document_id) docs_, count(distinct regexp_extract(su, 'govinfo\\.gov/content/pkg/([A-Za-z0-9._-]+)', 1)) packages from du where regexp_matches(su, 'govinfo\\.gov/content/pkg/[A-Za-z0-9._-]+')""")

# 5. identical real web pages at several addresses (design §6.1: 265 pages at 2-44 addresses)
q("5. real HTML pages (2xx, page-shaped by the 8 patterns, >= 2 KB, <= 100 URLs) shared by >= 2 URLs", f"""
with h as (select sha256, count(distinct context_url) urls, max(bytes) bytes from {cap}
           where sha256 is not null and http_status between 200 and 299 and media_type ilike 'text/html%'
             and not (regexp_matches(context_url, '\\.(pdf|zip|docx?|xml)([?#]|$)', 'i') or context_url ilike '%/download/%' or context_url ilike '%download=1%' or context_url ilike '%file_id=%')
           group by 1)
select count(*) pages, min(urls) min_urls, max(urls) max_urls, sum(urls) addresses from h where urls between 2 and 100 and bytes >= 2048""")

# 8. house-naming field coverage (DM §2.3: congress 34.7%, meeting_date 16.0%, GPO 14.2%, measure 2-4%, member IDs ~3%)
q("8. field coverage over all source files", f"""
select count(*) n,
  round(100.0*sum(case when len(congress)>0 then 1 else 0 end)/count(*),1) congress_pct,
  round(100.0*sum(case when len(meeting_date)>0 then 1 else 0 end)/count(*),1) meeting_date_pct,
  round(100.0*sum(case when len(hearing_package_id)>0 or len(publication_number)>0 or len(publication_code)>0 then 1 else 0 end)/count(*),1) gpo_pct,
  round(100.0*sum(case when len(measure_number)>0 then 1 else 0 end)/count(*),1) measure_pct,
  round(100.0*sum(case when len(bioguide_token)>0 then 1 else 0 end)/count(*),1) bioguide_pct,
  round(100.0*sum(case when len(date_token_candidates)>1 then 1 else 0 end)/count(*),1) ambiguous_date_pct
from {fn}""")

# 9. bodiless lines (DM §2.1: 1,041,863 of 2,596,054)
q("9. rows with no sha (bodiless lines) and distinct lines", f"select sum(case when sha256 is null then 1 else 0 end) no_sha_rows, count(distinct (receipt_key, receipt_line)) lines_ from {cap}")

# 10. occurrences per document max (int16 ordinal?)
q("10. max occurrences per document today; documents over 32,767", f"select max(len(source_occurrences)) mx, sum(case when len(source_occurrences) > 32767 then 1 else 0 end) over_int16, sum(case when len(source_occurrences) > 1024 then 1 else 0 end) over_1024 from {docs}")
