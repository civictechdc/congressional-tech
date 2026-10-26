import duckdb, sys
c=duckdb.connect()
q=lambda s: print(c.sql(s).fetchall())
q("select count(*), count(*) filter (where try_cast(term_district as int) is null and term_district is not null), list(distinct term_district) filter (where try_cast(term_district as int) is null) from 'dl/member_terms.parquet'")
q("select count(*) filter (where try_cast(term_start as date) is null and term_start is not null), min(term_start), max(term_start), count(*) filter (where term_end is null) from 'dl/member_terms.parquet'")
q("select list(distinct rank)[1:15], count(*) filter (where try_cast(rank as int) is null and rank is not null), list(distinct position)[1:10], list(distinct congress) from 'dl/committee_assignments.parquet'")
q("select count(*), count(distinct (system_code, bioguide_id)), count(distinct (system_code, rank, bioguide_id)), count(*) filter (where rank is null) from 'dl/committee_assignments.parquet'")
q("select count(*), count(distinct system_code) from 'dl/committees.parquet'")
q("select h.startDate, h.endDate from (select unnest(history) h from 'dl/committees.parquet') limit 5")
q("""with h as (select system_code, unnest(history) h from 'dl/committees.parquet')
 select count(*) from (select a.system_code from h a join h b on a.system_code=b.system_code and a.h.officialName<>b.h.officialName
 and a.h.startDate< coalesce(b.h.endDate,'9999') and b.h.startDate < coalesce(a.h.endDate,'9999'))""")
