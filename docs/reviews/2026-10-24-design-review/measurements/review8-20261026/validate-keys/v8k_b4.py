import duckdb,sys
D=sys.argv[1]; c=duckdb.connect()
def q(s,lim=20):
    print('>>',s.replace(D+'/','')[:300])
    for r in c.sql(s).fetchall()[:lim]: print('  ',r)
c.sql(f"create view b as select * from '{D}/bill_vote_references.parquet'")
c.sql(f"create view v as select * from '{D}/roll_call_votes.parquet'")
q("select vote_id, congress, chamber, session, roll_number from v using sample 3 rows")
q("select regexp_matches(vote_id,'^[0-9]+-(house|senate)-[0-9]+-[0-9]+$'), count(*) from v group by 1")
q("select count(*) from v where vote_id <> congress||'-'||chamber||'-'||session||'-'||roll_number")
q("select session, count(*) from b group by 1 order by 1")
q("select session, count(*) from v group by 1 order by 1")
q("select roll_number from b where not regexp_matches(roll_number,'^[1-9][0-9]*$') limit 5")
q("select roll_number from v where not regexp_matches(roll_number,'^[1-9][0-9]*$') limit 5")
# join on component columns with integer casting (different method from string concat)
q("""select count(*) as total, count(v.vote_id) as hit from b left join v on try_cast(b.congress as int)=try_cast(v.congress as int) and lower(b.chamber)=lower(v.chamber) and try_cast(b.session as int)=try_cast(v.session as int) and try_cast(b.roll_number as int)=try_cast(v.roll_number as int)""")
q("""select count(*) as total, count(v.vote_id) as hit from b left join v on b.congress||'-'||b.chamber||'-'||b.session||'-'||b.roll_number = v.vote_id""")
# reverse direction: refs whose bill_id differs from the vote's own bill_id
q("""select (v.bill_id = b.bill_id) same, v.bill_id is null vnull, count(*) from b join v on b.congress||'-'||b.chamber||'-'||b.session||'-'||b.roll_number = v.vote_id group by all""")
q("select count(*), count(distinct (bill_id,congress,chamber,session,roll_number)) from b")
# vote bill_id pattern
q("select count(*) filter (where bill_id is not null), count(*) filter (where bill_id is not null and not regexp_matches(bill_id,'^[0-9]+-[a-z]+-[0-9]+$')) from v")
