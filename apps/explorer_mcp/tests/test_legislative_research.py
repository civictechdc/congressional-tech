"""Consumer checks exercise source occurrence keys, ambiguity, coverage and paging."""
import shutil
import pytest
from conftest import CURRENT, manifest
from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import prepare
from congressional_explorer_mcp.models import ExplorerError


def test_actions_ballots_and_votes_are_actual_queryable_rows(reader):
    one = reader.get_bill_actions(dict(bill_id='119-HR-1',since='2025-02-01',until='2025-02-02',limit=1))
    two = reader.get_bill_actions(dict(bill_id='119-HR-1',since='2025-02-01',until='2025-02-02',limit=1,cursor=one['next_cursor']))
    assert [one['rows'][0]['action_index'],two['rows'][0]['action_index']] == [0,1]
    assert one['rows'][0]['action_time'] == '14:30:00'
    assert len(reader.get_roll_calls({})['rows']) == 2
    assert reader.get_roll_calls(dict(vote_id='119-h-outside'))['rows'][0]['bill_id'] is None
    assert reader.get_roll_calls(dict(bill_id='119-hr-linked'))['rows'][0]['vote_id']=='119-h-outside'
    ballots = reader.get_member_ballots(dict(vote_id='119-h-1',since='2025-02-01',until='2025-02-02'))['rows']
    assert {r['member_key'] for r in ballots} == {'bioguide:A000001','lis:S001'}
    assert next(r for r in ballots if r['member_key']=='lis:S001')['bioguide_id'] is None
    assert len(reader.query_sql(dict(sql='SELECT * FROM member_votes'))['rows']) == 2
    assert reader.get_bill_actions(dict(since='2025-02-02',until='2025-02-03'))['rows'] == []
    with pytest.raises(ExplorerError, match='until must be later'):
        reader.get_activity(dict(since='2025-02-02',until='2025-02-01'))


def test_activity_retains_events_and_resolves_supported_associations(reader):
    week = dict(since='2025-02-01',until='2025-02-08')
    result = reader.get_activity(week)
    assert len([r for r in result['rows'] if r['event_type']=='bill_action']) == 3
    assert len([r for r in result['rows'] if r['event_type']=='roll_call']) == 2
    assert all(r['date_precision']=='day' for r in result['rows'])
    filtered = reader.get_activity(dict(**week,committee='Energy and Commerce',topic='public transit'))
    assert filtered['resolved_filters'] == dict(committee='hsif00',topic='Public transit')
    assert all(r['subject_id'] != '119-h-outside' for r in filtered['rows'])
    page = reader.get_activity(dict(**week,limit=1))
    next_page = reader.get_activity(dict(**week,limit=1,cursor=page['next_cursor']))
    assert page['rows'] != next_page['rows']
    assert reader.get_activity(dict(since='2099-01-01',until='2099-01-02'))['rows'] == []


def test_activity_nomination_actions_are_not_bounded_by_received_dates(tmp_path,phase2):
    import asyncio
    import json
    import sys
    import pyarrow as pa
    import pyarrow.parquet as pq
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    root=tmp_path/'release';shutil.copytree(phase2.parent,root)
    table=pq.read_table(root/'nominations.parquet')
    activities=pa.list_(pa.struct([
        ('system_code',pa.string()),
        ('activities',pa.list_(pa.struct([('date',pa.string()),('name',pa.string())]))),
    ]))
    literal='2025-02-01T15:30:00Z'
    supplied=[dict(system_code='hsif00',activities=[
        dict(date=literal,name='Hearings By'),dict(date=literal,name='Hearings By')])]
    table=table.append_column('committee_activities',pa.array([supplied,None],type=activities))
    pq.write_table(table,root/'nominations.parquet')
    source=manifest(root)
    metadata=json.loads(source.read_text())
    next(item for item in metadata['files'] if item['name']=='nominations.parquet')['coverage'].update(
        date_start='2025-01-03',date_end='2025-01-03')
    source.write_text(json.dumps(metadata))
    data=tmp_path/'selected';prepare(data,source)

    async def run():
        transport=StdioTransport(sys.executable,['-m','congressional_explorer_mcp.cli','serve','--data-dir',str(data)],keep_alive=False)
        async with Client(transport) as client:
            query=dict(since='2025-02-01',until='2025-02-02',committee='hsif00',limit=1)
            rows=[]
            while True:
                result=(await client.call_tool('get_activity',{'query':query})).data
                coverage=result['coverage']
                assert coverage['interval_coverage']['nominations']=='event_date_bounds_unavailable'
                assert coverage['tables']['nominations'][0]['date_end']=='2025-01-03'
                rows.extend(row for row in result['rows'] if row['reference']['table']=='nominations')
                if not result['has_more']:break
                query=dict(query,cursor=result['next_cursor'])
            latest=[row for row in rows if row['event_type']=='nomination_latest_action']
            committee=[row for row in rows if row['event_type']=='nomination_committee_activity']
            assert len(latest)==len(committee)==2
            assert [row['event_date'] for row in latest]==['2025-02-01']*2
            assert [row['source_date'] for row in committee]==[literal]*2
            assert [row['event_key'] for row in committee]==['119-pn-730-2:1:1','119-pn-730-2:1:2']
            assert all(row['date_precision']=='day' and row['source_time'] is None for row in rows)
            empty=(await client.call_tool('get_activity',{'query':dict(since='2099-01-01',until='2099-01-02')})).data
            assert empty['rows']==[] and empty['coverage']['status']=='available'
            assert empty['coverage']['interval_coverage']['nominations']=='event_date_bounds_unavailable'
            received=(await client.call_tool('run_research_query',{'query':dict(name='pending_nominations',since='2025-02-01',until='2025-02-02')})).data
            assert received['rows']==[] and received['date_field']=='received'
            assert received['coverage']['interval_coverage']['nominations']=='outside_retained_dates'
    asyncio.run(run())


def test_named_queries_use_published_rows_and_recipes(reader):
    bills = reader.run_research_query(dict(name='recent_bills',since='2025-01-01',until='2025-01-04'))
    assert [r['bill_id'] for r in bills['rows']] == ['119-hr-1']
    assert bills['date_field'] == 'introduced' and bills['rows'][0]['reference']['table']=='bills'
    subject = reader.run_research_query(dict(name='legislation_by_subject',subject='public transit'))
    assert [r['bill_id'] for r in subject['rows']] == ['119-hr-1']
    assert subject['rows'][0]['publisher_url']=='https://www.congress.gov/bill/119th-congress/house-bill/1'
    assert reader.run_research_query(dict(name='pending_nominations'))['rows'] == []
    reader.db.execute("CREATE TEMP TABLE nominations_base AS SELECT * FROM nominations; CREATE OR REPLACE TEMP VIEW nominations AS SELECT * FROM nominations_base UNION ALL SELECT * REPLACE('119-pn-pending' AS nomination_id,'Received in the Senate and referred to committee for confirmation.' AS latest_action_text) FROM nominations_base LIMIT 3")
    pending=reader.run_research_query(dict(name='pending_nominations'))
    assert [row['nomination_id'] for row in pending['rows']]==['119-pn-pending']
    hearings = reader.run_research_query(dict(name='hearings_by_committee',committee='hsif00'))
    assert {r['event_id'] for r in hearings['rows']} == {118001,335321}
    assert reader.run_research_query(dict(name='recent_bills',since='2099-01-01'))['rows'] == []
    with pytest.raises(ExplorerError,match='Subject must identify one'):
        reader.run_research_query(dict(name='legislation_by_subject',subject='t'))
    reader.db.execute("CREATE TEMP TABLE committee_base AS SELECT * FROM committees; CREATE OR REPLACE TEMP VIEW committees AS SELECT * FROM committee_base UNION ALL SELECT * REPLACE('hsif01' AS system_code,'Energy and Commerce subcommittee' AS name) FROM committee_base")
    with pytest.raises(ExplorerError,match='Committee must identify one'):
        reader.run_research_query(dict(name='hearings_by_committee',committee='Commerce'))


def test_old_release_keeps_status_and_reports_missing_detail(tmp_path,phase2):
    root = tmp_path/'release';shutil.copytree(phase2.parent,root)
    for name in ['bill_actions','roll_call_votes','member_votes']:(root/(name+'.parquet')).unlink()
    r = Reader(prepare(tmp_path/'selected',manifest(root)))
    try:
        assert r.get_bill_actions({})['coverage']['status']=='unavailable'
        feed = r.get_activity(dict(since='2025-01-01'))
        assert 'bill_actions' in feed['coverage']['missing_tables']
        meeting = r.get_entity(dict(table='meetings',id=118001))['rows'][0]
        assert meeting['publisher_status']==meeting['status']
        assert meeting['outcome'] is None and meeting['outcome_evidence_available'] is False
    finally:r.close()


def test_new_research_tools_run_through_normal_stdio(tmp_path,phase2):
    import asyncio
    import sys
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    prepare(tmp_path,phase2,archive_origin='https://archive.example')
    async def run():
        transport=StdioTransport(sys.executable,['-m','congressional_explorer_mcp.cli','serve','--data-dir',str(tmp_path)],keep_alive=False)
        async with Client(transport) as client:
            names={tool.name for tool in await client.list_tools()}
            assert {'get_bill_actions','get_roll_calls','get_member_ballots','get_activity','run_research_query'} <= names
            for name,query,expected in [
                ('get_bill_actions',dict(bill_id='119-hr-1'),3),
                ('get_roll_calls',dict(vote_id='119-h-outside'),1),
                ('get_member_ballots',dict(vote_id='119-h-1'),2),
                ('get_activity',dict(since='2025-02-01',until='2025-02-08'),7),
                ('run_research_query',dict(name='legislation_by_subject',subject='Public transit'),1),
            ]:
                response=(await client.call_tool(name,{'query':query})).data
                assert len(response['rows'])==expected,(name,response)
    asyncio.run(run())


def test_explicit_meeting_projection_does_not_inject_outcome_fields(reader):
    result=reader.entity_rows(dict(rows=[dict(title='Projected title')]),'meetings',selected_fields=['title'])
    assert result['rows']==[dict(title='Projected title')]


def review_regression_release(tmp_path, phase2):
    """Retain the authentic three-action case and a vote with repeated supported links."""
    import json
    from pathlib import Path
    import pyarrow as pa
    import pyarrow.parquet as pq
    root=tmp_path/'release';shutil.copytree(phase2.parent,root)
    fixture=json.loads((Path(__file__).parent/'fixtures/bill-action-chronology.json').read_text())
    assert fixture['source_pin']['sha256']=='ded5f49598848192c847dd6e2b4ba0bd57b26209c0606a4d3d27f6dea32d78a9'
    rows=[dict(row,source_generation=fixture['source_generation'],source_reference=fixture['source_pin']['path']) for row in fixture['rows']]
    pq.write_table(pa.Table.from_pylist(rows),root/'bill_actions.parquet')
    table=pq.read_table(root/'roll_call_votes.parquet');votes=table.to_pylist()
    linked=next(row for row in votes if row['vote_id']=='119-h-1')
    linked['bill_id']=None
    linked['bill_references']=[dict(bill_id='119-hr-1',action_index=7),dict(bill_id='119-hr-1',action_index=8),dict(bill_id='119-hr-unavailable',action_index=9)]
    pq.write_table(pa.Table.from_pylist(votes,schema=table.schema),root/'roll_call_votes.parquet')
    return manifest(root),fixture


def test_authentic_local_action_times_order_detail_feed_and_pages(tmp_path,phase2):
    source,fixture=review_regression_release(tmp_path,phase2)
    reader=Reader(prepare(tmp_path/'selected',source))
    try:
        query=dict(bill_id='119-s-1055',since='2026-10-05',until='2026-10-06')
        rows=reader.get_bill_actions(query)['rows']
        assert [row['action_index'] for row in rows]==[1,0,2]
        assert [row['action_time'] for row in rows]==['16:31:57','16:50:14',None]
        original={row['action_index']:row for row in fixture['rows']}
        assert [{key:row[key] for key in original[row['action_index']]} for row in rows]==[original[1],original[0],original[2]]
        page=reader.get_bill_actions(dict(**query,limit=1));indices=[]
        while True:
            indices.extend(row['action_index'] for row in page['rows'])
            if not page['has_more']:break
            page=reader.get_bill_actions(dict(**query,limit=1,cursor=page['next_cursor']))
        assert indices==[1,0,2]
        feed=reader.get_activity(dict(since=query['since'],until=query['until']))
        assert [row['reference']['key']['action_index'] for row in feed['rows']]==[1,0,2]
        assert [row['source_time'] for row in feed['rows']]==['16:31:57','16:50:14',None]
        assert all(row['date_precision']=='day' for row in feed['rows'])
        assert 'No timezone is inferred' in reader.get_bill_actions(query)['ordering']
    finally:reader.close()


def test_activity_filters_follow_all_bill_references_without_multiplying_votes(tmp_path,phase2):
    source,_=review_regression_release(tmp_path,phase2)
    reader=Reader(prepare(tmp_path/'selected',source))
    try:
        window=dict(since='2025-02-01',until='2025-02-02')
        assert len([row for row in reader.get_activity(window)['rows'] if row['event_type']=='roll_call'])==2
        for filters in [dict(committee='hsif00'),dict(topic='Public transit'),dict(committee='hsif00',topic='Public transit')]:
            votes=[row for row in reader.get_activity(dict(**window,**filters))['rows'] if row['event_type']=='roll_call']
            assert len(votes)==1 and votes[0]['event_key']=='119-h-1'
            assert votes[0]['subject_id'] is None
        vote=reader.get_roll_calls(dict(bill_id='119-hr-1'))['rows'][0]
        assert vote['bill_id'] is None and len(vote['bill_references'])==3
        # Releases without bill_references retain the existing local floor-vote association.
        reader.db.execute('CREATE TEMP TABLE votes_base AS SELECT * FROM roll_call_votes; CREATE OR REPLACE TEMP VIEW roll_call_votes AS SELECT * EXCLUDE(bill_references) FROM votes_base')
        reader.schemas['roll_call_votes'].pop('bill_references')
        legacy=reader.get_activity(dict(**window,committee='hsif00',topic='Public transit'))
        assert [row['event_key'] for row in legacy['rows'] if row['event_type']=='roll_call']==['119-h-1']
    finally:reader.close()


def test_review_regressions_through_normal_stdio(tmp_path,phase2):
    import asyncio
    import sys
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    source,_=review_regression_release(tmp_path/'inputs',phase2)
    data=tmp_path/'selected';prepare(data,source)
    async def run():
        transport=StdioTransport(sys.executable,['-m','congressional_explorer_mcp.cli','serve','--data-dir',str(data)],keep_alive=False)
        async with Client(transport) as client:
            actions=(await client.call_tool('get_bill_actions',{'query':dict(bill_id='119-s-1055',since='2026-10-05',until='2026-10-06')})).data
            assert [row['action_index'] for row in actions['rows']]==[1,0,2]
            chronological=(await client.call_tool('get_activity',{'query':dict(since='2026-10-05',until='2026-10-06')})).data
            assert [row['source_time'] for row in chronological['rows']]==['16:31:57','16:50:14',None]
            linked=(await client.call_tool('get_activity',{'query':dict(since='2025-02-01',until='2025-02-02',committee='hsif00',topic='Public transit')})).data
            votes=[row for row in linked['rows'] if row['event_type']=='roll_call']
            assert len(votes)==1 and votes[0]['event_key']=='119-h-1' and votes[0]['subject_id'] is None
    asyncio.run(run())
