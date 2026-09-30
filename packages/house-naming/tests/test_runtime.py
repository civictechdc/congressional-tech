from __future__ import annotations
from copy import deepcopy
import json
import os
import random
from pathlib import Path
import subprocess
import sys
import pytest
from jsonschema import Draft202012Validator
from house_naming import Engine, NamingError, load_guide, check_catalog
from house_naming.compiler import records_schema, filename_schema
from house_naming.io import loads

ROOT=Path(__file__).resolve().parents[1]
CASES=json.loads((ROOT/'tests/records.json').read_text())
W={'kind':'witness-statement','congress':112,'committeeCode':'ED','witnessId':'IveyB','meetingDate':'20110922','extension':'pdf','meetingType':'HHRG'}

@pytest.fixture(scope='module')
def engine():return Engine()

# Intentional convention-to-record migrations. Every original scalar survives.
PARSED_KIND = {
    'conference-numbered': 'published-report',
    'appropriation-annual': 'appropriation-described',
    'appropriation-supplemental': 'appropriation-described',
    'continuing-resolution-reported': 'appropriation-described',
    'continuing-resolution-committee': 'appropriation-described',
    'committee-rules': 'committee-print',
}

def assert_record_recovered(original, result):
    expected = {**original, 'kind': PARSED_KIND.get(original['kind'], original['kind'])}
    assert any(all(match['record'].get(k) == v for k, v in expected.items())
               for match in result['matches']), (expected, result)

@pytest.mark.parametrize('case',CASES,ids=lambda x:x['input']['kind'])
def test_render_and_roundtrip(engine,case):
    original=deepcopy(case['input']); record=deepcopy(original)
    assert engine.render(record)==case['output']
    assert record==original
    if engine.guide['patterns'][record['kind']]['action']=='filename':
        result=engine.parse(case['output'])
        assert result['valid']
        assert_record_recovered(original, result)
        for x in result['matches']:
            assert engine.render(x['record'])==x['canonical_filename']
            assert x['record'] in [m['record'] for m in engine.parse(x['canonical_filename'])['matches']]

@pytest.mark.parametrize('case',CASES,ids=lambda x:x['input']['kind'])
def test_integer_valued_floats(engine,case):
    data={k:float(v) if type(v) is int else v for k,v in case['input'].items()}
    assert engine.render(data)==case['output']

@pytest.mark.parametrize('case',CASES,ids=lambda x:x['input']['kind'])
def test_all_required_fields_and_unknown_fields(engine,case):
    data=case['input'];kind=data['kind'];rule=engine.guide['patterns'][kind]
    for field in ['kind',*rule['required']]:
        with pytest.raises(NamingError):engine.render({k:v for k,v in data.items() if k!=field})
    with pytest.raises(NamingError):engine.render({**data,'typo':1})

@pytest.mark.parametrize('case',CASES,ids=lambda x:x['input']['kind'])
def test_revisions_and_meeting_counters(engine,case):
    data=case['input'];rule=engine.guide['patterns'][data['kind']]
    if rule['action']!='filename':return
    for revision in [1,2,10,2147483647]:
        record={**data,'revision':revision}
        output=engine.render(record)
        assert f'-U{revision}.' in output
        assert_record_recovered(record, engine.parse(output))
    if 'meetingOccurrence' in rule['fields']:
        record={**data,'meetingOccurrence':2,'revision':3}
        output=engine.render(record)
        assert_record_recovered(record, engine.parse(output))

@pytest.mark.parametrize('value',['','../IveyB','a/b','a\\b','a\nb','a\tb','a b','a\x00b','a\x7fb','a\u0085b','a\uFEFFb','a:b','a?b','a*b','a|b','<x>','"x"','a\ud800b','x'*161])
def test_unsafe_tokens(engine,value):
    with pytest.raises(NamingError):engine.render({**W,'witnessId':value})

@pytest.mark.parametrize('field,value',[
 ('congress',0),('congress',-1),('congress',True),('congress','112'),('congress',112.5),
 ('congress',float('nan')),('congress',float('inf')),('congress',2147483648),
 ('revision',0),('revision',True),('revision','01'),('revision',None),
 ('extension','exe'),('extension','PDF'),('meetingDate','2011092'),('meetingDate','20110229'),
 ('meetingDate','20111301'),('meetingDate','00000101'),('meetingDate','20110231'),
 ('committeeCode','AG000'),('committeeCode','ag'),('witnessId',{}),('witnessId',[])
])
def test_invalid_records(engine,field,value):
    with pytest.raises(NamingError):engine.render({**W,field:value})

@pytest.mark.parametrize('record',[None,[],True,'text',{'kind':[]},{'kind':'absent'}])
def test_invalid_root(engine,record):
    with pytest.raises(NamingError):engine.render(record)

@pytest.mark.parametrize('value',['a-U1','a-U0','a-U01','a-U123456789'])
def test_reserved_free_suffix(engine,value):
    data={'kind':'bill-preintroduced','congress':112,'measureType':'hres','description':value,'extension':'xml'}
    with pytest.raises(NamingError):engine.render(data)

@pytest.mark.parametrize('date_value,valid',[('20111205',True),('20111206',False),('20120229',False),('20240226',True),('20240230',False)])
def test_week_starts(engine,date_value,valid):
    r={'kind':'weekly-meeting-notice','congress':112,'committeeCode':'AG','weekOf':date_value,'extension':'pdf'}
    if valid:assert engine.parse(engine.render(r))['valid']
    else:
        with pytest.raises(NamingError):engine.render(r)

def test_leap_and_unicode(engine):
    r={**W,'meetingDate':'20240229','witnessId':"O’Brien-ÉlodieA"}
    output=engine.render(r)
    assert r in [m['record'] for m in engine.parse(output)['matches']]
    with pytest.raises(NamingError):engine.render({**W,'witnessId':'界'*100})

def test_hyphens_and_leading_zeros(engine):
    name='BILLS-112hres-PIH-electing-sgt-at-arms.xml'
    r=engine.parse(name)
    assert r['found_in_source'] and r['matches'][0]['record']['description']=='electing-sgt-at-arms'
    name='BILLS-112-HR3116-K000210-Amdt-001CC1.pdf'
    assert engine.parse(name)['matches'][0]['record']['amendmentId']=='001CC1'

@pytest.mark.parametrize('name',[
 'HMTG-112--HHRG- AG03-20110705.pdf',
 'BILLS-112-HR3116-C001067 Amdt-001B.pdf',
 'BILLS-112-HR3116-000193-Amdt-001A.pdf',
 'CMTG-112-HHRG-ED-201109022-U3.pdf'])
def test_bad_source_samples_are_not_validity_exceptions(engine,name):
    r=engine.parse(name)
    assert r['found_in_source'] and not r['valid']
    assert engine.examples(name)

def test_duplicate_samples_and_multiple_definitions(engine):
    examples=engine.examples('CRPT-112hrpt-HR2055-DivisonB.pdf')
    assert len(examples)==2
    entry=engine.lookup('version','RH')
    assert len(entry['statements'])==2
    assert 'occurs with' in entry['statements'][0]['text']
    assert 'occurs to' in entry['statements'][1]['text']
    assert len(engine.contexts('sc'))==4
    assert engine.lookup('collection','HPREC-DESCHLERS')['printed']=='HPREC-DESCHLERS'

def test_overlapping_patterns_return_all_matches(engine):
    r=engine.parse('BILLS-112HR-ORH-AP-FY13-Agriculture.pdf')
    assert not r['ambiguous']
    assert r['matches'][0]['record']['fiscalYear'] == '13'
    assert set(r['matches'][0]['matched_conventions']) == {'appropriation-described','appropriation-annual'}
    r=engine.parse('CRPT-112hrpt-HR2055-DivisonA-som.pdf')
    assert r['ambiguous'] and len(r['matches'])==2

def test_exact_matching_and_safe_bounds(engine):
    base=engine.render(W)
    for n in [base+'\n',base+'\r\n','/'+base,base+'.bak','x'*10000,base.replace('112','0112'),base.replace('.pdf','-U0.pdf'),base.replace('.pdf','-U01.pdf')]:
        assert not engine.parse(n)['valid']
    assert not engine.parse(base.replace('20110922','20110231'))['valid']

def test_single_convention_set(engine):
    assert len(engine.kinds()) == 56
    assert 'profiles' not in engine.guide
    assert len(engine._matchers) == 54

def test_copies_and_lookup_types(engine):
    guide=engine.guide;guide['committees'].clear()
    assert engine.committee('AG00')
    entry=engine.lookup('version','rh');entry['statements'].clear()
    assert len(engine.lookup('version','rh')['statements'])==2
    assert engine.committee('AG') is None
    assert engine.committee('AG00')['folder_code']=='AG00'
    assert engine.committee('ZZ00') is None
    for fn in [engine.committee,engine.source,engine.examples,engine.contexts]:
        with pytest.raises(NamingError):fn([])

@pytest.mark.parametrize('url',['https:///missing-host','javascript:alert(1)','file:///etc/passwd','https://user:pass@example.org/x','https://example.org:bad/x','https://example.org/x\n','https://example.org/%ZZ','https://example.org/{raw}','https://éxample.org/path'])
def test_bad_publication_links(engine,url):
    with pytest.raises(NamingError):engine.render({'kind':'committee-print-link','url':url})

def test_member_identifier_does_not_require_roster(engine):
    record={'kind':'member-statement','congress':200,'meetingType':'HMTG','committeeCode':'ZZ','memberBioguideId':'Z999999','meetingDate':'20260101','extension':'pdf'}
    assert engine.render(record)=='HMTG-200-ZZ-MState-Z999999-20260101.pdf'

def test_strict_json():
    for text in ['{"x":1,"x":2}', '{"x":NaN}','{"x":Infinity}','{','[',b'\xff']:
        with pytest.raises(NamingError):loads(text)
    with pytest.raises(NamingError):loads('"'+'x'*10+'"',max_bytes=5)

def test_all_generated_schemas():
    paths = sorted((ROOT/'src/house_naming/data').glob('*.schema.json'))
    assert len(paths) == 3
    for path in paths:
        Draft202012Validator.check_schema(json.loads(path.read_text()))
    guide = load_guide()
    check_catalog(guide)
    validator = Draft202012Validator(records_schema(guide))
    lexical = Draft202012Validator(filename_schema(guide))
    for case in CASES:
        validator.validate(case['input'])
        if guide['patterns'][case['input']['kind']]['action'] == 'filename':
            lexical.validate(case['output'])
    for case in CASES:
        for field in ['kind', *guide['patterns'][case['input']['kind']]['required']]:
            invalid = {k: v for k, v in case['input'].items() if k != field}
            assert not validator.is_valid(invalid)

@pytest.mark.parametrize('mutation',[
 lambda g:g['patterns']['witness-statement']['fields'].__setitem__('witnessId','absent'),
 lambda g:g['patterns']['witness-statement'].__setitem__('stem_template','{witnessId.__class__}'),
 lambda g:g['patterns']['witness-statement'].__setitem__('stem_template','{witnessId}{witnessId}'),
 lambda g:g['patterns']['witness-statement'].__setitem__('stem_template','{absent}'),
 lambda g:g['patterns']['witness-statement'].__setitem__('typo',1),
 lambda g:g['codes']['version']['rh']['sources'][0].__setitem__('page',40),
 lambda g:g['codes']['version']['rh']['sources'][0].__setitem__('source_id','absent'),
 lambda g:g['code_index'].__setitem__('sc',['version']),
 lambda g:g['example_index'].__setitem__('not-a-source-string',['example-0001']),
 lambda g:g['patterns']['witness-statement']['footnote_ids'].append('fn-absent'),
 lambda g:g.__setitem__('members', {}),
 lambda g:g['committees']['AG00'].__setitem__('folder_code','wrong'),
 lambda g:g['field_types']['legislativeStage']['enum'].append('not-in-source'),
 lambda g:g['sections']['section-01'].__setitem__('parent_id','section-01'),
 lambda g:g['patterns']['witness-statement']['required'].append('absent'),
])
def test_catalog_integrity_rejections(mutation):
    guide=load_guide();mutation(guide)
    with pytest.raises(NamingError):check_catalog(guide)

@pytest.mark.parametrize('case',CASES,ids=lambda x:x['input']['kind'])
def test_deterministic_mutation_roundtrips(engine,case):
    rule=engine.guide['patterns'][case['input']['kind']]
    if rule['action']!='filename':return
    rng=random.Random(1959+sum(map(ord,case['input']['kind'])))
    for _ in range(30):
        congress_type=engine.guide['field_types'][rule['fields']['congress']]
        r=deepcopy(case['input']);r['congress']=rng.randint(congress_type['minimum'],min(999,congress_type['maximum']))
        r['extension']=rng.choice(['pdf','xml'])
        if rng.choice([True,False]):r['revision']=rng.randint(1,1000)
        if 'meetingOccurrence' in rule['fields'] and rng.choice([True,False]):r['meetingOccurrence']=rng.randint(2,50)
        for key in ['measureNumber','reportNumber','partNumber']:
            if key in r:r[key]=rng.randint(1,99999)
        for key in ['supportId','enblocId','sequence','voteId']:
            if key in r:r[key]=str(rng.randint(1,9999)).zfill(rng.randint(1,8))
        for key in ['description','measureOrDescription','part','witnessId','subject']:
            if key in r:r[key]='prefix-hyphenated_'+str(rng.randint(1,999))
        output=engine.render(r)
        assert_record_recovered(r, engine.parse(output))

def test_schema_rebuild_is_deterministic():
    result=subprocess.run([sys.executable,str(ROOT/'tools/build.py'),'--check'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr

@pytest.mark.parametrize('args,expected',[
 (['check'],0),(['kinds'],0),(['render','examples/witness.json'],0),
 (['parse','HHRG-112-ED-WState-IveyB-20110922.pdf'],0),
 (['parse','HMTG-112--HHRG- AG03-20110705.pdf'],1),
 (['lookup','version','RH'],0),(['contexts','SC'],0),
 (['committee','AG00'],0),(['source','table-8491-row-3'],0),
 (['schema'],0),(['schema','--filename-lexical'],0),
 (['unknown-command'],2),
])
def test_cli(args,expected):
    result=subprocess.run([sys.executable,'-m','house_naming',*args],cwd=ROOT,capture_output=True,text=True,env={**os.environ,'PYTHONPATH':str(ROOT/'src')})
    assert result.returncode==expected,(result.stdout,result.stderr)
    json.loads(result.stdout if result.stdout else result.stderr)

def test_source_maps_counts_and_local_text(engine):
    g=engine.guide
    assert 'members' not in g and len(g['committees'])==131 and len(g['footnotes'])==9
    assert len(g['sections'])==45
    rows=[v for v in g['source_nodes'].values() if v['kind']=='row']
    assert len(rows)==320 and len({v['table_id'] for v in rows})==40
    assert len(g['examples'])==160 and len(g['example_index'])==154
    for value,ids in g['example_index'].items():
        r=engine.parse(value)
        assert r['found_in_source'] and r['source_example_ids']==ids
        for eid in ids:
            example=g['examples'][eid]
            assert value in example['raw_text']
            source=g['source_nodes'][example['source']['source_id']]
            assert example['raw_text'] in source['text']

def test_exponent_overflow_is_rejected():
    with pytest.raises(NamingError):loads('{"congress":1e9999}')

def test_runtime_with_network_blocked(monkeypatch):
    import socket
    from house_naming.catalog import _bundled
    def blocked(*args,**kwargs):raise AssertionError('Network access attempted')
    monkeypatch.setattr(socket,'socket',blocked)
    monkeypatch.setattr(socket,'create_connection',blocked)
    _bundled.cache_clear()
    engine=Engine()
    assert engine.render(W)=='HHRG-112-ED-WState-IveyB-20110922.pdf'
    assert engine.render({'kind':'committee-print-link','url':'https://example.org/not-fetched'})=='https://example.org/not-fetched'
    assert engine.parse(engine.render(W))['valid']

def test_source_issue_and_grammar_are_separate(engine):
    result=engine.parse('HHRG-112-IF03-MState-W000413-20120125.pdf')
    assert result['found_in_source'] and result['valid']
    assert any('meeting-type-prefix-conflict' in x['issues'] for x in result['source_issues'])


def test_bundled_artifacts_are_minimal_and_coherent():
    from house_naming import __version__
    data = ROOT/'src/house_naming/data'
    assert {p.name for p in data.iterdir() if p.is_file()} == {
        'guide.json', 'guide.schema.json', 'record.schema.json', 'filename-lexical.schema.json'
    }
    guide = load_guide()
    assert guide['catalog_version'] == __version__
    assert guide['document']['version'] == '1.2.1'
    assert len(guide['source_nodes']) == 446
    assert 'section-46' not in guide['sections']
    assert all(node['page'] < 30 for node in guide['source_nodes'].values())
    assert 'members' not in guide and 'profiles' not in guide
    # legislativeStage remains the source vocabulary underlying the observed
    # stages, which add PIH without modifying that vocabulary.
    assert set(guide['field_types']) == {t for r in guide['patterns'].values() for t in r['fields'].values()} | {'legislativeStage'}


def test_bioguide_syntax_without_directory(engine):
    record = {'kind':'member-statement', 'congress':200, 'meetingType':'HMTG',
              'committeeCode':'ZZ', 'memberBioguideId':'Z999999',
              'meetingDate':'20260101', 'extension':'pdf'}
    name = engine.render(record)
    assert record in [m['record'] for m in engine.parse(name)['matches']]
    for invalid in ('999999', 'z999999', 'Z99999', 'Z9999999', '../Z999999'):
        with pytest.raises(NamingError):
            engine.render({**record, 'memberBioguideId':invalid})


def test_bundled_guide_copies():
    guide = load_guide()
    guide['patterns'].clear()
    assert len(load_guide()['patterns']) == 56


@pytest.mark.parametrize('payload,expected', [
    (json.dumps(W), 0),
    ('{"kind":"witness-statement","kind":"bill-numbered"}', 1),
    ('{"congress":NaN}', 1),
    ('{"congress":1e9999}', 1),
    (' ' * 65537, 2),
])
def test_cli_stdin(payload,expected):
    result = subprocess.run([sys.executable,'-m','house_naming','render','-'],
        input=payload, cwd=ROOT, capture_output=True, text=True,
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')})
    assert result.returncode == expected, result.stderr
    value = json.loads(result.stdout or result.stderr)
    if expected == 0:
        assert value['output'] == 'HHRG-112-ED-WState-IveyB-20110922.pdf'
        assert 'profile' not in value
    else:
        assert 'error' in value


def test_output_and_input_schema_are_closed(engine):
    with pytest.raises(NamingError):
        engine.render({**W, 'filename':'conflicting.pdf'})
    for record in CASES:
        result = engine.validate(record['input'])
        assert all(result[k] == v for k, v in record['input'].items())
    validator = Draft202012Validator(records_schema(load_guide()))
    assert not validator.is_valid({**W, 'filename':'conflicting.pdf'})
    assert not validator.is_valid({**W, 'extension':'exe'})
