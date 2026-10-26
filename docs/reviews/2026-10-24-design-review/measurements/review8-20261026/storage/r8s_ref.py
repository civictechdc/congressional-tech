import json
d=json.load(open('dl/pub.json'))
need={'committees':['system_code','chamber','name','committee_type','parent_system_code','history','website_url','is_current'],
'members':['bioguide_id','name_first','name_last','lis_id','fec_ids','opensecrets_id','govtrack_id','icpsr_id','wikidata_id'],
'member_terms':['bioguide_id','term_type','term_state','term_district','term_party','term_start','term_end'],
'committee_assignments':['congress','system_code','bioguide_id','position','rank','party'],
'congress_bills':['bill_id','title','short_title','sponsor_bioguide_id','introduced_date','latest_action_date','latest_action_text','stage','policy_area','subjects'],
'cbo_cost_estimates':['bill_id','publication_id','pub_date','description'],
'roll_call_votes':['vote_id','chamber','vote_day','question','result','yea','nay','bill_id','documents'],
'bill_vote_references':['bill_id','congress','chamber','session','roll_number'],
'nominations':['congress','number','part_number','description','organization','received_date','latest_action_date','latest_action_text']}
found={}
for fam,f in d['families'].items():
    for k,t in f.get('tables',{}).items():
        name=t.get('table') or k.replace('.parquet','')
        found.setdefault(name,[]).append((fam,f['prefix'],t.get('key',k),dict((c[0],c[1]) for c in t['columns']),t.get('rows')))
for tbl,cols in need.items():
    if tbl not in found: print('MISSING TABLE',tbl); continue
    for fam,prefix,key,c,rows in found[tbl]:
        miss=[x for x in cols if x not in c]
        print(tbl,fam,prefix[:60],key,rows,'missing:',miss)
        print('   types:',{x:c[x] for x in cols if x in c})
