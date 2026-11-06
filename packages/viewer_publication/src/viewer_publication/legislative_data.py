"""Lossless release copies of selected legislative detail, including nonlocal bills."""
from congress_api.retention.provenance import list_of, struct

ACTION_SCHEMA=dict(bill_id='Utf8',action_index='Int64',action_date='Utf8',action_time='Utf8',
    action_text='Utf8',action_code='Utf8',action_type='Utf8',source_system_name='Utf8',
    recorded_vote_count='Int64',is_latest_action='Boolean',stage='Utf8')
BALLOT_SCHEMA={name:'Utf8' for name in ('vote_id','congress','chamber','session','roll_number',
    'member_key','bioguide_id','lis_id','member_name','party','state','position','position_normalized','vote_date')}
VOTE_EXTRA=dict(vote_date='Utf8',present='Int64',not_voting='Int64',
    tallies=list_of(struct(choice='Utf8',count='Int64')),member_vote_count='Int64',tally_kind='Utf8',
    amendments=list_of(struct(**{key:'Utf8' for key in ('number','purpose','to_amendment_number',
        'to_amendment_to_amendment_number','to_document_number','to_document_short_title')})),
    **{key:'Utf8' for key in ('legis_num','clerk_body_element','vote_desc','vote_question_text',
        'vote_title','majority_requirement','modify_date','tie_breaker_by_whom','tie_breaker_vote')},
    party_totals=list_of(struct(**{'party':'Utf8',**{key:'Int64' for key in
        ('yea-total','nay-total','present-total','not-voting-total')}})))


def detail_exports(generations, schemas):
    """One copy per input row; native export ordering never removes repeated events."""
    for table,family,keys,dictionary in (
        ('bill_actions','bill-family',['bill_id','action_index'],['action_type','source_system_name','stage']),
        ('roll_call_votes','roll-call-votes',['vote_id'],['chamber','result','tally_kind']),
        ('member_votes','roll-call-votes',['vote_id','member_key'],['chamber','party','state','position','position_normalized'])):
        generation=generations[family]
        columns=','.join('v.'+name for name in schemas['spicy_'+table])
        source=f'generations/{family}/{generation}/{table}.parquet'
        if table == 'roll_call_votes':
            fields=('bill_id','action_index','congress','chamber','session','roll_number','date','full_action_name')
            reference_generation=generations['bill-family']
            reference_path=f'generations/bill-family/{reference_generation}/bill_vote_references.parquet'
            values=','.join("'"+field+"',r."+field for field in fields)
            values+=f",'source_generation','{reference_generation}','source_reference','{reference_path}'"
            sql=f"""WITH bill_references AS (
                SELECT cast(r.congress AS VARCHAR) AS congress,lower(r.chamber) AS chamber,
                  cast(r.session AS VARCHAR) AS session,cast(r.roll_number AS VARCHAR) AS roll_number,
                  array_agg(named_struct({values}) ORDER BY r.bill_id,r.action_index) AS bill_references
                FROM spicy_bill_vote_references r
                GROUP BY cast(r.congress AS VARCHAR),lower(r.chamber),cast(r.session AS VARCHAR),cast(r.roll_number AS VARCHAR)
              ) SELECT {columns},'{generation}' AS source_generation,'{source}' AS source_reference,r.bill_references
              FROM spicy_roll_call_votes v LEFT JOIN bill_references r
                ON cast(v.congress AS VARCHAR)=r.congress AND cast(v.session AS VARCHAR)=r.session
                AND cast(v.roll_number AS VARCHAR)=r.roll_number
                AND CASE lower(v.chamber) WHEN 'h' THEN 'house' WHEN 's' THEN 'senate' ELSE lower(v.chamber) END=r.chamber"""
        else:
            sql=f"SELECT {columns},'{generation}' AS source_generation,'{source}' AS source_reference FROM spicy_{table} v"
        yield (table,sql,keys,dictionary)
