import duckdb,sys
D=sys.argv[1]+'/'
c=duckdb.connect()
def q(s):
    for r in c.sql(s).fetchall(): print('  ',r)
q(f"select system_code, chamber, name, [h.officialName for h in history][1:2] from '{D}committees.parquet' where system_code in ('hsap00','ssap00','hsju00','ssju00','hsas00','ssas00','hsif00','sscm00')")
q(f"select count(*) filter (where is_subcommittee), count(*) filter (where is_subcommittee and list_filter(history, h->h.officialName is not null)=[]) from '{D}committees.parquet'")
print('committee_meetings coverage'); q(f"select congress, chamber, count(*) from '{D}committee_meetings.parquet' group by all order by 1,2")
print('hearing_transcripts'); q(f"select package_id, event_id, mods_event_id, jacket_number, chamber from '{D}hearing_transcripts.parquet' limit 3")
q(f"select count(*), count(event_id) from '{D}hearing_transcripts.parquet'")
