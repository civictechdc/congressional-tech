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
