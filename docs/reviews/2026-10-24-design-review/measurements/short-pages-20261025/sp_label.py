# Assign a kind to every sampled page from patterns confirmed by reading (see findings.md).
import duckdb, re, json
c = duckdb.connect()
c.sql("create table x as select * from read_json_auto('parsed.jsonl', format='newline_delimited') join 'sample.parquet' using(sha256)")
rows = c.sql("select sha256, host, hgroup, coalesce(member_path, context_url) loc, title, heading, text, text_bytes from x").fetchall()
def kind(host, loc, title, heading, text, tb):
    t, T, u = text, (title or ''), loc.lower()
    if 'download will begin shortly' in t: return 'download_interstitial'
    if re.search(r'Client Challenge|Just a moment|Checking your browser|Attention Required', T + t[:300]): return 'bot_challenge'
    if re.search(r'^(Not Found|Internal Error|Page Not Found|404|Error - 404|Resource Unavailable)\b', T) or re.match(r'(Page Not Found|Oops! The requested page was not found)', t): return 'soft_error'
    if host == 'www.usaid.gov' and 'Administrative Leave' in t: return 'soft_error'
    if tb == 0 or re.match(r'Preparing to download', t): return 'empty_or_js_shell'
    if 'youtube.com' in host and tb < 400: return 'empty_or_js_shell'
    if tb >= 2048: return 'long_page'
    if u.startswith('chrg-') or '/content/pkg/chrg-' in u:
        if 'ERRATA' in t.upper(): return 'real_doc_errata'
        if re.search(r'TEXT NOT AVAILABLE|NO TEXT AVAILABLE|TIFF OMITTED|GRAPHIC', t.upper()) or tb < 2048: return 'real_doc_gpo_cover_only'
        return 'real_doc'
    if '/publication/' in u: return 'document_wrapper_page'
    if re.search(r'hearings_markups_details|/hearings?[/?.]|hearings-calendar|committee-activity/hearings|/meeting|/\d{4}/\d+/', u) and not u.endswith('.pdf'): return 'hearing_event_page'
    if 'docs.house.gov/floor' in u: return 'listing_page'
    if 'thomas.loc.gov' in host: return 'document_index_page'
    if 'waysandmeans.house.gov/legacy' in u or 'waysandmeans.house.gov/legacy' in u.replace('web.archive.org', ''): return 'real_doc_short_release'
    if 'Language selection' in T or T.startswith('Welcome') or u.rstrip('/') in ('http://docs.house.gov',): return 'landing_or_unrelated'
    if 'OrbitWheel' in T: return 'landing_or_unrelated'
    return 'other'
out = {}
for sha, host, hg, loc, title, heading, text, tb in rows:
    out[sha] = kind(host, loc, title, heading, text, tb)
json.dump(out, open('labels_rule.json', 'w'))
c.sql("create table l(sha256 varchar, kind varchar)")
c.executemany("insert into l values (?,?)", list(out.items()))
for r in c.sql("select kind, text_bytes<2048 short, count(*) n, round(sum(weight)) est from x join l using(sha256) group by all order by short desc, est desc").fetchall(): print(r)
print('--- short "other":')
for r in c.sql("select host, coalesce(member_path, context_url), title, text_bytes, left(text, 200) from x join l using(sha256) where kind='other' and text_bytes<2048").fetchall(): print(r)
