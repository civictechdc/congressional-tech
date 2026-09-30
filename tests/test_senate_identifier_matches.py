"""Individually reviewed raw source pairs are the oracle, not generated matches."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from congress_api.matching.senate import match_identifiers

CASES=json.loads((Path(__file__).parent/'fixtures/senate_official/manual-matches.json').read_text())
HOST='indian.senate.gov'


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['expected_event_id']+'-'+case['page']['event']['title'][:28])
def test_manually_reviewed_abbreviated_and_split_agendas(case):
    page=deepcopy(case['page']);state={HOST:{'pages':{case['page_url']:page}}}
    assert match_identifiers([case['native']],state)==[(case['page_url'],case['expected_event_id'])]
    assert page['events']==[case['expected_event_id']]
    proof=page['match_details'][case['expected_event_id']]
    assert proof['event_date']==case['page']['event']['date']
    assert proof['native_api_url']==case['native']['_url']
    assert proof['native_title']==case['native']['title']
    assert proof['reason']
    assert match_identifiers([case['native']],state)==[]  # Replay preserves the association.


@pytest.mark.parametrize('mutation',['date','committee','ambiguous','no_identifiers','wrong_transcript_congress'])
def test_rejects_unestablished_associations(mutation):
    case=deepcopy(CASES[18])  # Named nominee with exact transcript, no bills.
    native=case['native'];page=case['page'];meetings=[native]
    if mutation=='date':native['date']='2019-07-25T18:30:00Z'
    elif mutation=='committee':native['committees']=[{'systemCode':'ssfi00'}]
    elif mutation=='ambiguous':meetings.append({**native,'eventId':'another'})
    elif mutation=='no_identifiers':page['documents']=[]
    elif mutation=='wrong_transcript_congress':native['congress']=117
    assert match_identifiers(meetings,{HOST:{'pages':{case['page_url']:page}}})==[]
    assert page['events']==[]


def test_business_and_hearing_pages_can_link_to_one_combined_native_event():
    pair=[deepcopy(CASES[index]) for index in [0,20]]
    pages={case['page_url']:case['page'] for case in pair}
    added=match_identifiers([pair[0]['native']],{HOST:{'pages':pages}})
    assert len(added)==2 and {event for _,event in added}=={'326642'}


def test_preserves_existing_supported_match_even_if_new_identifiers_point_elsewhere():
    case=deepcopy(CASES[0]);case['page']['events']=['previous']
    assert match_identifiers([case['native']],{HOST:{'pages':{case['page_url']:case['page']}}})==[]
    assert case['page']['events']==['previous']


def test_adapter_exposes_exact_identifier_match_evidence_inline():
    from datetime import UTC, datetime

    from committee_meeting.common import Ref
    from congress_api.adapters.common import AdapterContext
    from congress_api.adapters.senate import records
    case=deepcopy(CASES[18]);state={HOST:{'pages':{case['page_url']:case['page']}}}
    match_identifiers([case['native']],state)
    ctx=AdapterContext(now=datetime(2026,9,28,tzinfo=UTC),input_id='reviewed',provider='senate.committees',ids=lambda kind,key:kind+':'+key)
    lookup={(116,'senate','326221'):Ref(kind='meeting',id='retained-meeting')}
    rows=list(records(state,ctx,meetings=lookup))
    appearance,=[row for row in rows if row.kind=='appearance']
    assert appearance.meeting.id=='retained-meeting'
    assert appearance.provenance.method.name=='senate.records.match_identifiers'
    assert appearance.provenance.citations[0].selector=='/match_details/326221'
    source,=[row for row in rows if row.kind=='source_record']
    assert source.payload['match_details']['326221']['shared_transcript_packages']==['CHRG-116shrg37479']
