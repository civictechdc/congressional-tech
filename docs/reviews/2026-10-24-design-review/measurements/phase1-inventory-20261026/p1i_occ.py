import duckdb
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/filenames.parquet'
con=duckdb.connect(); con.execute("SET threads=4; SET memory_limit='8GB'")
q=lambda s: con.execute(s).fetchall()
con.execute(f"create table o as select unnest(source_occurrences, recursive:=false) occ from read_parquet('{A}', columns=['source_occurrences'])" if False else
 f"create table o as select unnest(source_occurrences) occ from (select source_occurrences from read_parquet('{A}'))")
print(q("select count(*) from o"))
print(q("""select occ.source_page_type, count(*), count(distinct occ.source_page_sha256[1]), count(*) filter (where len(occ.source_witness_name)>0),
   count(distinct occ.source_page_sha256[1]) filter (where len(occ.source_witness_name)>0)
   from o group by 1 order by 2 desc limit 12"""))
print(q("select occ.source_association_basis, count(*) from o group by 1 order by 2 desc limit 12"))
