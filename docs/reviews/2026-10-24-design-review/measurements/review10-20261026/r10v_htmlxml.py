import duckdb
C='/Users/mikewolfd/Work/congressional-tech/.cache/nara-filename-estimate-20261015/publication-all-20261015/new-captures.parquet'
con=duckdb.connect(); con.execute("SET threads=4; SET memory_limit='6GB'")
cols=[r[0] for r in con.execute(f"describe select * from read_parquet('{C}')").fetchall()]
print([c for c in cols if any(k in c for k in ('status','media','http','code','body_key'))])
con.execute(f"""create table b as select body_key,
  bool_or(regexp_matches(lower(split_part(media_type,';',1)),'html|xml')) hx,
  bool_or(regexp_matches(lower(split_part(media_type,';',1)),'json')) js,
  bool_or(regexp_matches(lower(split_part(media_type,';',1)),'html|xml') and http_status between 200 and 299) hx2
  from read_parquet('{C}') where body_key is not null group by 1""")
print(con.execute("""select count(*) filter (where hx) html_xml, count(*) filter (where hx2) html_xml_2xx,
  count(*) filter (where js and not hx) json_only, count(*) filter (where hx or js) html_xml_json from b""").fetchall())
