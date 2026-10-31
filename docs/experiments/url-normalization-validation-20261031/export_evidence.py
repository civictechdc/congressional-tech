"""Keep reviewable results beside the report; large bodies remain in scratch."""
from common import *
import subprocess
evidence=HERE/'evidence';evidence.mkdir(exist_ok=True)
names=['prepare','pins','tables','normalization-results','corpus-results','scheduler-results','wayback-results','wayback-guard-results',
 'discovery-link-results','followup-results','remaining-results','alias-membership-results','lookup-summary','lookup-journeys',
 'lookup-different-documents','publication-link-impact','malformed-results','live-trim-results','live-pdf-results','bill-mismatch-publication']
def concise(x):
 if isinstance(x,list):return [concise(v) for v in x]
 if not isinstance(x,dict):return x
 return {k:concise(v) for k,v in x.items() if k not in ('__raw_line','__source_key','__source_line','text_head','first_page')}
for name in names:
 value=concise(json.loads((OUT/(name+'.json')).read_text()))
 (evidence/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
bodies=json.loads((OUT/'repair-body-summary.json').read_text())
bodies.pop('weak_examples',None)
for x in bodies['duplicate_bodies']:
 x.pop('text',None)
 if 'hr-4824' in ' '.join(x['targets']):x['content_identifier']='118th Congress, H. R. 4755, Privacy Enhancing Technology Research Act'
(evidence/'repair-body-summary.json').write_text(json.dumps(bodies,indent=2)+'\n')
checks=json.loads((OUT/'repair-body-checks.json').read_text())
metadata=[{k:v for k,v in x.items() if k not in ('text','parse_diagnostic','slug_tokens','slug_tokens_found','bindings')} for x in checks]
(evidence/'repair-body-checks.json').write_text(json.dumps(metadata,indent=2)+'\n')
source_paths=[REPO/'model/sql/url-normalized.sql',REPO/'model/registries/url-rules.json',REPO/'packages/corpus_recovery/src/corpus_recovery/discovery.py',REPO/'packages/congress_api/src/congress_api/acquisition/capture_scheduler.py',REPO/'apps/site/src/components/explorer/reader/archive.ts']
source_paths+=list(FROZEN.iterdir())
source_paths+=[Path(v['path']) for v in json.loads((OUT/'tables.json').read_text()).values()]
source_paths+=list((OUT/'inputs').iterdir())
source_paths+=[PUB/'release/release.json',PUB/'model/job.json']
pins={str(p):{'bytes':p.stat().st_size,'sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest()} for p in set(source_paths) if p.is_file()}
manifest={'checked_start_commit':'cafb1b43d4ede3738f2f9e17a4b70ecf02b00f8b','checked_end_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
 'code_drift':subprocess.check_output(['git','diff','--name-only','cafb1b43','HEAD','--','model','packages','apps'],cwd=REPO,text=True).splitlines(),
 'native_binary_sha256':'8d33f1d03540fb0bc8160eac18e0121c0cde428feaeb77b4e815abf805f2d819','native_source_revision':'eb40c5457a450c3820900583af5b4da13313ca96',
 'native_limits':{'threads':2,'memory_bytes':2147483648},'duckdb_limits':{'threads':2,'memory':'1GB'},'scratch':str(OUT),'inputs':pins}
(evidence/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
shutil.copy2(OUT/'proposed-discovery.py',HERE/'proposed_discovery.py')
bill_sha='f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee'
pdf=CAM/'track_b/raw_store/bodies/sha256'/bill_sha[:2]/bill_sha
assert hashlib.file_digest(pdf.open('rb'),'sha256').hexdigest()==bill_sha
shutil.copy2(pdf,evidence/'accepted-hr4824.pdf')
shutil.copy2(OUT/'bill-first-page.png',evidence/'accepted-hr4824-first-page.png')
print('exported',len(list(evidence.glob('*.json'))),'evidence files')
