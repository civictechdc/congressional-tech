"""F3: does today's catalog already put a GovInfo ZIP and its HTML/PDF members in one document? (decides whether rule (a) is an E4 change)"""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
con.execute("CREATE TEMP TABLE z AS SELECT DISTINCT sha zsha, rk, rl FROM real WHERE fmt='zip' AND mem IS NULL AND ctx ILIKE '%govinfo.gov%'")
con.execute("CREATE TEMP TABLE zm AS SELECT DISTINCT z.zsha, m.sha msha, m.fmt FROM z JOIN c m ON m.rk=z.rk AND m.rl=z.rl AND m.mem IS NOT NULL AND m.fmt IN ('html','pdf')")
con.execute(f"CREATE TEMP TABLE fd AS SELECT DISTINCT regexp_extract(body_key,'([0-9a-f]{{64}})',1) sha, document_id FROM read_parquet('{B}filenames.parquet') WHERE body_key IS NOT NULL")
print(con.execute("""WITH x AS (SELECT zm.zsha, bool_or(dz.document_id = dm.document_id) same_doc FROM zm JOIN fd dz ON dz.sha=zm.zsha JOIN fd dm ON dm.sha=zm.msha GROUP BY 1)
  SELECT same_doc, count(*) FROM x GROUP BY 1""").fetchall())
