import duckdb,json,hashlib,sys,os
D=sys.argv[1]
idx=json.load(open(D+'/publication.v2.json'))
for fam,f in idx['families'].items():
    for t,m in f.get('tables',{}).items():
        p=os.path.join(D,t)
        if os.path.exists(p):
            h='sha256:'+hashlib.sha256(open(p,'rb').read()).hexdigest()
            print('digest', t, 'OK' if h==m['sha256'] else 'MISMATCH')
c=duckdb.connect()
def q(s):
    print('>>',s.replace(D+'/','')); 
    for r in c.sql(s).fetchall(): print('  ',r)
P=lambda t: f"'{D}/{t}.parquet'"
for t,col in [('committees','chamber'),('committee_assignments','chamber'),('roll_call_votes','chamber'),('bill_vote_references','chamber'),('bill_committees','chamber'),('committee_reports','chamber'),('committee_meetings','chamber'),('member_terms','term_type'),('congress_bills','origin_chamber')]:
    q(f"select {col}, count(*) from {P(t)} group by 1 order by 2 desc")
q(f"select split_part(vote_id,'-',2) ch, chamber, count(*) from {P('roll_call_votes')} group by all order by 3 desc")
q(f"select unnest(committees).systemCode[1:1] l, chamber, count(*) from {P('committee_meetings')} group by all order by 3 desc")
q(f"select system_code[1:1], chamber, count(*) from {P('committees')} group by all order by 1")
