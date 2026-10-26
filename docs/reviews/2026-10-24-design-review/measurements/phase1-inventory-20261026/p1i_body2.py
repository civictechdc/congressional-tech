import duckdb
con=duckdb.connect('/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/phase1-inventory/p1i.duckdb')
q=lambda s: con.execute(s).fetchall()
print(q("select media[1], count(*), sum(bytes)/1e9, sum(stored_bytes)/1e9 from idx left join vb using(body_key) where vb.bf is null or len(vb.bf)=0 group by 1 order by 3 desc limit 10"))
print("totals", q("select count(*), sum(bytes)/1e9, sum(stored_bytes)/1e9 from idx"))
print("pdf candidates (media pdf or bf pdf)", q("select count(*), sum(stored_bytes)/1e9, count(*) filter (where list_contains(vb.bf,'pdf')), count(*) filter (where list_contains(media,'application/pdf')) from idx left join vb using(body_key) where list_contains(media,'application/pdf') or list_contains(vb.bf,'pdf')"))
print("pdf res sets", q("select res, count(*) from idx left join vb using(body_key) where list_contains(media,'application/pdf') or list_contains(vb.bf,'pdf') group by 1 order by 2 desc limit 15"))
print("pdf rf sets", q("select rf, count(*) from idx left join vb using(body_key) where list_contains(vb.bf,'pdf') group by 1 order by 2 desc limit 10"))
