import duckdb
base="/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/"
con=duckdb.connect()
c=f"read_parquet('{base}captures.parquet')"
q=lambda s: con.execute(s).fetchall()
print("reference_kind:", q(f"select reference_kind, count(*) from {c} group by 1 order by 2 desc"))
print("fidelity:", q(f"select fidelity, count(*) from {c} group by 1 order by 2 desc"))
print("resolution:", q(f"select resolution, count(*) from {c} group by 1 order by 2 desc limit 12"))
print("null retrieved_at rows:", q(f"select count(*) from {c} where retrieved_at is null or retrieved_at=''"))
print("families:", q(f"select family, count(*) from {c} group by 1 order by 2 desc"))
pats={
 "congress.gov/<c>/meeting/": r"congress\.gov/[0-9]+/meeting/",
 "www.congress.gov/event/": r"congress\.gov/event/",
 "api.congress.gov committee-meeting": r"api\.congress\.gov/v3/committee-meeting/",
 "api.congress.gov any": r"api\.congress\.gov/",
 "api.congress.gov format=xml": r"api\.congress\.gov/.*format=xml",
 "api.congress.gov format=json": r"api\.congress\.gov/.*format=json",
 "docs.house.gov/meetings/": r"docs\.house\.gov/meetings/",
 "docs.house.gov .xml": r"docs\.house\.gov/.*\.xml($|\?)",
 "docs.house.gov ByEvent": r"docs\.house\.gov/Committee/Calendar/ByEvent",
 "govinfo CHRG pkg": r"govinfo\.gov/.*CHRG-",
 "govinfo mods": r"govinfo\.gov/.*mods\.xml",
 "govinfo zip": r"govinfo\.gov/.*\.zip",
 "youtube": r"youtube\.com|youtu\.be|googlevideo",
 "senate.gov player/isvp": r"senate\.gov/.*(isvp|player)",
}
for k,p in pats.items():
    n=q(f"select count(distinct context_url) from {c} where regexp_matches(context_url, '{p}')")[0][0]
    print(f"{k:40s} distinct context_url: {n}")
print("--- sample api.congress.gov xml URLs (hosts/paths only, query stripped):")
for r in q(f"select distinct regexp_replace(context_url,'\\?.*$','') from {c} where regexp_matches(context_url, 'api\\.congress\\.gov/.*format=xml') limit 5"): print("  ",r[0])
print("--- sample api.congress.gov committee-meeting paths:")
for r in q(f"select distinct regexp_replace(context_url,'\\?.*$','') from {c} where regexp_matches(context_url, 'api\\.congress\\.gov/v3/committee-meeting/') limit 5"): print("  ",r[0])
print("--- sample docs.house.gov xml:")
for r in q(f"select distinct context_url from {c} where regexp_matches(context_url, 'docs\\.house\\.gov/.*\\.xml') limit 5"): print("  ",r[0])
print("--- sample govinfo CHRG package ids (extract):")
for r in q(f"select regexp_extract(context_url,'(CHRG-[0-9]+[hsj]hrg[0-9A-Za-z]+)',1) p, count(*) from {c} where regexp_matches(context_url,'CHRG-') group by 1 order by 2 desc limit 8"): print("  ",r)
print("CHRG jackets with leading zero:", q(f"select count(distinct regexp_extract(context_url,'(CHRG-[0-9]+[hsj]hrg0[0-9]+)',1)) from {c} where regexp_matches(context_url,'CHRG-[0-9]+[hsj]hrg0')")[0][0])
print("CHRG distinct packages:", q(f"select count(distinct regexp_extract(context_url,'(CHRG-[0-9]+[hsj]hrg[0-9]+)',1)) from {c} where regexp_matches(context_url,'CHRG-[0-9]+[hsj]hrg[0-9]+')")[0][0])
print("CHRG jacket length distribution:", q(f"select length(regexp_extract(context_url,'CHRG-[0-9]+[hsj]hrg([0-9]+)',1)) l, count(distinct regexp_extract(context_url,'(CHRG-[0-9]+[hsj]hrg[0-9]+)',1)) from {c} where regexp_matches(context_url,'CHRG-[0-9]+[hsj]hrg[0-9]+') group by 1 order by 1"))
