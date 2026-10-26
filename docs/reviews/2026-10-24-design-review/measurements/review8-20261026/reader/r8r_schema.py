import duckdb
d='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/'
c=duckdb.connect()
for t in ['captures','documents','document-filenames']:
    print('==',t)
    print(c.sql(f"select count(*) from '{d}{t}.parquet'").fetchall())
    for r in c.sql(f"describe select * from '{d}{t}.parquet'").fetchall(): print('  ',r[0],r[1])
