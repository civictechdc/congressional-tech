import json,sys
p=json.load(open(sys.argv[1]))
want={'committees','members','member_terms','committee_assignments','congress_bills','cbo_cost_estimates','roll_call_votes','bill_vote_references','nominations','member_votes','hearings','committee_meetings','witnesses'}
for fam,f in p['families'].items():
    for t,m in f.get('tables',{}).items():
        name=t.replace('.parquet','')
        if name in want or 'nomin' in name or 'hearing' in name or 'witness' in name or 'meeting' in name or 'vote' in name or 'committee' in name:
            print(fam, t, m.get('rows'), m.get('byteSize'), f['prefix']+'/'+m.get('key',t))
            print('    ', [c[0] for c in m.get('columns',[])])
