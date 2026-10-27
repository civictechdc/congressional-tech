import re, sys, collections
root = "/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/"
docs = {
 "ARCH": root+"engine-first-architecture.md",
 "DM": root+"engine-first-data-model.md",
 "PLAN": root+"plans/simplification-plan-20261024.md",
 "BIND": root+"plans/bindings-20261025.md",
}
text = {k: open(v, encoding="utf-8").read() for k,v in docs.items()}
lines = {k: v.splitlines() for k,v in text.items()}

print("== total words ==")
for k,v in text.items(): print(k, len(v.split()))

print("\n== words per H2/H3 section ==")
for k,ls in lines.items():
    cur="(preamble)"; counts=collections.OrderedDict(); counts[cur]=0
    for l in ls:
        m=re.match(r'^(#{2,3}) (.*)',l)
        if m: cur=m.group(2); counts[cur]=0
        else: counts[cur]+=len(l.split())
    print(f"-- {k}")
    for s,c in counts.items(): print(f"   {c:5d}  {s}")

print("\n== cross-reference density ==")
for k,v in text.items():
    refs=collections.Counter(re.findall(r'\[\[([A-Z\-]+)\]\]',v))
    sec=len(re.findall(r'§\d',v))
    print(k, dict(refs), "§-refs:",sec, "per 1k words:", round(1000*sec/len(v.split()),1))

print("\n== numeric claims (digits with commas or units) ==")
for k,v in text.items():
    nums=re.findall(r'\b\d{1,3}(?:,\d{3})+\b|\b\d+(?:\.\d+)?\s?(?:GB|MB|KB|TB|MiB|KiB)\b|\b\d+(?:\.\d+)?%',v)
    print(k, len(nums))

print("\n== phrase recurrence across docs (line numbers) ==")
phrases = [
 r'create-only', r'If-None-Match', r'Content-MD5', r'concurrency group', r'three retries|at most three',
 r'work list', r'anti-join', r'completion row', r'url_key', r'compact JSON', r'edition-ambiguous',
 r'placeholder', r'link key|link_key', r'listing baseline', r'previous_release_id|last-good',
 r'404', r'schema_version', r'pin list|pins/spicy', r'bucket lock', r'If-Match', r'HEAD',
 r'403 GB', r'260,175', r'1\.04M|1,036,256', r'199,156', r'18,140', r'ss-vhi2', r'ss-iwqu', r'ss-6jg6',
 r'B13', r'B0\b', r'multipart', r'news_lake', r'labeled sample', r'main content', r'legacy_pdf_checks',
 r'date-shaped', r'format preference|format-preference', r'group_path', r'witness_key', r'record_sha',
]
for p in phrases:
    row=[]
    for k,ls in lines.items():
        hits=[i+1 for i,l in enumerate(ls) if re.search(p,l)]
        if hits: row.append(f"{k}:{len(hits)}")
    print(f"{p:40s} {' '.join(row)}")
