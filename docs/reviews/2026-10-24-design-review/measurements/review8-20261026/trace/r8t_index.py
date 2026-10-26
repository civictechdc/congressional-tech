import json, urllib.request, sys
UA={"User-Agent":"congressional-tech-review/1.0"}
req=urllib.request.Request("https://data.spicygov.ai/publication.v2.json",headers=UA)
raw=urllib.request.urlopen(req,timeout=60).read()
open("dl/publication.v2.json","wb").write(raw)
o=json.loads(raw)
print("top keys:",list(o.keys())[:20])
fams=o.get("families") or o.get("datasets") or o
if isinstance(fams,dict):
    items=fams.items()
else:
    items=[(f.get("name") or f.get("family") or f.get("id"),f) for f in fams]
want={"committees","members","member_terms","committee_assignments","congress_bills","cbo_cost_estimates","roll_call_votes","bill_vote_references","nominations"}
found=set()
for name,f in items:
    if not isinstance(f,dict): continue
    tabs=f.get("tables") or f.get("outputs") or {}
    tnames=list(tabs.keys()) if isinstance(tabs,dict) else [t.get("name") or t.get("table") for t in tabs]
    hit=[t for t in tnames if t in want]
    found.update(hit)
    print(f"{name}: prefix={f.get('prefix')} tables={tnames[:12]}{'...' if len(tnames)>12 else ''}")
print("MISSING wanted tables:",sorted(want-found))
# print one family's structure in full for shape
first=next(iter(items))
print("example family json keys:",list(first[1].keys()) if isinstance(first[1],dict) else type(first[1]))
