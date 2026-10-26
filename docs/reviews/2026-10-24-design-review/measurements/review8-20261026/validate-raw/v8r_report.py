import pickle,sys,collections as C
S,imp,maxfr=pickle.load(open(sys.argv[1],'rb'))
for k in ['lines','rtype','mode','rows','A6','A6_alt','A5','A5_keys','fr','fr_op_kind','cap','A7','A7_status']:
    print(k, sorted(S.get(k,{}).items(), key=lambda x:-x[1])[:25])
print('A6_fam',S['A6_fam'].most_common(15))
print('A6_fammismatch',S.get('A6_fammismatch',C.Counter()).most_common(10))
print('A5_notime_fam',S['A5_notime_fam'].most_common(15))
print('A5_timefam',S['A5_timefam'].most_common(15))
print('fr_bodiless_ex',S['fr_bodiless_ex'].most_common(5))
print('maxfr',maxfr)
print('congress_api',S['congress_api'].most_common(30))
print('A1_bodies distinct',len(S['A1_bodies']), sum(S['A1_bodies'].values()))
print('imports',len(imp))
