import duckdb,sys
D=sys.argv[1]; c=duckdb.connect()
def q(s,lim=15):
    print('>>',s.replace(D+'/','')[:260])
    for r in c.sql(s).fetchall()[:lim]: print('  ',r)
c.sql(f"create view k as select * from '{D}/committees.parquet'")
q("select count(*), count(distinct system_code), count(*) filter (where is_subcommittee) from k")
# raw name collisions, exact strings
q("select count(*) as nnames, sum(n) as ncodes from (select name, count(distinct system_code) n from k group by 1 having n>1)")
q("select name, count(distinct system_code) n from k group by 1 having n>1 order by 2 desc",8)
# casefold/whitespace-relaxed
q("select count(*) from (select lower(trim(regexp_replace(name,'\\s+',' ','g'))) nm, count(distinct system_code) n from k group by 1 having n>1)")
# official names in history
c.sql("create table h as select system_code, is_subcommittee, unnest(history) x from k")
q("select count(*), count(x.officialName) from h")
q("select count(*) from k where is_subcommittee and (history is null or len(history)=0 or len(list_filter(history, e->e.officialName is not null))=0)")
q("select count(*) from k where is_subcommittee")
q("select count(*) as nnames from (select x.officialName o, count(distinct system_code) n from h where x.officialName is not null group by 1 having n>1)")
q("select x.officialName o, count(distinct system_code) n from h where x.officialName is not null group by 1 having n>1 order by 2 desc",5)
# full key: (name, chamber) collisions, and name+parent
q("select count(*) from (select name, chamber, count(distinct system_code) n from k group by all having n>1)")
q("select count(*) from (select name, parent_system_code, count(distinct system_code) n from k group by all having n>1)")
