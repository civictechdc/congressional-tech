import duckdb
c=duckdb.connect()
print(c.sql("""with h as (select system_code, unnest(history) h from 'dl/committees.parquet')
 select a.system_code, a.h.officialName, a.h.startDate, a.h.endDate, b.h.officialName, b.h.startDate, b.h.endDate from h a join h b on a.system_code=b.system_code and a.h.officialName<b.h.officialName
 and a.h.startDate< coalesce(b.h.endDate,'9999') and b.h.startDate < coalesce(a.h.endDate,'9999') limit 3""").fetchall())
print(c.sql("""with h as (select unnest(history) h from 'dl/committees.parquet') select count(*), count(*) filter (where h.startDate not like '%T04:%' and h.startDate not like '%T05:%') from h""").fetchall())
