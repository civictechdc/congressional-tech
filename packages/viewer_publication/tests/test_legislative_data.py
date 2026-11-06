"""Native detail exports conserve source rows, keys, literals and unknown members."""
import os
import json
from pathlib import Path
import pyarrow.parquet as pq
from congress_api.retention.provenance import run_job,parquet_output
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import SPICY_SCHEMAS,_prepare_spicy_inputs
from viewer_publication.legislative_data import detail_exports
from archive_job_fixture import spicy_input,SPICY_GENERATIONS


def test_native_detail_exports_preserve_input_in_both_directions(tmp_path):
    actions=[dict(bill_id='119-hr-1',action_index=i,action_date='2025-09-09',action_time='12:30:00',action_text='Agreed by voice vote',stage='passed_house') for i in range(3)]
    votes=[dict(vote_id='119-senate-1-1',bill_id='119-s-1',congress='119',chamber='senate',session='1',roll_number='1',vote_day='2025-09-09',vote_date='September 9, 2025, 12:30 PM',yea=60,nay=40),dict(vote_id='119-senate-1-2',congress='119',chamber='senate',session='1',roll_number='2',vote_day='2025-09-09')]
    ballots=[dict(vote_id='119-senate-1-1',member_key='lis:S1',bioguide_id=None,position='Yea',position_normalized='yea',vote_date='September 9, 2025, 12:30 PM')]
    stated=spicy_input(spicy_bill_actions=actions,spicy_roll_call_votes=votes,spicy_member_votes=ballots,
        spicy_bill_vote_references=[dict(bill_id='119-hr-outside',congress='119',chamber='senate',session='1',roll_number='2',action_index=7,date='2025-09-09T12:30:00Z')])
    inputs,_=_prepare_spicy_inputs(tmp_path/'prepared',stated,True)
    exports=list(detail_exports(SPICY_GENERATIONS,SPICY_SCHEMAS))
    result=run_job(tmp_path/'job',NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[],outputs=[parquet_output(tmp_path,name,sql,order=keys) for name,sql,keys,_ in exports],queries=[])
    for name,rows in [('bill_actions',actions),('roll_call_votes',votes),('member_votes',ballots)]:
        released=pq.read_table(tmp_path/(name+'.parquet')).to_pylist()
        # Compare every declared column in both directions; no deduplication or profile filter.
        expected=[{field:row.get(field,[] if isinstance(kind,dict) and 'List' in kind else None) for field,kind in SPICY_SCHEMAS['spicy_'+name].items()} for row in rows]
        actual=[{field:row[field] for field in SPICY_SCHEMAS['spicy_'+name]} for row in released]
        stable=lambda values: sorted(json.dumps(row,sort_keys=True) for row in values)
        assert stable(actual)==stable(expected)
        assert all(row['source_generation']==SPICY_GENERATIONS['bill-family' if name=='bill_actions' else 'roll-call-votes'] for row in released)
        assert all(row['source_reference'].endswith('/'+name+'.parquet') for row in released)
        if name=='roll_call_votes':
            linked=next(row for row in released if row['vote_id']=='119-senate-1-2')
            assert linked['bill_id'] is None and linked['bill_references'][0]['bill_id']=='119-hr-outside'
            assert linked['bill_references'][0]['date']=='2025-09-09T12:30:00Z'


def test_published_outcomes_use_evidence_on_the_selected_meeting_date(tmp_path):
    from viewer_publication.archive_model import build_release
    from test_phase2_model_entities import _stage_raw_fixture
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    staged=_stage_raw_fixture(tmp_path,engine,[dict(url='https://fixture.test/report.html',format='html',data=b'<html><head><title>Report</title></head><body>'+b'Source evidence. '*100+b'</body></html>')])
    def record(digest,event,status,day,source='congress_gov',**fields):
        return dict(record_sha=digest*32,source=source,meetings=[dict(event_id=str(event),chamber='house',congress=119,
            meeting_date=day,title='Dated hearing',status=status,meeting_type='HHRG',**fields)])
    rows=[record('11',201,'Scheduled','2025-02-01'),
          record('22',202,'Canceled','2025-02-01',not_held=True),
          record('33',110924,'Postponed','2020-07-17',not_held=True),
          record('44',204,'Canceled','2025-02-01',not_held=True),
          record('55',204,'Scheduled','2025-02-08',source='house_xml')]
    build_release(**staged,meeting_records=rows,appearance_records=[],spicy_regs=spicy_input(),engine=engine,
        output=tmp_path/'release',scratch=tmp_path/'model')
    meetings={r['event_id']:r for r in pq.read_table(tmp_path/'release/meetings.parquet').to_pylist()}
    assert meetings[201]['outcome']=='unknown'
    assert meetings[202]['outcome']=='canceled' and meetings[202]['outcome_source_reference']=='22'*32
    assert meetings[110924]['outcome']=='held' and meetings[110924]['publisher_status']=='Postponed'
    assert meetings[204]['outcome']=='unknown'  # An old-date cancellation cannot cancel the new-date House record.
    assert {(o['status'],str(o['meeting_date'])) for o in meetings[204]['publisher_status_observations']}=={('Canceled','2025-02-01'),('Scheduled','2025-02-08')}


def test_native_ordering_refuses_duplicate_ballots_before_publication(tmp_path):
    import pytest
    from docspec_client.models import DocSpecFailure
    # The tie crosses the native writer's fixed batch boundary.
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sql="SELECT 'vote-1' AS vote_id,lpad(cast(value AS VARCHAR),8,'0') AS member_key FROM generate_series(1,8192) UNION ALL SELECT 'vote-1','00008192'"
    with pytest.raises(DocSpecFailure,match='export ordering keys are not unique'):
        run_job(tmp_path/'job',engine,inputs=[],steps=[],outputs=[parquet_output(tmp_path,'member_votes',sql,['vote_id','member_key'])],queries=[])
    assert not (tmp_path/'member_votes.parquet').exists()
