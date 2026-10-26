import duckdb, re
O='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/page-versions/'
c=duckdb.connect()
FILE=re.compile(r'(\.pdf|\.zip|\.docx?|\.xml)(\?|$)|/download/|download=1|file_id=', re.I)
def stratum(u):
    h=re.match(r'^https?://([^/]+)',u).group(1).lower()
    p=u[len(re.match(r'^https?://[^/]+',u).group(0)):].lower()
    if FILE.search(u): return 'file_shaped_url'
    if h in ('www.govinfo.gov','www.gpo.gov','frwebgate.access.gpo.gov'): return 'gpo_transcript'
    if h=='veterans.house.gov': return 'veterans_statement' if re.search(r'/(witness-testimony|opening-statement|submission-for-the-record|hearing-transcript|prepared-statement)',p) else 'veterans_other'
    if h.endswith('senate.gov') and re.search(r'/(hearings|meetings)/',p): return 'senate_hearing_page'
    if h.endswith('senate.gov'): return 'senate_other'
    if h.endswith('house.gov') and re.search(r'/(hearings?|calendar|events?|meetings?)/|eventsingle|calendar/',p): return 'house_hearing_page'
    if h.endswith('house.gov') and re.search(r'press|news|media|statement',p): return 'house_news_statement'
    if h.endswith('house.gov'): return 'house_other'
    return 'external'
c.create_function('stratum', stratum, ['VARCHAR'], 'VARCHAR')
c.sql(f"create table u as select *, stratum(context_url) stratum, stratum(context_url)='file_shaped_url' file_shaped from '{O}urls_html.parquet'")
c.sql(f"copy u to '{O}urls_html_strata.parquet'")
print(c.sql("select stratum, count(*) from u group by 1 order by 2 desc").fetchall())
for s in ['house_other','senate_other','veterans_other','house_news_statement','house_hearing_page','external']:
    print(s, [x[0] for x in c.sql(f"select context_url from u where stratum='{s}' using sample 8").fetchall()])
