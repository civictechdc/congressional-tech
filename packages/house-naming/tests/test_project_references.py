"""Project-reference shapes preserve raw codes rather than inventing geography."""
import pytest
from house_naming import Engine

@pytest.fixture(scope='module')
def engine():
    return Engine()

def checked(engine, name):
    r=engine.extract(name)
    assert all(r[k]==v for k,v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in r['pieces'])==name
    matches=[m for m in r['observations'] if m['rule']=='gsa-project-reference']
    for m in matches:
        for f in m['fields']:
            assert m['start']<=f['start']<=f['end']<=m['end']
            assert name[f['start']:f['end']]==f['raw']
            assert f['code'] is None and f['label'] is None and f['context'] is None
            assert not f['candidates']
            assert 'no verified GSA association' in f['note']
    return r,matches

@pytest.mark.parametrize('name,prefix,identifier,suffix,year',[
 ('BILLS-116pih-PDC-0002-WA21.pdf','PDC','0002','WA','21'),
 ('BILLS-116pih-PCA-BSC-CA19.pdf','PCA','BSC','CA','19'),
 ('BILLS-116pih-PNY-03230282-NY20.pdf','PNY','03230282','NY','20'),
 ('BILLS-117pih-PMD-07781822-MD20.pdf','PMD','07781822','MD','20'),
 ('BILLS-117PVA-01-WA21ih.pdf','PVA','01','WA','21'),
 ('BILLS-116pih-PIL-0303-FY21.pdf','PIL','0303','FY','21'),
 ('pwa-00bn-bl18-blaine-wa.pdf','pwa','00bn','bl','18'),
 ('pdc-0689-wa19-washington-dc.pdf','pdc','0689','wa','19'),
 ('PDC-0002-WA21pdf.pdf','PDC','0002','WA','21'),
 ('PDC-0002-WA21&download=1','PDC','0002','WA','21'),
 ('PXX-UNKNOWN-ZZ00.pdf','PXX','UNKNOWN','ZZ','00'),
 ('BILLS-117PVA-20190101-WA21ih.pdf','PVA','20190101','WA','21'),
])
def test_reference_components_keep_exact_values(engine,name,prefix,identifier,suffix,year):
    r,matches=checked(engine,name)
    m,=matches
    assert {f['name']:f['raw'] for f in m['fields']}=={
        'reference_prefix_token':prefix,'reference_identifier_token':identifier,
        'reference_suffix_token':suffix,'reference_year_token':year,
    }
    assert not any(f['name'] in {'state','city','project_id','meeting_date'}
                   for obs in r['observations'] for f in obs['fields'])
    if name.startswith('BILLS-'):
        assert any(f['name']=='version_token' and f['code'] for obs in r['observations'] for f in obs['fields'])

@pytest.mark.parametrize('identifier',['20190101','111111','12345','HR123','S123','A000123','00000001','BSC'])
def test_middle_identifier_never_becomes_date_measure_or_person(engine,identifier):
    name=f'PDC-{identifier}-WA21.pdf'
    r,matches=checked(engine,name)
    m,=matches
    f=next(f for f in m['fields'] if f['name']=='reference_identifier_token')
    assert f['raw']==identifier
    assert not any(g['name'] in {'date_token','short_date_token','measure_number','bioguide_token'}
                   and g['start']<f['end'] and f['start']<g['end']
                   for obs in r['observations'] for g in obs['fields'])

@pytest.mark.parametrize('name',[
 'SPDC-0002-WA21.pdf','PDC-0002-WA211.pdf','PDC-0002-WA21st.pdf',
 'PDC-0002-WA.pdf','PDC-0002-W21.pdf','PDC-1-WA21.pdf',
 'PDC-00000000001-WA21.pdf','PDC--WA21.pdf','PDC-0002--WA21.pdf',
 'PDC 0002 WA21.pdf','PDC-00.02-WA21.pdf','XDC-0002-WA21.pdf',
 'Topic%20PDC-0002-WA21.pdf','PDC%200002-WA21.pdf',
 'HHRG-119-IF00-Wstate-PDC-0002-WA21-20250318.pdf',
])
def test_boundaries_and_person_slots(engine,name):
    _,matches=checked(engine,name)
    assert matches==[]

@pytest.mark.parametrize('name,year',[
 ('BILLS-116pih-PIL-0303-FY21.pdf','21'),
 ('BILLS-116pih-POH-0192-FY20.pdf','20'),
])
def test_literal_fiscal_year_wording_is_preserved(engine,name,year):
    r,matches=checked(engine,name)
    assert len(matches)==1
    assert any(m['rule']=='fiscal-year' and {f['name']:f['raw'] for f in m['fields']}=={
        'fiscal_marker':'FY','fiscal_year_token':year} for m in r['observations'])


def test_date_after_reference_keeps_its_own_role(engine):
    r,matches=checked(engine,'PDC-0002-WA21-2025-03-18.pdf')
    assert len(matches)==1
    assert any(f['raw']=='2025-03-18' and f['candidates']==['2025-03-18']
               for m in r['observations'] for f in m['fields'])


def test_slash_is_not_restored_from_external_metadata(engine):
    _,matches=checked(engine,'BILLS-116pih-POK-00460072-OK20.pdf')
    assert matches[0]['fields'][1]['raw']=='00460072'
