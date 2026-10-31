from common import *
import re
pins={}
for name,source in {'decisions':CAM/'track_a/recovery_decisions.parquet','retained':CAM/'track_a/retained_captures.parquet','requirements':CAM/'plan_v2/recovery-requirements.parquet','variants':CAM/'release_v2/url_variants.parquet',
 'wave4qualified':CAM/'track_b/b1_wave4_qualified.json','wave5results':CAM/'track_b/b1_wave5_results.json','wave5qualified':CAM/'track_b/b1_wave5_qualified.json'}.items():
 pins[name]=pin(source,name+source.suffix)
dump('pins.json',pins)
c=connect()
paths={'k':CAM/'key_prep/keyed_universe.parquet','raw':CAM/'inputs/raw_universe.parquet','d0':FROZEN/'plan.parquet','d':FROZEN/'plan_v2.parquet','selected':FROZEN/'selected.parquet','st':FROZEN/'state.parquet',
 'captures':PUB/'model/evidence/capture_sources.parquet','sources':PUB/'release/sources.parquet','urls':PUB/'release/urls.parquet','docs':PUB/'model/evidence/document_rows.parquet','links':PUB/'model/evidence/publisher_links.parquet','facts':PUB/'model/evidence/page_facts.parquet'}
paths.update({k:Path(v['path']) for k,v in pins.items() if v['path'].endswith('.parquet')})
for name,path in paths.items(): c.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{path}')")
dump('tables.json',{k:{'path':str(v),'rows':c.execute(f'SELECT count(*) FROM {k}').fetchone()[0],'columns':[x[0] for x in c.execute(f'DESCRIBE {k}').fetchall()]} for k,v in paths.items()})
c.execute('CREATE OR REPLACE TABLE all_urls AS SELECT target_url AS url FROM k UNION SELECT url FROM sources UNION SELECT target_url FROM links UNION SELECT requested_url FROM st UNION SELECT candidate_url FROM selected')
rules=json.loads((REPO/'model/registries/url-rules.json').read_text())
wrapper='|'.join('(?:'+r['pattern'].replace('(?i)','')+')' for r in rules if r['kind']=='wrapper')
screen="%20|[[:space:]]|[^:]//|/404[?]notfound=|&download=1|^mailto:|File URL path:"
c.execute('CREATE OR REPLACE TABLE risk_urls AS SELECT url FROM all_urls WHERE regexp_matches(url,?) OR regexp_matches(url,?)',[screen,'(?i)'+wrapper])
c.execute(f"COPY (SELECT cast(row_number() OVER(ORDER BY url) AS VARCHAR) input_id,url FROM risk_urls) TO '{OUT/'risk-urls.parquet'}' (FORMAT PARQUET)")
c.execute('''CREATE OR REPLACE TABLE relevant_captures AS SELECT * FROM captures
 WHERE requested_url IN (SELECT url FROM risk_urls) OR url IN (SELECT url FROM risk_urls)
 OR body_sha IN (SELECT body_sha256 FROM selected WHERE candidate_source IN ('repaired_download_query','stored_url_key_alias'))''')
dump('prepare.json',{'all_urls':c.execute('SELECT count(*) FROM all_urls').fetchone()[0],'risk_urls':c.execute('SELECT count(*) FROM risk_urls').fetchone()[0],
 'relevant_captures':c.execute('SELECT count(*) FROM relevant_captures').fetchone()[0], 'screen':screen,'wrapper_patterns':wrapper,'variants':rows(c,'SELECT * FROM variants')})
print((OUT/'prepare.json').read_text())
