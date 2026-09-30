"""Heading results are distinct from unrelated topic words and verified outcomes."""
import pytest
from house_naming import Engine

RULES={'meeting-results-prefix','meeting-results-suffix'}
@pytest.fixture(scope='module')
def engine():return Engine()

def checked(engine,name):
 r=engine.extract(name)
 assert all(r[k]==v for k,v in engine.parse(name).items())
 assert ''.join(p['raw'] for p in r['pieces'])==name
 matches=[m for m in r['observations'] if m['rule'] in RULES]
 for m in matches:
  field,=m['fields']
  assert field['name']=='result_wording'
  assert name[field['start']:field['end']]==field['raw']
  assert m['start']<=field['start']<=field['end']<=m['end']
  assert field['code'] is None and field['label'] is None and field['context'] is None
  assert not field['candidates']
  assert 'No meeting occurrence' in field['note']
 return r,matches

@pytest.mark.parametrize('name,raw',[
 ('01.09.2020 Results of Executive Business Meeting.pdf','Results'),
 ('080119 Results of the Executive Business Meeting.pdf','Results'),
 ('Results Of The Open Executive Session Of June 9-10, 2021.pdf','Results'),
 ('results-of-committee-on-finance-open-executive-session-january-7-2020','results'),
 ('results-of-4-4-19-executive-business-meeting','results'),
 ('results-of-executive-business-meetings-10721','results'),
 ('results-of-executive-sessio-of-february-5-2019','results'),
 ('Results of Closed Executive Session.pdf','Results'),
 ('Results of Business Meeting.pdf','Results'),
 ('Results of EBM.pdf','Results'),
 ('Results of Committee on Finance Open Executive Session.pdf','Results'),
 ('results-of-executive-session-on-january-22-2021&download=1','results'),
 ('Results of Executive Sessionpdf.pdf','Results'),
])
def test_results_before_heading(engine,name,raw):
 _,matches=checked(engine,name)
 m,=matches
 assert m['rule']=='meeting-results-prefix'
 assert m['fields'][0]['raw']==raw

@pytest.mark.parametrize('name,raw',[
 ('2021-03-01_-_ebm_results.pdf','results'),
 ('2023-02-09 - EBM - Results.pdf','Results'),
 ('EBM Results - 2022-02-10.pdf','Results'),
 ('2025-01-29_ebm_resultspdf','results'),
 ('2024-06-13_-_ebm_-_results1.pdf','results'),
 ('executive-business-meeting-results-05-05-2022','results'),
 ('executive-business-results-for-february-10-2022','results'),
 ('Mark up 1.13.22 Results.pdf','Results'),
 ('Markup Results.pdf','Results'),
 ('Executive Session Results.pdf','Results'),
 ('Business Meeting Results.pdf','Results'),
 ('2025-06-12_ebm_results&download=1','results'),
])
def test_results_after_heading(engine,name,raw):
 _,matches=checked(engine,name)
 m,=matches
 assert m['rule']=='meeting-results-suffix'
 assert m['fields'][0]['raw']==raw

@pytest.mark.parametrize('name',[
 'k-12-subcommittee-hearing-on-choice-and-literacy-empowering-families-for-better-educational-results',
 'Survey Results.pdf','Research Results.pdf','Results of Election.pdf',
 'Results of Executive Summary.pdf','Results of Executive Sessionary.pdf',
 'Results of Executive Business Meetingship.pdf',
 'Business Meeting on Improving Survey Results.pdf',
 'Results of a study presented at an Executive Session.pdf',
 'Results of Committee on Finance report about climate trends Executive Session.pdf',
 # Only the observed Finance title is accepted as intervening committee text.
 'Results of Committee on Commerce Science and Transportation Open Executive Session.pdf',
 'Nonresults of Executive Session.pdf','Executive Business Meeting ResultsOriented.pdf',
 'ResultsofExecutiveSession.pdf','EBMResults.pdf',
 'Topic%20Results of Executive Session.pdf','Topic%20EBM Results.pdf',
 'HHRG-119-IF00-Wstate-EBM Results-20250318.pdf',
 'HHRG-119-IF00-Wstate-Results of Executive Session-20250318.pdf',
])
def test_nonheading_context_and_protected_slots(engine,name):
 _,matches=checked(engine,name)
 assert matches==[]


def test_existing_access_and_date_fields_stay(engine):
 r,matches=checked(engine,'Results of the Open Executive Session of May 24, 2018.pdf')
 assert len(matches)==1
 assert any(f['name']=='access_wording' and f['raw']=='Open' for m in r['observations'] for f in m['fields'])
 assert any(f['name']=='date_token' and f['candidates']==['2018-05-24'] for m in r['observations'] for f in m['fields'])
 assert not any(f['name'] in {'meeting_status','vote_result','vote_count'} for m in r['observations'] for f in m['fields'])


def test_intervening_date_is_not_captured_as_result(engine):
 r,matches=checked(engine,'Mark up 1.13.22 Results.pdf')
 assert matches[0]['fields'][0]['raw']=='Results'
 assert any(f['raw']=='1.13.22' and f['name']=='date_token' for m in r['observations'] for f in m['fields'])
